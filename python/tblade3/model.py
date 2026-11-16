"""Case, blade rows and named parameters.

A ``Case`` is a folder of T-Blade3 input files: one ``3dbgbinput.<row>.dat`` per blade row plus its
auxiliary file. Every number in those files has a name, e.g. ``row2.sweep[4]`` or
``row2.naca.t_max[3]`` (indices are 1-based, as in T-Blade3's files, its derivative file names and
ESP). Parameters can be read, set, flagged as design variables, and differentiated.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml

from . import paths
from .engine.base import Engine
from .errors import TBlade3Error
from .geometry import Geometry
from .io import maininput, spancontrol
from .io.maininput import MainInput
from .io.spancontrol import ControlInputs, SpanControl

SIDECAR = "case.tb3.yaml"
_MAIN_RE = re.compile(r"^3dbgbinput\.(.+)\.dat$")
_NAME_RE = re.compile(r"^(?:row(?P<row>[^.]+)\.)?(?P<local>.+)$")


# --------------------------------------------------------------------------------------------
# Parameters
# --------------------------------------------------------------------------------------------

@dataclass
class Parameter:
    """One named number of a blade row.

    name        local name within the row, e.g. "sweep[4]"; the full name adds "row<N>."
    group       where it belongs, for display, e.g. "Spanwise controls/Sweep"
    deriv       (group, field, cp) of T-Blade3's analytic derivative, or None
    udp         (argument name, 1-based index) of the matching udpTblade argument, or None
    integer     True for counts and switches that cannot vary continuously
    """
    name: str
    group: str
    _get: Callable[[], float] = field(repr=False)
    _set: Callable[[float], None] = field(repr=False)
    deriv: tuple[int, int, int] | None = None
    udp: tuple[str, int] | None = None
    integer: bool = False
    lower: float | None = None
    upper: float | None = None
    is_dv: bool = False

    @property
    def value(self) -> float:
        return self._get()

    @value.setter
    def value(self, v: float) -> None:
        self._set(int(round(v)) if self.integer else float(v))


def _array_params(prefix: str, group: str, array: Callable[[], np.ndarray], *,
                  deriv: Callable[[int], tuple[int, int, int] | None] = lambda i: None,
                  udp: str | None = None) -> list[Parameter]:
    """One parameter per element of a 1-D array; ``array`` is looked up at access time."""
    out = []
    for i in range(len(array())):
        def get(i=i):
            return float(array()[i])

        def set_(v, i=i):
            array()[i] = v

        out.append(Parameter(f"{prefix}[{i + 1}]", group, get, set_, deriv=deriv(i + 1),
                             udp=(udp, i + 1) if udp else None))
    return out


def _attr_param(obj_get: Callable[[], object], attr: str, name: str, group: str, **kw) -> Parameter:
    return Parameter(name, group, lambda: getattr(obj_get(), attr),
                     lambda v: setattr(obj_get(), attr, v), **kw)


def _control_table_params(table_get, prefix: str, column: str, group: str, deriv_group: int | None,
                          udp_value: str | None, udp_span: str | None) -> list[Parameter]:
    """Value and span-location parameters of a spanwise control table with one value column.

    T-Blade3 numbers the derivative fields 1 = span location, 2 = value.
    """
    params = _array_params(prefix, group, lambda: table_get().values[column],
                           deriv=(lambda i: (deriv_group, 2, i)) if deriv_group else (lambda i: None),
                           udp=udp_value)
    params += _array_params(f"{prefix}.span", group, lambda: table_get().span,
                            deriv=(lambda i: (deriv_group, 1, i)) if deriv_group else (lambda i: None),
                            udp=udp_span)
    return params


def _safe(column: str) -> str:
    """Column label -> parameter name piece: 'tm/c' -> 'tm_c', 'LE_radius' -> 'le_radius'."""
    return re.sub(r"[^0-9a-z]+", "_", column.lower()).strip("_")


# --------------------------------------------------------------------------------------------
# Blade row
# --------------------------------------------------------------------------------------------

class BladeRow:
    """One blade row: its main input, its auxiliary input, and the geometry built from them."""

    def __init__(self, main: MainInput, aux: SpanControl | ControlInputs | None = None,
                 row_id: str | None = None, engine: Engine | str | None = None):
        self.main = main
        self.aux = aux
        self.row_id = str(row_id if row_id is not None else main.row)
        self._engine_spec = engine
        self._engine: Engine | None = None
        self._params: dict[str, Parameter] | None = None
        self._dv_state: dict[str, tuple[float | None, float | None]] = {}
        self.geometry: Geometry | None = None
        self._geometry_key: str | None = None
        self._fd_cache: dict[str, np.ndarray] = {}
        self.fd_rel_step = 1e-6

    # -- files -----------------------------------------------------------------------------
    @property
    def main_name(self) -> str:
        return f"3dbgbinput.{self.row_id}.dat"

    @property
    def aux_name(self) -> str | None:
        if isinstance(self.aux, SpanControl):
            return f"spancontrolinputs.{self.row_id}.dat"
        if isinstance(self.aux, ControlInputs):
            return f"controlinputs.{self.row_id}.dat"
        return None

    def files(self) -> dict[str, str]:
        """Input file texts for the current parameter values."""
        out = {self.main_name: maininput.format(self.main)}
        if isinstance(self.aux, SpanControl):
            out[self.aux_name] = spancontrol.format_spancontrol(self.aux)
        elif isinstance(self.aux, ControlInputs):
            out[self.aux_name] = spancontrol.format_controlinputs(self.aux)
        return out

    @classmethod
    def from_texts(cls, main_text: str, aux_text: str | None = None, aux_kind: str = "spancontrol",
                   row_id: str | None = None, engine: Engine | str | None = None) -> BladeRow:
        main = maininput.parse(main_text)
        aux = None
        if aux_text is not None:
            if aux_kind == "controlinputs":
                aux = spancontrol.parse_controlinputs(aux_text, main.n_streamlines)
            else:
                aux = spancontrol.parse_spancontrol(aux_text, main.thickness_distribution,
                                                    thickness_multiplier=main.thickness_multiplier,
                                                    le_spline=main.le_spline)
        return cls(main, aux, row_id=row_id, engine=engine)

    # -- parameters ------------------------------------------------------------------------
    def invalidate_parameters(self) -> None:
        """Call after a structural change (rows added to or removed from a table)."""
        if self._params is not None:
            self._dv_state = {p.name: (p.lower, p.upper) for p in self._params.values() if p.is_dv}
        self._params = None

    @property
    def parameters(self) -> dict[str, Parameter]:
        if self._params is None:
            self._params = {p.name: p for p in self._build_parameters()}
            for name, (lo, hi) in self._dv_state.items():
                p = self._params.get(name)
                if p is not None:
                    p.is_dv, p.lower, p.upper = True, lo, hi
        return self._params

    def _build_parameters(self) -> list[Parameter]:
        m = lambda: self.main            # noqa: E731  (late binding: self.main may be replaced)
        P: list[Parameter] = []

        g = "Row setup"
        P.append(_attr_param(m, "n_blades", "n_blades", g, integer=True))
        P.append(_attr_param(m, "scale_factor", "scale_factor", g))
        P.append(_attr_param(m, "clustering_parameter", "clustering_parameter", g))

        g = "Flow path"
        P.append(_attr_param(m, "hub_offset", "hub_offset", g, udp=("offsets", 1)))
        P.append(_attr_param(m, "tip_offset", "tip_offset", g, udp=("offsets", 2)))
        if self.main.hub_inflation_offset is not None:
            P.append(_attr_param(m, "hub_inflation_offset", "hub_inflation_offset", g, udp=("hub_inf_offset", 1)))
        if self.main.tip_inflation_offset is not None:
            P.append(_attr_param(m, "tip_inflation_offset", "tip_inflation_offset", g, udp=("tip_inf_offset", 1)))
        for j, col in enumerate(("x_le", "r_le", "x_te", "r_te")):
            P += _array_params(f"le_te.{col}", f"{g}/LE and TE curves", lambda j=j: m().le_te[:, j])
        for k in range(len(self.main.streamlines)):
            P += _array_params(f"streamline{k + 1}.x", f"{g}/Streamlines", lambda k=k: m().streamlines[k][:, 0])
            P += _array_params(f"streamline{k + 1}.r", f"{g}/Streamlines", lambda k=k: m().streamlines[k][:, 1])

        g = "Sections"
        for col in self.main.sections:
            P += _array_params(f"sec.{col}", g, lambda col=col: m().sections[col])

        g = "Stacking"
        for col in ("stk_u", "stk_v", "umxthk", "lethk", "tethk"):
            P += _array_params(col, g, lambda col=col: getattr(m(), col))

        g = "Spanwise controls"
        for attr, prefix, title, dgroup, udp in (
                ("sweep", "sweep", "Sweep", 1, "span_del_m"),
                ("lean", "lean", "Lean", 2, "span_del_theta"),
                ("in_beta", "in_beta", "Inlet angle", 3, "span_in_beta"),
                ("out_beta", "out_beta", "Exit angle", 4, "span_out_beta"),
                ("chord_multiplier", "chord_multiplier", "Chord multiplier", 5, "span_chord")):
            table = getattr(self.main, attr)
            if len(table) and table.values:
                column = next(iter(table.values))
                P += _control_table_params(lambda attr=attr: getattr(m(), attr), prefix, column,
                                           f"{g}/{title}", dgroup, udp, f"{udp}_ctrl")
        thk = self.main.thickness
        if len(thk):
            udps = {"tm_c": "span_thk_c", "u_max": "span_u_max"}
            for column in thk.values:
                P += _array_params(_safe(column), f"{g}/Thickness", lambda c=column: m().thickness.values[c],
                                   udp=udps.get(_safe(column)))
            P += _array_params("thickness.span", f"{g}/Thickness", lambda: m().thickness.span, udp="span_thk_c_ctrl")

        if isinstance(self.aux, SpanControl):
            P += self._spancontrol_parameters()
        elif isinstance(self.aux, ControlInputs):
            a = lambda: self.aux         # noqa: E731
            for kind, title in (("curvature", "Camber"), ("thickness", "Thickness")):
                for s in range(len(getattr(self.aux, kind))):
                    for j, col in enumerate(("u", "v")):
                        P += _array_params(f"{kind}{s + 1}.{col}", f"{title}/Section control points",
                                           lambda kind=kind, s=s, j=j: getattr(a(), kind)[s][:, j])
        return P

    def _spancontrol_parameters(self) -> list[Parameter]:
        a = lambda: self.aux             # noqa: E731
        P: list[Parameter] = []
        cur = self.aux.curvature
        # Derivative field = position of the column after the span column: u2.. first, then cur1..
        for j, col in enumerate(cur.columns):
            if j == 0:
                P += _array_params("curvature.span", "Camber", lambda: a().curvature.data[:, 0], udp="span_curv_ctrl")
                continue
            name = _safe(col)
            is_cur = name.startswith("cur")
            P += _array_params(name, "Camber/Curvature" if is_cur else "Camber/Chordwise locations",
                               lambda j=j: a().curvature.data[:, j],
                               deriv=(lambda i, j=j: (6, j, i)) if is_cur else (lambda i: None), udp=name)
        thk = self.aux.thickness
        if thk is not None:
            naca = self.main.thickness_distribution == 5
            for j, col in enumerate(thk.columns):
                if j == 0:
                    P += _array_params("naca.span" if naca else "thk.span", "Thickness",
                                       lambda: a().thickness.data[:, 0], udp="span_thk_ctrl" if naca else None)
                    continue
                name = _safe(col)
                if naca:
                    P += _array_params(f"naca.{name}", "Thickness/Modified NACA", lambda j=j: a().thickness.data[:, j],
                                       deriv=(lambda i, j=j: (7, j, i)) if j <= 4 else (lambda i: None),
                                       udp=f"naca_{name}" if j <= 4 else None)
                else:
                    P += _array_params(f"thk.{name}", "Thickness/Spline control points",
                                       lambda j=j: a().thickness.data[:, j])
        return P

    def get(self, name: str) -> float:
        return self._param(name).value

    def set(self, name: str, value: float) -> None:
        self._param(name).value = value

    def _param(self, name: str) -> Parameter:
        try:
            return self.parameters[name]
        except KeyError:
            raise KeyError(f"row {self.row_id} has no parameter {name!r}") from None

    # -- building --------------------------------------------------------------------------
    @property
    def engine(self) -> Engine:
        if self._engine is None:
            self._engine = make_engine(self._engine_spec)
        return self._engine

    def build(self, derivatives: bool = True) -> Geometry:
        """Run T-Blade3 with the current values. Raises TBlade3Error on failure."""
        files = self.files()
        cached = self.cached_geometry(files, derivatives)
        if cached is not None:
            return cached
        geo = self.engine.run(files, self.main_name, derivatives=derivatives)
        self.adopt(geo, files)
        return geo

    @staticmethod
    def _key(files: dict[str, str]) -> str:
        return repr(sorted(files.items()))

    def cached_geometry(self, files: dict[str, str], derivatives: bool = True) -> Geometry | None:
        """The stored geometry if it was built from exactly these files, else None."""
        geo = self.geometry
        if geo is not None and self._key(files) == self._geometry_key and (geo.derivatives is not None or not derivatives):
            return geo
        return None

    def adopt(self, geo: Geometry, files: dict[str, str]) -> None:
        """Store a geometry that was built from ``files`` (e.g. by a background thread)."""
        key = self._key(files)
        if key != self._geometry_key:
            self._fd_cache.clear()
        self.geometry, self._geometry_key = geo, key

    @property
    def is_current(self) -> bool:
        """True if the stored geometry matches the current parameter values."""
        return self.geometry is not None and self._key(self.files()) == self._geometry_key

    def derivative_method(self, name: str) -> str:
        """'analytic' if T-Blade3 provides d(sections)/d(parameter), else 'fd' (finite difference)."""
        p = self._param(name)
        geo = self.geometry
        if p.deriv is not None and (geo is None or geo.derivatives is None or p.deriv in geo.derivatives.xyz):
            return "analytic"
        return "fd"

    def dxyz(self, name: str, method: str | None = None) -> np.ndarray:
        """d(section points)/d(parameter), shape (nsec, npt, 3), mm per unit of the parameter.

        ``method`` forces "analytic" or "fd"; by default analytic is used where T-Blade3 has it.
        """
        p = self._param(name)
        geo = self.build(derivatives=True)
        if method is None:
            method = "analytic" if (p.deriv is not None and p.deriv in geo.derivatives.xyz) else "fd"
        if method == "analytic":
            if p.deriv is None or p.deriv not in geo.derivatives.xyz:
                raise TBlade3Error(f"T-Blade3 has no analytic derivative for {name!r}")
            return geo.derivatives.xyz[p.deriv]
        if name not in self._fd_cache:
            self._fd_cache[name] = self._finite_difference(p)
        return self._fd_cache[name]

    def fd_files(self, name: str) -> tuple[dict[str, str], dict[str, str], float]:
        """Input files with the parameter stepped up and down, and the step h (for a central difference).

        The parameter is restored afterwards.
        """
        p = self._param(name)
        if p.integer:
            raise TBlade3Error(f"{p.name!r} is an integer and cannot be differentiated")
        x0 = p.value
        h = self.fd_rel_step * max(abs(x0), 1.0)
        try:
            p.value = x0 + h
            plus = self.files()
            p.value = x0 - h
            minus = self.files()
        finally:
            p.value = x0
        return plus, minus, h

    def _finite_difference(self, p: Parameter) -> np.ndarray:
        """Central difference with two extra runs."""
        plus, minus, h = self.fd_files(p.name)
        a = self.engine.run(plus, self.main_name, derivatives=False).sections
        b = self.engine.run(minus, self.main_name, derivatives=False).sections
        return (a - b) / (2.0 * h)

    def store_fd(self, name: str, dxyz: np.ndarray) -> None:
        """Keep a finite-difference derivative computed elsewhere (valid for the current geometry)."""
        self._fd_cache[name] = dxyz

    def close(self) -> None:
        if self._engine is not None:
            self._engine.close()
            self._engine = None


def make_engine(spec: Engine | str | None = None) -> Engine:
    """'library', 'executable', an Engine, or None (library if it is built, else executable)."""
    if isinstance(spec, Engine):
        return spec
    if spec is None:
        try:
            paths.library()
            spec = "library"
        except FileNotFoundError:
            spec = "executable"
    if spec == "library":
        from .engine.library import LibraryEngine
        return LibraryEngine()
    if spec == "executable":
        from .engine.executable import ExecutableEngine
        return ExecutableEngine()
    raise ValueError(f"unknown engine {spec!r}")


# --------------------------------------------------------------------------------------------
# Case
# --------------------------------------------------------------------------------------------

class DesignVariables:
    """The parameters flagged as design variables, in a fixed order, as one vector."""

    def __init__(self, case: Case):
        self._case = case

    @property
    def names(self) -> list[str]:
        return [f"row{rid}.{p.name}" for rid, row in self._case.rows.items()
                for p in row.parameters.values() if p.is_dv]

    @property
    def values(self) -> np.ndarray:
        return np.array([self._case.get(n) for n in self.names])

    @values.setter
    def values(self, x: Iterable[float]) -> None:
        names = self.names
        x = np.asarray(list(x), dtype=float)
        if x.shape != (len(names),):
            raise ValueError(f"expected {len(names)} design-variable values, got {x.shape}")
        for n, v in zip(names, x):
            self._case.set(n, v)

    @property
    def bounds(self) -> list[tuple[float | None, float | None]]:
        return [(p.lower, p.upper) for p in map(self._case.parameter, self.names)]

    def add(self, name: str, lower: float | None = None, upper: float | None = None) -> None:
        p = self._case.parameter(name)
        if p.integer:
            raise ValueError(f"{name!r} is an integer and cannot be a design variable")
        p.is_dv, p.lower, p.upper = True, lower, upper

    def remove(self, name: str) -> None:
        p = self._case.parameter(name)
        p.is_dv, p.lower, p.upper = False, None, None

    def __len__(self) -> int:
        return len(self.names)


class Case:
    """All blade rows of one case folder."""

    def __init__(self, rows: dict[str, BladeRow] | None = None, folder: Path | None = None):
        self.rows: dict[str, BladeRow] = rows or {}
        self.folder = folder
        self.dv = DesignVariables(self)

    # -- loading and saving ----------------------------------------------------------------
    @classmethod
    def load(cls, folder: str | Path, engine: Engine | str | None = None) -> Case:
        """Load every 3dbgbinput.<row>.dat in ``folder`` (or the one file given) and its aux file."""
        folder = Path(folder)
        if folder.is_file():
            mains, folder = [folder], folder.parent
        else:
            mains = sorted(p for p in folder.iterdir() if _MAIN_RE.match(p.name))
        if not mains:
            raise FileNotFoundError(f"no 3dbgbinput.<row>.dat in {folder}")
        rows: dict[str, BladeRow] = {}
        for path in mains:
            rid = _MAIN_RE.match(path.name).group(1)
            aux_text, kind = None, "spancontrol"
            for kind_, name in (("spancontrol", f"spancontrolinputs.{rid}.dat"),
                                ("controlinputs", f"controlinputs.{rid}.dat")):
                if (folder / name).is_file():
                    aux_text, kind = (folder / name).read_text(errors="replace"), kind_
                    break
            rows[rid] = BladeRow.from_texts(path.read_text(errors="replace"), aux_text, kind, row_id=rid,
                                            engine=engine)
        ordered = dict(sorted(rows.items(), key=lambda kv: (not kv[0].isdigit(), int(kv[0]) if kv[0].isdigit() else 0, kv[0])))
        case = cls(ordered, folder)
        case._load_sidecar(folder / SIDECAR)
        return case

    def save(self, folder: str | Path | None = None) -> Path:
        """Write the input files of all rows and the design-variable sidecar."""
        folder = Path(folder) if folder is not None else self.folder
        if folder is None:
            raise ValueError("no folder given")
        folder.mkdir(parents=True, exist_ok=True)
        for row in self.rows.values():
            for name, text in row.files().items():
                (folder / name).write_text(text)
        dvs = [{"name": n, "lower": lo, "upper": hi} for n, (lo, hi) in zip(self.dv.names, self.dv.bounds)]
        sidecar = folder / SIDECAR
        if dvs:
            sidecar.write_text(yaml.safe_dump({"design_variables": dvs}, sort_keys=False))
        elif sidecar.exists():
            sidecar.unlink()
        self.folder = folder
        return folder

    def _load_sidecar(self, path: Path) -> None:
        if not path.is_file():
            return
        data = yaml.safe_load(path.read_text()) or {}
        for dv in data.get("design_variables", []):
            try:
                self.dv.add(dv["name"], dv.get("lower"), dv.get("upper"))
            except KeyError:
                pass                     # parameter no longer exists (e.g. a table got shorter)

    # -- parameters ------------------------------------------------------------------------
    def _split(self, name: str) -> tuple[BladeRow, str]:
        m = _NAME_RE.match(name)
        rid, local = m.group("row"), m.group("local")
        if rid is None:
            if len(self.rows) != 1:
                raise KeyError(f"{name!r}: give the row, e.g. 'row{next(iter(self.rows))}.{local}'")
            rid = next(iter(self.rows))
        if rid not in self.rows:
            raise KeyError(f"{name!r}: no row {rid!r} (rows: {', '.join(self.rows)})")
        return self.rows[rid], local

    def parameter(self, name: str) -> Parameter:
        row, local = self._split(name)
        return row._param(local)

    def get(self, name: str) -> float:
        return self.parameter(name).value

    def set(self, name: str, value: float) -> None:
        self.parameter(name).value = value

    def parameters(self) -> dict[str, Parameter]:
        """All parameters of all rows, by full name."""
        return {f"row{rid}.{p.name}": p for rid, row in self.rows.items() for p in row.parameters.values()}

    # -- building and derivatives ----------------------------------------------------------
    def build(self, derivatives: bool = True, parallel: bool = True) -> dict[str, Geometry]:
        """Build all rows; each row has its own engine, so they run side by side."""
        rows = list(self.rows.values())
        if parallel and len(rows) > 1:
            with ThreadPoolExecutor(len(rows)) as pool:
                geos = list(pool.map(lambda r: r.build(derivatives), rows))
        else:
            geos = [r.build(derivatives) for r in rows]
        return dict(zip(self.rows, geos))

    def dxyz(self, name: str, method: str | None = None) -> np.ndarray:
        row, local = self._split(name)
        return row.dxyz(local, method)

    def jacobian(self, names: Iterable[str] | None = None) -> dict[str, np.ndarray]:
        """d(section points)/d(design variables) per row: {row: (nsec, npt, 3, n_dv)}.

        A design variable of another row contributes zeros.
        """
        names = list(names) if names is not None else self.dv.names
        geos = self.build(derivatives=True)
        out = {rid: np.zeros((*geo.sections.shape, len(names))) for rid, geo in geos.items()}
        for k, name in enumerate(names):
            row, local = self._split(name)
            out[row.row_id][..., k] = row.dxyz(local)
        return out

    def close(self) -> None:
        for row in self.rows.values():
            row.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
