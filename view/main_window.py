# view/main_window.py
"""
Fenêtre principale :
    gauche   arborescence du composant (graphiques, courbes)
    dock     librairie de composants (sous la fenêtre par défaut, déplaçable)
    centre   image à numériser (canevas) puis aperçu des courbes en unités physiques
    droite   paramètres (composant, graphique, courbe, extraction, modèle) puis table XY
"""
import numpy as np
import pyqtgraph as pg
import pyqtgraph.parametertree as ptree
from PyQt6 import QtCore, QtGui, QtWidgets

from qtsocle import theme

from . import properties, zoom
from .canvas import ImageCanvas, Mode
from .detached_window import DetachedWindow
from .library_panel import LibraryPanel

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff")


def qimage_to_array(image: QtGui.QImage) -> np.ndarray:
    """QImage -> tableau (lignes, colonnes, 3) uint8, RGB (transparence aplatie sur blanc)."""
    if image.isNull():
        raise ValueError("image illisible")
    image = image.convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
    width, height = image.width(), image.height()
    pointer = image.constBits()
    pointer.setsize(height * image.bytesPerLine())
    array = np.frombuffer(pointer, np.uint8).reshape(height, image.bytesPerLine())
    rgba = array[:, :width * 4].reshape(height, width, 4).astype(float)
    alpha = rgba[..., 3:4] / 255.0
    rgb = rgba[..., :3] * alpha + 255.0 * (1.0 - alpha)
    return np.ascontiguousarray(np.round(rgb).astype(np.uint8))


