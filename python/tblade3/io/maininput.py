"""The main T-Blade3 input file, 3dbgbinput.<row>.dat.

``MainInput`` holds every value the file carries. ``parse`` and ``format`` mirror the reader in
source/readinput.f90 (subroutine readinput), including its positional quirks:

* list-directed reads (``read(1,*)``) may run on into following records and skip blank ones; the
  parser emulates them (``_records.Records``), so it depends on label wording only where Fortran does;
* units are characters 24-25 of the scale-factor label; an optional theta offset follows the scale
  factor (without it, Fortran rewinds and skips eight records list-directed, so the first eight
  lines must not be blank and the streamline-count label must not start with a number);
* without ``spanwise_spline`` on the camber line, the next record must start with ``Airfoil``;
* a second token on the thickness-distribution line means the multiplier label is absent;
* the sweep and lean counts are read from column 12 only (a single digit);
* the tm/c table header decides its columns, the airfoil header (Jcells/eta_ofst/BGgrid) the grid
  columns, the number of tokens on the hub/tip offset lines the inflation offsets;
* streamline data starts after the record whose first token is ``x_s``; each streamline ends with a
  row whose r is 0.

``format`` writes all counts from the data. Label lines come from ``labels`` when they are still
valid for the data, otherwise from built-in defaults.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..errors import InputFormatError
from ._records import Records, first_token, fortran_int, fortran_real, num

ANGLE_SPLINES = ("", "inletspline", "outletspline", "inoutspline", "inci_dev_spline")
THICKNESS_DISTRIBUTIONS = {0: "Wennerstrom", 1: "Spline", 2: "Spline, sharp TE", 5: "Modified NACA four-digit"}
CLUSTERING = {0: "uniform", 1: "sine", 2: "exponential", 3: "hyperbolic", 4: "elliptical"}
SECTION_COLUMNS = ("in_beta", "out_beta", "mrel_in", "chord", "tc_max", "incidence", "deviation",
                   "sec_flow_angle")
GRID_WORDS = ("Jcells", "eta_ofst", "BGgrid")
# Spanwise control tables: attribute, label key, value column name.
CONTROL_TABLES = (("sweep", "delta_m"), ("lean", "delta_theta"), ("in_beta", "in_beta*"),
                  ("out_beta", "out_beta*"), ("chord_multiplier", "chord_multiplier"))
UNITS = {"mm": "mm", "cm": "cm", "m)": "m", "m ": "m"}


@dataclass
class ControlTable:
    """Spanwise control points: span locations (0 at hub, 1 at tip) and one or more value columns.

    ``values`` keeps the file's column order, e.g. {"delta_m": ...} for sweep or
    {"tm/c": ..., "u_max": ...} for the thickness table.
    """
    span: np.ndarray
    values: dict[str, np.ndarray]

    def __len__(self) -> int:
        return len(self.span)


@dataclass
class MainInput:
    # -- header and switches ------------------------------------------------------------------
    casename: str = "case"
    row: int = 1
    n_blades: int = 1
    scale_factor: float = 1.0
    units: str = "mm"                        # taken from the "Blade Scaling factor (mm):" label
    theta_offset: float | None = None        # optional second number on the scale-factor line
    angle_switch: int = 0                    # 0 axial, 1 radial, 2 axial in/radial out, 3 radial in/axial out, 4 wing
    angle_spline: str = ""                   # one of ANGLE_SPLINES
    curvature_control: int = 0               # camber defined by curvature control (0/1)
    spanwise_spline: bool = False            # True: use spancontrolinputs.<row>.dat
    thickness_distribution: int = 0          # key of THICKNESS_DISTRIBUTIONS
    thickness_multiplier: int = 0            # 0/1
    le_spline: int = 0                       # must be 0 in current T-Blade3
    chord_switch: int = 0                    # 0 computed, 1 actual chord from the section table, 2 spline multiplier
    true_lean_sweep: int = 0                 # 0 tangential lean/axial sweep, 1 true lean/sweep
    clustering_switch: int = 0               # key of CLUSTERING
    clustering_parameter: float = 0.0

    # -- sectionwise properties: one entry per streamline -------------------------------------
    sections: dict[str, np.ndarray] = field(default_factory=dict)      # keys: SECTION_COLUMNS

    # -- LE / TE curve ------------------------------------------------------------------------
    le_te: np.ndarray = field(default_factory=lambda: np.zeros((0, 4)))  # columns xLE, rLE, xTE, rTE

    # -- airfoil type and stacking: one entry per streamline ----------------------------------
    variable_stacking: int = 0
    airfoil_type: list[str] = field(default_factory=list)              # sect1, naca4, s809m, crcle
    stk_u: np.ndarray = field(default_factory=lambda: np.zeros(0))
    stk_v: np.ndarray = field(default_factory=lambda: np.zeros(0))
    umxthk: np.ndarray = field(default_factory=lambda: np.zeros(0))
    lethk: np.ndarray = field(default_factory=lambda: np.zeros(0))
    tethk: np.ndarray = field(default_factory=lambda: np.zeros(0))
    grid_columns: np.ndarray | None = None   # legacy (nsl, 3): Jcells, eta_ofst, BGgrid; kept for round trip

    # -- blending section variable ------------------------------------------------------------
    blend_bsv1: int = 0
    blend_bsv2: int = 0
    blending: ControlTable = field(default_factory=lambda: ControlTable(np.zeros(0), {}))   # bf1, bf2 (integers)

    stacking_axis: int = 0                   # e.g. 25000 (written as 025000), 200000 = centroid

    # -- spanwise control tables --------------------------------------------------------------
    sweep: ControlTable = field(default_factory=lambda: ControlTable(np.zeros(0), {}))             # delta_m
    lean: ControlTable = field(default_factory=lambda: ControlTable(np.zeros(0), {}))              # delta_theta
    in_beta: ControlTable = field(default_factory=lambda: ControlTable(np.zeros(0), {}))           # in_beta*
    out_beta: ControlTable = field(default_factory=lambda: ControlTable(np.zeros(0), {}))          # out_beta*
    chord_multiplier: ControlTable = field(default_factory=lambda: ControlTable(np.zeros(0), {}))  # chord_multiplier
    thickness: ControlTable = field(default_factory=lambda: ControlTable(np.zeros(0), {}))         # tm/c and/or u_max

    # -- offsets ------------------------------------------------------------------------------
    hub_offset: float = 0.0
    tip_offset: float = 0.0
    hub_inflation_offset: float | None = None   # second number on the hub offset line, if present
    tip_inflation_offset: float | None = None

    # -- streamlines: one (n, 2) array of (x_s, r_s) per streamline, hub first ----------------
    streamlines: list[np.ndarray] = field(default_factory=list)

    # -- verbatim text kept so that load -> save keeps the file recognisable ------------------
    labels: dict[str, str] = field(default_factory=dict)   # label/comment lines, keyed by block name

    @property
    def n_streamlines(self) -> int:
        return len(self.streamlines)


# --------------------------------------------------------------------------------------------
# Default label lines (one list of lines per block; "\n"-joined in MainInput.labels)
# --------------------------------------------------------------------------------------------

_SECTIONS_HEADER = (" J        in_Beta        out_Beta          mrel_in           chord           t/c_max"
                    "         Incidence       Deviation      Sec. Flow Angle")
_AIRFOIL_HEADER = " J   type |stk_u |stk_v |umxthk |lethk |tethk"
_AIRFOIL_HEADER_GRID = (_AIRFOIL_HEADER + "  |Jcells(Grid:4n+1) |eta_ofst(<=10)[thkc/Jmax]  |BGgrid(0=no,1=yes) |")

DEFAULT_LABELS: dict[str, list[str]] = {
    "title": [" Input parameters (version 1.31)"],
    "row": [" Blade row #:"],
    "n_blades": [" Number of blades in this row:"],
    "scale_factor": [" Blade Scaling factor (mm):"],
    "n_streamlines": [" Number of streamlines:"],
    "angle_switch": [" Angles in the input file (0=Beta_z (default),1=Beta_r):"],
    "curvature_control": [" Airfoil camber defined by curvature control (0=no,1=yes ;spanwise_spline= "
                          "spancontrolinputs file):"],
    "thickness_distribution": [" Airfoil Thickness distribution (0=Wennerstrom,1=Spline,2=Spline + sharp TE,"
                               "5=modified NACA):"],
    "thickness_multiplier": [" Airfoil Thickness multiplier (0=no,1=yes):"],
    "le_spline": [" Airfoil LE defined by spline (0=no,1=yes):"],
    "chord_switch": [" Non-dimensional Actual chord (0=no,1=yes,2=spline):"],
    "true_lean_sweep": [" True lean and sweep (0=no,1=yes):"],
    "clustering": [" Clustering control (0=uniform,1=sine,2=exponential,3=hyperbolic,4=elliptical):"],
    "sections": [" Sectionwise properties:", _SECTIONS_HEADER],
    "le_te": ["", " LE / TE curve (x,r) definition :", " Number of Curve points :"],
    "le_te_header": ["       xLE            rLE            xTE            rTE"],
    "stacking": ["",
                 " # Airfoil type and Variable Radial Stacking information.         #",
                 " # stack_u: % chord stack (0.00 to 100.00).                       #",
                 " # stack_v: % below or above meanline stack (-100.00 to +100.00). #",
                 " # Use +200 for stacking on airfoil area centroid.                #",
                 " Variable Radial stacking (0=no,1=yes):"],
    "airfoil_header": [_AIRFOIL_HEADER],
    "blending": ["", " Control table for blending section variable:"],
    "blending_header": ["       span                       bf1         bf2"],
    "stacking_axis": ["", " Stacking axis location (200=centroid):"],
    "sweep": ["", " Control points for sweep:"],
    "sweep_header": ["        span                   delta_m"],
    "lean": ["", " Control points for lean:"],
    "lean_header": ["        span                    delta_theta"],
    "in_beta": ["", " Control points for in_beta*:"],
    "in_beta_header": ["        span                     in_beta*"],
    "out_beta": ["", " Control points for out_beta*:"],
    "out_beta_header": ["        span                     out_beta*"],
    "chord_multiplier": ["", " Control points for chord_multiplier:"],
    "chord_multiplier_header": ["        span                chord_multiplier"],
    "thickness": ["", " Control points for tm/c:"],
    "thickness_header": ["        span                       tm/c"],
    "hub_offset": ["", " Hub offset"],
    "tip_offset": [" Tip offset"],
    "streamlines": ["", "  Streamline Data", "        x_s                     r_s"],
}
_VARIABLE_LENGTH = {"streamlines"}


# --------------------------------------------------------------------------------------------
# Helpers shared by parse and format
# --------------------------------------------------------------------------------------------

def _units_of(label: str) -> str | None:
    return UNITS.get(label.ljust(25)[23:25])


def _has_grid(header: str) -> bool:
    return any(w in header.rstrip(" ") for w in GRID_WORDS)


def _thickness_columns(header: str) -> tuple[str, ...]:
    """Columns of the tm/c table as decided by its header (Fortran index() of 'tm/c' and 'u_max')."""
    h = header.rstrip(" ")
    itm, ium = h.find("tm/c") + 1, h.find("u_max") + 1
    if itm and ium:
        return ("tm/c", "u_max") if itm < ium else ("u_max", "tm/c")
    if itm:
        return ("tm/c",)
    if ium:
        return ("u_max",)
    return ()


def _split_offset(line: str, rec: Records, what: str) -> tuple[float, float | None]:
    """Hub/tip offset line: one number, or offset and inflation offset (first and last blank-separated pieces)."""
    s = line.strip(" ")

    def read(piece: str) -> float:
        try:
            return Records(piece).values("f", what)[0]
        except InputFormatError:
            raise rec.error(what) from None

    if " " not in s:
        return read(s), None
    return read(s[:s.index(" ")]), read(s[s.rindex(" "):])


def _blank(line: str) -> bool:
    return not line.strip(" \t")


def _streamline_block_ok(lines: list[str]) -> bool:
    """True if the Fortran x_s search over these label lines ends exactly at the last one."""
    if len(lines) < 2:
        return False
    if lines[1].rstrip(" ") == "x_s":
        return len(lines) == 2
    if len(lines) < 3:
        return False
    rec = Records("\n".join(lines[2:]))
    try:
        while True:
            token = rec.raw(1, "x_s")[0][0]
            if token == "x_s":
                return rec.pos == len(rec.lines)
    except InputFormatError:
        return False


# --------------------------------------------------------------------------------------------
# parse
# --------------------------------------------------------------------------------------------

def parse(text: str) -> MainInput:
    """Parse the text of a 3dbgbinput.<row>.dat file."""
    r = Records(text, "3dbgbinput file")
    inp = MainInput()
    lab: dict[str, str] = {}

    def label(key: str, n: int = 1) -> list[str]:
        lines = r.lines_n(n, f"{n} label line(s) ({key})")
        lab[key] = "\n".join(lines)
        return lines

    def table(n: int, kinds: str, what: str) -> list[list]:
        return [r.values(kinds, what) for _ in range(n)]

    # Header: casename, row, blades, units, scale factor (+ theta offset)
    label("title")
    inp.casename = r.values("s", "the casename")[0] or ""
    label("row")
    inp.row = r.values("i", "the blade row number (integer)")[0]
    label("n_blades")
    inp.n_blades = r.values("i", "the number of blades (integer)")[0]
    units_label = label("scale_factor")[0]
    units = _units_of(units_label)
    if units is None:
        raise r.error("units mm, cm or m in characters 24-25 of the scale-factor label")
    inp.units = units
    scf, temp = r.values("fs", "the blade scaling factor")
    inp.scale_factor = scf
    theta = fortran_real(temp) if temp is not None else None
    if theta is not None:
        inp.theta_offset = theta
    else:
        # Fortran: rewind and skip eight records with list-directed reads (blank records are skipped)
        r.pos = 0
        for _ in range(8):
            r.raw(1, "a header line")
    label("n_streamlines")
    nsl = r.values("i", "the number of streamlines (integer)")[0]
    label("angle_switch")

    # Angle switch line: one digit 0-4, optionally followed by a spline keyword
    beta = r.line("the angle switch line")
    digits = [d for d in "01234" if d in beta]
    if len(digits) != 1:
        raise r.error("an angle switch 0, 1, 2, 3 or 4")
    inp.angle_switch = int(digits[0])
    n_digit = 0 if digits[0] == "4" else beta.index(digits[0]) + 1
    found = [s for s in ANGLE_SPLINES[1:] if s in beta]
    if len(found) == 0 and len(beta[:n_digit]) == len(beta.rstrip(" ")):
        inp.angle_spline = ""
    elif len(found) == 1 and len(beta[:n_digit]) != len(beta.rstrip(" ")):
        inp.angle_spline = found[0]
    else:
        raise r.error("nothing or one of inletspline, outletspline, inoutspline, inci_dev_spline after the angle switch")
    label("curvature_control")

    # Camber line: read(1,*) curv, spanwise_spline (runs on into the next record if needed)
    tokens, first, last = r.raw(2, "the camber definition switch")
    curv = fortran_int(tokens[0]) if tokens[0] is not None else None
    if curv not in (0, 1):
        raise r.error("camber definition switch 0 or 1", first)
    inp.curvature_control = curv
    if tokens[1] == "spanwise_spline":
        inp.spanwise_spline = True
        label("thickness_distribution")
    elif tokens[1] == "Airfoil":
        inp.spanwise_spline = False
        if last > first:   # the "Airfoil ..." token came from the following label line(s)
            lab["thickness_distribution"] = "\n".join(r.lines[first:last])
    else:
        raise r.error("'spanwise_spline' after the camber switch, or a following label starting with 'Airfoil'", last)

    # Thickness distribution: read(1,*) thick_distr, temp2. A second token on the same line means
    # that the multiplier label is absent (temp2 otherwise swallows that label).
    tokens, first, last = r.raw(2, "the thickness distribution switch")
    td = fortran_int(tokens[0]) if tokens[0] is not None else None
    if td not in THICKNESS_DISTRIBUTIONS:
        raise r.error("thickness distribution switch 0, 1, 2 or 5", first)
    inp.thickness_distribution = td
    if last > first:
        lab["thickness_multiplier"] = "\n".join(r.lines[first:last])
    inp.thickness_multiplier = r.values("i", "the thickness multiplier switch (integer)")[0]
    label("le_spline")
    inp.le_spline = r.values("i", "the LE spline switch (integer)")[0]
    label("chord_switch")
    inp.chord_switch = r.values("i", "the chord switch (integer)")[0]
    label("true_lean_sweep")
    inp.true_lean_sweep = r.values("i", "the true lean/sweep switch (integer)")[0]
    label("clustering")
    inp.clustering_switch, inp.clustering_parameter = r.values("if", "clustering switch and parameter")

    # Sectionwise properties
    label("sections", 2)
    rows = np.array(table(nsl, "f" * 9, "a sectionwise properties row (J and 8 numbers)"), dtype=float).reshape(nsl, 9)
    inp.sections = {c: rows[:, j + 1].copy() for j, c in enumerate(SECTION_COLUMNS)}

    # LE / TE curve
    label("le_te", 3)
    npoints = r.values("i", "the number of LE/TE curve points (integer)")[0]
    label("le_te_header")
    inp.le_te = np.array(table(npoints, "ffff", "an LE/TE curve row xLE rLE xTE rTE"), dtype=float).reshape(npoints, 4)

    # Airfoil type and stacking
    label("stacking", 6)
    inp.variable_stacking = r.values("i", "the variable radial stacking switch (integer)")[0]
    grid = _has_grid(label("airfoil_header")[0])
    kinds = "fsfffff" + ("ffi" if grid else "")
    rows = table(nsl, kinds, "an airfoil/stacking row")
    inp.airfoil_type = [row[1] for row in rows]
    for j, name in enumerate(("stk_u", "stk_v", "umxthk", "lethk", "tethk")):
        setattr(inp, name, np.array([row[j + 2] for row in rows], dtype=float))
    inp.grid_columns = np.array([row[7:10] for row in rows], dtype=float).reshape(nsl, 3) if grid else None

    # Blending section variable
    label("blending", 2)
    cpbsv, inp.blend_bsv1, inp.blend_bsv2 = r.values("iii", "blending count, bsv1 and bsv2 (integers)")
    label("blending_header")
    rows = table(cpbsv, "fii", "a blending row: span bf1 bf2")
    inp.blending = ControlTable(np.array([row[0] for row in rows], dtype=float),
                                {"bf1": np.array([row[1] for row in rows], dtype=int),
                                 "bf2": np.array([row[2] for row in rows], dtype=int)})

    label("stacking_axis", 2)
    inp.stacking_axis = r.values("i", "the stacking axis location (integer)")[0]

    # Spanwise control tables. Sweep and lean counts: read(temp(12:12), *) -> one digit at column 12.
    for attr, column in CONTROL_TABLES:
        label(attr, 2)
        if attr in ("sweep", "lean"):
            count_line = r.line(f"the {attr} control point count")
            n = fortran_int(count_line.ljust(12)[11])
            if n is None:
                raise r.error(f"the {attr} control point count as a single digit at column 12")
        else:
            n = r.values("i", f"the {attr} control point count (integer)")[0]
        label(f"{attr}_header")
        rows = np.array(table(n, "ff", f"a {attr} control point row: span value"), dtype=float).reshape(n, 2)
        setattr(inp, attr, ControlTable(rows[:, 0].copy(), {column: rows[:, 1].copy()}))

    # Thickness (tm/c and/or u_max) table: the header decides the columns
    label("thickness", 2)
    n = r.values("i", "the tm/c control point count (integer)")[0]
    columns = _thickness_columns(label("thickness_header")[0])
    if n and not columns:
        raise r.error("a tm/c table header naming 'tm/c' and/or 'u_max'")
    rows = np.array(table(n, "f" * (1 + len(columns)), "a tm/c control point row"), dtype=float)
    rows = rows.reshape(n, 1 + len(columns))
    inp.thickness = ControlTable(rows[:, 0].copy(), {c: rows[:, j + 1].copy() for j, c in enumerate(columns)})

    # Hub and tip offsets (a second number is the inflation offset)
    label("hub_offset", 2)
    inp.hub_offset, inp.hub_inflation_offset = _split_offset(r.line("the hub offset line"), r, "the hub offset")
    label("tip_offset")
    inp.tip_offset, inp.tip_inflation_offset = _split_offset(r.line("the tip offset line"), r, "the tip offset")

    # Streamlines: data starts after the record whose first token is x_s
    start = r.pos
    r.lines_n(2, "streamline labels")
    if r.lines[start + 1].rstrip(" ") != "x_s":
        while r.raw(1, "a line starting with x_s before the streamline data")[0][0] != "x_s":
            pass
    lab["streamlines"] = "\n".join(r.lines[start:r.pos])
    inp.streamlines = []
    for k in range(nsl):
        points = []
        while True:
            x, rr = r.values("ff", f"a point (x_s r_s) of streamline {k + 1}, or 0 0 to end it")
            if rr == 0:
                break
            points.append((x, rr))
        inp.streamlines.append(np.array(points, dtype=float).reshape(len(points), 2))

    trailing = r.rest()
    if any(not _blank(line) for line in trailing):
        lab["trailing"] = "\n".join(trailing)
    inp.labels = lab
    return inp


# --------------------------------------------------------------------------------------------
# format
# --------------------------------------------------------------------------------------------

def _check_len(name: str, n: int, nsl: int) -> None:
    if n != nsl:
        raise ValueError(f"{name} has {n} entries but there are {nsl} streamlines")


def format(inp: MainInput) -> str:      # noqa: A001  (name mirrors parse)
    """Text of a 3dbgbinput.<row>.dat file that T-Blade3 reads back to the same values."""
    labels = inp.labels or {}
    nsl = len(inp.streamlines)
    for c in SECTION_COLUMNS:
        _check_len(f"sections[{c!r}]", len(inp.sections[c]), nsl)
    for name in ("airfoil_type", "stk_u", "stk_v", "umxthk", "lethk", "tethk"):
        _check_len(name, len(getattr(inp, name)), nsl)
    if inp.grid_columns is not None:
        _check_len("grid_columns", len(inp.grid_columns), nsl)
    if inp.units not in ("mm", "cm", "m"):
        raise ValueError(f"units must be mm, cm or m, not {inp.units!r}")
    if inp.angle_spline not in ANGLE_SPLINES:
        raise ValueError(f"angle_spline must be one of {ANGLE_SPLINES}, not {inp.angle_spline!r}")

    def lab(key: str, ok=None, default: list[str] | None = None) -> list[str]:
        default = DEFAULT_LABELS[key] if default is None else default
        stored = labels.get(key)
        if stored is not None:
            lines = stored.split("\n")
            if (key in _VARIABLE_LENGTH or len(lines) == len(default)) and (ok is None or ok(lines)):
                return lines
        return list(default)

    no_theta = inp.theta_offset is None
    nonblank = (lambda lines: not any(_blank(x) for x in lines)) if no_theta else None
    out: list[str] = []
    out += lab("title", nonblank)
    out.append(f" {inp.casename}")
    out += lab("row", nonblank)
    out.append(f"{inp.row:12d}")
    out += lab("n_blades", nonblank)
    out.append(f"{inp.n_blades:12d}")
    out += lab("scale_factor", lambda ls: _units_of(ls[0]) == inp.units and not _blank(ls[0]),
               [f" Blade Scaling factor ({inp.units}):"])
    out.append(f"   {num(inp.scale_factor)}" + ("" if no_theta else f"  {num(inp.theta_offset)}"))

    def streamline_count_ok(lines: list[str]) -> bool:
        tok = first_token(lines[0])
        return not no_theta or (tok is not None and fortran_real(tok) is None)

    out += lab("n_streamlines", streamline_count_ok)
    out.append(f"{nsl:12d}")
    out += lab("angle_switch")
    out.append(f"{inp.angle_switch:12d}" + (f"  {inp.angle_spline}" if inp.angle_spline else ""))
    out += lab("curvature_control")
    out.append(f"{inp.curvature_control:12d}" + ("  spanwise_spline" if inp.spanwise_spline else ""))
    if inp.spanwise_spline:
        out += lab("thickness_distribution")
    else:
        out += lab("thickness_distribution", lambda ls: first_token(ls[0]) == "Airfoil")
    out.append(f"{inp.thickness_distribution:12d}")
    out += lab("thickness_multiplier", lambda ls: first_token(ls[0]) is not None)
    out.append(f"{inp.thickness_multiplier:12d}")
    out += lab("le_spline")
    out.append(f"{inp.le_spline:12d}")
    out += lab("chord_switch")
    out.append(f"{inp.chord_switch:12d}")
    out += lab("true_lean_sweep")
    out.append(f"{inp.true_lean_sweep:12d}")
    out += lab("clustering")
    out.append(f"{inp.clustering_switch:12d}  {num(inp.clustering_parameter)}")

    out += lab("sections")
    for j in range(nsl):
        out.append(f"{j + 1:2d}" + "".join(f"{num(inp.sections[c][j]):>24}" for c in SECTION_COLUMNS))

    out += lab("le_te")
    out.append(f"{len(inp.le_te):12d}")
    out += lab("le_te_header")
    for x in inp.le_te:
        out.append("".join(f"{num(v):>24}" for v in x))

    out += lab("stacking")
    out.append(f"{inp.variable_stacking:12d}")
    grid = inp.grid_columns is not None
    out += lab("airfoil_header", lambda ls: _has_grid(ls[0]) == grid,
               [_AIRFOIL_HEADER_GRID if grid else _AIRFOIL_HEADER])
    for j in range(nsl):
        if not inp.airfoil_type[j] or any(c in inp.airfoil_type[j] for c in " \t,/'\""):
            raise ValueError(f"airfoil type {inp.airfoil_type[j]!r} cannot be written list-directed")
        line = f"{j + 1:2d}   {inp.airfoil_type[j]}" + "".join(
            f"  {num(getattr(inp, c)[j])}" for c in ("stk_u", "stk_v", "umxthk", "lethk", "tethk"))
        if grid:
            jc, eta, bg = inp.grid_columns[j]
            line += f"  {_short(jc)}  {_short(eta)}  {int(round(bg))}"
        out.append(line)

    out += lab("blending")
    bl = inp.blending
    out.append(f"{len(bl):12d}{inp.blend_bsv1:12d}{inp.blend_bsv2:12d}")
    out += lab("blending_header")
    for j in range(len(bl)):
        out.append(f"{num(bl.span[j]):>22}{int(bl.values['bf1'][j]):12d}{int(bl.values['bf2'][j]):12d}")

    out += lab("stacking_axis")
    out.append(f"       {inp.stacking_axis:06d}")

    for attr, column in CONTROL_TABLES:
        t: ControlTable = getattr(inp, attr)
        n = len(t)
        out += lab(attr)
        if attr in ("sweep", "lean") and not 0 <= n <= 9:
            raise ValueError(f"T-Blade3 reads the {attr} control point count from one column: 0 to 9 points, not {n}")
        out.append(f"{n:12d}")
        out += lab(f"{attr}_header")
        values = t.values[column] if n else []
        for j in range(n):
            out.append(f"{num(t.span[j]):>22}{num(values[j]):>26}")

    t = inp.thickness
    columns = tuple(t.values)
    if columns not in ((), ("tm/c",), ("u_max",), ("tm/c", "u_max"), ("u_max", "tm/c")):
        raise ValueError(f"thickness table columns must be tm/c and/or u_max, not {columns}")
    if len(t) and not columns:
        raise ValueError("thickness table has control points but no tm/c or u_max column")
    out += lab("thickness")
    out.append(f"{len(t):12d}")
    out += lab("thickness_header", lambda ls: _thickness_columns(ls[0]) == columns,
               ["        span" + "".join(f"{c:>27}" for c in columns)])
    for j in range(len(t)):
        out.append(f"{num(t.span[j]):>22}" + "".join(f"{num(t.values[c][j]):>27}" for c in columns))

    out += lab("hub_offset")
    out.append(_offset_line(inp.hub_offset, inp.hub_inflation_offset))
    out += lab("tip_offset")
    out.append(_offset_line(inp.tip_offset, inp.tip_inflation_offset))

    out += lab("streamlines", _streamline_block_ok)
    for k, s in enumerate(inp.streamlines):
        for x, rr in s:
            if rr == 0:
                raise ValueError(f"streamline {k + 1} has a point with r = 0 (that marks the end of a streamline)")
            out.append(f"{num(x):>24}{num(rr):>24}")
        out.append("           0           0")
    if labels.get("trailing"):
        out += labels["trailing"].split("\n")
    return "\n".join(out) + "\n"


def _offset_line(offset: float, inflation: float | None) -> str:
    return f"   {num(offset)}" + ("" if inflation is None else f"  {num(inflation)}")


def _short(x: float) -> str:
    """Integral values without a decimal point (legacy grid columns), else full precision."""
    x = float(x)
    return str(int(x)) if x.is_integer() and abs(x) < 1e15 else repr(x)
