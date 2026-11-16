"""Start the GUI: ``tb3-gui [case folder]`` or ``python -m tblade3.gui.app [case folder]``."""
from __future__ import annotations

import sys

import pyqtgraph as pg
from PySide6.QtWidgets import QApplication


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else [str(a) for a in argv]
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("T-Blade3")
    pg.setConfigOptions(antialias=True)

    from .main_window import MainWindow     # after QApplication exists (PyVista needs it)

    window = MainWindow()
    window.show()
    if argv:
        window.open_case(argv[0])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
