"""Exact B-Rep of one blade row from a T-Blade3 run: blade, hub wedge, structural solid, fluid passage.

All faces, edges and vertices are built directly (no Boolean operations), so the bodies share their
interfaces exactly and every edge is a curve we know: an iso-curve of one of our B-spline surfaces or a
circle. OpenCASCADE's surface/surface intersections of these dense B-splines were up to 0.07 mm off, which
is why the bodies are not cut out of each other.

1. **Flow path.** ``hub.<cn>.sldcrv`` and ``casing.<cn>.sldcrv`` are (x, r) curves, interpolated by cubic
   B-splines (as udpTblade's ``tbStreamlineCap``) and revolved about x. The same revolved surface bounds
   the hub wedge, the passage and the blade root.
2. **Blade.** A bicubic surface through all section points (udpTblade: ``EG_approximate``, natural ends),
   split at the LE into suction and pressure faces. The hub (tip) section is first moved radially onto the
   hub (casing) streamline when it lies within ``cap_tol`` of it (T-Blade3 leaves it up to 0.016 mm off on
   the TCT rotor), so the root edge lies on the hub surface. A tip off the casing (tip gap) is closed by
   the revolved tip meanline.
3. **Periodic sheet.** A bicubic surface through rows at common axial stations from the inlet to the
   outlet plane: the bore, rows between bore and hub at the hub meanline's angle, the hub, the meanlines
   in between, the casing. Each meanline is resampled at the stations as span fraction and angle against x
   (T-Blade3's straight 15 % chord extensions, continued linearly). Because every row has a point at each
   station, the inlet and outlet edges are iso-curves lying exactly in their planes, and the hub, casing
   and bore edges are iso-curves lying on those surfaces. The low side is the sheet rotated by -pi/N, the
   high side by +pi/N.
4. **Bodies.** blade; hub wedge (bore to hub); passage (hub to casing, minus the blade); structural solid
   (wedge + blade, without the root face); assembly (the three, sharing faces).

Coordinates as T-Blade3: (x, r sin(theta), r cos(theta)), mm.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from OCP.BRep import BRep_Builder
from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeVertex,
                                BRepBuilderAPI_MakeWire)
from OCP.BRepLib import BRepLib
from OCP.Geom import Geom_Circle, Geom_CylindricalSurface, Geom_Plane, Geom_SurfaceOfRevolution
from OCP.Geom2d import Geom2d_Line
from OCP.gp import gp_Ax2, gp_Ax3, gp_Dir, gp_Dir2d, gp_Pnt, gp_Pnt2d
from OCP.ShapeFix import ShapeFix_Face
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS, TopoDS_Compound, TopoDS_Shell, TopoDS_Solid
from scipy.interpolate import CubicSpline

from ..geometry import Geometry
from . import nurbs, occ

# Face roles
BLADE_SUCTION = "blade_suction"
BLADE_PRESSURE = "blade_pressure"
BLADE_ROOT = "blade_root"          # blade/hub interface (internal in the structural solid)
BLADE_TIP = "blade_tip"
HUB = "hub"
CASING = "casing"
BORE = "bore"
PERIODIC_LO = "periodic_lo"        # passage part of the low periodic side
PERIODIC_HI = "periodic_hi"
WEDGE_PERIODIC_LO = "wedge_periodic_lo"
WEDGE_PERIODIC_HI = "wedge_periodic_hi"
INLET = "inlet"
OUTLET = "outlet"
WEDGE_INLET = "wedge_inlet"
WEDGE_OUTLET = "wedge_outlet"

BODY_NAMES = ("blade", "hub_wedge", "passage", "solid", "assembly")


@dataclass
class BuildOptions:
    bore_radius: float | None = None   # default: 0.25 x smallest hub radius between inlet and outlet
    x_inlet: float | None = None       # default: most upstream point of the extended meanlines
    x_outlet: float | None = None      # default: most downstream point of the extended meanlines
    cap_tol: float = 1e-3              # relative (to the largest radius) distance for moving end sections
    stations: int = 121                # axial stations of the periodic sheet


# ------------------------------------------------------------------------------------- streamlines

class Streamline:
    """A flow-path or section streamline as an (x, r) cubic B-spline, x increasing along it."""

    def __init__(self, xr: np.ndarray):
        xr = np.asarray(xr, float)
        if xr[-1, 0] < xr[0, 0]:
            xr = xr[::-1]
        self.points = xr
        self.curve, self.interp = nurbs.interpolate_curve(xr, "natural")
        t0, t1 = self.curve.range
        self._t = np.linspace(t0, t1, 4001)
        self._x = self.curve(self._t)[:, 0]

    @classmethod
    def from_xyz(cls, pts: np.ndarray) -> Streamline:
        """From 3-D points (x, r sin t, r cos t) or a .sldcrv (x, 0, r)."""
        return cls(np.column_stack([pts[:, 0], np.hypot(pts[:, 1], pts[:, 2])]))

    def t_at(self, x) -> np.ndarray:
        x = np.atleast_1d(np.asarray(x, float))
        t = np.interp(x, self._x, self._t)
        for _ in range(10):
            d0 = self.curve(t)[:, 0] - x
            d1 = self.curve(t, deriv=1)[:, 0]
            t = t - d0 / d1
        return t

    def radius(self, x) -> tuple[np.ndarray, np.ndarray]:
        """r(x) and dr/dx."""
        t = self.t_at(x)
        p = self.curve(t)
        d = self.curve(t, deriv=1)
        return p[:, 1], d[:, 1] / d[:, 0]

    @property
    def xrange(self) -> tuple[float, float]:
        return float(self.points[0, 0]), float(self.points[-1, 0])

    def surface(self, seam: float) -> Geom_SurfaceOfRevolution:
        """The streamline revolved about +x; its generatrix lies at theta = seam.

        Parameters: u = seam - theta (a right-handed angle about +x), v = the B-spline's parameter.
        """
        cps = self.curve.cps
        c3 = nurbs.Curve(self.curve.knots,
                         np.column_stack([cps[:, 0], cps[:, 1] * math.sin(seam), cps[:, 1] * math.cos(seam)]))
        return Geom_SurfaceOfRevolution(occ.bspline_curve(c3), occ.X_AXIS)

    def uv(self, pts: np.ndarray, seam: float) -> np.ndarray:
        """(u, v) on ``surface(seam)`` of points lying on it."""
        x, _, t = cyl(pts)
        return np.column_stack([_wrap(seam - t), self.t_at(x)])


def cyl(p: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    p = np.asarray(p, float)
    return p[..., 0], np.hypot(p[..., 1], p[..., 2]), np.arctan2(p[..., 1], p[..., 2])


def cart(x, r, t) -> np.ndarray:
    return np.stack(np.broadcast_arrays(x, r * np.sin(t), r * np.cos(t)), axis=-1)


def _wrap(a: np.ndarray) -> np.ndarray:
    """Angles into [0, 2 pi)."""
    return np.mod(a, 2 * math.pi)


@dataclass
class Projection:
    """Radial move of one row of points onto a streamline (and its derivative)."""
    streamline: Streamline
    index: int                 # section index
    distance: float            # largest radial move

    def apply(self, pts: np.ndarray) -> np.ndarray:
        x, _, t = cyl(pts)
        r, _ = self.streamline.radius(x)
        return cart(x, r, t)

    def derivative(self, pts: np.ndarray, dpts: np.ndarray) -> np.ndarray:
        """d(apply(pts)) for a change dpts of the unprojected points pts."""
        x, r0, t = cyl(pts)
        r, drdx = self.streamline.radius(x)
        dx = dpts[..., 0]
        dt = (pts[..., 2] * dpts[..., 1] - pts[..., 1] * dpts[..., 2]) / r0 ** 2
        dr = drdx * dx
        return np.stack([dx, dr * np.sin(t) + r * np.cos(t) * dt, dr * np.cos(t) - r * np.sin(t) * dt],
                        axis=-1)


# ------------------------------------------------------------------------------------------ surfaces

@dataclass
class BladeSurface:
    raw: np.ndarray                  # (npt, nsec, 3) T-Blade3 section points (u along the section)
    grid: np.ndarray                 # the same after moving the end sections onto the flow path
    surface: nurbs.Surface
    interp: nurbs.SurfaceInterpolant
    u_le: float
    projections: list[Projection]
    tip_on_casing: bool


@dataclass
class SheetSurface:
    """The periodic sheet (before its rotation by -pi/N or +pi/N)."""
    stations: np.ndarray             # (nx,) axial stations
    grid: np.ndarray                 # (nx, nrows, 3)
    surface: nurbs.Surface
    interp: nurbs.SurfaceInterpolant
    rows: list[tuple[str, int, float]]   # per row: kind ("bore", "sub", "hub", "meanline", "casing"),
                                         # meanline index used for theta, and the radius fraction (sub)
    v_bore: float
    v_hub: float
    v_casing: float
    half_pitch: float


def nblades_of(geo: Geometry) -> int:
    pitch = geo.section_table.get("pitch")
    if pitch is None or not len(pitch):
        raise ValueError("no pitch in blade_section_data: cannot find the number of blades")
    return int(round(2 * math.pi / float(pitch[0])))


def blade_surface(geo: Geometry, hub: Streamline, casing: Streamline, opts: BuildOptions,
                  notes: list[str]) -> BladeSurface:
    raw = np.transpose(geo.sections, (1, 0, 2)).copy()      # (npt, nsec, 3)
    grid = raw.copy()
    rmax = float(np.hypot(raw[..., 1], raw[..., 2]).max())
    projections = []
    tip_on_casing = True
    for j, fs, name in ((0, hub, "hub"), (raw.shape[1] - 1, casing, "casing")):
        x, r, _ = cyl(raw[:, j])
        rs, _ = fs.radius(x)
        dist = float(np.abs(r - rs).max())
        end = "root" if j == 0 else "tip"
        if dist <= opts.cap_tol * rmax:
            pr = Projection(fs, j, dist)
            grid[:, j] = pr.apply(raw[:, j])
            projections.append(pr)
            notes.append(f"blade {end} section moved onto the {name} streamline (largest move {dist:.3g})")
        elif j == 0:
            raise NotImplementedError(
                f"the hub section is {dist:.3g} off the hub streamline (hub offset or inflation): a blade "
                "root off the hub is not supported yet")
        else:
            tip_on_casing = False
            notes.append(f"blade tip is {dist:.3g} off the casing (tip gap): closed by its own streamsurface")
    srf, si = nurbs.interpolate_surface(grid, "natural", "natural")
    npt = grid.shape[0]
    return BladeSurface(raw, grid, srf, si, float(si.u.params[npt // 2]), projections, tip_on_casing)


def _resample(x: np.ndarray, y: np.ndarray, xs: np.ndarray) -> np.ndarray:
    """Natural cubic spline y(x) at xs, continued linearly (end slope) outside the data."""
    cs = CubicSpline(x, y, bc_type="natural")
    out = cs(xs)
    lo, hi = xs < x[0], xs > x[-1]
    out[lo] = y[0] + cs(x[0], 1) * (xs[lo] - x[0])
    out[hi] = y[-1] + cs(x[-1], 1) * (xs[hi] - x[-1])
    return out


def meanline_rows(geo: Geometry, hub: Streamline, casing: Streamline, xs: np.ndarray):
    """Span fraction s_j(xs) and angle theta_j(xs) of every meanline."""
    rh, rc = hub.radius(xs)[0], casing.radius(xs)[0]
    s_rows, t_rows = [], []
    for ml in geo.meanlines:
        x, r, t = cyl(ml)
        t = np.unwrap(t)
        sh, sc = hub.radius(x)[0], casing.radius(x)[0]
        s = (r - sh) / (sc - sh)
        s_rows.append(_resample(x, s, xs))
        t_rows.append(_resample(x, t, xs))
    return np.array(s_rows), np.array(t_rows), rh, rc


def sheet_surface(geo: Geometry, hub: Streamline, casing: Streamline, nb: int, x_in: float, x_out: float,
                  bore: float, opts: BuildOptions) -> SheetSurface:
    xs = np.linspace(x_in, x_out, opts.stations)
    s, t, rh, rc = meanline_rows(geo, hub, casing, xs)
    nsec = s.shape[0]
    tol = opts.cap_tol * float(rc.max()) / float((rc - rh).mean())    # as a span fraction
    inner = [j for j in range(nsec) if s[j].min() > tol and s[j].max() < 1 - tol]
    ds = float(np.median(np.diff(s.mean(axis=1))))                     # spanwise spacing (fraction)
    dr = ds * float((rc - rh).mean())
    k = max(2, math.ceil(float((rh - bore).mean()) / dr))
    rows: list[tuple[str, int, float]] = [("bore", 0, 0.0)]
    pts = [cart(xs, np.full_like(xs, bore), t[0])]
    for i in range(1, k):
        f = i / k
        rows.append(("sub", 0, f))
        pts.append(cart(xs, bore + f * (rh - bore), t[0]))
    rows.append(("hub", 0, 0.0))
    pts.append(cart(xs, rh, t[0]))
    for j in inner:
        rows.append(("meanline", j, 0.0))
        pts.append(cart(xs, rh + s[j] * (rc - rh), t[j]))
    rows.append(("casing", nsec - 1, 0.0))
    pts.append(cart(xs, rc, t[-1]))
    grid = np.stack(pts, axis=1)
    r = np.hypot(grid[..., 1], grid[..., 2])
    if np.any(np.diff(r, axis=1) <= 0):
        raise ValueError("periodic sheet rows cross (meanlines out of radial order)")
    srf, si = nurbs.interpolate_surface(grid, "natural", "natural")
    pv = si.v.params
    return SheetSurface(xs, grid, srf, si, rows, float(pv[0]), float(pv[k]), float(pv[-1]), math.pi / nb)


def rotated(srf: nurbs.Surface, delta: float) -> nurbs.Surface:
    rot = occ.rotation_matrix(delta)
    return nurbs.Surface(srf.uknots, srf.vknots, srf.cps @ rot.T, srf.weights, srf.udegree, srf.vdegree)


# ------------------------------------------------------------------------------------- topology kit

class _Kit:
    """Vertices, edges with p-curves, faces."""

    TOL = 1e-7

    def __init__(self):
        self.builder = BRep_Builder()

    def vertex(self, p) -> object:
        return BRepBuilderAPI_MakeVertex(gp_Pnt(*map(float, p))).Vertex()

    def edge(self, curve, v1, v2, t1: float, t2: float):
        mk = BRepBuilderAPI_MakeEdge(curve, v1, v2, float(t1), float(t2))
        if not mk.IsDone():
            raise RuntimeError(f"edge construction failed ({mk.Error()})")
        return mk.Edge()

    def pcurve(self, edge, curve2d, surface) -> None:
        self.builder.UpdateEdge(edge, curve2d, surface, TopLoc_Location(), self.TOL)

    @staticmethod
    def line(p, d):
        return Geom2d_Line(gp_Pnt2d(float(p[0]), float(p[1])), gp_Dir2d(float(d[0]), float(d[1])))

    @staticmethod
    def sampled(params: np.ndarray, uv: np.ndarray):
        """2-D B-spline through (u, v) at the 3-D curve's parameters (so it is same-parameter)."""
        crv, _ = nurbs.interpolate_curve(uv, "natural", params=params)
        return occ.bspline_curve(crv)

    def face(self, surface, loops: list[list]):
        """Face on a surface bounded by loops of edges (first: outer). Wires are oriented by ShapeFix."""
        wires = []
        for loop in loops:
            mk = BRepBuilderAPI_MakeWire()
            for e in loop:
                mk.Add(e)
            if not mk.IsDone():
                raise RuntimeError("wire construction failed")
            wires.append(mk.Wire())
        mk = BRepBuilderAPI_MakeFace(surface, wires[0], True)
        for w in wires[1:]:
            mk.Add(w)
        if not mk.IsDone():
            raise RuntimeError("face construction failed")
        sf = ShapeFix_Face(mk.Face())
        sf.FixOrientation()
        return sf.Face()

    def solid(self, faces: list):
        shell = TopoDS_Shell()
        self.builder.MakeShell(shell)
        for f in orient_faces(faces):
            self.builder.Add(shell, f)
        shell.Closed(True)
        solid = TopoDS_Solid()
        self.builder.MakeSolid(solid)
        self.builder.Add(solid, shell)
        BRepLib.OrientClosedSolid_s(solid)
        return solid

    def compound(self, shapes: list):
        comp = TopoDS_Compound()
        self.builder.MakeCompound(comp)
        for s in shapes:
            self.builder.Add(comp, s)
        return comp


