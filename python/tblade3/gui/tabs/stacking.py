"""Stacking tab: airfoil type of each section, the stacking axis, variable stacking and the blending table.

How T-Blade3 uses these (source/funcNsubs.f90, stacking()): with variable stacking off every
section is stacked on the one stacking axis, a number whose thousands are the chordwise position
in % of chord (200 = area centroid) and whose remainder is the position above or below the
meanline in % of the thickness. With variable stacking on, stk_u and stk_v of each section would
be used instead. The per-section umxthk, lethk and tethk are thickness inputs (Thickness tab).
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFormLayout, QGroupBox, QHeaderView, QLabel, QSplitter,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..controller import Controller
from ..plots import DragPoints, Plot, series_colour
from ..widgets import ChoiceBox, StackingAxisEdit, format_number
from .base import RowTab
from .rowsetup import CHOICES, change_switch
from .sections import section_span

# Airfoil types of bladegen.f90; any four digits are a NACA four-digit section (e.g. 0012).
AIRFOIL_TYPES = {"sect1": "sect1", "crcle": "crcle", "s809m": "s809m", "clark": "clark", "negclarkCR": "negclarkCR"}


def valid_airfoil(name: str) -> bool:
    return name in AIRFOIL_TYPES or (len(name) == 4 and name.isdigit())


def _note() -> QLabel:
    label = QLabel()
    label.setWordWrap(True)
    return label


class StackingTab(RowTab):
    title = "Stacking"

    def __init__(self, controller: Controller, parent: QWidget | None = None):
        super().__init__(controller, parent)
        self._filling = False

        # -- stacking switch and axis ---------------------------------------------------------
        self.variable_box = ChoiceBox(controller, "variable_stacking", CHOICES["variable_stacking"],
                                      "Change variable stacking",
                                      commit=lambda rid, value: change_switch(controller, rid, "variable_stacking",
                                                                              value))
        self.variable_note = _note()
        self.axis_edit = StackingAxisEdit(controller)
        stack_box = QGroupBox("Stacking")
        form = QFormLayout(stack_box)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        form.addRow("Variable stacking", self.variable_box)
        form.addRow(self.variable_note)
        form.addRow("Stacking axis", self.axis_edit)

        # -- per section: airfoil type, stk_u, stk_v ------------------------------------------
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Airfoil type", "stk_u (% chord)", "stk_v (% thickness)"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.itemChanged.connect(self._item_changed)
        self.table_note = _note()
        section_box = QGroupBox("Per section (row 1 = hub)")
        layout = QVBoxLayout(section_box)
        layout.addWidget(self.table)
        layout.addWidget(self.table_note)

        # -- blending table (read only) -------------------------------------------------------
        self.blend_table = QTableWidget(0, 3)
        self.blend_table.setHorizontalHeaderLabels(["Span", "bf1", "bf2"])
        self.blend_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.blend_table.verticalHeader().setDefaultSectionSize(22)
        self.blend_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.blend_table.setMaximumHeight(120)
        self.blend_note = _note()
        blend_box = QGroupBox("Blending section variable")
        layout = QVBoxLayout(blend_box)
        layout.addWidget(self.blend_table)
        layout.addWidget(self.blend_note)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(stack_box)
        left_layout.addWidget(section_box, 1)
        left_layout.addWidget(blend_box)

        # -- right: stk_u and stk_v against span ----------------------------------------------
        self.plot = Plot("Stacking position (%)", "Span fraction", legend=True)
        self.plot.getPlotItem().setYRange(-0.03, 1.2, padding=0)       # room for the legend above the tip
        self.points: dict[str, DragPoints] = {}
        for slot, (name, label) in enumerate((("stk_u", "stk_u, % of chord"), ("stk_v", "stk_v, % above meanline"))):
            points = DragPoints(series_colour(slot), movable="x", line=True)
            self.plot.addItem(points)
            self.plot.curve(f"legend {name}", [], [], series_colour(slot), symbol="o", label=label)
            points.signals.started.connect(lambda _i: controller.begin_drag())
            points.signals.moved.connect(lambda i, x, _y, name=name: self._point_dragged(name, i, x))
            points.signals.clicked.connect(lambda i: self.table.selectRow(i))
            self.points[name] = points
        self.plot_note = _note()
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.plot, 1)
        right_layout.addWidget(self.plot_note)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([470, 610])
        QVBoxLayout(self).addWidget(splitter)

    # -- RowTab -----------------------------------------------------------------------------
    def row_changed(self) -> None:
        self.variable_box.set_row(self.row_id)
        self.axis_edit.set_row(self.row_id)

    def refresh_inputs(self) -> None:
        self.variable_box.refresh()
        self.axis_edit.refresh()
        row = self.row
        if row is None:
            self.table.setRowCount(0)
            self.blend_table.setRowCount(0)
            return
        m = row.main
        variable = bool(m.variable_stacking)
        self.axis_edit.setEnabled(not variable)
        self.variable_note.setText(
            "On: stk_u and stk_v of each section are used, but current T-Blade3 crashes with variable stacking "
            "(stacking() in funcNsubs.f90); switch it off." if variable else
            "Off: all sections are stacked on the stacking axis below. Variable stacking cannot be switched on here: "
            "current T-Blade3 crashes with it.")
        self._fill_table(variable)
        self._fill_blending()
        self._draw()

    def refresh_geometry(self) -> None:
        self._draw()                    # section spans come from the run

    def apply_theme(self) -> None:
        self.plot.apply_theme()
        for slot, name in enumerate(("stk_u", "stk_v")):
            self.plot.curve(f"legend {name}", [], [], series_colour(slot), symbol="o")
        self._draw()

    # -- tables -----------------------------------------------------------------------------
    def _fill_table(self, variable: bool) -> None:
        m = self.row.main
        n = m.n_streamlines
        self._filling = True
        try:
            if self.table.rowCount() != n:
                self.table.setRowCount(n)
            for j in range(n):
                box = self.table.cellWidget(j, 0)
                if box is None:
                    box = QComboBox()
                    box.setEditable(True)
                    for key, label in AIRFOIL_TYPES.items():
                        box.addItem(label, key)
                    box.setToolTip("sect1: T-Blade3's own section (camber and thickness inputs); crcle, s809m, "
                                   "clark, negclarkCR: fixed shapes; or type four digits for a NACA four-digit "
                                   "section, e.g. 0012")
                    box.activated.connect(lambda _i, j=j: self._type_changed(j))
                    box.lineEdit().editingFinished.connect(lambda j=j: self._type_changed(j))
                    self.table.setCellWidget(j, 0, box)
                self._show_type(box, m.airfoil_type[j])
                for col, name in ((1, "stk_u"), (2, "stk_v")):
                    text = format_number(float(getattr(m, name)[j]))
                    item = self.table.item(j, col)
                    if item is None:
                        item = QTableWidgetItem(text)
                        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                        self.table.setItem(j, col, item)
                    elif item.text() != text:
                        item.setText(text)
                    item.setFlags(item.flags() | Qt.ItemIsEditable if variable else item.flags() & ~Qt.ItemIsEditable)
                    item.setForeground(self.palette().text() if variable else self.palette().placeholderText())
        finally:
            self._filling = False
        others = sorted({t for t in m.airfoil_type if t != "sect1"})
        text = ("stk_u and stk_v are greyed out: they are used only with variable stacking. " if not variable else "")
        text += "umxthk, lethk and tethk of each section are in the Thickness tab."
        if others:
            text += f" Sections of type {', '.join(others)} ignore the thickness and camber inputs."
        self.table_note.setText(text)

    @staticmethod
    def _show_type(box: QComboBox, name: str) -> None:
        box.blockSignals(True)
        index = box.findData(name)
        if index >= 0:
            box.setCurrentIndex(index)
        else:
            box.setEditText(name)
        box.blockSignals(False)

    def _type_changed(self, j: int) -> None:
        row = self.row
        if self._filling or row is None:
            return
        box = self.table.cellWidget(j, 0)
        text = box.currentText().strip()
        index = box.findText(text)
        name = box.itemData(index) if index >= 0 else text.split(" ")[0]
        if name == row.main.airfoil_type[j]:
            self._show_type(box, name)
            return
        if not valid_airfoil(name):
            self.controller.message.emit(f"Unknown airfoil type {name!r}: use {', '.join(AIRFOIL_TYPES)} or four "
                                         "digits (NACA)")
            self._show_type(box, row.main.airfoil_type[j])
            return
        self.set_airfoil_type(j, name)

    def set_airfoil_type(self, j: int, name: str) -> None:
        """Set the airfoil type of section j (0-based), undoable."""
        rid = self.row_id
        old = list(self.row.main.airfoil_type)
        new = list(old)
        new[j] = name

        def apply(values: list[str]) -> None:
            self.controller.row(rid).main.airfoil_type = list(values)

        self.controller.edit(rid, f"Change the airfoil type of section {j + 1}", lambda: apply(new), lambda: apply(old))

    def _item_changed(self, item: QTableWidgetItem) -> None:
        if self._filling or self.row_id is None or item.column() not in (1, 2):
            return
        name = ("stk_u", "stk_v")[item.column() - 1]
        try:
            value = float(item.text())
        except ValueError:
            self.refresh_inputs()
            return
        self.controller.set_value(self.row_id, f"{name}[{item.row() + 1}]", value)

    def _fill_blending(self) -> None:
        m = self.row.main
        bl = m.blending
        self.blend_table.setRowCount(len(bl))
        for j in range(len(bl)):
            for col, value in enumerate((format_number(float(bl.span[j])), str(int(bl.values["bf1"][j])),
                                         str(int(bl.values["bf2"][j])))):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                item.setForeground(self.palette().placeholderText())
                self.blend_table.setItem(j, col, item)
        self.blend_note.setText(f"bsv1 = {m.blend_bsv1}, bsv2 = {m.blend_bsv2}. Read only: current T-Blade3 reads "
                                "this table but does not use it (it is kept so that the file stays the same).")

    # -- plot -------------------------------------------------------------------------------
    def _draw(self) -> None:
        row = self.row
        if row is None:
            for points in self.points.values():
                points.set_points([], [])
            return
        m = row.main
        span, from_run = section_span(row, m.n_streamlines)
        for name, points in self.points.items():
            points.set_points(getattr(m, name), span)
        self.plot.set_labels(y_label="Span fraction" if from_run else "Span fraction (evenly spaced)")
        self.plot_note.setText("Drag the points to change the values." if m.variable_stacking else
                               "Not used with variable stacking off; shown for reference.")

    def _point_dragged(self, name: str, index: int, x: float) -> None:
        row = self.row
        if row is None or not row.main.variable_stacking:
            return
        self.controller.set_value(self.row_id, f"{name}[{index + 1}]", x, drag=True)
