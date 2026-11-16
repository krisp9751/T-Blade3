"""Locations of the T-Blade3 executable, shared library and example inputs.

The package lives in ``<T-Blade3>/python/tblade3``. An in-tree ``make`` puts the executable in
``<T-Blade3>/bin`` and ``make library`` puts the shared library in ``<T-Blade3>/lib``.
The environment variables TBLADE3_EXE and TBLADE3_LIB override both.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INPUTS_DIR = REPO_ROOT / "inputs"


def executable() -> Path:
    env = os.environ.get("TBLADE3_EXE")
    if env:
        return Path(env)
    local = REPO_ROOT / "bin" / "tblade3"
    if local.exists():
        return local
    found = shutil.which("tblade3")
    if found:
        return Path(found)
    raise FileNotFoundError(
        f"tblade3 executable not found: run `make` in {REPO_ROOT} or set TBLADE3_EXE")


def library() -> Path:
    env = os.environ.get("TBLADE3_LIB")
    if env:
        return Path(env)
    local = REPO_ROOT / "lib" / "libTBlade3.so"
    if local.exists():
        return local
    raise FileNotFoundError(
        f"libTBlade3.so not found: run `make library` in {REPO_ROOT} or set TBLADE3_LIB")
