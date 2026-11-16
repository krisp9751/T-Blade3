"""Shared fixtures: input cases and a session-scoped T-Blade3 run of the TCT rotor."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tblade3 import paths
from tblade3.io.outputs import read_run_dir

TCT_DIR = paths.INPUTS_DIR / "OpenCSM" / "Case7-28-8" / "Rotor"
TCT_MAIN = "3dbgbinput.2.dat"


def load_case(folder: Path, main: str) -> dict[str, str]:
    """Main input file plus its auxiliary (span)controlinputs file, as {name: text}."""
    row = main.split(".")[1]
    files = {main: (folder / main).read_text()}
    for aux in (f"spancontrolinputs.{row}.dat", f"controlinputs.{row}.dat"):
        if (folder / aux).exists():
            files[aux] = (folder / aux).read_text()
    return files


def _executable() -> Path:
    try:
        return paths.executable()
    except FileNotFoundError as exc:
        pytest.skip(str(exc))


@pytest.fixture(scope="session")
def tct_files() -> dict[str, str]:
    return load_case(TCT_DIR, TCT_MAIN)


@pytest.fixture(scope="session")
def tct_run_dir(tmp_path_factory, tct_files) -> Path:
    """A folder holding a finished T-Blade3 run of the TCT rotor (run directly, not via an engine)."""
    exe = _executable()
    folder = tmp_path_factory.mktemp("tct")
    for name, text in tct_files.items():
        (folder / name).write_text(text)
    proc = subprocess.run([str(exe), TCT_MAIN], cwd=folder, capture_output=True, timeout=300)
    assert proc.returncode == 0, proc.stderr.decode(errors="replace")
    return folder


@pytest.fixture(scope="session")
def tct_geometry(tct_run_dir):
    return read_run_dir(tct_run_dir)


@pytest.fixture
def engine():
    from tblade3.engine import ExecutableEngine

    _executable()
    eng = ExecutableEngine()
    yield eng
    eng.close()
