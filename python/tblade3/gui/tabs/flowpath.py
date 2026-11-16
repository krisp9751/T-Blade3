"""Flow path tab: streamlines, LE and TE curves, offsets, and the meridional (x, r) view of all rows."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QGroupBox, QLabel, QSpinBox, QSplitter, QVBoxLayout, QWidget

from ...surfaces import edge_points
from ..controller import Controller
from ..plots import DragPoints, Plot, muted_colour, series_colour
from ..widgets import ParamTable, ValueEdit
from .base import RowTab


class FlowPathTab(RowTab):
    title = "Flow path"

    def __init__(self, controller: Controller, parent: QWidget | None = None):
        super().__init__(controller, parent)

        # -- left: inputs ---------------------------------------------------------------------
        self.le_te_table = ParamTable(controller, [("x LE", "le_te.x_le"), ("r LE", "le_te.r_le"),
                                                   ("x TE", "le_te.x_te"), ("r TE", "le_te.r_te")])
        le_te_box = QGroupBox("LE and TE curves")
        QVBoxLayout(le_te_box).addWidget(self.le_te_table)

        self.offset_edits = {name: ValueEdit(controller, name) for name in
                             ("hub_offset", "tip_offset", "hub_inflation_offset", "tip_inflation_offset")}
        offsets_box = QGroupBox("Offsets")
        form = QFormLayout(offsets_box)
        for label, name in (("Hub offset", "hub_offset"), ("Tip offset", "tip_offset"),
                            ("Hub inflation offset", "hub_inflation_offset"),
                            ("Tip inflation offset", "tip_inflation_offset")):
            form.addRow(label, self.offset_edits[name])

        self.streamline_spin = QSpinBox()
        self.streamline_spin.setMinimum(1)
        self.streamline_spin.valueChanged.connect(self._streamline_selected)
        self.streamline_table = ParamTable(controller, [("x", "streamline1.x"), ("r", "streamline1.r")])
        self.streamline_note = QLabel()
        stream_box = QGroupBox("Streamlines")
        stream_layout = QVBoxLayout(stream_box)
        stream_form = QFormLayout()
        stream_form.addRow("Streamline (1 = hub)", self.streamline_spin)
        stream_layout.addLayout(stream_form)
        stream_layout.addWidget(self.streamline_table)
        stream_layout.addWidget(self.streamline_note)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(le_te_box, 3)
        left_layout.addWidget(offsets_box, 0)
        left_layout.addWidget(stream_box, 3)

        # -- right: meridional plot -----------------------------------------------------------
        self.plot = Plot("x (non-dimensional)", "r (non-dimensional)", equal_aspect=True, legend=True)
        self.le_points = DragPoints(series_colour(0), line=True)
        self.te_points = DragPoints(series_colour(1), line=True)
        for points, prefix in ((self.le_points, "le"), (self.te_points, "te")):
            self.plot.addItem(points)
            points.signals.started.connect(lambda _i: controller.begin_drag())
            points.signals.moved.connect(lambda i, x, y, prefix=prefix: self._point_dragged(prefix, i, x, y))
            points.signals.clicked.connect(self.le_te_table.select_row)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(self.plot)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([380, 700])
        layout = QVBoxLayout(self)
        layout.addWidget(splitter)

    # -- RowTab -----------------------------------------------------------------------------
    def row_changed(self) -> None:
        self.le_te_table.set_row(self.row_id)
        for edit in self.offset_edits.values():
            edit.set_row(self.row_id)
        row = self.row
        self.streamline_spin.blockSignals(True)
        self.streamline_spin.setMaximum(max(row.main.n_streamlines if row else 1, 1))
        self.streamline_spin.setValue(1)
        self.streamline_spin.blockSignals(False)
        self._streamline_selected(1)

    def refresh_inputs(self) -> None:
        self.le_te_table.refresh()
        self.streamline_table.refresh()
        for edit in self.offset_edits.values():
            edit.refresh()
        self._draw_inputs()

    def refresh_geometry(self) -> None:
        geo, row = self.geometry, self.row
        if geo is None or row is None:
            self.plot.remove("built le")
            self.plot.remove("built te")
            return
        scale = row.main.scale_factor
        le, te = edge_points(geo.sections)
        for name, edge, slot, label in (("built le", le, 0, "LE as built"), ("built te", te, 1, "TE as built")):
            pts = edge / scale
            self.plot.curve(name, pts[:, 0], np.hypot(pts[:, 1], pts[:, 2]), series_colour(slot), width=2.5,
                            label=label, z=5)

    def apply_theme(self) -> None:
        self.plot.apply_theme()
        self._draw_inputs()

    # -- drawing ----------------------------------------------------------------------------
    def _draw_inputs(self) -> None:
        case = self.controller.case
        keep: set[str] = set()
        if case is not None:
            for rid, row in case.rows.items():
                current = rid == self.row_id
                n = row.main.n_streamlines
                for k, line in enumerate(row.main.streamlines):
                    edge = k in (0, n - 1)
                    selected = current and k == self.streamline_spin.value() - 1
                    name = f"stream {rid} {k}"
                    keep.add(name)
                    colour = series_colour(2) if selected else muted_colour()
                    self.plot.curve(name, line[:, 0], line[:, 1], colour,
                                    width=2.0 if (edge or selected) else 1.0, z=3 if selected else (1 if current else 0))
                if not current:
                    for j, tag in ((0, "le"), (2, "te")):
                        name = f"other {rid} {tag}"
                        keep.add(name)
                        self.plot.curve(name, row.main.le_te[:, j], row.main.le_te[:, j + 1], muted_colour(),
                                        width=1.5, dashed=True)
        self.plot.remove_matching("stream ", keep)
        self.plot.remove_matching("other ", keep)
        row = self.row
        le_te = row.main.le_te if row is not None else np.zeros((0, 4))
        self.le_points.set_points(le_te[:, 0], le_te[:, 1])
        self.te_points.set_points(le_te[:, 2], le_te[:, 3])

    # -- edits ------------------------------------------------------------------------------
    def _point_dragged(self, prefix: str, index: int, x: float, y: float) -> None:
        if self.row_id is None:
            return
        self.controller.set_values(self.row_id, {f"le_te.x_{prefix}[{index + 1}]": x,
                                                 f"le_te.r_{prefix}[{index + 1}]": y}, drag=True)

    def _streamline_selected(self, number: int) -> None:
        self.streamline_table.set_columns([("x", f"streamline{number}.x"), ("r", f"streamline{number}.r")])
        self.streamline_table.set_row(self.row_id)
        row = self.row
        if row is not None and 1 <= number <= row.main.n_streamlines:
            self.streamline_note.setText(f"{len(row.main.streamlines[number - 1])} points")
        if self.isVisible():
            self._draw_inputs()
