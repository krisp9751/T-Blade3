"""The GUI's link to the model: loading, undoable edits, and T-Blade3 runs in the background.

Widgets never run T-Blade3 or change the model directly. They call the controller, which records
the edit on the undo stack, tells every view what changed (signals), and rebuilds the affected
row on a worker thread after a short pause. Results are delivered back on the GUI thread.
"""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QUndoCommand, QUndoStack

from ..errors import TBlade3Error
from ..model import BladeRow, Case

BUILD_DELAY_MS = 300


@dataclass
class _RowState:
    timer: QTimer
    running: bool = False
    pending: bool = False
    error: str = ""


class _SetValues(QUndoCommand):
    """Set one or more named parameters. Successive changes of the same parameters from one drag merge."""

    def __init__(self, controller: Controller, row_id: str, values: dict[str, float], merge_id: int):
        names = list(values)
        super().__init__(f"Change {names[0]}" + (f" and {len(names) - 1} more" if len(names) > 1 else ""))
        self.c, self.row_id = controller, row_id
        row = controller.case.rows[row_id]
        self.old = {name: row.get(name) for name in names}
        self.new = dict(values)
        self.merge_id = merge_id

    def id(self) -> int:
        return self.merge_id

    def mergeWith(self, other: QUndoCommand) -> bool:
        if not isinstance(other, _SetValues) or other.row_id != self.row_id or set(other.new) != set(self.new):
            return False
        self.new = other.new
        return True

    def _apply(self, values: dict[str, float]) -> None:
        row = self.c.case.rows[self.row_id]
        for name, value in values.items():
            row.set(name, value)
        self.c._after_edit(self.row_id, structural=False)

    def redo(self) -> None:
        self._apply(self.new)

    def undo(self) -> None:
        self._apply(self.old)


class _Edit(QUndoCommand):
    """Any other edit, given as a pair of functions that apply and revert it."""

    def __init__(self, controller: Controller, row_id: str, text: str, do: Callable[[], None],
                 undo: Callable[[], None]):
        super().__init__(text)
        self.c, self.row_id, self._do, self._undo = controller, row_id, do, undo

    def redo(self) -> None:
        self._do()
        self.c._after_edit(self.row_id, structural=True)

    def undo(self) -> None:
        self._undo()
        self.c._after_edit(self.row_id, structural=True)


class _SetDesignVariable(QUndoCommand):
    """Flag or unflag a parameter as a design variable, or change its bounds. Does not rebuild."""

    def __init__(self, controller: Controller, row_id: str, name: str, new: tuple[bool, float | None, float | None]):
        super().__init__(f"{'Flag' if new[0] else 'Unflag'} {name} as a design variable")
        self.c, self.row_id, self.name, self.new = controller, row_id, name, new
        p = controller.case.rows[row_id].parameters[name]
        self.old = (p.is_dv, p.lower, p.upper)
        if self.old[0] and new[0]:
            self.setText(f"Change the bounds of {name}")

    def _apply(self, state: tuple[bool, float | None, float | None]) -> None:
        p = self.c.case.rows[self.row_id].parameters[self.name]     # looked up now: parameters may be rebuilt
        p.is_dv, p.lower, p.upper = state
        self.c.designVariablesChanged.emit()

    def redo(self) -> None:
        self._apply(self.new)

    def undo(self) -> None:
        self._apply(self.old)


