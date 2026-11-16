"""The auxiliary T-Blade3 input files.

``SpanControl``   spancontrolinputs.<row>.dat: spanwise control points of the camber-line curvature
                  and of the thickness (modified NACA parameters, or thickness-spline control points
                  in the older format). Readers: read_spanwise_NACA_input, read_spanwise_input.
``ControlInputs`` controlinputs.<row>.dat (oldest format): curvature and thickness control points
                  given per section. Reader: readcontrolinput.

Positional rules mirrored from source/readinput.f90:

* spancontrolinputs: five label lines (casename and row are informational), then the count line
  "<span points> <ncp_chord>", a header, and rows of span, u2..u<ncp_chord-1>, cur1..cur<ncp_chord>.
  Without ``cur1`` in the header (older format, not allowed with NACA thickness) the curvature
  columns are cur2..cur<ncp_chord>.
* NACA thickness block (thickness distribution 5): two labels, "<span points> <spline switch>", a
  header (``dy_dx_TE`` or ``dy_dx_norm`` in it adds a TE-derivative column), rows of span,
  LE_radius, u_max, t_max, t_TE [, TE derivative].
* Older thickness block (only read if the thickness multiplier or LE switch is on): two labels,
  "<span points> <columns per row>", a header, the rows.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..errors import InputFormatError
from ._records import Records, first_token, fortran_int, num

NACA_COLUMNS = ["span", "LE_radius", "u_max", "t_max", "t_TE"]
TE_DERIVATIVE_COLUMNS = ("dy_dx_TE", "dy_dx_norm")


@dataclass
class Table:
    """A table with named columns; ``data`` is (rows, len(columns)). The first column is the span."""
    columns: list[str]
    data: np.ndarray

    def column(self, name: str) -> np.ndarray:
        return self.data[:, self.columns.index(name)]

    def set_column(self, name: str, values) -> None:
        self.data[:, self.columns.index(name)] = values


@dataclass
class SpanControl:
    casename: str = "case"
    row: int = 1
    # Curvature block. Columns: span, u2..u<n> (chordwise locations), cur1..cur<m> (curvature values).
    # ``ncp_chord`` is the second number of the count line; the first is the number of rows.
    ncp_chord: int = 0
    curvature: Table = field(default_factory=lambda: Table([], np.zeros((0, 0))))
    # Thickness block. NACA format (thickness distribution 5): columns span, LE_radius, u_max, t_max,
    # t_TE and optionally the TE derivative; ``thickness_switch`` is the spline switch on the count
    # line. Older format: thickness-spline control points; ``thickness_switch`` is then the number of
    # chordwise control points. None when the file has no thickness block.
    thickness: Table | None = None
    thickness_switch: int = 0
    # Anything after the thickness block (e.g. LE control block of very old files), kept verbatim.
    trailing_text: str = ""
    labels: dict[str, str] = field(default_factory=dict)   # label/comment lines, keyed by block name

    @property
    def naca(self) -> bool:
        """True if the thickness block is in the modified-NACA format."""
        return self.thickness is not None and is_naca_columns(self.thickness.columns)


@dataclass
class ControlInputs:
    casename: str = "case"
    row: int = 1
    curvature: list[np.ndarray] = field(default_factory=list)   # per section (n, 2): u, curvature
    thickness: list[np.ndarray] = field(default_factory=list)   # per section (n, 2): u, thickness
    labels: dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------------------------
# Column names
# --------------------------------------------------------------------------------------------

def curvature_columns(ncp_chord: int, cur1: bool = True) -> list[str]:
    """span, u2..u<ncp_chord-1>, cur1..cur<ncp_chord> (cur2.. without cur1)."""
    return (["span"] + [f"u{k}" for k in range(2, ncp_chord)]
            + [f"cur{k}" for k in range(1 if cur1 else 2, ncp_chord + 1)])


def _ncp_chord_of(columns: list[str]) -> tuple[int, bool]:
    cur1 = "cur1" in columns
    n = len(columns)
    ncp = (n + 1) // 2 if cur1 else (n + 2) // 2
    if columns != curvature_columns(ncp, cur1):
        raise ValueError(f"curvature columns must be span, u2..u<n-1>, cur1..cur<n>; got {columns}")
    return ncp, cur1


def is_naca_columns(columns: list[str]) -> bool:
    return columns[:5] == NACA_COLUMNS and (len(columns) == 5 or
                                            (len(columns) == 6 and columns[5] in TE_DERIVATIVE_COLUMNS))


def _te_derivative_of(header: str) -> str | None:
    h = header.rstrip(" ")
    found = [w for w in TE_DERIVATIVE_COLUMNS if w in h]
    if len(found) > 1:
        raise InputFormatError(f"conflicting TE derivative columns {found} in header {header!r}")
    return found[0] if found else None


def _spline_thickness_columns(n: int) -> list[str]:
    return ["span"] + [f"thk{k}" for k in range(1, n)]


# --------------------------------------------------------------------------------------------
# spancontrolinputs
# --------------------------------------------------------------------------------------------

_SC_DEFAULTS: dict[str, list[str]] = {
    "casename_label": ["Casename:"],
    "row_label": ["Blade row#:"],
    "curvature_title": ["Span control points, Chord & curvature control points"],
    "thickness_title": ["", "Span control points, Chord & thickness control points"],
}


def parse_spancontrol(text: str, thickness_distribution: int | None = None, *,
                      thickness_multiplier: int = 0, le_spline: int = 0) -> SpanControl:
    """Parse spancontrolinputs.<row>.dat. The thickness block depends on the main file's switches.

    thickness_distribution 5: NACA thickness block (required). Otherwise the older thickness block is
    read only when ``thickness_multiplier`` or ``le_spline`` is set, as T-Blade3 does. None: guess
    (NACA block if one follows, else none). Text T-Blade3 does not read goes to ``trailing_text``.
    """
    r = Records(text, "spancontrolinputs file")
    aux = SpanControl()
    lab: dict[str, str] = {}

    def label(key: str, n: int = 1) -> list[str]:
        lines = r.lines_n(n, f"{n} label line(s) ({key})")
        lab[key] = "\n".join(lines)
        return lines

    label("casename_label")
    lab["casename_line"] = r.line("the casename line")
    aux.casename = first_token(lab["casename_line"]) or ""
    label("row_label")
    lab["row_line"] = r.line("the blade row line")
    tok = first_token(lab["row_line"])
    aux.row = (fortran_int(tok) if tok is not None else None) or 0
    label("curvature_title")
    n_span, ncp = r.values("ii", "number of span control points and ncp_chord (integers)")
    aux.ncp_chord = ncp
    header = label("curvature_header")[0]
    cur1 = "cur1" in header.rstrip(" ")
    if thickness_distribution == 5 and not cur1:
        raise r.error("a curvature header with cur1 (older format is not allowed with NACA thickness)")
    columns = curvature_columns(ncp, cur1)
    rows = [r.values("f" * len(columns), f"a curvature row of {len(columns)} numbers") for _ in range(n_span)]
    aux.curvature = Table(columns, np.array(rows, dtype=float).reshape(n_span, len(columns)))

    def read_naca() -> None:
        label("thickness_title", 2)
        n, aux.thickness_switch = r.values("ii", "number of span control points and the spline switch (integers)")
        te = _te_derivative_of(label("thickness_header")[0])
        cols = NACA_COLUMNS + ([te] if te else [])
        rows = [r.values("f" * len(cols), f"a NACA thickness row of {len(cols)} numbers") for _ in range(n)]
        aux.thickness = Table(cols, np.array(rows, dtype=float).reshape(n, len(cols)))

    if thickness_distribution == 5:
        read_naca()
    elif thickness_distribution is not None and (thickness_multiplier or le_spline):
        label("thickness_title", 2)
        n, nc = r.values("ii", "number of span control points and of chordwise columns (integers)")
        aux.thickness_switch = nc
        label("thickness_header")
        cols = _spline_thickness_columns(nc)
        rows = [r.values("f" * nc, f"a thickness row of {nc} numbers") for _ in range(n)]
        aux.thickness = Table(cols, np.array(rows, dtype=float).reshape(n, nc))
    elif thickness_distribution is None and cur1:
        pos, saved = r.pos, dict(lab)
        try:
            read_naca()
        except InputFormatError:
            r.pos, lab, aux.thickness, aux.thickness_switch = pos, saved, None, 0
    trailing = r.rest()
    if any(line.strip() for line in trailing):
        aux.trailing_text = "\n".join(trailing)
    aux.labels = lab
    return aux


def _label(labels: dict[str, str], defaults: dict[str, list[str]], key: str, ok=None,
           default: list[str] | None = None) -> list[str]:
    default = defaults[key] if default is None else default
    stored = labels.get(key)
    if stored is not None:
        lines = stored.split("\n")
        if len(lines) == len(default) and (ok is None or ok(lines)):
            return lines
    return list(default)


def _table_rows(data: np.ndarray) -> list[str]:
    return ["".join(f"{num(v):<22}" for v in row).rstrip() for row in data]


def _header(columns: list[str]) -> str:
    return "".join(f"{('Span' if c == 'span' else c):<22}" for c in columns).rstrip()


def format_spancontrol(aux: SpanControl) -> str:
    """Text of spancontrolinputs.<row>.dat; counts come from the tables."""
    labels = aux.labels or {}
    lab = lambda key, ok=None, default=None: _label(labels, _SC_DEFAULTS, key, ok, default)  # noqa: E731
    out: list[str] = []
    out += lab("casename_label")
    out += lab("casename_line", lambda ls: first_token(ls[0]) == aux.casename, [f" {aux.casename}"])
    out += lab("row_label")
    out += lab("row_line", lambda ls: first_token(ls[0]) == str(aux.row), [f"{aux.row}"])
    out += lab("curvature_title")
    cur = aux.curvature
    ncp, cur1 = _ncp_chord_of(list(cur.columns))
    out.append(f"{len(cur.data):9d}{ncp:4d}")
    ncols = len(cur.columns)
    out += lab("curvature_header",
               lambda ls: ("cur1" in ls[0].rstrip(" ")) == cur1 and len(ls[0].split()) == ncols,
               [_header(cur.columns)])
    out += _table_rows(cur.data)

    thk = aux.thickness
    if thk is not None:
        cols = list(thk.columns)
        out += lab("thickness_title")
        if is_naca_columns(cols):
            te = cols[5] if len(cols) == 6 else None
            out.append(f"{len(thk.data):9d}{aux.thickness_switch:4d}")

            def ok(ls: list[str]) -> bool:
                try:
                    return _te_derivative_of(ls[0]) == te and len(ls[0].split()) == len(cols)
                except InputFormatError:
                    return False
        else:
            if cols != _spline_thickness_columns(len(cols)):
                raise ValueError(f"thickness columns must be the NACA columns {NACA_COLUMNS} [+ TE derivative] "
                                 f"or span, thk1..thk<n-1>; got {cols}")
            out.append(f"{len(thk.data):9d}{len(cols):4d}")
            ok = None
        out += lab("thickness_header", ok, [_header(cols)])
        out += _table_rows(thk.data)
    if aux.trailing_text:
        out += aux.trailing_text.split("\n")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------------------------
# controlinputs
# --------------------------------------------------------------------------------------------

def _ci_default(key: str) -> list[str]:
    if key == "casename_label":
        return ["Casename:"]
    if key == "thickness_title":
        return ["", "Thickness control points (u, thickness multiplier) for each section"]
    if key.endswith("_header"):
        return ["   u                     curvature" if key.startswith("curvature") else
                "   u                     thickness"]
    if key.startswith("curvature"):
        return ["", f"Curvature control points for section {key[len('curvature'):]}:"]
    return ["", f"Thickness control points for section {key[len('thickness'):]}:"]


def parse_controlinputs(text: str, n_sections: int) -> ControlInputs:
    """Parse controlinputs.<row>.dat (per-section curvature and thickness control points).

    The blade row is not stored in this file; ``row`` keeps its default.
    """
    r = Records(text, "controlinputs file")
    aux = ControlInputs()
    lab: dict[str, str] = {}

    def label(key: str, n: int = 1) -> list[str]:
        lines = r.lines_n(n, f"{n} label line(s) ({key})")
        lab[key] = "\n".join(lines)
        return lines

    label("casename_label")
    lab["casename_line"] = r.line("the casename line")
    aux.casename = first_token(lab["casename_line"]) or ""
    for kind in ("curvature", "thickness"):
        if kind == "thickness":
            label("thickness_title", 2)
        tables = []
        for i in range(1, n_sections + 1):
            label(f"{kind}{i}", 2)
            n = r.values("i", f"the number of {kind} control points of section {i} (integer)")[0]
            label(f"{kind}{i}_header")
            rows = [r.values("ff", f"a {kind} control point of section {i}: u value") for _ in range(n)]
            tables.append(np.array(rows, dtype=float).reshape(n, 2))
        setattr(aux, kind, tables)
    trailing = r.rest()
    if any(line.strip() for line in trailing):
        lab["trailing"] = "\n".join(trailing)
    aux.labels = lab
    return aux


def format_controlinputs(aux: ControlInputs) -> str:
    """Text of controlinputs.<row>.dat; counts come from the arrays."""
    labels = aux.labels or {}
    if len(aux.curvature) != len(aux.thickness):
        raise ValueError(f"{len(aux.curvature)} curvature tables but {len(aux.thickness)} thickness tables")

    def lab(key: str, ok=None, default=None) -> list[str]:
        return _label(labels, {key: _ci_default(key)}, key, ok, default)

    out: list[str] = []
    out += lab("casename_label")
    out += lab("casename_line", lambda ls: first_token(ls[0]) == aux.casename, [f" {aux.casename}"])
    for kind in ("curvature", "thickness"):
        if kind == "thickness":
            out += lab("thickness_title")
        for i, t in enumerate(getattr(aux, kind), start=1):
            out += lab(f"{kind}{i}")
            out.append(f"{len(t):12d}")
            out += lab(f"{kind}{i}_header")
            out += _table_rows(np.asarray(t).reshape(len(t), 2))
    if labels.get("trailing"):
        out += labels["trailing"].split("\n")
    return "\n".join(out) + "\n"