class MainWindow(QtWidgets.QMainWindow):
    # émis à la fermeture, avant la destruction : le contrôleur enregistre ses réglages
    closing = QtCore.pyqtSignal()
    files_dropped = QtCore.pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(QtWidgets.QApplication.applicationName())
        self.resize(1500, 900)
        self.setAcceptDrops(True)
        # référence faible vers une fonction -> bool : False annule la fermeture
        self.close_guard = None
        self.answer = True              # réponse aux questions sans écran (tests)
        self.last_question = None
        self._build_actions()
        self._build_panels()
        self._build_menus()
        self.refresh_theme()

    # ============================================================ actions
    def _action(self, text, icon_name=None, tip=None, shortcut=None, checkable=False):
        act = QtGui.QAction(text, self)
        act.setToolTip(tip or text)
        act.setStatusTip(tip or text)
        act.setCheckable(checkable)
        if shortcut:
            act.setShortcut(QtGui.QKeySequence(shortcut))
        if icon_name:
            theme.set_action_icon(act, icon_name)
        return act

    def _build_actions(self):
        a = self._action
        self.actionNew = a("Nouveau composant", "file", shortcut="Ctrl+N")
        self.actionOpenImage = a("Ajouter une image...", "image",
                                 "Ajouter un graphique à partir d'une image", "Ctrl+I")
        self.actionPaste = a("Coller une image", "paste",
                             "Ajouter un graphique depuis le presse-papiers", "Ctrl+V")
        self.actionOpen = a("Ouvrir un projet...", "open", shortcut="Ctrl+O")
        self.actionImportScope = a("Importer une capture d'oscilloscope...", "scope",
                                   "Capture d'écran Tektronix : voies numérisées, un graphique "
                                   "par voie (nouveau composant)", "Ctrl+Shift+T")
        self.actionImportPdf = a("Importer une datasheet PDF...", "pdf",
                                 "Nouveau composant : graphiques, calibration et courbes "
                                 "lus dans une datasheet PDF vectorielle", "Ctrl+Shift+O")
        self.actionSave = a("Enregistrer", "save", shortcut="Ctrl+S")
        self.actionSaveAs = a("Enregistrer sous...", shortcut="Ctrl+Shift+S")
        self.actionExportCsv = a("Courbes du graphique (CSV)...", "export")
        self.actionExportGrid = a("Courbes sur la grille de X commune (CSV)...", "table")
        self.actionExportComponent = a("Fiche du composant (JSON)...", "export")
        self.actionExportPlecs = a("Composant pour PLECS (XML)...", "export",
                                   "Description thermique PLECS : pertes et modèle thermique")
        self.actionCopyTable = a("Copier la table de la courbe", "table",
                                 "Copier X, Y (collage Excel)", "Ctrl+Shift+C")
        self.actionCopyLut = a("Copier la courbe en table formules", "link",
                               "Copier interp(x; x1; y1; ...) dans le presse-papiers")
        self.actionQuit = a("Quitter", shortcut="Ctrl+Q")

        # modes du canevas : exclusifs
        self.modeGroup = QtGui.QActionGroup(self)
        self.modeActions = {}
        for mode, icon_name, key in ((Mode.NAVIGATE, "hand", "Esc"),
                                     (Mode.CALIBRATE, "calibrate", "C"),
                                     (Mode.ADD, "point_add", "A"),
                                     (Mode.DELETE, "point_remove", "D"),
                                     (Mode.PAINT, "brush", "B"),
                                     (Mode.ERASE, "eraser", "E"),
                                     (Mode.PICK, "pipette", "P"),
                                     (Mode.FOLLOW, "follow", "F")):
            act = a(mode.value, icon_name, f"{mode.value} ({key})", key, checkable=True)
            act.setData(mode)
            self.modeGroup.addAction(act)
            self.modeActions[mode] = act
        self.modeActions[Mode.NAVIGATE].setChecked(True)

        self.actionClearMask = a("Effacer le masque", "trash")
        self.actionDetection = a("Aperçu des pixels détectés", "eye", checkable=True)
        self.actionExtract = a("Extraire la courbe", "extract",
                               "Extraction automatique dans le masque (Ctrl+E)", "Ctrl+E")
        self.actionFit = a("Ajuster le modèle", "fit", shortcut="Ctrl+M")
        self.actionAddCurve = a("Nouvelle courbe", "curve_add", shortcut="Ctrl+K")
        self.actionSplit = a("Séparer les points du masque", "split",
                             "Points de la courbe peints au pinceau -> nouvelle courbe "
                             "(deux courbes relevées comme une seule)", "Ctrl+Shift+X")
        self.actionMerge = a("Fusionner les courbes", "merge",
                             "Courbes sélectionnées d'un même graphique (Ctrl+clic dans "
                             "l'arborescence) -> une seule courbe, morceaux reliés bout à bout",
                             "Ctrl+Shift+J")
        self.actionDelete = a("Supprimer la sélection", "trash",
                              "Supprimer le graphique ou la courbe sélectionné")
        self.actionDetachPreview = a("Détacher l'aperçu", "detach",
                                     "Aperçu en unités physiques dans sa propre fenêtre "
                                     "(la fermer le remet sous l'image)")
        self.actionDetachLibrary = a("Détacher la librairie", "detach",
                                     "Librairie dans sa propre fenêtre (la fermer la remet "
                                     "dans la fenêtre principale)")
        self.actionOptions = a("Options...", "settings", "Options de l'application")
        self.actionDark = a("Thème sombre", "moon", checkable=True)
        self.actionCompare = a("Comparer des composants...", "compare",
                               "Courbes de plusieurs composants sur des axes communs",
                               "Ctrl+Shift+K")

        # librairie
        self.actionPublish = a("Publier dans la librairie", "publish",
                               "Écrire la fiche, le projet et la description PLECS du "
                               "composant dans la librairie", "Ctrl+Shift+P")
        self.actionLibraryOpen = a("Ouvrir le projet", "open",
                                   "Ouvrir le projet du composant choisi dans la librairie")
        self.actionLibraryCompare = a("Comparer", "compare",
                                      "Comparer les composants choisis dans la librairie")
        self.actionLibraryRemove = a("Mettre à la corbeille", "trash",
                                     "Déplacer les composants choisis dans la corbeille "
                                     "de la librairie (_corbeille)")
        self.actionLibraryReveal = a("Afficher dans l'explorateur", "folder",
                                     "Ouvrir le dossier du composant choisi, ou de la librairie")
        self.actionLibraryReload = a("Actualiser", "redo", "Relire le dossier de la librairie")

        bar = self.addToolBar("Fichier")
        bar.setMovable(False)
        for act in (self.actionImportPdf, self.actionOpenImage, self.actionPaste,
                    self.actionOpen, self.actionSave, self.actionPublish):
            bar.addAction(act)
        bar = self.addToolBar("Numérisation")
        bar.setMovable(False)
        self.digitizeBar = bar
        for act in self.modeActions.values():
            bar.addAction(act)
        bar.addSeparator()
        for act in (self.actionClearMask, self.actionDetection, self.actionExtract,
                    self.actionFit, self.actionAddCurve, self.actionSplit):
            bar.addAction(act)
        bar = self.addToolBar("Application")
        bar.setMovable(False)
        bar.addAction(self.actionOptions)
        bar.addAction(self.actionDark)

    def _build_menus(self):
        menu = self.menuBar().addMenu("&Fichier")
        for act in (self.actionNew, self.actionOpen, self.actionImportPdf,
                    self.actionImportScope, self.actionSave,
                    self.actionSaveAs):
            menu.addAction(act)
        menu.addSeparator()
        menu.addAction(self.actionOpenImage)
        menu.addAction(self.actionPaste)
        menu.addSeparator()
        exports = menu.addMenu("Exporter")
        for act in (self.actionExportCsv, self.actionExportGrid, self.actionExportComponent,
                    self.actionExportPlecs):
            exports.addAction(act)
        menu.addSeparator()
        menu.addAction(self.actionQuit)
        menu = self.menuBar().addMenu("&Numérisation")
        for act in self.modeActions.values():
            menu.addAction(act)
        menu.addSeparator()
        for act in (self.actionClearMask, self.actionDetection, self.actionExtract,
                    self.actionFit, self.actionAddCurve, self.actionSplit, self.actionMerge,
                    self.actionDelete):
            menu.addAction(act)
        menu = self.menuBar().addMenu("&Librairie")
        self.actionLibraryPanel = self.library_dock.toggleViewAction()
        self.actionLibraryPanel.setText("Panneau de la librairie")
        self.actionLibraryPanel.setShortcut(QtGui.QKeySequence("Ctrl+L"))
        theme.set_action_icon(self.actionLibraryPanel, "library")
        for act in (self.actionLibraryPanel, None, self.actionPublish, self.actionLibraryOpen,
                    self.actionLibraryCompare, self.actionLibraryRemove, None,
                    self.actionLibraryReveal, self.actionLibraryReload):
            if act is None:
                menu.addSeparator()
            else:
                menu.addAction(act)
        menu = self.menuBar().addMenu("&Affichage")
        menu.addAction(self.actionDetachPreview)
        menu.addAction(self.actionDetachLibrary)
        menu = self.menuBar().addMenu("&Outils")
        menu.addAction(self.actionCompare)
        menu = self.menuBar().addMenu("&Édition")
        self.editMenu = menu
        menu.addAction(self.actionCopyTable)
        menu.addAction(self.actionCopyLut)
        menu.addSeparator()
        menu.addAction(self.actionOptions)
        menu.addAction(self.actionDark)

    # ============================================================ panneaux
    def _build_panels(self):
        self.tree = QtWidgets.QTreeView()
        self.tree.setHeaderHidden(True)
        self.tree.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.addAction(self.actionMerge)
        self.tree.addAction(self.actionDelete)
        self.tree.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.ActionsContextMenu)
        self.actionDelete.setShortcut(QtGui.QKeySequence("Ctrl+Del"))

        self.canvas = ImageCanvas()
        self.preview = pg.PlotWidget()
        self.preview_plot = self.preview.getPlotItem()
        self.preview_plot.showGrid(x=True, y=True, alpha=0.3)
        self.preview_plot.addLegend(offset=(-10, 10))
        zoom.limit_empty(self.preview_plot)              # bornée dès l'ouverture
        menu = self.preview_plot.vb.menu
        menu.addSeparator()
        menu.addAction(self.actionDetachPreview)
        center = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.center = center
        center.addWidget(self.canvas)
        center.addWidget(self.preview)
        center.setStretchFactor(0, 3)
        center.setStretchFactor(1, 1)
        center.setSizes([600, 220])

        self.parameters = ptree.ParameterTree(showHeader=False)
        self.params = {"component": properties.component(), "graph": properties.graph(),
                       "dataset": properties.dataset(), "extraction": properties.extraction(),
                       "model": properties.model()}
        for name, param in self.params.items():
            self.parameters.addParameters(param)
        self.table = QtWidgets.QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["X", "Y"])
        self.table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Stretch)
        right = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        right.addWidget(self.parameters)
        right.addWidget(self.table)
        right.setSizes([560, 260])

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        for widget in (self.tree, center, right):
            splitter.addWidget(widget)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([230, 900, 340])
        self.setCentralWidget(splitter)

        self.coordinates = QtWidgets.QLabel()
        self.statusBar().addPermanentWidget(self.coordinates)

        self.library = LibraryPanel([self.actionPublish, None, self.actionLibraryOpen,
                                     self.actionLibraryCompare, self.actionLibraryRemove, None,
                                     self.actionLibraryReveal, self.actionLibraryReload, None,
                                     self.actionDetachLibrary])
        dock = QtWidgets.QDockWidget("Librairie", self)
        dock.setObjectName("library_dock")
        # pas de dock flottant (petite fenêtre toujours au-dessus) : « Détacher la librairie »
        dock.setFeatures(QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetClosable
                         | QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable)
        dock.setWidget(self.library)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        self.resizeDocks([dock], [200], QtCore.Qt.Orientation.Vertical)    # l'image d'abord
        self.library_dock = dock
        # panneaux détachés : fenêtres créées au premier détachement, puis réutilisées
        self.preview_window = None
        self.library_window = None
        self._preview_sizes = None
        self.actionDetachPreview.triggered.connect(self.toggle_preview)
        self.actionDetachLibrary.triggered.connect(self.toggle_library)
        self.closing.connect(self.attach_all)

    # ============================================================ affichage
    def add_history_actions(self, undo: QtGui.QAction, redo: QtGui.QAction):
        """Annuler / Refaire (créées par la pile du contrôleur) : barre et menu Édition."""
        undo.setShortcut(QtGui.QKeySequence.StandardKey.Undo)
        redo.setShortcuts([QtGui.QKeySequence("Ctrl+Y"), QtGui.QKeySequence("Ctrl+Shift+Z")])
        theme.set_action_icon(undo, "undo")
        theme.set_action_icon(redo, "redo")
        first = self.digitizeBar.actions()[0]
        self.digitizeBar.insertActions(first, [undo, redo])
        self.digitizeBar.insertSeparator(first)
        first = self.editMenu.actions()[0]
        self.editMenu.insertActions(first, [undo, redo])
        self.editMenu.insertSeparator(first)
        self.actionUndo, self.actionRedo = undo, redo

    # ============================================================ panneaux détachés
    def shared_actions(self) -> list:
        """Raccourcis actifs aussi dans les fenêtres détachées."""
        return [a for a in (getattr(self, "actionUndo", None), getattr(self, "actionRedo", None),
                            self.actionSave, self.actionQuit) if a is not None]

    def _window(self, current, size, attach):
        """Fenêtre détachée existante (réutilisée) ou nouvelle ; sa croix appelle attach."""
        if current is not None:
            return current
        window = DetachedWindow(self, size)
        window.addActions(self.shared_actions())
        window.closed.connect(attach)
        return window

    @property
    def preview_detached(self) -> bool:
        return self.preview_window is not None and self.preview_window.content is not None

    @property
    def library_detached(self) -> bool:
        return self.library_window is not None and self.library_window.content is not None

    def toggle_preview(self):
        self.attach_preview() if self.preview_detached else self.detach_preview()

    def toggle_library(self):
        self.attach_library() if self.library_detached else self.detach_library()

    def detach_preview(self):
        """Aperçu en unités physiques dans sa fenêtre ; l'image prend toute la hauteur."""
        if self.preview_detached:
            return
        self._preview_sizes = self.center.sizes()
        self.preview_window = self._window(self.preview_window, (1000, 500), self.attach_preview)
        app = QtWidgets.QApplication.applicationName()
        self.preview_window.assign(self.preview, f"Aperçu en unités physiques — {app}")
        self.actionDetachPreview.setText("Réintégrer l'aperçu")
        self.preview_window.show()
        self.preview_window.raise_()

    def attach_preview(self, *_):
        """Aperçu remis sous l'image, à sa hauteur d'avant."""
        if not self.preview_detached:
            return
        widget = self.preview_window.release()
        self.center.insertWidget(1, widget)
        if self._preview_sizes:
            self.center.setSizes(self._preview_sizes)
        self.actionDetachPreview.setText("Détacher l'aperçu")

    def detach_library(self):
        """Panneau de la librairie dans sa fenêtre ; le dock est masqué."""
        if self.library_detached:
            return
        self.library_window = self._window(self.library_window, (1100, 450), self.attach_library)
        self.library.setParent(None)
        self.library_dock.hide()
        self.actionLibraryPanel.setEnabled(False)
        app = QtWidgets.QApplication.applicationName()
        self.library_window.assign(self.library, f"Librairie — {app}")
        self.actionDetachLibrary.setText("Réintégrer la librairie")
        self.library_window.show()
        self.library_window.raise_()

    def attach_library(self, *_):
        """Librairie remise dans son dock."""
        if not self.library_detached:
            return
        widget = self.library_window.release()
        self.library_dock.setWidget(widget)
        self.library_dock.show()
        self.actionLibraryPanel.setEnabled(True)
        self.actionDetachLibrary.setText("Détacher la librairie")

    def attach_all(self):
        """Fermeture de la fenêtre principale : panneaux réintégrés, fenêtres masquées."""
        self.attach_preview()
        self.attach_library()

    def refresh_theme(self):
        """Couleurs des graphiques : à rappeler après theme.apply()."""
        colors = theme.colors()
        self.canvas.setBackground(colors["graph_bg"])
        self.preview.setBackground(colors["graph_bg"])
        theme.style_plot(self.preview_plot)

    def message(self, text: str, timeout: int = 0):
        self.statusBar().showMessage(text, timeout)

    def ask(self, title: str, text: str) -> bool:
        """Question oui / non. Sans écran : self.answer, la question gardée pour les tests."""
        if QtWidgets.QApplication.platformName() == "offscreen":
            self.last_question = text
            return bool(self.answer)
        answer = QtWidgets.QMessageBox.question(
            self, title, text, QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No)
        return answer == QtWidgets.QMessageBox.StandardButton.Yes

    def error(self, title: str, text: str):
        if QtWidgets.QApplication.platformName() == "offscreen":
            self.message(f"{title} : {text}")
            self.last_error = text          # lu par les tests
            return
        QtWidgets.QMessageBox.warning(self, title, text)

    # ============================================================ glisser-déposer
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()

    def closeEvent(self, event):
        guard = self.close_guard() if self.close_guard is not None else None
        if guard is not None and not guard():
            event.ignore()
            return
        self.closing.emit()
        super().closeEvent(event)
