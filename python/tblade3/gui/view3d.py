"""The 3D view: structured surfaces with optional scalar colouring, drawn with PyVista.

The view knows nothing about T-Blade3. It draws ``Surface`` objects (see tblade3.surfaces), grouped
under a key (one key per blade row), so another geometry source such as ESP can use it unchanged.
"""
from __future__ import annotations

import numpy as np
import pyvista as pv
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
from pyvistaqt import QtInteractor

from ..surfaces import Surface, rotation_about_x

# Colours (light, dark theme)
_BLADE = ("#5B7FA6", "#7FA3CC")
_BLADE_DIM = ("#B8C2CE", "#4A5563")
_HUB = ("#C9C7C1", "#5A5A58")
_CASING = ("#D8D6D0", "#6A6A68")
_LINE = ("#14213D", "#E8EAF0")
_SEQ = ("#cde2fb", "#0d366b")               # sequential: one hue, light to dark
_DIV = ("#2a78d6", "#f0efec", "#e34948")    # diverging: blue, neutral grey, red


def is_dark() -> bool:
    app = QApplication.instance()
    return bool(app) and app.palette().window().color().lightness() < 128


def _rgb(hex_colour: str) -> np.ndarray:
    h = hex_colour.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=float)


def lookup_table(lo: float, hi: float) -> pv.LookupTable:
    """Diverging colours when the range spans zero (centred on zero), else one hue light to dark."""
    x = np.linspace(0.0, 1.0, 256)[:, None]
    if lo < 0.0 < hi:
        m = max(abs(lo), abs(hi))
        lo, hi = -m, m
        a, mid, b = (_rgb(c) for c in _DIV)
        rgb = np.where(x < 0.5, a + (mid - a) * (x / 0.5), mid + (b - mid) * ((x - 0.5) / 0.5))
    else:
        a, b = (_rgb(c) for c in _SEQ)
        if hi <= 0.0:                       # all negative: strongest colour at the low end
            a, b = b, a
        rgb = a + (b - a) * x
    values = np.concatenate([rgb, np.full((256, 1), 255.0)], axis=1).astype(np.uint8)
    lut = pv.LookupTable()
    lut.values = values
    lut.scalar_range = (lo, hi) if hi > lo else (lo - 1.0, lo + 1.0)
    return lut


def _grid(points: np.ndarray) -> pv.StructuredGrid:
    """(nu, nv, 3) points -> structured surface; point (i, j) is index i * nv + j."""
    nu, nv = points.shape[:2]
    grid = pv.StructuredGrid()
    grid.points = points.reshape(-1, 3)
    grid.dimensions = (nv, nu, 1)
    return grid


