# controller/compare_controller.py
"""
Contrôleur de la fenêtre de comparaison : sources (librairie, fichiers ajoutés, composant
ouvert), choix de la caractéristique et des courbes, tracé, curseur, exports.
"""
import pathlib

import numpy as np
import pyqtgraph as pg
import pyqtgraph.exporters
from PyQt6 import QtCore, QtGui, QtWidgets

from model import compare, library
from model.compare import CompareError, Frame
from model.document import PALETTE
from view.dialogs import parse_value
from view import zoom

ROLE = QtCore.Qt.ItemDataRole.UserRole + 1
OPEN_COMPONENT = "composant ouvert"
AUTO = "auto"
LINE_STYLES = (QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenStyle.DashLine,
               QtCore.Qt.PenStyle.DotLine, QtCore.Qt.PenStyle.DashDotLine)


class CompareController(QtCore.QObject):

    def __init__(self, view, options: dict, current_sheet=None):
        """
        options : réglages de l'application (library_dir, separator, decimal, last_dir),
        partagés avec le contrôleur principal. current_sheet : référence faible vers une
        fonction -> fiche du composant ouvert (ou None).
        """
        super().__init__()
        self.view = view
        self.options = options
        self.current_sheet = current_sheet
        self.extra_files = []           # fichiers ajoutés à la main
        self.curves = []                # toutes les courbes lues
        self.selected = []              # clés des courbes cochées, dans l'ordre du choix
        self.characteristic = None
        self.frame = None
        self.reference_key = AUTO       # choix de l'utilisateur ; AUTO : première courbe
        self._loading = False

        self.tree_model = QtGui.QStandardItemModel(view.tree)
        view.tree.setModel(self.tree_model)

        view.actionReload.triggered.connect(self.reload)
        view.actionAddFiles.triggered.connect(self.add_files)
        view.actionUncheck.triggered.connect(self.uncheck_all)
        view.actionExportCsv.triggered.connect(self.export_csv)
        view.actionExportImage.triggered.connect(self.export_image)
        view.characteristic.currentIndexChanged.connect(self.characteristic_changed)
        view.filter.textChanged.connect(self.rebuild_tree)
        self.tree_model.itemChanged.connect(self.item_changed)
        view.log_x.toggled.connect(self.refresh_plot)
        view.log_y.toggled.connect(self.refresh_plot)
        view.reference.currentIndexChanged.connect(self.reference_changed)
        view.cursor.sigPositionChanged.connect(self.cursor_moved)
        view.cursor_value.editingFinished.connect(self.cursor_typed)
        self.reload()

    # ============================================================ sources
    def reload(self):
        entries, errors = library.scan(self.options["library_dir"])
        files = [entry.data_path for entry in entries]
        known = {pathlib.Path(f).resolve() for f in files}
        files += [f for f in self.extra_files if pathlib.Path(f).resolve() not in known]
        curves, read_errors = compare.load_files(files)
        errors = errors + read_errors
        sheet = self.current_sheet() if self.current_sheet is not None else None
        if callable(sheet):          # WeakMethod : la référence rend la méthode
            sheet = sheet()
        if sheet:
            curves = compare.curves_of(sheet, OPEN_COMPONENT) + curves
        self.curves = curves
        keys = {c.key for c in curves}
        self.selected = [k for k in self.selected if k in keys]
        self.rebuild_characteristics()
        components = len({c.source for c in curves})
        text = f"{components} composant(s), {len(curves)} courbe(s)"
        if errors:
            text += f" — {len(errors)} fichier(s) ignoré(s) : " + " ; ".join(errors[:3])
        self.view.message(text)

    def show_sources(self, paths) -> int:
        """
        Coche les courbes de ces fichiers (composants choisis dans la librairie), dans la
        caractéristique que le plus grand nombre d'entre eux partagent. Retourne le nombre
        de courbes cochées.
        """
        self.reload()
        wanted = {str(pathlib.Path(p).resolve()) for p in paths}
        curves = [c for c in self.curves if c.source != OPEN_COMPONENT
                  and str(pathlib.Path(c.source).resolve()) in wanted]
        if not curves:
            self.view.message("Aucune courbe à comparer dans ces composants", 5000)
            return 0
        sources, counts = {}, {}
        for curve in curves:
            sources.setdefault(curve.characteristic, set()).add(curve.source)
            counts[curve.characteristic] = counts.get(curve.characteristic, 0) + 1
        best = max(sources, key=lambda k: (len(sources[k]), counts[k]))
        keys = [c.key for c in curves if c.characteristic == best]
        self.selected = []
        self.characteristic = best
        self.rebuild_characteristics()
        self.set_checked(keys)
        return len(keys)

    def add_files(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self.view, "Composants à comparer", self.options.get("last_dir") or "",
            "Projets et fiches (*.json)")
        if paths:
            self.add_paths(paths)

    def add_paths(self, paths):
        for path in paths:
            if path not in self.extra_files:
                self.extra_files.append(str(path))
        self.options["last_dir"] = str(pathlib.Path(paths[-1]).parent)
        self.reload()

    # ============================================================ caractéristique et arbre
    def rebuild_characteristics(self):
        counts = {}
        for curve in self.curves:
            counts.setdefault(curve.characteristic, set()).add(curve.source)
        keys = sorted(counts, key=lambda k: (-len(counts[k]), compare.characteristic_label(k)))
        if self.selected:       # la caractéristique des courbes cochées reste choisie
            first = next(c for c in self.curves if c.key == self.selected[0])
            self.characteristic = first.characteristic
        elif self.characteristic not in counts:
            self.characteristic = keys[0] if keys else None
        combo = self.view.characteristic
        self._loading = True
        combo.clear()
        for key in keys:
            combo.addItem(f"{compare.characteristic_label(key)} — {len(counts[key])} composant(s)",
                          key)
        if self.characteristic is not None:
            combo.setCurrentIndex(keys.index(self.characteristic))
        self._loading = False
        self.rebuild_tree()
        self.refresh_plot()

    def characteristic_changed(self, index):
        if self._loading or index < 0:
            return
        key = self.view.characteristic.itemData(index)
        if key != self.characteristic:
            self.characteristic = key
            self.selected = []
            self.rebuild_tree()
            self.refresh_plot()

    def visible_curves(self):
        """Courbes de la caractéristique, filtrées par le texte saisi."""
        text = self.view.filter.text().strip().lower()
        out = []
        for curve in self.curves:
            if curve.characteristic != self.characteristic:
                continue
            haystack = " ".join((curve.component, curve.category, curve.graph, curve.name,
                                 curve.condition)).lower()
            if text and text not in haystack:
                continue
            out.append(curve)
        return out

    def rebuild_tree(self):
        self._loading = True
        self.tree_model.clear()
        root = self.tree_model.invisibleRootItem()
        nodes = {}
        for curve in self.visible_curves():
            component = nodes.get(curve.source)
            if component is None:
                category = f"  [{curve.category}]" if curve.category else ""
                text = curve.component + category
                if curve.source == OPEN_COMPONENT:
                    text += "  (ouvert)"
                component = QtGui.QStandardItem(text)
                component.setToolTip(curve.source)
                root.appendRow(component)
                nodes[curve.source] = component
            graph_key = (curve.source, curve.graph)
            graph = nodes.get(graph_key)
            if graph is None:
                graph = QtGui.QStandardItem(f"{curve.graph}  —  {curve.y_axis.label()} "
                                            f"/ {curve.x_axis.label()}")
                component.appendRow(graph)
                nodes[graph_key] = graph
            item = QtGui.QStandardItem(curve.name + (f"  ({curve.condition})" if curve.condition else ""))
            item.setCheckable(True)
            item.setCheckState(QtCore.Qt.CheckState.Checked if curve.key in self.selected
                               else QtCore.Qt.CheckState.Unchecked)
            item.setData(curve.key, ROLE)
            graph.appendRow(item)
        self.view.tree.expandAll()
        self._loading = False

    def item_changed(self, item):
        if self._loading:
            return
        key = item.data(ROLE)
        if key is None:
            return
        if item.checkState() == QtCore.Qt.CheckState.Checked:
            if key not in self.selected:
                self.selected.append(key)
        elif key in self.selected:
            self.selected.remove(key)
        if len(self.selected) == 1:
            self.set_log_defaults()     # échelles du graphique de la première courbe
        self.refresh_plot()

    def set_checked(self, keys):
        """Coche ces courbes (tests, scripts) dans l'ordre donné."""
        self.selected = [k for k in keys if any(c.key == k for c in self.curves)]
        self.rebuild_tree()
        self.set_log_defaults()
        self.refresh_plot()

    def uncheck_all(self):
        self.set_checked([])

    # ============================================================ tracé
    def selected_curves(self):
        by_key = {c.key: c for c in self.curves}
        return [by_key[k] for k in self.selected if k in by_key]

    def refresh_plot(self, *_):
        view, plot = self.view, self.view.plot
        plot.clear()
        view.legend.clear()
        curves = self.selected_curves()
        try:
            self.frame = Frame.for_curves(curves) if curves else None
        except CompareError as error:
            self.frame = None
            view.message(str(error), 6000)
        if self.frame is None:
            plot.setLogMode(False, False)
            zoom.limit_empty(plot)
            plot.setLabel("bottom", "")
            plot.setLabel("left", "")
            self._fill_reference([])
            self.refresh_readings()
            return
        log_x = view.log_x.isChecked()
        log_y = view.log_y.isChecked()
        plot.setLogMode(log_x, log_y)
        plot.setLabel("bottom", self.frame.x_axis.label())
        plot.setLabel("left", self.frame.y_axis.label())
        components = list(dict.fromkeys(c.source for c in curves))
        xs, ys = [], []                          # bornes du zoom : données tracées
        for index, curve in enumerate(curves):
            x, y = self.frame.convert(curve)
            if log_x or log_y:
                keep = ((x > 0) if log_x else True) & ((y > 0) if log_y else True)
                x, y = x[keep], y[keep]
            xs.append(x)
            ys.append(y)
            color = PALETTE[index % len(PALETTE)]
            style = LINE_STYLES[components.index(curve.source) % len(LINE_STYLES)]
            plot.plot(x, y, name=curve.label, pen=pg.mkPen(color, width=2, style=style),
                      symbol="o", symbolSize=4, symbolBrush=color, symbolPen=None)
        plot.addItem(view.cursor, ignoreBounds=True)
        zoom.limit_plot(plot, xs, ys, log_x, log_y)
        plot.enableAutoRange()
        self._fill_reference(curves)
        if not self._cursor_inside():
            self.set_cursor(float(np.median(compare.default_axis(curves, self.frame, 3, log_x))))
        self.refresh_readings()

    def set_log_defaults(self):
        """Échelles des graphiques d'origine pour la caractéristique choisie."""
        curves = self.selected_curves()
        if curves:
            self.view.log_x.setChecked(curves[0].x_axis.log)
            self.view.log_y.setChecked(curves[0].y_axis.log)

    def _fill_reference(self, curves):
        combo = self.view.reference
        self._loading = True
        combo.clear()
        combo.addItem("aucune", None)
        for curve in curves:
            combo.addItem(curve.label, curve.key)
        if self.reference_key is None:
            index = 0
        else:
            index = combo.findData(self.reference_key)
            if index < 0:               # choix automatique, ou courbe décochée
                index = 1 if curves else 0
        combo.setCurrentIndex(index)
        self._loading = False

    def reference_changed(self, index):
        if self._loading:
            return
        self.reference_key = self.view.reference.itemData(index)
        self.refresh_readings()

    # ============================================================ curseur
    def cursor_x(self) -> float:
        value = self.view.cursor.value()
        return float(10 ** value) if self.view.log_x.isChecked() else float(value)

    def set_cursor(self, x: float):
        if self.view.log_x.isChecked():
            if x <= 0:
                return
            x = np.log10(x)
        self.view.cursor.setValue(x)

    def _cursor_inside(self) -> bool:
        if self.frame is None:
            return False
        x = self.cursor_x()
        xs = np.concatenate([self.frame.convert(c)[0] for c in self.selected_curves()])
        return bool(np.isfinite(x) and xs.min() <= x <= xs.max())

    def cursor_moved(self, *_):
        self.refresh_readings()

    def cursor_typed(self):
        try:
            self.set_cursor(parse_value(self.view.cursor_value.text()))
        except ValueError as error:
            self.view.message(str(error), 4000)

    def refresh_readings(self, *_):
        if self._loading:
            return
        table = self.view.table
        curves = self.selected_curves()
        if self.frame is None or not curves:
            table.setRowCount(0)
            return
        x = self.cursor_x()
        keys = [c.key for c in curves]
        reference = self.view.reference.currentData()
        ref_index = keys.index(reference) if reference in keys else None
        reads = compare.readings(curves, x, ref_index, self.frame,
                                 self.view.log_x.isChecked(), self.view.log_y.isChecked())
        unit = self.frame.y_axis.unit
        self.view.cursor_value.blockSignals(True)
        self.view.cursor_value.setText(format(x, ".5g"))
        self.view.cursor_value.blockSignals(False)
        table.setRowCount(len(reads))

        def cell(text, color=None):
            item = QtWidgets.QTableWidgetItem(text)
            if color is not None:
                item.setForeground(QtGui.QColor(color))
            return item

        for index, read in enumerate(reads):
            row = index
            color = PALETTE[index % len(PALETTE)]
            table.setItem(row, 0, cell(read.curve.label, color))
            table.setItem(row, 1, cell("hors plage" if not np.isfinite(read.value)
                                       else f"{read.value:.4g} {unit}"))
            if ref_index is None or index == ref_index or not np.isfinite(read.delta):
                table.setItem(row, 2, cell("référence" if index == ref_index else ""))
                table.setItem(row, 3, cell(""))
            else:
                table.setItem(row, 2, cell(f"{read.delta:+.4g} {unit}"))
                table.setItem(row, 3, cell("" if not np.isfinite(read.relative)
                                           else f"{100 * read.relative:+.1f} %"))
        self.view.message(f"{self.frame.x_axis.label()} = {x:.5g}")

    # ============================================================ exports
    def _save_name(self, title, name, filters):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self.view, title, str(pathlib.Path(self.options.get("last_dir") or "") / name), filters)
        if path:
            self.options["last_dir"] = str(pathlib.Path(path).parent)
        return path

    def export_csv(self, path=None) -> bool:
        curves = self.selected_curves()
        if self.frame is None or not curves:
            self.view.message("Cochez d'abord des courbes", 4000)
            return False
        path = path or self._save_name("Comparaison", "comparaison.csv", "CSV (*.csv)")
        if not path:
            return False
        log_x = self.view.log_x.isChecked()
        axis = compare.default_axis(curves, self.frame, 50, log_x)
        text = compare.csv_text(curves, axis, self.frame, self.options["separator"],
                                self.options["decimal"], log_x, self.view.log_y.isChecked())
        pathlib.Path(path).write_text(text, encoding="utf-8")
        self.view.message(f"Comparaison écrite : {path}", 5000)
        return True

    def export_image(self, path=None) -> bool:
        if self.frame is None:
            self.view.message("Cochez d'abord des courbes", 4000)
            return False
        path = path or self._save_name("Image de la comparaison", "comparaison.png", "PNG (*.png)")
        if not path:
            return False
        exporter = pg.exporters.ImageExporter(self.view.plot)
        exporter.parameters()["width"] = 1600
        exporter.export(str(path))
        self.view.message(f"Image écrite : {path}", 5000)
        return True
