"""Reusable input widgets bound to the controller."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLineEdit, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

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
                    item.setFlags(item.flags() | Qt.ItemIsEditable if p is not None else item.flags() & ~Qt.ItemIsEditable)
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
    a blade row (default: the row's main input).
    """

    def __init__(self, controller: Controller, attr: str, choices: dict, text: str,
                 target: Callable | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.controller, self.attr, self.text = controller, attr, text
        self.target = target or (lambda row: row.main)
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
            self.setEnabled(True)
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
        obj = self.target(self.controller.case.rows[self.row_id])
        self.controller.set_attribute(self.row_id, obj, self.attr, self.currentData(), self.text)
