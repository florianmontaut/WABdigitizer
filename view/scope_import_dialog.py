# view/scope_import_dialog.py
"""
Import d'une capture d'écran d'oscilloscope Tektronix : voies lues (cochables ; nom,
échelle et unité modifiables), base de temps modifiable, aperçu de la capture avec les
tracés numérisés et le zéro de chaque voie, détail (mesures de l'écran, avertissements).
La capture est déjà lue (model.scope.read_capture) : l'aperçu est ce qui sera importé.
"""
import numpy as np
from PyQt6 import QtCore, QtGui, QtWidgets

from model import scope
from .dialogs import format_value, parse_value
from .pdf_import_dialog import array_to_qimage

HEADERS = ["", "Voie", "Nom", "Échelle / div", "Unité", "Points", "À vérifier"]
NAME, SCALE, UNIT = 2, 3, 4


def parse_time(text: str) -> float:
    """« 100µs », « 1e-4 » -> secondes ; ValueError sinon."""
    quantity = scope.parse_quantity(text.replace(" ", "").replace("/div", ""))
    if quantity is not None and quantity[1] == "s":
        return quantity[0]
    return parse_value(text)


class ScopeImportDialog(QtWidgets.QDialog):

    def __init__(self, capture, image, name="", parent=None):
        """capture : model.scope.ScopeCapture ; image : la capture (RGB)."""
        super().__init__(parent)
        self.setWindowTitle("Importer une capture d'oscilloscope")
        self.resize(1250, 720)
        self.capture = capture
        self.image = np.asarray(image)[:, :, :3]
        mode = "vue zoomée" if capture.zoomed else "capture simple"
        if capture.zoom_window:
            mode += (f" (de {capture.zoom_window[0] * 1e6:g} à "
                     f"{capture.zoom_window[1] * 1e6:g} µs)")
        summary = QtWidgets.QLabel(
            f"<b>{name}</b> : {mode}, {len(capture.channels)} voie(s). Les voies cochées "
            "forment un nouveau composant (un graphique par voie, sur la même image), à "
            "vérifier puis enregistrer.")
        summary.setWordWrap(True)
        self.time_per_div = QtWidgets.QLineEdit(
            format_value(capture.time_per_div) if capture.time_per_div else "")
        self.time_per_div.setPlaceholderText("à saisir (s) : 100µs, 1e-4")
        self.time_per_div.setToolTip("Base de temps de la vue numérisée, en secondes par "
                                     "division (accepte « 100µs »)")
        form = QtWidgets.QFormLayout()
        form.addRow("Base de temps (s / div)", self.time_per_div)

        table = QtWidgets.QTableWidget(len(capture.channels), len(HEADERS))
        table.setHorizontalHeaderLabels(HEADERS)
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        table.verticalHeader().hide()
        editable = (QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable
                    | QtCore.Qt.ItemFlag.ItemIsEditable)
        fixed = QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable
        for row, ch in enumerate(capture.channels):
            check = QtWidgets.QTableWidgetItem()
            check.setFlags(fixed | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            check.setCheckState(QtCore.Qt.CheckState.Checked if len(ch.pixels)
                                else QtCore.Qt.CheckState.Unchecked)
            table.setItem(row, 0, check)
            cells = {1: (ch.name, fixed), NAME: (ch.name, editable),
                     SCALE: (format_value(ch.scale) if ch.scale else "", editable),
                     UNIT: (ch.unit, editable), 5: (str(len(ch.pixels)), fixed),
                     6: (str(len(ch.warnings)) if ch.warnings else "", fixed)}
            for col, (text, flags) in cells.items():
                cell = QtWidgets.QTableWidgetItem(text)
                cell.setFlags(flags)
                if col == 1:
                    cell.setForeground(QtGui.QColor(*ch.color))
                if ch.warnings:
                    cell.setToolTip("\n".join(ch.warnings))
                table.setItem(row, col, cell)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(NAME, QtWidgets.QHeaderView.ResizeMode.Stretch)
        table.currentCellChanged.connect(self._show)
        self.table = table

        self.preview = QtWidgets.QLabel()
        self.preview.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(480, 340)
        self.details = QtWidgets.QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(170)
        right = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(right)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.preview, 1)
        lay.addWidget(self.details)
        left = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(left)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(form)
        lay.addWidget(table, 1)
        split = QtWidgets.QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok
                                             | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        ok = buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
        ok.setText("Importer")
        ok.setAutoDefault(False)
        ok.setDefault(False)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        self.error = QtWidgets.QLabel()
        self.error.setStyleSheet("color: #C62828")

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(summary)
        layout.addWidget(split, 1)
        layout.addWidget(self.error)
        layout.addWidget(buttons)
        if capture.channels:
            table.selectRow(0)
        self._show(0)

    # ------------------------------------------------------------ choix
    def selected(self) -> list:
        return [self.capture.channels[r].name for r in range(self.table.rowCount())
                if self.table.item(r, 0).checkState() == QtCore.Qt.CheckState.Checked]

    def apply(self):
        """Réglages saisis reportés dans la capture ; ValueError si l'un est illisible."""
        text = self.time_per_div.text().strip()
        if text:
            value = parse_time(text)
            if value <= 0:
                raise ValueError("base de temps : valeur positive attendue")
            self.capture.time_per_div = value
        for row, ch in enumerate(self.capture.channels):
            scale = self.table.item(row, SCALE).text().strip()
            if scale:
                ch.scale = parse_value(scale)
            ch.unit = self.table.item(row, UNIT).text().strip()

    def labels(self) -> dict:
        return {ch.name: self.table.item(row, NAME).text().strip() or ch.name
                for row, ch in enumerate(self.capture.channels)}

    def choice(self) -> dict:
        """Arguments de scope.to_component (après apply)."""
        return {"choose": self.selected(), "labels": self.labels()}

    def _accept(self):
        try:
            self.apply()
        except ValueError as error:
            self.error.setText(str(error))
            return
        self.accept()

    # ------------------------------------------------------------ aperçu
    def _show(self, row, *_):
        pixmap = QtGui.QPixmap.fromImage(array_to_qimage(np.ascontiguousarray(self.image)))
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.fillRect(pixmap.rect(), QtGui.QColor(0, 0, 0, 150))   # capture assombrie
        g = self.capture.graticule
        for k, ch in enumerate(self.capture.channels):
            if not len(ch.pixels):
                continue
            color = QtGui.QColor(*ch.color)
            width = 3 if k == row else 1.5
            painter.setPen(QtGui.QPen(color, width))
            painter.drawPolyline(QtGui.QPolygonF(
                [QtCore.QPointF(float(x), float(y)) for x, y in ch.pixels]))
            if ch.zero_y is not None:          # zéro de la voie
                painter.setPen(QtGui.QPen(color, 2, QtCore.Qt.PenStyle.DashLine))
                painter.drawLine(QtCore.QPointF(g.x0 - 14, ch.zero_y),
                                 QtCore.QPointF(g.x0 + 30, ch.zero_y))
        painter.setPen(QtGui.QPen(QtGui.QColor("#9e9e9e"), 1))
        painter.drawRect(QtCore.QRectF(g.x0, g.y0, g.x1 - g.x0, g.y1 - g.y0))
        painter.end()
        self.preview.setPixmap(pixmap.scaled(
            self.preview.size(), QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation))
        lines = []
        if self.capture.measurements:
            lines.append("Mesures de l'écran : " + " ; ".join(
                f"{n} {k} {v:g} {u}" for n, k, v, u in self.capture.measurements))
        if self.capture.warnings:
            lines += ["Capture :"] + [f"- {w}" for w in self.capture.warnings]
        if 0 <= row < len(self.capture.channels):
            ch = self.capture.channels[row]
            lines.append(f"{ch.name} : {len(ch.pixels)} points, zéro à y = "
                         f"{ch.zero_y:.0f}" if ch.zero_y is not None else f"{ch.name} : zéro inconnu")
            lines += [f"- {w}" for w in ch.warnings]
        self.details.setPlainText("\n".join(lines))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._show(self.table.currentRow())
