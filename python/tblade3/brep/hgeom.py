"""``.hgeom``: HANGAR's exact geometry format (version 1; version 0 files are still read).

One zip file holding:

- ``manifest.yaml``: units, axis convention, provenance, and the B-Rep: surfaces, edges (3-D curve, range,
  vertices, tolerance, one p-curve per face), faces (surface, role, loops of oriented edges), bodies
  (solids as shells of oriented faces), and the sensitivity index;
- ``arrays.npz``: every number array the manifest refers to by key (control points, knots, weights,
  vertex coordinates, sensitivities);
- ``source/<name>``: the T-Blade3 input files the geometry was built from;
- ``brep/<body>.brep`` (version 1): each body as OpenCASCADE .brep text, for readers without OCC's API
  (gmsh). Its faces are matched to the manifest's by ``centroid`` and ``area`` (version 1, per face).

Version 1 also adds ``blade`` (``u_le``, ``u_range``, ``v_range`` of the blade surface; u runs around the
section, v from root to tip).

Nothing is converted: B-spline surfaces and curves are stored with their own control points and knots
(the ones ``tblade3.brep.nurbs`` computed), revolved surfaces as their generatrix and axis, cylinders and
planes by their frames. Faces shared between bodies (e.g. the hub between the wedge and the passage) are
stored once and referenced by each body, so the bodies' conformity is kept.

Geometry types
  surface: bspline (udegree, vdegree, uknots, vknots, cps (nu, nv, 3), weights (nu, nv) or none);
           revolution (curve: a 3-D curve, axis origin/direction; u = angle, v = curve parameter);
           cylinder (origin, axis, xdir, radius; u = angle from xdir, v = distance along axis);
           plane (origin, normal, xdir)
  curve:   bspline (degree, knots, cps (n, 3), weights); circle (center, normal, xdir, radius)
  pcurve:  line (origin (2), direction (2)); bspline (degree, knots, cps (n, 2), weights)
Knot vectors are stored expanded (each knot repeated by its multiplicity).

Orientation: "F" (forward) or "R" (reversed), as in OpenCASCADE. A face's loops are given for the
face's forward orientation; bodies list (face, orientation) per shell, with outward normals.

Sensitivities: ``sensitivities.surfaces[name]`` is the key of an array (nvar, *cps.shape) holding
d(control points)/d(variable) for the variables in ``sensitivities.variables`` (in the file's units per
unit of the variable). Surfaces not listed do not move. Edges are iso-curves or circles of the surfaces
and move with them; their derivatives are not stored.
"""
from __future__ import annotations

import io
import math
import zipfile
from pathlib import Path

import numpy as np
import yaml
from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Curve2d
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeVertex
from OCP.Geom import Geom_Circle, Geom_CylindricalSurface, Geom_Plane, Geom_SurfaceOfRevolution
from OCP.Geom2d import Geom2d_Line
from OCP.Geom2dConvert import Geom2dConvert
from OCP.GeomAbs import GeomAbs_BSplineCurve, GeomAbs_Circle, GeomAbs_Line
from OCP.gp import gp_Ax1, gp_Ax2, gp_Ax3, gp_Dir, gp_Dir2d, gp_Pnt, gp_Pnt2d
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_FORWARD, TopAbs_REVERSED, TopAbs_SHELL, TopAbs_WIRE
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS, TopoDS_Compound, TopoDS_Face, TopoDS_Shell, TopoDS_Solid, TopoDS_Wire

from . import nurbs, occ

FORMAT = "hgeom"
VERSION = 1


# ---------------------------------------------------------------------------------------------- write

class _Arrays:
    def __init__(self):
        self.data: dict[str, np.ndarray] = {}

    def put(self, key: str, arr) -> str:
        self.data[key] = np.asarray(arr)
        return key


def _ori(shape) -> str:
    return "R" if shape.Orientation() == TopAbs_REVERSED else "F"


def _index(items: list, shape) -> int:
    for i, s in enumerate(items):
        if s.IsSame(shape):
            return i
    items.append(shape)
    return len(items) - 1


def _sub(shape, kind) -> list:
    exp = TopExp_Explorer(shape, kind)
    out = []
    while exp.More():
        out.append(exp.Current())
        exp.Next()
    return out


