# view/pdf_import_dialog.py
"""
Choix des graphiques à importer d'une datasheet PDF :
    table cochable (page, graphique, axes, courbes, points à vérifier)
    aperçu du graphique choisi (image rendue et courbes lues), détail des avertissements
Les graphiques sont déjà convertis (model.pdfimport.to_component) : l'aperçu est l'image
qui sera importée.
"""
import numpy as np
from PyQt6 import QtCore, QtGui, QtWidgets

HEADERS = ["", "Page", "Graphique", "Axe X", "Axe Y", "Courbes", "À vérifier"]


def array_to_qimage(image: np.ndarray) -> QtGui.QImage:
    image = np.ascontiguousarray(image[:, :, :3])
    h, w = image.shape[:2]
    return QtGui.QImage(image.data, w, h, 3 * w, QtGui.QImage.Format.Format_RGB888).copy()


class PdfImportDialog(QtWidgets.QDialog):

    def __init__(self, source: str, graphs, found, parent=None):
        """graphs : Graph du composant brouillon ; found : FoundGraph correspondants."""
        super().__init__(parent)
        self.setWindowTitle("Importer une datasheet PDF")
        self.resize(1100, 640)
        self.graphs, self.found = graphs, found

        summary = QtWidgets.QLabel(
            f"<b>{source}</b> : {len(graphs)} graphique(s) trouvé(s). Cochez ceux à "
            "importer ; ils formeront un nouveau composant, à vérifier puis enregistrer.")
        summary.setWordWrap(True)

        table = QtWidgets.QTableWidget(len(graphs), len(HEADERS))
        table.setHorizontalHeaderLabels(HEADERS)
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().hide()
        table.verticalHeader().setDefaultSectionSize(22)
        table.setWordWrap(False)
        for row, (graph, item) in enumerate(zip(graphs, found)):
            check = QtWidgets.QTableWidgetItem()
            check.setFlags(QtCore.Qt.ItemFlag.ItemIsUserCheckable | QtCore.Qt.ItemFlag.ItemIsEnabled
                           | QtCore.Qt.ItemFlag.ItemIsSelectable)
            check.setCheckState(QtCore.Qt.CheckState.Checked)
            table.setItem(row, 0, check)
            axes = []
            for axis, fit in ((graph.x_axis, item.x), (graph.y_axis, item.y)):
                text = axis.quantity or "?"
                if axis.unit:
                    text += f" [{axis.unit}]"
                axes.append(text + (" log" if fit.log else ""))
            values = [str(item.page), graph.name, axes[0], axes[1],
                      str(len(item.curves)), str(len(item.warnings)) if item.warnings else ""]
            for col, value in enumerate(values, 1):
                cell = QtWidgets.QTableWidgetItem(value)
                if col in (1, 5, 6):
                    cell.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                if item.warnings:
                    cell.setToolTip("\n".join(item.warnings))
                table.setItem(row, col, cell)
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
        self.details.setMaximumHeight(150)
        right = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(right)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.preview, 1)
        lay.addWidget(self.details)
        split = QtWidgets.QSplitter()
        split.addWidget(table)
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
        if graphs:
            table.selectRow(0)
            self._show(0, 0, -1, -1)

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

    def _show(self, row, *_):
        if not 0 <= row < len(self.graphs):
            return
        graph, item = self.graphs[row], self.found[row]
        pixmap = QtGui.QPixmap.fromImage(array_to_qimage(graph.image))
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        for dataset in graph.datasets:                    # courbes lues, par-dessus l'image
            pen = QtGui.QPen(QtGui.QColor(dataset.color), 2)
            painter.setPen(pen)
            points = [QtCore.QPointF(float(x), float(y)) for x, y in dataset.pixels]
            if len(points) > 1:
                painter.drawPolyline(QtGui.QPolygonF(points))
        painter.end()
        self.preview.setPixmap(pixmap.scaled(
            self.preview.size(), QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation))
        lines = [f"Courbes : " + (", ".join(d.name for d in graph.datasets) or "aucune")]
        if item.caption[1:]:
            lines.append("Conditions : " + " ; ".join(item.caption[1:]).replace("_", "").replace("^", ""))
        if item.warnings:
            lines += ["À vérifier :"] + [f"- {w}" for w in item.warnings]
        self.details.setPlainText("\n".join(lines))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._show(self.table.currentRow())
