"""Structural edits (adding or removing table rows) as undoable controller edits.

Value changes go through ``controller.set_value``. Anything that changes how many parameters
exist goes through ``controller.edit`` with a pair of functions; the helpers here build those
pairs for the common tables so every tab does it the same way.
"""
from __future__ import annotations

from collections.abc import Callable

import numpy as np

from ..io.maininput import ControlTable
from .controller import Controller


def _set_control_table(table: ControlTable, span: np.ndarray, values: dict[str, np.ndarray]) -> None:
    table.span = span.copy()
    table.values = {key: v.copy() for key, v in values.items()}


def replace_control_table(controller: Controller, row_id: str, table_get: Callable[[], ControlTable], text: str,
                          span: np.ndarray, values: dict[str, np.ndarray]) -> None:
    """Replace the control points of a spanwise control table (undoable)."""
    table = table_get()
    old_span, old_values = table.span.copy(), {key: v.copy() for key, v in table.values.items()}
    controller.edit(row_id, text,
                    lambda: _set_control_table(table_get(), span, values),
                    lambda: _set_control_table(table_get(), old_span, old_values))


def insert_control_point(controller: Controller, row_id: str, table_get: Callable[[], ControlTable], index: int,
                         what: str) -> None:
    """Add a control point after row ``index``, halfway to the next one (values interpolated).

    An empty table gets four evenly spaced points with zero values.
    """
    table = table_get()
    n = len(table)
    if n == 0:
        span = np.linspace(0.0, 1.0, 4)
        values = {key: np.zeros(4) for key in table.values}
    elif n == 1:
        new = 1.0 if table.span[0] < 1.0 else 0.0
        order = np.argsort([table.span[0], new])
        span = np.array([table.span[0], new])[order]
        values = {key: np.array([v[0], v[0]])[order] for key, v in table.values.items()}
    else:
        i = min(max(index, 0), n - 2)
        span = np.insert(table.span, i + 1, 0.5 * (table.span[i] + table.span[i + 1]))
        values = {key: np.insert(v, i + 1, 0.5 * (v[i] + v[i + 1])) for key, v in table.values.items()}
    replace_control_table(controller, row_id, table_get, f"Add a {what} control point", span, values)


def remove_control_point(controller: Controller, row_id: str, table_get: Callable[[], ControlTable], index: int,
                         what: str) -> None:
    """Remove control point ``index`` (undoable)."""
    table = table_get()
    if not 0 <= index < len(table):
        return
    span = np.delete(table.span, index)
    values = {key: np.delete(v, index) for key, v in table.values.items()}
    replace_control_table(controller, row_id, table_get, f"Remove a {what} control point", span, values)
