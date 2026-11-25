"""Small layer over OpenCASCADE (OCP): our B-splines to Geom objects, shape lists, checks, properties.

Coordinates as in T-Blade3: a point at radius r and angle theta is (x, r sin(theta), r cos(theta)); the
machine axis is +x. A right-handed rotation about +x by alpha lowers theta by alpha, so ``rotate_theta``
(which raises theta) rotates by -delta.
"""
from __future__ import annotations

import math

import numpy as np
from OCP.BRep import BRep_Tool
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_Transform
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.collections import List_TopoDS_Shape
from OCP.Geom import Geom_BSplineCurve, Geom_BSplineSurface
from OCP.Geom2d import Geom2d_BSplineCurve
from OCP.GProp import GProp_GProps
from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Pnt2d, gp_Trsf
from OCP.collections import Array1_double as TColStd_Array1OfReal
from OCP.collections import Array1_gp_Pnt as TColgp_Array1OfPnt
from OCP.collections import Array1_gp_Pnt2d as TColgp_Array1OfPnt2d
from OCP.collections import Array1_int as TColStd_Array1OfInteger
from OCP.collections import Array2_double as TColStd_Array2OfReal
from OCP.collections import Array2_gp_Pnt as TColgp_Array2OfPnt
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SOLID, TopAbs_VERTEX
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS

from . import nurbs

X_AXIS = gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(1, 0, 0))


# --------------------------------------------------------------------------------------- conversion

def _real_array(values) -> TColStd_Array1OfReal:
    arr = TColStd_Array1OfReal(1, len(values))
    for i, v in enumerate(values, 1):
        arr.SetValue(i, float(v))
    return arr


def _int_array(values) -> TColStd_Array1OfInteger:
    arr = TColStd_Array1OfInteger(1, len(values))
    for i, v in enumerate(values, 1):
        arr.SetValue(i, int(v))
    return arr


def bspline_surface(srf: nurbs.Surface) -> Geom_BSplineSurface:
    nu, nv, _ = srf.cps.shape
    poles = TColgp_Array2OfPnt(1, nu, 1, nv)
    for i in range(nu):
        for j in range(nv):
            poles.SetValue(i + 1, j + 1, gp_Pnt(*map(float, srf.cps[i, j])))
    uk, um = nurbs.unique_knots(srf.uknots)
    vk, vm = nurbs.unique_knots(srf.vknots)
    if srf.weights is None:
        return Geom_BSplineSurface(poles, _real_array(uk), _real_array(vk), _int_array(um), _int_array(vm),
                                   srf.udegree, srf.vdegree)
    w = TColStd_Array2OfReal(1, nu, 1, nv)
    for i in range(nu):
        for j in range(nv):
            w.SetValue(i + 1, j + 1, float(srf.weights[i, j]))
    return Geom_BSplineSurface(poles, w, _real_array(uk), _real_array(vk), _int_array(um), _int_array(vm),
                               srf.udegree, srf.vdegree)


def bspline_curve(crv: nurbs.Curve) -> Geom_BSplineCurve | Geom2d_BSplineCurve:
    """3-D curve for (n, 3) control points, 2-D (Geom2d) for (n, 2)."""
    k, m = nurbs.unique_knots(crv.knots)
    n, dim = crv.cps.shape
    if dim == 3:
        poles = TColgp_Array1OfPnt(1, n)
        for i in range(n):
            poles.SetValue(i + 1, gp_Pnt(*map(float, crv.cps[i])))
        cls = Geom_BSplineCurve
    else:
        poles = TColgp_Array1OfPnt2d(1, n)
        for i in range(n):
            poles.SetValue(i + 1, gp_Pnt2d(*map(float, crv.cps[i])))
        cls = Geom2d_BSplineCurve
    if crv.weights is None:
        return cls(poles, _real_array(k), _int_array(m), crv.degree)
    return cls(poles, _real_array(crv.weights), _real_array(k), _int_array(m), crv.degree)


