# view/pdf_import_dialog.py
"""
Import d'une datasheet PDF : identité du composant (référence, fabricant, catégorie,
modifiables), partie importée (module IGBT + diode : deux composants, un import chacun),
table des graphiques trouvés (cochable : page, nom, caractéristique, rôle PLECS modifiable,
axes, courbes, points à vérifier), aperçu du graphique choisi (image et courbes lues) et
détail (courbes et conditions, avertissements).
Les graphiques sont déjà convertis (model.pdfimport.prepare) : l'aperçu est ce qui sera
importé.
"""
import numpy as np
from PyQt6 import QtCore, QtGui, QtWidgets

from model import datasheet, plecs
from .properties import CATEGORIES

HEADERS = ["", "Page", "Graphique", "Caractéristique", "Rôle PLECS", "Axe X", "Axe Y",
           "Courbes", "À vérifier"]
ROLE_COLUMN = 4


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
            values = {1: str(found.page), 2: graph.name,
                      3: datasheet.KINDS.get(dg.kind, dg.kind) + (" (diode)" if dg.part == "Diode"
                                                                  and len(draft.parts) > 1 else ""),
                      5: axis_text(graph.x_axis, found.x.log), 6: axis_text(graph.y_axis, found.y.log),
                      7: str(len(graph.datasets)),
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
        right = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(right)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.preview, 1)
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
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setText("Importer")
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
        pixmap = QtGui.QPixmap.fromImage(array_to_qimage(graph.image))
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        for dataset in graph.datasets:                    # courbes lues, par-dessus l'image
            painter.setPen(QtGui.QPen(QtGui.QColor(dataset.color), 2))
            points = [QtCore.QPointF(float(x), float(y)) for x, y in dataset.pixels]
            if len(points) > 1:
                painter.drawPolyline(QtGui.QPolygonF(points))
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
