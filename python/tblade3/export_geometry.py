"""Build and write the B-Rep of one blade row (shared by ``tb3 export`` and the GUI's export dialog).

Needs OpenCASCADE (OCP); the imports are inside the functions so the rest of the package works without it.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import TBlade3Error
from .model import BladeRow, Case


@dataclass
class ExportRequest:
    """What to write for one row. ``None`` for a bore radius or x limit means the default of ``BuildOptions``."""
    out_dir: Path
    stem: str
    bodies: tuple[str, ...] | None = None       # default: export.DEFAULT_BODIES
    formats: tuple[str, ...] | None = None      # default: export.FORMATS
    bore_radius: float | None = None
    x_inlet: float | None = None
    x_outlet: float | None = None
    sensitivities: tuple[str, ...] = ()         # parameter names of the row (row-local, e.g. "sweep[4]")
    source: dict | None = None                  # provenance for the .hgeom; default: ``source_of`` at export time


def local_names(case: Case, row_id: str, names: list[str]) -> list[str]:
    """Parameter names as the row knows them: ``row2.sweep[4]`` -> ``sweep[4]``; other rows' names are dropped."""
    prefix = f"row{row_id}."
    out = []
    for name in names:
        if name.startswith("row") and "." in name:
            if not name.startswith(prefix):
                continue
            name = name[len(prefix):]
        out.append(name)
    return out


def source_of(case: Case, row: BladeRow) -> dict:
    """Provenance stored in the .hgeom: the row's input files and the case's design variables."""
    return {"files": row.files(), "design_variables": dict(zip(case.dv.names, map(float, case.dv.values)))}


def export_built_row(case: Case, row: BladeRow, geometry, request: ExportRequest) -> tuple[list[Path], list[str]]:
    """Build the B-Rep from ``geometry`` and write it. Returns (files written, notes for the user).

    Raises ValueError / NotImplementedError / TBlade3Error with a readable message.
    """
    try:
        from .brep import build, export
    except ImportError as exc:
        raise TBlade3Error(f"B-Rep export needs OpenCASCADE (the OCP package): {exc}") from exc
    notes: list[str] = []
    formats = tuple(request.formats or export.FORMATS)
    options = build.BuildOptions(bore_radius=request.bore_radius, x_inlet=request.x_inlet, x_outlet=request.x_outlet)
    brep = build.build_row(geometry, options)
    notes.extend(brep.notes)
    sens = None
    if request.sensitivities:
        from .brep import sensitivity
        sens = sensitivity.compute(row, brep, list(request.sensitivities))
    files = export.export_row(brep, request.out_dir, request.stem,
                              bodies=request.bodies or export.DEFAULT_BODIES, formats=formats,
                              sensitivities=sens, source=request.source or source_of(case, row))
    return files, notes
