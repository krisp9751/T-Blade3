"""Engine that runs T-Blade3 from its shared library, in a helper process.

Two properties of T-Blade3 shape this design:

* A fatal error executes a Fortran ``stop`` and a bug can segfault. Either ends the process that
  loaded the library, which Python cannot catch.
* T-Blade3 keeps its state in module variables that are not reset between runs, so a second run
  in the same process can silently reuse data of the first (for example after a truncated input
  file, or when hub inflation is switched off again).

So the library is loaded once in a long-lived worker process that never runs T-Blade3 itself. For
every run the worker forks; the child starts from the pristine library state, runs T-Blade3, sends
the result and exits. Forking costs about a millisecond. If the child stops or crashes, the worker
reports it and ``run`` raises ``TBlade3Error``; callers only ever see ordinary Python exceptions.

The worker is started as ``python -m tblade3.engine._worker`` (not through multiprocessing), so
scripts that use this package need no ``if __name__ == "__main__"`` guard.
"""
from __future__ import annotations

import ctypes
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
from multiprocessing.connection import Connection
from collections.abc import Mapping
from pathlib import Path

import numpy as np

from .. import paths
from ..errors import TBlade3Error
from ..geometry import Geometry
from .base import Engine

_AUX_PREFIXES = ("spancontrolinputs.", "controlinputs.")
_CHILD_SENT = 17        # exit status of a child that delivered its reply


def make_work_dir(prefix: str = "tb3_") -> Path:
    """A private scratch folder, in memory (/dev/shm) when the system has it."""
    base = "/dev/shm" if os.path.isdir("/dev/shm") and os.access("/dev/shm", os.W_OK) else None
    return Path(tempfile.mkdtemp(prefix=prefix, dir=base))


def clear_dir(path: Path) -> None:
    for entry in path.iterdir():
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            entry.unlink(missing_ok=True)


def row_of(main: str) -> str:
    """'3dbgbinput.2.dat' -> '2' (T-Blade3 takes the row from the file name the same way)."""
    parts = main.split(".")
    if len(parts) < 3:
        raise TBlade3Error(f"main input file name {main!r} is not of the form 3dbgbinput.<row>.dat")
    return parts[-2]


def log_tail(work_dir: Path, lines: int = 25) -> str:
    """The end of error.log, T-Blade3_run.log and the captured output, for error messages."""
    out = []
    for name in ("error.log", "T-Blade3_run.log", "stdout.log"):
        f = work_dir / name
        if f.is_file():
            text = f.read_text(errors="replace").strip().splitlines()
            if name == "error.log" and len(text) <= 1:      # only the header line: no errors
                continue
            if text:
                out.append(f"--- {name} ---\n" + "\n".join(text[-lines:]))
    return "\n".join(out)


# ---------------------------------------------------------------------------------------------
# Worker process and its per-run children
# ---------------------------------------------------------------------------------------------

