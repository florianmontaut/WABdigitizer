# view/pdf_import_dialog.py
"""
Import d'une datasheet PDF : identité du composant (référence, fabricant, catégorie,
modifiables), partie importée (module IGBT + diode : deux composants, un import chacun),
table des graphiques trouvés (cochable : page, nom, caractéristique, rôle PLECS modifiable,
axes, courbes, points à vérifier), aperçu du graphique choisi (image et courbes lues) et
détail (courbes et conditions, avertissements).
Les graphiques sont déjà convertis (model.pdfimport.prepare) : l'aperçu est ce qui sera
importé. Graphique en image : graduations repérées encadrées sur l'aperçu, valeurs lues
dans l'image proposées (texte gris des champs) : un champ vide garde la valeur lue, une
saisie la remplace (-> Draft.calibrate) ; sans valeur lue ni saisie, le graphique est
importé sans calibration.
"""
import numpy as np
from PyQt6 import QtCore, QtGui, QtWidgets

from model import datasheet, plecs
from model.calibration import CalibrationError
from .dialogs import format_value, parse_value
from .properties import CATEGORIES

HEADERS = ["", "Page", "Graphique", "Caractéristique", "Rôle PLECS", "Axe X", "Axe Y",
           "Courbes", "À vérifier"]
ROLE_COLUMN = 4
# graduations d'un graphique en image : (clé, texte, axe, extrémité), couleurs des repères
TICKS = (("x1", "X, première graduation", "x", 0), ("x2", "X, dernière graduation", "x", -1),
         ("y1", "Y, première graduation (bas)", "y", -1), ("y2", "Y, dernière graduation (haut)", "y", 0))
MARKER_COLORS = {"x1": "#E53935", "x2": "#D81B60", "y1": "#E53935", "y2": "#FB8C00"}


def array_to_qimage(image: np.ndarray) -> QtGui.QImage:
    image = np.ascontiguousarray(image[:, :, :3])
    h, w = image.shape[:2]
    return QtGui.QImage(image.data, w, h, 3 * w, QtGui.QImage.Format.Format_RGB888).copy()


def axis_text(axis, log) -> str:
    text = axis.quantity or "?"
    if axis.unit:
        text += f" [{axis.unit}]"
    return text + (" log" if log else "")


