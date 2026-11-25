"""Export a case as an OpenCSM (.csm) script for ESP / CAPS.

Each blade row becomes one ``UDPRIM tblade`` that reads the row's T-Blade3 input files. The
udpTblade arguments that hold design variables are declared as DESPMTRs, so ESP sees the same
design variables as the Python API. An argument is a whole vector (e.g. all sweep control points),
so flagging one control point exports its whole vector.
"""
from __future__ import annotations

from pathlib import Path

from ..model import BladeRow, Case


def _udp_vectors(row: BladeRow, all_parameters: bool) -> dict[str, list[float]]:
    """udpTblade argument name -> current values, for arguments holding at least one design variable."""
    vectors: dict[str, dict[int, float]] = {}
    wanted: set[str] = set()
    for p in row.parameters.values():
        if p.udp is None:
            continue
        arg, index = p.udp
        vectors.setdefault(arg, {})[index] = p.value
        if p.is_dv or all_parameters:
            wanted.add(arg)
    return {arg: [vals[i] for i in sorted(vals)] for arg, vals in vectors.items() if arg in wanted}


BORE_RADIUS = 12.7                      # as in tblade_rotor_hubwedge.csm
BORE_X = (-100.0, 1000.0)               # axial extent of the bore cylinder, long enough to cut through any row


def csm_text(case: Case, all_parameters: bool = False, ncp: int = 33, hubwedge: bool = False,
             bore_radius: float = BORE_RADIUS, dump_step: str | None = None) -> str:
    """The .csm script. Input files are referenced relative to the script ($$/), so save it in the case folder.

    ``all_parameters`` exports every udpTblade argument, not only those with design variables.
    ``hubwedge`` follows ESP's tblade_rotor_hubwedge.csm: per row, ESP's ``hubwedge`` primitive and the blade are
    united and a bore of ``bore_radius`` is subtracted. ``dump_step`` (a file name) adds a ``DUMP`` of the result.
    """
    multi = len(case.rows) > 1
    lines = ["# T-Blade3 case exported by the tblade3 Python package.",
             "# Keep this file next to the 3dbgbinput / spancontrolinputs files it names."]
    if hubwedge:
        lines += ["# Note: ESP's hubwedge surface is the revolved hub-section meanline, not the hub streamline.",
                  "# tblade3.brep (tb3 export) builds the exact version."]
    lines.append("")
    blocks = []
    for rid, row in case.rows.items():
        prefix = f"r{rid}_" if multi else ""
        vectors = _udp_vectors(row, all_parameters)
        for arg, values in vectors.items():
            lines.append(f"DIMENSION {prefix + arg:<22} 1 {len(values)}")
        for arg, values in vectors.items():
            lines.append(f"DESPMTR   {prefix + arg:<22} \"" + " ".join(f"{v:.16g};" for v in values) + "\"")
        if vectors:
            lines.append("")
        block = []
        for prim in (("hubwedge", "tblade") if hubwedge else ("tblade",)):
            block.append(f"UDPARG    {prim:<9} {'ncp':<22} {ncp}")
            block += [f"UDPARG    {prim:<9} {arg:<22} {prefix + arg}" for arg in vectors]
            if prim == "hubwedge":
                block.append(f"UDPRIM    hubwedge  {'filename':<22} $$/{row.main_name} \\")
                block.append(f"                    {'auxname':<22} $$/{row.aux_name or f'spancontrolinputs.{rid}.dat'}")
                block.append("")
        block.append(f"UDPRIM    tblade    {'filename':<22} $$/{row.main_name} \\")
        block.append(f"                    {'auxname':<22} $$/{row.aux_name or f'spancontrolinputs.{rid}.dat'}")
        if hubwedge:
            block += ["", "UNION", "", f"CYLINDER  {BORE_X[0]:g} 0 0 {BORE_X[1]:g} 0 0 {bore_radius:g}", "SUBTRACT"]
        blocks.append("\n".join(block))
    lines.append("\n\n".join(blocks))
    if dump_step:
        lines += ["", f"DUMP      $$/{dump_step}"]
    lines += ["", "END", ""]
    return "\n".join(lines)


def export_csm(case: Case, path: str | Path | None = None, all_parameters: bool = False, hubwedge: bool = False,
               bore_radius: float = BORE_RADIUS, dump_step: str | None = None) -> Path:
    """Write the .csm (default: <case folder>/<casename>.csm) together with the current input files."""
    if path is None:
        if case.folder is None:
            raise ValueError("no path given and the case has no folder")
        name = next(iter(case.rows.values())).main.casename
        path = case.folder / f"{name}.csm"
    path = Path(path)
    folder = case.folder
    case.save(path.parent)              # the script names the input files next to it
    if folder is not None:
        case.folder = folder            # exporting elsewhere does not move the case
    path.write_text(csm_text(case, all_parameters, hubwedge=hubwedge, bore_radius=bore_radius, dump_step=dump_step))
    return path
