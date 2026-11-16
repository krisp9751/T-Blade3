"""Camber tab: the camber line defined by curvature control (spancontrolinputs file).

The curvature of the camber line along the chord is a cubic B-spline through chordwise control
points (chord fraction u, value cur). The control points are given at a few span stations and
T-Blade3 splines each of them along the span. The values are relative: at every section T-Blade3
scales the curvature so that the camber line turns from the inlet to the exit blade angle.

Top plot: the control points of the selected station (drag them) and the curve they define.
Bottom left: one control-point column against span. Bottom right: what the last run produced at
every blade section (curvature, camber line or slope against chord).
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QGroupBox, QHeaderView, QLabel, QSplitter,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ...camber import curvature_spline
from ...io.spancontrol import SpanControl, Table
from ...surfaces import span_parameter
from ..controller import Controller
from ..edits import insert_table_row, remove_table_row
from ..plots import DragPoints, Plot, muted_colour, ramp_colours, series_colour
from ..widgets import ParamTable, format_number
from .base import RowTab

# What the results plot can show: title, column of Geometry.camber_data, axis label
QUANTITIES = (("Curvature", 3, "Camber-line curvature, d²v/du²"),
              ("Camber line", 1, "Camber, v (chord fractions)"),
              ("Slope", 2, "Camber-line slope, dv/du"))
MIN_STATIONS = 3            # fewer span stations than this are not offered (T-Blade3 splines them along the span)
_GAP = 1e-4                 # smallest distance kept between neighbouring chord locations when dragging


class CamberTab(RowTab):
    title = "Camber"

    def __init__(self, controller: Controller, parent: QWidget | None = None):
        super().__init__(controller, parent)
        self.station = 0                    # selected span station (row of the curvature table)
        self._filling = False
        self._columns: list[str] = []       # columns offered in column_box

        # -- left: span stations, and the chordwise control points of the selected one ---------
        self.stations = ParamTable(controller, [("Span fraction", "curvature.span")],
                                   on_add=self._add_station, on_remove=self._remove_station, noun="station")
        self.stations.rowSelected.connect(self._station_selected)
        stations_box = QGroupBox("Span stations")
        QVBoxLayout(stations_box).addWidget(self.stations)

        self.points_table = QTableWidget(0, 2)
        self.points_table.setHorizontalHeaderLabels(["Chord fraction, u", "Curvature value"])
        self.points_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.points_table.verticalHeader().setDefaultSectionSize(22)
        self.points_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.points_table.itemChanged.connect(self._point_edited)
        self.points_box = QGroupBox("Points along the chord")
        QVBoxLayout(self.points_box).addWidget(self.points_table)

        self.note = QLabel()
        self.note.setWordWrap(True)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(stations_box, 1)
        left_layout.addWidget(self.points_box, 1)
        left_layout.addWidget(self.note)
        left.setMaximumWidth(300)           # the plots need the width

        # -- right, top: control points of the selected station along the chord ----------------
        self.control_plot = Plot("Chord fraction, u", "Curvature control value (relative)", legend=True)
        self.points = DragPoints(series_colour(0), line=True)
        self.control_plot.addItem(self.points)
        self.points.signals.started.connect(lambda _i: controller.begin_drag())
        self.points.signals.moved.connect(self._point_dragged)
        self.points.signals.clicked.connect(self._point_clicked)

        # -- right, bottom left: one column against span ---------------------------------------
        self.column_box = QComboBox()
        self.column_box.currentIndexChanged.connect(lambda _i: self._draw_span())
        self.span_plot = Plot("", "Span fraction")
        self.span_points = DragPoints(series_colour(0), movable="x", line=True)
        self.span_plot.addItem(self.span_points)
        self.span_points.signals.started.connect(lambda _i: controller.begin_drag())
        self.span_points.signals.moved.connect(self._span_point_dragged)
        self.span_points.signals.clicked.connect(self.stations.select_row)
        span_panel = QWidget()
        span_layout = QVBoxLayout(span_panel)
        span_layout.setContentsMargins(0, 0, 0, 0)
        span_layout.addWidget(self.column_box)
        span_layout.addWidget(self.span_plot, 1)

        # -- right, bottom right: results of the last run --------------------------------------
        self.quantity_box = QComboBox()
        for title, _column, _label in QUANTITIES:
            self.quantity_box.addItem(f"{title} at every section, as built")
        self.quantity_box.currentIndexChanged.connect(lambda _i: self._draw_result())
        self.result_plot = Plot("Chord fraction, u", QUANTITIES[0][2], legend=True)
        result_panel = QWidget()
        result_layout = QVBoxLayout(result_panel)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.addWidget(self.quantity_box)
        result_layout.addWidget(self.result_plot, 1)

        bottom = QSplitter(Qt.Horizontal)
        bottom.addWidget(span_panel)
        bottom.addWidget(result_panel)
        right = QSplitter(Qt.Vertical)
        right.addWidget(self.control_plot)
        right.addWidget(bottom)
        right.setSizes([400, 400])

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([250, 830])
        QVBoxLayout(self).addWidget(splitter)

    # -- RowTab -----------------------------------------------------------------------------
    def row_changed(self) -> None:
        self.station = 0
        self.stations.set_row(self.row_id)

    def refresh_inputs(self) -> None:
        self.stations.refresh()
        table = self._table()
        usable = table is not None and self.row.main.curvature_control == 1
        for widget in (self.stations, self.points_box, self.column_box):
            widget.setEnabled(usable)
        if table is None:
            self.note.setText(self._why_not())
        else:
            self.station = min(self.station, len(table.data) - 1)
            text = (f"{len(table.data)} span stations, {self._n()} control points along the chord. The first and "
                    "last station must cover span 0 to 1. Curvature values are relative: T-Blade3 scales them at "
                    "each section to meet the blade angles.")
            if not usable:
                text = "Curvature control is switched off (Row setup), so these control points are not used. " + text
            self.note.setText(text)
        self._fill_columns()
        self._fill_points()
        self._draw_control()
        self._draw_span()

    def refresh_geometry(self) -> None:
        self._draw_span()
        self._draw_result()

    def apply_theme(self) -> None:
        for plot in (self.control_plot, self.span_plot, self.result_plot):
            plot.apply_theme()
        self._draw_control()
        self._draw_span()
        self._draw_result()

    # -- the curvature table ----------------------------------------------------------------
    def _table(self) -> Table | None:
        """The curvature table of the current row, or None if it has none this tab can edit."""
        row = self.row
        if row is None or not isinstance(row.aux, SpanControl):
            return None
        table = row.aux.curvature
        return table if len(table.data) >= 2 and row.aux.ncp_chord >= 3 else None

    def _why_not(self) -> str:
        row = self.row
        if row is None:
            return "No row selected."
        if row.aux is None:
            return ("This row has no spancontrolinputs file: its camber line follows from the inlet and exit "
                    "angles alone.")
        if not isinstance(row.aux, SpanControl):
            return ("This row uses the older controlinputs file (control points per section). Its values are "
                    "listed under Camber in the Sensitivities and Design variables tabs.")
        return "The spancontrolinputs file of this row has no curvature control points."

    def _n(self) -> int:
        return self.row.aux.ncp_chord

    def _names(self, k: int) -> tuple[str | None, str | None]:
        """Parameter names (location, value) of chordwise point ``k`` (0-based) at the selected station.

        None where the file has no such number: the end locations are fixed at 0 and 1, and the
        oldest format has no cur1 (taken as zero).
        """
        columns, i = self._table().columns, self.station + 1
        u = f"u{k + 1}[{i}]" if f"u{k + 1}" in columns else None
        cur = f"cur{k + 1}[{i}]" if f"cur{k + 1}" in columns else None
        return u, cur

    def _station_points(self, i: int) -> tuple[np.ndarray, np.ndarray]:
        """Chord locations and curvature values of the control points at station ``i``."""
        table, n = self._table(), self._n()
        value = lambda name, default: table.data[i, table.columns.index(name)] if name in table.columns else default  # noqa: E731
        u = np.array([0.0] + [value(f"u{k}", np.nan) for k in range(2, n)] + [1.0])
        cur = np.array([value(f"cur{k}", 0.0) for k in range(1, n + 1)])
        return u, cur

    # -- widgets ----------------------------------------------------------------------------
    def _fill_columns(self) -> None:
        table = self._table()
        columns = list(table.columns[1:]) if table is not None else []
        if columns == self._columns:
            return
        keep = self.column_box.currentData()
        self._columns = columns
        self.column_box.blockSignals(True)
        self.column_box.clear()
        for name in columns:
            self.column_box.addItem(f"{name} along the span", name)
        index = columns.index(keep) if keep in columns else next((j for j, c in enumerate(columns) if c.startswith("cur")), 0)
        self.column_box.setCurrentIndex(index if columns else -1)
        self.column_box.blockSignals(False)

    def _fill_points(self) -> None:
        table = self._table()
        self._filling = True
        try:
            if table is None:
                self.points_table.setRowCount(0)
                return
            u, cur = self._station_points(self.station)
            self.points_box.setTitle(f"Station {self.station + 1} (span {format_number(table.data[self.station, 0])}): "
                                     "points along the chord")
            self.points_table.setRowCount(len(u))
            for k in range(len(u)):
                for j, (value, name) in enumerate(zip((u[k], cur[k]), self._names(k))):
                    item = self.points_table.item(k, j)
                    if item is None:
                        item = QTableWidgetItem()
                        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                        self.points_table.setItem(k, j, item)
                    text = format_number(value)
                    if item.text() != text:
                        item.setText(text)
                    item.setFlags(item.flags() | Qt.ItemIsEditable if name else item.flags() & ~Qt.ItemIsEditable)
                    item.setToolTip("" if name else "Fixed by T-Blade3")
        finally:
            self._filling = False

    def _draw_control(self) -> None:
        table = self._table()
        if table is None:
            self.points.set_points([], [])
            self.control_plot.remove_matching("station")
            return
        lo, hi = float(table.data[:, self._n() - 1:].min()), float(table.data[:, self._n() - 1:].max())
        hi = max(hi, lo + 1e-9)
        self.control_plot.setYRange(lo, hi + 0.3 * (hi - lo), padding=0.05)      # empty band at the top for the legend
        n = len(table.data)
        names = set()
        other_labelled = False
        for i in range(n):
            u, cur = self._station_points(i)
            name = f"station{i}"
            names.add(name)
            self.control_plot.remove(name)          # recreate: the legend label depends on the selection
            x, y = curvature_spline(u, cur)
            if i == self.station:
                self.control_plot.curve(name, x, y, series_colour(0), label=f"Station {i + 1}, the spline T-Blade3 uses",
                                        z=2)
                self.points.set_points(u, cur)
            else:
                self.control_plot.curve(name, x, y, muted_colour(), width=1.0,
                                        label=None if other_labelled else "Other stations")
                other_labelled = True
        self.control_plot.remove_matching("station", keep=names)

    def _draw_span(self) -> None:
        table, column = self._table(), self.column_box.currentData()
        if table is None or column not in table.columns:
            self.span_points.set_points([], [])
            self.span_plot.remove("built")
            return
        what = "Chord location" if column.startswith("u") else "Curvature value"
        self.span_plot.set_labels(x_label=f"{what} {column}", title="Stations (points), sections (line)")
        self.span_points.set_points(table.column(column), table.data[:, 0])
        geo = self.geometry
        built = geo.curvature_controls if geo is not None else None
        n = self._n()
        if built is not None and built.shape[1] == 2 * n and self.row.is_current:
            k = int(column.lstrip("ucr"))
            values = built[:, k - 1] if column.startswith("u") else built[:, n + k - 1]
            self.span_plot.curve("built", values, self._span(geo), muted_colour(), z=1)
        else:
            self.span_plot.remove("built")

    def _draw_result(self) -> None:
        geo = self.geometry
        data = geo.camber_data if geo is not None else None
        _title, column, label = QUANTITIES[max(self.quantity_box.currentIndex(), 0)]
        self.result_plot.set_labels(y_label=label)
        self.result_plot.remove_matching("sec")
        if data is None:
            return
        colours = ramp_colours(len(data))
        for i, section in enumerate(data):
            end = "Hub section" if i == 0 else "Tip section" if i == len(data) - 1 else None
            self.result_plot.curve(f"sec{i}", section[:, 0], section[:, column], colours[i], width=1.5, label=end)
        lo, hi = float(data[:, :, column].min()), float(data[:, :, column].max())
        hi = max(hi, lo + 1e-9)
        self.result_plot.setYRange(lo, hi + 0.3 * (hi - lo), padding=0.05)      # room for the legend

    @staticmethod
    def _span(geo) -> np.ndarray:
        span = geo.section_table.get("span")
        if span is not None and len(span) == geo.nsec and np.all(np.isfinite(span)):
            return np.asarray(span, dtype=float)
        return span_parameter(geo.sections)

    # -- selection --------------------------------------------------------------------------
    def _station_selected(self, index: int) -> None:
        table = self._table()
        if table is None or not 0 <= index < len(table.data) or index == self.station:
            return
        self.station = index
        self._fill_points()
        self._draw_control()

    def _point_clicked(self, k: int) -> None:
        """A control point was clicked: show its curvature value along the span."""
        self.points_table.selectRow(k)
        index = self.column_box.findData(f"cur{k + 1}")
        if index >= 0:
            self.column_box.setCurrentIndex(index)

    # -- edits ------------------------------------------------------------------------------
    def _point_edited(self, item: QTableWidgetItem) -> None:
        if self._filling or self.row_id is None:
            return
        name = self._names(item.row())[item.column()]
        try:
            value = float(item.text())
        except ValueError:
            value = None
        if name is None or value is None:
            self._fill_points()             # fixed cell or not a number: restore
            return
        self.controller.set_value(self.row_id, name, value)

    def _point_dragged(self, k: int, x: float, y: float) -> None:
        if self.row_id is None or self._table() is None:
            return
        u_name, cur_name = self._names(k)
        values = {}
        if cur_name:
            values[cur_name] = y
        if u_name:                          # keep the chord locations in order
            u, _cur = self._station_points(self.station)
            values[u_name] = float(min(max(x, u[k - 1] + _GAP), u[k + 1] - _GAP))
        if values:
            self.controller.set_values(self.row_id, values, drag=True)

    def _span_point_dragged(self, i: int, x: float, _y: float) -> None:
        column = self.column_box.currentData()
        if self.row_id is not None and column:
            self.controller.set_value(self.row_id, f"{column}[{i + 1}]", x, drag=True)

    def _add_station(self, index: int) -> None:
        if self._table() is None:
            return
        new = insert_table_row(self.controller, self.row_id, lambda: self.row.aux.curvature, index, "camber")
        self.stations.select_row(new)

    def _remove_station(self, index: int) -> None:
        table = self._table()
        if table is None:
            return
        if len(table.data) <= MIN_STATIONS:
            self.controller.message.emit(f"The camber line needs at least {MIN_STATIONS} span stations")
            return
        remove_table_row(self.controller, self.row_id, lambda: self.row.aux.curvature, index, "camber")
