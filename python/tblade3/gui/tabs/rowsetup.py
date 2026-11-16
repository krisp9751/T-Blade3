"""Row setup tab: identity of the row, blade count, scale, and every switch of the main input.

Several switches decide which tables and files T-Blade3 reads (source/3dbgb.f90, readinput.f90).
``change_switch`` makes a switch change together with what the new value needs, as one undo
step: the auxiliary file is parsed again for the new switches (so a NACA block that was ignored
becomes editable, and the other way round), and missing data gets sensible defaults. A combination
that T-Blade3 is known to reject is refused with a message in the log instead.
"""
from __future__ import annotations

import copy

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

from ...errors import InputFormatError
from ...io.maininput import ANGLE_SPLINES, CLUSTERING, THICKNESS_DISTRIBUTIONS, ControlTable
from ...io.spancontrol import (ControlInputs, SpanControl, Table, NACA_COLUMNS, curvature_columns, format_spancontrol,
                               parse_spancontrol)
from ...model import BladeRow
from ..controller import Controller
from ..edits import set_inputs
from ..widgets import ChoiceBox, StackingAxisEdit, ValueEdit, decode_stacking_axis
from .base import RowTab

ANGLE_SWITCHES = {0: "Axial angles (beta_z)", 1: "Radial angles (beta_r)", 2: "Axial inlet, radial exit",
                  3: "Radial inlet, axial exit", 4: "Wing (angles from the spanwise splines)"}
ANGLE_SPLINE_TEXT = {"": "From the section table",
                     "inletspline": "Inlet angle from its spanwise spline",
                     "outletspline": "Exit angle from its spanwise spline",
                     "inoutspline": "Inlet and exit angles from spanwise splines",
                     "inci_dev_spline": "Section table plus incidence/deviation splines"}
assert set(ANGLE_SPLINE_TEXT) == set(ANGLE_SPLINES)
SWITCH_TEXT = {"angle_switch": "the angle switch", "angle_spline": "the angle splines",
               "curvature_control": "the camber definition", "spanwise_spline": "the auxiliary file format",
               "thickness_distribution": "the thickness distribution",
               "thickness_multiplier": "the thickness multiplier",
               "le_spline": "the LE spline switch", "chord_switch": "the chord switch",
               "true_lean_sweep": "the lean/sweep switch", "clustering_switch": "the point clustering",
               "variable_stacking": "variable stacking", "units": "the units"}
CHOICES: dict[str, dict] = {
    "angle_switch": ANGLE_SWITCHES,
    "angle_spline": ANGLE_SPLINE_TEXT,
    "curvature_control": {0: "No: camber from the inlet and exit angles", 1: "Yes: curvature control points"},
    "spanwise_spline": {True: "spancontrolinputs (spanwise splines)", False: "controlinputs (a table per section)"},
    "thickness_distribution": THICKNESS_DISTRIBUTIONS,
    "thickness_multiplier": {0: "No", 1: "Yes: spline multiplier from the auxiliary file"},
    "le_spline": {0: "No: elliptical LE", 1: "Yes: spline LE"},
    "chord_switch": {0: "Computed from the LE and TE curves", 1: "From the section table (chord column)",
                     2: "Computed, times the spanwise chord multiplier"},
    "true_lean_sweep": {0: "Axial sweep, tangential lean", 1: "True sweep and lean"},
    "clustering_switch": {k: v.capitalize() for k, v in CLUSTERING.items()},
    "variable_stacking": {0: "No: one stacking axis for all sections", 1: "Yes: stk_u, stk_v of each section"},
    "units": {"mm": "mm", "cm": "cm", "m": "m"},
}
# Spanwise tables an angle-spline mode reads (3dbgb.f90): they must have control points.
_SPLINE_TABLES = {"inletspline": ("in_beta",), "outletspline": ("out_beta",), "inoutspline": ("in_beta", "out_beta"),
                  "inci_dev_spline": ("in_beta", "out_beta")}
_AUX_SWITCHES = ("curvature_control", "thickness_distribution", "thickness_multiplier", "le_spline")


# --------------------------------------------------------------------------------------------
# Switch changes with the data they need
# --------------------------------------------------------------------------------------------