def write(row, path: str | Path, bodies=None, sensitivities=None, source: dict | None = None) -> Path:
    """Write a ``build.RowBrep`` (the chosen bodies; default all but the assembly)."""
    from importlib.metadata import PackageNotFoundError, version
    try:
        pkg_version = version("tblade3")
    except PackageNotFoundError:
        pkg_version = "?"
    from . import build

    path = Path(path)
    bodies = list(bodies) if bodies is not None else [b for b in build.BODY_NAMES if b != "assembly"]
    arr = _Arrays()

    # topology: unique faces, edges, vertices over all bodies
    faces, edges, verts = [], [], []
    body_out = {}
    for b in bodies:
        solids = []
        for so in occ.explore(row.bodies[b], "solid"):
            shells = []
            for sh in _sub(so, TopAbs_SHELL):
                shells.append([[_index(faces, TopoDS.Face(f)), _ori(f)] for f in _sub(sh, TopAbs_FACE)])
            solids.append({"shells": shells})
        body_out[b] = {"solids": solids}
    for f in faces:
        for e in _sub(f, TopAbs_EDGE):
            _index(edges, TopoDS.Edge(e))
    for e in edges:
        _index(verts, TopExp.FirstVertex_s(e))
        _index(verts, TopExp.LastVertex_s(e))

    # surfaces used by these faces
    used = sorted({_face_surface(row, f) for f in faces})
    surfaces = {name: _surface_record(row, name, arr) for name in used}

    face_out = []
    face_ids = {}
    for i, f in enumerate(faces):
        ff = TopoDS.Face(f.Oriented(TopAbs_FORWARD))
        loops = []
        for w in _sub(ff, TopAbs_WIRE):
            loops.append([[_index(edges, TopoDS.Edge(e)), _ori(e)] for e in _sub(w, TopAbs_EDGE)])
        face_out.append({"surface": _face_surface(row, f), "role": row.role(f),
                         "tolerance": float(BRep_Tool.Tolerance_s(f)), "loops": loops,
                         "centroid": [float(c) for c in _face_centroid(f)], "area": float(occ.area(f))})
        face_ids[i] = ff

    edge_out = []
    for i, e in enumerate(edges):
        ad = BRepAdaptor_Curve(e)
        t0, t1 = ad.FirstParameter(), ad.LastParameter()
        rec = {"curve": _curve3d_record(ad, arr, f"edge{i}"), "range": [t0, t1],
               "vertices": [_index(verts, TopExp.FirstVertex_s(e)), _index(verts, TopExp.LastVertex_s(e))],
               "tolerance": float(BRep_Tool.Tolerance_s(e)), "pcurves": {}}
        for j, ff in face_ids.items():
            if any(x.IsSame(e) for x in _sub(ff, TopAbs_EDGE)):
                rec["pcurves"][j] = _pcurve_record(BRepAdaptor_Curve2d(e, ff), arr, f"edge{i}_face{j}")
        edge_out.append(rec)

    vxyz = np.array([occ._xyz(BRep_Tool.Pnt_s(TopoDS.Vertex(v))) for v in verts])
    vtol = np.array([BRep_Tool.Tolerance_s(TopoDS.Vertex(v)) for v in verts])

    manifest = {
        "format": FORMAT, "version": VERSION, "units": "mm",
        "generator": f"tblade3 {pkg_version} (tblade3.brep)",
        "axis": {"origin": [0.0, 0.0, 0.0], "direction": [1.0, 0.0, 0.0],
                 "convention": "x is the machine axis; a point at radius r and angle theta is "
                               "(x, r sin(theta), r cos(theta))"},
        "row": {"nblades": int(row.nblades), "bore_radius": float(row.bore_radius),
                "x_inlet": float(row.x_inlet), "x_outlet": float(row.x_outlet), "seam": float(row.seam),
                "tip_on_casing": bool(row.blade_surface.tip_on_casing)},
        "blade": {"u_le": float(row.blade_surface.u_le),
                  "u_range": [float(t) for t in row.blade_surface.surface.urange],
                  "v_range": [float(t) for t in row.blade_surface.surface.vrange]},
        "notes": list(row.notes),
        "source": {},
        "surfaces": surfaces,
        "vertices": {"xyz": arr.put("vertices/xyz", vxyz), "tolerance": arr.put("vertices/tolerance", vtol)},
        "edges": edge_out,
        "faces": face_out,
        "bodies": body_out,
    }
    files = {}
    if source:
        files = dict(source.get("files", {}))
        manifest["source"] = {"files": sorted(files),
                              "design_variables": {k: float(v) for k, v in
                                                   source.get("design_variables", {}).items()}}
    if sensitivities is not None:
        sens = {"variables": list(sensitivities.names), "methods": dict(sensitivities.methods),
                "values": {k: float(v) for k, v in sensitivities.values.items()}, "surfaces": {},
                "flowpath_change": {k: float(v) for k, v in sensitivities.flowpath_change.items()}}
        for name, d in sensitivities.surfaces.items():
            if name in surfaces:
                sens["surfaces"][name] = arr.put(f"sensitivities/{name}", d)
        manifest["sensitivities"] = sens

    buf = io.BytesIO()
    np.savez_compressed(buf, **arr.data)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.yaml", yaml.safe_dump(_plain(manifest), sort_keys=False, width=120))
        z.writestr("arrays.npz", buf.getvalue())
        for name, text in files.items():
            z.writestr(f"source/{name}", text)
        for b in bodies:
            z.writestr(f"brep/{b}.brep", _brep_text(row.bodies[b]))
    return path


