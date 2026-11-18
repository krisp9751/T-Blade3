"""Start the GUI: ``tblade [case folder]`` (also ``tb3-gui`` or ``python -m tblade3.gui.app``)."""
from __future__ import annotations

import argparse
import sys

import pyqtgraph as pg
from PySide6.QtWidgets import QApplication


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else [str(a) for a in argv]
    parser = argparse.ArgumentParser(prog="tblade", description="T-Blade3 blade geometry GUI")
    parser.add_argument("case", nargs="?", help="case folder to open")
    args = parser.parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("T-Blade3")
    pg.setConfigOptions(antialias=True)

    from .main_window import MainWindow     # after QApplication exists (PyVista needs it)

    window = MainWindow()
    window.show()
    if args.case:
        window.open_case(args.case)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