class Controller(QObject):
    caseChanged = Signal()                  # a case was loaded or closed
    designVariablesChanged = Signal()       # a design-variable flag or bound changed
    inputsChanged = Signal(str)             # row id: values or table sizes changed
    buildStarted = Signal(str)              # row id
    buildFinished = Signal(str)             # row id: row.geometry is new
    buildFailed = Signal(str, str)          # row id, message with log
    sensitivityReady = Signal(str, str)     # row id, parameter name: row.dxyz(name) is available
    sensitivityFailed = Signal(str, str, str)   # row id, parameter name, message
    message = Signal(str)                   # short status text

    _jobDone = Signal(object)               # internal: (callback, result) from a worker thread

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.case: Case | None = None
        self.undo_stack = QUndoStack(self)
        self.auto_run = True
        self._rows: dict[str, _RowState] = {}
        self._pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="tb3-build")
        self._merge_id = 1
        self._jobDone.connect(self._deliver)

    # -- case -------------------------------------------------------------------------------
    def load(self, path: str | Path) -> None:
        case = Case.load(path)              # raises on unreadable input; the caller reports it
        self.close_case()
        self.case = case
        for rid in case.rows:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda rid=rid: self._start_build(rid))
            self._rows[rid] = _RowState(timer)
        self.caseChanged.emit()
        self.message.emit(f"Loaded {case.folder}")
        self.build_all()

    def save(self, folder: str | Path | None = None) -> None:
        if self.case is not None:
            self.message.emit(f"Saved to {self.case.save(folder)}")
            self.undo_stack.setClean()

    def close_case(self) -> None:
        for state in self._rows.values():
            state.timer.stop()
        self._rows.clear()
        self.undo_stack.clear()
        if self.case is not None:
            case, self.case = self.case, None
            self._pool.submit(case.close)   # engines may still be finishing a run

    def shutdown(self) -> None:
        self.close_case()
        self._pool.shutdown(wait=False, cancel_futures=True)

    def row(self, row_id: str) -> BladeRow:
        return self.case.rows[row_id]

    def is_building(self, row_id: str) -> bool:
        state = self._rows.get(row_id)
        return bool(state and (state.running or state.timer.isActive()))

    def error(self, row_id: str) -> str:
        """Message of the last failed build of the row, empty if its last build succeeded."""
        state = self._rows.get(row_id)
        return state.error if state else ""

    # -- edits ------------------------------------------------------------------------------
    def begin_drag(self) -> None:
        """Call when a mouse drag starts: the value changes that follow merge into one undo step."""
        self._merge_id += 1

    def set_value(self, row_id: str, name: str, value: float, drag: bool = False) -> None:
        """Set a named parameter (undoable). With ``drag`` the change merges with the previous one."""
        self.set_values(row_id, {name: value}, drag)

    def set_values(self, row_id: str, values: dict[str, float], drag: bool = False) -> None:
        """Set several named parameters of a row as one undo step."""
        row = self.case.rows[row_id]
        if all(row.get(name) == value for name, value in values.items()):
            return
        if not drag:
            self._merge_id += 1
        self.undo_stack.push(_SetValues(self, row_id, values, self._merge_id))

    def edit(self, row_id: str, text: str, do: Callable[[], None], undo: Callable[[], None]) -> None:
        """Apply any other edit (switches, text, adding or removing table rows), undoable."""
        self.undo_stack.push(_Edit(self, row_id, text, do, undo))

    def set_attribute(self, row_id: str, obj, attr: str, value, text: str | None = None) -> None:
        """Set ``obj.attr`` (e.g. a switch of the row's main input), undoable."""
        old = getattr(obj, attr)
        if old == value:
            return
        self.edit(row_id, text or f"Change {attr}", lambda: setattr(obj, attr, value),
                  lambda: setattr(obj, attr, old))

    def set_design_variable(self, row_id: str, name: str, is_dv: bool, lower: float | None = None,
                            upper: float | None = None) -> None:
        """Flag (with optional bounds) or unflag a parameter as a design variable, undoable."""
        p = self.case.rows[row_id].parameters[name]
        if p.integer and is_dv:
            raise ValueError(f"{name!r} is an integer and cannot be a design variable")
        new = (True, lower, upper) if is_dv else (False, None, None)
        if new != (p.is_dv, p.lower, p.upper):
            self.undo_stack.push(_SetDesignVariable(self, row_id, name, new))

    def _after_edit(self, row_id: str, structural: bool) -> None:
        if structural:
            self.case.rows[row_id].invalidate_parameters()
        self.inputsChanged.emit(row_id)
        if self.auto_run:
            self.request_build(row_id)

    # -- builds -----------------------------------------------------------------------------
    def request_build(self, row_id: str, delay_ms: int = BUILD_DELAY_MS) -> None:
        """Rebuild the row after ``delay_ms`` without further edits."""
        state = self._rows.get(row_id)
        if state is not None:
            state.timer.start(delay_ms)

    def build_all(self) -> None:
        for rid in self._rows:
            self.request_build(rid, 0)

    def _start_build(self, row_id: str) -> None:
        state = self._rows.get(row_id)
        if state is None:
            return
        if state.running:
            state.pending = True            # run again when the current build ends
            return
        row = self.case.rows[row_id]
        try:
            files = row.files()
        except Exception as exc:            # values that cannot be written as an input file
            self._build_failed(row_id, f"Cannot write the input files: {exc}")
            return
        if row.cached_geometry(files) is not None:
            state.error = ""
            self.buildFinished.emit(row_id)
            return
        state.running = True
        self.buildStarted.emit(row_id)
        case, engine, main = self.case, row.engine, row.main_name

        def job():
            try:
                return engine.run(files, main, derivatives=True)
            except Exception as exc:
                return exc

        def done(result):
            if self.case is not case:       # another case was loaded meanwhile
                return
            state.running = False
            if isinstance(result, Exception):
                self._build_failed(row_id, str(result))
            else:
                row.adopt(result, files)
                state.error = ""
                self.buildFinished.emit(row_id)
            if state.pending:
                state.pending = False
                self._start_build(row_id)

        self._submit(job, done)

    def _build_failed(self, row_id: str, text: str) -> None:
        self._rows[row_id].error = text
        self.buildFailed.emit(row_id, text)

    # -- sensitivities ----------------------------------------------------------------------
    def request_sensitivity(self, row_id: str, name: str) -> None:
        """Make ``row.dxyz(name)`` available: at once if analytic, else by two background runs."""
        row = self.case.rows[row_id]
        geo = row.geometry
        if geo is None or not row.is_current:
            self.sensitivityFailed.emit(row_id, name, "The geometry is not up to date yet")
            return
        p = row.parameters[name]
        if (p.deriv is not None and geo.derivatives is not None and p.deriv in geo.derivatives.xyz) \
                or name in row._fd_cache:
            self.sensitivityReady.emit(row_id, name)
            return
        try:
            plus, minus, h = row.fd_files(name)
        except TBlade3Error as exc:
            self.sensitivityFailed.emit(row_id, name, str(exc))
            return
        case, engine, main = self.case, row.engine, row.main_name

        def job():
            try:
                a = engine.run(plus, main, derivatives=False).sections
                b = engine.run(minus, main, derivatives=False).sections
                return (a - b) / (2.0 * h)
            except Exception as exc:
                return exc

        def done(result):
            if self.case is not case or row.geometry is not geo:
                return
            if isinstance(result, Exception):
                self.sensitivityFailed.emit(row_id, name, str(result))
            else:
                row.store_fd(name, result)
                self.sensitivityReady.emit(row_id, name)

        self.message.emit(f"Finite difference for {name} (2 runs)")
        self._submit(job, done)

    # -- thread plumbing --------------------------------------------------------------------
    def _submit(self, job: Callable[[], object], done: Callable[[object], None]) -> None:
        self._pool.submit(lambda: self._jobDone.emit((done, job())))

    def _deliver(self, payload) -> None:    # runs on the GUI thread
        done, result = payload
        done(result)
