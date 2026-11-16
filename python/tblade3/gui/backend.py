"""What the views need from a geometry source, and the T-Blade3 implementation of it.

The 3D view and the sensitivity tools draw ``Surface`` objects and per-point scalar fields. Any
source that can produce those can drive them. ``GeometryBackend`` names the operations; the
T-Blade3 functions below implement them for a ``BladeRow``. An ESP backend (pyOCSM: DESPMTRs,
tessellation, tessellation velocities) can implement the same protocol later.
"""
from __future__ import annotations

from typing import Protocol

import numpy as np

from ..geometry import Geometry
from ..model import BladeRow, Parameter
from ..surfaces import (Surface, blade_field, blade_surface, blend_span, component, edge_points, mean_theta, revolve,
                        span_parameter)

N_SPAN = 81


class GeometryBackend(Protocol):
    def parameters(self) -> dict[str, Parameter]: ...
    def build(self) -> None: ...
    def surfaces(self, all_blades: bool) -> tuple[list[Surface], list[np.ndarray]]: ...
    def sensitivity(self, name: str, which: str) -> np.ndarray: ...


def _clip_curve(curve: np.ndarray, x0: float, x1: float) -> np.ndarray:
    """The part of a meridional curve (n, 3) between x0 and x1, with interpolated end points."""
    x = curve[:, 0]
    order = np.argsort(x)
    xs, pts = x[order], curve[order]
    x0, x1 = max(x0, xs[0]), min(x1, xs[-1])
    if x1 <= x0:
        return curve
    inner = pts[(xs > x0) & (xs < x1)]
    ends = np.array([[np.interp(v, xs, pts[:, j]) for j in range(curve.shape[1])] for v in (x0, x1)])
    return np.vstack([ends[:1], inner, ends[1:]])


def row_surfaces(geo: Geometry, n_blades: int, all_blades: bool) -> tuple[list[Surface], list[np.ndarray]]:
    """Blade, hub and casing surfaces of one row, and its LE and TE lines.

    With ``all_blades`` the full annulus is drawn; otherwise one blade with one pitch of hub and casing.
    """
    surfaces = [blade_surface(geo.sections, N_SPAN, copies=n_blades if all_blades else 1)]
    x = geo.sections[..., 0]
    margin = 0.6 * (x.max() - x.min())
    if all_blades or n_blades < 1:
        theta0, theta1, n_theta = 0.0, 2.0 * np.pi, 181
    else:
        centre, half = mean_theta(geo.sections), np.pi / n_blades
        theta0, theta1, n_theta = centre - half, centre + half, 25
    for curve, kind in ((geo.hub, "hub"), (geo.casing, "casing")):
        if curve is not None and len(curve) > 1:
            clipped = _clip_curve(curve, x.min() - margin, x.max() + margin)
            surfaces.append(revolve(clipped, theta0, theta1, n_theta, name=kind, kind=kind))
    t = span_parameter(geo.sections)
    lines = [blend_span(edge, t, N_SPAN) for edge in edge_points(geo.sections)]     # leading edge, trailing edge
    return surfaces, lines


def sensitivity_field(row: BladeRow, name: str, which: str) -> np.ndarray:
    """One component of d(surface)/d(parameter) on the grid of the row's blade surface."""
    geo = row.geometry
    return blade_field(component(row.dxyz(name), geo.sections, which), geo.sections, N_SPAN)