class _Library:
    """ctypes wrapper of libTBlade3.so (see source/capi.f90 and source/file_operations.f90)."""

    def __init__(self, path: Path):
        self.lib = ctypes.CDLL(str(path))
        self.lib.tb_run.argtypes = [ctypes.c_char_p] * 5
        self.lib.tb_run.restype = ctypes.c_int
        self.lib.tb_get_xyz_ders_size.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
        self.lib.tb_get_xyz_ders_size.restype = ctypes.c_int
        self.lib.tb_get_xyz_ders.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                             np.ctypeslib.ndpointer(np.float64, flags="C_CONTIGUOUS")]
        self.lib.tb_get_xyz_ders.restype = ctypes.c_int
        try:                                    # absent in libraries built before the switch existed
            self._set_write_der_files = self.lib.tb_set_write_der_files
            self._set_write_der_files.argtypes = [ctypes.c_int]
            self._set_write_der_files.restype = None
        except AttributeError:
            self._set_write_der_files = None

    def run(self, main: str, aux: str, args: tuple[str, ...]) -> None:
        # The section derivatives are read from memory (xyz_derivatives), so T-Blade3 need not
        # write them as formatted text: about 170 files for a typical blade, most of the run time.
        if self._set_write_der_files is not None:
            self._set_write_der_files(0)
        a = [s.encode() for s in (*args, "", "", "")[:3]]
        self.lib.tb_run(main.encode(), aux.encode(), *a)

    def xyz_derivatives(self, nsec: int, npt: int) -> dict[tuple[int, int, int], np.ndarray]:
        """Section derivatives straight from memory, keyed like the derivative file names.

        The entries are those T-Blade3 writes to derivative_files/ (write_xyz_der_files), so the
        result is the same set the executable engine reads from the files, at full precision. The
        curvature group (6) holds the chordwise locations u2.. in its first fields; T-Blade3 does
        not differentiate with respect to those and writes only the cur1.. fields.
        """
        out: dict[tuple[int, int, int], np.ndarray] = {}
        dims = (ctypes.c_int * 4)()
        buf = np.empty(3 * nsec * npt)
        for group in range(1, 8):
            if self.lib.tb_get_xyz_ders_size(group, dims) != 0:
                continue
            ns, np_, nparams, ncp = dims
            if (ns, np_) != (nsec, npt):
                continue
            for k in range(nparams // 2 if group == 6 else 1, nparams + 1):
                for l in range(1, ncp + 1):
                    if self.lib.tb_get_xyz_ders(group, k, l, buf) == 0:
                        out[(group, k, l)] = buf.reshape(nsec, npt, 3).copy()
        return out


def _run_in_child(lib: _Library, work_dir: Path, files: Mapping[str, str], main: str,
                  derivatives: bool) -> Geometry:
    from ..io import outputs

    clear_dir(work_dir)
    for name, text in files.items():
        if os.sep in name or name in (".", ".."):
            raise TBlade3Error(f"input file name {name!r} must be a plain file name")
        (work_dir / name).write_text(text)
    (work_dir / "derivative_files").mkdir()     # saves T-Blade3 a shell call
    row = row_of(main)
    aux = next((n for n in files if n.startswith(_AUX_PREFIXES)), f"spancontrolinputs.{row}.dat")

    # T-Blade3 prints to stdout even when quiet; send that to a file in the work folder.
    # (This is a forked child that exits afterwards, so nothing needs restoring.)
    log_fd = os.open(work_dir / "stdout.log", os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
    os.dup2(log_fd, 1)
    os.dup2(log_fd, 2)
    lib.run(main, aux, ("quiet",))

    try:
        geo = outputs.read_run_dir(work_dir, derivatives=False)
    except Exception as exc:                    # no usable section output
        raise TBlade3Error(f"T-Blade3 produced no usable geometry: {exc}", log_tail(work_dir)) from None
    if derivatives:
        geo.derivatives = outputs.read_derivatives(work_dir, geo.nsec, geo.npt, xyz=False)
        geo.derivatives.xyz = lib.xyz_derivatives(geo.nsec, geo.npt)
    return geo


def _child(conn, lib: _Library, work: Path, request) -> None:
    """Forked per run: run T-Blade3 from the pristine library state, reply, exit."""
    files, main, derivatives = request
    try:
        try:
            reply = ("ok", _run_in_child(lib, work, files, main, derivatives), None)
        except TBlade3Error as exc:
            reply = ("error", exc.message, exc.log)
        except Exception as exc:                # bug on the Python side
            reply = ("error", f"{type(exc).__name__}: {exc}", log_tail(work))
        conn.send(reply)
        conn.close()
    except BaseException:
        os._exit(3)                             # the worker reports the failure
    os._exit(_CHILD_SENT)


def worker_main(conn, lib_path: str, work_dir: str) -> None:
    """Loop of the worker process: fork one child per request until the pipe closes."""
    work = Path(work_dir)
    os.chdir(work)
    try:
        lib = _Library(Path(lib_path))
    except OSError as exc:
        conn.send(("error", f"cannot load {lib_path}: {exc}", ""))
        return
    conn.send(("ready", None, None))
    while True:
        try:
            request = conn.recv()
        except (EOFError, OSError):
            return
        if request is None:
            return
        pid = os.fork()
        if pid == 0:
            _child(conn, lib, work, request)    # never returns
        _, status = os.waitpid(pid, 0)
        if os.WIFEXITED(status) and os.WEXITSTATUS(status) == _CHILD_SENT:
            continue                            # the child sent the reply itself
        if os.WIFSIGNALED(status):
            message = f"T-Blade3 crashed (signal {os.WTERMSIG(status)})"
        elif os.WEXITSTATUS(status) == 0:
            message = "T-Blade3 stopped with a fatal error"
        else:
            message = f"T-Blade3 stopped with a run-time error (exit code {os.WEXITSTATUS(status)})"
        conn.send(("error", message, log_tail(work)))


# ---------------------------------------------------------------------------------------------
# Engine (parent side)
# ---------------------------------------------------------------------------------------------

class LibraryEngine(Engine):
    """Runs T-Blade3 through libTBlade3.so in a helper process (see the module docstring).

    One engine serves one blade row at a time; use one engine per row to build rows in parallel.
    ``run`` may be called from any thread, one call at a time.
    """

    def __init__(self, lib: str | os.PathLike | None = None, timeout: float = 120.0):
        self.lib_path = Path(lib) if lib else paths.library()
        if not self.lib_path.is_file():
            raise FileNotFoundError(f"T-Blade3 shared library not found: {self.lib_path}")
        self.timeout = timeout
        self.work_dir = make_work_dir()
        self._proc: subprocess.Popen | None = None
        self._conn = None
        self._lock = threading.Lock()
        self.restarts = 0                       # number of times the worker itself had to be replaced

    # -- worker management --------------------------------------------------------------------
    def _start(self) -> None:
        ours, theirs = socket.socketpair()
        package_parent = str(Path(__file__).resolve().parents[2])
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [package_parent, env.get("PYTHONPATH")]))
        try:
            # Own session: the engine can then kill the worker together with a child running T-Blade3.
            self._proc = subprocess.Popen(
                [sys.executable, "-m", "tblade3.engine._worker", str(self.lib_path), str(self.work_dir),
                 str(theirs.fileno())],
                pass_fds=[theirs.fileno()], start_new_session=True, stdin=subprocess.DEVNULL, env=env)
        finally:
            theirs.close()
        self._conn = Connection(ours.detach())
        status, message, log = self._receive(self.timeout)
        if status != "ready":
            self._stop()
            raise TBlade3Error(message or "T-Blade3 worker failed to start", log or "")

    def _stop(self) -> None:
        proc, conn = self._proc, self._conn
        self._proc = self._conn = None
        if conn is not None:
            conn.close()
        if proc is not None:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    proc.kill()
            try:
                proc.wait(5.0)
            except subprocess.TimeoutExpired:
                pass

    def _receive(self, timeout: float):
        """One reply. A silent or dead worker becomes TBlade3Error and is replaced on the next run."""
        try:
            if not self._conn.poll(timeout):
                self._stop()
                self.restarts += 1
                raise TBlade3Error(f"T-Blade3 did not finish within {timeout:g} s", log_tail(self.work_dir))
            return self._conn.recv()
        except (EOFError, OSError):
            self._stop()
            self.restarts += 1
            raise TBlade3Error("the T-Blade3 worker process ended unexpectedly", log_tail(self.work_dir)) from None

    # -- Engine interface ---------------------------------------------------------------------
    def run(self, files: Mapping[str, str], main: str, *, derivatives: bool = True,
            timeout: float | None = None) -> Geometry:
        if main not in files:
            raise ValueError(f"main input file {main!r} is not among the given files")
        with self._lock:
            if self.work_dir is None:
                raise RuntimeError("engine is closed")
            if self._proc is None or self._proc.poll() is not None:
                self._stop()
                self._start()
            try:
                self._conn.send((dict(files), main, derivatives))
            except (BrokenPipeError, OSError):
                self._stop()
                self._start()
                self._conn.send((dict(files), main, derivatives))
            status, payload, log = self._receive(self.timeout if timeout is None else timeout)
            if status == "ok":
                return payload
            raise TBlade3Error(payload, log or "")

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.send(None)
                except (BrokenPipeError, OSError):
                    pass
            self._stop()
            if self.work_dir is not None:
                shutil.rmtree(self.work_dir, ignore_errors=True)
                self.work_dir = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
