# view/signals_window.py
"""
Fenêtre « Calculs entre signaux » (non modale) :
    gauche   signaux du composant (à cocher pour les tracer), arbre des voies calculées
             (ajouter, nom, formule, unité, base de temps, affichée, état, supprimer)
             échelle de l'axe choisi (automatique, min / max, graduations, grille)
    droite   graphique à plusieurs axes d'ordonnées (view/y_axes.py : un axe par unité,
             par voie, axe unique) ou graphiques séparés par unité, curseur vertical,
             valeurs au curseur
Le contrôleur (controller/signals_controller.py) remplit et redessine.
"""
import pyqtgraph as pg
import pyqtgraph.parametertree as ptree
from PyQt6 import QtCore, QtGui, QtWidgets

from qtsocle import theme

from view import y_axes


class SignalsWindow(QtWidgets.QMainWindow):
    closing = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent, QtCore.Qt.WindowType.Window)
        self.setWindowTitle("Calculs entre signaux")
        self.resize(1300, 800)
        bar = self.addToolBar("Calculs")
        bar.setMovable(False)
        self.actionAdd = QtGui.QAction("Ajouter une voie calculée", self)
        self.actionAdd.setToolTip("Nouvelle formule sur les signaux du composant")
        theme.set_action_icon(self.actionAdd, "curve_add")
        self.actionRefresh = QtGui.QAction("Recalculer", self)
        self.actionRefresh.setToolTip("Relire les courbes du composant et recalculer")
        theme.set_action_icon(self.actionRefresh, "redo")
        self.actionExport = QtGui.QAction("Exporter (CSV)...", self)
        self.actionExport.setToolTip("Signaux tracés, sur la base de temps la plus fine")
        theme.set_action_icon(self.actionExport, "export")
        self.actionAutoScale = QtGui.QAction("Échelles automatiques", self)
        self.actionAutoScale.setToolTip("Chaque axe de nouveau ajusté à ses courbes")
        theme.set_action_icon(self.actionAutoScale, "fit")
        for act in (self.actionAdd, self.actionRefresh, self.actionExport):
            bar.addAction(act)
        bar.addSeparator()
        self.axis_mode = QtWidgets.QComboBox()
        self.axis_mode.setToolTip("Répartition des signaux par axe d'ordonnées ; molette ou "
                                  "glissement sur un axe : son échelle seule")
        for key, text in y_axes.MODES.items():
            self.axis_mode.addItem(text, key)
        bar.addWidget(self.axis_mode)
        bar.addAction(self.actionAutoScale)

        self.signals = QtWidgets.QListWidget()
        self.signals.setToolTip("Signaux du composant : cochés = tracés ; dans une formule, "
                                "le nom entre crochets ([Vce])")
        self.tree = ptree.ParameterTree(showHeader=False)
        self.scale_tree = ptree.ParameterTree(showHeader=False)
        left = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        box = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QtWidgets.QLabel("Signaux"))
        lay.addWidget(self.signals)
        left.addWidget(box)
        left.addWidget(self.tree)
        left.addWidget(self.scale_tree)
        left.setSizes([180, 420, 200])

        self.plots = pg.GraphicsLayoutWidget()
        self.readings = QtWidgets.QLabel()
        self.readings.setWordWrap(True)
        self.readings.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        right = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(right)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.plots, 1)
        lay.addWidget(self.readings)
        split = QtWidgets.QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 3)
        split.setSizes([360, 940])
        self.setCentralWidget(split)
        self.statusBar()
        self.refresh_theme()

    def refresh_theme(self):
        self.plots.setBackground(theme.colors()["graph_bg"])

    def closeEvent(self, event):
        self.closing.emit()
        super().closeEvent(event)
