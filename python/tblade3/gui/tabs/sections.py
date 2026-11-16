"""Sections tab: the sectionwise table of the main input (one row per streamline section).

The table edits the values; the plot shows the chosen column against the span of each section
(hub at the bottom), with the points draggable in value, and what the last run produced where the
run writes a matching column.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QSplitter, QVBoxLayout,
                               QWidget)

from ..controller import Controller
from ..plots import DragPoints, Plot, muted_colour, series_colour
from ..widgets import ParamTable
from .base import RowTab


@dataclass(frozen=True)
class Column:
    key: str                    # key of MainInput.sections
    header: str                 # as in the input file
    label: str                  # axis label
    built: str | None = None    # section-table column of the run for the same quantity
    built_label: str = ""       # its own axis label: different units, drawn on a second plot


COLUMNS = (
    Column("in_beta", "in_Beta", "Inlet angle, in_Beta (deg)", "beta_z_le"),
    Column("out_beta", "out_Beta", "Exit angle, out_Beta (deg)", "beta_z_te"),
    Column("mrel_in", "mrel_in", "Inlet relative Mach number, mrel_in"),
    Column("chord", "chord", "Chord, non-dimensional", "chord", "Chord as built ({units})"),
    Column("tc_max", "t/c_max", "Maximum thickness / chord, t/c_max", "tc_built"),
    Column("incidence", "Incidence", "Incidence (deg)"),
    Column("deviation", "Deviation", "Deviation (deg)"),
    Column("sec_flow_angle", "Sec. Flow Angle", "Section flow angle (deg)"),
)
_BUILT_TEXT = {"beta_z_le": "LE blade angle as built", "beta_z_te": "TE blade angle as built",
               "tc_built": "Max thickness / chord as built"}


def section_span(row, n: int) -> tuple[np.ndarray, bool]:
    """Span fraction of each section from the last run, or evenly spaced; and whether it came from the run."""
    geo = row.geometry if row is not None else None
    span = geo.section_table.get("span") if geo is not None else None
    if span is not None and len(span) == n:
        return np.asarray(span, dtype=float), True
    return np.linspace(0.0, 1.0, n), False


class SectionsTab(RowTab):
    title = "Sections"

    def __init__(self, controller: Controller, parent: QWidget | None = None):
        super().__init__(controller, parent)
        self.column = COLUMNS[0]

        # -- left: the table ------------------------------------------------------------------
        self.table = ParamTable(controller, [(c.header, f"sec.{c.key}") for c in COLUMNS])
        self.table.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)   # full digits
        self.note = QLabel()
        self.note.setWordWrap(True)
        box = QGroupBox("Sectionwise properties (row 1 = hub)")
        box_layout = QVBoxLayout(box)
        box_layout.addWidget(self.table)
        box_layout.addWidget(self.note)

        # -- right: which column, and its plots -----------------------------------------------
        self.column_list = QComboBox()
        self.column_list.addItems([c.header for c in COLUMNS])
        self.column_list.currentIndexChanged.connect(self._column_selected)
        self.plot = Plot("", "Span fraction", legend=True)
        self.points = DragPoints(series_colour(0), movable="x", line=True)
        self.plot.addItem(self.points)
        self.points.signals.started.connect(lambda _i: controller.begin_drag())
        self.points.signals.moved.connect(self._point_dragged)
        self.points.signals.clicked.connect(self.table.select_row)
        self.built_plot = Plot("", "Span fraction")
        plots = QSplitter(Qt.Horizontal)
        plots.addWidget(self.plot)
        plots.addWidget(self.built_plot)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        choice = QHBoxLayout()
        choice.addWidget(QLabel("Plotted column"))
        choice.addWidget(self.column_list, 1)
        right_layout.addLayout(choice)
        right_layout.addWidget(plots, 1)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(box)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([600, 480])
        QVBoxLayout(self).addWidget(splitter)
        self._column_selected(0)

    # -- RowTab -----------------------------------------------------------------------------
    def row_changed(self) -> None:
        self.table.set_row(self.row_id)

    def refresh_inputs(self) -> None:
        row = self.row
        chord_unused = row is not None and row.main.chord_switch != 1
        self.table.set_read_only_columns({3} if chord_unused else set())
        self.table.refresh()
        self.note.setText("The chord column is used only with the chord switch at 1 (Row setup); it is greyed out."
                          if chord_unused else "")
        self._draw()

    def refresh_geometry(self) -> None:
        self._draw()

    def apply_theme(self) -> None:
        self.plot.apply_theme()
        self.built_plot.apply_theme()
        self._draw()

    # -- drawing ----------------------------------------------------------------------------
    def _column_selected(self, index: int) -> None:
        if not 0 <= index < len(COLUMNS):
            return
        self.column = COLUMNS[index]
        self.plot.set_labels(x_label=self.column.label)
        self.table.table.setCurrentCell(max(self.table.table.currentRow(), 0), index)
        if self.isVisible():
            self._draw()

    def _built(self) -> np.ndarray | None:
        """As-built values of the chosen column at the sections, or None."""
        geo, c = self.geometry, self.column
        if geo is None or c.built is None:
            return None
        t = geo.section_table
        if c.built == "tc_built":           # max thickness over chord, both in mm (geom_data.<cn>.csv)
            if "max_thickness" not in t or "chord" not in t:
                return None
            return np.asarray(t["max_thickness"], dtype=float) / np.asarray(t["chord"], dtype=float)
        return np.asarray(t[c.built], dtype=float) if c.built in t else None

    def _draw(self) -> None:
        row, c = self.row, self.column
        if row is None:
            self.points.set_points([], [])
            self.plot.remove("built")
            self.built_plot.hide()
            return
        values = row.main.sections[c.key]
        span, from_run = section_span(row, len(values))
        self.points.set_points(values, span)
        self.plot.set_labels(y_label="Span fraction" if from_run else "Span fraction (evenly spaced: no run yet)")
        built = self._built()
        ok = built is not None and len(built) == len(span)
        if ok and not c.built_label:
            self.plot.curve("built", built, span, muted_colour(), width=2.0, label=_BUILT_TEXT[c.built], z=1)
        else:
            self.plot.remove("built")
        if ok and c.built_label:
            self.built_plot.set_labels(x_label=c.built_label.format(units=row.main.units))
            self.built_plot.curve("built", built, span, series_colour(0), symbol="o")
            self.built_plot.show()
        else:
            self.built_plot.remove("built")
            self.built_plot.hide()
        # the legend names the input points only when there is a second series
        if ok and not c.built_label:
            self.plot.curve("input label", [], [], series_colour(0), symbol="o", label="Input (drag in value)")
        else:
            self.plot.remove("input label")

    # -- edits ------------------------------------------------------------------------------
    def _point_dragged(self, index: int, x: float, _y: float) -> None:
        if self.row_id is not None:
            self.controller.set_value(self.row_id, f"sec.{self.column.key}[{index + 1}]", x, drag=True)
