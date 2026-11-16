"""Structural edits (adding or removing table rows) as undoable controller edits.

Value changes go through ``controller.set_value``. Anything that changes how many parameters
exist goes through ``controller.edit`` with a pair of functions; the helpers here build those
pairs for the common tables so every tab does it the same way.
"""
from __future__ import annotations

from collections.abc import Callable

import numpy as np

from ..io.maininput import ControlTable
from ..io.spancontrol import Table
from .controller import Controller

_KEEP = object()


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


# -- tables of the auxiliary file (spancontrol.Table: first column span, one row per control point) --

def replace_table_data(controller: Controller, row_id: str, table_get: Callable[[], Table], data: np.ndarray,
                       text: str) -> None:
    """Replace all rows of a spancontrol Table (undoable)."""
    old, new = table_get().data.copy(), np.array(data, dtype=float)

    def apply(values: np.ndarray) -> None:
        table_get().data = values.copy()

    controller.edit(row_id, text, lambda: apply(new), lambda: apply(old))


def insert_table_row(controller: Controller, row_id: str, table_get: Callable[[], Table], index: int,
                     what: str) -> int:
    """Add a row after row ``index`` of a spancontrol Table, halfway to the next one (undoable).

    An empty table gets a row at the hub and one at the tip with zero values; a single row is
    copied to the other end of the span. Returns the index of the new row.
    """
    data = table_get().data
    n, ncol = data.shape
    if n == 0:
        new = np.zeros((2, ncol))
        new[:, 0] = [0.0, 1.0]
        added = 1
    elif n == 1:
        other = data[0].copy()
        other[0] = 1.0 if data[0, 0] < 1.0 else 0.0
        new = np.vstack([data, other])
        new = new[np.argsort(new[:, 0], kind="stable")]
        added = 1 if other[0] == 1.0 else 0
    else:
        i = min(max(index, 0), n - 2)
        new = np.insert(data, i + 1, 0.5 * (data[i] + data[i + 1]), axis=0)
        added = i + 1
    replace_table_data(controller, row_id, table_get, new, f"Add a {what} control point")
    return added


def remove_table_row(controller: Controller, row_id: str, table_get: Callable[[], Table], index: int,
                     what: str) -> None:
    """Remove row ``index`` of a spancontrol Table (undoable)."""
    data = table_get().data
    if 0 <= index < len(data):
        replace_table_data(controller, row_id, table_get, np.delete(data, index, axis=0),
                           f"Remove a {what} control point")


# -- several inputs at once --------------------------------------------------------------------

def set_inputs(controller: Controller, row_id: str, text: str, main: dict[str, object] | None = None,
               aux=_KEEP) -> None:
    """Set attributes of the row's main input and optionally replace its auxiliary input, as one undo step.

    Use it for a switch that needs other data to change with it (a table the new value reads, or
    the auxiliary file parsed for the new switches). Values are stored as given; pass new objects,
    not ones that stay in use elsewhere.
    """
    main = dict(main or {})
    row = controller.row(row_id)
    old_main = {key: getattr(row.main, key) for key in main}
    old_aux = row.aux

    def apply(values: dict[str, object], new_aux) -> None:
        r = controller.row(row_id)
        for key, value in values.items():
            setattr(r.main, key, value)
        if new_aux is not _KEEP:
            r.aux = new_aux

    undo_aux = old_aux if aux is not _KEEP else _KEEP
    controller.edit(row_id, text, lambda: apply(main, aux), lambda: apply(old_main, undo_aux))
