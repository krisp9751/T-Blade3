"""Thickness tab: the inputs of the row's thickness distribution and the thickness T-Blade3 built.

Modified NACA (distribution 5): spanwise control points of LE radius, u_max, t_max and t_TE in
spancontrolinputs. Wennerstrom and the splines (0, 1, 2): t/c_max of the section table, umxthk,
lethk and tethk of each section, and the tm/c and u_max control points of the main input. The
result plot shows thickness / chord against the chord fraction from the run's thickness_data files.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QGroupBox, QHBoxLayout, QLabel, QSplitter, QStackedWidget,
                               QVBoxLayout, QWidget)

from ...io.maininput import THICKNESS_DISTRIBUTIONS
from ..controller import Controller
from ..edits import insert_table_row, remove_table_row
from ..plots import DragPoints, Plot, ramp_colours, series_colour
from ..widgets import ParamTable
from .base import RowTab
from .sections import section_span

_NACA_TEXT = {"LE_radius": "LE radius index", "u_max": "Location of max thickness, u_max",
              "t_max": "Max thickness / chord, t_max", "t_TE": "TE thickness / chord, t_TE",
              "dy_dx_TE": "TE thickness slope, dy_dx_TE", "dy_dx_norm": "Normalised TE slope, dy_dx_norm"}


@dataclass(frozen=True)
class SectionValue:
    title: str
    prefix: str         # parameter prefix, e.g. "umxthk" -> umxthk[j]
    attr: str           # where the values live: "sections.tc_max" or a MainInput attribute
    label: str


SECTION_VALUES = (
    SectionValue("t/c_max", "sec.tc_max", "sections.tc_max", "Max thickness / chord, t/c_max"),
    SectionValue("umxthk", "umxthk", "umxthk", "Location of max thickness, umxthk"),
    SectionValue("lethk", "lethk", "lethk", "LE thickness parameter, lethk"),
    SectionValue("tethk", "tethk", "tethk", "TE thickness parameter, tethk"),
)


def _safe(column: str) -> str:
    """Column name -> parameter name piece, as model.BladeRow names them: 'LE_radius' -> 'le_radius'."""
    return re.sub(r"[^0-9a-z]+", "_", column.lower()).strip("_")


def _labelled(text: str, widget: QWidget) -> QHBoxLayout:
    layout = QHBoxLayout()
    layout.addWidget(QLabel(text))
    layout.addWidget(widget, 1)
    return layout


def _note() -> QLabel:
    label = QLabel()
    label.setWordWrap(True)
    return label


class ThicknessTab(RowTab):
    title = "Thickness"

    def __init__(self, controller: Controller, parent: QWidget | None = None):
        super().__init__(controller, parent)
        self.naca_param = "t_max"
        self.section_value = SECTION_VALUES[0]

        self.header = _note()

        # -- page 0: modified NACA ------------------------------------------------------------
        self.naca_table = ParamTable(controller, [("Span", "naca.span")], on_add=self._add_naca,
                                     on_remove=self._remove_naca)
        self.naca_note = _note()
        self.naca_list = QComboBox()
        self.naca_list.currentIndexChanged.connect(self._naca_selected)
        naca_page = QWidget()
        layout = QVBoxLayout(naca_page)
        layout.setContentsMargins(0, 0, 0, 0)
        box = QGroupBox("Modified NACA control points (spancontrolinputs)")
        box_layout = QVBoxLayout(box)
        box_layout.addWidget(self.naca_table)
        box_layout.addWidget(self.naca_note)
        layout.addWidget(box, 1)
        layout.addLayout(_labelled("Plotted parameter", self.naca_list))

        # -- page 1: per-section values (Wennerstrom, splines) --------------------------------
        self.section_table = ParamTable(controller, [(v.title, v.prefix) for v in SECTION_VALUES])
        self.section_note = _note()
        self.tm_table = ParamTable(controller, [("Span", "thickness.span"), ("tm/c", "tm_c")])
        self.tm_table.setMaximumHeight(170)
        self.tm_note = _note()
        self.section_list = QComboBox()
        self.section_list.addItems([v.title for v in SECTION_VALUES])
        self.section_list.currentIndexChanged.connect(self._section_value_selected)
        section_page = QWidget()
        layout = QVBoxLayout(section_page)
        layout.setContentsMargins(0, 0, 0, 0)
        box = QGroupBox("Per section (row 1 = hub)")
        box_layout = QVBoxLayout(box)
        box_layout.addWidget(self.section_table)
        box_layout.addWidget(self.section_note)
        layout.addWidget(box, 3)
        box = QGroupBox("Thickness multiplier tm/c (spanwise control points)")
        box_layout = QVBoxLayout(box)
        box_layout.addWidget(self.tm_table)
        box_layout.addWidget(self.tm_note)
        layout.addWidget(box, 1)
        layout.addLayout(_labelled("Plotted value", self.section_list))

        self.pages = QStackedWidget()
        self.pages.addWidget(naca_page)
        self.pages.addWidget(section_page)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.header)
        left_layout.addWidget(self.pages, 1)

        # -- right: inputs against span, and the thickness the run produced --------------------
        self.input_plot = Plot("", "Span fraction")
        self.points = DragPoints(series_colour(0), line=True)
        self.input_plot.addItem(self.points)
        self.points.signals.started.connect(lambda _i: controller.begin_drag())
        self.points.signals.moved.connect(self._point_dragged)
        self.points.signals.clicked.connect(self._point_clicked)
        self.result_choice = QComboBox()
        self.result_choice.currentIndexChanged.connect(lambda _i: self._draw_result())
        self.result_plot = Plot("Chord fraction, u", "Thickness / chord", legend=True)
        self.result_note = _note()
        result = QWidget()
        result_layout = QVBoxLayout(result)
        result_layout.setContentsMargins(0, 0, 0, 0)
        choice_row = QHBoxLayout()
        choice_row.addWidget(QLabel("Thickness as built:"))
        choice_row.addWidget(self.result_choice, 1)
        result_layout.addLayout(choice_row)
        result_layout.addWidget(self.result_plot, 1)
        result_layout.addWidget(self.result_note)
        plots = QSplitter(Qt.Vertical)
        plots.addWidget(self.input_plot)
        plots.addWidget(result)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(plots)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([430, 650])
        QVBoxLayout(self).addWidget(splitter)
        self._section_value_selected(0)

    # -- helpers ----------------------------------------------------------------------------
    def _naca_table(self):
        """The NACA Table of the auxiliary file, or None."""
        row = self.row
        if row is None or row.main.thickness_distribution != 5:
            return None
        aux = row.aux
        return aux.thickness if getattr(aux, "naca", False) else None

    @property
    def is_naca(self) -> bool:
        row = self.row
        return row is not None and row.main.thickness_distribution == 5

    # -- RowTab -----------------------------------------------------------------------------
    def row_changed(self) -> None:
        for table in (self.naca_table, self.section_table, self.tm_table):
            table.set_row(self.row_id)

    def refresh_inputs(self) -> None:
        row = self.row
        if row is None:
            self.header.setText("")
            return
        m = row.main
        td = m.thickness_distribution
        self.header.setText(f"Thickness distribution: {THICKNESS_DISTRIBUTIONS.get(td, td)} ({td}); change it in "
                            "Row setup.")
        self.pages.setCurrentIndex(0 if td == 5 else 1)
        if td == 5:
            self._refresh_naca()
        else:
            self._refresh_sections()
        self._draw_inputs()

    def refresh_geometry(self) -> None:
        geo = self.geometry
        n = len(geo.thickness) if geo is not None else 0
        keep = self.result_choice.currentData()
        self.result_choice.blockSignals(True)
        self.result_choice.clear()
        self.result_choice.addItem("Hub, mid and tip", "hmt")
        self.result_choice.addItem("All sections", "all")
        for i in range(n):
            self.result_choice.addItem(f"Section {i + 1}", i)
        index = self.result_choice.findData(keep)
        self.result_choice.setCurrentIndex(max(index, 0))
        self.result_choice.blockSignals(False)
        self._draw_result()
        self._draw_inputs()             # section spans come from the run

    def apply_theme(self) -> None:
        self.input_plot.apply_theme()
        self.result_plot.apply_theme()
        self._draw_inputs()
        self._draw_result()

    # -- modified NACA ----------------------------------------------------------------------
    def _refresh_naca(self) -> None:
        table = self._naca_table()
        if table is None:
            self.naca_table.set_columns([("Span", "naca.span")])
            self.naca_table.setEnabled(False)
            self.naca_note.setText("The auxiliary file has no modified NACA block, so T-Blade3 will stop. Switching to "
                                   "this distribution in Row setup adds default control points.")
            self.naca_list.clear()
            return
        self.naca_table.setEnabled(True)
        params = table.columns[1:]
        columns = [("Span", "naca.span")] + [(c, f"naca.{_safe(c)}") for c in params]
        if [p for _, p in columns] != [p for _, p in self.naca_table.columns]:
            self.naca_table.set_columns(columns)
        else:
            self.naca_table.refresh()
        if [self.naca_list.itemText(i) for i in range(self.naca_list.count())] != params:
            self.naca_list.blockSignals(True)
            self.naca_list.clear()
            self.naca_list.addItems(params)
            self.naca_list.setCurrentIndex(params.index(self.naca_param) if self.naca_param in params else 0)
            self.naca_list.blockSignals(False)
            self.naca_param = self.naca_list.currentText()
        n = len(table.data)
        self.naca_note.setText(f"{n} control points along the span; T-Blade3 fits a spline through each column. "
                               "The section table's t/c_max, umxthk, lethk and tethk are not used with this "
                               "distribution.")

    def _naca_selected(self, index: int) -> None:
        if index >= 0:
            self.naca_param = self.naca_list.itemText(index)
            if self.isVisible():
                self._draw_inputs()

    def _add_naca(self, index: int) -> None:
        if self._naca_table() is not None:
            insert_table_row(self.controller, self.row_id, lambda: self.row.aux.thickness, index, "NACA thickness")
            self.naca_table.select_row(index + 1)

    def _remove_naca(self, index: int) -> None:
        table = self._naca_table()
        if table is None:
            return
        if len(table.data) <= 2:
            self.controller.message.emit("The NACA thickness needs at least two control points")
            return
        remove_table_row(self.controller, self.row_id, lambda: self.row.aux.thickness, index, "NACA thickness")

    # -- per-section values -----------------------------------------------------------------
    def _refresh_sections(self) -> None:
        m = self.row.main
        self.section_table.refresh()
        self.tm_table.refresh()
        thk = m.thickness
        has_umax = "u_max" in thk.values and len(thk) and np.all(np.asarray(thk.values["u_max"]) > 0)
        self.section_table.set_read_only_columns({1} if has_umax else set())
        self.section_note.setText("umxthk is greyed out: the u_max control points of the tm/c table (Spanwise "
                                  "controls) set the location of maximum thickness." if has_umax else
                                  "lethk and tethk set the LE and TE thickness, umxthk the location of the maximum.")
        has_tm = "tm/c" in thk.values and len(thk) > 0
        used = has_tm and not m.thickness_multiplier
        self.tm_table.setEnabled(used)
        if not has_tm:
            self.tm_note.setText("This row's tm/c table has no tm/c column: no multiplier.")
        elif m.thickness_multiplier:
            self.tm_note.setText("Not used: the thickness multiplier switch (Row setup) takes the multiplier from the "
                                 "auxiliary file instead.")
        else:
            self.tm_note.setText("t/c is multiplied by (1 + tm/c)." if m.thickness_distribution in (1, 2) else
                                 "The Wennerstrom thickness is multiplied by (1 + tm/c).")

    def _section_value_selected(self, index: int) -> None:
        if 0 <= index < len(SECTION_VALUES):
            self.section_value = SECTION_VALUES[index]
            if self.isVisible():
                self._draw_inputs()

    def _section_values(self) -> np.ndarray:
        m = self.row.main
        v = self.section_value
        return m.sections["tc_max"] if v.attr == "sections.tc_max" else getattr(m, v.attr)

    # -- drawing ----------------------------------------------------------------------------
    def _draw_inputs(self) -> None:
        row = self.row
        if row is None:
            self.points.set_points([], [])
            return
        if self.is_naca:
            table = self._naca_table()
            if table is None or self.naca_param not in table.columns:
                self.points.set_points([], [])
                return
            self.points.movable = "xy"
            self.input_plot.set_labels(x_label=_NACA_TEXT.get(self.naca_param, self.naca_param),
                                       y_label="Span fraction")
            self.points.set_points(table.column(self.naca_param), table.column("span"))
        else:
            values = self._section_values()
            span, from_run = section_span(row, len(values))
            self.points.movable = "x"
            self.input_plot.set_labels(x_label=self.section_value.label,
                                       y_label="Span fraction" if from_run else "Span fraction (evenly spaced)")
            self.points.set_points(values, span)

    def _draw_result(self) -> None:
        geo = self.geometry
        curves = geo.thickness if geo is not None else []
        self.result_plot.remove_matching("thk ")
        n = len(curves)
        if n == 0:
            self.result_note.setText("No thickness_data files in the last run." if geo is not None else "")
            return
        choice = self.result_choice.currentData()
        if choice == "all":
            picked = list(range(n))
        elif choice == "hmt" or choice is None:
            picked = sorted({0, n // 2, n - 1})
        else:
            picked = [int(choice)]
        # the ramp without its faintest end, which hardly shows on the plot background
        colours = ramp_colours(len(picked) + 1)[1:] if len(picked) > 1 else [series_colour(0)]
        span = geo.section_table.get("span")
        for k, (i, colour) in enumerate(zip(picked, colours)):
            data = curves[i]
            if len(data) == 0:
                continue
            labelled = len(picked) <= 3 or k in (0, len(picked) - 1)
            where = f", span {span[i]:.2f}" if span is not None and len(span) == n else ""
            label = f"Section {i + 1}{where}" if labelled and len(picked) > 1 else None
            self.result_plot.curve(f"thk {i}", data[:, 0], data[:, 1], colour, width=1.5, label=label, z=k)
        top = max((float(np.nanmax(curves[i][:, 1])) for i in picked if len(curves[i])), default=0.0)
        if top > 0:                     # headroom so the legend does not cover the curves
            self.result_plot.getPlotItem().setRange(xRange=(0.0, 1.0), yRange=(0.0, 1.4 * top), padding=0.02)
        missing = [i + 1 for i in picked if len(curves[i]) == 0]
        text = "Full thickness over chord, as T-Blade3 wrote it (thickness_data files)."
        if len(picked) > 3:
            text += " Light to dark: hub to tip."
        if missing:
            text += f" No thickness file for sections {missing} (airfoil type other than sect1)."
        self.result_note.setText(text)

    # -- edits ------------------------------------------------------------------------------
    def _point_clicked(self, index: int) -> None:
        (self.naca_table if self.is_naca else self.section_table).select_row(index)

    def _point_dragged(self, index: int, x: float, y: float) -> None:
        if self.row_id is None:
            return
        if self.is_naca:
            self.controller.set_values(self.row_id, {f"naca.{_safe(self.naca_param)}[{index + 1}]": x,
                                                     f"naca.span[{index + 1}]": y}, drag=True)
        else:
            self.controller.set_value(self.row_id, f"{self.section_value.prefix}[{index + 1}]", x, drag=True)
