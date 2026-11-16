"""Spanwise controls tab: the control points of sweep, lean, inlet and exit angle, chord and thickness.

Each control is a short table of (span, value) control points; T-Blade3 fits a spline through them
and evaluates it at every section. The plot shows the control points (drag them) with the span on
the vertical axis, hub at the bottom, and what the last run produced at each section.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGroupBox, QLabel, QListWidget, QSplitter, QVBoxLayout, QWidget

from ..controller import Controller
from ..edits import insert_control_point, remove_control_point
from ..plots import DragPoints, Plot, muted_colour, series_colour
from ..widgets import ParamTable
from .base import RowTab


@dataclass(frozen=True)
class Control:
    title: str              # shown in the list
    attr: str               # ControlTable attribute of the main input
    column: str             # value column in that table
    prefix: str             # parameter name prefix of the values, e.g. "sweep" -> sweep[1]
    span_prefix: str        # parameter name prefix of the span locations
    label: str              # axis label of the values
    built: str | None       # section-table column produced by the run that corresponds to it
    built_label: str = ""   # axis label of that column; empty: same quantity, drawn on the same axes
    max_points: int | None = None


CONTROLS = (
    Control("Sweep", "sweep", "delta_m", "sweep", "sweep.span", "Sweep, delta m′", "sweep", max_points=9),
    Control("Lean", "lean", "delta_theta", "lean", "lean.span", "Lean, delta theta", "lean", max_points=9),
    Control("Inlet angle", "in_beta", "in_beta*", "in_beta", "in_beta.span", "Inlet angle control, in_beta*",
            "beta_z_le", "LE blade angle as built (deg)"),
    Control("Exit angle", "out_beta", "out_beta*", "out_beta", "out_beta.span", "Exit angle control, out_beta*",
            "beta_z_te", "TE blade angle as built (deg)"),
    Control("Chord multiplier", "chord_multiplier", "chord_multiplier", "chord_multiplier", "chord_multiplier.span",
            "Chord multiplier control", "chord", "Chord as built ({units})"),
    Control("Thickness, tm/c", "thickness", "tm/c", "tm_c", "thickness.span", "Thickness control, tm/c",
            "max_thickness", "Max thickness as built ({units})"),
    Control("Thickness, u_max", "thickness", "u_max", "u_max", "thickness.span", "Location of maximum thickness, u_max",
            None),
)


class SpanwiseTab(RowTab):
    title = "Spanwise controls"

    def __init__(self, controller: Controller, parent: QWidget | None = None):
        super().__init__(controller, parent)
        self.control = CONTROLS[0]

        # -- left: which control, and its table -----------------------------------------------
        self.control_list = QListWidget()
        self.control_list.addItems([c.title for c in CONTROLS])
        self.control_list.setMaximumHeight(8 * 22)
        self.control_list.currentRowChanged.connect(self._control_selected)
        self.table = ParamTable(controller, [("Span", self.control.span_prefix), ("Value", self.control.prefix)],
                                on_add=self._add_point, on_remove=self._remove_point)
        self.note = QLabel()
        self.note.setWordWrap(True)
        box = QGroupBox("Control points")
        box_layout = QVBoxLayout(box)
        box_layout.addWidget(self.table)
        box_layout.addWidget(self.note)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.control_list)
        left_layout.addWidget(box, 1)

        # -- right: control points against span, and the result of the run ---------------------
        self.plot = Plot("", "Span fraction", legend=True)
        self.points = DragPoints(series_colour(0), line=True)
        self.plot.addItem(self.points)
        self.points.signals.started.connect(lambda _i: controller.begin_drag())
        self.points.signals.moved.connect(self._point_dragged)
        self.points.signals.clicked.connect(self.table.select_row)
        self.built_plot = Plot("", "Span fraction")
        plots = QSplitter(Qt.Horizontal)
        plots.addWidget(self.plot)
        plots.addWidget(self.built_plot)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(plots)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 780])
        QVBoxLayout(self).addWidget(splitter)
        self.control_list.setCurrentRow(0)

    # -- RowTab -----------------------------------------------------------------------------
    def row_changed(self) -> None:
        self.table.set_row(self.row_id)

    def refresh_inputs(self) -> None:
        self.table.refresh()
        self._draw_inputs()

    def refresh_geometry(self) -> None:
        self._draw_built()

    def apply_theme(self) -> None:
        self.plot.apply_theme()
        self.built_plot.apply_theme()
        self._draw_inputs()
        self._draw_built()

    # -- the chosen control -----------------------------------------------------------------
    def _table(self):
        """The ControlTable of the chosen control in the current row, or None."""
        row = self.row
        return getattr(row.main, self.control.attr) if row is not None else None

    def _has_column(self) -> bool:
        table = self._table()
        return table is not None and self.control.column in table.values

    def _control_selected(self, index: int) -> None:
        if not 0 <= index < len(CONTROLS):
            return
        self.control = CONTROLS[index]
        self.table.set_columns([("Span", self.control.span_prefix), ("Value", self.control.prefix)])
        self.plot.set_labels(x_label=self.control.label)
        if self.isVisible():
            self._draw_inputs()
            self._draw_built()

    def _draw_inputs(self) -> None:
        table = self._table()
        c = self.control
        if table is None or not self._has_column():
            self.points.set_points([], [])
            self.note.setText("" if table is None else
                              f"This row's input file has no {c.column} column in its thickness table.")
            self.table.setEnabled(False)
            return
        self.table.setEnabled(True)
        self.points.set_points(table.values[c.column], table.span)
        n = len(table)
        text = "No control points: this control is not used." if n == 0 else f"{n} control points."
        if c.attr == "thickness" and len(table.values) > 1:
            text += " tm/c and u_max share their span locations."
        if c.max_points is not None:
            text += f" T-Blade3 reads at most {c.max_points} here."
        self.note.setText(text)

    def _draw_built(self) -> None:
        geo, row, c = self.geometry, self.row, self.control
        column = geo.section_table.get(c.built) if (geo is not None and c.built) else None
        span = geo.section_table.get("span") if geo is not None else None
        ok = column is not None and span is not None and len(column) == len(span) and self._has_column()
        overlay = ok and not c.built_label
        if overlay:
            self.plot.curve("built", column, span, muted_colour(), width=2.0, label="At the sections, as built", z=1)
        else:
            self.plot.remove("built")
        if ok and c.built_label:
            self.built_plot.set_labels(x_label=c.built_label.format(units=row.main.units))
            self.built_plot.curve("built", column, span, series_colour(0), symbol="o")
            self.built_plot.show()
        else:
            self.built_plot.remove("built")
            self.built_plot.hide()

    # -- edits ------------------------------------------------------------------------------
    def _point_dragged(self, index: int, x: float, y: float) -> None:
        if self.row_id is None:
            return
        c = self.control
        self.controller.set_values(self.row_id, {f"{c.prefix}[{index + 1}]": x, f"{c.span_prefix}[{index + 1}]": y},
                                   drag=True)

    def _add_point(self, index: int) -> None:
        table, c = self._table(), self.control
        if table is None or not self._has_column():
            return
        if c.max_points is not None and len(table) >= c.max_points:
            self.controller.message.emit(f"T-Blade3 reads at most {c.max_points} {c.title.lower()} control points")
            return
        attr = c.attr
        insert_control_point(self.controller, self.row_id, lambda: getattr(self.row.main, attr), index, c.title.lower())
        self.table.select_row(min(index + 1, len(table) - 1))

    def _remove_point(self, index: int) -> None:
        if self._table() is None or not self._has_column():
            return
        attr = self.control.attr
        remove_control_point(self.controller, self.row_id, lambda: getattr(self.row.main, attr), index,
                             self.control.title.lower())
