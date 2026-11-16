"""Airfoils tab (results only): the 2D blade sections and the section table of the last run.

The sections are drawn as T-Blade3 writes them in blade.<i>.<row>.<cn>: m′ (meridional length over
radius) against θ in radians, with equal scales. The meanline is the midpoint of the two sides
(T-Blade3 puts the suction and pressure side points at the same chord fractions either side of the
camber line). Selecting a row of the table highlights that section.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QHBoxLayout, QHeaderView, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from ..controller import Controller
from ..plots import Plot, ramp_colours, series_colour
from ..widgets import format_number
from .base import RowTab

# Section-table columns in display order, with headers; {u} is the length unit of the row.
TABLE_COLUMNS = (
    ("section", "Section"), ("span", "Span"), ("chord", "Chord ({u})"), ("meridional_chord", "Meridional chord"),
    ("beta_z_le", "βz LE (deg)"), ("beta_z_te", "βz TE (deg)"), ("beta_m_le", "βm LE (deg)"),
    ("beta_m_te", "βm TE (deg)"), ("throat", "Throat ({u})"), ("throat_location", "Throat at"),
    ("pitch", "Pitch (rad)"), ("zweifel", "Zweifel"), ("le_thickness", "LE thickness ({u})"),
    ("max_thickness", "Max thickness ({u})"), ("te_thickness", "TE thickness ({u})"), ("lethk", "lethk·c ({u})"),
    ("tethk", "tethk·c ({u})"), ("area", "Area ({u}²)"), ("sweep", "Sweep, m′ offset"), ("lean", "Lean, θ offset"),
)


class AirfoilsTab(RowTab):
    title = "Airfoils"

    def __init__(self, controller: Controller, parent: QWidget | None = None):
        super().__init__(controller, parent)
        self._filling = False
        self.highlight: int | None = None

        # -- left: which sections ------------------------------------------------------------
        self.section_list = QListWidget()
        self.section_list.itemChanged.connect(lambda _item: self._draw())
        buttons = QHBoxLayout()
        for text, how in (("All", "all"), ("Hub, mid, tip", "hmt"), ("None", "none")):
            button = QPushButton(text)
            button.clicked.connect(lambda _c=False, how=how: self.check(how))
            buttons.addWidget(button)
        self.meanline_box = QCheckBox("Meanlines")
        self.meanline_box.setChecked(True)
        self.meanline_box.toggled.connect(lambda _on: self._draw())
        left = QWidget()
        left.setMaximumWidth(270)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("Sections (1 = hub)"))
        left_layout.addWidget(self.section_list, 1)
        left_layout.addLayout(buttons)
        left_layout.addWidget(self.meanline_box)

        # -- right: plot and table -----------------------------------------------------------
        self.plot = Plot("m′ (meridional length / radius)", "θ (rad)", equal_aspect=True, legend=True)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.table = QTableWidget(0, len(TABLE_COLUMNS))
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(22)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.currentCellChanged.connect(lambda r, *_: self._row_selected(r))
        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.addWidget(self.plot, 1)
        top_layout.addWidget(self.note)
        right = QSplitter(Qt.Vertical)
        right.addWidget(top)
        right.addWidget(self.table)
        right.setSizes([560, 300])

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([250, 830])
        QVBoxLayout(self).addWidget(splitter)

    # -- RowTab -----------------------------------------------------------------------------
    def refresh_geometry(self) -> None:
        geo = self.geometry
        n = len(geo.sections_2d) if geo is not None else 0
        span = geo.section_table.get("span") if geo is not None else None
        if self.section_list.count() != n:
            self._filling = True
            self.section_list.clear()
            for i in range(n):
                item = QListWidgetItem()
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Unchecked)
                self.section_list.addItem(item)
            self._filling = False
            self.check("hmt")
        self._filling = True
        for i in range(n):
            where = f"  (span {span[i]:.2f})" if span is not None and len(span) == n else ""
            self.section_list.item(i).setText(f"Section {i + 1}{where}")
        self._filling = False
        self._fill_table()
        self._draw()

    def apply_theme(self) -> None:
        self.plot.apply_theme()
        self._draw()

    # -- selection --------------------------------------------------------------------------
    def check(self, how: str) -> None:
        """Tick sections: "all", "none" or "hmt" (hub, mid and tip)."""
        n = self.section_list.count()
        picked = set(range(n)) if how == "all" else ({0, n // 2, n - 1} if how == "hmt" and n else set())
        self._filling = True
        for i in range(n):
            self.section_list.item(i).setCheckState(Qt.Checked if i in picked else Qt.Unchecked)
        self._filling = False
        self._draw()

    def checked(self) -> list[int]:
        return [i for i in range(self.section_list.count()) if self.section_list.item(i).checkState() == Qt.Checked]

    def _row_selected(self, index: int) -> None:
        self.highlight = index if index >= 0 else None
        self._draw()

    # -- drawing ----------------------------------------------------------------------------
    def _fill_table(self) -> None:
        geo, row = self.geometry, self.row
        t = geo.section_table if geo is not None else {}
        columns = [(key, header) for key, header in TABLE_COLUMNS if key in t]
        units = row.main.units if row is not None else "mm"
        n = max((len(t[k]) for k, _ in columns), default=0)
        keep = self.table.currentRow()
        self.table.blockSignals(True)
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels([header.format(u=units) for _, header in columns])
        self.table.setRowCount(n)
        for j, (key, _) in enumerate(columns):
            for i, value in enumerate(t[key]):
                if isinstance(value, str | np.str_):
                    text = str(value)
                elif key == "section":
                    text = str(int(value))
                else:
                    text = "" if not np.isfinite(value) else format_number(float(np.round(value, 6)))
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(i, j, item)
        if 0 <= keep < n:
            self.table.selectRow(keep)
        self.table.blockSignals(False)

    def _draw(self) -> None:
        if self._filling:
            return
        geo = self.geometry
        self.plot.remove_matching("sec ")
        self.plot.remove_matching("mean ")
        if geo is None or not geo.sections_2d:
            self.note.setText("No 2D sections yet." if geo is None else "The last run wrote no 2D section files.")
            return
        picked = self.checked()
        colours = ramp_colours(len(picked) + 1)[1:] if len(picked) > 1 else [series_colour(0)]   # faintest end dropped
        h = self.highlight if self.highlight is not None and 0 <= self.highlight < len(geo.sections_2d) else None
        labelled = set(picked) if len(picked) <= 4 else {picked[0], picked[-1]}
        legend = len(picked) > 1 or (h is not None and picked != [h])
        for k, (i, colour) in enumerate(zip(picked, colours)):
            pts = geo.sections_2d[i]
            label = f"Section {i + 1}" if i in labelled and legend else None
            self.plot.curve(f"sec {i}", pts[:, 0], pts[:, 1], colour, width=1.5, label=label, z=k)
            if self.meanline_box.isChecked():
                mean = 0.5 * (pts + pts[::-1])[: len(pts) // 2 + 1]
                self.plot.curve(f"mean {i}", mean[:, 0], mean[:, 1], colour, width=1.0, dashed=True, z=k)
        if h is not None:
            pts = geo.sections_2d[h]
            self.plot.curve("sec highlight", pts[:, 0], pts[:, 1], series_colour(1), width=3.0,
                            label=f"Selected: section {h + 1}", z=100)
        text = "Equal scales. Dashed: meanlines (midpoints of the two sides)." if self.meanline_box.isChecked() else \
            "Equal scales."
        if len(picked) > 4:
            text += " Light to dark: hub to tip."
        self.note.setText(text)
