# controller/main_controller.py
"""
Contrôleur principal : relie la fenêtre (canevas, arborescence, paramètres, table) au
document numérisé (model.document) et aux calculs (calibration, extraction, ajustement).
"""
import dataclasses
import json
import pathlib
import subprocess
import sys
import weakref

import numpy as np
import pyqtgraph as pg
from PyQt6 import QtCore, QtGui, QtWidgets

from formules import FormulaError, units
from qtsocle import options_panel, settings, theme
from ressources import app_settings

from model import document, export, extraction, fit, library, mask, pdfimport, plecs, sheet
from model.calibration import (AxisCalibration, CalibrationError, orthogonal_points,
                               to_four_points)
from model.library import LibraryError
from model.plecs import PlecsError
from controller.commands import (CalibrationCommand, InsertCommand, MaskCommand,
                                 PointsCommand, points_state, same_points)
from controller.compare_controller import CompareController
from controller.library_controller import LibraryController
from view import zoom
from view.canvas import Mode
from view.compare_window import CompareWindow
from view.dialogs import CalibrationDialog, format_value, parse_value
from view.main_window import IMAGE_SUFFIXES, qimage_to_array
from view.pdf_import_dialog import PdfImportDialog

ROLE = QtCore.Qt.ItemDataRole.UserRole + 1
CLICK_TOLERANCE = 7          # pixels de l'écran
MODEL_SAMPLES = 300
UNDO_LIMIT = 200