class PdfImportDialog(QtWidgets.QDialog):

    def __init__(self, draft, parent=None):
        """draft : model.pdfimport.Draft."""
        super().__init__(parent)
        self.setWindowTitle("Importer une datasheet PDF")
        self.resize(1250, 700)
        self.draft = draft
        graphs = draft.graphs
        identity = draft.identity

        summary = QtWidgets.QLabel(
            f"<b>{draft.path.name}</b> : {len(graphs)} graphique(s) trouvé(s). Les graphiques "
            "cochés forment un nouveau composant, à vérifier puis enregistrer ou publier.")
        summary.setWordWrap(True)

        # identité
        self.part_number = QtWidgets.QLineEdit(identity.part_number)
        self.manufacturer = QtWidgets.QLineEdit(identity.manufacturer)
        self.category = QtWidgets.QComboBox()
        self.category.setEditable(True)
        self.category.addItems(CATEGORIES)
        self.part = QtWidgets.QComboBox()
        self.part.addItems(draft.parts)
        form = QtWidgets.QFormLayout()
        form.addRow("Référence", self.part_number)
        form.addRow("Fabricant", self.manufacturer)
        form.addRow("Catégorie", self.category)
        if len(draft.parts) > 1:
            note = QtWidgets.QLabel("Module : un composant par partie ; importer le PDF une "
                                    "seconde fois pour l'autre partie.")
            note.setWordWrap(True)
            form.addRow("Partie importée", self.part)
            form.addRow("", note)
        identity_box = QtWidgets.QGroupBox("Composant")
        identity_box.setLayout(form)

        # graphiques
        table = QtWidgets.QTableWidget(len(graphs), len(HEADERS))
        table.setHorizontalHeaderLabels(HEADERS)
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().hide()
        table.verticalHeader().setDefaultSectionSize(24)
        table.setWordWrap(False)
        self.roles = []
        for row, dg in enumerate(graphs):
            graph, found = dg.graph, dg.found
            check = QtWidgets.QTableWidgetItem()
            check.setFlags(QtCore.Qt.ItemFlag.ItemIsUserCheckable | QtCore.Qt.ItemFlag.ItemIsEnabled
                           | QtCore.Qt.ItemFlag.ItemIsSelectable)
            table.setItem(row, 0, check)
            raster = dg.plot is not None
            log_x, log_y = (dg.plot.log_x, dg.plot.log_y) if raster else (found.x.log, found.y.log)
            values = {1: str(found.page), 2: graph.name,
                      3: datasheet.KINDS.get(dg.kind, dg.kind) + (" (diode)" if dg.part == "Diode"
                                                                  and len(draft.parts) > 1 else ""),
                      5: axis_text(graph.x_axis, log_x), 6: axis_text(graph.y_axis, log_y),
                      7: (("image, calibrée" if graph.calibrated else "image") if raster
                          else str(len(graph.datasets))),
                      8: str(len(dg.warnings)) if dg.warnings else ""}
            for col, value in values.items():
                cell = QtWidgets.QTableWidgetItem(value)
                if col in (1, 7, 8):
                    cell.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                if dg.warnings:
                    cell.setToolTip("\n".join(dg.warnings))
                table.setItem(row, col, cell)
            role = QtWidgets.QComboBox()
            for key, text in plecs.ROLES.items():
                role.addItem(text.split(" : ")[0] if key else "—", key)
            role.setCurrentIndex(max(role.findData(graph.plecs_role), 0))
            role.setToolTip("Rôle du graphique dans l'export PLECS")
            role.currentIndexChanged.connect(self._role_changed)
            table.setCellWidget(row, ROLE_COLUMN, role)
            self.roles.append(role)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Stretch)
        table.currentCellChanged.connect(self._show)
        self.table = table

        self.preview = QtWidgets.QLabel()
        self.preview.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(420, 320)
        self.details = QtWidgets.QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(170)
        self._build_ticks()
        right = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(right)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.preview, 1)
        lay.addWidget(self.ticks_box)
        lay.addWidget(self.details)
        left = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(left)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(identity_box)
        lay.addWidget(table, 1)
        split = QtWidgets.QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok
                                             | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        ok = buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
        ok.setText("Importer")
        ok.setAutoDefault(False)          # Entrée dans une valeur de graduation : pas d'import
        ok.setDefault(False)
        every = buttons.addButton("Tout cocher", QtWidgets.QDialogButtonBox.ButtonRole.ActionRole)
        none = buttons.addButton("Tout décocher", QtWidgets.QDialogButtonBox.ButtonRole.ActionRole)
        every.clicked.connect(self.check_all)
        none.clicked.connect(self.uncheck_all)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(summary)
        layout.addWidget(split, 1)
        layout.addWidget(buttons)

        self.part.currentIndexChanged.connect(self._part_changed)
        self._part_changed()
        if graphs:
            table.selectRow(0)
            self._show(0, 0, -1, -1)

    # ------------------------------------------------------------ partie et identité
    def _part_changed(self, *_):
        """Partie choisie : ses graphiques cochés, référence et catégorie de la partie."""
        part = self.part.currentText() or self.draft.parts[0]
        for row, dg in enumerate(self.draft.graphs):
            self.table.item(row, 0).setCheckState(
                QtCore.Qt.CheckState.Checked if dg.part == part else QtCore.Qt.CheckState.Unchecked)
        diode = part == "Diode" and len(self.draft.parts) > 1
        reference = self.draft.identity.part_number
        self.part_number.setText(reference + (" (diode)" if diode and reference else ""))
        category = "Diode" if diode else self.draft.identity.category
        index = self.category.findText(category)
        if index >= 0:
            self.category.setCurrentIndex(index)
        else:
            self.category.setEditText(category)

    # ------------------------------------------------------------ graduations (image)
    def _build_ticks(self):
        """Saisie des valeurs des graduations repérées d'un graphique en image."""
        box = QtWidgets.QGroupBox("Graphique en image : graduations encadrées (vide = valeur lue)")
        grid = QtWidgets.QGridLayout(box)
        self.tick_images, self.tick_edits = {}, {}
        for row, (key, text, _, _) in enumerate(TICKS):
            label = QtWidgets.QLabel(text)
            label.setStyleSheet(f"color: {MARKER_COLORS[key]}")
            snippet = QtWidgets.QLabel()
            snippet.setMinimumWidth(70)
            edit = QtWidgets.QLineEdit()
            edit.setObjectName(key)
            edit.editingFinished.connect(self._ticks_edited)
            grid.addWidget(label, row, 0)
            grid.addWidget(snippet, row, 1)
            grid.addWidget(edit, row, 2)
            self.tick_images[key], self.tick_edits[key] = snippet, edit
        self.log_x = QtWidgets.QCheckBox("Axe X logarithmique")
        self.log_y = QtWidgets.QCheckBox("Axe Y logarithmique")
        for check in (self.log_x, self.log_y):
            check.toggled.connect(self._ticks_edited)
        grid.addWidget(self.log_x, 0, 3)
        grid.addWidget(self.log_y, 2, 3)
        self.tick_error = QtWidgets.QLabel()
        self.tick_error.setWordWrap(True)
        grid.addWidget(self.tick_error, 4, 0, 1, 4)
        box.hide()
        self.ticks_box = box
        self._ticks_row = -1
        self._ticks_loading = False
        self.tick_values = {}             # ligne -> (textes saisis, log_x, log_y)

    def _load_ticks(self, row):
        """Graduations du graphique choisi : extraits de l'image, valeurs déjà saisies."""
        dg = self.draft.graphs[row]
        self._ticks_row = row
        self.ticks_box.setVisible(dg.plot is not None)
        if dg.plot is None:
            return
        self._ticks_loading = True
        texts, log_x, log_y = self.tick_values.get(row, ({}, dg.plot.log_x, dg.plot.log_y))
        for key, _, axis, end in TICKS:
            x0, y0, x1, y1 = (dg.plot.x_labels if axis == "x" else dg.plot.y_labels)[end]
            image = dg.graph.image
            y1 = max(y1, int(y0 + dg.plot.char))  # « 0 » du bas : coupé au bord du cadre
            part = image[max(y0 - 3, 0):y1 + 4, max(x0 - 3, 0):x1 + 4]
            pixmap = QtGui.QPixmap.fromImage(array_to_qimage(part))
            self.tick_images[key].setPixmap(pixmap.scaledToHeight(
                min(28, 2 * pixmap.height()), QtCore.Qt.TransformationMode.SmoothTransformation))
            self.tick_edits[key].setText(texts.get(key, ""))
            read = dg.plot.read_values()[key]
            self.tick_edits[key].setPlaceholderText(
                f"lu : {format_value(read)}" if read is not None else "à saisir")
        self.log_x.setChecked(log_x)
        self.log_y.setChecked(log_y)
        self._ticks_loading = False
        self._tick_status()

    def _ticks_edited(self, *_):
        """
        Valeurs saisies, sinon lues : calibration du graphique dès que les quatre sont
        connues (un champ vide garde la valeur lue dans l'image).
        """
        row = self._ticks_row
        if self._ticks_loading or not 0 <= row < len(self.draft.graphs) \
                or self.draft.graphs[row].plot is None:
            return
        dg = self.draft.graphs[row]
        texts = {key: edit.text().strip() for key, edit in self.tick_edits.items()}
        self.tick_values[row] = (texts, self.log_x.isChecked(), self.log_y.isChecked())
        dg.graph.set_calibration(None)
        read = dg.plot.read_values()
        try:
            values = {key: parse_value(text) if text else read[key]
                      for key, text in texts.items()}
            if None not in values.values():
                self.draft.calibrate(row, log_x=self.log_x.isChecked(),
                                     log_y=self.log_y.isChecked(), **values)
        except (ValueError, CalibrationError) as error:
            self.tick_error.setText(f"<span style='color:#C62828'>{error}</span>")
            self._update_row(row)
            self._show(row)
            return
        self._tick_status()
        self._update_row(row)
        self._show(row)

    def _tick_status(self):
        graph = self.draft.graphs[self._ticks_row].graph
        typed = any(edit.text().strip() for edit in self.tick_edits.values())
        if graph.calibrated:
            cal = graph.calibration
            origin = "valeurs lues dans l'image, à vérifier" if not typed else "valeurs saisies"
            self.tick_error.setText(
                f"Calibré ({origin}) : X de {format_value(cal.x1)} à {format_value(cal.x2)}, "
                f"Y de {format_value(cal.y1)} à {format_value(cal.y2)}. Courbes à relever "
                "après l'import (pinceau, extraction).")
        else:
            self.tick_error.setText("Valeurs non lues : à saisir, sinon le graphique est "
                                    "importé sans calibration (à calibrer dans l'application).")

    def _update_row(self, row):
        dg = self.draft.graphs[row]
        if dg.plot is not None:
            texts, log_x, log_y = self.tick_values.get(row, ({}, dg.plot.log_x, dg.plot.log_y))
            self.table.item(row, 5).setText(axis_text(dg.graph.x_axis, log_x))
            self.table.item(row, 6).setText(axis_text(dg.graph.y_axis, log_y))
            self.table.item(row, 7).setText("image, calibrée" if dg.graph.calibrated else "image")

    def _role_changed(self, *_):
        for combo, dg in zip(self.roles, self.draft.graphs):
            dg.graph.plecs_role = combo.currentData() or ""

    def choice(self) -> dict:
        """Arguments de Draft.component : graphiques cochés, partie, identité saisie."""
        return {"indices": self.selected(), "part": self.part.currentText() or None,
                "part_number": self.part_number.text().strip(),
                "manufacturer": self.manufacturer.text().strip(),
                "category": self.category.currentText().strip()}

    # ------------------------------------------------------------ cases
    def check_all(self):
        self._set_all(QtCore.Qt.CheckState.Checked)

    def uncheck_all(self):
        self._set_all(QtCore.Qt.CheckState.Unchecked)

    def _set_all(self, state):
        for row in range(self.table.rowCount()):
            self.table.item(row, 0).setCheckState(state)

    def selected(self) -> list:
        return [row for row in range(self.table.rowCount())
                if self.table.item(row, 0).checkState() == QtCore.Qt.CheckState.Checked]

    # ------------------------------------------------------------ aperçu
    def _show(self, row, *_):
        if not 0 <= row < len(self.draft.graphs):
            return
        dg = self.draft.graphs[row]
        graph = dg.graph
        if row != self._ticks_row:
            self._load_ticks(row)
        pixmap = QtGui.QPixmap.fromImage(array_to_qimage(graph.image))
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        for dataset in graph.datasets:                    # courbes lues, par-dessus l'image
            painter.setPen(QtGui.QPen(QtGui.QColor(dataset.color), 2))
            points = [QtCore.QPointF(float(x), float(y)) for x, y in dataset.pixels]
            if len(points) > 1:
                painter.drawPolyline(QtGui.QPolygonF(points))
        if dg.plot is not None:                           # graduations repérées, repères
            origin, x2, y2 = dg.plot.markers()
            centers = {"x1": origin, "x2": x2, "y1": origin, "y2": y2}
            for key, _, axis, end in TICKS:
                x0, y0, x1, y1 = (dg.plot.x_labels if axis == "x" else dg.plot.y_labels)[end]
                pen = QtGui.QPen(QtGui.QColor(MARKER_COLORS[key]), 2)
                painter.setPen(pen)
                painter.drawRect(QtCore.QRectF(x0 - 3, y0 - 3, x1 - x0 + 6, y1 - y0 + 6))
                cx, cy = centers[key]
                painter.drawEllipse(QtCore.QPointF(cx, cy), 6, 6)
        painter.end()
        self.preview.setPixmap(pixmap.scaled(
            self.preview.size(), QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation))
        lines = ["Courbes :"]
        for dataset in graph.datasets:
            extra = f" — {dataset.condition}" if dataset.condition and dataset.condition != dataset.name else ""
            lines.append(f"  {dataset.name}{extra}")
        if dg.conditions:
            lines.append("Conditions communes : " + " ; ".join(dg.conditions))
        if dg.warnings:
            lines += ["À vérifier :"] + [f"- {w}" for w in dg.warnings]
        self.details.setPlainText("\n".join(lines))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._show(self.table.currentRow())
