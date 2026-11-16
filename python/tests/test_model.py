"""The data model: named parameters, building, derivatives, design variables, saving."""
from __future__ import annotations

import shutil

import numpy as np
import pytest

import tblade3 as tb
from tblade3 import paths
from tblade3.model import BladeRow, Case

from conftest import TCT_DIR, TCT_MAIN

CASE7 = paths.INPUTS_DIR / "OpenCSM" / "Case7-28-8"


def _library_or_skip():
    try:
        paths.library()
    except FileNotFoundError as exc:
        pytest.skip(str(exc))


@pytest.fixture(scope="module")
def tct():
    """The TCT rotor, built once. Tests that change values must restore them."""
    _library_or_skip()
    case = Case.load(TCT_DIR)
    case.build()
    yield case
    case.close()


@pytest.fixture
def tct_copy(tmp_path):
    """A private, editable copy of the TCT rotor case."""
    _library_or_skip()
    for name in (TCT_MAIN, "spancontrolinputs.2.dat"):
        shutil.copy(TCT_DIR / name, tmp_path / name)
    case = Case.load(tmp_path)
    yield case
    case.close()


# -- parameters --------------------------------------------------------------------------------

def test_package_exports_case():
    assert tb.Case is Case


def test_parameter_names_and_values(tct):
    row = tct.rows["2"]
    assert list(tct.rows) == ["2"]
    assert tct.get("row2.n_blades") == 16
    assert tct.get("scale_factor") == pytest.approx(152.4)           # the row may be left out with one row
    assert tct.get("row2.lean[1]") == pytest.approx(0.05125)
    assert tct.get("row2.naca.t_max[3]") == pytest.approx(0.04794)
    assert tct.get("row2.naca.u_max[5]") == pytest.approx(0.60)
    assert row.parameters["sweep[4]"].deriv == (1, 2, 4)
    assert row.parameters["sweep.span[2]"].deriv == (1, 1, 2)
    assert row.parameters["naca.le_radius[1]"].udp == ("naca_le_radius", 1)
    assert row.parameters["sweep[1]"].udp == ("span_del_m", 1)
    assert row.parameters["n_blades"].integer
    assert set(tct.parameters()) == {f"row2.{n}" for n in row.parameters}


def test_unknown_names_raise(tct):
    with pytest.raises(KeyError):
        tct.get("row2.no_such_thing")
    with pytest.raises(KeyError):
        tct.get("row7.sweep[1]")


def test_set_changes_the_input_file(tct_copy):
    before = tct_copy.rows["2"].files()
    tct_copy.set("row2.sweep[4]", 0.0125)
    tct_copy.set("row2.naca.t_max[2]", 0.09)
    after = tct_copy.rows["2"].files()
    assert before[TCT_MAIN] != after[TCT_MAIN]
    assert before["spancontrolinputs.2.dat"] != after["spancontrolinputs.2.dat"]
    again = BladeRow.from_texts(after[TCT_MAIN], after["spancontrolinputs.2.dat"])
    assert again.get("sweep[4]") == 0.0125 and again.get("naca.t_max[2]") == 0.09
    tct_copy.set("row2.n_blades", 17.4)
    assert tct_copy.get("row2.n_blades") == 17


# -- building ----------------------------------------------------------------------------------

def test_build_equals_engine_run_of_the_original_files(tct, tct_files):
    from tblade3.engine.library import LibraryEngine
    with LibraryEngine() as engine:
        ref = engine.run(tct_files, TCT_MAIN, derivatives=False)
    assert np.array_equal(tct.rows["2"].geometry.sections, ref.sections)


def test_build_is_cached_until_an_input_changes(tct_copy):
    row = tct_copy.rows["2"]
    geo = row.build()
    assert row.build() is geo and row.is_current
    row.set("lean[1]", 0.06)
    assert not row.is_current
    geo2 = row.build()
    assert geo2 is not geo and np.abs(geo2.sections - geo.sections).max() > 1e-3


def test_failed_build_raises_and_keeps_the_last_geometry(tct_copy):
    row = tct_copy.rows["2"]
    good = row.build()
    old = row.get("naca.t_te[5]")
    row.set("naca.t_te[5]", -0.5)                      # negative thickness: T-Blade3 fatal error
    with pytest.raises(tb.TBlade3Error, match="[Nn]egative thickness"):
        row.build()
    assert row.geometry is good and not row.is_current
    row.set("naca.t_te[5]", old)
    assert row.build() is good                          # same files again: no new run needed


# -- derivatives -------------------------------------------------------------------------------

def test_every_analytic_parameter_has_a_derivative(tct):
    row = tct.rows["2"]
    keys = {p.deriv for p in row.parameters.values() if p.deriv is not None}
    assert keys == set(row.geometry.derivatives.xyz)
    assert len(keys) == 130


