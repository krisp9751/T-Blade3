"""Main window: blade-row list, editor tabs, the 3D view and the log."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QDockWidget, QFileDialog, QLabel, QListWidget, QListWidgetItem, QMainWindow,
                               QMessageBox, QPlainTextEdit, QSplitter, QTabWidget, QToolBar, QVBoxLayout, QWidget)

from .backend import row_surfaces
from .controller import Controller
from .tabs.base import RowTab
from .tabs.flowpath import FlowPathTab
from .view3d import View3D


def tab_classes() -> list[type[RowTab]]:
    """The editor tabs, in display order. Tabs that are not written yet are simply absent."""
    classes: list[type[RowTab]] = []
    for module, name in (("rowsetup", "RowSetupTab"), ("flowpath", "FlowPathTab"), ("sections", "SectionsTab"),
                         ("spanwise", "SpanwiseTab"), ("camber", "CamberTab"), ("thickness", "ThicknessTab"),
                         ("stacking", "StackingTab"), ("airfoils", "AirfoilsTab"),
                         ("sensitivities", "SensitivitiesTab"), ("designvars", "DesignVariablesTab")):
        try:
            mod = __import__(f"tblade3.gui.tabs.{module}", fromlist=[name])
        except ModuleNotFoundError as exc:
            if exc.name != f"tblade3.gui.tabs.{module}":
                raise
            continue
        classes.append(getattr(mod, name))
    return classes or [FlowPathTab]


class MainWindow(QMainWindow):
    def __init__(self, controller: Controller | None = None):
        super().__init__()
        self.controller = controller or Controller(self)
        self.setWindowTitle("T-Blade3")
        self.resize(1600, 950)
        self.all_blades = False
        self._warnings: dict[str, str] = {}      # last warnings logged per row, to avoid repeating them

        # -- widgets --------------------------------------------------------------------------
        self.row_list = QListWidget()
        self.row_list.setMaximumWidth(220)
        self.row_list.currentItemChanged.connect(lambda *_: self._row_selected())
        self.tabs = QTabWidget()
        self.tab_widgets: list[RowTab] = [cls(self.controller) for cls in tab_classes()]
        for tab in self.tab_widgets:
            self.tabs.addTab(tab, tab.title)
            if hasattr(tab, "attach_view"):
                pass                        # attached below, once the 3D view exists
        self.view = View3D()
        for tab in self.tab_widgets:
            if hasattr(tab, "attach_view"):
                tab.attach_view(self.view)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(6, 6, 0, 6)
        left_layout.addWidget(QLabel("Blade rows"))
        left_layout.addWidget(self.row_list)
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(self.tabs)
        splitter.addWidget(self.view)
        splitter.setSizes([150, 930, 520])     # wide enough for all ten tab titles
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 2)
        self.setCentralWidget(splitter)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        dock = QDockWidget("Log", self)
        dock.setObjectName("log")
        dock.setWidget(self.log)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)
        self.resizeDocks([dock], [140], Qt.Vertical)
        self.status = QLabel("No case loaded")
        self.statusBar().addPermanentWidget(self.status)

        self._make_actions()

        c = self.controller
        c.caseChanged.connect(self._case_changed)
        c.inputsChanged.connect(self._inputs_changed)
        c.buildStarted.connect(lambda rid: self._update_status())
        c.buildFinished.connect(self._build_finished)
        c.buildFailed.connect(self._build_failed)
        c.message.connect(self._log)
        c.undo_stack.cleanChanged.connect(lambda *_: self._update_title())

    # -- actions ----------------------------------------------------------------------------
    def _make_actions(self) -> None:
        bar = QToolBar("Main")
        bar.setObjectName("main")
        bar.setMovable(False)
        self.addToolBar(bar)
        menu_file = self.menuBar().addMenu("&File")
        menu_edit = self.menuBar().addMenu("&Edit")
        menu_view = self.menuBar().addMenu("&View")

        def action(text, slot, shortcut=None, checkable=False, checked=False, menus=(), toolbar=True):
            a = QAction(text, self)
            if shortcut:
                a.setShortcut(shortcut)
            a.setCheckable(checkable)
            a.setChecked(checked)
            a.triggered.connect(slot)
            for m in menus:
                m.addAction(a)
            if toolbar:
                bar.addAction(a)
            return a

        action("Open…", self.open_dialog, QKeySequence.Open, menus=[menu_file])
        action("Save", lambda: self.save(), QKeySequence.Save, menus=[menu_file])
        action("Save as…", self.save_as_dialog, QKeySequence.SaveAs, menus=[menu_file], toolbar=False)
        bar.addSeparator()
        undo = self.controller.undo_stack.createUndoAction(self, "Undo")
        undo.setShortcut(QKeySequence.Undo)
        redo = self.controller.undo_stack.createRedoAction(self, "Redo")
        redo.setShortcut(QKeySequence.Redo)
        for a in (undo, redo):
            menu_edit.addAction(a)
            bar.addAction(a)
        bar.addSeparator()
        action("Run", self.controller.build_all, "F5", menus=[menu_edit])
        self.auto_action = action("Run on edit", self._set_auto_run, checkable=True, checked=True, menus=[menu_edit])
        bar.addSeparator()
        self.all_blades_action = action("All blades", self._set_all_blades, checkable=True, menus=[menu_view])
        self.hub_action = action("Hub", lambda on: self.view.set_visibility(hub=on), checkable=True, checked=True,
                                 menus=[menu_view])
        self.casing_action = action("Casing", lambda on: self.view.set_visibility(casing=on), checkable=True,
                                    menus=[menu_view])
        action("Reset view", self.view.reset_camera, menus=[menu_view])

    def _set_auto_run(self, on: bool) -> None:
        self.controller.auto_run = on
        if on:
            self.controller.build_all()

    def _set_all_blades(self, on: bool) -> None:
        self.all_blades = on
        for rid in (self.controller.case.rows if self.controller.case else []):
            self._show_row_geometry(rid)
        self.view.reset_camera()

    # -- files ------------------------------------------------------------------------------
    def open_dialog(self) -> None:
        start = str(self.controller.case.folder) if self.controller.case and self.controller.case.folder else ""
        path, _ = QFileDialog.getOpenFileName(self, "Open a T-Blade3 case: pick any 3dbgbinput file of it", start,
                                              "T-Blade3 main input (3dbgbinput.*.dat);;All files (*)")
        if path:
            self.open_case(Path(path).parent)

    def open_case(self, path: str | Path) -> bool:
        if not self._confirm_discard():
            return False
        try:
            self.controller.load(path)
        except Exception as exc:
            self._log(f"Could not open {path}: {exc}")
            QMessageBox.critical(self, "T-Blade3", f"Could not open {path}:\n\n{exc}")
            return False
        return True

    def save(self, folder: str | Path | None = None) -> None:
        if self.controller.case is None:
            return
        try:
            self.controller.save(folder)
        except Exception as exc:
            QMessageBox.critical(self, "T-Blade3", f"Could not save:\n\n{exc}")

    def save_as_dialog(self) -> None:
        if self.controller.case is None:
            return
        folder = QFileDialog.getExistingDirectory(self, "Save the case into a folder")
        if folder:
            self.save(folder)
            self._update_title()

    def _confirm_discard(self) -> bool:
        if self.controller.case is None or self.controller.undo_stack.isClean():
            return True
        answer = QMessageBox.question(self, "T-Blade3", "Discard the unsaved changes?",
                                      QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Cancel)
        return answer == QMessageBox.Discard

    # -- controller signals -----------------------------------------------------------------
    @property
    def current_row(self) -> str | None:
        item = self.row_list.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def _case_changed(self) -> None:
        self.view.clear()
        self._warnings.clear()
        self.row_list.blockSignals(True)
        self.row_list.clear()
        case = self.controller.case
        for rid, row in (case.rows.items() if case else []):
            item = QListWidgetItem(f"Row {rid}: {row.main.casename}")
            item.setData(Qt.UserRole, rid)
            self.row_list.addItem(item)
        self.row_list.blockSignals(False)
        if self.row_list.count():
            self.row_list.setCurrentRow(0)
        else:
            self._row_selected()
        self._update_title()
        self._update_status()

    def _row_selected(self) -> None:
        rid = self.current_row
        for tab in self.tab_widgets:
            tab.set_row(rid)
        case = self.controller.case
        self.view.set_dimmed({r for r in case.rows if r != rid} if case else set())

    def _inputs_changed(self, row_id: str) -> None:
        for tab in self.tab_widgets:
            if row_id == tab.row_id or getattr(tab, "shows_all_rows", False):
                tab.notify_inputs()
        item = self._item(row_id)
        if item is not None:
            item.setText(f"Row {row_id}: {self.controller.row(row_id).main.casename}")
        self._update_status()

    def _build_finished(self, row_id: str) -> None:
        self._show_row_geometry(row_id)
        for tab in self.tab_widgets:
            if row_id == tab.row_id:
                tab.notify_geometry()
        geo = self.controller.row(row_id).geometry
        warnings = geo.warnings.strip() if geo is not None else ""
        if warnings != self._warnings.get(row_id, ""):
            self._warnings[row_id] = warnings
            lines = [line.strip() for line in warnings.splitlines() if line.strip()]
            self._log(f"Row {row_id}: " + (" | ".join(lines[:3]) if lines else "built without warnings"))
        self._update_status()

    def _build_failed(self, row_id: str, text: str) -> None:
        self._log(f"Row {row_id}: T-Blade3 failed. The last good geometry stays on screen.\n{text}")
        self._update_status()

    def _show_row_geometry(self, row_id: str) -> None:
        row = self.controller.row(row_id)
        if row.geometry is None:
            return
        surfaces, lines = row_surfaces(row.geometry, row.main.n_blades, self.all_blades)
        self.view.set_surfaces(row_id, surfaces, lines)

    # -- small things -----------------------------------------------------------------------
    def _item(self, row_id: str) -> QListWidgetItem | None:
        for i in range(self.row_list.count()):
            if self.row_list.item(i).data(Qt.UserRole) == row_id:
                return self.row_list.item(i)
        return None

    def _log(self, text: str) -> None:
        self.log.appendPlainText(text)
        self.statusBar().showMessage(text.splitlines()[0], 5000)

    def _update_title(self) -> None:
        case = self.controller.case
        name = str(case.folder) if case and case.folder else "no case"
        dirty = "" if self.controller.undo_stack.isClean() else " *"
        self.setWindowTitle(f"T-Blade3: {name}{dirty}")

    def _update_status(self) -> None:
        case = self.controller.case
        if case is None:
            self.status.setText("No case loaded")
            return
        parts = []
        for rid in case.rows:
            if self.controller.is_building(rid):
                state = "building…"
            elif self.controller.error(rid):
                state = "failed"
            elif case.rows[rid].geometry is None:
                state = "not built"
            else:
                state = "up to date" if case.rows[rid].is_current else "edited"
            parts.append(f"Row {rid}: {state}")
        self.status.setText("   ".join(parts))

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.PaletteChange, QEvent.ThemeChange):
            self.view.apply_theme()
            for tab in self.tab_widgets:
                tab.apply_theme()

    def closeEvent(self, event) -> None:
        if not self._confirm_discard():
            event.ignore()
            return
        self.controller.shutdown()
        self.view.close()
        super().closeEvent(event)