def surface_to_nurbs(s) -> nurbs.Surface:
    """Geom_BSplineSurface -> nurbs.Surface (expanded knots)."""
    nu, nv = s.NbUPoles(), s.NbVPoles()
    cps = np.array([[_xyz(s.Pole(i, j)) for j in range(1, nv + 1)] for i in range(1, nu + 1)])
    w = None
    if s.IsURational() or s.IsVRational():
        w = np.array([[s.Weight(i, j) for j in range(1, nv + 1)] for i in range(1, nu + 1)])
    uk = nurbs.expand_knots([s.UKnot(i) for i in range(1, s.NbUKnots() + 1)],
                            [s.UMultiplicity(i) for i in range(1, s.NbUKnots() + 1)])
    vk = nurbs.expand_knots([s.VKnot(i) for i in range(1, s.NbVKnots() + 1)],
                            [s.VMultiplicity(i) for i in range(1, s.NbVKnots() + 1)])
    return nurbs.Surface(uk, vk, cps, w, s.UDegree(), s.VDegree())


def _xyz(p) -> tuple[float, float, float]:
    return (p.X(), p.Y(), p.Z())


# ---------------------------------------------------------------------------------------- shapes

def shape_list(shapes) -> List_TopoDS_Shape:
    out = List_TopoDS_Shape()
    for s in shapes:
        out.Append(s)
    return out


def from_list(lst) -> list:
    out = []
    while lst.Size():
        out.append(lst.First())
        lst.RemoveFirst()
    return out


def explore(shape, kind) -> list:
    """Distinct sub-shapes of a kind ("face", "edge", "vertex", "solid"), in explorer order."""
    topo = {"face": TopAbs_FACE, "edge": TopAbs_EDGE, "vertex": TopAbs_VERTEX, "solid": TopAbs_SOLID}[kind]
    cast = {"face": TopoDS.Face, "edge": TopoDS.Edge, "vertex": TopoDS.Vertex,
            "solid": TopoDS.Solid}[kind]
    out, seen = [], []
    exp = TopExp_Explorer(shape, topo)
    while exp.More():
        s = exp.Current()
        if not any(s.IsSame(t) for t in seen):
            seen.append(s)
            out.append(cast(s))
        exp.Next()
    return out


def face_from_surface(surface, u0, u1, v0, v1, tol: float = 1e-7):
    return BRepBuilderAPI_MakeFace(surface, float(u0), float(u1), float(v0), float(v1), tol).Face()


def rotate_theta(shape, delta: float, copy: bool = False):
    """The shape with theta raised by delta (right-handed rotation about +x by -delta).

    Without ``copy`` the result shares its sub-shapes with the input (a location is added), so a face of
    the input moved the same way ``IsSame`` the matching face of the result.
    """
    tr = gp_Trsf()
    tr.SetRotation(X_AXIS, -delta)
    if copy:
        return BRepBuilderAPI_Transform(shape, tr, True).Shape()
    return shape.Moved(TopLoc_Location(tr))


def rotation_matrix(delta: float) -> np.ndarray:
    """3x3 matrix of ``rotate_theta``: (x, r sin t, r cos t) -> (x, r sin(t+d), r cos(t+d))."""
    c, s = math.cos(delta), math.sin(delta)
    return np.array([[1, 0, 0], [0, c, s], [0, -s, c]])


# ---------------------------------------------------------------------------------- inspection

def is_valid(shape) -> bool:
    return BRepCheck_Analyzer(shape).IsValid()


# Adaptive Gauss integration: the default VolumeProperties is ~1e-3 off on these B-spline faces
GPROP_EPS = 1e-9


def volume(shape, eps: float = GPROP_EPS) -> float:
    p = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, p, eps)
    return p.Mass()


def area(shape, eps: float = GPROP_EPS) -> float:
    p = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, p, eps)
    return p.Mass()


def centroid(shape, eps: float = GPROP_EPS) -> np.ndarray:
    p = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, p, eps)
    return np.array(_xyz(p.CentreOfMass()))


def max_tolerance(shape) -> float:
    tol = 0.0
    for e in explore(shape, "edge"):
        tol = max(tol, BRep_Tool.Tolerance_s(e))
    for v in explore(shape, "vertex"):
        tol = max(tol, BRep_Tool.Tolerance_s(v))
    return tol


def counts(shape) -> dict[str, int]:
    return {k: len(explore(shape, k)) for k in ("solid", "face", "edge", "vertex")}
