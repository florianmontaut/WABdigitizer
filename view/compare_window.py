# view/compare_window.py
"""
Fenêtre de comparaison des composants (non modale) :
    gauche   caractéristique (« tension en fonction de courant »), filtre, arborescence
             composant > graphique > courbe à cocher
    centre   courbes cochées sur des axes communs, curseur vertical déplaçable
    bas      échelles log, courbe de référence, valeurs au curseur et écarts
"""
import pyqtgraph as pg
from PyQt6 import QtCore, QtGui, QtWidgets

from qtsocle import theme

from view import zoom


class CompareWindow(QtWidgets.QMainWindow):
    closing = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent, QtCore.Qt.WindowType.Window)
        self.setWindowTitle("Comparaison de composants")
        self.resize(1300, 800)
        self._build_actions()
        self._build_panels()
        self.refresh_theme()

    def _build_actions(self):
        bar = self.addToolBar("Comparaison")
        bar.setMovable(False)

        def action(text, icon_name, tip):
            act = QtGui.QAction(text, self)
            act.setToolTip(tip)
            act.setStatusTip(tip)
            theme.set_action_icon(act, icon_name)
            bar.addAction(act)
            return act

        self.actionReload = action("Recharger", "redo",
                                   "Relire la librairie et le composant ouvert")
        self.actionAddFiles = action("Ajouter des fichiers...", "import",
                                     "Ajouter des projets *.pdig.json ou des fiches JSON")
        self.actionUncheck = action("Tout décocher", "trash", "Retirer toutes les courbes")
        bar.addSeparator()
        self.actionExportCsv = action("Exporter (CSV)...", "export",
                                      "Courbes cochées sur des X communs")
        self.actionExportImage = action("Exporter l'image...", "image", "Graphique en PNG")

    def _build_panels(self):
        self.characteristic = QtWidgets.QComboBox()
        self.characteristic.setToolTip("Courbes comparables : mêmes dimensions physiques "
                                       "en X et en Y, quel que soit le type de composant")
        self.filter = QtWidgets.QLineEdit()
        self.filter.setPlaceholderText("Filtrer (composant, catégorie, condition)")
        self.filter.setClearButtonEnabled(True)
        self.tree = QtWidgets.QTreeView()
        self.tree.setHeaderHidden(True)
        self.tree.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        left = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(left)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(QtWidgets.QLabel("Caractéristique"))
        layout.addWidget(self.characteristic)
        layout.addWidget(self.filter)
        layout.addWidget(self.tree)

        self.plot_widget = pg.PlotWidget()
        self.plot = self.plot_widget.getPlotItem()
        zoom.limit_empty(self.plot)                      # bornée dès l'ouverture
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        self.legend = self.plot.addLegend(offset=(10, 10))
        self.cursor = pg.InfiniteLine(angle=90, movable=True,
                                      pen=pg.mkPen("#888888", width=1,
                                                   style=QtCore.Qt.PenStyle.DashLine))
        self.cursor.setZValue(100)

        self.log_x = QtWidgets.QCheckBox("X log")
        self.log_y = QtWidgets.QCheckBox("Y log")
        self.reference = QtWidgets.QComboBox()
        self.reference.setToolTip("Courbe de référence des écarts")
        self.cursor_value = QtWidgets.QLineEdit()
        self.cursor_value.setPlaceholderText("X du curseur")
        self.cursor_value.setMaximumWidth(120)
        controls = QtWidgets.QHBoxLayout()
        for widget in (self.log_x, self.log_y, QtWidgets.QLabel("Référence"), self.reference,
                       QtWidgets.QLabel("Curseur X ="), self.cursor_value):
            controls.addWidget(widget)
        controls.setStretch(3, 1)
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Courbe", "Valeur", "Écart", "Écart %"])
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            header.setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        bottom = QtWidgets.QWidget()
        bottom_layout = QtWidgets.QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(4, 4, 4, 4)
        bottom_layout.addLayout(controls)
        bottom_layout.addWidget(self.table)

        center = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        center.addWidget(self.plot_widget)
        center.addWidget(bottom)
        center.setSizes([550, 230])
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(center)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([330, 970])
        self.setCentralWidget(splitter)
        self.statusBar()

    def refresh_theme(self):
        self.plot_widget.setBackground(theme.colors()["graph_bg"])
        theme.style_plot(self.plot)

    def message(self, text: str, timeout: int = 0):
        self.statusBar().showMessage(text, timeout)

    def closeEvent(self, event):
        self.closing.emit()
        super().closeEvent(event)