class View3D(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.plotter = QtInteractor(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.plotter.interactor)
        self._actors: dict[str, list] = {}          # key -> actors
        self._scalar: dict[str, tuple[np.ndarray, str, str] | None] = {}
        self._surfaces: dict[str, list[Surface]] = {}
        self._lines: dict[str, list[np.ndarray]] = {}
        self._dim: set[str] = set()
        self._bars: dict[str, str] = {}             # key -> title of its scalar bar
        self.show_casing = False
        self.show_hub = True
        self._framed: set[str] = set()       # keys the camera has been fitted to since the last clear
        self.apply_theme()
        self.plotter.add_axes(interactive=False)

    def apply_theme(self) -> None:
        colour = QApplication.instance().palette().window().color() if QApplication.instance() else None
        self.plotter.set_background(colour.name() if colour else "white")
        for key in list(self._surfaces):
            self._redraw(key)

    # -- content ----------------------------------------------------------------------------
    def set_surfaces(self, key: str, surfaces: list[Surface], lines: list[np.ndarray] | None = None) -> None:
        """Replace everything drawn under ``key``. ``lines`` are polylines (n, 3), e.g. LE and TE."""
        self._surfaces[key] = surfaces
        self._lines[key] = lines or []
        self._redraw(key)
        if key not in self._framed:          # a row seen for the first time: fit the view to everything
            self._framed.add(key)
            self.reset_camera()

    def set_scalar(self, key: str, values: np.ndarray | None, title: str = "", units: str = "") -> None:
        """Colour the blade surfaces of ``key`` by ``values`` (same grid as the surface points), or clear.

        ``title`` is shown at the top of the view, ``units`` on the colour bar.
        """
        self._scalar[key] = None if values is None else (np.asarray(values), title, units)
        self._redraw(key)

    def set_dimmed(self, keys: set[str]) -> None:
        """Draw the blades of these keys in a muted colour (rows that are not selected)."""
        changed = keys ^ self._dim
        self._dim = set(keys)
        for key in changed:
            if key in self._surfaces:
                self._redraw(key)

    def remove(self, key: str) -> None:
        for actor in self._actors.pop(key, []):
            self.plotter.remove_actor(actor, render=False)
        self._surfaces.pop(key, None)
        self._lines.pop(key, None)
        self._scalar.pop(key, None)
        self.plotter.render()

    def clear(self) -> None:
        for key in list(self._surfaces):
            self.remove(key)
        self._framed.clear()

    def set_visibility(self, hub: bool | None = None, casing: bool | None = None) -> None:
        if hub is not None:
            self.show_hub = hub
        if casing is not None:
            self.show_casing = casing
        for key in list(self._surfaces):
            self._redraw(key)

    def reset_camera(self) -> None:
        self.plotter.view_isometric()
        self.plotter.reset_camera()

    # -- drawing ----------------------------------------------------------------------------
    def _redraw(self, key: str) -> None:
        p = self.plotter
        for actor in self._actors.pop(key, []):
            p.remove_actor(actor, render=False)
        bar = self._bars.pop(key, None)
        if bar is not None and bar in p.scalar_bars:
            p.remove_scalar_bar(bar, render=False)
        p.remove_actor(f"title {key}", render=False)
        dark = int(is_dark())
        actors = []
        scalar = self._scalar.get(key)
        for surface in self._surfaces.get(key, []):
            if surface.kind == "hub" and not self.show_hub:
                continue
            if surface.kind == "casing" and not self.show_casing:
                continue
            grid = _grid(surface.points)
            kwargs: dict = dict(smooth_shading=True, reset_camera=False, render=False, ambient=0.3, diffuse=0.7,
                                specular=0.0)
            if surface.kind == "blade":
                if scalar is not None and scalar[0].shape == surface.points.shape[:2]:
                    values = scalar[0]
                    grid["field"] = values.ravel()
                    lut = lookup_table(float(np.nanmin(values)), float(np.nanmax(values)))
                    # Colours carry the data here, so keep them close to the colour bar under any light.
                    kwargs.update(scalars="field", cmap=lut, show_scalar_bar=False, ambient=0.75, diffuse=0.25)
                else:
                    kwargs.update(color=(_BLADE_DIM if key in self._dim else _BLADE)[dark])
            elif surface.kind == "hub":
                kwargs.update(color=_HUB[dark])
            else:
                kwargs.update(color=_CASING[dark], opacity=0.25)
            for k in range(max(surface.copies, 1)):
                actor = p.add_mesh(grid, **kwargs)
                if k:
                    actor.user_matrix = rotation_about_x(2.0 * np.pi * k / surface.copies)
                actors.append(actor)
                if k == 0 and "scalars" in kwargs and key not in self._bars:
                    bar_title = scalar[2] or " " * (1 + len(self._bars))     # PyVista keys bars by title
                    p.add_scalar_bar(title=bar_title, mapper=actor.mapper, vertical=True, n_labels=5,
                                     fmt="%.3g", color=_LINE[dark], title_font_size=13, label_font_size=13,
                                     position_x=0.86, position_y=0.2, height=0.6, width=0.07, render=False)
                    self._bars[key] = bar_title
                    if scalar[1]:
                        p.add_text(scalar[1], position="upper_left", font_size=10, color=_LINE[dark],
                                   name=f"title {key}", render=False)
        for line in self._lines.get(key, []):
            actors.append(p.add_mesh(pv.lines_from_points(line), color=_LINE[dark], line_width=2,
                                     reset_camera=False, render=False))
        self._actors[key] = actors
        p.render()

    def closeEvent(self, event) -> None:
        self.plotter.close()
        super().closeEvent(event)
