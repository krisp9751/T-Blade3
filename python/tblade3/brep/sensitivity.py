"""Design sensitivities of the B-Rep: d(control points)/d(design variable) for every B-spline surface.

The B-Rep's surfaces are interpolations with fixed parameters (``nurbs``), so their control points are a
linear map of the data points. A data-point derivative therefore gives the control-point derivative
exactly:

- blade (``blade_ss``, ``blade_ps``): d(section points)/dp from T-Blade3 (analytic for sweep, lean and the
  NACA thickness controls, central finite differences otherwise, as ``BladeRow.dxyz``), the end sections
  through the derivative of their move onto the hub/casing streamline;
- periodic sheet (``periodic_lo``, ``periodic_hi``): central finite differences of the sheet's data points
  (two extra T-Blade3 runs per variable; meanlines have no analytic derivatives), with the inlet/outlet
  stations, bore and row layout held at their baseline values;
- hub, casing, bore, inlet, outlet: the flow path does not depend on the blade's design variables; their
  derivatives are zero. ``Sensitivities.flowpath_change`` reports the largest flow-path move seen in the
  finite differences, so a variable that does move it is noticed.

Edges and vertices are iso-curves and corners of these surfaces (or circles on the fixed flow path), so
their derivatives follow from the surfaces'.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import build, occ


@dataclass
class Sensitivities:
    names: list[str]
    methods: dict[str, str]                                  # blade derivative per variable: analytic | fd
    values: dict[str, float]                                 # variable values at the baseline
    surfaces: dict[str, np.ndarray] = field(default_factory=dict)   # surface -> (nvar, nu, nv, 3)
    flowpath_change: dict[str, float] = field(default_factory=dict)  # variable -> largest hub/casing move


def compute(blade_row, row: build.RowBrep, names: list[str], method: str | None = None) -> Sensitivities:
    """Control-point derivatives of the blade and periodic surfaces for the given parameters.

    ``blade_row`` is the ``tblade3.model.BladeRow`` the geometry ``row`` was built from (current values).
    ``method`` forces "analytic" or "fd" for the blade (default: analytic where T-Blade3 has it).
    """
    bs, sh = row.blade_surface, row.sheet
    nvar = len(names)
    d_blade = np.zeros((nvar,) + bs.surface.cps.shape)
    d_sheet = np.zeros((nvar,) + sh.surface.cps.shape)
    methods, values, fp_change = {}, {}, {}
    for k, name in enumerate(names):
        values[name] = blade_row.get(name)
        m = method or blade_row.derivative_method(name)
        methods[name] = m
        d_blade[k] = blade_cp_derivative(bs, blade_row.dxyz(name, m))
        plus, minus, h = blade_row.fd_files(name)
        gp = blade_row.engine.run(plus, blade_row.main_name, derivatives=False)
        gm = blade_row.engine.run(minus, blade_row.main_name, derivatives=False)
        grids = []
        for g in (gp, gm):
            hub = build.Streamline.from_xyz(g.hub)
            cas = build.Streamline.from_xyz(g.casing)
            grids.append(build.sheet_grid(g, hub, cas, sh.stations, sh.bore, sh.rows))
        d_sheet[k] = sh.interp.cp_derivative((grids[0] - grids[1]) / (2 * h))
        fp_change[name] = float(max(np.abs(gp.hub - gm.hub).max(), np.abs(gp.casing - gm.casing).max()))
    rot_lo = occ.rotation_matrix(-sh.half_pitch)
    rot_hi = occ.rotation_matrix(sh.half_pitch)
    surfaces = {"blade_ss": d_blade, "blade_ps": d_blade,
                "periodic_lo": d_sheet @ rot_lo.T, "periodic_hi": d_sheet @ rot_hi.T}
    return Sensitivities(list(names), methods, values, surfaces, fp_change)


def blade_cp_derivative(bs: build.BladeSurface, dxyz: np.ndarray) -> np.ndarray:
    """d(blade control points) from d(section points) (nsec, npt, 3)."""
    dgrid = np.transpose(dxyz, (1, 0, 2)).copy()
    for pr in bs.projections:
        dgrid[:, pr.index] = pr.derivative(bs.raw[:, pr.index], dgrid[:, pr.index])
    return bs.interp.cp_derivative(dgrid)
