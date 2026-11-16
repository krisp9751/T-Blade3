"""Read the output files of a finished T-Blade3 run into a ``Geometry``.

File names written by T-Blade3 (``<cn>`` = casename, ``<r>`` = blade row, ``<i>`` = section, 1-based):

- ``blade3d.<cn>.dat``             header "npt nsec", then all (x, y, z) points, section-major
- ``sec<i>.<cn>.dat``              (x, y, z) of one section (same data as blade3d)
- ``meanline.sec<i>.<cn>.dat``     (x, y, z) of one 3D meanline
- ``blade.<i>.<r>.<cn>``           2D section (m-prime, theta) after two header lines
- ``blade_section_data.<cn>.dat``  fixed-width table, one row per section
- ``geom_data.<cn>.csv``           csv table (only for some thickness/clustering options)
- ``hub.<cn>.sldcrv``, ``casing.<cn>.sldcrv``   (x, y, z) curves
- ``LE_TE_intersection.<cn>.dat``  per section: x_le, r_le, x_te, r_te (non-dimensional)
- ``thickness_data.<i>.<cn>``      thickness against chord fraction; the columns depend on the
                                   distribution (see ``read_thickness``)
- ``T-Blade3_run.log``, ``error.log``
- ``derivative_files/xyz_ders_<g>_<f>_<cp>.dat``, ``stagger_ders_<g>_<f>.dat``, ``throat_ders_<g>_<f>.dat``
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from ..errors import TBlade3Error
from ..geometry import Derivatives, Geometry

__all__ = ["read_run_dir", "read_sections", "read_derivatives", "read_section_table", "read_thickness",
           "find_casename", "find_row"]

# Fortran fixed-format width of the numbers in the derivative files ('(3F22.16)' / '(nF22.16)').
_DER_WIDTH = 22

# Columns of blade_section_data.<cn>.dat, in file order. Lengths are in the units of the scale
# factor (normally mm); angles in degrees.
_SECTION_DATA_COLUMNS = (
    "section",          # section number, 1-based
    "span",             # normalized span
    "beta_z_le",        # betaZ* at LE (deg)
    "beta_z_te",        # betaZ* at TE (deg)
    "beta_m_le",        # betaM* at LE (deg)
    "beta_m_te",        # betaM* at TE (deg)
    "chord",            # actual chord
    "sweep",            # m-prime offset of the section (bladedata(7))
    "lean",             # theta offset of the section (bladedata(8))
    "area",             # section area
    "lethk",            # LE thickness parameter * chord (input-based, see bladegen.f90)
    "tethk",            # TE thickness parameter * chord
    "throat",           # minimum 3D throat
    "pitch",            # blade pitch angle 2*pi/nblades (header "(r*delta_theta)LE/TE/WT")
    "zweifel",          # geometric Zweifel coefficient
    "throat_location",  # 'le', 'te', 'between' or 'none' (string column)
)

# Columns of geom_data.<cn>.csv, in file order. section/span/chord/throat duplicate the columns of
# blade_section_data with more digits, and replace them.
_GEOM_DATA_COLUMNS = ("section", "span", "meridional_chord", "chord", "throat",
                      "le_thickness", "max_thickness", "te_thickness")


# --------------------------------------------------------------------------------------------
# Low-level readers
# --------------------------------------------------------------------------------------------
def _load(path: Path, skip: int = 0) -> np.ndarray:
    """Load a whitespace-separated numeric table as a 2D float array."""
    return np.loadtxt(path, skiprows=skip, ndmin=2)


def _load_fixed(path: Path, width: int = _DER_WIDTH) -> np.ndarray:
    """Load a table of Fortran 'Fw.d' fields as a 2D float array.

    Tries a fast whitespace split first. Falls back to fixed-width slicing when fields run
    together (large negative values) or overflowed ('****', mapped to NaN).
    """
    try:
        return _load(path)
    except ValueError:
        pass
    rows = []
    for line in path.read_text().splitlines():
        line = line.rstrip()
        if not line:
            continue
        fields = [line[i:i + width] for i in range(0, len(line), width)]
        rows.append([np.nan if "*" in f else float(f) for f in fields])
    return np.array(rows, dtype=float)


def _float_or_nan(token: str) -> float:
    return np.nan if "*" in token else float(token)


def _read_points(path: Path, ncols: int, skip: int = 0) -> np.ndarray:
    data = _load(path, skip)
    if data.shape[1] != ncols:
        raise TBlade3Error(f"{path.name}: expected {ncols} columns, found {data.shape[1]}")
    return data


def _stack(arrays: list[np.ndarray], what: str) -> np.ndarray:
    """Stack equally sized per-section arrays; raise a clear error if their sizes differ."""
    counts = [len(a) for a in arrays]
    if len(set(counts)) > 1:
        detail = ", ".join(f"{i + 1}:{n}" for i, n in enumerate(counts))
        raise TBlade3Error(f"{what} have different numbers of points (section:points {detail})")
    return np.stack(arrays)


def _numbered(path: Path, pattern: str) -> list[Path]:
    """Files matching ``pattern`` (a regex with one group for the 1-based index), sorted by it.

    Raises if the numbering has gaps.
    """
    rx = re.compile(pattern)
    found = {}
    for p in path.iterdir():
        m = rx.fullmatch(p.name)
        if m:
            found[int(m.group(1))] = p
    if not found:
        return []
    n = max(found)
    missing = sorted(set(range(1, n + 1)) - set(found))
    if missing:
        raise TBlade3Error(f"{path}: files for sections {missing} are missing ({pattern})")
    return [found[i] for i in range(1, n + 1)]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except FileNotFoundError:
        return ""


# --------------------------------------------------------------------------------------------
# Casename and row
# --------------------------------------------------------------------------------------------
def find_casename(path: str | Path) -> str:
    """Casename of the run in ``path``, from ``blade3d.<cn>.dat`` (or ``sec1.<cn>.dat``)."""
    path = Path(path)
    for prefix in ("blade3d.", "sec1."):
        names = sorted(p.name[len(prefix):-4] for p in path.glob(f"{prefix}*.dat"))
        if len(names) == 1:
            return names[0]
        if len(names) > 1:
            raise ValueError(f"{path} holds several cases ({', '.join(names)}); pass casename")
    raise FileNotFoundError(f"no T-Blade3 section output (blade3d.*.dat or sec1.*.dat) in {path}")


def find_row(path: str | Path, casename: str) -> int:
    """Blade-row number of the run, from ``blade.1.<row>.<cn>``, the input file name or the log."""
    path = Path(path)
    rx = re.compile(r"blade\.1\.(\d+)\." + re.escape(casename))
    for p in path.glob("blade.1.*"):
        m = rx.fullmatch(p.name)
        if m:
            return int(m.group(1))
    rows = {int(m.group(1)) for p in path.glob("3dbgbinput.*.dat")
            if (m := re.fullmatch(r"3dbgbinput\.(\d+)\.dat", p.name))}
    if len(rows) == 1:
        return rows.pop()
    m = re.search(r"bladerow #:\s*(\d+)", _read_text(path / "T-Blade3_run.log"))
    if m:
        return int(m.group(1))
    raise ValueError(f"cannot determine the blade row of the run in {path}; pass row")


# --------------------------------------------------------------------------------------------
# Public readers
# --------------------------------------------------------------------------------------------
def read_sections(path: str | Path, casename: str) -> np.ndarray:
    """(nsec, npt, 3) section coordinates. Reads ``blade3d.<cn>.dat``, else ``sec<i>.<cn>.dat``."""
    path = Path(path)
    b3d = path / f"blade3d.{casename}.dat"
    if b3d.exists():
        with open(b3d) as f:
            header = f.readline().split()
        try:
            npt, nsec = int(header[0]), int(header[1])
        except (IndexError, ValueError):
            raise TBlade3Error(f"{b3d.name}: bad header line {' '.join(header)!r}") from None
        data = _read_points(b3d, 3, skip=1)
        if data.shape[0] != npt * nsec:
            raise TBlade3Error(f"{b3d.name}: header says {nsec} sections x {npt} points, "
                               f"file has {data.shape[0]} points")
        return data.reshape(nsec, npt, 3)
    files = _numbered(path, r"sec(\d+)\." + re.escape(casename) + r"\.dat")
    if not files:
        raise FileNotFoundError(f"no section files for case {casename!r} in {path}")
    return _stack([_read_points(p, 3) for p in files], "blade sections")


def read_derivatives(path: str | Path, nsec: int, npt: int, xyz: bool = True) -> Derivatives:
    """Read ``derivative_files/`` (``path`` may be the run folder or that folder itself).

    Missing folder or files give empty dictionaries. A file of the wrong size raises TBlade3Error.
    ``xyz=False`` skips the section-point derivatives (the library engine takes those from memory).
    """
    path = Path(path)
    if (path / "derivative_files").is_dir():
        path = path / "derivative_files"
    ders = Derivatives()
    if not path.is_dir():
        return ders
    rx = re.compile(r"(xyz|stagger|throat)_ders_(\d+)_(\d+)(?:_(\d+))?\.dat")
    for p in sorted(path.iterdir()):
        m = rx.fullmatch(p.name)
        if not m:
            continue
        kind, g, f, cp = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)
        if kind == "xyz" and not xyz:
            continue
        data = _load_fixed(p)
        if kind == "xyz":
            if cp is None:
                continue
            if data.shape != (nsec * npt, 3):
                raise TBlade3Error(f"{p.name}: shape {data.shape}, expected ({nsec * npt}, 3)")
            ders.xyz[(g, f, int(cp))] = data.reshape(nsec, npt, 3)
        elif cp is None:
            if data.shape[0] != nsec:
                raise TBlade3Error(f"{p.name}: {data.shape[0]} rows, expected {nsec}")
            (ders.stagger if kind == "stagger" else ders.throat)[(g, f)] = data
    return ders


def read_section_table(path: str | Path, casename: str) -> dict[str, np.ndarray]:
    """Per-section columns of ``blade_section_data.<cn>.dat`` and ``geom_data.<cn>.csv``.

    Keys are listed in ``_SECTION_DATA_COLUMNS`` and ``_GEOM_DATA_COLUMNS``. Overflowed Fortran
    fields ('*****') become NaN. 'section' is an int array, 'throat_location' a str array.
    Missing files give an empty (or partial) table.
    """
    path = Path(path)
    table: dict[str, np.ndarray] = {}

    bsd = path / f"blade_section_data.{casename}.dat"
    if bsd.exists():
        rows = []
        in_table = False
        for line in bsd.read_text(errors="replace").splitlines():
            tokens = line.split()
            if not tokens:
                continue
            if tokens[0] == "section":
                in_table = True
                continue
            if not in_table or not tokens[0].isdigit():
                if in_table:
                    break           # 'Total Volume ...' line ends the table
                continue
            if len(tokens) != len(_SECTION_DATA_COLUMNS):
                raise TBlade3Error(f"{bsd.name}: cannot parse row {line.strip()!r}")
            rows.append(tokens)
        if rows:
            cols = list(zip(*rows))
            for name, col in zip(_SECTION_DATA_COLUMNS[:-1], cols[:-1]):
                table[name] = np.array([_float_or_nan(t) for t in col])
            table["section"] = table["section"].astype(int)
            loc = [{"btwee": "between"}.get(t, t) for t in cols[-1]]
            table["throat_location"] = np.array(loc)

    csv = path / f"geom_data.{casename}.csv"
    if csv.exists():
        rows = [line.split(",") for line in csv.read_text(errors="replace").splitlines()[1:]
                if line.strip()]
        if rows:
            if any(len(r) != len(_GEOM_DATA_COLUMNS) for r in rows):
                raise TBlade3Error(f"{csv.name}: expected {len(_GEOM_DATA_COLUMNS)} columns")
            cols = list(zip(*rows))
            for name, col in zip(_GEOM_DATA_COLUMNS, cols):
                table[name] = np.array([_float_or_nan(t.strip()) for t in col])
            table["section"] = table["section"].astype(int)
    return table


def _read_thickness_file(path: Path) -> np.ndarray:
    """(n, 2): u, full thickness / chord, from one thickness_data file of any of the three formats."""
    rows = []
    for line in path.read_text(errors="replace").splitlines():
        tokens = line.split()
        if not tokens:
            continue
        if "*" in line:             # an overflowed '(4F40.16)' field runs into its neighbour: slice it
            line = line.rstrip()
            tokens = [line[i:i + 40] for i in range(0, len(line), 40)]
        try:
            rows.append([_float_or_nan(t) for t in tokens])
        except ValueError:
            if rows:
                raise TBlade3Error(f"{path.name}: cannot parse row {line.strip()!r}") from None
            continue                # header line of the spline format
    if not rows:
        return np.zeros((0, 2))
    if len({len(r) for r in rows}) != 1:
        raise TBlade3Error(f"{path.name}: rows of different lengths")
    data = np.array(rows, dtype=float)
    ncol = data.shape[1]
    if ncol == 4:                   # modified NACA: u, thickness, dt/du, d2t/du2 (full thickness)
        t = data[:, 1]
    elif ncol == 2:                 # Wennerstrom: u, half thickness
        t = 2.0 * data[:, 1]
    elif ncol == 3:                 # spline: u, top, bottom
        t = data[:, 1] - data[:, 2]
    else:
        raise TBlade3Error(f"{path.name}: {ncol} columns, expected 2, 3 or 4")
    return np.column_stack([data[:, 0], t])


def read_thickness(path: str | Path, casename: str, nsec: int) -> list[np.ndarray]:
    """Thickness distribution of each section from ``thickness_data.<i>.<cn>``.

    The files differ by thickness distribution (bladegen.f90 / file_operations.f90): modified NACA
    writes u, thickness, dt/du, d2t/du2; Wennerstrom u and half the thickness; the spline
    distributions a header and u, top, bottom. All become (n, 2) arrays of u and the full thickness
    divided by the chord. Sections without a file (not 'sect1') get an empty (0, 2) array; no files
    at all give an empty list.
    """
    path = Path(path)
    rx = re.compile(r"thickness_data\.(\d+)\." + re.escape(casename))
    found = {}
    for p in path.glob("thickness_data.*"):
        m = rx.fullmatch(p.name)
        if m and 1 <= int(m.group(1)) <= nsec:
            found[int(m.group(1))] = p
    if not found:
        return []
    return [_read_thickness_file(found[i]) if i in found else np.zeros((0, 2)) for i in range(1, nsec + 1)]


def read_run_dir(path: str | Path, casename: str | None = None, row: int | None = None,
                 derivatives: bool = True) -> Geometry:
    """Read all outputs of a finished T-Blade3 run in folder ``path`` into a ``Geometry``.

    ``casename`` and ``row`` are found from the file names when not given. Only the section
    coordinates are required; other missing files give None or empty fields.
    """
    path = Path(path)
    if not path.is_dir():
        raise FileNotFoundError(f"not a folder: {path}")
    casename = casename or find_casename(path)
    row = find_row(path, casename) if row is None else row
    cn = re.escape(casename)

    sections = read_sections(path, casename)
    nsec, npt = sections.shape[:2]

    mfiles = _numbered(path, r"meanline\.sec(\d+)\." + cn + r"\.dat")
    meanlines = _stack([_read_points(p, 3) for p in mfiles], "meanlines") if mfiles else None

    bfiles = _numbered(path, r"blade\.(\d+)\." + str(row) + r"\." + cn)
    sections_2d = [_read_points(p, 2, skip=2) for p in bfiles]

    def optional_points(name: str, ncols: int) -> np.ndarray | None:
        p = path / name
        return _read_points(p, ncols) if p.exists() and p.stat().st_size else None

    warnings = "\n".join(line.strip() for line in _read_text(path / "error.log").splitlines()
                         if line.strip() and line.strip() != "T-Blade3 ERROR LOG FILE")

    return Geometry(
        casename=casename,
        row=row,
        sections=sections,
        meanlines=meanlines,
        sections_2d=sections_2d,
        section_table=read_section_table(path, casename),
        hub=optional_points(f"hub.{casename}.sldcrv", 3),
        casing=optional_points(f"casing.{casename}.sldcrv", 3),
        le_te=optional_points(f"LE_TE_intersection.{casename}.dat", 4),
        thickness=read_thickness(path, casename, nsec),
        derivatives=(read_derivatives(path, nsec, npt)
                     if derivatives and (path / "derivative_files").is_dir() else None),
        log=_read_text(path / "T-Blade3_run.log"),
        warnings=warnings,
    )
