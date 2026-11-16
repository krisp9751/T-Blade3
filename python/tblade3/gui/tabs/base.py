"""Base class of the editor tabs.

A tab shows one blade row (the row selected in the main window). The main window tells it when
the row, its inputs or its geometry change. A hidden tab only notes that it is stale and
refreshes when it is shown, so edits stay fast however many tabs exist.

To write a tab: build the widgets in ``__init__``, then override
    refresh_inputs()    show the current input values (tables, switches, input curves)
    refresh_geometry()  show results of the last successful T-Blade3 run (may be None)
Read the data from ``self.row`` (a BladeRow or None) and ``self.geometry``. Make every change
through ``self.controller`` (set_value, set_attribute, edit) so that it is undoable and all views
stay in step; never modify the model directly.
"""
from __future__ import annotations

from PySide6.QtWidgets import QWidget

from ...geometry import Geometry
from ...model import BladeRow
from ..controller import Controller


class RowTab(QWidget):
    title = "Tab"

    def __init__(self, controller: Controller, parent: QWidget | None = None):
        super().__init__(parent)
        self.controller = controller
        self.row_id: str | None = None
        self._stale_inputs = True
        self._stale_geometry = True

    # -- data -------------------------------------------------------------------------------
    @property
    def row(self) -> BladeRow | None:
        case = self.controller.case
        return case.rows.get(self.row_id) if case is not None and self.row_id is not None else None

    @property
    def geometry(self) -> Geometry | None:
        row = self.row
        return row.geometry if row is not None else None

    # -- called by the main window ----------------------------------------------------------
    def set_row(self, row_id: str | None) -> None:
        self.row_id = row_id
        self.row_changed()
        self.notify_inputs()
        self.notify_geometry()

    def notify_inputs(self) -> None:
        if self.isVisible():
            self._stale_inputs = False
            self.refresh_inputs()
        else:
            self._stale_inputs = True

    def notify_geometry(self) -> None:
        if self.isVisible():
            self._stale_geometry = False
            self.refresh_geometry()
        else:
            self._stale_geometry = True

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._stale_inputs:
            self._stale_inputs = False
            self.refresh_inputs()
        if self._stale_geometry:
            self._stale_geometry = False
            self.refresh_geometry()

    # -- to override ------------------------------------------------------------------------
    def row_changed(self) -> None:
        """The selected row changed: pass ``self.row_id`` on to bound widgets (set_row)."""

    def refresh_inputs(self) -> None:
        """Show the current input values."""

    def refresh_geometry(self) -> None:
        """Show the results of the last successful run (``self.geometry`` may be None)."""

    def apply_theme(self) -> None:
        """The light/dark theme changed: restyle plots."""