class MainController(QtCore.QObject):

    def __init__(self, view, data_dir):
        super().__init__()
        self.view = view
        self.data_dir = pathlib.Path(data_dir)
        self.settings_path = self.data_dir / "settings.json"
        self.schema = app_settings.schema(str(self.data_dir / "library"))
        self.options = settings.load(self.settings_path,
                                     {"dark_mode": False, "last_dir": "",
                                      **options_panel.schema_defaults(self.schema)})

        self.component = document.Component()
        self.path = None                 # fichier du projet
        self.dirty = False
        self.graph_index = None
        self.dataset_index = None
        self.calibration_clicks = []     # points pointés pendant la calibration (bruts)
        self.drag_index = None
        self.drag_before = None          # état des points au début d'un glisser
        self.drag_text = ""
        self.drag_selected = None
        self.selected_point = None       # indice du point sélectionné de la courbe
        self.calibration_marker = None   # repère sélectionné (indice dans markers())
        self.calibration_drag = None     # repères pendant le glisser d'un repère
        self.last_paint = None
        self.mask_before = None          # masque au début d'un coup de pinceau
        self._loading = False            # remplissage des paramètres en cours
        self._outside_dirty = False      # modifications hors de la pile (propriétés)
        self.compare = None              # contrôleur de la fenêtre de comparaison
        self.read_only = False           # fiche sans projet : consultation seulement

        # annuler / refaire : pile parentée à la vue, actions dans la barre et le menu
        self.undo_stack = QtGui.QUndoStack(view)
        self.undo_stack.setUndoLimit(UNDO_LIMIT)
        self.undo_stack.cleanChanged.connect(self._update_title)
        self.undo_stack.indexChanged.connect(self._update_title)
        view.add_history_actions(self.undo_stack.createUndoAction(view, "Annuler"),
                                 self.undo_stack.createRedoAction(view, "Refaire"))

        # modèles Qt parentés à leur vue : détruits avec elle, dans l'ordre
        self.tree_model = QtGui.QStandardItemModel(view.tree)
        view.tree.setModel(self.tree_model)
        self.library = LibraryController(view.library, self.options)

        # slots en méthodes liées (pas de lambda qui garderait le contrôleur en vie)
        view.actionNew.triggered.connect(self.new_component)
        view.actionOpenImage.triggered.connect(self.open_image)
        view.actionPaste.triggered.connect(self.paste_image)
        view.actionOpen.triggered.connect(self.open_project)
        view.actionImportPdf.triggered.connect(self.open_pdf)
        if not pdfimport.available():
            view.actionImportPdf.setEnabled(False)
            view.actionImportPdf.setToolTip("Import PDF indisponible : installez pdfminer.six "
                                            "et pypdfium2")
        view.actionSave.triggered.connect(self.save_project)
        view.actionSaveAs.triggered.connect(self.save_project_as)
        view.actionExportCsv.triggered.connect(self.export_csv)
        view.actionExportGrid.triggered.connect(self.export_grid)
        view.actionExportComponent.triggered.connect(self.export_component)
        view.actionExportPlecs.triggered.connect(self.export_plecs)
        view.actionCompare.triggered.connect(self.open_compare)
        view.actionPublish.triggered.connect(self.publish)
        view.actionLibraryOpen.triggered.connect(self.library_open)
        view.actionLibraryCompare.triggered.connect(self.library_compare)
        view.actionLibraryRemove.triggered.connect(self.library_remove)
        view.actionLibraryReveal.triggered.connect(self.library_reveal)
        view.actionLibraryReload.triggered.connect(self.library.reload)
        view.library.table.doubleClicked.connect(self.library_open)
        view.actionCopyTable.triggered.connect(self.copy_table)
        view.actionCopyLut.triggered.connect(self.copy_lut)
        view.actionQuit.triggered.connect(view.close)
        view.modeGroup.triggered.connect(self.mode_triggered)
        view.actionClearMask.triggered.connect(self.clear_mask)
        view.actionDetection.toggled.connect(self.refresh_detection)
        view.actionExtract.triggered.connect(self.extract)
        view.actionFit.triggered.connect(self.fit_model)
        view.actionAddCurve.triggered.connect(self.add_dataset)
        view.actionSplit.triggered.connect(self.split_points)
        view.actionDelete.triggered.connect(self.delete_selection)
        view.actionOptions.triggered.connect(self.edit_options)
        view.actionDark.toggled.connect(self.set_dark_mode)
        view.closing.connect(self.save_settings)
        view.closing.connect(self.release_history)
        # projet modifié : proposé à l'enregistrement avant fermeture (référence faible :
        # la fenêtre ne garde pas le contrôleur en vie)
        view.close_guard = weakref.WeakMethod(self._ask_discard)
        view.files_dropped.connect(self.open_files)
        view.canvas.pressed.connect(self.canvas_pressed)
        view.canvas.moved.connect(self.canvas_moved)
        view.canvas.released.connect(self.canvas_released)
        view.canvas.nudged.connect(self.nudge)
        view.canvas.key_command.connect(self.key_command)
        view.table.currentCellChanged.connect(self.table_current_changed)
        view.tree.selectionModel().currentChanged.connect(self.tree_current_changed)
        self.tree_model.itemChanged.connect(self.tree_item_changed)
        view.table.cellChanged.connect(self.table_cell_changed)
        for name, param in view.params.items():
            param.sigTreeStateChanged.connect(getattr(self, f"_{name}_changed"))

        view.canvas.set_brush_radius(self.options["brush_radius"])
        view.actionDark.setChecked(bool(self.options["dark_mode"]))
        self.apply_theme()
        self.refresh_all()

    # ============================================================ accès courants
    @property
    def graph(self):
        if self.graph_index is None or self.graph_index >= len(self.component.graphs):
            return None
        return self.component.graphs[self.graph_index]

    @property
    def dataset(self):
        graph = self.graph
        if graph is None or self.dataset_index is None or self.dataset_index >= len(graph.datasets):
            return None
        return graph.datasets[self.dataset_index]

    def set_dirty(self, dirty=True):
        """Modification hors de la pile (propriétés) ; False : projet enregistré."""
        self._outside_dirty = dirty
        self._update_title()

    def _update_title(self, *_):
        self.dirty = self._outside_dirty or not self.undo_stack.isClean()
        name = self.path.name if self.path else "sans titre"
        if self.read_only:
            name += " [lecture seule]"
        app = QtWidgets.QApplication.applicationName()
        self.view.setWindowTitle(f"{'* ' if self.dirty else ''}{name} — {app}")

    # ------------------------------------------------------------ lecture seule
    def _editable(self, quiet=False) -> bool:
        """False (et un message) quand le composant ouvert est une fiche en lecture seule."""
        if self.read_only and not quiet:
            self.view.message("Fiche en lecture seule : rien n'est modifiable (ouvrez un "
                              "projet, ou créez-en un nouveau)", 5000)
        return not self.read_only

    def _apply_read_only(self):
        """Actions de modification désactivées, propriétés et table figées."""
        view, editable = self.view, not self.read_only
        for mode, action in view.modeActions.items():
            action.setEnabled(editable or mode == Mode.NAVIGATE)
        for action in (view.actionSave, view.actionSaveAs, view.actionPublish,
                       view.actionOpenImage, view.actionPaste, view.actionClearMask,
                       view.actionDetection, view.actionExtract, view.actionFit,
                       view.actionAddCurve, view.actionSplit, view.actionDelete,
                       view.actionExportPlecs):
            action.setEnabled(editable)
        view.parameters.setEnabled(editable)
        view.table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked
            | QtWidgets.QAbstractItemView.EditTrigger.EditKeyPressed
            | QtWidgets.QAbstractItemView.EditTrigger.AnyKeyPressed if editable
            else QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        if not editable:
            self.set_mode(Mode.NAVIGATE)

    def release_history(self):
        """
        À la fermeture : la pile se vide en étant détruite (destructeur de QUndoStack) et
        émet alors indexChanged / cleanChanged, vers une fenêtre déjà détruite.
        """
        self.undo_stack.cleanChanged.disconnect(self._update_title)
        self.undo_stack.indexChanged.disconnect(self._update_title)

    def push(self, command):
        """Commande dans la pile (son redo() est appliqué) ; ignorée si elle ne change rien."""
        if not getattr(command, "empty", False):
            self.undo_stack.push(command)

    def select(self, graph_index, dataset_index=None):
        self.graph_index = graph_index
        graph = self.graph
        if graph is not None and dataset_index is None and graph.datasets:
            dataset_index = 0
        self.dataset_index = dataset_index
        self.calibration_clicks = []
        self.selected_point = None
        self.calibration_marker = None
        self.refresh_all(reset_view=True)

    # ------------------------------------------------------------ retours des commandes
    def _focus(self, graph, dataset=None) -> bool:
        """Rend courants graph (et dataset), désignés par identité ; True si le graphique change."""
        index = next((i for i, g in enumerate(self.component.graphs) if g is graph), None)
        changed = index != self.graph_index
        self.graph_index = index
        if changed:
            self.calibration_clicks = []
            self.selected_point = None
            self.calibration_marker = None
        if graph is not None and dataset is not None:
            self.dataset_index = next((i for i, d in enumerate(graph.datasets) if d is dataset),
                                      self.dataset_index)
        return changed

    def show_points(self, graph, dataset, selected):
        changed = self._focus(graph, dataset)
        self.selected_point = selected
        if changed:
            self.refresh_all(reset_view=True)
        else:
            self.refresh_dataset_views()

    def show_calibration(self, graph, marker):
        changed = self._focus(graph)
        self.calibration_marker = marker
        self.calibration_clicks = []
        self.refresh_all(reset_view=changed)

    def show_mask(self, graph, dataset):
        if self._focus(graph, dataset):
            self.refresh_all(reset_view=True)
            return
        self.view.canvas.set_mask(dataset.mask)
        self.refresh_detection()

    def show_structure(self, graph, item):
        """Après ajout / suppression : graph None -> item est un graphique."""
        graphs = self.component.graphs
        if graph is None:
            if item is not None:
                self._focus(item)
                self.dataset_index = 0 if item.datasets else None
            else:
                self.graph_index = min(self.graph_index or 0, len(graphs) - 1) if graphs else None
                self.dataset_index = 0 if self.graph and self.graph.datasets else None
            self.calibration_clicks = []
            self.selected_point = None
            self.refresh_all(reset_view=True)
            return
        changed = self._focus(graph)
        if item is not None:
            self.dataset_index = next(i for i, d in enumerate(graph.datasets) if d is item)
        else:
            self.dataset_index = (min(self.dataset_index or 0, len(graph.datasets) - 1)
                                  if graph.datasets else None)
        self.selected_point = None
        self.refresh_all(reset_view=changed)

    # ============================================================ thème et réglages
    def set_dark_mode(self, enabled: bool):
        self.options["dark_mode"] = bool(enabled)
        self.apply_theme()

    def apply_theme(self):
        theme.apply(QtWidgets.QApplication.instance(), self.options["dark_mode"],
                    extra_qss=theme.ITEM_VIEW_QSS)
        self.view.refresh_theme()
        if self.compare is not None:
            self.compare.view.refresh_theme()

    # ============================================================ comparaison
    def current_sheet(self):
        """
        Fiche du composant ouvert (courbes calibrées), None s'il n'en a pas, ou si c'est
        une fiche ouverte en lecture seule (le comparateur la lit déjà dans son fichier).
        """
        if self.read_only:
            return None
        data = export.component_dict(self.component)
        return data if any(g["curves"] for g in data["graphs"]) else None

    def open_compare(self):
        """
        Fenêtre non modale, créée une fois : enfant de la fenêtre principale (détruite
        avec elle), le composant ouvert lu par référence faible.
        """
        if self.compare is None:
            window = CompareWindow(self.view)
            self.compare = CompareController(window, self.options,
                                             weakref.WeakMethod(self.current_sheet))
        else:
            self.compare.reload()
        self.compare.view.show()
        self.compare.view.raise_()
        self.compare.view.activateWindow()

    # ============================================================ librairie
    def _library_folder(self) -> pathlib.Path:
        return pathlib.Path(self.options["library_dir"])

    @staticmethod
    def _same_file(a, b) -> bool:
        try:
            return a is not None and b is not None and \
                pathlib.Path(a).resolve() == pathlib.Path(b).resolve()
        except OSError:
            return False

    def publish(self, *_) -> bool:
        """
        Fiche en lecture seule : refusé (rien à republier, pas d'image).
        Publie le composant ouvert : fiche, projet et description PLECS dans
        <librairie>/<Catégorie>/<Référence>. Une autre entrée de même référence est
        remplacée après confirmation (ses fichiers vont dans la corbeille de la librairie).
        Le projet ouvert devient celui de la librairie s'il n'avait pas de fichier, ou
        s'il était déjà celui de la librairie.
        """
        if not self._editable():
            return False
        if not any(g.calibrated and any(len(d.pixels) for d in g.datasets)
                   for g in self.component.graphs):
            self.view.error("Publier", "Aucune courbe relevée sur un graphique calibré : "
                            "rien à publier.")
            return False
        folder = self._library_folder()
        entries, _ = library.scan(folder)
        try:
            clash = library.conflicts(entries, folder, self.component)
        except LibraryError as error:
            self.view.error("Publier", str(error))
            return False
        own = [e for e in clash if self._same_file(e.project_path, self.path)]
        others = [e for e in clash if e not in own]
        if others:
            names = "\n".join(f"- {e.title} : {e.folder}" for e in others)
            if not self.view.ask("Publier dans la librairie",
                                 f"La librairie contient déjà :\n{names}\n\nLe remplacer ? "
                                 "Les fichiers actuels iront dans la corbeille de la librairie "
                                 f"({library.TRASH})."):
                return False
        directory, stem = library.target(folder, self.component)
        moved = [e for e in own if not (e.folder == directory and e.stem == stem)]
        try:
            if others or moved:             # catégorie ou référence changée : ancienne entrée
                library.remove(others + moved, folder)
            entry, warnings = library.publish(self.component, folder)
        except (LibraryError, OSError) as error:
            self.view.error("Publier", str(error))
            self.library.reload()
            return False
        if self.path is None or own:
            self.path = entry.project_path
            self.undo_stack.setClean()
            self.set_dirty(False)
        self.library.reload(select=entry.key)
        if warnings:
            self.view.error("Publier", f"Publié dans {entry.folder}\n\nÀ vérifier :\n- "
                            + "\n- ".join(warnings))
        else:
            self.view.message(f"Publié : {entry.title} ({entry.folder})", 6000)
        return True

    def library_open(self, *_) -> bool:
        """Ouvre le projet du composant choisi dans la librairie."""
        entries = self.library.selected()
        if len(entries) != 1:
            self.view.message("Choisissez un composant dans la librairie", 4000)
            return False
        entry = entries[0]
        path = entry.project_path or entry.sheet_path      # fiche seule : lecture seule
        if self._same_file(path, self.path) or not self._ask_discard():
            return False
        self.load_project(path)
        return self._same_file(path, self.path)

    def library_compare(self, *_) -> int:
        """Comparateur ouvert sur les courbes des composants choisis."""
        entries = self.library.selected()
        if not entries:
            self.view.message("Choisissez des composants dans la librairie "
                              "(Ctrl+clic pour plusieurs)", 4000)
            return 0
        self.open_compare()
        return self.compare.show_sources([e.data_path for e in entries])

    def library_remove(self, *_) -> bool:
        """Met les composants choisis dans la corbeille de la librairie."""
        entries = self.library.selected()
        if not entries:
            return False
        names = "\n".join(f"- {e.title}" for e in entries[:10])
        if len(entries) > 10:
            names += f"\n- ... ({len(entries) - 10} de plus)"
        if not self.view.ask("Librairie", f"Mettre à la corbeille de la librairie :\n{names}\n\n"
                             f"Les fichiers sont déplacés dans {library.TRASH}, d'où ils "
                             "peuvent être récupérés."):
            return False
        try:
            trash = library.remove(entries, self._library_folder())
        except OSError as error:
            self.view.error("Librairie", str(error))
            self.library.reload()
            return False
        if not self.read_only and any(self._same_file(e.project_path, self.path)
                                      for e in entries):
            self.path = None                # le projet ouvert n'a plus de fichier
            self.set_dirty(True)
        self.library.reload()
        self.view.message(f"{len(entries)} composant(s) dans {trash}", 6000)
        return True

    def library_reveal(self, *_):
        """Explorateur sur le fichier du composant choisi, sinon sur la librairie."""
        entries = self.library.selected()
        target = entries[0].data_path if entries else self._library_folder()
        if QtWidgets.QApplication.platformName() == "offscreen":
            return target
        if not entries:
            target.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32" and entries:
            subprocess.Popen(["explorer", f"/select,{target}"])
        else:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(
                str(target if not entries else target.parent)))
        return target

    def edit_options(self):
        dialog = options_panel.OptionsPannel(self.schema, self.options, self.view)
        if dialog.exec():
            self.apply_options(dialog.getOptions())

    def apply_options(self, values: dict):
        previous = self.options.get("library_dir")
        self.options.update(values)
        self.view.canvas.set_brush_radius(self.options["brush_radius"])
        if self.options.get("library_dir") != previous:
            self.library.reload()
        self.save_settings()

    def save_settings(self):
        settings.save(self.settings_path, self.options)

    # ============================================================ fichiers
    def _ask_discard(self) -> bool:
        if not self.dirty or QtWidgets.QApplication.platformName() == "offscreen":
            return True
        answer = QtWidgets.QMessageBox.question(
            self.view, "Projet modifié", "Enregistrer les modifications ?",
            QtWidgets.QMessageBox.StandardButton.Save
            | QtWidgets.QMessageBox.StandardButton.Discard
            | QtWidgets.QMessageBox.StandardButton.Cancel)
        if answer == QtWidgets.QMessageBox.StandardButton.Save:
            return self.save_project()
        return answer == QtWidgets.QMessageBox.StandardButton.Discard

    def new_component(self):
        if not self._ask_discard():
            return
        self.set_component(document.Component(), None)

    def set_component(self, component, path, read_only=False):
        self.component = component
        self.path = pathlib.Path(path) if path else None
        self.read_only = read_only
        self.graph_index = 0 if component.graphs else None
        self.dataset_index = 0 if component.graphs and component.graphs[0].datasets else None
        self.selected_point = None
        self.calibration_marker = None
        self.calibration_clicks = []
        self.undo_stack.clear()
        self.set_dirty(False)
        self._apply_read_only()
        self.refresh_all(reset_view=True)

    def _dialog_dir(self) -> str:
        return self.options.get("last_dir") or str(pathlib.Path.home())

    def _remember_dir(self, path):
        self.options["last_dir"] = str(pathlib.Path(path).parent)

    def open_image(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self.view, "Image du graphique", self._dialog_dir(),
            "Images (" + " ".join(f"*{s}" for s in IMAGE_SUFFIXES) + ")")
        if path:
            self.add_image_file(path)

    def add_image_file(self, path):
        image = QtGui.QImage(str(path))
        if image.isNull():
            self.view.error("Image", f"Impossible de lire {path}")
            return
        self._remember_dir(path)
        self.add_image(qimage_to_array(image), pathlib.Path(path).stem, str(path))

    def paste_image(self):
        clipboard = QtWidgets.QApplication.clipboard()
        image = clipboard.image()
        if image.isNull():
            urls = [u.toLocalFile() for u in clipboard.mimeData().urls() if u.isLocalFile()]
            if urls:
                self.open_files(urls)
                return
            self.view.message("Pas d'image dans le presse-papiers", 4000)
            return
        self.add_image(qimage_to_array(image), None, "presse-papiers")

    def add_image(self, array: np.ndarray, name=None, source=""):
        if not self._editable():
            return
        graph = self.component.add_graph(array, name, source)
        graph.datasets[0].tolerance = float(self.options["tolerance"])
        graphs = self.component.graphs
        graphs.remove(graph)
        self.push(InsertCommand(self, graphs, len(graphs), graph, True, "Ajouter une image"))
        self.set_mode(Mode.CALIBRATE)

    def open_files(self, paths):
        for path in paths:
            if str(path).lower().endswith(".json"):
                self.load_project(path)
            elif str(path).lower().endswith(".pdf"):
                self.import_pdf(path)
            elif pathlib.Path(path).suffix.lower() in IMAGE_SUFFIXES:
                self.add_image_file(path)

    def open_project(self):
        if not self._ask_discard():
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self.view, "Ouvrir un projet", self._dialog_dir(),
            f"Projets ParamDigitizer (*{document.PROJECT_SUFFIX});;JSON (*.json)")
        if path:
            self.load_project(path)

    def load_project(self, path):
        """Projet *.pdig.json, ou fiche de composant (ouverte en lecture seule)."""
        try:
            data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("format") == export.COMPONENT_FORMAT:
                self.open_sheet(path, data)
                return
            component = document.Component.from_dict(data)
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.view.error("Ouverture", f"{path} :\n{error}")
            return
        self._remember_dir(path)
        self.set_component(component, path)

    def open_pdf(self, *_):
        if not self._ask_discard():
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self.view, "Importer une datasheet PDF", self._dialog_dir(), "PDF (*.pdf)")
        if path:
            self.import_pdf(path, ask=False)

    def import_pdf(self, path, choose=None, ask=True) -> bool:
        """
        Datasheet PDF vectorielle -> nouveau composant (sans fichier, à enregistrer) :
        graphiques trouvés, choisis dans PdfImportDialog (sans écran, ou choose donné :
        ces indices, sinon tous), calibrés, courbes relevées. Avertissements dans les notes
        du composant.
        """
        if ask and not self._ask_discard():
            return False
        path = pathlib.Path(path)
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            found = pdfimport.analyse(path)
            component, _ = pdfimport.to_component(path, found) if found else (None, [])
        except pdfimport.PdfImportError as error:
            self.view.error("Import PDF", str(error))
            return False
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self._remember_dir(path)
        if not found:
            self.view.error("Import PDF", f"{path.name} : aucun graphique vectoriel trouvé. "
                            "PDF scanné ou graphiques en image : capturez-les "
                            "(Ctrl+V) ou ajoutez-les comme images (Ctrl+I).")
            return False
        if choose is None and QtWidgets.QApplication.platformName() != "offscreen":
            dialog = PdfImportDialog(path.name, component.graphs, found, self.view)
            if not dialog.exec():
                return False
            choose = dialog.selected()
        if choose is not None:
            choose = [i for i in choose if 0 <= i < len(found)]
            if not choose:
                self.view.message("Aucun graphique choisi : rien n'est importé", 5000)
                return False
            found = [found[i] for i in choose]
            component.graphs = [component.graphs[i] for i in choose]
        component.notes, warnings = pdfimport.import_notes(path.name, found)
        self.set_component(component, None)
        self.set_dirty(True)                    # nouveau projet, pas encore enregistré
        curves = sum(len(g.datasets) for g in component.graphs)
        text = f"{path.name} : {len(component.graphs)} graphique(s), {curves} courbe(s) importés"
        if warnings:
            text += f" ; {len(warnings)} point(s) à vérifier (notes du composant)"
        self.view.message(text, 10000)
        return True

    def open_sheet(self, path, data=None) -> bool:
        """
        Fiche sans projet, en lecture seule : graphiques redessinés sur fond quadrillé
        (pas d'image d'origine), courbes, modèles, table, aperçu et exports.
        """
        try:
            if data is None:
                data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
            component, warnings = sheet.component_from_sheet(data, str(path))
        except (OSError, ValueError) as error:
            self.view.error("Ouverture", f"{path} :\n{error}")
            return False
        self._remember_dir(path)
        self.set_component(component, path, read_only=True)
        text = "Fiche ouverte en lecture seule : pas d'image d'origine, courbes sur fond quadrillé"
        if warnings:
            self.view.error("Ouverture", text + "\n\nÀ vérifier :\n- " + "\n- ".join(warnings))
        else:
            self.view.message(text, 8000)
        return True

    def save_project(self) -> bool:
        if not self._editable():
            return False
        if self.path is None:
            return self.save_project_as()
        return self.write_project(self.path)

    def save_project_as(self) -> bool:
        if not self._editable():
            return False
        default = self.path or pathlib.Path(self._dialog_dir()) / (
            (self.component.part_number or self.component.name or "composant")
            + document.PROJECT_SUFFIX)
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self.view, "Enregistrer le projet", str(default),
            f"Projets ParamDigitizer (*{document.PROJECT_SUFFIX})")
        if not path:
            return False
        if not path.endswith(document.PROJECT_SUFFIX):
            path = str(pathlib.Path(path).with_suffix("")).removesuffix(".pdig") + document.PROJECT_SUFFIX
        return self.write_project(path)

    def write_project(self, path) -> bool:
        try:
            document.save(self.component, path)
        except OSError as error:
            self.view.error("Enregistrement", str(error))
            return False
        self.path = pathlib.Path(path)
        self._remember_dir(path)
        self.undo_stack.setClean()
        self.set_dirty(False)
        self.view.message(f"Projet enregistré : {path}", 5000)
        return True

    # ============================================================ exports
    def _save_name(self, title, default_name, filters):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self.view, title, str(pathlib.Path(self._dialog_dir()) / default_name), filters)
        if path:
            self._remember_dir(path)
        return path

    def _need_calibration(self) -> bool:
        if self.graph is None or not self.graph.calibrated:
            self.view.error("Calibration", "Calibrez d'abord les axes du graphique.")
            return False
        return True

    def export_csv(self):
        if not self._need_calibration():
            return
        path = self._save_name("Courbes du graphique", f"{self.graph.name}.csv", "CSV (*.csv)")
        if path:
            export.write_text(path, export.csv_text(self.graph, separator=self.options["separator"],
                                                    decimal=self.options["decimal"]))

    def export_grid(self):
        if not self._need_calibration():
            return
        graph = self.graph
        settings_ = graph.extraction
        try:
            grid = extraction.make_grid(settings_.grid_start, settings_.grid_stop,
                                        settings_.grid_step, settings_.grid_count,
                                        graph.calibration.log_x)
        except ValueError as error:
            self.view.error("Grille", str(error))
            return
        path = self._save_name("Courbes sur une grille commune", f"{graph.name}_grille.csv",
                               "CSV (*.csv)")
        if not path:
            return
        table = export.common_grid(graph, grid, method=settings_.interpolation,
                                   extrapolate=settings_.extrapolate)
        sep, dec = self.options["separator"], self.options["decimal"]
        header = [graph.x_axis.label("X")] + [
            f"{graph.y_axis.label('Y')} [{d.name}{' ; ' + d.condition if d.condition else ''}]"
            for d in graph.datasets]
        lines = [sep.join(header)]
        for row in table:
            lines.append(sep.join("" if not np.isfinite(v) else
                                  format(v, ".8g").replace(".", dec) for v in row))
        export.write_text(path, "\n".join(lines) + "\n")

    def export_plecs(self, path=None) -> bool:
        """Description thermique PLECS ; erreurs et avertissements affichés."""
        try:
            text, warnings = plecs.build(self.component)
        except PlecsError as error:
            self.view.error("Export PLECS", str(error))
            return False
        if path is None:
            name = library.safe_name(self.component.part_number or self.component.name) \
                or "composant"
            path = self._save_name("Composant pour PLECS", f"{name}.xml", "XML (*.xml)")
            if not path:
                return False
        export.write_text(path, text)
        if warnings:
            self.view.error("Export PLECS", f"Fichier écrit : {path}\n\nÀ vérifier :\n- "
                            + "\n- ".join(warnings))
        else:
            self.view.message(f"Fichier PLECS écrit : {path}", 6000)
        return True

    def export_component(self):
        """Fiche seule, hors de la librairie (pour la librairie : Publier)."""
        name = library.safe_name(self.component.part_number or self.component.name) \
            or "composant"
        path = self._save_name("Fiche du composant", f"{name}.json", "JSON (*.json)")
        if path:
            export.write_component(self.component, path)
            self.view.message(f"Fiche écrite : {path}", 5000)

    def copy_table(self):
        if self.dataset is None:
            return
        data = self.dataset.data(self.graph.calibration)
        dec = self.options["decimal"]
        text = "\n".join("\t".join(format(v, ".8g").replace(".", dec) for v in row)
                         for row in data)
        QtWidgets.QApplication.clipboard().setText(text + "\n")
        self.view.message(f"{len(data)} points copiés", 3000)

    def copy_lut(self):
        if self.dataset is None or not self._need_calibration():
            return
        QtWidgets.QApplication.clipboard().setText(export.lut_formula(self.graph, self.dataset))
        self.view.message("Table interp(x; ...) copiée", 3000)

    # ============================================================ arborescence
    def rebuild_tree(self):
        self._loading = True
        self.tree_model.clear()
        root = self.tree_model.invisibleRootItem()
        current = None
        for g, graph in enumerate(self.component.graphs):
            mark = "" if graph.calibrated else "  (non calibré)"
            item = QtGui.QStandardItem(theme.icon("image"), graph.name + mark)
            item.setData((g, None), ROLE)
            root.appendRow(item)
            if g == self.graph_index and self.dataset_index is None:
                current = item
            for d, dataset in enumerate(graph.datasets):
                label = dataset.name + (f"  [{dataset.condition}]" if dataset.condition else "")
                child = QtGui.QStandardItem(label + f"  ({len(dataset)})")
                child.setData((g, d), ROLE)
                child.setCheckable(True)
                child.setCheckState(QtCore.Qt.CheckState.Checked if dataset.visible
                                    else QtCore.Qt.CheckState.Unchecked)
                child.setData(QtGui.QColor(dataset.color), QtCore.Qt.ItemDataRole.DecorationRole)
                item.appendRow(child)
                if g == self.graph_index and d == self.dataset_index:
                    current = child
        self.view.tree.expandAll()
        if current is not None:
            self.view.tree.selectionModel().setCurrentIndex(
                current.index(), QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self._loading = False

    def tree_current_changed(self, current, _previous):
        if self._loading or not current.isValid():
            return
        g, d = current.data(ROLE)
        if g == self.graph_index and d == self.dataset_index:
            return
        if g != self.graph_index:
            self.select(g, d)
        else:
            self.dataset_index = d
            self.selected_point = None
            self.refresh_all()

    def tree_item_changed(self, item):
        if self._loading:
            return
        g, d = item.data(ROLE)
        if d is None:
            return
        dataset = self.component.graphs[g].datasets[d]
        dataset.visible = item.checkState() == QtCore.Qt.CheckState.Checked
        if not self.read_only:          # affichage seulement : la fiche reste intacte
            self.set_dirty()
        self.refresh_curves()

    def add_dataset(self):
        if not self._editable():
            return
        graph = self.graph
        if graph is None:
            return
        dataset = graph.add_dataset(tolerance=self.options["tolerance"])
        graph.datasets.remove(dataset)
        self.push(InsertCommand(self, graph.datasets, len(graph.datasets), dataset, True,
                                "Nouvelle courbe", graph=graph))
        if self.view.canvas.mode not in (Mode.ADD, Mode.PAINT, Mode.ERASE):
            self.set_mode(Mode.ADD)

    def delete_selection(self):
        if not self._editable():
            return
        if self.graph is None:
            return
        graph = self.graph
        if self.dataset is not None:
            self.push(InsertCommand(self, graph.datasets, self.dataset_index, self.dataset,
                                    False, f"Supprimer « {self.dataset.name} »", graph=graph))
        else:
            self.push(InsertCommand(self, self.component.graphs, self.graph_index, graph,
                                    False, f"Supprimer « {graph.name} »"))

    # ============================================================ modes
    def mode_triggered(self, action):
        self.set_mode(action.data())

    def set_mode(self, mode: Mode):
        refused = self.read_only and mode != Mode.NAVIGATE
        if refused:
            mode = Mode.NAVIGATE
        self.view.modeActions[mode].setChecked(True)
        self.view.canvas.set_mode(mode)
        self.drag_index = None
        self.calibration_marker = None
        if mode == Mode.CALIBRATE:
            self.calibration_clicks = []
            self.refresh_calibration_markers()
        self.refresh_selection()
        self.view.message(self._mode_hint(mode))
        if refused:
            self._editable()            # message : lecture seule

    # ------------------------------------------------------------ calibration : repères
    @property
    def orthogonal(self) -> bool:
        """Option : repère orthonormé, 3 clics (O, X2, Y2) au lieu de 4."""
        return bool(self.options.get("orthogonal_axes", True))

    def needed_clicks(self) -> int:
        return 3 if self.orthogonal else 4

    def click_markers(self, clicks=None) -> list:
        """Repères affichés pour les clics en cours (ramenés sur les axes en orthonormé)."""
        clicks = self.calibration_clicks if clicks is None else clicks
        if self.orthogonal and clicks:
            return orthogonal_points(*clicks)
        return list(clicks)

    def show_markers(self, markers, orthogonal):
        self.view.canvas.set_calibration_points(markers, orthogonal)

    def _mode_hint(self, mode: Mode) -> str:
        if mode == Mode.CALIBRATE:
            if self.orthogonal:
                labels = ("O : l'origine des axes (croisement de X et Y)",
                          "X2 : un point de l'axe X de valeur connue",
                          "Y2 : un point de l'axe Y de valeur connue")
            else:
                labels = ("X1 : un point de l'axe X de valeur connue",
                          "X2 : un autre point de l'axe X", "Y1 : un point de l'axe Y",
                          "Y2 : un autre point de l'axe Y")
            n = len(self.calibration_clicks)
            if n == 0 and self.graph is not None and self.graph.calibrated:
                return ("Calibration — cliquez un repère pour le déplacer (glisser ou flèches), "
                        f"ou {labels[0]} pour recommencer")
            return (f"Calibration — cliquez {labels[min(n, len(labels) - 1)]} ; flèches : ajuster "
                    "(Maj ×10, Ctrl ×0,1) ; molette : zoom")
        return {
            Mode.NAVIGATE: "Navigation — glisser : déplacer, molette : zoom",
            Mode.ADD: ("Clic : ajouter un point ; glisser : déplacer ; flèches : ajuster "
                       "(Maj ×10, Ctrl ×0,1) ; Suppr ; Tab : point suivant"),
            Mode.DELETE: "Clic sur un point : le supprimer",
            Mode.PAINT: "Peindre la zone de la courbe, puis Extraire (Ctrl+E)",
            Mode.ERASE: "Gommer le masque",
            Mode.PICK: "Clic sur la courbe : couleur recherchée par l'extraction",
        }[mode]

    # ============================================================ souris sur l'image
    def _tolerance(self) -> float:
        return CLICK_TOLERANCE * self.view.canvas.pixel_size()

    def canvas_pressed(self, x, y):
        graph = self.graph
        if graph is None or not self._editable(quiet=True):
            return
        mode = self.view.canvas.mode
        if mode == Mode.CALIBRATE:
            marker = self._nearest_marker(x, y) if not self.calibration_clicks else None
            if marker is not None:
                # repère existant : sélectionné, déplaçable au glisser et aux flèches
                self.calibration_marker = marker
                self.calibration_drag = (marker, self.calibration_points())
                self.refresh_selection()
                return
            self.calibration_marker = None
            self.calibration_clicks.append((x, y))
            self.show_markers(self.click_markers(), self.orthogonal)
            self.refresh_selection()
            if len(self.calibration_clicks) == self.needed_clicks():
                clicks = self.calibration_clicks
                self.finish_calibration(to_four_points(*clicks) if self.orthogonal else clicks)
            else:
                self.view.message(self._mode_hint(mode))
        elif mode == Mode.ADD:
            if self.dataset is None:
                self.add_dataset()
            dataset = self.dataset
            self.drag_before = points_state(dataset)
            self.drag_selected = self.selected_point
            index = dataset.nearest(x, y, self._tolerance())
            if index is None:
                index = dataset.add_pixel(x, y, graph.calibration)
                self.drag_text = "Ajouter un point"
            else:
                self.drag_text = "Déplacer un point"
            self.drag_index = index
            self.selected_point = index
            self.refresh_curves()
            self.refresh_selection()
        elif mode == Mode.DELETE:
            dataset = self.dataset
            if dataset is not None:
                index = dataset.nearest(x, y, self._tolerance())
                if index is not None:
                    self.delete_point(index)
        elif mode in (Mode.PAINT, Mode.ERASE):
            if self.dataset is None:
                self.add_dataset()
            self.mask_before = graph.mask_of(self.dataset).copy()
            self.last_paint = (x, y)
            self._paint((x, y), (x, y))
        elif mode == Mode.PICK:
            row, col = int(y), int(x)
            if (self.dataset is not None and 0 <= row < graph.image.shape[0]
                    and 0 <= col < graph.image.shape[1]):
                color = tuple(int(v) for v in graph.image[row, col, :3])
                self.dataset.curve_color = color
                self.set_dirty()
                self.fill_extraction()
                self.refresh_detection()
                self.view.message(f"Couleur de la courbe : RGB{color}", 4000)

    def canvas_moved(self, x, y, down):
        graph = self.graph
        if graph is None:
            return
        self.show_coordinates(x, y)
        if not down:
            self._preview_calibration(x, y)
            return
        mode = self.view.canvas.mode
        if mode == Mode.ADD and self.drag_index is not None and self.dataset is not None:
            self.dataset.move_pixel(self.drag_index, x, y)
            self.refresh_curves()
            self.refresh_selection()
        elif mode == Mode.CALIBRATE and self.calibration_drag is not None:
            marker, points = self.calibration_drag
            points[marker] = (x, y)
            orthogonal = len(points) == 3
            shown = orthogonal_points(*points) if orthogonal else points
            self.show_markers(shown, orthogonal)
            self.view.canvas.set_selection(shown[marker])
        elif mode in (Mode.PAINT, Mode.ERASE) and self.last_paint is not None:
            self._paint(self.last_paint, (x, y))
            self.last_paint = (x, y)

    def _preview_calibration(self, x, y):
        """Orthonormé : le prochain repère suit la souris, déjà ramené sur son axe."""
        if (self.view.canvas.mode != Mode.CALIBRATE or not self.orthogonal
                or len(self.calibration_clicks) not in (1, 2)):
            return
        self.show_markers(self.click_markers(self.calibration_clicks + [(x, y)]), True)

    def canvas_released(self, x, y):
        if not self._editable(quiet=True):
            return
        mode = self.view.canvas.mode
        if mode == Mode.ADD and self.drag_index is not None:
            dataset, graph = self.dataset, self.graph
            index = dataset.sort(graph.calibration, follow=self.drag_index)
            self.drag_index = None
            after = points_state(dataset)
            if same_points(self.drag_before, after):
                self.selected_point = index
                self.refresh_dataset_views()
            else:
                self.push(PointsCommand(self, graph, dataset, self.drag_before, after,
                                        self.drag_text, self.drag_selected, index))
        elif mode == Mode.CALIBRATE and self.calibration_drag is not None:
            marker, points = self.calibration_drag
            self.calibration_drag = None
            if points != self.calibration_points():
                self.move_markers(points, "Déplacer un repère d'axe")
        elif mode in (Mode.PAINT, Mode.ERASE) and self.last_paint is not None:
            self.last_paint = None
            text = "Peindre le masque" if mode == Mode.PAINT else "Gommer le masque"
            self.push(MaskCommand(self, self.graph, self.dataset, self.mask_before,
                                  self.dataset.mask, text))
            self.mask_before = None
            self.refresh_detection()

    def _paint(self, start, end):
        graph = self.graph
        target = graph.mask_of(self.dataset)
        radius = self.view.canvas.brush_radius
        mask.paint_stroke(target, start, end, radius, self.view.canvas.mode == Mode.PAINT)
        h, w = target.shape
        x0 = int(max(0, min(start[0], end[0]) - radius - 2))
        x1 = int(min(w, max(start[0], end[0]) + radius + 3))
        y0 = int(max(0, min(start[1], end[1]) - radius - 2))
        y1 = int(min(h, max(start[1], end[1]) + radius + 3))
        if x0 < x1 and y0 < y1:
            self.view.canvas.update_mask(target, x0, y0, x1, y1)

    # ============================================================ clavier et sélection
    def change_points(self, text, mutate, selected_after=None):
        """Applique mutate(dataset) et la pousse dans la pile (rien si rien ne change)."""
        graph, dataset = self.graph, self.dataset
        before = points_state(dataset)
        mutate(dataset)
        after = points_state(dataset)
        if same_points(before, after):
            self.refresh_dataset_views()
            return
        self.push(PointsCommand(self, graph, dataset, before, after, text,
                                self.selected_point, selected_after))

    def delete_point(self, index):
        remaining = len(self.dataset) - 1
        selected = min(index, remaining - 1) if remaining > 0 else None
        self.change_points("Supprimer un point", lambda d: d.remove_pixel(index), selected)

    def nudge(self, dx, dy):
        """Flèches : repère de calibration ou point sélectionné, appuis fusionnés."""
        graph = self.graph
        if graph is None or not self._editable(quiet=True):
            return
        mode = self.view.canvas.mode
        if mode == Mode.CALIBRATE:
            if self.calibration_clicks:
                x, y = self.calibration_clicks[-1]
                self.calibration_clicks[-1] = (x + dx, y + dy)
                self.show_markers(self.click_markers(), self.orthogonal)
                self.refresh_selection()
            elif graph.calibrated and self.calibration_marker is not None:
                points = self.calibration_points()
                x, y = points[self.calibration_marker]
                points[self.calibration_marker] = (x + dx, y + dy)
                self.move_markers(points, "Ajuster un repère d'axe", self.calibration_marker)
            return
        dataset, index = self.dataset, self.selected_point
        if mode != Mode.ADD or dataset is None or index is None or index >= len(dataset):
            return
        before = points_state(dataset)
        x, y = dataset.pixels[index]
        dataset.move_pixel(index, x + dx, y + dy)
        new_index = dataset.sort(graph.calibration, follow=index)
        self.push(PointsCommand(self, graph, dataset, before, points_state(dataset),
                                "Ajuster un point", index, new_index, merge=True))

    def key_command(self, command):
        dataset = self.dataset
        if dataset is None or not len(dataset):
            return
        if command == "delete":
            if not self._editable():
                return
            if self.selected_point is not None and self.selected_point < len(dataset):
                self.delete_point(self.selected_point)
            return
        step = 1 if command == "next" else -1
        if self.selected_point is None:
            self.selected_point = 0 if step > 0 else len(dataset) - 1
        else:
            self.selected_point = (self.selected_point + step) % len(dataset)
        self.refresh_selection()

    def table_current_changed(self, row, _column, _previous_row, _previous_column):
        if self._loading or self.dataset is None or row < 0:
            return
        self.selected_point = row
        self.refresh_selection(select_row=False)

    def refresh_selection(self, select_row=True):
        """Anneau sur le repère ou le point sélectionné, ligne de la table."""
        canvas, graph, dataset = self.view.canvas, self.graph, self.dataset
        point = None
        if graph is not None and canvas.mode == Mode.CALIBRATE:
            if self.calibration_clicks:
                point = self.click_markers()[-1]
            elif self.calibration_marker is not None and graph.calibrated:
                point = self.calibration_points()[self.calibration_marker]
        elif dataset is not None and self.selected_point is not None:
            if self.selected_point < len(dataset):
                point = dataset.pixels[self.selected_point]
            else:
                self.selected_point = None
        canvas.set_selection(point)
        if select_row:
            table = self.view.table
            self._loading = True
            if self.selected_point is not None and self.selected_point < table.rowCount():
                table.selectRow(self.selected_point)
            else:
                table.clearSelection()
            self._loading = False

    def calibration_points(self) -> list:
        """Repères de la calibration du graphique : (O, X2, Y2) ou les 4."""
        return self.graph.calibration.markers()

    def _nearest_marker(self, x, y):
        graph = self.graph
        if graph is None or not graph.calibrated:
            return None
        points = np.array(self.calibration_points())
        distance = np.hypot(points[:, 0] - x, points[:, 1] - y)
        index = int(np.argmin(distance))
        return index if distance[index] <= self._tolerance() else None

    def move_markers(self, points, text, marker=None):
        """Nouvelle calibration aux repères déplacés, mêmes valeurs ; dans la pile."""
        graph = self.graph
        cal = graph.calibration
        try:
            new = cal.with_markers(points)
        except CalibrationError as error:
            self.view.message(f"Calibration : {error}", 5000)
            self.refresh_calibration_markers()
            return
        self.push(CalibrationCommand(self, graph, cal, new, graph.extraction, graph.extraction,
                                     text, marker))
        self.calibration_marker = self.calibration_marker if marker is None else marker
        self.refresh_selection()

    def show_coordinates(self, x, y):
        graph = self.graph
        text = f"px ({x:.1f}, {y:.1f})"
        if graph.calibrated:
            dx, dy = graph.calibration.pixel_to_data([(x, y)])[0]
            text += (f"   {graph.x_axis.quantity or 'X'} = {dx:.5g} {graph.x_axis.unit}"
                     f"   {graph.y_axis.quantity or 'Y'} = {dy:.5g} {graph.y_axis.unit}")
        self.view.coordinates.setText(text)

    # ============================================================ calibration
    def finish_calibration(self, clicks):
        graph = self.graph
        previous = graph.calibration.to_dict() if graph.calibrated else {
            "x1": 0, "x2": 1, "y1": 0, "y2": 1}
        if QtWidgets.QApplication.platformName() == "offscreen":
            return                  # sans écran : les tests appellent apply_calibration
        orthogonal = np.allclose(clicks[0], clicks[2])
        dialog = CalibrationDialog(previous, self.view, orthogonal)
        if dialog.exec():
            self.apply_calibration(clicks, dialog.values())
        else:
            self.calibration_clicks = []
            self.refresh_calibration_markers()
            self.set_mode(Mode.NAVIGATE)

    def edit_axis_values(self):
        if not self._editable():
            return
        graph = self.graph
        if graph is None or not graph.calibrated:
            self.set_mode(Mode.CALIBRATE)
            return
        cal = graph.calibration
        dialog = CalibrationDialog(cal.to_dict(), self.view, cal.orthogonal)
        if dialog.exec():
            self.apply_calibration([cal.px_x1, cal.px_x2, cal.px_y1, cal.px_y2], dialog.values())

    def apply_calibration(self, clicks, values: dict) -> bool:
        graph = self.graph
        try:
            calibration = AxisCalibration(*clicks, **values)
        except CalibrationError as error:
            self.view.error("Calibration", str(error))
            self.calibration_clicks = []
            self.refresh_calibration_markers()
            return False
        before = dataclasses.replace(graph.extraction)
        after = dataclasses.replace(graph.extraction)
        if not graph.calibrated:
            # grille d'extraction par défaut : la plage pointée en X
            low, high = sorted((calibration.x1, calibration.x2))
            after.grid_start, after.grid_stop = low, high
            if calibration.log_x:
                after.grid_count = 20
            else:
                after.grid_step = (high - low) / 20
        self.calibration_clicks = []
        self.push(CalibrationCommand(self, graph, graph.calibration, calibration, before, after))
        skew = calibration.skew_degrees()
        self.set_mode(Mode.ADD)
        if skew > 1.0:
            self.view.message(f"Calibration faite. Axes non perpendiculaires de {skew:.1f}° "
                              "(image de travers ?)", 8000)
        else:
            self.view.message("Calibration faite — ajoutez des points ou peignez la courbe", 6000)
        return True

    # ============================================================ masque, extraction
    def clear_mask(self):
        if not self._editable():
            return
        dataset = self.dataset
        if dataset is None or dataset.mask is None or not dataset.mask.any():
            return
        before = dataset.mask.copy()
        dataset.mask[...] = False
        self.push(MaskCommand(self, self.graph, dataset, before, dataset.mask,
                              "Effacer le masque"))

    def split_points(self, *_) -> bool:
        """
        Points de la courbe choisie situés dans son masque (peint au pinceau) -> nouvelle
        courbe, placée juste après ; le masque est effacé. Pour séparer deux courbes
        relevées comme une seule (import PDF, extraction). Une seule étape d'annulation.
        """
        if not self._editable():
            return False
        graph, dataset = self.graph, self.dataset
        if dataset is None or not len(dataset):
            self.view.message("Choisissez une courbe qui a des points", 5000)
            return False
        if dataset.mask is None or not dataset.mask.any():
            self.view.message(f"Peignez d'abord au pinceau (B) les points à séparer de "
                              f"« {dataset.name} »", 6000)
            self.set_mode(Mode.PAINT)
            return False
        rows, cols = dataset.mask.shape
        px = np.clip(np.round(dataset.pixels).astype(int), 0, [cols - 1, rows - 1])
        inside = dataset.mask[px[:, 1], px[:, 0]]
        if not inside.any() or inside.all():
            self.view.message("Le masque doit couvrir une partie des points de la courbe, "
                              "pas aucun ni tous", 6000)
            return False
        used = {d.name for d in graph.datasets}
        name, n = f"{dataset.name} (2)", 2
        while name in used:
            n += 1
            name = f"{dataset.name} ({n})"
        new = document.Dataset(name=name,
                               color=document.PALETTE[len(graph.datasets) % len(document.PALETTE)],
                               pixels=dataset.pixels[inside].copy())
        new.tolerance, new.curve_color = dataset.tolerance, dataset.curve_color
        keep = ~inside
        text = f"Séparer {int(inside.sum())} point(s) de « {dataset.name} »"
        self.undo_stack.beginMacro(text)
        try:
            self.change_points(text, lambda d: setattr(d, "pixels", d.pixels[keep]))
            before = dataset.mask.copy()
            dataset.mask[...] = False
            self.push(MaskCommand(self, graph, dataset, before, dataset.mask, "Effacer le masque"))
            index = graph.datasets.index(dataset) + 1
            self.push(InsertCommand(self, graph.datasets, index, new, True, text, graph=graph))
        finally:
            self.undo_stack.endMacro()
        self.view.message(f"{text} : nouvelle courbe « {name} »", 6000)
        return True

    def foreground(self):
        dataset = self.dataset
        return mask.foreground(self.graph.image, dataset.mask, dataset.curve_color,
                               dataset.tolerance)

    def refresh_detection(self, *_):
        graph = self.graph
        if (graph is None or graph.image is None or self.dataset is None
                or not self.view.actionDetection.isChecked()):
            self.view.canvas.set_detection(None)
            return
        self.view.canvas.set_detection(self.foreground())

    def extract(self):
        if not self._editable():
            return
        graph = self.graph
        if graph is None or graph.image is None:
            return
        if self.dataset is None:
            self.add_dataset()
        binary = self.foreground()
        if not binary.any():
            self.view.error("Extraction", "Aucun pixel de la couleur recherchée dans le masque.\n"
                            "Vérifiez la couleur (pipette) et la tolérance.")
            return
        try:
            points = extraction.extract(binary, graph.extraction, graph.calibration)
        except (ValueError, RuntimeError) as error:
            self.view.error("Extraction", str(error))
            return
        if len(points) == 0:
            self.view.error("Extraction", "Aucun point extrait.")
            return
        def replace(dataset):
            dataset.pixels = points
            dataset.sort(graph.calibration)

        self.change_points("Extraire la courbe", replace)
        unmasked = "" if self.dataset.mask is not None and self.dataset.mask.any() else \
            " (sans masque : toute l'image a été parcourue)"
        self.view.message(f"{len(points)} points extraits{unmasked}", 6000)

    # ============================================================ modèle
    def fit_model(self):
        if not self._editable():
            return
        graph, dataset = self.graph, self.dataset
        if dataset is None or not self._need_calibration():
            return
        params = self.view.params["model"]
        formula = params["Formule"]
        data = dataset.data(graph.calibration)
        try:
            result = fit.fit(formula, data[:, 0], data[:, 1], relative=params["Erreur relative"])
        except FormulaError as error:
            self.view.error("Modèle", str(error))
            return
        self.change_points("Ajuster le modèle", lambda d: setattr(d, "fit", result),
                           self.selected_point)

    def model_pixels(self, graph, dataset):
        """Courbe du modèle ajusté, en pixels, sur la plage des points."""
        if dataset.fit is None or not graph.calibrated or len(dataset) < 2:
            return None
        cal = graph.calibration
        scaled = cal.pixel_to_scaled(dataset.pixels)
        xs_scaled = np.linspace(scaled[:, 0].min(), scaled[:, 0].max(), MODEL_SAMPLES)
        xs = cal.scaled_to_data(np.column_stack((xs_scaled, np.zeros_like(xs_scaled))))[:, 0]
        try:
            ys = dataset.fit.evaluate(xs)
        except (FormulaError, ValueError):
            return None
        return cal.data_to_pixel(np.column_stack((xs, ys)))

    # ============================================================ paramètres
    def _component_changed(self, param, changes):
        if self._loading:
            return
        c = self.component
        c.name, c.manufacturer = param["Nom"], param["Fabricant"]
        c.part_number, c.category, c.notes = param["Référence"], param["Catégorie"], param["Notes"]
        for child, change, _ in changes:
            if change == "activated" and child.name() == "Exporter pour PLECS":
                self.export_plecs()
                return
        group, settings_ = param.child("Export PLECS"), c.plecs
        settings_.current_axis = group["Axe de courant (A)"]
        settings_.current_points = group["Intervalles (axe auto)"]
        settings_.origin, settings_.zero_voltage = group["Point (0, 0)"], group["Ligne 0 V"]
        settings_.safety_factor = group["Facteur de sécurité Csecu"]
        settings_.foster = group["Modèle thermique Foster"]
        self.set_dirty()

    def _graph_changed(self, param, changes):
        if self._loading or self.graph is None:
            return
        graph = self.graph
        for child, change, _ in changes:
            if change == "activated" and child.name() == "Modifier les valeurs des axes":
                self.edit_axis_values()
                return
        graph.name = param["Nom"]
        graph.plecs_role = param["Rôle PLECS"]
        graph.x_axis.quantity, graph.x_axis.unit = param["Grandeur X"], param["Unité X"]
        graph.y_axis.quantity, graph.y_axis.unit = param["Grandeur Y"], param["Unité Y"]
        for child, change, _ in changes:
            if change == "value" and child.name().startswith("Unité") and child.value():
                try:
                    unit = units.parse_unit(child.value())
                    self.view.message(f"{child.name()} : {units.describe(unit)}", 4000)
                except ValueError as error:
                    self.view.message(f"{child.name()} : unité non reconnue ({error})", 6000)
        self.set_dirty()
        self.rebuild_tree()
        self.refresh_preview()

    def _dataset_changed(self, param, changes):
        if self._loading or self.dataset is None:
            return
        dataset = self.dataset
        for child, change, _ in changes:
            if change == "activated":
                if child.name() == "Trier par X":
                    self.change_points("Trier les points",
                                       lambda d: d.sort(self.graph.calibration))
                elif child.name() == "Effacer les points":
                    def clear(d):
                        d.pixels = np.empty((0, 2))
                        d.fit = None
                    self.change_points("Effacer les points", clear)
                return
        dataset.name = param["Nom"]
        dataset.condition = param["Condition"]
        for field, label in (("temperature", "Tj (°C)"), ("voltage", "Tension (V)")):
            text = param[label].strip()
            try:
                setattr(dataset, field, parse_value(text) if text else None)
            except ValueError as error:
                self.view.message(f"{label} : {error}", 5000)
        dataset.color = pg.mkColor(param["Couleur"]).name()
        self.set_dirty()
        self.rebuild_tree()
        self.refresh_curves()
        self.refresh_preview()

    def _extraction_changed(self, param, changes):
        if self._loading:
            return
        for child, change, _ in changes:
            if change == "activated":
                if child.name() == "Extraire":
                    self.extract()
                elif child.name() == "Couleur dominante du masque":
                    self.dominant_color()
                return
        self.view.canvas.set_brush_radius(param["Rayon du pinceau"])
        self.options["brush_radius"] = param["Rayon du pinceau"]
        graph = self.graph
        if graph is None:
            return
        if self.dataset is not None:
            color = pg.mkColor(param["Couleur de la courbe"])
            self.dataset.curve_color = (color.red(), color.green(), color.blue())
            self.dataset.tolerance = float(param["Tolérance couleur"])
        s = graph.extraction
        s.method = param["Méthode"]
        s.dx, s.dy, s.smooth = param["Fenêtre dx"], param["Fenêtre dy"], param["Lissage"]
        grid = param.child("Grille")
        s.grid_start, s.grid_stop = grid["X début"], grid["X fin"]
        s.grid_step, s.grid_count = grid["Pas"], grid["Nombre de points"]
        s.interpolation, s.extrapolate = grid["Interpolation"], grid["Extrapoler"]
        s.simplify = param["Tolérance du squelette"]
        self.set_dirty()
        if any(c.name() in ("Couleur de la courbe", "Tolérance couleur") for c, _, _ in changes):
            self.refresh_detection()

    def dominant_color(self):
        graph, dataset = self.graph, self.dataset
        if dataset is None or dataset.mask is None or not dataset.mask.any():
            self.view.message("Peignez d'abord la courbe avec le pinceau", 4000)
            return
        color = mask.dominant_color(graph.image, dataset.mask)
        if color is None:
            self.view.message("Le masque ne contient que du fond clair", 4000)
            return
        dataset.curve_color = color
        self.set_dirty()
        self.fill_extraction()
        self.refresh_detection()

    def _model_changed(self, param, changes):
        if self._loading:
            return
        for child, change, data in changes:
            if change == "activated":
                if child.name() == "Ajuster":
                    self.fit_model()
                elif child.name() == "Supprimer le modèle" and self.dataset is not None:
                    self.change_points("Supprimer le modèle", lambda d: setattr(d, "fit", None),
                                       self.selected_point)
                return
            if change == "value" and child.name() == "Modèle type" and data:
                self._loading = True
                param["Formule"] = fit.PRESETS[data]
                self._loading = False

    # ============================================================ table
    def table_cell_changed(self, row, column):
        if self._loading or self.dataset is None or not self._editable():
            return
        graph, dataset = self.graph, self.dataset
        data = dataset.data(graph.calibration)
        try:
            data[row, column] = parse_value(self.view.table.item(row, column).text())
        except ValueError as error:
            self.view.message(str(error), 5000)
            self.refresh_table()
            return
        if graph.calibrated:
            pixel = graph.calibration.data_to_pixel(data[row:row + 1])[0]
            if not np.all(np.isfinite(pixel)):
                self.view.message("Valeur impossible sur un axe logarithmique", 5000)
                self.refresh_table()
                return
        else:
            pixel = data[row]
        result = {}

        def edit(d):
            d.move_pixel(row, *pixel)
            result["index"] = d.sort(graph.calibration, follow=row)

        before = points_state(dataset)
        edit(dataset)
        self.push(PointsCommand(self, graph, dataset, before, points_state(dataset),
                                "Modifier un point", self.selected_point, result["index"]))

    # ============================================================ rafraîchissements
    def refresh_all(self, reset_view=False):
        graph = self.graph
        if reset_view:
            self.view.canvas.set_image(None if graph is None else graph.image)
        self.view.canvas.set_mask(None if self.dataset is None else self.dataset.mask)
        self.rebuild_tree()
        self.refresh_calibration_markers()
        self.fill_properties()
        self.refresh_dataset_views()
        self.refresh_detection()

    def refresh_dataset_views(self):
        self.refresh_curves()
        self.refresh_preview()
        self.refresh_table()
        self.fill_dataset()
        self.fill_model()
        self._update_tree_counts()
        self.refresh_selection()

    def _update_tree_counts(self):
        self._loading = True
        for g in range(self.tree_model.rowCount()):
            item = self.tree_model.item(g)
            graph = self.component.graphs[g]
            for d in range(item.rowCount()):
                dataset = graph.datasets[d]
                label = dataset.name + (f"  [{dataset.condition}]" if dataset.condition else "")
                item.child(d).setText(label + f"  ({len(dataset)})")
        self._loading = False

    def refresh_calibration_markers(self):
        graph = self.graph
        if graph is None:
            self.view.canvas.set_calibration_points([])
        elif self.calibration_clicks:
            self.show_markers(self.click_markers(), self.orthogonal)
        elif graph.calibrated:
            cal = graph.calibration
            self.show_markers(cal.markers(), cal.orthogonal)
        else:
            self.view.canvas.set_calibration_points([])
        self.refresh_selection()

    def refresh_curves(self):
        graph = self.graph
        if graph is None:
            self.view.canvas.set_datasets([])
            return
        curves = [{"pixels": d.pixels, "color": d.color, "active": i == self.dataset_index,
                   "model": self.model_pixels(graph, d)}
                  for i, d in enumerate(graph.datasets) if d.visible]
        self.view.canvas.set_datasets(curves)

    def refresh_preview(self):
        plot = self.view.preview_plot
        plot.clear()
        if plot.legend is not None:
            plot.legend.clear()
        graph = self.graph
        if graph is None or not graph.calibrated:
            plot.setLogMode(False, False)
            zoom.limit_empty(plot)
            plot.setLabel("bottom", "")
            plot.setLabel("left", "")
            plot.setTitle("Aperçu en unités physiques (graphique non calibré)", size="9pt")
            return
        cal = graph.calibration
        plot.setTitle(None)
        plot.setLogMode(cal.log_x, cal.log_y)
        plot.setLabel("bottom", graph.x_axis.label("X"))
        plot.setLabel("left", graph.y_axis.label("Y"))
        xs, ys = [], []                          # bornes du zoom : données tracées
        for i, dataset in enumerate(graph.datasets):
            if not dataset.visible or len(dataset) == 0:
                continue
            data = dataset.data(cal)
            xs.append(data[:, 0])
            ys.append(data[:, 1])
            name = dataset.name + (f" ({dataset.condition})" if dataset.condition else "")
            plot.plot(data[:, 0], data[:, 1], pen=pg.mkPen(dataset.color, width=1.5),
                      symbol="o", symbolSize=5, symbolBrush=dataset.color, name=name)
            model = self.model_pixels(graph, dataset)
            if model is not None:
                values = cal.pixel_to_data(model)
                plot.plot(values[:, 0], values[:, 1], connect="finite",
                          pen=pg.mkPen(dataset.color, width=1, style=QtCore.Qt.PenStyle.DashLine))
                xs.append(values[:, 0])
                ys.append(values[:, 1])
        zoom.limit_plot(plot, xs, ys, cal.log_x, cal.log_y)
        plot.enableAutoRange()

    def refresh_table(self):
        table = self.view.table
        self._loading = True
        table.blockSignals(True)
        graph, dataset = self.graph, self.dataset
        if dataset is None:
            table.setRowCount(0)
        else:
            data = dataset.data(graph.calibration)
            table.setRowCount(len(data))
            for r, row in enumerate(data):
                for c, value in enumerate(row):
                    table.setItem(r, c, QtWidgets.QTableWidgetItem(format(value, ".6g")))
        if graph is not None and graph.calibrated:
            table.setHorizontalHeaderLabels([graph.x_axis.label("X"), graph.y_axis.label("Y")])
        else:
            table.setHorizontalHeaderLabels(["X (px)", "Y (px)"])
        table.blockSignals(False)
        self._loading = False

    # ------------------------------------------------------------ remplissage
    def fill_properties(self):
        self._loading = True
        c, p = self.component, self.view.params["component"]
        p["Nom"], p["Fabricant"], p["Référence"] = c.name, c.manufacturer, c.part_number
        p["Catégorie"], p["Notes"] = c.category, c.notes
        group, s = p.child("Export PLECS"), c.plecs
        group["Axe de courant (A)"], group["Intervalles (axe auto)"] = s.current_axis, s.current_points
        group["Point (0, 0)"], group["Ligne 0 V"] = s.origin, s.zero_voltage
        group["Facteur de sécurité Csecu"], group["Modèle thermique Foster"] = s.safety_factor, s.foster
        graph, p = self.graph, self.view.params["graph"]
        p.setOpts(visible=graph is not None)
        if graph is not None:
            p["Nom"] = graph.name
            p["Grandeur X"], p["Unité X"] = graph.x_axis.quantity, graph.x_axis.unit
            p["Grandeur Y"], p["Unité Y"] = graph.y_axis.quantity, graph.y_axis.unit
            if graph.calibrated:
                cal = graph.calibration
                p["Calibration"] = (f"X {format_value(cal.x1)} → {format_value(cal.x2)}"
                                    f"{' (log)' if cal.log_x else ''} ; "
                                    f"Y {format_value(cal.y1)} → {format_value(cal.y2)}"
                                    f"{' (log)' if cal.log_y else ''}")
            else:
                p["Calibration"] = "non calibré"
        self._loading = False
        self.fill_extraction()

    def fill_extraction(self):
        self._loading = True
        graph, p = self.graph, self.view.params["extraction"]
        p["Rayon du pinceau"] = self.options["brush_radius"]
        if graph is not None:
            if self.dataset is not None:
                p["Couleur de la courbe"] = QtGui.QColor(*self.dataset.curve_color)
                p["Tolérance couleur"] = self.dataset.tolerance
            s = graph.extraction
            p["Méthode"] = s.method
            p["Fenêtre dx"], p["Fenêtre dy"], p["Lissage"] = s.dx, s.dy, s.smooth
            grid = p.child("Grille")
            grid["X début"], grid["X fin"] = s.grid_start, s.grid_stop
            grid["Pas"], grid["Nombre de points"] = s.grid_step, s.grid_count
            grid["Interpolation"], grid["Extrapoler"] = s.interpolation, s.extrapolate
            p["Tolérance du squelette"] = s.simplify
        self._loading = False

    def fill_dataset(self):
        self._loading = True
        dataset, p = self.dataset, self.view.params["dataset"]
        p.setOpts(visible=dataset is not None)
        if dataset is not None:
            p["Nom"], p["Condition"] = dataset.name, dataset.condition
            p["Tj (°C)"] = "" if dataset.temperature is None else format_value(dataset.temperature)
            p["Tension (V)"] = "" if dataset.voltage is None else format_value(dataset.voltage)
            p["Couleur"] = QtGui.QColor(dataset.color)
            p["Points"] = len(dataset)
        self._loading = False

    def fill_model(self):
        self._loading = True
        dataset, p = self.dataset, self.view.params["model"]
        p.setOpts(visible=dataset is not None)
        if dataset is not None and dataset.fit is not None:
            result = dataset.fit
            p["Formule"] = result.formula
            p["Erreur relative"] = result.relative
            lines = [f"{name} = {value:.6g}" + (f"  (± {result.errors[name]:.2g})"
                                                 if np.isfinite(result.errors.get(name, np.nan)) else "")
                     for name, value in result.parameters.items()]
            lines += [f"R² = {result.r2:.6f}", f"écart quadratique = {result.rmse:.4g}",
                      f"écart relatif max = {100 * result.max_relative_error:.2f} %",
                      "", result.numeric_formula()]
            p["Résultat"] = "\n".join(lines)
        elif dataset is not None:
            p["Résultat"] = ""
        self._loading = False
