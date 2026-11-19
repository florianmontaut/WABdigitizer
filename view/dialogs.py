# view/dialogs.py
"""Boîtes de dialogue : valeurs des points de calibration."""
from PyQt6 import QtWidgets

import formules
from formules import lut


def parse_value(text: str) -> float:
    """
    Nombre saisi : « 1,5 », « 2e-3 », ou petite formule (« 10^-3 », « 3*20 »).
    ValueError au message affichable sinon.
    """
    try:
        return lut.parse_number(text)
    except ValueError:
        pass
    try:
        value = formules.evaluate(formules.parse(text.replace(",", ".")), {})
        return float(value)
    except (ValueError, TypeError):
        raise ValueError(f"« {text} » n'est pas un nombre") from None


def format_value(value: float) -> str:
    return format(float(value), ".10g")


class CalibrationDialog(QtWidgets.QDialog):
    """Valeurs physiques des points X1, X2, Y1, Y2 et échelles logarithmiques."""

    def __init__(self, values: dict, parent=None, orthogonal=False):
        super().__init__(parent)
        self.setWindowTitle("Calibration des axes")
        layout = QtWidgets.QVBoxLayout(self)
        origin = ("X1 et Y1 : valeurs de X et de Y à l'origine O.\n" if orthogonal else "")
        layout.addWidget(QtWidgets.QLabel(
            "Valeurs des points pointés sur l'image.\n" + origin
            + "Accepte « 1,5 », « 2e-3 » ou « 10^-3 »."))
        grid = QtWidgets.QGridLayout()
        self.edits = {}
        for row, (axis, names) in enumerate((("X", ("x1", "x2")), ("Y", ("y1", "y2")))):
            for col, name in enumerate(names):
                grid.addWidget(QtWidgets.QLabel(name.upper()), row, 2 * col)
                edit = QtWidgets.QLineEdit(format_value(values.get(name, col)))
                edit.setObjectName(name)
                grid.addWidget(edit, row, 2 * col + 1)
                self.edits[name] = edit
        self.log_x = QtWidgets.QCheckBox("Axe X logarithmique")
        self.log_y = QtWidgets.QCheckBox("Axe Y logarithmique")
        self.log_x.setChecked(bool(values.get("log_x", False)))
        self.log_y.setChecked(bool(values.get("log_y", False)))
        grid.addWidget(self.log_x, 0, 4)
        grid.addWidget(self.log_y, 1, 4)
        layout.addLayout(grid)
        self.error = QtWidgets.QLabel()
        self.error.setStyleSheet("color: #C62828")
        layout.addWidget(self.error)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._check_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> dict:
        out = {name: parse_value(edit.text()) for name, edit in self.edits.items()}
        out["log_x"] = self.log_x.isChecked()
        out["log_y"] = self.log_y.isChecked()
        return out

    def _check_and_accept(self):
        try:
            values = self.values()
        except ValueError as error:
            self.error.setText(str(error))
            return
        for axis in ("x", "y"):
            if values[f"log_{axis}"] and min(values[f"{axis}1"], values[f"{axis}2"]) <= 0:
                self.error.setText(f"Axe {axis.upper()} logarithmique : valeurs > 0 requises")
                return
        self.accept()
