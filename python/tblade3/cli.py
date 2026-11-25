"""Command line interface: ``tb3 run | params | export-csm | export | gui``."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from .errors import TBlade3Error
from .model import Case


def _apply_settings(case: Case, args) -> None:
    for item in args.set or []:
        name, sep, value = item.partition("=")
        if not sep:
            raise SystemExit(f"--set expects name=value, got {item!r}")
        case.set(name.strip(), float(value))
    if getattr(args, "dv_file", None):
        case.dv.values = np.loadtxt(args.dv_file, ndmin=1)


def cmd_run(args) -> int:
    with Case.load(args.case, engine=args.engine) as case:
        _apply_settings(case, args)
        geos = case.build(derivatives=args.derivs)
        out: dict[str, np.ndarray] = {}
        for rid, geo in geos.items():
            out[f"row{rid}_sections"] = geo.sections
            if geo.meanlines is not None:
                out[f"row{rid}_meanlines"] = geo.meanlines
            print(f"row {rid}: {geo.nsec} sections x {geo.npt} points")
        if args.derivs:
            names = args.wrt or case.dv.names
            for rid, jac in case.jacobian(names).items():
                out[f"row{rid}_jacobian"] = jac
            out["dv_names"] = np.array(names)
            out["dv_values"] = np.array([case.get(n) for n in names])
            out["dv_methods"] = np.array([case._split(n)[0].derivative_method(case._split(n)[1]) for n in names])
            print(f"derivatives with respect to {len(names)} parameter(s)")
        if args.save_inputs:
            case.save(args.save_inputs)
        if args.out:
            np.savez_compressed(args.out, **out)
            print(f"wrote {args.out}")
    return 0


def cmd_params(args) -> int:
    with Case.load(args.case, engine="executable") as case:
        for name, p in case.parameters().items():
            if args.dv and not p.is_dv:
                continue
            if args.filter and args.filter not in name:
                continue
            flags = ("DV " if p.is_dv else "   ") + ("analytic" if p.deriv else "        ")
            bounds = f"[{p.lower}, {p.upper}]" if p.is_dv else ""
            print(f"{name:<40} {p.value:>22.14g}  {flags}  {bounds}")
    return 0


def cmd_export_csm(args) -> int:
    from .io.csm import export_csm
    with Case.load(args.case, engine="executable") as case:
        for name in args.dv or []:
            case.dv.add(name)
        path = export_csm(case, args.out, all_parameters=args.all, hubwedge=args.hubwedge,
                          bore_radius=args.bore_radius, dump_step=args.dump_step)
        print(f"wrote {path}")
    return 0


def cmd_export(args) -> int:
    from .export_geometry import ExportRequest, export_built_row, local_names
    with Case.load(args.case) as case:
        if args.row is not None and args.row not in case.rows:
            raise ValueError(f"the case has no row {args.row!r} (rows: {', '.join(case.rows)})")
        rows = [args.row] if args.row is not None else list(case.rows)
        if args.stem and len(rows) > 1:
            raise ValueError("--stem names one file set; with several rows choose one with --row")
        formats = tuple(args.formats) if args.formats else ("hgeom", "step", "brep")
        name = next(iter(case.rows.values())).main.casename
        for rid in rows:
            stem = args.stem or (name if len(case.rows) == 1 else f"{name}_row{rid}")
            request = ExportRequest(args.out, stem, tuple(args.bodies) if args.bodies else None, formats,
                                    args.bore_radius, args.x_inlet, args.x_outlet,
                                    tuple(local_names(case, rid, args.sens or [])))
            row = case.rows[rid]
            files, notes = export_built_row(case, row, row.build(derivatives=False), request)
            print(f"row {rid}:")
            for f in files:
                print(f"  wrote {f}")
            for note in notes:
                print(f"  note: {note}")
    return 0


def cmd_gui(args) -> int:
    from .gui.app import main as gui_main
    return gui_main([args.case] if args.case else [])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tb3", description="T-Blade3 from the command line")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="build the geometry of a case")
    run.add_argument("case", type=Path, help="case folder (or one 3dbgbinput.<row>.dat)")
    run.add_argument("--set", action="append", metavar="NAME=VALUE", help="set a parameter, e.g. row2.sweep[4]=0.02")
    run.add_argument("--dv-file", type=Path, help="text file with one value per design variable")
    run.add_argument("--derivs", action="store_true", help="also compute d(sections)/d(design variables)")
    run.add_argument("--wrt", nargs="+", metavar="NAME", help="parameters to differentiate (default: design variables)")
    run.add_argument("--out", type=Path, help="write results to this .npz file")
    run.add_argument("--save-inputs", type=Path, help="write the modified input files to this folder")
    run.add_argument("--engine", choices=("library", "executable"), default=None)
    run.set_defaults(func=cmd_run)

    params = sub.add_parser("params", help="list parameter names and values")
    params.add_argument("case", type=Path)
    params.add_argument("--dv", action="store_true", help="only design variables")
    params.add_argument("--filter", help="only names containing this text")
    params.set_defaults(func=cmd_params)

    csm = sub.add_parser("export-csm", help="write a .csm script with DESPMTRs for ESP/CAPS")
    csm.add_argument("case", type=Path)
    csm.add_argument("--out", type=Path, help="default: <case>/<casename>.csm")
    csm.add_argument("--dv", nargs="+", metavar="NAME", help="extra design variables to flag")
    csm.add_argument("--all", action="store_true", help="export every udpTblade argument")
    csm.add_argument("--hubwedge", action="store_true",
                     help="add ESP's hubwedge primitive, a UNION with the blade and a bore (like tblade_rotor_hubwedge.csm)")
    csm.add_argument("--bore-radius", type=float, default=12.7, help="bore radius with --hubwedge (default 12.7)")
    csm.add_argument("--dump-step", metavar="NAME", help="end the script with DUMP $$/NAME (e.g. rotor.step)")
    csm.set_defaults(func=cmd_export_csm)

    exp = sub.add_parser("export", help="write the B-Rep of a case (hgeom, STEP, BREP)")
    exp.add_argument("case", type=Path, help="case folder (or one 3dbgbinput.<row>.dat)")
    exp.add_argument("-o", "--out", type=Path, required=True, help="output folder")
    exp.add_argument("--row", help="row id (default: every row)")
    exp.add_argument("--stem", help="file name stem (default: the case name, with _row<id> for several rows)")
    exp.add_argument("--bodies", nargs="+", choices=("blade", "hub_wedge", "passage", "solid", "assembly"), help="bodies to write (default: blade hub_wedge passage solid)")
    exp.add_argument("--formats", nargs="+", choices=("hgeom", "step", "brep"), help="default: all three")
    exp.add_argument("--bore-radius", type=float, help="radius of the bore (default: from the hub)")
    exp.add_argument("--x-inlet", type=float, help="axial position of the inlet plane (default: from the blade)")
    exp.add_argument("--x-outlet", type=float, help="axial position of the outlet plane (default: from the blade)")
    exp.add_argument("--sens", nargs="+", metavar="NAME", help="parameters whose sensitivities are stored (hgeom)")
    exp.set_defaults(func=cmd_export)

    gui = sub.add_parser("gui", help="open the GUI")
    gui.add_argument("case", nargs="?", type=Path)
    gui.set_defaults(func=cmd_gui)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (TBlade3Error, FileNotFoundError, KeyError, ValueError, NotImplementedError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
