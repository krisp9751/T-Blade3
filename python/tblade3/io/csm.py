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


def csm_text(case: Case, all_parameters: bool = False, ncp: int = 33) -> str:
    """The .csm script. Input files are referenced relative to the script ($$/), so save it in the case folder.

    ``all_parameters`` exports every udpTblade argument, not only those with design variables.
    """
    multi = len(case.rows) > 1
    lines = ["# T-Blade3 case exported by the tblade3 Python package.",
             "# Keep this file next to the 3dbgbinput / spancontrolinputs files it names.", ""]
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
        block = [f"UDPARG    tblade    {'ncp':<22} {ncp}"]
        block += [f"UDPARG    tblade    {arg:<22} {prefix + arg}" for arg in vectors]
        block.append(f"UDPRIM    tblade    {'filename':<22} $$/{row.main_name} \\")
        block.append(f"                    {'auxname':<22} $$/{row.aux_name or f'spancontrolinputs.{rid}.dat'}")
        blocks.append("\n".join(block))
    lines.append("\n\n".join(blocks))
    lines += ["", "END", ""]
    return "\n".join(lines)


def export_csm(case: Case, path: str | Path | None = None, all_parameters: bool = False) -> Path:
    """Write the .csm (default: <case folder>/<casename>.csm) together with the current input files."""
    if path is None:
        if case.folder is None:
            raise ValueError("no path given and the case has no folder")
        name = next(iter(case.rows.values())).main.casename
        path = case.folder / f"{name}.csm"
    path = Path(path)
    case.save(path.parent)
    path.write_text(csm_text(case, all_parameters))
    return path