def _face_centroid(face) -> np.ndarray:
    """Area centroid of a face (``occ.centroid`` integrates a volume and is meant for solids)."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    p = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, p, occ.GPROP_EPS)
    return np.array(occ._xyz(p.CentreOfMass()))


def _brep_text(shape) -> str:
    """The OpenCASCADE .brep text of a shape (for readers without OCC's API, e.g. gmsh)."""
    import tempfile
    from OCP.BRepTools import BRepTools
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "body.brep"
        if not BRepTools.Write_s(shape, str(p)):
            raise OSError("could not write the .brep text")
        return p.read_text()


def _plain(obj):
    """numpy scalars and tuples to plain YAML types."""
    if isinstance(obj, dict):
        return {(int(k) if isinstance(k, np.integer) else k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    if isinstance(obj, np.generic):
        return obj.item()
    return obj


def _face_surface(row, face) -> str:
    from . import build
    role = row.role(face)
    name = build.FACE_SURFACE[role]
    if name == "tip" and row.blade_surface.tip_on_casing:
        return "casing"
    return name


def _surface_record(row, name: str, arr: _Arrays) -> dict:
    from . import build
    seam = row.seam
    if name in ("blade_ss", "blade_ps"):
        return _bspline_surface(row.blade_surface.surface, arr, f"surfaces/{name}")
    if name in ("periodic_lo", "periodic_hi"):
        sh = row.sheet
        srf = build.rotated(sh.surface, -sh.half_pitch if name == "periodic_lo" else sh.half_pitch)
        return _bspline_surface(srf, arr, f"surfaces/{name}")
    if name in ("hub", "casing", "tip"):
        stl = {"hub": row.hub, "casing": row.casing, "tip": row.tip}[name]
        cps = stl.curve.cps
        c3 = np.column_stack([cps[:, 0], cps[:, 1] * math.sin(seam), cps[:, 1] * math.cos(seam)])
        return {"type": "revolution", "axis_origin": [0.0, 0.0, 0.0], "axis_direction": [1.0, 0.0, 0.0],
                "curve": {"type": "bspline", "degree": stl.curve.degree,
                          "knots": arr.put(f"surfaces/{name}/knots", stl.curve.knots),
                          "cps": arr.put(f"surfaces/{name}/cps", c3), "weights": None},
                "generatrix_xr": arr.put(f"surfaces/{name}/xr", stl.curve.cps)}
    if name == "bore":
        return {"type": "cylinder", "origin": [0.0, 0.0, 0.0], "axis": [1.0, 0.0, 0.0],
                "xdir": [0.0, math.sin(seam), math.cos(seam)], "radius": float(row.bore_radius)}
    if name in ("inlet", "outlet"):
        x = row.x_inlet if name == "inlet" else row.x_outlet
        return {"type": "plane", "origin": [float(x), 0.0, 0.0], "normal": [1.0, 0.0, 0.0],
                "xdir": [0.0, 0.0, 1.0]}
    raise KeyError(name)


def _bspline_surface(srf: nurbs.Surface, arr: _Arrays, key: str) -> dict:
    return {"type": "bspline", "udegree": srf.udegree, "vdegree": srf.vdegree,
            "uknots": arr.put(f"{key}/uknots", srf.uknots), "vknots": arr.put(f"{key}/vknots", srf.vknots),
            "cps": arr.put(f"{key}/cps", srf.cps),
            "weights": None if srf.weights is None else arr.put(f"{key}/weights", srf.weights)}


def _bspline_curve_record(c, arr: _Arrays, key: str, dim: int) -> dict:
    n = c.NbPoles()
    if dim == 3:
        cps = np.array([occ._xyz(c.Pole(i)) for i in range(1, n + 1)])
    else:
        cps = np.array([(c.Pole(i).X(), c.Pole(i).Y()) for i in range(1, n + 1)])
    knots = nurbs.expand_knots([c.Knot(i) for i in range(1, c.NbKnots() + 1)],
                               [c.Multiplicity(i) for i in range(1, c.NbKnots() + 1)])
    w = None
    if c.IsRational():
        w = arr.put(f"{key}/weights", np.array([c.Weight(i) for i in range(1, n + 1)]))
    return {"type": "bspline", "degree": c.Degree(), "knots": arr.put(f"{key}/knots", knots),
            "cps": arr.put(f"{key}/cps", cps), "weights": w}


def _curve3d_record(ad: BRepAdaptor_Curve, arr: _Arrays, key: str) -> dict:
    kind = ad.GetType()
    if kind == GeomAbs_Circle:
        c = ad.Circle()
        ax = c.Position()
        return {"type": "circle", "center": list(occ._xyz(ax.Location())),
                "normal": list(occ._xyz(ax.Direction())), "xdir": list(occ._xyz(ax.XDirection())),
                "radius": c.Radius()}
    if kind == GeomAbs_BSplineCurve:
        return _bspline_curve_record(ad.BSpline(), arr, key, 3)
    raise NotImplementedError(f"3-D curve type {kind}")


def _pcurve_record(ad: BRepAdaptor_Curve2d, arr: _Arrays, key: str) -> dict:
    kind = ad.GetType()
    if kind == GeomAbs_Line:
        ln = ad.Line()
        return {"type": "line", "origin": [ln.Location().X(), ln.Location().Y()],
                "direction": [ln.Direction().X(), ln.Direction().Y()]}
    if kind == GeomAbs_BSplineCurve:
        return _bspline_curve_record(ad.BSpline(), arr, key, 2)
    # any other analytic p-curve (circles on planes): exact rational B-spline
    from OCP.Geom2d import Geom2d_TrimmedCurve
    trimmed = Geom2d_TrimmedCurve(ad.Curve(), ad.FirstParameter(), ad.LastParameter())
    bs = Geom2dConvert.CurveToBSplineCurve_s(trimmed)
    rec = _bspline_curve_record(bs, arr, key, 2)
    rec["reparameterized"] = True
    return rec


# ----------------------------------------------------------------------------------------------- read

class HGeom:
    """A read .hgeom: the manifest, the arrays, the rebuilt OpenCASCADE bodies and the source files."""

    def __init__(self, manifest: dict, arrays: dict[str, np.ndarray], sources: dict[str, str]):
        self.manifest = manifest
        self.arrays = arrays
        self.sources = sources
        self.surfaces = {name: _make_surface(rec, arrays) for name, rec in manifest["surfaces"].items()}
        self.faces: list = []
        self.bodies: dict[str, object] = {}
        self._build()

    def array(self, key):
        return None if key is None else self.arrays[key]

    def sensitivity(self, surface: str) -> np.ndarray | None:
        sens = self.manifest.get("sensitivities") or {}
        key = sens.get("surfaces", {}).get(surface)
        return None if key is None else self.arrays[key]

    def role(self, face) -> str | None:
        for f, rec in zip(self.faces, self.manifest["faces"]):
            if f.IsSame(face):
                return rec["role"]
        return None

    def _build(self) -> None:
        m, a = self.manifest, self.arrays
        b = BRep_Builder()
        xyz = a[m["vertices"]["xyz"]]
        vtol = a[m["vertices"]["tolerance"]]
        verts = []
        for p, t in zip(xyz, vtol):
            v = BRepBuilderAPI_MakeVertex(gp_Pnt(*map(float, p))).Vertex()
            b.UpdateVertex(v, float(t))
            verts.append(v)
        face_surf = [self.surfaces[f["surface"]] for f in m["faces"]]
        edges = []
        for rec in m["edges"]:
            crv = _make_curve3d(rec["curve"], a)
            t0, t1 = rec["range"]
            v0, v1 = (verts[i] for i in rec["vertices"])
            e = BRepBuilderAPI_MakeEdge(crv, v0, v1, float(t0), float(t1)).Edge()
            for j, pc in rec["pcurves"].items():
                if pc.get("reparameterized"):
                    continue                 # analytic p-curve on a plane: OpenCASCADE recomputes it
                b.UpdateEdge(e, _make_pcurve(pc, a), face_surf[int(j)], TopLoc_Location(), float(rec["tolerance"]))
            b.UpdateEdge(e, float(rec["tolerance"]))
            edges.append(e)
        for rec, surf in zip(m["faces"], face_surf):
            f = TopoDS_Face()
            b.MakeFace(f, surf, TopLoc_Location(), float(rec["tolerance"]))
            for loop in rec["loops"]:
                w = TopoDS_Wire()
                b.MakeWire(w)
                for ei, o in loop:
                    b.Add(w, edges[ei].Oriented(TopAbs_REVERSED if o == "R" else TopAbs_FORWARD))
                w.Closed(True)
                b.Add(f, w)
            self.faces.append(f)
        for name, rec in m["bodies"].items():
            solids = []
            for srec in rec["solids"]:
                so = TopoDS_Solid()
                b.MakeSolid(so)
                for shell in srec["shells"]:
                    sh = TopoDS_Shell()
                    b.MakeShell(sh)
                    for fi, o in shell:
                        b.Add(sh, self.faces[fi].Oriented(TopAbs_REVERSED if o == "R" else TopAbs_FORWARD))
                    sh.Closed(True)
                    b.Add(so, sh)
                solids.append(so)
            if len(solids) == 1:
                self.bodies[name] = solids[0]
            else:
                comp = TopoDS_Compound()
                b.MakeCompound(comp)
                for so in solids:
                    b.Add(comp, so)
                self.bodies[name] = comp


def read(path: str | Path) -> HGeom:
    with zipfile.ZipFile(path) as z:
        manifest = yaml.safe_load(z.read("manifest.yaml"))
        if manifest.get("format") != FORMAT:
            raise ValueError(f"{path} is not an .hgeom file")
        if manifest.get("version", 0) > VERSION:
            raise ValueError(f"{path}: .hgeom version {manifest['version']} is newer than this reader ({VERSION})")
        with np.load(io.BytesIO(z.read("arrays.npz"))) as npz:
            arrays = {k: npz[k] for k in npz.files}
        sources = {n[len("source/"):]: z.read(n).decode() for n in z.namelist() if n.startswith("source/")}
    return HGeom(manifest, arrays, sources)


def _make_surface(rec: dict, a: dict):
    kind = rec["type"]
    if kind == "bspline":
        srf = nurbs.Surface(a[rec["uknots"]], a[rec["vknots"]], a[rec["cps"]],
                            None if rec.get("weights") is None else a[rec["weights"]],
                            rec["udegree"], rec["vdegree"])
        return occ.bspline_surface(srf)
    if kind == "revolution":
        crv = _make_curve3d(rec["curve"], a)
        return Geom_SurfaceOfRevolution(crv, gp_Ax1(gp_Pnt(*rec["axis_origin"]), gp_Dir(*rec["axis_direction"])))
    if kind == "cylinder":
        ax = gp_Ax3(gp_Pnt(*rec["origin"]), gp_Dir(*rec["axis"]), gp_Dir(*rec["xdir"]))
        return Geom_CylindricalSurface(ax, float(rec["radius"]))
    if kind == "plane":
        return Geom_Plane(gp_Ax3(gp_Pnt(*rec["origin"]), gp_Dir(*rec["normal"]), gp_Dir(*rec["xdir"])))
    raise ValueError(f"unknown surface type {kind!r}")


def _make_curve3d(rec: dict, a: dict):
    if rec["type"] == "circle":
        return Geom_Circle(gp_Ax2(gp_Pnt(*rec["center"]), gp_Dir(*rec["normal"]), gp_Dir(*rec["xdir"])),
                           float(rec["radius"]))
    if rec["type"] == "bspline":
        crv = nurbs.Curve(a[rec["knots"]], a[rec["cps"]],
                          None if rec.get("weights") is None else a[rec["weights"]], rec["degree"])
        return occ.bspline_curve(crv)
    raise ValueError(f"unknown curve type {rec['type']!r}")


def _make_pcurve(rec: dict, a: dict):
    if rec["type"] == "line":
        return Geom2d_Line(gp_Pnt2d(*rec["origin"]), gp_Dir2d(*rec["direction"]))
    crv = nurbs.Curve(a[rec["knots"]], a[rec["cps"]], None if rec.get("weights") is None else a[rec["weights"]],
                      rec["degree"])
    return occ.bspline_curve(crv)
