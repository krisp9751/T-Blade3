"""ExecutableEngine: runs the T-Blade3 executable in a private folder."""
from __future__ import annotations

import re
import shutil
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest
from conftest import TCT_MAIN, load_case

from tblade3 import TBlade3Error, paths
from tblade3.engine import ExecutableEngine


def _set_nblades(text: str, n: int) -> str:
    lines = text.splitlines(keepends=True)
    lines[5] = f"          {n}\n"
    return "".join(lines)


def test_run(engine, tct_files, tct_geometry):
    g = engine.run(tct_files, TCT_MAIN)
    assert g.sections.shape == (21, 241, 3)
    np.testing.assert_array_equal(g.sections, tct_geometry.sections)
    assert (1, 2, 4) in g.derivatives.xyz
    assert set(engine.timings) == {"tblade3", "read"}
    assert engine.run(tct_files, TCT_MAIN, derivatives=False).derivatives is None


def test_fresh_folder_each_run(engine, tct_files):
    engine.run(tct_files, TCT_MAIN)
    stale = engine.workdir / "sec99.Case7-28-8.dat"
    stale.write_text("stale")
    engine.run(tct_files, TCT_MAIN)
    assert not stale.exists()


def test_fatal_error_then_success(engine, tct_files):
    files = {TCT_MAIN: tct_files[TCT_MAIN]}         # no spancontrolinputs file -> fatal_error
    with pytest.raises(TBlade3Error, match="FATAL ERROR") as info:
        engine.run(files, TCT_MAIN)
    assert "spancontrolinputs.2.dat" in info.value.log
    assert engine.run(tct_files, TCT_MAIN).sections.shape == (21, 241, 3)


def test_runtime_error(engine, tct_files):
    files = dict(tct_files)
    files[TCT_MAIN] = "".join(files[TCT_MAIN].splitlines(keepends=True)[:30])   # truncated
    with pytest.raises(TBlade3Error, match="exit code"):
        engine.run(files, TCT_MAIN)
    files[TCT_MAIN] = re.sub(r"152\.4\d*", "abc", tct_files[TCT_MAIN], count=1)   # bad number
    with pytest.raises(TBlade3Error, match="Fortran runtime error"):
        engine.run(files, TCT_MAIN)
    assert engine.run(tct_files, TCT_MAIN).nsec == 21


def test_wennerstrom_sweep_and_lean_derivatives_only(engine):
    """Without NACA thickness and curvature control, T-Blade3 writes only sweep and lean derivatives."""
    folder = paths.INPUTS_DIR / "OpenCSM" / "Wennerstrom_with_umxthk"
    g = engine.run(load_case(folder, "3dbgbinput.1.dat"), "3dbgbinput.1.dat")
    assert g.sections.shape == (21, 241, 3) and np.all(np.isfinite(g.sections))
    assert {key[0] for key in g.derivatives.xyz} == {1, 2}
    assert all(np.all(np.isfinite(d)) for d in g.derivatives.xyz.values())
    assert not g.derivatives.stagger and not g.derivatives.throat


def test_timeout(tct_files):
    with ExecutableEngine(timeout=0.01) as eng:
        with pytest.raises(TBlade3Error, match="timed out"):
            eng.run(tct_files, TCT_MAIN)
        assert eng.run(tct_files, TCT_MAIN, timeout=120).nsec == 21


def test_bad_arguments(engine, tct_files):
    with pytest.raises(ValueError):
        engine.run(tct_files, "missing.dat")
    with pytest.raises(ValueError):
        engine.run({**tct_files, "../evil.dat": ""}, TCT_MAIN)


def test_close_and_keep_dir(tct_files):
    eng = ExecutableEngine()
    eng.run(tct_files, TCT_MAIN)
    root = eng.workdir.parent
    eng.close()
    assert not root.exists()
    keep = ExecutableEngine(keep_dir=True)
    work = keep.workdir
    try:
        with pytest.raises(TBlade3Error, match="run folder"):
            keep.run({TCT_MAIN: tct_files[TCT_MAIN]}, TCT_MAIN)
        keep.close()
        assert (work / "error.log").exists()
    finally:
        shutil.rmtree(work.parent, ignore_errors=True)


def test_parallel_engines(tct_files):
    """Two engines in two threads, with different blade counts, give different results."""
    cases = [tct_files, {**tct_files, TCT_MAIN: _set_nblades(tct_files[TCT_MAIN], 20)}]

    def work(files):
        with ExecutableEngine() as eng:
            return [eng.run(files, TCT_MAIN, derivatives=False) for _ in range(2)]

    with ThreadPoolExecutor(2) as pool:
        a, b = pool.map(work, cases)
    np.testing.assert_array_equal(a[0].sections, a[1].sections)
    np.testing.assert_array_equal(b[0].sections, b[1].sections)
    assert a[0].section_table["pitch"][0] == pytest.approx(2 * np.pi / 16)
    assert b[0].section_table["pitch"][0] == pytest.approx(2 * np.pi / 20)


@pytest.mark.parametrize("folder, main", [
    ("NACA_thickness_cases/turbine_geometry", "3dbgbinput.2.dat"),
    ("OpenCSM/Case7-28-8/OGV", "3dbgbinput.3.dat"),
    ("OpenCSM/Wennerstrom_with_umxthk", "3dbgbinput.1.dat"),
])
def test_other_cases(engine, folder, main):
    files = load_case(paths.INPUTS_DIR / folder, main)
    g = engine.run(files, main)
    assert g.row == int(main.split(".")[1])
    assert g.sections.ndim == 3 and g.sections.shape[2] == 3 and g.nsec >= 2
    assert np.all(np.isfinite(g.sections))
    assert len(g.sections_2d) == g.nsec
    assert g.derivatives is not None and g.derivatives.xyz
    assert len(g.section_table["span"]) == g.nsec
