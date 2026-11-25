"""The "Export geometry" dialog: which row, bodies and formats to write, where, and with what options."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QWidget)

from ..export_geometry import ExportRequest, local_names
from .controller import Controller

BODIES = ("blade", "hub_wedge", "passage", "solid", "assembly")
FORMATS = ("hgeom", "step", "brep")
DEFAULT_BODIES = ("blade", "hub_wedge", "passage", "solid")


def default_stem(controller: Controller, row_id: str) -> str:
    case = controller.case
    name = case.rows[row_id].main.casename or "row"
    return name if len(case.rows) == 1 else f"{name}_row{row_id}"


class ExportDialog(QDialog):
    def __init__(self, controller: Controller, row_id: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Export geometry")
        self.controller = controller
        case = controller.case
        form = QFormLayout(self)
        self.row_combo = QComboBox()
        for rid, row in case.rows.items():
            self.row_combo.addItem(f"Row {rid}: {row.main.casename}", rid)
        self.row_combo.setCurrentIndex(max(self.row_combo.findData(row_id), 0))
        self.row_combo.currentIndexChanged.connect(self._row_changed)
        if len(case.rows) > 1:
            form.addRow("Blade row", self.row_combo)
        else:
            form.addRow(QLabel(self.row_combo.currentText()))

        self.body_boxes = {}
        bodies = QHBoxLayout()
        for name in BODIES:
            box = QCheckBox(name)
            box.setChecked(name in DEFAULT_BODIES)
            self.body_boxes[name] = box
            bodies.addWidget(box)
        form.addRow("Bodies", bodies)

        self.format_boxes = {}
        formats = QHBoxLayout()
        for name in FORMATS:
            box = QCheckBox(name)
            box.setChecked(True)
            self.format_boxes[name] = box
            formats.addWidget(box)
        form.addRow("Formats", formats)

        folder = case.folder or Path.home()
        self.folder_edit = QLineEdit(str(Path(folder) / "brep"))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        line = QHBoxLayout()
        line.addWidget(self.folder_edit)
        line.addWidget(browse)
        form.addRow("Output folder", line)
        self.stem_edit = QLineEdit(default_stem(controller, self.row_id))
        form.addRow("File name stem", self.stem_edit)

        self.bore_edit = QLineEdit()
        self.bore_edit.setPlaceholderText("default")
        self.inlet_edit = QLineEdit()
        self.inlet_edit.setPlaceholderText("default")
        self.outlet_edit = QLineEdit()
        self.outlet_edit.setPlaceholderText("default")
        form.addRow("Bore radius", self.bore_edit)
        form.addRow("Inlet x", self.inlet_edit)
        form.addRow("Outlet x", self.outlet_edit)

        self.sens_box = QCheckBox("Include sensitivities of the design variables")
        form.addRow(self.sens_box)
        self._row_changed()

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        form.addRow(self.buttons)
        self.error = QLabel()
        self.error.setStyleSheet("color: #c0392b")
        form.addRow(self.error)

    @property
    def row_id(self) -> str:
        return self.row_combo.currentData()

    def _row_changed(self) -> None:
        case = self.controller.case
        self.stem_edit.setText(default_stem(self.controller, self.row_id))
        n = len(local_names(case, self.row_id, case.dv.names))
        self.sens_box.setEnabled(n > 0)
        self.sens_box.setToolTip(f"{n} design variable(s) in this row" if n else "This row has no design variables")
        if n == 0:
            self.sens_box.setChecked(False)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Output folder", self.folder_edit.text())
        if folder:
            self.folder_edit.setText(folder)

    @staticmethod
    def _number(edit: QLineEdit, what: str) -> float | None:
        text = edit.text().strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            raise ValueError(f"{what} must be a number or blank, got {text!r}") from None

    def request(self) -> ExportRequest:
        """The request the dialog describes. Raises ValueError with a readable message if it is incomplete."""
        bodies = tuple(n for n, b in self.body_boxes.items() if b.isChecked())
        formats = tuple(n for n, b in self.format_boxes.items() if b.isChecked())
        if not bodies:
            raise ValueError("choose at least one body")
        if not formats:
            raise ValueError("choose at least one format")
        folder, stem = self.folder_edit.text().strip(), self.stem_edit.text().strip()
        if not folder or not stem:
            raise ValueError("give an output folder and a file name stem")
        case = self.controller.case
        sens = tuple(local_names(case, self.row_id, case.dv.names)) if self.sens_box.isChecked() else ()
        return ExportRequest(Path(folder), stem, bodies, formats, self._number(self.bore_edit, "Bore radius"),
                             self._number(self.inlet_edit, "Inlet x"), self._number(self.outlet_edit, "Outlet x"),
                             sens)

    def _accept(self) -> None:
        try:
            self.request()
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.accept()