def _section_span(row: BladeRow) -> np.ndarray:
    """Span fraction of each section: from the last run, else evenly spaced."""
    n = row.main.n_streamlines
    geo = row.geometry
    span = geo.section_table.get("span") if geo is not None else None
    if span is not None and len(span) == n and np.all(np.isfinite(span)):
        return np.asarray(span, dtype=float)
    return np.linspace(0.0, 1.0, n)


def default_spancontrol(row: BladeRow) -> SpanControl:
    """A spancontrolinputs file with a zero-curvature table at hub and tip (straight camber-line curvature)."""
    columns = curvature_columns(7)
    data = np.zeros((2, len(columns)))
    data[:, 0] = [0.0, 1.0]
    data[:, 1:6] = [0.15, 0.25, 0.5, 0.75, 0.95]        # chordwise locations u2..u6, as in the example cases
    return SpanControl(casename=row.main.casename, row=row.main.row, ncp_chord=7, curvature=Table(columns, data))


def default_naca_table(row: BladeRow) -> Table:
    """Modified NACA control points at hub, mid and tip from the section table's t/c_max and umxthk."""
    m = row.main
    span = np.array([0.0, 0.5, 1.0])
    sec_span = _section_span(row)
    t_max = np.interp(span, sec_span, m.sections["tc_max"])
    u_max = np.interp(span, sec_span, m.umxthk) if np.all(m.umxthk > 0) else np.full(3, 0.4)
    data = np.column_stack([span, np.full(3, 5.5), u_max, t_max, 0.15 * t_max])   # LE radius index as in the examples
    return Table(list(NACA_COLUMNS), data)


def _default_control(row: BladeRow, attr: str, mode: str) -> ControlTable:
    """Four control points for an angle spline: the section-table angles, or zero increments."""
    span = np.linspace(0.0, 1.0, 4)
    column = "in_beta*" if attr == "in_beta" else "out_beta*"
    if mode == "inci_dev_spline":
        values = np.zeros(4)
    else:
        values = np.interp(span, _section_span(row), row.main.sections[attr])
    return ControlTable(span, {column: values})


def _reparse(aux: SpanControl, s: dict) -> SpanControl:
    """The auxiliary file read the way T-Blade3 reads it with switches ``s``. Raises InputFormatError."""
    return parse_spancontrol(format_spancontrol(aux), s["thickness_distribution"],
                             thickness_multiplier=s["thickness_multiplier"], le_spline=s["le_spline"])


