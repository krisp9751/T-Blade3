"""Tessellate the B-Rep of a row for the 3D view (OCP -> PyVista). Safe to call on a worker thread."""
from __future__ import annotations

import numpy as np
import pyvista as pv

# Face role -> (colour name, opacity); roles not listed use "other".
_ROLE_STYLE = {
    "blade_suction": ("blade", 1.0), "blade_pressure": ("blade", 1.0), "blade_root": ("blade", 1.0),
    "blade_tip": ("blade", 1.0),
    "hub": ("hub", 1.0), "bore": ("bore", 1.0),
    "wedge_periodic_lo": ("wedge_periodic", 1.0), "wedge_periodic_hi": ("wedge_periodic", 1.0),
    "wedge_inlet": ("end", 1.0), "wedge_outlet": ("end", 1.0),
    "casing": ("casing", 0.25),
    "periodic_lo": ("periodic", 0.3), "periodic_hi": ("periodic", 0.3),
    "inlet": ("end", 0.3), "outlet": ("end", 0.3),
}
# Colours (light, dark theme)
COLOURS = {
    "blade": ("#5B7FA6", "#7FA3CC"), "hub": ("#C9C7C1", "#7A7A78"), "bore": ("#8E8B84", "#5A5A58"),
    "casing": ("#B9B7B0", "#8A8A88"), "periodic": ("#4FA37A", "#6FC49A"),
    "wedge_periodic": ("#3E8A64", "#5BAE86"), "end": ("#D08A3C", "#E3A65E"), "other": ("#A05AA0", "#C07AC0"),
}


def role_style(role: str | None) -> tuple[str, float]:
    """(colour name, opacity) of a face role."""
    return _ROLE_STYLE.get(role or "", ("other", 1.0))


def face_mesh(face, deflection: float = 0.05) -> pv.PolyData | None:
    """Triangles of one OCC face (call ``BRepMesh_IncrementalMesh`` on the shape first)."""
    from OCP.BRep import BRep_Tool
    from OCP.TopAbs import TopAbs_REVERSED
    from OCP.TopLoc import TopLoc_Location
    loc = TopLoc_Location()
    tri = BRep_Tool.Triangulation_s(face, loc)
    if tri is None:
        return None
    trsf = loc.Transformation()
    identity = loc.IsIdentity()
    n = tri.NbNodes()
    points = np.empty((n, 3))
    for i in range(1, n + 1):
        pnt = tri.Node(i)
        if not identity:
            pnt = pnt.Transformed(trsf)
        points[i - 1] = (pnt.X(), pnt.Y(), pnt.Z())
    flip = face.Orientation() == TopAbs_REVERSED
    cells = np.empty((tri.NbTriangles(), 4), dtype=np.int64)
    cells[:, 0] = 3
    for i in range(1, tri.NbTriangles() + 1):
        a, b, c = tri.Triangle(i).Get()
        cells[i - 1, 1:] = (a - 1, c - 1, b - 1) if flip else (a - 1, b - 1, c - 1)
    return pv.PolyData(points, cells.ravel())


def brep_meshes(row_brep, deflection: float = 0.05) -> list[tuple[str, pv.PolyData]]:
    """One (role, mesh) per face of the assembly body, with the role of each face."""
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    shape = row_brep.bodies["assembly"]
    BRepMesh_IncrementalMesh(shape, deflection, False, 0.3, True)
    out = []
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face(explorer.Current())
        mesh = face_mesh(face, deflection)
        if mesh is not None and mesh.n_cells:
            out.append((row_brep.role(face) or "other", mesh))
        explorer.Next()
    return out


def build_meshes(geometry) -> tuple[list[tuple[str, pv.PolyData]], list[str]]:
    """B-Rep of a geometry as face meshes, and the build notes."""
    from ..brep import build
    row = build.build_row(geometry)
    if "assembly" not in row.bodies:
        raise ValueError("the B-Rep has no assembly body")
    return brep_meshes(row), list(row.notes)
