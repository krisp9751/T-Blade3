"""Reusable input widgets bound to the controller."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from .controller import Controller


def format_number(value: float) -> str:
    return f"{value:.10g}"


class ParamTable(QWidget):
    """A table of named parameters: cell (i, column) edits ``<prefix>[i+1]`` of the current row.

    ``columns`` is a list of (header, parameter prefix), e.g. [("span", "sweep.span"), ("delta_m", "sweep")].
    Rows follow the number of parameters that exist. ``on_add`` / ``on_remove`` (optional) are called
    with the selected row index to insert a row after it or delete it; they must make the change
    through ``controller.edit`` so it can be undone.
    """

    rowSelected = Signal(int)

    def __init__(self, controller: Controller, columns: list[tuple[str, str]],
                 on_add: Callable[[int], None] | None = None, on_remove: Callable[[int], None] | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.controller = controller
        self.columns = columns
        self.row_id: str | None = None
        self._filling = False
        self._read_only: set[int] = set()
        self.table = QTableWidget(0, len(columns), self)
        self.table.setHorizontalHeaderLabels([header for header, _ in columns])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(22)
        self.table.setSelectionMode(QAbstractItemView.ContiguousSelection)
        self.table.itemChanged.connect(self._item_changed)
        self.table.currentCellChanged.connect(lambda r, *_: self.rowSelected.emit(r))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)
        if on_add or on_remove:
            buttons = QHBoxLayout()
            if on_add:
                add = QPushButton("Add point")
                add.clicked.connect(lambda: on_add(max(self.table.currentRow(), 0)))
                buttons.addWidget(add)
            if on_remove:
                remove = QPushButton("Remove point")
                remove.clicked.connect(lambda: self.table.currentRow() >= 0 and on_remove(self.table.currentRow()))
                buttons.addWidget(remove)
            buttons.addStretch(1)
            layout.addLayout(buttons)

    def set_columns(self, columns: list[tuple[str, str]]) -> None:
        self.columns = columns
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels([header for header, _ in columns])
        self.refresh()

    def set_row(self, row_id: str | None) -> None:
        self.row_id = row_id
        self.refresh()

    def set_read_only_columns(self, columns: set[int]) -> None:
        """Show these columns greyed and not editable (e.g. values a switch makes unused)."""
        if set(columns) != self._read_only:
            self._read_only = set(columns)
            self.refresh()

    def _count(self, params: dict) -> int:
        n = 0
        while self.columns and f"{self.columns[0][1]}[{n + 1}]" in params:
            n += 1
        return n

    def refresh(self) -> None:
        """Show the current values (call after any change of the inputs)."""
        self._filling = True
        try:
            case = self.controller.case
            if case is None or self.row_id not in case.rows:
                self.table.setRowCount(0)
                return
            params = case.rows[self.row_id].parameters
            n = self._count(params)
            self.table.setRowCount(n)
            for i in range(n):
                for j, (_, prefix) in enumerate(self.columns):
                    p = params.get(f"{prefix}[{i + 1}]")
                    text = "" if p is None else format_number(p.value)
                    item = self.table.item(i, j)
                    if item is None:
                        item = QTableWidgetItem(text)
                        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                        self.table.setItem(i, j, item)
                    elif item.text() != text:
                        item.setText(text)
                    editable = p is not None and j not in self._read_only
                    item.setFlags(item.flags() | Qt.ItemIsEditable if editable else item.flags() & ~Qt.ItemIsEditable)
                    item.setForeground(self.palette().placeholderText() if j in self._read_only else
                                       self.palette().text())
        finally:
            self._filling = False

    def _item_changed(self, item: QTableWidgetItem) -> None:
        if self._filling or self.row_id is None:
            return
        name = f"{self.columns[item.column()][1]}[{item.row() + 1}]"
        try:
            value = float(item.text())
        except ValueError:
            self.refresh()                  # not a number: restore the stored value
            return
        self.controller.set_value(self.row_id, name, value)

    def select_row(self, index: int) -> None:
        if 0 <= index < self.table.rowCount():
            self.table.setCurrentCell(index, max(self.table.currentColumn(), 0))


class ValueEdit(QLineEdit):
    """A line edit for one named parameter of the current row."""

    def __init__(self, controller: Controller, name: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.controller, self.name = controller, name
        self.row_id: str | None = None
        self.setAlignment(Qt.AlignRight)
        self.editingFinished.connect(self._commit)

    def set_row(self, row_id: str | None) -> None:
        self.row_id = row_id
        self.refresh()

    def refresh(self) -> None:
        case = self.controller.case
        p = case.rows[self.row_id].parameters.get(self.name) if case and self.row_id in case.rows else None
        self.setEnabled(p is not None)
        self.setText("" if p is None else format_number(p.value))

    def _commit(self) -> None:
        if self.row_id is None or not self.isEnabled():
            return
        try:
            value = float(self.text())
        except ValueError:
            self.refresh()
            return
        self.controller.set_value(self.row_id, self.name, value)


class ChoiceBox(QComboBox):
    """A combo box for an attribute with a fixed set of values, e.g. a switch of the main input.

    ``choices`` maps stored value -> label. ``target`` returns the object holding the attribute for
    a blade row (default: the row's main input). ``commit(row_id, value)`` (optional) makes the
    change instead of a plain ``set_attribute``, e.g. to add data the new value needs or to refuse
    it; the box then shows whatever the model holds afterwards. ``locked`` keeps the box disabled.
    """

    def __init__(self, controller: Controller, attr: str, choices: dict, text: str,
                 target: Callable | None = None, commit: Callable[[str, object], None] | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.controller, self.attr, self.text = controller, attr, text
        self.target = target or (lambda row: row.main)
        self.commit = commit
        self.locked = False
        self.row_id: str | None = None
        self._filling = False
        for value, label in choices.items():
            self.addItem(label, value)
        self.currentIndexChanged.connect(self._commit)

    def set_row(self, row_id: str | None) -> None:
        self.row_id = row_id
        self.refresh()

    def refresh(self) -> None:
        case = self.controller.case
        self._filling = True
        try:
            if case is None or self.row_id not in case.rows:
                self.setEnabled(False)
                return
            self.setEnabled(not self.locked)
            value = getattr(self.target(case.rows[self.row_id]), self.attr)
            index = self.findData(value)
            if index < 0:                   # a value outside the known set: show it as it is
                self.addItem(str(value), value)
                index = self.count() - 1
            self.setCurrentIndex(index)
        finally:
            self._filling = False

    def _commit(self) -> None:
        if self._filling or self.row_id is None:
            return
        if self.commit is not None:
            self.commit(self.row_id, self.currentData())
            self.refresh()                  # shows the old value again if the change was refused
            return
        obj = self.target(self.controller.case.rows[self.row_id])
        self.controller.set_attribute(self.row_id, obj, self.attr, self.currentData(), self.text)


def decode_stacking_axis(stack: int) -> tuple[int, int]:
    """Stacking axis number -> (% of chord, % above the meanline), as stacking() in funcNsubs.f90 decodes it.

    The thousands are the chordwise position (200 = area centroid), the remainder the position above
    (+) or below (-) the meanline; a negative number makes the remainder negative.
    """
    u = abs(int(stack)) // 1000
    return u, (int(stack) - u * 1000) if stack >= 0 else (int(stack) + u * 1000)


def encode_stacking_axis(u: int, v: int) -> int:
    return u * 1000 + v if v >= 0 else -(u * 1000 - v)


class StackingAxisEdit(QWidget):
    """The stacking axis of a row (main input ``stacking_axis``) as chord and meanline positions."""

    def __init__(self, controller: Controller, parent: QWidget | None = None):
        super().__init__(parent)
        self.controller = controller
        self.row_id: str | None = None
        self._filling = False
        self.u_spin = QSpinBox()
        self.u_spin.setRange(0, 100)
        self.u_spin.setSuffix(" % of chord")
        self.v_spin = QSpinBox()
        self.v_spin.setRange(-100, 100)
        self.v_spin.setSuffix(" % above meanline")
        self.centroid = QCheckBox("Area centroid")
        self.note = QLabel()
        self.note.setWordWrap(True)
        for w in (self.u_spin, self.v_spin):
            w.editingFinished.connect(self._commit)
        self.centroid.toggled.connect(self._commit)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.u_spin)
        row.addWidget(self.v_spin)
        row.addWidget(self.centroid)
        row.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(row)
        layout.addWidget(self.note)

    def set_row(self, row_id: str | None) -> None:
        self.row_id = row_id
        self.refresh()

    def refresh(self) -> None:
        case = self.controller.case
        row = case.rows.get(self.row_id) if case is not None else None
        self._filling = True
        try:
            self.setEnabled(row is not None)
            if row is None:
                return
            stack = row.main.stacking_axis
            u, v = decode_stacking_axis(stack)
            self.centroid.setChecked(u == 200)
            self.u_spin.setEnabled(u != 200)
            self.u_spin.setValue(min(u, 100))
            self.v_spin.setValue(max(-100, min(v, 100)))
            where = "the area centroid" if u == 200 else f"{u} % of the chord"
            self.note.setText(f"Stored as {stack:06d}: thousands = % of chord (200 = area centroid), the rest = % of "
                              f"the thickness above (+) or below (−) the meanline. Now: {where}, {v} % above the "
                              "meanline.")
        finally:
            self._filling = False

    def _commit(self, *_args) -> None:
        if self._filling or self.row_id is None:
            return
        u = 200 if self.centroid.isChecked() else self.u_spin.value()
        value = encode_stacking_axis(u, self.v_spin.value())
        main = self.controller.case.rows[self.row_id].main
        self.controller.set_attribute(self.row_id, main, "stacking_axis", value, "Change the stacking axis")
        self.refresh()


class ParameterTree(QWidget):
    """All continuous parameters of a blade row as a tree by group, with a text filter.

    ``selected(name)`` is emitted when a parameter is picked. With ``checkable`` each parameter has
    a check box showing its design-variable flag; ``toggled(name, on)`` is emitted when the user
    changes one (the tree does not change the model itself).
    """

    selected = Signal(str)
    toggled = Signal(str, bool)
    _NAME = Qt.UserRole

    def __init__(self, checkable: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.checkable = checkable
        self._names: tuple[str, ...] = ()
        self._items: dict[str, QTreeWidgetItem] = {}
        self._filling = False
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter, e.g. sweep or naca.t_max")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filter)
        self.analytic_only = QCheckBox("Only parameters with an analytic derivative")
        self.analytic_only.toggled.connect(self._apply_filter)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Parameter", "Derivative"])
        self.tree.setUniformRowHeights(True)
        self.tree.setColumnWidth(0, 250)
        self.tree.currentItemChanged.connect(self._current_changed)
        self.tree.itemChanged.connect(self._item_changed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.filter_edit)
        layout.addWidget(self.analytic_only)
        layout.addWidget(self.tree, 1)

    # -- content ----------------------------------------------------------------------------
    def set_parameters(self, parameters) -> None:
        """Show these parameters (a dict name -> Parameter, or None). Rebuilds only if the names changed."""
        parameters = parameters or {}
        names = tuple(parameters)
        if names != self._names:
            self._names = names
            self._fill(parameters)
        elif self.checkable:
            self.set_checked({name for name, p in parameters.items() if p.is_dv})

    def _fill(self, parameters) -> None:
        keep = self.current
        self._filling = True
        self.tree.blockSignals(True)
        self.tree.clear()
        self._items = {}
        groups: dict[str, QTreeWidgetItem] = {}
        for p in parameters.values():
            if p.integer:
                continue
            parent, path = None, ""
            for piece in p.group.split("/"):
                path = f"{path}/{piece}" if path else piece
                node = groups.get(path)
                if node is None:
                    node = QTreeWidgetItem(parent or self.tree.invisibleRootItem(), [piece])
                    node.setFlags(Qt.ItemIsEnabled)
                    groups[path] = node
                parent = node
            item = QTreeWidgetItem(parent, [p.name, "analytic" if p.deriv is not None else "finite difference"])
            item.setData(0, self._NAME, p.name)
            if self.checkable:
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(0, Qt.Checked if p.is_dv else Qt.Unchecked)
            self._items[p.name] = item
        self.tree.blockSignals(False)
        self._filling = False
        self._apply_filter()
        if keep in self._items:
            self.tree.blockSignals(True)
            self.tree.setCurrentItem(self._items[keep])
            self.tree.blockSignals(False)
            self.tree.scrollToItem(self._items[keep])

    def set_checked(self, names: set[str]) -> None:
        self._filling = True
        for name, item in self._items.items():
            state = Qt.Checked if name in names else Qt.Unchecked
            if item.checkState(0) != state:
                item.setCheckState(0, state)
        self._filling = False

    # -- selection --------------------------------------------------------------------------
    @property
    def current(self) -> str | None:
        item = self.tree.currentItem()
        return item.data(0, self._NAME) if item is not None else None

    def select(self, name: str) -> None:
        """Select a parameter by its local name; KeyError if it is not in the tree."""
        self.tree.setCurrentItem(self._items[name])
        self.tree.scrollToItem(self._items[name])

    def _current_changed(self, item: QTreeWidgetItem | None, _previous=None) -> None:
        name = item.data(0, self._NAME) if item is not None else None
        if name is not None:
            self.selected.emit(name)

    def _item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        name = item.data(0, self._NAME)
        if not self._filling and self.checkable and column == 0 and name is not None:
            self.toggled.emit(name, item.checkState(0) == Qt.Checked)

    # -- filter -----------------------------------------------------------------------------
    def _apply_filter(self, *_args) -> None:
        text = self.filter_edit.text().strip().lower()
        analytic = self.analytic_only.isChecked()

        def visit(node: QTreeWidgetItem) -> bool:
            name = node.data(0, self._NAME)
            if name is not None:
                show = (text in name.lower()) and (not analytic or node.text(1) == "analytic")
            else:
                show = False
                for i in range(node.childCount()):
                    show = visit(node.child(i)) or show
                if text or analytic:
                    node.setExpanded(show and (bool(text) or node.childCount() <= 200))
            node.setHidden(not show)
            return show

        root = self.tree.invisibleRootItem()
        self.tree.setUpdatesEnabled(False)
        for i in range(root.childCount()):
            visit(root.child(i))
        self.tree.setUpdatesEnabled(True)
