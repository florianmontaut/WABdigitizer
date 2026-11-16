# controller/main_controller.py
"""
Contrôleur principal : relie la fenêtre (canevas, arborescence, paramètres, table) au
document numérisé (model.document) et aux calculs (calibration, extraction, ajustement).
"""
import pathlib
import weakref

import numpy as np
import pyqtgraph as pg
from PyQt6 import QtCore, QtGui, QtWidgets

from formules import FormulaError, units
from qtsocle import options_panel, settings, theme
from ressources import app_settings

from model import document, export, extraction, fit, mask, plecs
from model.calibration import AxisCalibration, CalibrationError
from model.plecs import PlecsError
from view.canvas import Mode
from view.dialogs import CalibrationDialog, format_value, parse_value
from view.main_window import IMAGE_SUFFIXES, qimage_to_array

ROLE = QtCore.Qt.ItemDataRole.UserRole + 1
CLICK_TOLERANCE = 7          # pixels de l'écran
MODEL_SAMPLES = 300


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
        self.calibration_clicks = []     # points pointés pendant la calibration
        self.drag_index = None
        self.last_paint = None
        self._loading = False            # remplissage des paramètres en cours

        # modèles Qt parentés à leur vue : détruits avec elle, dans l'ordre
        self.tree_model = QtGui.QStandardItemModel(view.tree)
        view.tree.setModel(self.tree_model)

        # slots en méthodes liées (pas de lambda qui garderait le contrôleur en vie)
        view.actionNew.triggered.connect(self.new_component)
        view.actionOpenImage.triggered.connect(self.open_image)
        view.actionPaste.triggered.connect(self.paste_image)
        view.actionOpen.triggered.connect(self.open_project)
        view.actionSave.triggered.connect(self.save_project)
        view.actionSaveAs.triggered.connect(self.save_project_as)
        view.actionExportCsv.triggered.connect(self.export_csv)
        view.actionExportGrid.triggered.connect(self.export_grid)
        view.actionExportComponent.triggered.connect(self.export_component)
        view.actionExportPlecs.triggered.connect(self.export_plecs)
        view.actionCopyTable.triggered.connect(self.copy_table)
        view.actionCopyLut.triggered.connect(self.copy_lut)
        view.actionQuit.triggered.connect(view.close)
        view.modeGroup.triggered.connect(self.mode_triggered)
        view.actionClearMask.triggered.connect(self.clear_mask)
        view.actionDetection.toggled.connect(self.refresh_detection)
        view.actionExtract.triggered.connect(self.extract)
        view.actionFit.triggered.connect(self.fit_model)
        view.actionAddCurve.triggered.connect(self.add_dataset)
        view.actionDelete.triggered.connect(self.delete_selection)
        view.actionOptions.triggered.connect(self.edit_options)
        view.actionDark.toggled.connect(self.set_dark_mode)
        view.closing.connect(self.save_settings)
        # projet modifié : proposé à l'enregistrement avant fermeture (référence faible :
        # la fenêtre ne garde pas le contrôleur en vie)
        view.close_guard = weakref.WeakMethod(self._ask_discard)
        view.files_dropped.connect(self.open_files)
        view.canvas.pressed.connect(self.canvas_pressed)
        view.canvas.moved.connect(self.canvas_moved)
        view.canvas.released.connect(self.canvas_released)
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
        self.dirty = dirty
        name = self.path.name if self.path else "sans titre"
        app = QtWidgets.QApplication.applicationName()
        self.view.setWindowTitle(f"{'* ' if dirty else ''}{name} — {app}")

    def select(self, graph_index, dataset_index=None):
        self.graph_index = graph_index
        graph = self.graph
        if graph is not None and dataset_index is None and graph.datasets:
            dataset_index = 0
        self.dataset_index = dataset_index
        self.calibration_clicks = []
        self.refresh_all(reset_view=True)

    # ============================================================ thème et réglages
    def set_dark_mode(self, enabled: bool):
        self.options["dark_mode"] = bool(enabled)
        self.apply_theme()

    def apply_theme(self):
        theme.apply(QtWidgets.QApplication.instance(), self.options["dark_mode"],
                    extra_qss=theme.ITEM_VIEW_QSS)
        self.view.refresh_theme()

    def edit_options(self):
        dialog = options_panel.OptionsPannel(self.schema, self.options, self.view)
        if dialog.exec():
            self.options.update(dialog.getOptions())
            self.view.canvas.set_brush_radius(self.options["brush_radius"])
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

    def set_component(self, component, path):
        self.component = component
        self.path = pathlib.Path(path) if path else None
        self.graph_index = 0 if component.graphs else None
        self.dataset_index = 0 if component.graphs and component.graphs[0].datasets else None
        self.set_dirty(False)
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
        graph = self.component.add_graph(array, name, source)
        graph.datasets[0].tolerance = float(self.options["tolerance"])
        self.set_dirty()
        self.select(len(self.component.graphs) - 1, 0)
        self.set_mode(Mode.CALIBRATE)

    def open_files(self, paths):
        for path in paths:
            if str(path).lower().endswith(".json"):
                self.load_project(path)
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
        try:
            component = document.load(path)
        except (OSError, ValueError, KeyError) as error:
            self.view.error("Ouverture", f"{path} :\n{error}")
            return
        self._remember_dir(path)
        self.set_component(component, path)

    def save_project(self) -> bool:
        if self.path is None:
            return self.save_project_as()
        return self.write_project(self.path)

    def save_project_as(self) -> bool:
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
            library = pathlib.Path(self.options["library_dir"])
            library.mkdir(parents=True, exist_ok=True)
            name = self.component.part_number or self.component.name or "composant"
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self.view, "Composant pour PLECS", str(library / f"{name}.xml"), "XML (*.xml)")
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
        library = pathlib.Path(self.options["library_dir"])
        library.mkdir(parents=True, exist_ok=True)
        name = self.component.part_number or self.component.name or "composant"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self.view, "Fiche du composant", str(library / f"{name}.json"), "JSON (*.json)")
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
            self.refresh_all()

    def tree_item_changed(self, item):
        if self._loading:
            return
        g, d = item.data(ROLE)
        if d is None:
            return
        dataset = self.component.graphs[g].datasets[d]
        dataset.visible = item.checkState() == QtCore.Qt.CheckState.Checked
        self.set_dirty()
        self.refresh_curves()

    def add_dataset(self):
        if self.graph is None:
            return
        self.graph.add_dataset(tolerance=self.options["tolerance"])
        self.dataset_index = len(self.graph.datasets) - 1
        self.set_dirty()
        self.refresh_all()
        if self.view.canvas.mode not in (Mode.ADD, Mode.PAINT, Mode.ERASE):
            self.set_mode(Mode.ADD)

    def delete_selection(self):
        if self.graph is None:
            return
        if self.dataset is not None:
            del self.graph.datasets[self.dataset_index]
            self.dataset_index = (min(self.dataset_index, len(self.graph.datasets) - 1)
                                  if self.graph.datasets else None)
        else:
            del self.component.graphs[self.graph_index]
            self.graph_index = (min(self.graph_index, len(self.component.graphs) - 1)
                                if self.component.graphs else None)
            self.dataset_index = 0 if self.graph and self.graph.datasets else None
        self.set_dirty()
        self.refresh_all(reset_view=True)

    # ============================================================ modes
    def mode_triggered(self, action):
        self.set_mode(action.data())

    def set_mode(self, mode: Mode):
        self.view.modeActions[mode].setChecked(True)
        self.view.canvas.set_mode(mode)
        self.drag_index = None
        if mode == Mode.CALIBRATE:
            self.calibration_clicks = []
            self.view.canvas.set_calibration_points([])
        self.view.message(self._mode_hint(mode))

    def _mode_hint(self, mode: Mode) -> str:
        if mode == Mode.CALIBRATE:
            labels = ("X1 : un point de l'axe X de valeur connue",
                      "X2 : un autre point de l'axe X", "Y1 : un point de l'axe Y",
                      "Y2 : un autre point de l'axe Y")
            n = len(self.calibration_clicks)
            return f"Calibration — cliquez {labels[min(n, 3)]} (molette : zoom)"
        return {
            Mode.NAVIGATE: "Navigation — glisser : déplacer, molette : zoom",
            Mode.ADD: "Clic : ajouter un point ; glisser un point : le déplacer",
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
        if graph is None:
            return
        mode = self.view.canvas.mode
        if mode == Mode.CALIBRATE:
            self.calibration_clicks.append((x, y))
            self.view.canvas.set_calibration_points(self.calibration_clicks)
            if len(self.calibration_clicks) == 4:
                self.finish_calibration(self.calibration_clicks)
            else:
                self.view.message(self._mode_hint(mode))
        elif mode == Mode.ADD:
            dataset = self.dataset
            if dataset is None:
                dataset = graph.add_dataset()
                self.dataset_index = len(graph.datasets) - 1
                self.rebuild_tree()
            index = dataset.nearest(x, y, self._tolerance())
            if index is None:
                index = dataset.add_pixel(x, y, graph.calibration)
                self.set_dirty()
                self.refresh_dataset_views()
            self.drag_index = index
        elif mode == Mode.DELETE:
            dataset = self.dataset
            if dataset is not None:
                index = dataset.nearest(x, y, self._tolerance())
                if index is not None:
                    dataset.remove_pixel(index)
                    self.set_dirty()
                    self.refresh_dataset_views()
        elif mode in (Mode.PAINT, Mode.ERASE):
            if self.dataset is None:
                self.add_dataset()
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
            return
        mode = self.view.canvas.mode
        if mode == Mode.ADD and self.drag_index is not None and self.dataset is not None:
            self.dataset.move_pixel(self.drag_index, x, y)
            self.set_dirty()
            self.refresh_curves()
        elif mode in (Mode.PAINT, Mode.ERASE) and self.last_paint is not None:
            self._paint(self.last_paint, (x, y))
            self.last_paint = (x, y)

    def canvas_released(self, x, y):
        mode = self.view.canvas.mode
        if mode == Mode.ADD and self.drag_index is not None:
            self.drag_index = None
            if self.dataset is not None:
                self.dataset.sort(self.graph.calibration)
            self.refresh_dataset_views()
        elif mode in (Mode.PAINT, Mode.ERASE):
            self.last_paint = None
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
        self.set_dirty()

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
        dialog = CalibrationDialog(previous, self.view)
        if dialog.exec():
            self.apply_calibration(clicks, dialog.values())
        else:
            self.calibration_clicks = []
            self.refresh_calibration_markers()
            self.set_mode(Mode.NAVIGATE)

    def edit_axis_values(self):
        graph = self.graph
        if graph is None or not graph.calibrated:
            self.set_mode(Mode.CALIBRATE)
            return
        cal = graph.calibration
        dialog = CalibrationDialog(cal.to_dict(), self.view)
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
        first = not graph.calibrated
        graph.set_calibration(calibration)
        if first:
            # grille d'extraction par défaut : la plage pointée en X
            low, high = sorted((calibration.x1, calibration.x2))
            graph.extraction.grid_start, graph.extraction.grid_stop = low, high
            if calibration.log_x:
                graph.extraction.grid_count = 20
            else:
                graph.extraction.grid_step = (high - low) / 20
        self.calibration_clicks = []
        self.set_dirty()
        self.refresh_all()
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
        if self.dataset is None or self.dataset.mask is None:
            return
        self.dataset.mask[...] = False
        self.view.canvas.set_mask(self.dataset.mask)
        self.set_dirty()
        self.refresh_detection()

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
        self.dataset.pixels = points
        self.dataset.sort(graph.calibration)
        self.set_dirty()
        self.refresh_dataset_views()
        unmasked = "" if self.dataset.mask is not None and self.dataset.mask.any() else \
            " (sans masque : toute l'image a été parcourue)"
        self.view.message(f"{len(points)} points extraits{unmasked}", 6000)

    # ============================================================ modèle
    def fit_model(self):
        graph, dataset = self.graph, self.dataset
        if dataset is None or not self._need_calibration():
            return
        params = self.view.params["model"]
        formula = params["Formule"]
        data = dataset.data(graph.calibration)
        try:
            dataset.fit = fit.fit(formula, data[:, 0], data[:, 1],
                                  relative=params["Erreur relative"])
        except FormulaError as error:
            self.view.error("Modèle", str(error))
            return
        self.set_dirty()
        self.refresh_dataset_views()

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
                    dataset.sort(self.graph.calibration)
                elif child.name() == "Effacer les points":
                    dataset.pixels = np.empty((0, 2))
                    dataset.fit = None
                self.set_dirty()
                self.refresh_dataset_views()
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
                    self.dataset.fit = None
                    self.set_dirty()
                    self.refresh_dataset_views()
                return
            if change == "value" and child.name() == "Modèle type" and data:
                self._loading = True
                param["Formule"] = fit.PRESETS[data]
                self._loading = False

    # ============================================================ table
    def table_cell_changed(self, row, column):
        if self._loading or self.dataset is None:
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
            dataset.move_pixel(row, *pixel)
        else:
            dataset.move_pixel(row, *data[row])
        dataset.sort(graph.calibration)
        self.set_dirty()
        self.refresh_dataset_views()

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
            self.view.canvas.set_calibration_points(self.calibration_clicks)
        elif graph.calibrated:
            cal = graph.calibration
            self.view.canvas.set_calibration_points([cal.px_x1, cal.px_x2, cal.px_y1, cal.px_y2])
        else:
            self.view.canvas.set_calibration_points([])

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
            plot.setLabel("bottom", "")
            plot.setLabel("left", "")
            plot.setTitle("Aperçu en unités physiques (graphique non calibré)", size="9pt")
            return
        cal = graph.calibration
        plot.setTitle(None)
        plot.setLogMode(cal.log_x, cal.log_y)
        plot.setLabel("bottom", graph.x_axis.label("X"))
        plot.setLabel("left", graph.y_axis.label("Y"))
        for i, dataset in enumerate(graph.datasets):
            if not dataset.visible or len(dataset) == 0:
                continue
            data = dataset.data(cal)
            name = dataset.name + (f" ({dataset.condition})" if dataset.condition else "")
            plot.plot(data[:, 0], data[:, 1], pen=pg.mkPen(dataset.color, width=1.5),
                      symbol="o", symbolSize=5, symbolBrush=dataset.color, name=name)
            model = self.model_pixels(graph, dataset)
            if model is not None:
                values = cal.pixel_to_data(model)
                plot.plot(values[:, 0], values[:, 1], connect="finite",
                          pen=pg.mkPen(dataset.color, width=1, style=QtCore.Qt.PenStyle.DashLine))
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
