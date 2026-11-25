"""The .hgeom format and the B-Rep sensitivities (tblade3.brep.hgeom, tblade3.brep.sensitivity)."""
import zipfile

import numpy as np
import pytest
import yaml

pytest.importorskip("OCP")
from tblade3.brep import build, export, hgeom, nurbs, occ, sensitivity  # noqa: E402
from tblade3.model import Case  # noqa: E402


@pytest.fixture(scope="module")
def case(tmp_path_factory, tct_files):
    folder = tmp_path_factory.mktemp("tct_case")
    for name, text in tct_files.items():
        (folder / name).write_text(text)
    c = Case.load(folder)
    yield c
    c.close()


@pytest.fixture(scope="module")
def blade_row(case):
    return next(iter(case.rows.values()))


@pytest.fixture(scope="module")
def row(blade_row):
    return build.build_row(blade_row.build())


@pytest.fixture(scope="module")
def sens(blade_row, row):
    return sensitivity.compute(blade_row, row, ["lean[2]", "sweep[3]", "naca.t_max[2]"])


def test_roundtrip_exact(row, blade_row, sens, tmp_path):
    src = {"files": blade_row.files(), "design_variables": sens.values}
    p = export.export_row(row, tmp_path, "tct", formats=("hgeom",), sensitivities=sens, source=src)[0]
    h = hgeom.read(p)
    assert set(h.bodies) == set(export.DEFAULT_BODIES)
    for name, shape in h.bodies.items():
        orig = row.bodies[name]
        assert occ.is_valid(shape), name
        assert occ.counts(shape) == occ.counts(orig)
        assert occ.volume(shape) == pytest.approx(occ.volume(orig), rel=1e-12)
        assert occ.area(shape) == pytest.approx(occ.area(orig), rel=1e-12)
        roles = {h.role(f) for f in occ.explore(shape, "face")}
        assert roles == set(row.faces_by_role(name)), name
    # faces shared between bodies are stored once
    hub = [f for f in h.faces if h.role(f) == "hub"]
    assert len(hub) == 1
    for body in ("hub_wedge", "passage", "solid"):
        assert any(f.IsSame(hub[0]) for f in occ.explore(h.bodies[body], "face"))
    assert h.sources == blade_row.files()
    m = h.manifest
    assert m["format"] == "hgeom" and m["units"] == "mm" and m["row"]["nblades"] == 16
    # the blade surface is stored with our own control points
    cps = h.arrays[m["surfaces"]["blade_ss"]["cps"]]
    assert np.array_equal(cps, row.blade_surface.surface.cps)
    assert h.sensitivity("blade_ss").shape == (3,) + cps.shape
    assert h.sensitivity("hub") is None


def test_manifest_is_plain_yaml(row, tmp_path):
    p = hgeom.write(row, tmp_path / "x.hgeom", bodies=["blade"])
    with zipfile.ZipFile(p) as z:
        m = yaml.safe_load(z.read("manifest.yaml"))
    assert list(m["bodies"]) == ["blade"]
    assert {f["role"] for f in m["faces"]} == {"blade_suction", "blade_pressure", "blade_root", "blade_tip"}


def _fd_cps(blade_row, row, name):
    """Central differences of the control points with the baseline parameterization."""
    bs, sh = row.blade_surface, row.sheet
    plus, minus, h = blade_row.fd_files(name)
    out = []
    for files in (plus, minus):
        g = blade_row.engine.run(files, blade_row.main_name, derivatives=False)
        grid = np.transpose(g.sections, (1, 0, 2)).copy()
        for pr in bs.projections:
            grid[:, pr.index] = pr.apply(grid[:, pr.index])
        hub, cas = build.Streamline.from_xyz(g.hub), build.Streamline.from_xyz(g.casing)
        out.append((bs.interp.cps(grid), sh.interp.cps(build.sheet_grid(g, hub, cas, sh.stations, sh.bore, sh.rows))))
    return (out[0][0] - out[1][0]) / (2 * h), (out[0][1] - out[1][1]) / (2 * h)


def test_blade_sensitivity_matches_finite_differences(blade_row, row, sens):
    for k, name in enumerate(sens.names):
        fd_blade, _ = _fd_cps(blade_row, row, name)
        an = sens.surfaces["blade_ss"][k]
        rel = np.abs(an - fd_blade).max() / np.abs(an).max()
        # sweep and lean: T-Blade3's analytic derivatives are exact; t_max has T-Blade3's known
        # 1e-4..3e-3 error (HANGAR/docs/esp_tblade3_sensitivities.md)
        assert rel < (5e-3 if "t_max" in name else 1e-6), (name, rel)
        assert sens.methods[name] == "analytic"
    assert all(v == 0.0 for v in sens.flowpath_change.values())


def test_sensitivity_moves_the_surface(row, sens):
    """d(surface points) = basis x d(control points): a lean change moves the blade and the periodic sheet."""
    bs = row.blade_surface
    k = sens.names.index("lean[2]")
    d = nurbs.Surface(bs.surface.uknots, bs.surface.vknots, sens.surfaces["blade_ss"][k])
    assert np.abs(d.grid([0.3], [0.5])).max() > 1.0
    assert np.abs(sens.surfaces["periodic_lo"][k]).max() > 1.0