# ---------------------------------------------------------------------------------------- result

@dataclass
class RowBrep:
    """The bodies of one blade row and what they were built from."""
    nblades: int
    options: BuildOptions
    x_inlet: float
    x_outlet: float
    bore_radius: float
    seam: float                       # theta of the generatrix of the revolved surfaces
    hub: Streamline
    casing: Streamline
    tip: Streamline                   # tip streamline (the casing when the tip is on it)
    blade_surface: BladeSurface
    sheet: SheetSurface
    bodies: dict[str, object] = field(default_factory=dict)
    faces: dict[str, object] = field(default_factory=dict)          # role -> face (one face per role)
    surfaces: dict[str, object] = field(default_factory=dict)       # name -> Geom surface handle
    notes: list[str] = field(default_factory=list)

    def role(self, face) -> str | None:
        for r, f in self.faces.items():
            if f.IsSame(face):
                return r
        return None

    def faces_by_role(self, body: str) -> dict[str, list]:
        out: dict[str, list] = {}
        for f in occ.explore(self.bodies[body], "face"):
            out.setdefault(self.role(f) or "unknown", []).append(f)
        return out


# ---------------------------------------------------------------------------------------------- build

def build_row(geo: Geometry, options: BuildOptions | None = None, nblades: int | None = None) -> RowBrep:
    opts = options or BuildOptions()
    if geo.hub is None or geo.casing is None:
        raise ValueError("T-Blade3 wrote no hub/casing streamline (hub.<cn>.sldcrv, casing.<cn>.sldcrv)")
    if geo.meanlines is None:
        raise ValueError("T-Blade3 wrote no meanlines")
    nb = nblades or nblades_of(geo)
    notes: list[str] = []
    hub = Streamline.from_xyz(geo.hub)
    casing = Streamline.from_xyz(geo.casing)

    mx = geo.meanlines[..., 0]
    x_in = float(mx.min()) if opts.x_inlet is None else float(opts.x_inlet)
    x_out = float(mx.max()) if opts.x_outlet is None else float(opts.x_outlet)
    for stl, name in ((hub, "hub"), (casing, "casing")):
        lo, hi = stl.xrange
        if not lo < x_in < x_out < hi:
            raise ValueError(f"inlet/outlet x ({x_in:.4g}, {x_out:.4g}) outside the {name} streamline "
                             f"({lo:.4g}, {hi:.4g})")
    xs = np.linspace(x_in, x_out, 201)
    bore = 0.25 * float(hub.radius(xs)[0].min()) if opts.bore_radius is None else float(opts.bore_radius)
    if not 0 < bore < float(hub.radius(xs)[0].min()):
        raise ValueError(f"bore radius {bore:.4g} must be positive and below the hub")

    bs = blade_surface(geo, hub, casing, opts, notes)
    sheet = sheet_surface(geo, hub, casing, nb, x_in, x_out, bore, opts)
    tip = casing if bs.tip_on_casing else Streamline.from_xyz(geo.meanlines[-1])

    theta_mean = float(np.angle(np.exp(1j * cyl(geo.meanlines)[2]).mean()))
    seam = theta_mean + math.pi                      # revolved surfaces have their seam opposite the row
    kit = _Kit()

    # --- surfaces -------------------------------------------------------------------------------
    s_hub = hub.surface(seam)
    s_cas = casing.surface(seam)
    s_tip = s_cas if bs.tip_on_casing else tip.surface(seam)
    ax = gp_Ax3(gp_Pnt(0, 0, 0), gp_Dir(1, 0, 0), gp_Dir(0, math.sin(seam), math.cos(seam)))
    s_bore = Geom_CylindricalSurface(ax, bore)       # u = seam - theta, v = x
    s_in = Geom_Plane(gp_Pnt(x_in, 0, 0), gp_Dir(1, 0, 0))
    s_out = Geom_Plane(gp_Pnt(x_out, 0, 0), gp_Dir(1, 0, 0))
    blade_n = bs.surface
    s_ss = occ.bspline_surface(blade_n)              # two handles on the same geometry: the TE edge
    s_ps = occ.bspline_surface(blade_n)              # needs a p-curve on each side (u = 0 and u = 1)
    sh = sheet.half_pitch
    lo_n, hi_n = rotated(sheet.surface, -sh), rotated(sheet.surface, sh)
    s_lo, s_hi = occ.bspline_surface(lo_n), occ.bspline_surface(hi_n)

    # --- blade vertices and edges ----------------------------------------------------------------
    u0, u1 = blade_n.urange
    v0, v1 = blade_n.vrange
    ule = bs.u_le
    P = lambda u, v: blade_n([u], [v])[0]                                  # noqa: E731
    vb_te, vb_le, vt_te, vt_le = (kit.vertex(P(u, v)) for u, v in ((u0, v0), (ule, v0), (u0, v1), (ule, v1)))
    te_crv = occ.bspline_curve(nurbs.iso_curve(blade_n, 0, u0))
    le_crv = occ.bspline_curve(nurbs.iso_curve(blade_n, 0, ule))
    e_te = kit.edge(te_crv, vb_te, vt_te, v0, v1)
    e_le = kit.edge(le_crv, vb_le, vt_le, v0, v1)
    kit.pcurve(e_te, kit.line((u0, 0), (0, 1)), s_ss)
    kit.pcurve(e_te, kit.line((u1, 0), (0, 1)), s_ps)
    kit.pcurve(e_le, kit.line((ule, 0), (0, 1)), s_ss)
    kit.pcurve(e_le, kit.line((ule, 0), (0, 1)), s_ps)

    def blade_row_edge(v, ua, ub, va, vb, end_surface, end_stl, s_side):
        iso = nurbs.iso_curve(blade_n, 1, v)
        e = kit.edge(occ.bspline_curve(iso), va, vb, ua, ub)
        kit.pcurve(e, kit.line((0, v), (1, 0)), s_side)
        t = _samples(iso.knots, ua, ub)
        kit.pcurve(e, kit.sampled(t, end_stl.uv(iso(t), seam)), end_surface)
        return e

    e_root_ss = blade_row_edge(v0, u0, ule, vb_te, vb_le, s_hub, hub, s_ss)
    e_root_ps = blade_row_edge(v0, ule, u1, vb_le, vb_te, s_hub, hub, s_ps)
    e_tip_ss = blade_row_edge(v1, u0, ule, vt_te, vt_le, s_tip, tip, s_ss)
    e_tip_ps = blade_row_edge(v1, ule, u1, vt_le, vt_te, s_tip, tip, s_ps)

    # --- sheet vertices and edges (lo and hi) ------------------------------------------------------
    su0, su1 = sheet.surface.urange
    levels = {"bore": sheet.v_bore, "hub": sheet.v_hub, "casing": sheet.v_casing}
    level_surface = {"bore": (s_bore, None), "hub": (s_hub, hub), "casing": (s_cas, casing)}
    side = {}
    for name, srf_n, s_geom in (("lo", lo_n, s_lo), ("hi", hi_n, s_hi)):
        V = {(end, lv): kit.vertex(srf_n([u], [v])[0])
             for end, u in (("in", su0), ("out", su1)) for lv, v in levels.items()}
        E = {}
        for lv, v in levels.items():                      # rows: bore, hub, casing
            iso = nurbs.iso_curve(srf_n, 1, v)
            e = kit.edge(occ.bspline_curve(iso), V["in", lv], V["out", lv], su0, su1)
            kit.pcurve(e, kit.line((0, v), (1, 0)), s_geom)
            t = _samples(iso.knots, su0, su1)
            surf, stl = level_surface[lv]
            pts = iso(t)
            if stl is None:                               # bore cylinder: (seam - theta, x)
                x, _, th = cyl(pts)
                uv = np.column_stack([_wrap(seam - th), x])
            else:
                uv = stl.uv(pts, seam)
            kit.pcurve(e, kit.sampled(t, uv), surf)
            E[lv] = e
        for end, u in (("in", su0), ("out", su1)):        # columns, split at the hub
            iso = nurbs.iso_curve(srf_n, 0, u)
            crv = occ.bspline_curve(iso)
            for part, (la, lb) in (("lower", ("bore", "hub")), ("upper", ("hub", "casing"))):
                e = kit.edge(crv, V[end, la], V[end, lb], levels[la], levels[lb])
                kit.pcurve(e, kit.line((u, 0), (0, 1)), s_geom)
                E[end, part] = e
        side[name] = (V, E)

    # --- arcs at the inlet and outlet ----------------------------------------------------------------
    arcs = {}
    for end, x, plane in (("in", x_in, s_in), ("out", x_out, s_out)):
        for lv, surf_info in level_surface.items():
            surf, stl = surf_info
            radius = bore if stl is None else float(stl.radius(x)[0][0])
            circle = Geom_Circle(gp_Ax2(gp_Pnt(x, 0, 0), gp_Dir(1, 0, 0),
                                        gp_Dir(0, math.sin(seam), math.cos(seam))), radius)
            va, vb = side["lo"][0][end, lv], side["hi"][0][end, lv]
            th_lo = cyl(np.array(occ._xyz(_vpnt(va))))[2]
            th_hi = cyl(np.array(occ._xyz(_vpnt(vb))))[2]
            phi_lo, phi_hi = float(_wrap(seam - th_lo)), float(_wrap(seam - th_hi))
            e = kit.edge(circle, vb, va, phi_hi, phi_lo)      # phi increases from the hi to the lo side
            if stl is None:
                kit.pcurve(e, kit.line((0, x), (1, 0)), surf)
            else:
                kit.pcurve(e, kit.line((0, float(stl.t_at(x)[0])), (1, 0)), surf)
            arcs[end, lv] = e

    # --- faces ----------------------------------------------------------------------------------------
    F = {}
    F[BLADE_SUCTION] = kit.face(s_ss, [[e_te, e_root_ss, e_le, e_tip_ss]])
    F[BLADE_PRESSURE] = kit.face(s_ps, [[e_le, e_root_ps, e_te, e_tip_ps]])
    F[BLADE_ROOT] = kit.face(s_hub, [[e_root_ss, e_root_ps]])
    F[BLADE_TIP] = kit.face(s_tip, [[e_tip_ss, e_tip_ps]])
    (Vl, El), (Vh, Eh) = side["lo"], side["hi"]
    for role, s_geom, E, part, la, lb in (
            (WEDGE_PERIODIC_LO, s_lo, El, "lower", "bore", "hub"),
            (WEDGE_PERIODIC_HI, s_hi, Eh, "lower", "bore", "hub"),
            (PERIODIC_LO, s_lo, El, "upper", "hub", "casing"),
            (PERIODIC_HI, s_hi, Eh, "upper", "hub", "casing")):
        F[role] = kit.face(s_geom, [[E[la], E["out", part], E[lb], E["in", part]]])
    for end, plane, r_out, r_wedge in (("in", s_in, INLET, WEDGE_INLET), ("out", s_out, OUTLET, WEDGE_OUTLET)):
        F[r_wedge] = kit.face(plane, [[El[end, "lower"], arcs[end, "hub"], Eh[end, "lower"], arcs[end, "bore"]]])
        F[r_out] = kit.face(plane, [[El[end, "upper"], arcs[end, "casing"], Eh[end, "upper"], arcs[end, "hub"]]])
    F[BORE] = kit.face(s_bore, [[El["bore"], arcs["out", "bore"], Eh["bore"], arcs["in", "bore"]]])
    F[HUB] = kit.face(s_hub, [[El["hub"], arcs["out", "hub"], Eh["hub"], arcs["in", "hub"]],
                              [e_root_ss, e_root_ps]])
    cas_loops = [[El["casing"], arcs["out", "casing"], Eh["casing"], arcs["in", "casing"]]]
    if bs.tip_on_casing:
        cas_loops.append([e_tip_ss, e_tip_ps])
    F[CASING] = kit.face(s_cas, cas_loops)

    # edge tolerances from the true deviation of each 3-D curve from its p-curves (the blade root edge,
    # a Cartesian cubic, is ~1e-4 mm off the revolved hub between the T-Blade3 points)
    allf = kit.compound(list(F.values()))
    BRepLib.SameParameter_s(allf, kit.TOL, True)
    BRepLib.UpdateTolerances_s(allf, False)

    # --- bodies --------------------------------------------------------------------------------------------
    blade = kit.solid([F[BLADE_SUCTION], F[BLADE_PRESSURE], F[BLADE_ROOT], F[BLADE_TIP]])
    wedge = kit.solid([F[WEDGE_PERIODIC_LO], F[WEDGE_PERIODIC_HI], F[WEDGE_INLET], F[WEDGE_OUTLET], F[BORE],
                       F[HUB], F[BLADE_ROOT]])
    pas = [F[PERIODIC_LO], F[PERIODIC_HI], F[INLET], F[OUTLET], F[HUB], F[CASING], F[BLADE_SUCTION],
           F[BLADE_PRESSURE]]
    if not bs.tip_on_casing:
        pas.append(F[BLADE_TIP])
    passage = kit.solid(pas)
    solid = kit.solid([F[BLADE_SUCTION], F[BLADE_PRESSURE], F[BLADE_TIP], F[WEDGE_PERIODIC_LO],
                       F[WEDGE_PERIODIC_HI], F[WEDGE_INLET], F[WEDGE_OUTLET], F[BORE], F[HUB]])
    bodies = {"blade": blade, "hub_wedge": wedge, "passage": passage, "solid": solid,
              "assembly": kit.compound([blade, wedge, passage])}
    surfaces = {"blade_ss": s_ss, "blade_ps": s_ps, "hub": s_hub, "casing": s_cas, "tip": s_tip,
                "bore": s_bore, "inlet": s_in, "outlet": s_out, "periodic_lo": s_lo, "periodic_hi": s_hi}
    return RowBrep(nb, opts, x_in, x_out, bore, seam, hub, casing, tip, bs, sheet, bodies, F, surfaces, notes)


