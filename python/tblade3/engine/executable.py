"""Engine that runs the standalone T-Blade3 executable in a private temporary folder."""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Mapping
from pathlib import Path

from .. import paths
from ..errors import TBlade3Error
from ..geometry import Geometry
from ..io.outputs import read_run_dir
from .base import Engine

_TAIL_LINES = 30


def _tail(text: str, n: int = _TAIL_LINES) -> str:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines[-n:])


def _first_line_with(text: str, *markers: str) -> str | None:
    for line in text.splitlines():
        for marker in markers:
            if marker in line:
                return line.strip()
    return None


class ExecutableEngine(Engine):
    """Runs ``tblade3 <main>`` in a fresh, private folder for every run.

    The folder lives under /dev/shm when available (else the system temp dir) and is removed by
    ``close()`` unless ``keep_dir`` is set. Runs of one engine are serialized; use one engine per
    thread for parallel runs. ``timings`` holds the T-Blade3 and read times of the last run (s).

    T-Blade3 always writes its derivative files; ``derivatives=False`` only skips reading them.
    """

    def __init__(self, executable: str | Path | None = None, timeout: float = 120.0,
                 keep_dir: bool = False):
        self.executable = Path(executable) if executable else paths.executable()
        self.timeout = timeout
        self.keep_dir = keep_dir
        self.timings: dict[str, float] = {}
        self._root: Path | None = None
        self._lock = threading.Lock()

    @property
    def workdir(self) -> Path:
        """Folder of the current/last run (created on first use)."""
        if self._root is None:
            base = "/dev/shm" if os.path.isdir("/dev/shm") and os.access("/dev/shm", os.W_OK) else None
            self._root = Path(tempfile.mkdtemp(prefix="tblade3_", dir=base))
        return self._root / "run"

    def run(self, files: Mapping[str, str | bytes], main: str, *, derivatives: bool = True,
            timeout: float | None = None) -> Geometry:
        if main not in files:
            raise ValueError(f"main input file {main!r} is not among the given files")
        with self._lock:
            return self._run(files, main, derivatives, self.timeout if timeout is None else timeout)

    def _prepare(self, files: Mapping[str, str | bytes]) -> Path:
        work = self.workdir
        if work.exists():
            shutil.rmtree(work)
        work.mkdir()
        # T-Blade3 otherwise creates this with a shell 'mkdir' call.
        (work / "derivative_files").mkdir()
        for name, content in files.items():
            if Path(name).name != name or name in ("", ".", ".."):
                raise ValueError(f"input file name must be a plain file name: {name!r}")
            target = work / name
            if isinstance(content, bytes):
                target.write_bytes(content)
            else:
                target.write_text(content)
        return work

    def _run(self, files: Mapping[str, str | bytes], main: str, derivatives: bool,
             timeout: float) -> Geometry:
        work = self._prepare(files)
        where = f" (run folder: {work})" if self.keep_dir else ""
        t0 = time.perf_counter()
        try:
            proc = subprocess.run([str(self.executable), main], cwd=work, capture_output=True,
                                  stdin=subprocess.DEVNULL, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            out = (exc.stdout or b"").decode(errors="replace")
            raise TBlade3Error(f"T-Blade3 timed out after {timeout:g} s{where}",
                               self._logs(work, out, "")) from None
        except OSError as exc:
            raise TBlade3Error(f"cannot run {self.executable}: {exc}") from None
        t1 = time.perf_counter()

        stdout = proc.stdout.decode(errors="replace")
        stderr = proc.stderr.decode(errors="replace")
        error_log = (work / "error.log").read_text(errors="replace") if (work / "error.log").exists() else ""
        fatal = _first_line_with(error_log + "\n" + stdout, "FATAL ERROR")
        if proc.returncode != 0:
            reason = (_first_line_with(stderr, "Fortran runtime error", "Program received signal")
                      or fatal)
            at = _first_line_with(stderr, "At line ")
            if reason and at:
                reason = f"{reason} ({at})"
            if proc.returncode < 0:
                try:
                    sig = signal.Signals(-proc.returncode).name
                except ValueError:
                    sig = str(-proc.returncode)
                msg = f"T-Blade3 crashed with signal {sig}"
            else:
                msg = f"T-Blade3 failed with exit code {proc.returncode}"
            raise TBlade3Error(f"{msg}: {reason}{where}" if reason else msg + where,
                               self._logs(work, stdout, stderr))
        if fatal:
            raise TBlade3Error(fatal + where, self._logs(work, stdout, stderr))
        if not any(work.glob("blade3d.*.dat")) and not any(work.glob("sec1.*.dat")):
            reason = _first_line_with(stdout, "ERROR:")
            msg = "T-Blade3 wrote no blade sections"
            raise TBlade3Error(f"{msg}: {reason}{where}" if reason else msg + where,
                               self._logs(work, stdout, stderr))

        try:
            geometry = read_run_dir(work, derivatives=derivatives)
        except TBlade3Error:
            raise
        except (OSError, ValueError) as exc:
            raise TBlade3Error(f"cannot read T-Blade3 output: {exc}{where}",
                               self._logs(work, stdout, stderr)) from None
        self.timings = {"tblade3": t1 - t0, "read": time.perf_counter() - t1}
        return geometry

    @staticmethod
    def _logs(work: Path, stdout: str, stderr: str) -> str:
        """Tails of error.log, T-Blade3_run.log, stdout and stderr, for TBlade3Error.log."""
        parts = []
        for name in ("error.log", "T-Blade3_run.log"):
            p = work / name
            if p.exists():
                text = _tail(p.read_text(errors="replace"))
                if text and text != "T-Blade3 ERROR LOG FILE":
                    parts.append(f"--- {name} ---\n{text}")
        for name, text in (("stdout", stdout), ("stderr", stderr)):
            text = _tail(text)
            if text:
                parts.append(f"--- {name} ---\n{text}")
        return "\n".join(parts)

    def close(self) -> None:
        """Remove the working folder (unless keep_dir). The engine can still be used afterwards."""
        with self._lock:
            if self._root is not None and not self.keep_dir:
                shutil.rmtree(self._root, ignore_errors=True)
            self._root = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
