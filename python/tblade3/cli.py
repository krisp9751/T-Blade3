"""Command line interface: ``tb3 run | params | export-csm | gui``."""
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
        path = export_csm(case, args.out, all_parameters=args.all)
        print(f"wrote {path}")
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
    csm.set_defaults(func=cmd_export_csm)

    gui = sub.add_parser("gui", help="open the GUI")
    gui.add_argument("case", nargs="?", type=Path)
    gui.set_defaults(func=cmd_gui)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (TBlade3Error, FileNotFoundError, KeyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