def change_switch(controller: Controller, row_id: str, attr: str, value) -> str | None:
    """Change a switch of the row's main input with the data it needs, as one undo step.

    Returns None when the change was made, else the reason it was refused (also sent as a message).
    """
    row = controller.row(row_id)
    m = row.main
    if getattr(m, attr) == value:
        return None
    new: dict[str, object] = {attr: value}
    notes: list[str] = []

    def refuse(reason: str) -> str:
        controller.message.emit(f"Row {row_id}: {reason}")
        return reason

    s = {k: getattr(m, k) for k in (*_AUX_SWITCHES, "spanwise_spline", "clustering_switch", "angle_switch",
                                    "angle_spline")}
    s[attr] = value

    # -- combinations T-Blade3 rejects ---------------------------------------------------------
    if attr == "le_spline" and value:
        return refuse("the LE spline is not available in current T-Blade3 (readinput.f90 stops); it stays 0.")
    if attr in ("clustering_switch", "thickness_distribution") and s["clustering_switch"] == 4 \
            and s["thickness_distribution"] != 5:
        return refuse("elliptical clustering works only with the modified NACA thickness (bladegen.f90). "
                      "Choose another clustering first.")
    if attr in ("thickness_multiplier", "thickness_distribution") and s["thickness_multiplier"] \
            and s["thickness_distribution"] == 5:
        return refuse("the thickness multiplier cannot be used with the modified NACA thickness "
                      "(T-Blade3 stops in spanwise_variation.f90).")
    if attr in ("angle_switch", "angle_spline") and s["angle_switch"] == 4 and not s["angle_spline"]:
        return refuse("the wing option needs an angle spline (readinput.f90 rejects it without one). "
                      "Choose the angle splines first.")

    # -- the auxiliary file --------------------------------------------------------------------
    aux = row.aux
    new_aux = None                      # None: keep the current one
    needs_aux = any(s[k] for k in _AUX_SWITCHES)
    if attr == "spanwise_spline" and needs_aux:
        if value and not isinstance(aux, SpanControl):
            return refuse("spanwise splines need a spancontrolinputs file, which this row does not have.")
        if not value and not isinstance(aux, ControlInputs):
            return refuse(f"without spanwise splines T-Blade3 reads controlinputs.{row_id}.dat, which this row "
                          "does not have.")
    elif needs_aux:
        if aux is None:
            aux = new_aux = default_spancontrol(row)
            notes.append(f"created spancontrolinputs.{row_id}.dat with zero curvature")
        if isinstance(aux, SpanControl) and not s["spanwise_spline"]:
            new["spanwise_spline"] = s["spanwise_spline"] = True
            notes.append("switched to the spancontrolinputs file")
    if isinstance(aux, ControlInputs) and s["thickness_distribution"] == 5:
        return refuse("the modified NACA thickness needs a spancontrolinputs file; this row has a controlinputs "
                      "file.")
    if isinstance(aux, SpanControl):
        if s["thickness_distribution"] == 5 and "cur1" not in aux.curvature.columns:
            return refuse("the modified NACA thickness needs cur1 in the curvature table of spancontrolinputs "
                          "(older format).")
        try:
            new_aux = _reparse(aux, s)
        except InputFormatError:
            if s["thickness_distribution"] == 5:
                new_aux = copy.deepcopy(aux)
                new_aux.thickness, new_aux.thickness_switch = default_naca_table(row), 1
                notes.append("added modified NACA control points from t/c_max and umxthk")
            elif s["thickness_multiplier"] and needs_aux:
                return refuse("the thickness multiplier needs a thickness block (span, thk1, ...) in "
                              "spancontrolinputs; this row has none and there is no safe default.")
            # otherwise the file is not read with these switches: keep it as it is

    # -- tables the new value reads ------------------------------------------------------------
    if attr in ("angle_spline", "angle_switch"):
        for table in _SPLINE_TABLES.get(s["angle_spline"], ()):
            if len(getattr(m, table)) < 2:
                new[table] = _default_control(row, table, s["angle_spline"])
                notes.append(f"added four {table}* control points")
    if attr == "variable_stacking" and value:       # start from the stacking axis: the blade stays as it is
        u, v = decode_stacking_axis(m.stacking_axis)
        if not (np.all(m.stk_u == u) and np.all(m.stk_v == v)):
            new["stk_u"], new["stk_v"] = np.full(len(m.stk_u), float(u)), np.full(len(m.stk_v), float(v))
            notes.append(f"set stk_u = {u} and stk_v = {v} at every section, from the stacking axis")
    if attr == "chord_switch" and value == 2 and len(m.chord_multiplier) < 2:
        new["chord_multiplier"] = ControlTable(np.linspace(0.0, 1.0, 4), {"chord_multiplier": np.zeros(4)})
        notes.append("added four chord multiplier control points of 0 (no change of chord)")

    set_inputs(controller, row_id, f"Change {SWITCH_TEXT.get(attr, attr)}", new,
               **({} if new_aux is None else {"aux": new_aux}))
    if notes:
        controller.message.emit(f"Row {row_id}: " + "; ".join(notes) + ".")
    return None


def aux_requirement(row: BladeRow) -> str:
    """Plain-language summary of the auxiliary file T-Blade3 reads for the row's switches."""
    m = row.main
    rid = row.row_id
    if not any(getattr(m, k) for k in _AUX_SWITCHES):
        text = "With these switches T-Blade3 reads no auxiliary file."
    elif not m.spanwise_spline:
        text = f"T-Blade3 reads controlinputs.{rid}.dat (curvature and thickness control points per section)."
    else:
        blocks = ["curvature"]
        if m.thickness_distribution == 5:
            blocks.append("modified NACA thickness")
        elif m.thickness_multiplier or m.le_spline:
            blocks.append("thickness multiplier")
        text = f"T-Blade3 reads spancontrolinputs.{rid}.dat ({' and '.join(blocks)} blocks)."
    text += f" This row has {row.aux_name or 'no auxiliary file'}."
    analytic = m.spanwise_spline and m.curvature_control == 1 and m.thickness_distribution == 5
    text += (" Analytic derivatives: yes." if analytic else
             " Analytic derivatives need curvature control, the modified NACA thickness and spancontrolinputs; "
             "other parameters use finite differences.")
    return text


