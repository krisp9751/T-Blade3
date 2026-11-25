"""B-spline curves and surfaces we own (numpy only): interpolation, extension, evaluation.

The interpolation follows EGADS ``EG_approximate(..., mDeg=0, tol)`` (``EG_spline1d``/``EG_spline2d`` in
``egadsSplineFit.cpp``), which udpTblade uses for the blade:

- cubic, clamped (four equal knots at each end), one knot at every data parameter, so ``n`` data points
  give ``n + 2`` control points;
- parameters by arc length, normalized to [0, 1]; for a grid, the normalized arc length of every row
  (column) is averaged, as EGADS does;
- two end conditions per direction: ``"natural"`` (second derivative zero, EGADS ``endc = 0``) or
  ``"quadratic"`` (first derivative of the quadratic through the first three points, EGADS ``endc = 2``,
  used by udpHubWedge for the meanline).

EGADS solves the same equations by iteration; here they are one linear solve. The collocation matrices are
kept on the result, so a change of the data points maps to a change of the control points linearly
(``Interpolant.cp_derivative``), with the parameters (knots) held at their baseline values.

Grids are indexed ``[i, j]`` with ``i`` along u and ``j`` along v; control nets are ``(ncu, ncv, 3)``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.interpolate import BSpline

DEGREE = 3


# ---------------------------------------------------------------------------------------------- basics

def basis_matrix(knots: np.ndarray, t: np.ndarray, degree: int = DEGREE, deriv: int = 0) -> np.ndarray:
    """(len(t), ncp) matrix of the B-spline basis functions (or their derivatives) at t."""
    knots = np.asarray(knots, float)
    ncp = len(knots) - degree - 1
    t = np.clip(np.atleast_1d(np.asarray(t, float)), knots[degree], knots[-degree - 1])
    if deriv == 0:
        spl = BSpline(knots, np.eye(ncp), degree, extrapolate=False)
        return np.nan_to_num(spl(t))
    # derivatives by the NURBS Book recursion (A2.3); works across repeated interior knots, where
    # scipy's BSpline.derivative refuses
    out = np.zeros((len(t), ncp))
    for k, tk in enumerate(t):
        span = int(np.searchsorted(knots, tk, side="right") - 1)
        span = min(max(span, degree), ncp - 1)
        ders = _ders_basis(span, tk, degree, deriv, knots)
        out[k, span - degree:span + 1] = ders[deriv]
    return out


def _ders_basis(span: int, u: float, p: int, n: int, U: np.ndarray) -> np.ndarray:
    ndu = np.zeros((p + 1, p + 1))
    ndu[0, 0] = 1.0
    left = np.zeros(p + 1)
    right = np.zeros(p + 1)
    for j in range(1, p + 1):
        left[j] = u - U[span + 1 - j]
        right[j] = U[span + j] - u
        saved = 0.0
        for r in range(j):
            ndu[j, r] = right[r + 1] + left[j - r]
            temp = ndu[r, j - 1] / ndu[j, r]
            ndu[r, j] = saved + right[r + 1] * temp
            saved = left[j - r] * temp
        ndu[j, j] = saved
    ders = np.zeros((n + 1, p + 1))
    ders[0] = ndu[:, p]
    a = np.zeros((2, p + 1))
    for r in range(p + 1):
        s1, s2 = 0, 1
        a[0, 0] = 1.0
        for k in range(1, n + 1):
            d = 0.0
            rk, pk = r - k, p - k
            if r >= k:
                a[s2, 0] = a[s1, 0] / ndu[pk + 1, rk]
                d = a[s2, 0] * ndu[rk, pk]
            j1 = 1 if rk >= -1 else -rk
            j2 = k - 1 if r - 1 <= pk else p - r
            for j in range(j1, j2 + 1):
                a[s2, j] = (a[s1, j] - a[s1, j - 1]) / ndu[pk + 1, rk + j]
                d += a[s2, j] * ndu[rk + j, pk]
            if r <= pk:
                a[s2, k] = -a[s1, k - 1] / ndu[pk + 1, r]
                d += a[s2, k] * ndu[r, pk]
            ders[k, r] = d
            s1, s2 = s2, s1
    fac = p
    for k in range(1, n + 1):
        ders[k] *= fac
        fac *= p - k
    return ders


def arc_params(points: np.ndarray) -> np.ndarray:
    """Normalized cumulative chord length of a polyline (n, d) -> (n,) in [0, 1]."""
    d = np.linalg.norm(np.diff(points, axis=0), axis=1)
    if np.any(d == 0):
        raise ValueError("repeated point in spline data")
    s = np.concatenate([[0.0], np.cumsum(d)])
    return s / s[-1]


def grid_params(grid: np.ndarray, axis: int) -> np.ndarray:
    """EGADS-style averaged normalized arc length of a (nu, nv, 3) grid along ``axis`` (0: u, 1: v)."""
    g = np.moveaxis(grid, axis, 0)             # (n, m, 3), parameters along the first index
    d = np.linalg.norm(np.diff(g, axis=0), axis=2)   # (n-1, m)
    tot = d.sum(axis=0)
    rsize = np.linalg.norm(grid.reshape(-1, 3).max(0) - grid.reshape(-1, 3).min(0))
    keep = tot >= 1e-13 * rsize                # degenerate rows (a point) are skipped, as in EGADS
    s = np.concatenate([np.zeros((1, keep.sum())), np.cumsum(d[:, keep], axis=0)]) / tot[keep]
    p = s.mean(axis=1)
    if np.any(np.diff(p) <= 0):
        p = np.linspace(0.0, 1.0, g.shape[0])
    return p


def clamped_knots(params: np.ndarray, degree: int = DEGREE) -> np.ndarray:
    """Knot vector with a knot at every parameter and degree+1 equal knots at each end."""
    return np.concatenate([[params[0]] * degree, params, [params[-1]] * degree])


def collocation(params: np.ndarray, end: str = "natural") -> tuple[np.ndarray, np.ndarray]:
    """Square (n+2, n+2) system matrix and knots for cubic interpolation at ``params``.

    Rows: the end condition at the start, the n interpolation conditions, the end condition at the end.
    The right-hand side for the end rows is built by ``_end_rhs``.
    """
    knots = clamped_knots(params)
    n = len(params)
    a = np.zeros((n + 2, n + 2))
    a[1:-1] = basis_matrix(knots, params)
    if end == "natural":
        a[0] = basis_matrix(knots, params[:1], deriv=2)[0]
        a[-1] = basis_matrix(knots, params[-1:], deriv=2)[0]
    elif end == "quadratic":
        a[0] = basis_matrix(knots, params[:1], deriv=1)[0]
        a[-1] = basis_matrix(knots, params[-1:], deriv=1)[0]
    else:
        raise ValueError(f"unknown end condition {end!r}")
    return a, knots


def _end_weights(params: np.ndarray, end: str) -> tuple[np.ndarray, np.ndarray]:
    """Weights w0, w1 (length n) so that the end-row right-hand sides are w0 @ data and w1 @ data."""
    n = len(params)
    w0 = np.zeros(n)
    w1 = np.zeros(n)
    if end == "quadratic" and n >= 3:
        # derivative of the quadratic through the first (last) three points, at the first (last) point
        t0, t1, t2 = params[:3]
        w0[:3] = [(2 * t0 - t1 - t2) / ((t0 - t1) * (t0 - t2)),
                  (t0 - t2) / ((t1 - t0) * (t1 - t2)),
                  (t0 - t1) / ((t2 - t0) * (t2 - t1))]
        t0, t1, t2 = params[-1], params[-2], params[-3]
        w1[[-1, -2, -3]] = [(2 * t0 - t1 - t2) / ((t0 - t1) * (t0 - t2)),
                            (t0 - t2) / ((t1 - t0) * (t1 - t2)),
                            (t0 - t1) / ((t2 - t0) * (t2 - t1))]
    elif end == "quadratic":          # two points: chord slope
        w0[:2] = np.array([-1.0, 1.0]) / (params[1] - params[0])
        w1[-2:] = np.array([-1.0, 1.0]) / (params[-1] - params[-2])
    return w0, w1


@dataclass
class Interpolant:
    """Linear map from data values (n, ...) to control points (n+2, ...) for one direction."""
    params: np.ndarray
    knots: np.ndarray
    end: str
    matrix: np.ndarray = field(repr=False)     # (n+2, n): control points = matrix @ data

    @classmethod
    def build(cls, params: np.ndarray, end: str = "natural") -> Interpolant:
        params = np.asarray(params, float)
        if end == "quadratic" and len(params) == 2:
            end = "natural"
        a, knots = collocation(params, end)
        n = len(params)
        rhs = np.zeros((n + 2, n))
        rhs[1:-1] = np.eye(n)
        w0, w1 = _end_weights(params, end)
        rhs[0] = w0
        rhs[-1] = w1
        return cls(params, knots, end, np.linalg.solve(a, rhs))

    def apply(self, data: np.ndarray, axis: int = 0) -> np.ndarray:
        data = np.moveaxis(np.asarray(data, float), axis, 0)
        out = np.tensordot(self.matrix, data, axes=(1, 0))
        return np.moveaxis(out, 0, axis)


# --------------------------------------------------------------------------------------------- curves

@dataclass
class Curve:
    """Non-rational (weights None) or rational B-spline curve, any dimension."""
    knots: np.ndarray
    cps: np.ndarray                        # (n, d)
    weights: np.ndarray | None = None
    degree: int = DEGREE

    def __call__(self, t, deriv: int = 0) -> np.ndarray:
        t = np.atleast_1d(np.asarray(t, float))
        if self.weights is None:
            return basis_matrix(self.knots, t, self.degree, deriv) @ self.cps
        if deriv:
            raise NotImplementedError("derivatives of rational curves")
        b = basis_matrix(self.knots, t, self.degree) * self.weights
        return (b @ self.cps) / b.sum(axis=1, keepdims=True)

    @property
    def range(self) -> tuple[float, float]:
        return float(self.knots[self.degree]), float(self.knots[-self.degree - 1])


def interpolate_curve(points: np.ndarray, end: str = "natural",
                      params: np.ndarray | None = None) -> tuple[Curve, Interpolant]:
    """Cubic B-spline through every point (EGADS EG_spline1d)."""
    points = np.asarray(points, float)
    p = arc_params(points) if params is None else np.asarray(params, float)
    it = Interpolant.build(p, end)
    return Curve(it.knots, it.apply(points)), it


# ------------------------------------------------------------------------------------------- surfaces

@dataclass
class Surface:
    """Non-rational or rational tensor-product B-spline surface; ``cps`` is (ncu, ncv, 3)."""
    uknots: np.ndarray
    vknots: np.ndarray
    cps: np.ndarray
    weights: np.ndarray | None = None      # (ncu, ncv)
    udegree: int = DEGREE
    vdegree: int = DEGREE

    def __call__(self, u, v, du: int = 0, dv: int = 0) -> np.ndarray:
        """Points at the pairs (u[k], v[k]) -> (n, 3)."""
        u = np.atleast_1d(np.asarray(u, float))
        v = np.atleast_1d(np.asarray(v, float))
        bu = basis_matrix(self.uknots, u, self.udegree, du)
        bv = basis_matrix(self.vknots, v, self.vdegree, dv)
        if self.weights is None:
            return np.einsum("ki,ijc,kj->kc", bu, self.cps, bv)
        if du or dv:
            raise NotImplementedError("derivatives of rational surfaces")
        num = np.einsum("ki,ijc,ij,kj->kc", bu, self.cps, self.weights, bv)
        den = np.einsum("ki,ij,kj->k", bu, self.weights, bv)
        return num / den[:, None]

    def grid(self, u, v) -> np.ndarray:
        """Points on the tensor grid u x v -> (len(u), len(v), 3)."""
        bu = basis_matrix(self.uknots, np.atleast_1d(u), self.udegree)
        bv = basis_matrix(self.vknots, np.atleast_1d(v), self.vdegree)
        if self.weights is None:
            return np.einsum("ai,ijc,bj->abc", bu, self.cps, bv)
        num = np.einsum("ai,ijc,ij,bj->abc", bu, self.cps, self.weights, bv)
        den = np.einsum("ai,ij,bj->ab", bu, self.weights, bv)
        return num / den[..., None]

    @property
    def urange(self) -> tuple[float, float]:
        return float(self.uknots[self.udegree]), float(self.uknots[-self.udegree - 1])

    @property
    def vrange(self) -> tuple[float, float]:
        return float(self.vknots[self.vdegree]), float(self.vknots[-self.vdegree - 1])


@dataclass
class SurfaceInterpolant:
    """The two 1-D interpolants of a tensor-product interpolation: cps = Mu @ X @ Mv^T."""
    u: Interpolant
    v: Interpolant

    def cps(self, grid: np.ndarray) -> np.ndarray:
        return self.v.apply(self.u.apply(grid, axis=0), axis=1)

    # the map is linear, so the same call gives control-point derivatives from data derivatives
    cp_derivative = cps


def interpolate_surface(grid: np.ndarray, uend: str = "natural", vend: str = "natural",
                        uparams: np.ndarray | None = None,
                        vparams: np.ndarray | None = None) -> tuple[Surface, SurfaceInterpolant]:
    """Bicubic B-spline surface through every point of a (nu, nv, 3) grid (EGADS EG_spline2d)."""
    grid = np.asarray(grid, float)
    pu = grid_params(grid, 0) if uparams is None else np.asarray(uparams, float)
    pv = grid_params(grid, 1) if vparams is None else np.asarray(vparams, float)
    si = SurfaceInterpolant(Interpolant.build(pu, uend), Interpolant.build(pv, vend))
    return Surface(si.u.knots, si.v.knots, si.cps(grid)), si


# -------------------------------------------------------------------------------- linear extensions

def extension_rows(first: np.ndarray, second: np.ndarray, scale: float) -> np.ndarray:
    """Control rows of a straight (degree-elevated) extension before ``first``.

    ``first``/``second`` are the first two control rows (along the direction being extended). The new
    end row is E = first - scale * (second - first); the returned rows are [E, (2E+A)/3, (E+2A)/3]
    (A = first). Linear in the inputs, so derivatives transform the same way.
    """
    e = first - scale * (second - first)
    return np.stack([e, (2 * e + first) / 3, (e + 2 * first) / 3])


def extend_surface(srf: Surface, axis: int, scale_lo: float = 0.0, scale_hi: float = 0.0) -> Surface:
    """Extend a clamped cubic surface along u (axis 0) or v (axis 1) by straight C1 segments.

    The extension ends at E = A - s * (B - A) (A, B the first two control rows), so its length is s times
    the first control-polygon leg of each row. The joint knot has multiplicity 3 (C0 formally) but the
    knot spacing is chosen so the surface is C1 across it. ``extend_cps`` applies the same linear map to
    control-point derivatives.
    """
    if srf.weights is not None:
        raise NotImplementedError("extension of rational surfaces")
    knots = srf.uknots if axis == 0 else srf.vknots
    cps = np.moveaxis(srf.cps, axis, 0)
    cps, knots = _extend(cps, knots, scale_lo, scale_hi)
    cps = np.moveaxis(cps, 0, axis)
    if axis == 0:
        return Surface(knots, srf.vknots, cps)
    return Surface(srf.uknots, knots, cps)


def extended_knots(knots: np.ndarray, scale_lo: float, scale_hi: float) -> np.ndarray:
    k = np.asarray(knots, float)
    out = k
    if scale_lo > 0:
        d = scale_lo * (k[4] - k[3]) / 3.0
        out = np.concatenate([[k[0] - d] * 4, out[1:]])   # joint keeps multiplicity 3
    if scale_hi > 0:
        d = scale_hi * (k[-4] - k[-5]) / 3.0
        out = np.concatenate([out[:-1], [k[-1] + d] * 4])
    return out


def _extend(cps: np.ndarray, knots: np.ndarray, scale_lo: float, scale_hi: float):
    rows = [cps]
    if scale_lo > 0:
        rows.insert(0, extension_rows(cps[0], cps[1], scale_lo))
    if scale_hi > 0:
        rows.append(extension_rows(cps[-1], cps[-2], scale_hi)[::-1])
    return np.concatenate(rows, axis=0), extended_knots(knots, scale_lo, scale_hi)


def extend_cps(cps: np.ndarray, axis: int, scale_lo: float, scale_hi: float) -> np.ndarray:
    """The control-point part of ``extend_surface`` (for derivative nets)."""
    c = np.moveaxis(cps, axis, 0)
    rows = [c]
    if scale_lo > 0:
        rows.insert(0, extension_rows(c[0], c[1], scale_lo))
    if scale_hi > 0:
        rows.append(extension_rows(c[-1], c[-2], scale_hi)[::-1])
    return np.moveaxis(np.concatenate(rows, axis=0), 0, axis)


def extend_curve(crv: Curve, scale_lo: float = 0.0, scale_hi: float = 0.0) -> Curve:
    """1-D version of ``extend_surface``."""
    if crv.weights is not None:
        raise NotImplementedError
    cps, knots = _extend(crv.cps, crv.knots, scale_lo, scale_hi)
    return Curve(knots, cps)


# ------------------------------------------------------------------------------- helpers for OCC

def unique_knots(knots: np.ndarray, tol: float = 1e-14) -> tuple[np.ndarray, np.ndarray]:
    """Distinct knot values and their multiplicities (the OCC form)."""
    vals = [knots[0]]
    mults = [1]
    for k in knots[1:]:
        if abs(k - vals[-1]) <= tol * max(1.0, abs(k)):
            mults[-1] += 1
        else:
            vals.append(k)
            mults.append(1)
    return np.array(vals), np.array(mults, int)


def expand_knots(values: np.ndarray, mults: np.ndarray) -> np.ndarray:
    return np.repeat(np.asarray(values, float), np.asarray(mults, int))


def iso_curve(srf: Surface, axis: int, value: float) -> Curve:
    """Iso-parametric curve of a non-rational surface: u = value (axis 0, a curve along v) or v = value
    (axis 1, a curve along u). Exact: the control points are the surface's, blended in the other direction."""
    if srf.weights is not None:
        raise NotImplementedError
    if axis == 0:
        b = basis_matrix(srf.uknots, [value], srf.udegree)[0]
        return Curve(srf.vknots, np.einsum("i,ijc->jc", b, srf.cps), degree=srf.vdegree)
    b = basis_matrix(srf.vknots, [value], srf.vdegree)[0]
    return Curve(srf.uknots, np.einsum("j,ijc->ic", b, srf.cps), degree=srf.udegree)
