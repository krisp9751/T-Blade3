"""Surfaces and scalar fields for display, from section data (numpy only, no GUI imports).

T-Blade3 gives blade sections; between them the blade is a smooth spanwise spline (in ESP a cubic
B-spline through the same sections). ``blend_span`` reproduces that smoothness for display, for
the surface itself and for any field given per section point (e.g. a sensitivity).

Coordinates: x is the machine axis; a point at radius r and angle theta is (x, r sin(theta), r cos(theta)),
so T-Blade3's hub and casing curves (x, 0, r) lie at theta = 0.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.interpolate import CubicSpline

COMPONENTS = ("normal", "magnitude", "x", "y", "z", "radial", "tangential")
COMPONENT_LABELS = {"normal": "normal to the surface", "magnitude": "magnitude", "x": "axial (x)", "y": "y", "z": "z",
                    "radial": "radial", "tangential": "tangential (r dθ)"}


@dataclass
class Surface:
    """A structured surface patch for the 3D view: ``points`` is (nu, nv, 3).

    ``copies`` rotational copies about the x axis are drawn (the blade count for a blade).
    ``fields`` holds scalars per point, each (nu, nv).
    """
    name: str
    kind: str                       # "blade", "hub" or "casing"
    points: np.ndarray
    copies: int = 1
    fields: dict[str, np.ndarray] = field(default_factory=dict)


def span_parameter(sections: np.ndarray) -> np.ndarray:
    """A spanwise coordinate per section, 0 at the first and 1 at the last: mean distance between sections."""
    step = np.linalg.norm(np.diff(sections, axis=0), axis=2).mean(axis=1)
    t = np.concatenate([[0.0], np.cumsum(step)])
    return t / t[-1] if t[-1] > 0 else np.linspace(0.0, 1.0, len(t))


def blend_span(values: np.ndarray, t: np.ndarray, n: int = 81) -> np.ndarray:
    """Cubic-spline interpolation along the span (axis 0) from len(t) sections to n stations."""
    if len(t) < 2:
        return np.repeat(values, n, axis=0)
    fine = np.linspace(0.0, 1.0, n)
    if len(t) < 4:
        return np.stack([np.interp(fine, t, col) for col in values.reshape(len(t), -1).T], axis=1).reshape(
            (n, *values.shape[1:]))
    return CubicSpline(t, values, axis=0)(fine)


def section_normals(sections: np.ndarray) -> np.ndarray:
    """Unit normals of the blade surface at the section points, (nsec, npt, 3)."""
    du = np.gradient(sections, axis=1)
    dv = np.gradient(sections, axis=0) if sections.shape[0] > 1 else np.tile([1.0, 0.0, 0.0], (*sections.shape[:2], 1))
    n = np.cross(du, dv)
    length = np.linalg.norm(n, axis=2, keepdims=True)
    return n / np.where(length > 0, length, 1.0)


def component(dxyz: np.ndarray, sections: np.ndarray, which: str) -> np.ndarray:
    """One scalar component of a vector field given at the section points: (nsec, npt)."""
    if which == "normal":
        return (dxyz * section_normals(sections)).sum(axis=2)
    if which == "magnitude":
        return np.linalg.norm(dxyz, axis=2)
    if which in ("x", "y", "z"):
        return dxyz[..., "xyz".index(which)]
    y, z = sections[..., 1], sections[..., 2]
    r = np.hypot(y, z)
    r = np.where(r > 0, r, 1.0)
    if which == "radial":
        return (y * dxyz[..., 1] + z * dxyz[..., 2]) / r
    if which == "tangential":       # theta measured from +z towards +y, matching (x, r sin, r cos)
        return (z * dxyz[..., 1] - y * dxyz[..., 2]) / r
    raise ValueError(f"unknown component {which!r}; choose from {COMPONENTS}")


def edge_points(sections: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Leading-edge and trailing-edge point of each section, each (nsec, 3).

    T-Blade3 sections start and end at the trailing edge; the leading edge is taken as the point
    farthest from it.
    """
    te = sections[:, 0]
    far = np.linalg.norm(sections - te[:, None, :], axis=2).argmax(axis=1)
    return sections[np.arange(len(sections)), far], te


def blade_surface(sections: np.ndarray, n_span: int = 81, name: str = "blade", copies: int = 1) -> Surface:
    """The blade as a smooth surface through its sections."""
    t = span_parameter(sections)
    return Surface(name, "blade", blend_span(sections, t, n_span), copies)


def blade_field(values: np.ndarray, sections: np.ndarray, n_span: int = 81) -> np.ndarray:
    """A per-section-point scalar, blended along the span like ``blade_surface``."""
    return blend_span(values, span_parameter(sections), n_span)


def revolve(curve: np.ndarray, theta0: float = 0.0, theta1: float = 2.0 * np.pi, n_theta: int = 121,
            name: str = "hub", kind: str = "hub") -> Surface:
    """Surface of revolution about the x axis from a meridional curve.

    ``curve`` is (n, 2) as (x, r), or (n, 3) as written by T-Blade3 (x, y, z), where r = hypot(y, z).
    """
    curve = np.asarray(curve, dtype=float)
    x = curve[:, 0]
    r = curve[:, 1] if curve.shape[1] == 2 else np.hypot(curve[:, 1], curve[:, 2])
    theta = np.linspace(theta0, theta1, n_theta)
    pts = np.empty((len(x), n_theta, 3))
    pts[..., 0] = x[:, None]
    pts[..., 1] = r[:, None] * np.sin(theta)[None, :]
    pts[..., 2] = r[:, None] * np.cos(theta)[None, :]
    return Surface(name, kind, pts)


def rotation_about_x(angle: float) -> np.ndarray:
    """4x4 matrix rotating by ``angle`` (radians) about the x axis, in the sense of increasing theta."""
    c, s = np.cos(angle), np.sin(angle)
    return np.array([[1.0, 0.0, 0.0, 0.0],
                     [0.0, c, s, 0.0],
                     [0.0, -s, c, 0.0],
                     [0.0, 0.0, 0.0, 1.0]])


def mean_theta(points: np.ndarray) -> float:
    """Circular mean of the angle theta of a set of points (..., 3)."""
    y, z = points[..., 1].ravel(), points[..., 2].ravel()
    return float(np.arctan2(y.mean(), z.mean()))