# Tolerances relative to the largest finite-difference value. The inlet/exit angle and t_max
# analytic derivatives of T-Blade3 are themselves only accurate to about 1e-2 and 1e-3; the
# error does not change with the step size (see HANGAR docs/esp_tblade3_sensitivities.md).
@pytest.mark.parametrize("name, tol", [
    ("sweep[4]", 1e-5), ("sweep.span[2]", 1e-5), ("lean[1]", 1e-5), ("lean.span[3]", 1e-5),
    ("chord_multiplier[1]", 1e-5), ("chord_multiplier.span[2]", 1e-5),
    ("cur1[1]", 1e-5), ("cur3[4]", 1e-5), ("cur7[2]", 1e-5),
    ("naca.le_radius[2]", 1e-5), ("naca.u_max[3]", 1e-5), ("naca.t_te[5]", 1e-5),
    ("naca.t_max[3]", 5e-3), ("in_beta[3]", 2e-2), ("out_beta[2]", 3e-2),
])
def test_analytic_derivative_matches_finite_difference(tct, name, tol):
    row = tct.rows["2"]
    assert row.derivative_method(name) == "analytic"
    analytic = row.dxyz(name, "analytic")
    fd = row.dxyz(name, "fd")
    assert analytic.shape == fd.shape == row.geometry.sections.shape
    assert np.abs(fd).max() > 0
    assert np.abs(analytic - fd).max() / np.abs(fd).max() < tol


def test_finite_difference_fallback(tct):
    row = tct.rows["2"]
    assert row.derivative_method("hub_offset") == "fd"
    d = tct.dxyz("row2.hub_offset")
    assert d.shape == row.geometry.sections.shape and np.abs(d).max() > 1.0
    with pytest.raises(tb.TBlade3Error):
        row.dxyz("hub_offset", "analytic")
    with pytest.raises(tb.TBlade3Error):
        row.dxyz("n_blades")
    assert row.is_current                               # stepping restored the value


def test_jacobian(tct):
    names = ["row2.sweep[4]", "row2.naca.u_max[3]", "row2.hub_offset"]
    jac = tct.jacobian(names)["2"]
    assert jac.shape == (*tct.rows["2"].geometry.sections.shape, 3)
    for k, name in enumerate(names):
        assert np.array_equal(jac[..., k], tct.dxyz(name))


# -- design variables and saving ---------------------------------------------------------------

def test_design_variables_round_trip(tct_copy, tmp_path):
    case = tct_copy
    case.dv.add("row2.sweep[4]", -0.05, 0.05)
    case.dv.add("row2.naca.t_max[3]", 0.03, None)
    assert case.dv.names == ["row2.sweep[4]", "row2.naca.t_max[3]"]
    assert case.dv.bounds == [(-0.05, 0.05), (0.03, None)]
    with pytest.raises(ValueError):
        case.dv.add("row2.n_blades")
    case.dv.values = [0.01, 0.05]
    assert case.get("row2.sweep[4]") == 0.01 and case.get("row2.naca.t_max[3]") == 0.05
    with pytest.raises(ValueError):
        case.dv.values = [0.0]
    geo = case.build(derivatives=False)["2"]

    out = tmp_path / "saved"
    case.save(out)
    assert (out / "case.tb3.yaml").is_file()
    with Case.load(out) as again:
        assert again.dv.names == case.dv.names and again.dv.bounds == case.dv.bounds
        assert np.array_equal(again.dv.values, case.dv.values)
        assert np.array_equal(again.build(derivatives=False)["2"].sections, geo.sections)

    case.dv.remove("row2.sweep[4]")
    case.dv.remove("row2.naca.t_max[3]")
    case.save(out)
    assert not (out / "case.tb3.yaml").exists()


def test_design_variable_flags_survive_a_structural_change(tct_copy):
    row = tct_copy.rows["2"]
    tct_copy.dv.add("row2.lean[1]", 0.0, 0.1)
    n = len(row.main.sweep.span)
    row.invalidate_parameters()
    p = row.parameters["lean[1]"]
    assert p.is_dv and (p.lower, p.upper) == (0.0, 0.1)
    assert f"sweep[{n}]" in row.parameters


# -- several rows ------------------------------------------------------------------------------

def test_multi_row_case(tmp_path):
    _library_or_skip()
    for sub in ("IGV", "Rotor", "OGV"):
        for path in (CASE7 / sub).glob("*input*.dat"):
            shutil.copy(path, tmp_path / path.name)
    with Case.load(tmp_path) as case:
        assert list(case.rows) == ["1", "2", "3"]
        with pytest.raises(KeyError):
            case.get("sweep[1]")                        # ambiguous without the row
        geos = case.build(derivatives=False)
        assert set(geos) == {"1", "2", "3"}
        with Case.load(CASE7 / "Rotor") as single:
            assert np.array_equal(geos["2"].sections, single.build(derivatives=False)["2"].sections)
        jac = case.jacobian(["row2.sweep[4]", "row3.lean[1]"])
        assert not jac["1"].any()
        assert jac["2"][..., 0].any() and not jac["2"][..., 1].any()
        assert jac["3"][..., 1].any() and not jac["3"][..., 0].any()
