"""Sensitivities tab: pick a parameter and see d(blade surface)/d(parameter) as a contour on the 3D view.

The derivative is T-Blade3's analytic one where it exists, otherwise a central finite difference
(two extra runs in the background). Line plots show how it varies along the span, and the stagger
and throat derivatives T-Blade3 writes for the analytic parameters.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFormLayout, QGroupBox, QLabel, QSplitter, QVBoxLayout, QWidget

from ...surfaces import COMPONENT_LABELS, COMPONENTS, component, span_parameter
from ..backend import sensitivity_field
from ..controller import Controller
from ..plots import Plot, series_colour
from ..widgets import ParameterTree, format_number
from .base import RowTab


class SensitivitiesTab(RowTab):
    title = "Sensitivities"

    def __init__(self, controller: Controller, parent: QWidget | None = None):
        super().__init__(controller, parent)
        self.view = None                    # the main window's 3D view (attach_view)
        self.selected: str | None = None    # local parameter name, kept across rows when it exists there
        self._coloured: str | None = None   # row whose blade is currently coloured by this tab

        # -- left: parameter picker -----------------------------------------------------------
        self.picker = ParameterTree()
        self.picker.selected.connect(self._parameter_selected)
        left = self.picker

        # -- right: what is shown, and line plots ---------------------------------------------
        self.component_box = QComboBox()
        for which in COMPONENTS:
            self.component_box.addItem(COMPONENT_LABELS[which].capitalize(), which)
        self.component_box.currentIndexChanged.connect(lambda _i: self._show())
        self.name_label = QLabel("Pick a parameter on the left")
        self.method_label = QLabel()
        self.peak_label = QLabel()
        for label in (self.name_label, self.method_label, self.peak_label):
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        box = QGroupBox("Shown on the blade")
        form = QFormLayout(box)
        form.addRow("Parameter", self.name_label)
        form.addRow("Component", self.component_box)
        form.addRow("Derivative", self.method_label)
        form.addRow("Largest", self.peak_label)

        self.span_plot = Plot("Span fraction", "", title="Range of the derivative over each section", legend=True)
        self.stagger_plot = Plot("Span fraction", "per unit", title="Derivative of the section stagger angle")
        self.throat_plot = Plot("Span fraction", "per unit", title="Derivative of the section throat")
        self.stagger_plot.hide()
        self.throat_plot.hide()
        self.aux_note = QLabel()
        self.aux_note.setWordWrap(True)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(box)
        right_layout.addWidget(self.span_plot, 3)
        right_layout.addWidget(self.stagger_plot, 2)
        right_layout.addWidget(self.throat_plot, 2)
        right_layout.addWidget(self.aux_note)
        right_layout.addStretch(0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([380, 620])
        QVBoxLayout(self).addWidget(splitter)

        controller.sensitivityReady.connect(self._ready)
        controller.sensitivityFailed.connect(self._failed)

    def attach_view(self, view) -> None:
        self.view = view

    # -- RowTab -----------------------------------------------------------------------------
    def row_changed(self) -> None:
        self._clear_colour()

    def refresh_inputs(self) -> None:
        row = self.row
        self.picker.set_parameters(row.parameters if row is not None else None)
        self.picker.set_unused(row.unused_parameters() if row is not None else {})
        if self.picker.current != self.selected:
            self.selected = self.picker.current      # the parameter no longer exists (other row, table shrank)
        self._describe()

    def refresh_geometry(self) -> None:
        self._request()

    def apply_theme(self) -> None:
        for plot in (self.span_plot, self.stagger_plot, self.throat_plot):
            plot.apply_theme()
        self._show()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._request()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._clear_colour()

    # -- parameter picker -------------------------------------------------------------------
    def _parameter_selected(self, name: str) -> None:
        if name == self.selected:
            return
        self.selected = name
        self._describe()
        self._request()

    def select(self, name: str) -> None:
        """Select a parameter by its local name (used by other tabs and tests)."""
        self.picker.select(name)

    # -- showing a sensitivity --------------------------------------------------------------
    def _parameter(self):
        row = self.row
        return row.parameters.get(self.selected) if row is not None and self.selected else None

    def _describe(self) -> None:
        p = self._parameter()
        if p is None:
            self.name_label.setText("Pick a parameter on the left")
            self.method_label.setText("")
            self.peak_label.setText("")
            return
        self.name_label.setText(f"{p.name} = {format_number(p.value)}")

    def _request(self) -> None:
        """Ask for the derivative of the selected parameter; ``_ready`` shows it when it is there."""
        row, p = self.row, self._parameter()
        if not self.isVisible() or row is None or p is None:
            return
        if self._no_effect(row, p):
            return
        if row.geometry is None or not row.is_current or self.controller.is_building(self.row_id):
            self.method_label.setText("Waiting for the geometry to be rebuilt")
            return
        if row.derivative_method(p.name) == "fd" and p.name not in row._fd_cache:
            self.method_label.setText("Finite difference: running T-Blade3 twice…")
        self.controller.request_sensitivity(self.row_id, p.name)

    def _no_effect(self, row, p) -> bool:
        """True (and say so) if T-Blade3 ignores the parameter with the current switches: nothing to compute."""
        reason = row.unused_reason(p.name)
        if reason:
            self.method_label.setText(f"No effect on the blade: {reason}.")
            self.peak_label.setText("")
            self.aux_note.setText("")
            self._clear_colour()
            self._clear_plots()
        return bool(reason)

    def _ready(self, row_id: str, name: str) -> None:
        if row_id == self.row_id and name == self.selected and self.isVisible():
            self._show()

    def _failed(self, row_id: str, name: str, text: str) -> None:
        if row_id == self.row_id and name == self.selected:
            self.method_label.setText("Not available: " + text.splitlines()[0])
            self.peak_label.setText("")
            self._clear_colour()
            self._clear_plots()

    def _show(self) -> None:
        row, p = self.row, self._parameter()
        if not self.isVisible() or row is None or p is None or row.geometry is None or not row.is_current:
            return
        if self._no_effect(row, p):
            return
        method = row.derivative_method(p.name)
        if method == "fd" and p.name not in row._fd_cache:
            return                          # still being computed
        geo = row.geometry
        which = self.component_box.currentData()
        dxyz = row.dxyz(p.name)
        values = component(dxyz, geo.sections, which)
        units = f"{row.main.units} per unit"
        self.method_label.setText("Analytic, from T-Blade3" if method == "analytic"
                                  else "Central finite difference (two extra runs)")
        sec, pt = np.unravel_index(np.abs(values).argmax(), values.shape)
        self.peak_label.setText(f"{values[sec, pt]:.4g} {units}, on section {sec + 1} of {geo.nsec}")
        if self.view is not None:
            self._clear_colour()
            self.view.set_scalar(self.row_id, sensitivity_field(row, p.name, which),
                                 f"d(surface)/d({p.name}): {COMPONENT_LABELS[which]}", units)
            self._coloured = self.row_id

        span = self._span(geo)
        self.span_plot.set_labels(y_label=units, title=f"{COMPONENT_LABELS[which].capitalize()}: range over each section")
        hi, lo = values.max(axis=1), values.min(axis=1)
        self.span_plot.curve("max", span, hi, series_colour(0), label="Largest on the section")
        if which == "magnitude":
            self.span_plot.remove("min")
            lo = np.zeros_like(hi)
        else:
            self.span_plot.curve("min", span, lo, series_colour(1), label="Smallest on the section")
        bottom, top = float(lo.min()), float(hi.max())
        room = 0.45 * max(top - bottom, 1e-12)          # empty band at the top for the legend
        self.span_plot.setYRange(bottom, top + room, padding=0.04)

        ders = geo.derivatives
        shown = False
        for plot, table, label in ((self.stagger_plot, ders.stagger if ders else {}, "per unit"),
                                   (self.throat_plot, ders.throat if ders else {}, "per unit")):
            data = table.get(p.deriv[:2]) if (method == "analytic" and p.deriv is not None) else None
            if data is not None and data.ndim == 2 and p.deriv[2] <= data.shape[1] and len(data) == len(span):
                plot.curve("d", span, data[:, p.deriv[2] - 1], series_colour(0), symbol="o")
                plot.show()
                shown = True
            else:
                plot.remove("d")
                plot.hide()
        self.aux_note.setText("" if shown else "T-Blade3 gives no stagger or throat derivative for this parameter.")

    @staticmethod
    def _span(geo) -> np.ndarray:
        span = geo.section_table.get("span")
        if span is not None and len(span) == geo.nsec and np.all(np.isfinite(span)):
            return np.asarray(span, dtype=float)
        return span_parameter(geo.sections)

    def _clear_plots(self) -> None:
        for plot, names in ((self.span_plot, ("max", "min")), (self.stagger_plot, ("d",)), (self.throat_plot, ("d",))):
            for name in names:
                plot.remove(name)
        self.stagger_plot.hide()
        self.throat_plot.hide()

    def _clear_colour(self) -> None:
        if self.view is not None and self._coloured is not None:
            if self.controller.case is not None and self._coloured in self.controller.case.rows:
                self.view.set_scalar(self._coloured, None)
        self._coloured = None
