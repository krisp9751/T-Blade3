"""The camber-line curvature that T-Blade3 builds from chordwise control points (curvature control).

At a blade section the control points are chord fractions u1 = 0, u2, ..., u<n> = 1 with values
cur1..cur<n>. T-Blade3 (source/spanwise_variation.f90, bsplinecam.f90) adds a mirrored point
beyond each end and runs a uniform cubic B-spline through the n + 2 points; the curve starts at
(0, cur1) and ends at (1, cur<n>). The values are relative: T-Blade3 multiplies them by one factor
per section so that the camber line turns from the inlet to the exit blade angle.
"""
from __future__ import annotations

import numpy as np


def curvature_spline(u: np.ndarray, cur: np.ndarray, n_per_segment: int = 24) -> tuple[np.ndarray, np.ndarray]:
    """The curve (chord fraction, relative curvature) defined by the control points ``u``, ``cur``."""
    u, cur = np.asarray(u, dtype=float), np.asarray(cur, dtype=float)
    if len(u) != len(cur) or len(u) < 2:
        raise ValueError("need at least two control points, as many locations as values")
    x = np.concatenate([[2 * u[0] - u[1]], u, [2 * u[-1] - u[-2]]])
    y = np.concatenate([[2 * cur[0] - cur[1]], cur, [2 * cur[-1] - cur[-2]]])
    t = np.linspace(0.0, 1.0, n_per_segment + 1)
    basis = np.stack([(1 - t) ** 3, 3 * t ** 3 - 6 * t ** 2 + 4, -3 * t ** 3 + 3 * t ** 2 + 3 * t + 1, t ** 3]) / 6.0
    xs, ys = [], []
    for j in range(len(x) - 3):
        keep = slice(None) if j == len(x) - 4 else slice(0, -1)     # segments share their end points
        xs.append((x[j:j + 4] @ basis)[keep])
        ys.append((y[j:j + 4] @ basis)[keep])
    return np.concatenate(xs), np.concatenate(ys)
