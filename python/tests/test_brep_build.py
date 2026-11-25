"""Exact B-Rep of a blade row (tblade3.brep.build) on the TCT rotor."""
import math

import numpy as np
import pytest

pytest.importorskip("OCP")
from tblade3.brep import build, nurbs, occ  # noqa: E402

# ESP udpTblade on the same inputs, read back from its STEP dump and integrated with eps = 1e-9
# (ESP's own @volume, 11668.72, is OpenCASCADE's default low-precision integration)
ESP_BLADE_VOLUME = 11638.33
ESP_BLADE_AREA = 10415.27


@pytest.fixture(scope="module")
def row(tct_geometry):
    return build.build_row(tct_geometry)


def test_bodies_valid_and_tight(row):
    for name in build.BODY_NAMES:
        body = row.bodies[name]
        assert occ.is_valid(body), name
        assert occ.max_tolerance(body) < 1e-3, name        # ESP's TCT blade: 1.9e-2
    assert occ.counts(row.bodies["blade"]) == {"solid": 1, "face": 4, "edge": 6, "vertex": 4}
    assert occ.counts(row.bodies["assembly"])["solid"] == 3


def test_blade_matches_esp(row):
    b = row.bodies["blade"]
    assert occ.volume(b) == pytest.approx(ESP_BLADE_VOLUME, rel=2e-4)
    assert occ.area(b) == pytest.approx(ESP_BLADE_AREA, rel=1e-4)


def test_volumes_add_up(row):
    v = {k: occ.volume(row.bodies[k]) for k in ("blade", "hub_wedge", "passage", "solid")}
    assert v["solid"] == pytest.approx(v["blade"] + v["hub_wedge"], rel=1e-7)
    assert occ.volume(row.bodies["assembly"]) == pytest.approx(v["blade"] + v["hub_wedge"] + v["passage"], rel=1e-7)


def test_roles(row):
    want = {
        "blade": {"blade_suction", "blade_pressure", "blade_root", "blade_tip"},
        "hub_wedge": {"wedge_periodic_lo", "wedge_periodic_hi", "wedge_inlet", "wedge_outlet", "bore", "hub",
                      "blade_root"},
        "passage": {"periodic_lo", "periodic_hi", "inlet", "outlet", "hub", "casing", "blade_suction",
                    "blade_pressure"},
        "solid": {"blade_suction", "blade_pressure", "blade_tip", "wedge_periodic_lo", "wedge_periodic_hi",
                  "wedge_inlet", "wedge_outlet", "bore", "hub"},
    }
    for body, roles in want.items():
        assert set(row.faces_by_role(body)) == roles, body


def test_shared_faces(row):
    """The bodies share their interfaces (same faces), so they conform."""
    hub = row.faces["hub"]
    for body in ("hub_wedge", "passage", "solid"):
        assert any(f.IsSame(hub) for f in occ.explore(row.bodies[body], "face"))
    root = row.faces["blade_root"]
    assert any(f.IsSame(root) for f in occ.explore(row.bodies["hub_wedge"], "face"))
    assert not any(f.IsSame(root) for f in occ.explore(row.bodies["solid"], "face"))


def test_periodic_sides_are_rotated_copies(row):
    sh = row.sheet
    lo = build.rotated(sh.surface, -sh.half_pitch)
    hi = build.rotated(sh.surface, sh.half_pitch)
    u = np.linspace(*sh.surface.urange, 17)
    v = np.linspace(*sh.surface.vrange, 9)
    rot = occ.rotation_matrix(2 * math.pi / row.nblades)
    assert np.abs(lo.grid(u, v) @ rot.T - hi.grid(u, v)).max() < 1e-9


def test_sheet_edges_on_their_surfaces(row):
    """Inlet/outlet columns lie in their planes; hub/casing/bore rows on their surfaces of revolution."""
    sh = row.sheet
    srf = sh.surface
    for u, x in ((srf.urange[0], row.x_inlet), (srf.urange[1], row.x_outlet)):
        col = nurbs.iso_curve(srf, 0, u)(np.linspace(*srf.vrange, 50))
        assert np.abs(col[:, 0] - x).max() < 1e-9
    uu = np.linspace(*srf.urange, 400)
    for v, stl in ((sh.v_hub, row.hub), (sh.v_casing, row.casing)):
        p = nurbs.iso_curve(srf, 1, v)(uu)
        x, r, _ = build.cyl(p)
        assert np.abs(r - stl.radius(x)[0]).max() < 3e-4      # cubic in x, y, z vs the revolved curve
    p = nurbs.iso_curve(srf, 1, sh.v_bore)(uu)
    assert np.abs(np.hypot(p[:, 1], p[:, 2]) - row.bore_radius).max() < 3e-4


def test_blade_surface_through_section_points(row, tct_geometry):
    bs = row.blade_surface
    pts = bs.surface.grid(bs.interp.u.params, bs.interp.v.params)
    assert np.abs(pts - bs.grid).max() < 1e-9
    # only the end sections moved (onto the hub and casing), by T-Blade3's own error
    assert np.abs(bs.grid[:, 1:-1] - bs.raw[:, 1:-1]).max() == 0
    assert np.abs(bs.grid - bs.raw).max() < 0.02


def test_options(tct_geometry):
    row = build.build_row(tct_geometry, build.BuildOptions(bore_radius=20.0, x_inlet=-5.0, x_outlet=75.0,
                                                          stations=61))
    assert occ.is_valid(row.bodies["assembly"])
    assert row.bore_radius == 20.0
    with pytest.raises(ValueError):
        build.build_row(tct_geometry, build.BuildOptions(bore_radius=80.0))
