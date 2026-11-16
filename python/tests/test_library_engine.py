"""The shared-library engine: same results as the executable, survives T-Blade3 failures."""
from __future__ import annotations

import threading

import numpy as np
import pytest

from tblade3 import TBlade3Error, paths
from tblade3.engine import ExecutableEngine

TCT_MAIN = "3dbgbinput.2.dat"


@pytest.fixture(scope="module")
def lib_engine():
    try:
        paths.library()
    except FileNotFoundError as exc:
        pytest.skip(str(exc))
    from tblade3.engine.library import LibraryEngine

    eng = LibraryEngine()
    yield eng
    eng.close()


@pytest.fixture(scope="module")
def lib_geometry(lib_engine, tct_files):
    return lib_engine.run(tct_files, TCT_MAIN)


def test_matches_executable(lib_geometry, tct_geometry):
    assert lib_geometry.sections.shape == (21, 241, 3)
    assert np.array_equal(lib_geometry.sections, tct_geometry.sections)
    assert np.array_equal(lib_geometry.meanlines, tct_geometry.meanlines)
    assert lib_geometry.casename == "Case7-28-8" and lib_geometry.row == 2


def test_derivatives_from_memory_match_files(lib_geometry, tct_geometry):
    mem, ref = lib_geometry.derivatives, tct_geometry.derivatives
    assert set(mem.xyz) == set(ref.xyz) and len(mem.xyz) == 130
    for key in ref.xyz:                       # files hold 16 decimals
        assert np.abs(mem.xyz[key] - ref.xyz[key]).max() < 1e-12, key
    assert set(mem.stagger) == set(ref.stagger) and set(mem.throat) == set(ref.throat)
    for key in ref.stagger:
        assert np.array_equal(mem.stagger[key], ref.stagger[key])


def test_repeated_runs_are_identical(lib_engine, tct_files, lib_geometry):
    for _ in range(3):
        geo = lib_engine.run(tct_files, TCT_MAIN, derivatives=False)
        assert geo.derivatives is None
        assert np.array_equal(geo.sections, lib_geometry.sections)
    assert lib_engine.restarts == 0


def test_fatal_error_raises_and_engine_recovers(lib_engine, tct_files, lib_geometry):
    files = {TCT_MAIN: tct_files[TCT_MAIN]}                  # no auxiliary file: T-Blade3 stops
    with pytest.raises(TBlade3Error) as err:
        lib_engine.run(files, TCT_MAIN)
    assert "fatal error" in err.value.message and "spancontrolinputs.2.dat" in str(err.value)
    assert lib_engine.restarts == 0                          # only the per-run child ended
    geo = lib_engine.run(tct_files, TCT_MAIN, derivatives=False)
    assert np.array_equal(geo.sections, lib_geometry.sections)


def test_garbage_input_raises_and_engine_recovers(lib_engine, tct_files, lib_geometry):
    lines = tct_files[TCT_MAIN].splitlines()
    files = dict(tct_files)
    files[TCT_MAIN] = "\n".join(lines[:40]) + "\n"           # truncated main file
    with pytest.raises(TBlade3Error):                        # must not return the previous geometry
        lib_engine.run(files, TCT_MAIN)
    geo = lib_engine.run(tct_files, TCT_MAIN, derivatives=False)
    assert np.array_equal(geo.sections, lib_geometry.sections)


def test_changed_input_changes_geometry(lib_engine, tct_files, lib_geometry):
    text = tct_files[TCT_MAIN].replace("0.0190000000000000", "0.0290000000000000", 1)   # sweep at the hub
    assert text != tct_files[TCT_MAIN]
    geo = lib_engine.run({**tct_files, TCT_MAIN: text}, TCT_MAIN, derivatives=False)
    assert np.abs(geo.sections - lib_geometry.sections).max() > 0.1


def test_two_engines_in_parallel(tct_files, lib_geometry):
    from tblade3.engine.library import LibraryEngine

    engines = [LibraryEngine(), LibraryEngine()]
    results: list = [None, None]

    def work(i):
        results[i] = engines[i].run(tct_files, TCT_MAIN, derivatives=False)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for eng in engines:
        eng.close()
    for geo in results:
        assert np.array_equal(geo.sections, lib_geometry.sections)


def test_work_dir_removed_on_close(tct_files):
    from tblade3.engine.library import LibraryEngine

    eng = LibraryEngine()
    eng.run(tct_files, TCT_MAIN, derivatives=False)
    work = eng.work_dir
    assert work.is_dir()
    eng.close()
    assert not work.exists()


def test_executable_and_library_agree_on_other_case():
    from tblade3.engine.library import LibraryEngine

    folder = paths.INPUTS_DIR / "NACA_thickness_cases" / "turbine_geometry"
    files = {n: (folder / n).read_text() for n in ("3dbgbinput.2.dat", "spancontrolinputs.2.dat")}
    with ExecutableEngine() as exe, LibraryEngine() as lib:
        a = exe.run(files, "3dbgbinput.2.dat", derivatives=False)
        b = lib.run(files, "3dbgbinput.2.dat", derivatives=False)
    assert np.array_equal(a.sections, b.sections)


def test_timeout_kills_the_run(tct_files, lib_geometry):
    from tblade3.engine.library import LibraryEngine

    with LibraryEngine() as eng:
        with pytest.raises(TBlade3Error, match="did not finish"):
            eng.run(tct_files, TCT_MAIN, timeout=0.05)
        assert eng.restarts == 1
        geo = eng.run(tct_files, TCT_MAIN, derivatives=False)
        assert np.array_equal(geo.sections, lib_geometry.sections)