def orient_faces(faces: list) -> list:
    """Faces of a closed shell with consistent orientations: each shared edge runs opposite ways in its
    two faces. Starts from the first face as given; the solid is flipped afterwards if inside out."""
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer

    def edges(face):
        out = []
        exp = TopExp_Explorer(face, TopAbs_EDGE)
        while exp.More():
            out.append(exp.Current())
            exp.Next()
        return out

    result: list = [None] * len(faces)
    result[0] = faces[0]
    todo = [0]
    while todo:
        i = todo.pop()
        for e in edges(result[i]):
            for j, g in enumerate(faces):
                if result[j] is not None:
                    continue
                for e2 in edges(g):
                    if e2.IsSame(e):
                        result[j] = g.Reversed() if e2.Orientation() == e.Orientation() else g
                        todo.append(j)
                        break
    if any(r is None for r in result):
        raise RuntimeError("faces do not form one connected shell")
    return [TopoDS.Face(r) for r in result]


def _samples(knots: np.ndarray, a: float, b: float, per_span: int = 2) -> np.ndarray:
    """Parameters in [a, b]: every distinct knot plus ``per_span - 1`` points inside each span."""
    k = np.unique(knots[(knots >= a) & (knots <= b)])
    k = np.unique(np.concatenate([[a], k, [b]]))
    fr = np.arange(per_span) / per_span
    t = (k[:-1, None] + np.diff(k)[:, None] * fr[None]).ravel()
    return np.concatenate([t, [b]])


def _vpnt(v):
    from OCP.BRep import BRep_Tool
    return BRep_Tool.Pnt_s(v)
