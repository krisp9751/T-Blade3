"""Reader for the output files of a finished T-Blade3 run."""
from __future__ import annotations

import shutil
import time

import numpy as np
import pytest

from tblade3 import TBlade3Error
from tblade3.geometry import DERIV_GROUPS
from tblade3.io.outputs import read_derivatives, read_run_dir, read_section_table, read_sections

CN = "Case7-28-8"


def test_shapes(tct_geometry):
    g = tct_geometry
    assert (g.casename, g.row) == (CN, 2)
    assert g.sections.shape == (21, 241, 3)
    assert (g.nsec, g.npt) == (21, 241)
    assert g.meanlines.shape[0] == 21 and g.meanlines.shape[2] == 3
    assert len(g.sections_2d) == 21 and all(s.shape == (241, 2) for s in g.sections_2d)
    assert g.hub.shape[1] == 3 and g.casing.shape[1] == 3
    assert g.le_te.shape == (21, 4)
    assert "END" in g.log or g.log
    assert "T-Blade3 ERROR LOG FILE" not in g.warnings


def test_sections_equal_sec_files(tct_run_dir, tct_geometry):
    for i in range(21):
        sec = np.loadtxt(tct_run_dir / f"sec{i + 1}.{CN}.dat")
        np.testing.assert_array_equal(tct_geometry.sections[i], sec)


def test_sec_file_fallback(tct_run_dir, tmp_path):
    for p in tct_run_dir.glob(f"sec*.{CN}.dat"):
        shutil.copy(p, tmp_path)
    np.testing.assert_array_equal(read_sections(tmp_path, CN), read_sections(tct_run_dir, CN))


def test_unequal_sections_raise(tct_run_dir, tmp_path):
    for p in tct_run_dir.glob(f"sec*.{CN}.dat"):
        shutil.copy(p, tmp_path)
    lines = (tmp_path / f"sec5.{CN}.dat").read_text().splitlines()
    (tmp_path / f"sec5.{CN}.dat").write_text("\n".join(lines[:-3]) + "\n")
    with pytest.raises(TBlade3Error, match="different numbers of points"):
        read_sections(tmp_path, CN)


def test_derivatives(tct_geometry):
    d = tct_geometry.derivatives
    assert (1, 2, 4) in d.xyz and (7, 3, 3) in d.xyz
    assert all(v.shape == (21, 241, 3) for v in d.xyz.values())
    assert {k[0] for k in d.xyz} == set(DERIV_GROUPS)
    assert d.stagger and d.throat
    assert all(v.shape[0] == 21 for v in (*d.stagger.values(), *d.throat.values()))
    assert d.stagger[(3, 1)].shape == (21, 8)


def test_derivatives_match_file(tct_run_dir, tct_geometry):
    raw = np.loadtxt(tct_run_dir / "derivative_files" / "xyz_ders_7_3_3.dat")
    np.testing.assert_array_equal(tct_geometry.derivatives.xyz[(7, 3, 3)].reshape(-1, 3), raw)


def test_derivative_read_speed(tct_run_dir):
    read_derivatives(tct_run_dir, 21, 241)       # warm the file cache
    t = time.perf_counter()
    d = read_derivatives(tct_run_dir, 21, 241)
    assert time.perf_counter() - t < 1.0
    assert len(d.xyz) + len(d.stagger) + len(d.throat) == 168


def test_fixed_width_fallback(tmp_path):
    """Fields that run together or overflow ('****') in the F22.16 derivative files."""
    folder = tmp_path / "derivative_files"
    folder.mkdir()
    rows = [(1.5, -2.0, 3.0), (-1234.5, -2345.25, 0.0)]
    text = "".join("".join(f"{v:22.16f}" for v in r) + "\n" for r in rows)
    text = text.replace(f"{0.0:22.16f}", "*" * 22)
    (folder / "xyz_ders_1_1_1.dat").write_text(text)
    d = read_derivatives(tmp_path, 1, 2)
    x = d.xyz[(1, 1, 1)].reshape(-1, 3)
    np.testing.assert_array_equal(x[0], [1.5, -2.0, 3.0])
    np.testing.assert_array_equal(x[1, :2], [-1234.5, -2345.25])
    assert np.isnan(x[1, 2])


def test_section_table(tct_geometry):
    t = tct_geometry.section_table
    expected = {"section", "span", "beta_z_le", "beta_z_te", "beta_m_le", "beta_m_te", "chord",
                "sweep", "lean", "area", "lethk", "tethk", "throat", "pitch", "zweifel",
                "throat_location", "meridional_chord", "le_thickness", "max_thickness",
                "te_thickness"}
    assert expected <= set(t)
    assert all(len(v) == 21 for v in t.values())
    np.testing.assert_array_equal(t["section"], np.arange(1, 22))
    assert t["span"][0] == 0.0 and t["span"][-1] == 1.0
    assert np.isnan(t["area"][0])                # '***********' overflow in the file
    assert np.all(np.isfinite(t["area"][14:]))
    assert set(t["throat_location"]) <= {"le", "te", "between", "none"}


def test_missing_optional_files(tct_run_dir, tmp_path):
    shutil.copy(tct_run_dir / f"blade3d.{CN}.dat", tmp_path)
    g = read_run_dir(tmp_path, row=2)
    assert g.sections.shape == (21, 241, 3)
    assert g.meanlines is None and g.hub is None and g.derivatives is None
    assert g.sections_2d == [] and g.section_table == {} and g.log == ""
    assert read_section_table(tmp_path, CN) == {}


def test_no_derivatives_flag(tct_run_dir):
    assert read_run_dir(tct_run_dir, derivatives=False).derivatives is None


def test_empty_folder(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_run_dir(tmp_path)