# --------------------------------------------------------------------------------------------
# The tab
# --------------------------------------------------------------------------------------------

def _note(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    label.setStyleSheet("color: palette(placeholder-text);")
    return label


class RowSetupTab(RowTab):
    title = "Row setup"

    def __init__(self, controller: Controller, parent: QWidget | None = None):
        super().__init__(controller, parent)
        self.boxes: dict[str, ChoiceBox] = {}
        self.notes: dict[str, QLabel] = {}

        def choice(attr: str) -> ChoiceBox:
            box = ChoiceBox(controller, attr, CHOICES[attr], f"Change {SWITCH_TEXT[attr]}",
                            commit=None if attr == "units" else
                            (lambda rid, value, attr=attr: change_switch(controller, rid, attr, value)))
            self.boxes[attr] = box
            return box

        def add(form: QFormLayout, label: str, widget: QWidget, note_key: str | None = None) -> None:
            if isinstance(widget, QComboBox):           # may shrink: long choices are elided, not clipped
                widget.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
                widget.setMinimumContentsLength(16)
                widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            form.addRow(label, widget)
            if note_key:
                self.notes[note_key] = _note()
                form.addRow(self.notes[note_key])

        # -- Identity -----------------------------------------------------------------------------
        self.casename_edit = QLineEdit()
        self.casename_edit.editingFinished.connect(self._casename_changed)
        self.row_label = QLabel()
        self.blades_edit = ValueEdit(controller, "n_blades")
        self.scale_edit = ValueEdit(controller, "scale_factor")
        scale = QWidget()
        scale_layout = QHBoxLayout(scale)
        scale_layout.setContentsMargins(0, 0, 0, 0)
        scale_layout.addWidget(self.scale_edit, 1)
        scale_layout.addWidget(choice("units"))
        self.theta_edit = QLineEdit()
        self.theta_edit.setAlignment(Qt.AlignRight)
        self.theta_edit.setPlaceholderText("none")
        self.theta_edit.editingFinished.connect(self._theta_changed)
        identity = QGroupBox("Identity")
        form = QFormLayout(identity)
        add(form, "Case name", self.casename_edit)
        add(form, "Blade row", self.row_label)
        add(form, "Number of blades", self.blades_edit)
        add(form, "Scale factor", scale)
        form.addRow(_note("Non-dimensional lengths (flow path, chord) are multiplied by the scale factor; the units "
                          "name what that gives."))
        add(form, "Theta offset", self.theta_edit)
        form.addRow(_note("Optional rotation of the row about the axis; leave empty for none."))

        # -- Angles -------------------------------------------------------------------------------
        angles = QGroupBox("Angles")
        form = QFormLayout(angles)
        add(form, "Angles in the input", choice("angle_switch"))
        add(form, "Angle splines", choice("angle_spline"), "angle_spline")
        add(form, "Lean and sweep", choice("true_lean_sweep"))

        # -- Camber and thickness -----------------------------------------------------------------
        camber = QGroupBox("Camber and thickness")
        form = QFormLayout(camber)
        add(form, "Curvature control", choice("curvature_control"))
        add(form, "Auxiliary file", choice("spanwise_spline"))
        add(form, "Thickness distribution", choice("thickness_distribution"), "thickness_distribution")
        add(form, "Thickness multiplier", choice("thickness_multiplier"), "thickness_multiplier")
        add(form, "LE spline", choice("le_spline"), "le_spline")
        self.boxes["le_spline"].locked = True
        self.aux_note = _note()
        form.addRow(self.aux_note)

        # -- Chord and stacking -------------------------------------------------------------------
        chord = QGroupBox("Chord and stacking")
        form = QFormLayout(chord)
        add(form, "Chord", choice("chord_switch"), "chord_switch")
        add(form, "Variable stacking", choice("variable_stacking"), "variable_stacking")
        self.stacking_edit = StackingAxisEdit(controller)
        add(form, "Stacking axis", self.stacking_edit)

        # -- Point clustering ---------------------------------------------------------------------
        clustering = QGroupBox("Point clustering")
        form = QFormLayout(clustering)
        add(form, "Clustering", choice("clustering_switch"), "clustering_switch")
        self.clustering_edit = ValueEdit(controller, "clustering_parameter")
        add(form, "Clustering parameter", self.clustering_edit)

        for box in (identity, angles, camber, chord, clustering):
            box.layout().setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        inner = QWidget()
        column = QVBoxLayout(inner)
        for w in (identity, angles, camber, chord, clustering):
            column.addWidget(w)
        column.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(inner)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)

    # -- RowTab -----------------------------------------------------------------------------
    def row_changed(self) -> None:
        for w in (*self.boxes.values(), self.blades_edit, self.scale_edit, self.clustering_edit, self.stacking_edit):
            w.set_row(self.row_id)

    def refresh_inputs(self) -> None:
        row = self.row
        for w in (*self.boxes.values(), self.blades_edit, self.scale_edit, self.clustering_edit, self.stacking_edit):
            w.refresh()
        if row is None:
            self.casename_edit.setText("")
            self.row_label.setText("")
            self.theta_edit.setText("")
            return
        m = row.main
        self.casename_edit.setText(m.casename)
        self.row_label.setText(f"{m.row}   (from the file name 3dbgbinput.{row.row_id}.dat; read-only)")
        self.theta_edit.setText("" if m.theta_offset is None else f"{m.theta_offset:.10g}")
        self.stacking_edit.setEnabled(not m.variable_stacking)
        self._update_notes(row)

    def _update_notes(self, row: BladeRow) -> None:
        m = row.main
        n = self.notes
        n["angle_spline"].setText("The in_beta*/out_beta* control points (Spanwise controls) are angles with the "
                                  "inlet/exit splines and increments with incidence/deviation; switching does not "
                                  "convert them.")
        td = m.thickness_distribution
        n["thickness_distribution"].setText(
            {5: "Control points in spancontrolinputs (Thickness tab). Needed for analytic derivatives.",
             0: "Elliptical LE/TE and cubic sides from t/c_max, umxthk, lethk, tethk (Thickness tab).",
             }.get(td, "Quartic spline from t/c_max, umxthk, lethk, tethk. Note: on the example cases T-Blade3 stops "
                       "with 'Singular matrix … thickness distribution' for this option; see the log."))
        n["thickness_multiplier"].setText(
            "Unused with the modified NACA thickness." if td == 5 else
            ("Multiplies the thickness by a spline from the auxiliary file's thickness block." if m.thickness_multiplier
             else "Off: the tm/c control points (Spanwise controls) scale the thickness instead."))
        n["le_spline"].setText("Must be 0: current T-Blade3 stops when it is on (readinput.f90).")
        chord = {0: "The chord column of the section table is not used.",
                 1: "Uses the chord column of the Sections tab.",
                 2: "Uses the chord multiplier control points (Spanwise controls)."}
        n["chord_switch"].setText(chord.get(m.chord_switch, ""))
        n["variable_stacking"].setText("On: stk_u and stk_v of each section (Stacking tab) replace the stacking axis."
                                       if m.variable_stacking else
                                       "Off: all sections are stacked on the stacking axis.")
        n["clustering_switch"].setText("Elliptical works only with the modified NACA thickness.")
        self.aux_note.setText(aux_requirement(row))

    # -- edits ------------------------------------------------------------------------------
    def _casename_changed(self) -> None:
        row = self.row
        if row is None:
            return
        text = self.casename_edit.text().strip()
        if not text or any(c in text for c in " \t,/'\"\\"):
            self.controller.message.emit("The case name must be one word without / , or quotes "
                                         "(T-Blade3 uses it in file names)")
            self.casename_edit.setText(row.main.casename)
            return
        self.controller.set_attribute(self.row_id, row.main, "casename", text, "Change the case name")

    def _theta_changed(self) -> None:
        row = self.row
        if row is None:
            return
        text = self.theta_edit.text().strip()
        try:
            value = float(text) if text else None
        except ValueError:
            self.theta_edit.setText("" if row.main.theta_offset is None else f"{row.main.theta_offset:.10g}")
            return
        self.controller.set_attribute(self.row_id, row.main, "theta_offset", value, "Change the theta offset")
