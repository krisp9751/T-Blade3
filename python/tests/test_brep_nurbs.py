"""B-spline interpolation and extension (tblade3.brep.nurbs)."""
import numpy as np
import pytest

from tblade3.brep import nurbs


def _helix(n=40):
    t = np.linspace(0, 3, n) ** 1.3
    return np.column_stack([np.cos(t), np.sin(t), 0.3 * t])


@pytest.mark.parametrize("end", ["natural", "quadratic"])
def test_curve_interpolates(end):
    pts = _helix()
    crv, it = nurbs.interpolate_curve(pts, end)
    assert crv.cps.shape == (len(pts) + 2, 3)
    assert np.abs(crv(it.params) - pts).max() < 1e-12
    if end == "natural":
        assert np.abs(crv(it.params[[0, -1]], deriv=2)).max() < 1e-9


def test_quadratic_end_slope():
    pts = _helix(10)
    crv, it = nurbs.interpolate_curve(pts, "quadratic")
    t = it.params
    q = np.polyfit(t[:3], pts[:3], 2)
    slope = 2 * q[0] * t[0] + q[1]
    assert np.allclose(crv(t[:1], deriv=1)[0], slope)


def _grid(nu=31, nv=7):
    u = np.linspace(0, 2 * np.pi, nu)
    v = np.linspace(0, 1, nv) ** 1.2
    r = 1 + 0.3 * v
    x = np.cos(u)[:, None] * r[None]
    y = np.sin(u)[:, None] * r[None] * 0.2
    z = np.broadcast_to(v[None] * 2 + 0.1 * np.sin(u)[:, None], x.shape)
    return np.stack([x, y, z], axis=-1)


def test_surface_interpolates_and_is_linear():
    g = _grid()
    srf, si = nurbs.interpolate_surface(g)
    pts = srf.grid(si.u.params, si.v.params)
    assert np.abs(pts - g).max() < 1e-11
    # control points are linear in the data (with fixed parameters)
    dg = np.random.default_rng(0).normal(size=g.shape)
    assert np.allclose(si.cps(g + dg), srf.cps + si.cp_derivative(dg))


def test_grid_params_match_egads_rule():
    g = _grid()
    p = nurbs.grid_params(g, 1)
    rows = [nurbs.arc_params(g[i]) for i in range(g.shape[0])]
    assert np.allclose(p, np.mean(rows, axis=0))


def test_extension_is_c1_and_keeps_surface():
    g = _grid()
    srf, si = nurbs.interpolate_surface(g)
    ext = nurbs.extend_surface(srf, axis=1, scale_lo=2.0, scale_hi=1.5)
    u = np.linspace(0, 1, 23)
    v = np.linspace(0, 1, 9)
    assert np.abs(ext.grid(u, v) - srf.grid(u, v)).max() < 1e-12
    # first derivative continuous across the joints
    for vj in (0.0, 1.0):
        eps = 1e-7
        a = ext(u, np.full_like(u, vj - eps), dv=1)
        b = ext(u, np.full_like(u, vj + eps), dv=1)
        assert np.abs(a - b).max() < 1e-4 * np.abs(a).max()
    # the extension is straight: second derivative zero inside it
    vlo = ext.vrange[0]
    assert np.abs(ext(u, np.full_like(u, 0.5 * vlo), dv=2)).max() < 1e-8
    assert np.allclose(nurbs.extend_cps(srf.cps, 1, 2.0, 1.5), ext.cps)


def test_unique_knots_roundtrip():
    k = nurbs.clamped_knots(np.array([0, .2, .5, 1.0]))
    vals, mults = nurbs.unique_knots(k)
    assert list(mults) == [4, 1, 1, 4]
    assert np.array_equal(nurbs.expand_knots(vals, mults), k)
