"""Design variables tab: flag parameters as design variables, set bounds, export for ESP or a script.

The flags and bounds are saved with the case (case.tb3.yaml). The same list is what
``case.dv`` gives a Python optimizer and what ``tb3 run --dv-file`` expects.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                               QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ...io.csm import export_csm
from ..controller import Controller
from ..widgets import ParameterTree, format_number
from .base import RowTab

_COLUMNS = ("Design variable", "Value", "Lower bound", "Upper bound", "Derivative", "ESP argument")


class DesignVariablesTab(RowTab):
    title = "Design variables"
    shows_all_rows = True               # the table lists the design variables of every row

    def __init__(self, controller: Controller, parent: QWidget | None = None):
        super().__init__(controller, parent)
        self._filling = False

        # -- left: tick parameters of the selected row ----------------------------------------
        self.picker = ParameterTree(checkable=True)
        self.picker.toggled.connect(self._toggled)
        self.picker_label = QLabel()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.picker_label)
        left_layout.addWidget(self.picker, 1)

        # -- right: the design variables of all rows ------------------------------------------
        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setMinimumSectionSize(70)
        self.table.verticalHeader().setDefaultSectionSize(22)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.itemChanged.connect(self._item_changed)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.remove_button = QPushButton("Remove selected")
        self.remove_button.clicked.connect(self._remove_selected)
        self.csm_button = QPushButton("Export .csm for ESP…")
        self.csm_button.clicked.connect(self._export_csm)
        self.values_button = QPushButton("Export values…")
        self.values_button.clicked.connect(self._export_values)
        buttons = QHBoxLayout()
        buttons.addWidget(self.remove_button)
        buttons.addStretch(1)
        buttons.addWidget(self.values_button)
        buttons.addWidget(self.csm_button)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.table, 1)
        right_layout.addWidget(self.summary)
        right_layout.addLayout(buttons)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([380, 620])
        QVBoxLayout(self).addWidget(splitter)

        controller.designVariablesChanged.connect(self.notify_inputs)

    # -- RowTab -----------------------------------------------------------------------------
    def refresh_inputs(self) -> None:
        row = self.row
        self.picker.set_parameters(row.parameters if row is not None else None)
        self.picker.set_unused(row.unused_parameters() if row is not None else {})
        self.picker_label.setText(f"Tick parameters of row {self.row_id} to make them design variables"
                                  if row is not None else "No row selected")
        self._fill_table()

    # -- table ------------------------------------------------------------------------------
    def _design_variables(self) -> list[tuple[str, str, object]]:
        """(row id, local name, Parameter) of every design variable, in ``case.dv`` order."""
        case = self.controller.case
        if case is None:
            return []
        return [(rid, p.name, p) for rid, row in case.rows.items() for p in row.parameters.values() if p.is_dv]

    def _fill_table(self) -> None:
        dvs = self._design_variables()
        self._filling = True
        try:
            self.table.setRowCount(len(dvs))
            for i, (rid, name, p) in enumerate(dvs):
                texts = (f"row{rid}.{name}", format_number(p.value),
                         "" if p.lower is None else format_number(p.lower),
                         "" if p.upper is None else format_number(p.upper),
                         "analytic" if p.deriv is not None else "finite difference",
                         f"{p.udp[0]}[{p.udp[1]}]" if p.udp is not None else "none")
                for j, text in enumerate(texts):
                    item = self.table.item(i, j)
                    if item is None:
                        item = QTableWidgetItem()
                        if j in (1, 2, 3):
                            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                        else:
                            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                        self.table.setItem(i, j, item)
                    if item.text() != text:
                        item.setText(text)
                    item.setData(Qt.UserRole, (rid, name))
        finally:
            self._filling = False
        n = len(dvs)
        analytic = sum(p.deriv is not None for _, _, p in dvs)
        no_udp = sum(p.udp is None for _, _, p in dvs)
        text = "No design variables yet." if n == 0 else (
            f"{n} design variable{'s' if n != 1 else ''}: {analytic} with an analytic derivative, "
            f"{n - analytic} by finite difference (two extra runs each).")
        if no_udp:
            text += (f" {no_udp} of them {'has' if no_udp == 1 else 'have'} no matching udpTblade argument and "
                     f"{'is' if no_udp == 1 else 'are'} left out of the .csm.")
        case = self.controller.case
        ignored = sum(bool(case.rows[rid].unused_reason(name)) for rid, name, _ in dvs)
        if ignored:
            text += (f" {ignored} of them {'has' if ignored == 1 else 'have'} no effect with the current switches "
                     "(greyed in the tree on the left).")
        self.summary.setText(text)
        for button in (self.remove_button, self.csm_button, self.values_button):
            button.setEnabled(self.controller.case is not None and (n > 0 or button is self.csm_button))

    def _item_changed(self, item: QTableWidgetItem) -> None:
        if self._filling:
            return
        rid, name = item.data(Qt.UserRole)
        p = self.controller.case.rows[rid].parameters[name]
        text = item.text().strip()
        try:
            value = float(text) if text else None
        except ValueError:
            self._fill_table()
            return
        column = item.column()
        if column == 1:
            if value is None:
                self._fill_table()
            else:
                self.controller.set_value(rid, name, value)
        elif column == 2:
            self.controller.set_design_variable(rid, name, True, value, p.upper)
        elif column == 3:
            self.controller.set_design_variable(rid, name, True, p.lower, value)

    # -- edits ------------------------------------------------------------------------------
    def _toggled(self, name: str, on: bool) -> None:
        if self.row_id is not None:
            self.controller.set_design_variable(self.row_id, name, on)

    def _remove_selected(self) -> None:
        picked = {self.table.item(index.row(), 0).data(Qt.UserRole) for index in self.table.selectedIndexes()}
        stack = self.controller.undo_stack
        stack.beginMacro(f"Remove {len(picked)} design variable{'s' if len(picked) != 1 else ''}")
        for rid, name in picked:
            self.controller.set_design_variable(rid, name, False)
        stack.endMacro()

    # -- export -----------------------------------------------------------------------------
    def _start_folder(self) -> Path:
        case = self.controller.case
        return case.folder if case is not None and case.folder is not None else Path.home()

    def _export_csm(self) -> None:
        case = self.controller.case
        if case is None:
            return
        name = next(iter(case.rows.values())).main.casename
        path, _ = QFileDialog.getSaveFileName(self, "Export an OpenCSM script (the input files are written next to it)",
                                              str(self._start_folder() / f"{name}.csm"), "OpenCSM script (*.csm)")
        if path:
            self.export_csm(path)

    def export_csm(self, path: str | Path) -> None:
        try:
            out = export_csm(self.controller.case, path)
        except Exception as exc:
            QMessageBox.critical(self, "T-Blade3", f"Could not export:\n\n{exc}")
            return
        self.controller.message.emit(f"Exported {out} and the input files next to it")

    def _export_values(self) -> None:
        if self.controller.case is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export the design-variable values",
                                              str(self._start_folder() / "design_variables.txt"), "Text (*.txt)")
        if path:
            self.export_values(path)

    def export_values(self, path: str | Path) -> None:
        """One value per line, in ``case.dv`` order; names and bounds as comments. Read by ``tb3 run --dv-file``."""
        dv = self.controller.case.dv
        lines = ["# T-Blade3 design variables: value, then name and bounds as a comment"]
        for name, value, (lower, upper) in zip(dv.names, dv.values, dv.bounds):
            lines.append(f"{float(value)!r}    # {name}  [{'' if lower is None else lower}, {'' if upper is None else upper}]")
        Path(path).write_text("\n".join(lines) + "\n")
        np.loadtxt(path, ndmin=1)           # must read back the way the command line reads it
        self.controller.message.emit(f"Exported {len(dv)} design-variable values to {path}")
