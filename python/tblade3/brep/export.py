"""Write the bodies of a blade row: STEP AP242 (names on bodies and faces), OpenCASCADE .brep, .hgeom.

    from tblade3.brep import build, export
    row = build.build_row(geometry)
    paths = export.export_row(row, "out", "rotor", bodies=("solid", "passage"), formats=("step", "brep"))

File names: ``<stem>.step`` (all chosen bodies, each a named solid, every face named by its role),
``<stem>_<body>.brep`` (one per body; .brep carries no names), ``<stem>.hgeom`` (everything, see
``hgeom``).
"""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from OCP.BRepTools import BRepTools
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static
from OCP.STEPCAFControl import STEPCAFControl_Reader, STEPCAFControl_Writer
from OCP.STEPControl import STEPControl_AsIs
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDocStd import TDocStd_Document
from OCP.XCAFApp import XCAFApp_Application
from OCP.XCAFDoc import XCAFDoc_DocumentTool

from . import occ
from .build import BODY_NAMES, RowBrep

FORMATS = ("hgeom", "step", "brep")
DEFAULT_BODIES = ("blade", "hub_wedge", "passage", "solid")


def export_row(row: RowBrep, out_dir: str | Path, stem: str, bodies: Iterable[str] = DEFAULT_BODIES,
               formats: Iterable[str] = FORMATS, sensitivities=None, source: dict | None = None) -> list[Path]:
    """Write the chosen bodies in the chosen formats; returns the files written.

    ``sensitivities``: a ``sensitivity.Sensitivities`` to store in the .hgeom (ignored by the others).
    ``source``: provenance for the .hgeom (input file texts, design variables; see ``hgeom.write``).
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    bodies = list(bodies)
    for b in bodies:
        if b not in BODY_NAMES:
            raise ValueError(f"unknown body {b!r} (choose from {', '.join(BODY_NAMES)})")
    formats = list(formats)
    for f in formats:
        if f not in FORMATS:
            raise ValueError(f"unknown format {f!r} (choose from {', '.join(FORMATS)})")
    written = []
    if "step" in formats:
        written.append(write_step(row, out / f"{stem}.step", bodies))
    if "brep" in formats:
        for b in bodies:
            p = out / f"{stem}_{b}.brep"
            if not BRepTools.Write_s(row.bodies[b], str(p)):
                raise OSError(f"could not write {p}")
            written.append(p)
    if "hgeom" in formats:
        from . import hgeom
        written.append(hgeom.write(row, out / f"{stem}.hgeom", bodies=bodies, sensitivities=sensitivities,
                                   source=source))
    return written


def quiet() -> None:
    """Silence OpenCASCADE's console printers (the STEP translators print statistics)."""
    from OCP.Message import Message
    from OCP.Message import Message_Gravity
    for p in _printers():
        p.SetTraceLevel(Message_Gravity.Message_Fail)


def _printers():
    from OCP.Message import Message
    msgr = Message.DefaultMessenger_s()
    try:
        return list(msgr.Printers())
    except Exception:
        return []


def _name(label, text: str) -> None:
    TDataStd_Name.Set_s(label, TCollection_ExtendedString(text))


def write_step(row: RowBrep, path: str | Path, bodies: Iterable[str] = DEFAULT_BODIES) -> Path:
    """STEP AP242: each body a named shape, each face named by its role (XCAF names)."""
    path = Path(path)
    quiet()
    doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
    XCAFApp_Application.GetApplication_s().InitDocument(doc)
    tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    # each body is copied, so faces shared between bodies become separate STEP entities that can each
    # carry their name
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
    named = []
    for b in bodies:
        cp = BRepBuilderAPI_Copy(row.bodies[b], True, False)
        shape = cp.Shape()
        label = tool.AddShape(shape, False)
        _name(label, b)
        for f in occ.explore(row.bodies[b], "face"):
            role = row.role(f)
            if role:
                named += [(g, role) for g in occ.from_list(cp.Modified(f))]
    Interface_Static.SetCVal_s("write.step.schema", "AP242DIS")
    Interface_Static.SetCVal_s("write.step.unit", "MM")
    writer = STEPCAFControl_Writer()
    writer.SetNameMode(True)
    if not writer.Transfer(doc, STEPControl_AsIs):
        raise RuntimeError("STEP transfer failed")
    # face names: XCAF does not write sub-shape names, so name the ADVANCED_FACE entities directly
    from OCP.STEPConstruct import STEPConstruct
    from OCP.TCollection import TCollection_HAsciiString
    fp = writer.ChangeWriter().WS().TransferWriter().FinderProcess()
    for f, role in named:
        ent = STEPConstruct.FindEntity_s(fp, f)
        if ent is not None:
            ent.SetName(TCollection_HAsciiString(role))
    if writer.Write(str(path)) != IFSelect_RetDone:
        raise OSError(f"could not write {path}")
    return path


def read_step(path: str | Path) -> dict[str, tuple[object, dict[str, list]]]:
    """Read a STEP file written by ``write_step``: {body name: (shape, {face name: [faces]})}."""
    quiet()
    doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
    XCAFApp_Application.GetApplication_s().InitDocument(doc)
    Interface_Static.SetIVal_s("read.stepcaf.subshapes.name", 1)
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    if reader.ReadFile(str(path)) != IFSelect_RetDone or not reader.Transfer(doc):
        raise OSError(f"could not read {path}")
    tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    from OCP.collections import Sequence_TDF_Label as TDF_LabelSequence
    labels = TDF_LabelSequence()
    tool.GetFreeShapes(labels)
    out = {}
    for i in range(1, labels.Length() + 1):
        lab = labels.Value(i)
        shape = tool.GetShape_s(lab)
        faces: dict[str, list] = {}
        subs = TDF_LabelSequence()
        tool.GetSubShapes_s(lab, subs)
        for j in range(1, subs.Length() + 1):
            sl = subs.Value(j)
            faces.setdefault(_label_name(sl), []).append(tool.GetShape_s(sl))
        out[_label_name(lab)] = (shape, faces)
    return out


def _label_name(label) -> str:
    attr = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), attr):
        return attr.Get().ToExtString()
    return ""


def read_brep(path: str | Path):
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Shape
    shape = TopoDS_Shape()
    if not BRepTools.Read_s(shape, str(path), BRep_Builder()):
        raise OSError(f"could not read {path}")
    return shape
