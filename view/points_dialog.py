# view/points_dialog.py
"""
Décimer / lisser les points sélectionnés : méthode et réglages, aperçu en direct.

Le dialogue ne calcule rien : il émet ses réglages (`changed`) ; le contrôleur affiche
l'aperçu sur le canevas et le nombre de points (`set_info`), puis applique à l'acceptation.
"""
from PyQt6 import QtCore, QtWidgets

from model.pointops import DECIMATE, FILTERS


class PointsDialog(QtWidgets.QDialog):
    changed = QtCore.pyqtSignal(dict)

    def __init__(self, kind: str, values: dict, parent=None):
        """kind : "decimate" ou "filter" ; values : réglages précédents."""
        super().__init__(parent)
        self.kind = kind
        self.setWindowTitle("Décimer les points" if kind == "decimate"
                            else "Lisser / filtrer les points")
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.method = QtWidgets.QComboBox()
        for key, text in (DECIMATE if kind == "decimate" else FILTERS).items():
            self.method.addItem(text, key)
        index = self.method.findData(values.get("method"))
        self.method.setCurrentIndex(max(index, 0))
        form.addRow("Méthode", self.method)
        if kind == "decimate":
            self.every = QtWidgets.QSpinBox()
            self.every.setRange(2, 1000)
            self.every.setValue(int(values.get("every", 2)))
            self.distance = QtWidgets.QDoubleSpinBox()
            self.distance.setRange(0.1, 10000)
            self.distance.setDecimals(1)
            self.distance.setSuffix(" px")
            self.distance.setValue(float(values.get("distance", 2.0)))
            form.addRow("n", self.every)
            form.addRow("Distance", self.distance)
            widgets = (self.every, self.distance)
        else:
            self.window = QtWidgets.QSpinBox()
            self.window.setRange(3, 999)
            self.window.setSingleStep(2)
            self.window.setValue(int(values.get("window", 5)))
            self.window.setSuffix(" points")
            self.order = QtWidgets.QSpinBox()
            self.order.setRange(0, 6)
            self.order.setValue(int(values.get("order", 2)))
            form.addRow("Fenêtre", self.window)
            form.addRow("Ordre du polynôme", self.order)
            widgets = (self.window, self.order)
        layout.addLayout(form)
        note = ("Les deux bouts de chaque morceau sélectionné sont gardés." if kind == "decimate"
                else "Y seulement, en coordonnées calibrées ; les points voisins servent "
                     "de contexte.")
        hint = QtWidgets.QLabel(note)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.info = QtWidgets.QLabel()
        layout.addWidget(self.info)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._form = form
        self.method.currentIndexChanged.connect(self._emit)
        for widget in widgets:
            widget.valueChanged.connect(self._emit)
        self._update_rows()

    def values(self) -> dict:
        method = self.method.currentData()
        if self.kind == "decimate":
            return {"method": method, "every": self.every.value(),
                    "distance": self.distance.value()}
        return {"method": method, "window": self.window.value(), "order": self.order.value()}

    def set_info(self, text: str):
        self.info.setText(text)

    def _update_rows(self):
        method = self.method.currentData()
        if self.kind == "decimate":
            self._form.setRowVisible(self.every, method == "every")
            self._form.setRowVisible(self.distance, method != "every")
        else:
            self._form.setRowVisible(self.order, method == "savgol")

    def _emit(self, *_):
        self._update_rows()
        self.changed.emit(self.values())

    def showEvent(self, event):
        super().showEvent(event)
        self.changed.emit(self.values())             # premier aperçu
