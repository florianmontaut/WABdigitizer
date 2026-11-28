# controller/signals_controller.py
"""
Contrôleur de la fenêtre « Calculs entre signaux » : signaux du composant ouvert (courbes
des graphiques calibrés), voies calculées du composant (Component.computed, enregistrées
dans le projet, hors de la pile d'annulation comme les autres propriétés), recalcul à
chaque modification, tracés à plusieurs axes d'ordonnées (view/y_axes.py, repris de
loggerFPGA) ou graphiques séparés, échelle de chaque axe réglable (automatique, min / max,
graduations, grille ; réglages gardés pendant la session), curseur, export CSV.
"""
import pathlib

import numpy as np
import pyqtgraph as pg
import pyqtgraph.parametertree as ptree
from PyQt6 import QtCore, QtWidgets

from model import signals
from model.signals import AUTO, PERIOD, ComputedCurve
from qtsocle import theme
from view import y_axes, zoom

ROLE = QtCore.Qt.ItemDataRole.UserRole + 1
COLORS = ("#ff8c00", "#e377c2", "#17becf", "#bcbd22", "#8c564b", "#7f7f7f")
BASES = {"signal le plus fin": AUTO, "pas propre": PERIOD}
GROUP = "Voies calculées"
ADD = "Ajouter une voie calculée"
HELP = "Voies et fonctions"


def _format(value: float, unit: str) -> str:
    if not np.isfinite(value):
        return "—"
    return pg.siFormat(value, precision=4, suffix=unit) if unit else f"{value:.4g}"


class SignalsController(QtCore.QObject):

    def __init__(self, view, options: dict, host):
        """
        host : référence faible (weakref.ref) vers le contrôleur principal, qui donne le
        composant ouvert (component), set_dirty() et _editable().
        """
        super().__init__()
        self.view = view
        self.options = options
        self.host = host
        self.inputs = {}            # clé affichée -> Signal (signaux du composant)
        self.available = {}         # toutes les clés des formules -> Signal
        self.results = []           # [Result], dans l'ordre des voies calculées
        self.hidden = set()         # sources des signaux décochés
        self.axes = []              # axes tracés : {key, signals, plot, vb, axis, label}
        self.extra_scales = []      # y_axes.AxisScale au-delà du premier axe
        self.lines = []             # curseurs (un par graphique)
        self.main_plot = self.main_axis = None
        self.axis_mode = "unit"
        self.scales = {}            # clé d'axe -> réglages (auto, min, max, graduations...)
        self._scale_key = None      # axe choisi dans l'arbre « Échelle »
        self._labels = {}
        self._applying = False      # plages posées par le programme
        self._scale_loading = False
        self._loading = False
        self._cursor = None         # instant du curseur (s)

        self.root = ptree.Parameter.create(name=GROUP, type="group")
        view.tree.setParameters(self.root, showTop=True)
        self.root.sigTreeStateChanged.connect(self._tree_changed)
        view.actionAdd.triggered.connect(self.add_curve)
        view.actionRefresh.triggered.connect(self.reload)
        view.actionExport.triggered.connect(self.export_csv)
        view.signals.itemChanged.connect(self._signal_checked)
        view.signals.currentItemChanged.connect(self._signal_current)
        self.scale_root = ptree.Parameter.create(name="Échelle", type="group")
        view.scale_tree.setParameters(self.scale_root, showTop=True)
        self.scale_root.sigTreeStateChanged.connect(self._scale_changed)
        view.axis_mode.setCurrentIndex(view.axis_mode.findData(self.axis_mode))
        view.axis_mode.currentIndexChanged.connect(self._mode_chosen)
        view.actionAutoScale.triggered.connect(self.auto_scales)
        self.reload()

    # ============================================================ composant
    @property
    def component(self):
        host = self.host()
        return None if host is None else host.component

    @property
    def curves(self) -> list:
        component = self.component
        return [] if component is None else component.computed

    def _editable(self) -> bool:
        host = self.host()
        return host is not None and host._editable(quiet=True)

    def _modified(self):
        host = self.host()
        if host is not None:
            host.set_dirty()

    def reload(self, *_):
        """Relit les signaux du composant, reconstruit l'arbre et recalcule."""
        component = self.component
        self.available = {} if component is None else signals.component_signals(component)
        self.inputs = {}
        for key, signal in self.available.items():       # un nom par courbe : le plus court
            known = next((k for k, s in self.inputs.items() if s is signal), None)
            if known is None or len(key) < len(known):
                self.inputs.pop(known, None)
                self.inputs[key] = signal
        self._fill_signals()
        self._build_tree()
        editable = self._editable()
        self.view.actionAdd.setEnabled(editable)
        self.view.tree.setEnabled(editable or not self.curves)
        self.recompute()

    def _fill_signals(self):
        widget = self.view.signals
        self._loading = True
        widget.clear()
        for key, signal in self.inputs.items():
            item = QtWidgets.QListWidgetItem(f"[{key}]" + (f"  ({signal.unit})" if signal.unit
                                                           else ""))
            item.setToolTip(f"{signal.source} : {len(signal.t)} points, "
                            f"t de {_format(signal.t[0], 's')} à {_format(signal.t[-1], 's')}")
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.CheckState.Unchecked if signal.source in self.hidden
                               else QtCore.Qt.CheckState.Checked)
            item.setForeground(pg.mkColor(signal.color))
            item.setData(ROLE, key)
            widget.addItem(item)
        if not self.inputs:
            item = QtWidgets.QListWidgetItem("aucun signal : il faut un graphique calibré")
            item.setFlags(QtCore.Qt.ItemFlag.NoItemFlags)
            widget.addItem(item)
        self._loading = False

    def _signal_checked(self, item):
        if self._loading:
            return
        signal = self.inputs.get(item.data(ROLE))
        if signal is None:
            return
        if item.checkState() == QtCore.Qt.CheckState.Checked:
            self.hidden.discard(signal.source)
        else:
            self.hidden.add(signal.source)
        self.refresh_plots()

    def set_signal_visible(self, key: str, visible: bool):
        """Coche ou décoche un signal (tests, scripts)."""
        for row in range(self.view.signals.count()):
            item = self.view.signals.item(row)
            if item.data(ROLE) == key:
                item.setCheckState(QtCore.Qt.CheckState.Checked if visible
                                   else QtCore.Qt.CheckState.Unchecked)

    # ============================================================ arbre des voies calculées
    def _build_tree(self):
        self._loading = True
        self.root.clearChildren()
        self.root.addChild({"name": HELP, "type": "str", "value": "survoler pour l'aide",
                            "readonly": True, "tip": signals.FUNCTIONS_HELP})
        for index, curve in enumerate(self.curves):
            self.root.addChild(self._curve_group(index, curve))
        self._loading = False

    @staticmethod
    def _curve_group(index: int, curve: ComputedCurve) -> dict:
        base = next(k for k, v in BASES.items() if v == curve.base) if curve.base in \
            BASES.values() else "signal le plus fin"
        return {"name": f"voie{index}", "title": curve.name, "type": "group", "children": [
            {"name": "Nom", "type": "str", "value": curve.name,
             "tip": "Nom de la voie, utilisable entre crochets dans les voies suivantes"},
            {"name": "Formule", "type": "str", "value": curve.formula,
             "tip": signals.FUNCTIONS_HELP},
            {"name": "Unité", "type": "str", "value": curve.unit,
             "tip": "Vide : déduite de la formule"},
            {"name": "Base de temps", "type": "list", "limits": list(BASES), "value": base,
             "tip": "Signal le plus fin des signaux utilisés (sur leur intervalle commun), "
                    "ou pas régulier propre"},
            {"name": "Pas", "type": "float", "value": curve.period, "suffix": "s",
             "siPrefix": True, "limits": (1e-15, None), "dec": True,
             "visible": curve.base == PERIOD},
            {"name": "Couleur", "type": "color", "value": curve.color},
            {"name": "Affichée", "type": "bool", "value": curve.visible},
            {"name": "État", "type": "str", "value": "", "readonly": True},
            {"name": "Supprimer", "type": "action"},
        ]}

    def _new_name(self) -> str:
        taken = {c.name for c in self.curves} | set(self.available)
        n = 1
        while f"M{n}" in taken:
            n += 1
        return f"M{n}"

    def add_curve(self, *_, formula: str = "", name: str | None = None) -> ComputedCurve | None:
        component = self.component
        if component is None or not self._editable():
            return None
        curve = ComputedCurve(name=name or self._new_name(), formula=formula,
                              color=COLORS[len(component.computed) % len(COLORS)])
        component.computed.append(curve)
        self._modified()
        self._build_tree()
        self.recompute()
        return curve

    def remove_curve(self, index: int):
        if not self._editable() or not 0 <= index < len(self.curves):
            return
        del self.curves[index]
        self._modified()
        self._build_tree()
        self.recompute()

    def _tree_changed(self, _param, changes):
        if self._loading:
            return
        for param, kind, data in changes:
            group = param.parent()
            if group is None or not group.name().startswith("voie"):
                continue
            index = int(group.name()[4:])
            if index >= len(self.curves):
                continue
            if kind == "activated" and param.name() == "Supprimer":
                self.remove_curve(index)
                return
            if kind != "value" or param.name() == "État":
                continue
            curve = self.curves[index]
            name = param.name()
            if name == "Nom":
                curve.name = str(data).strip() or curve.name
                group.setOpts(title=curve.name)
            elif name == "Formule":
                curve.formula = str(data)
            elif name == "Unité":
                curve.unit = str(data).strip()
            elif name == "Base de temps":
                curve.base = BASES.get(data, AUTO)
                group.child("Pas").setOpts(visible=curve.base == PERIOD)
            elif name == "Pas":
                curve.period = float(data)
            elif name == "Couleur":
                curve.color = pg.mkColor(data).name()
            elif name == "Affichée":
                curve.visible = bool(data)
            self._modified()
            if name == "Affichée":
                self.refresh_plots()
            else:
                self.recompute()

    def set_curve(self, index: int, **values):
        """Modifie une voie calculée comme dans l'arbre (tests, scripts) : Nom=..., Formule=..."""
        group = self.root.child(f"voie{index}")
        for key, value in values.items():
            group.child(key.replace("_", " ")).setValue(value)

    # ============================================================ calcul
    def recompute(self):
        self.results = signals.evaluate_all(self.curves, self.available)
        self._loading = True
        for index, result in enumerate(self.results):
            group = self.root.child(f"voie{index}")
            if group is None:
                continue
            state = group.child("État")
            if result.error:
                text, tip = f"⚠ {result.error}", result.error
            elif result.value is not None:
                text = "= " + _format(result.value, result.unit)
                tip = text
            else:
                text = "✓ " + (result.unit or "sans unité") + f", {len(result.t)} points"
                tip = text
            if result.warnings:
                text += "  (!)"
                tip += "\n" + "\n".join(result.warnings)
            state.setValue(text)
            state.setOpts(tip=tip)
        self._loading = False
        self.refresh_plots()

    def shown(self) -> list:
        """Signaux tracés : signaux cochés, puis voies calculées affichées et réussies."""
        out = [s for s in self.inputs.values() if s.source not in self.hidden]
        for curve, result in zip(self.curves, self.results):
            if curve.visible and result.signal is not None:
                out.append(result.signal)
        return out

    # ============================================================ tracés
    @staticmethod
    def _ident(signal) -> str:
        """Identité d'un signal tracé : courbe d'origine, ou nom de la voie calculée."""
        return f"calcul:{signal.name}" if signal.source == "calcul" else signal.source

    def _axis_key(self, group: list, mode: str) -> str:
        """Clé des réglages d'échelle d'un axe (gardés d'un tracé à l'autre)."""
        if mode == "single":
            return "*"
        if mode == "channel" and len(group) == 1:
            return "voie:" + self._ident(group[0])
        return "unité:" + group[0].unit

    def set_axis_mode(self, mode: str):
        if mode in y_axes.MODES and mode != self.axis_mode:
            self.axis_mode = mode
            index = self.view.axis_mode.findData(mode)
            if self.view.axis_mode.currentIndex() != index:
                self.view.axis_mode.setCurrentIndex(index)
            self.refresh_plots()

    def _mode_chosen(self, index):
        self.set_axis_mode(self.view.axis_mode.itemData(index))

    def auto_scales(self, *_):
        """Toutes les échelles de nouveau ajustées à leurs courbes."""
        for settings in self.scales.values():
            settings["auto"] = True
        self.refresh_plots()

    def refresh_plots(self):
        layout = self.view.plots
        for axis in self.axes:                  # ViewBox retirées : plus de nouvelles
            try:
                axis["vb"].sigYRangeChanged.disconnect(self._range_changed)
            except TypeError:
                pass
        if self.main_plot is not None and self.main_axis is not None:
            try:
                self.main_plot.vb.sigYRangeChanged.disconnect(self._main_y_changed)
            except TypeError:
                pass
        layout.clear()
        self.axes, self.lines, self.extra_scales = [], [], []
        self.main_plot = self.main_axis = None
        shown = self.shown()
        mode = self.axis_mode
        groups = y_axes.groups(shown, lambda s: s.unit, mode)
        if not groups:
            plot = layout.addPlot(row=0, col=0)
            theme.style_plot(plot)
            zoom.limit_empty(plot)
            plot.setLabel("bottom", "temps", units="s")
            self._fill_scale_tree()
            self.refresh_readings()
            return
        t_all = np.concatenate([s.t for s in shown])
        if mode == "split":
            self._build_split(groups, t_all)
        else:
            self._build_multi(groups, t_all, mode)
        self._applying = True
        try:
            for axis in self.axes:
                self._apply_scale(axis)
        finally:
            self._applying = False
        for scale in self.extra_scales:
            scale.store_relation()
        for axis in self.axes:
            axis["vb"].sigYRangeChanged.connect(self._range_changed)
        lo, hi = float(np.nanmin(t_all)), float(np.nanmax(t_all))
        if self._cursor is None or not lo <= self._cursor <= hi:
            self._cursor = (lo + hi) / 2
        self._fill_scale_tree()
        self.set_cursor(self._cursor)

    def _new_plot(self, row: int, axis_item=None) -> pg.PlotItem:
        items = {"left": axis_item} if axis_item is not None else None
        plot = pg.PlotItem(viewBox=y_axes.TimeViewBox(), axisItems=items)
        self.view.plots.addItem(plot, row=row, col=0)
        theme.style_plot(plot)
        plot.hideButtons()                      # « A » : bouton Échelles automatiques
        plot.getAxis("bottom").setGrid(77)
        plot.addLegend(offset=(10, 5))
        return plot

    def _add_axis(self, key, group, plot, vb, axis_item, label, unit, color=None):
        y_axes.style_axis(axis_item, label, unit, color)
        self.axes.append({"key": key, "signals": group, "plot": plot, "vb": vb,
                          "axis": axis_item, "label": label + (f" ({unit})" if unit else "")})

    def _curve(self, plot, vb, signal):
        curve = pg.PlotDataItem(signal.t, signal.y, pen=pg.mkPen(signal.color, width=1.5),
                                connect="finite", name=f"[{signal.name}]")
        if vb is plot.vb:
            plot.addItem(curve)
        else:                                   # hors du PlotItem : légende à la main
            vb.addItem(curve)
            plot.legend.addItem(curve, f"[{signal.name}]")

    def _cursor_line(self, plot):
        line = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen("#888", width=1))
        plot.addItem(line, ignoreBounds=True)
        line.sigPositionChanged.connect(self._cursor_moved)
        self.lines.append(line)

    def _build_split(self, groups, t_all):
        """Un graphique par unité, axes des temps liés (affichage d'avant les axes multiples)."""
        first = None
        for row, group in enumerate(groups):
            plot = self._new_plot(row)
            unit = group[0].unit
            self._add_axis(self._axis_key(group, "split"), group, plot, plot.vb,
                           plot.getAxis("left"), "" if unit else "sans unité", unit)
            for signal in group:
                self._curve(plot, plot.vb, signal)
            if row == len(groups) - 1:
                plot.setLabel("bottom", "temps", units="s")
            zoom.limit_axis(plot.vb, "x", float(np.nanmin(t_all)), float(np.nanmax(t_all)))
            if first is None:
                first = plot
            else:
                plot.setXLink(first)
            self._cursor_line(plot)
        self.main_plot = first

    def _build_multi(self, groups, t_all, mode):
        """Un graphique, un axe d'ordonnées par groupe (view/y_axes.py)."""
        main_axis = y_axes.MainAxis("left")
        plot = self._new_plot(0, main_axis)
        y_axes.reserve_columns(plot)
        plot.setLabel("bottom", "temps", units="s")
        self.main_plot, self.main_axis = plot, main_axis
        places = y_axes.columns(len(groups))
        self.extra_scales = [y_axes.AxisScale(plot, side, column)
                             for side, column in places[1:]]
        multiple = len(groups) > 1
        for g, group in enumerate(groups):
            if g == 0:
                vb, axis_item = plot.vb, main_axis
            else:
                scale = self.extra_scales[g - 1]
                vb, axis_item = scale.vb, scale.axis
            units = {s.unit for s in group}
            unit = units.pop() if len(units) == 1 else None
            if multiple and len(group) == 1:
                label, color = group[0].name, group[0].color
            else:
                label, color = ("" if unit else "Signaux"), None
            self._add_axis(self._axis_key(group, mode), group, plot, vb, axis_item, label,
                           unit, color)
            for signal in group:
                self._curve(plot, vb, signal)
        zoom.limit_axis(plot.vb, "x", float(np.nanmin(t_all)), float(np.nanmax(t_all)))
        plot.vb.sigYRangeChanged.connect(self._main_y_changed)
        self._cursor_line(plot)

    # ------------------------------------------------------------ échelles
    @staticmethod
    def _bounds(group) -> tuple:
        ys = np.concatenate([s.y[np.isfinite(s.y)] for s in group])
        return (float(ys.min()), float(ys.max())) if ys.size else (0.0, 1.0)

    def settings(self, key: str, grid: bool = True) -> dict:
        """Réglages d'un axe ; nouveaux : ajusté aux courbes, grille selon `grid`."""
        return self.scales.setdefault(key, {"auto": True, "min": 0.0, "max": 1.0,
                                            "major": 0.0, "minor": 0, "grid": grid})

    def _apply_scale(self, axis: dict):
        """Réglages de l'axe appliqués : plage (ajustée ou saisie), graduations, grille."""
        # grille du premier axe seulement par défaut (toutes ensemble : illisible)
        settings = self.settings(axis["key"], grid=axis is self.axes[0] or
                                 self.axis_mode == "split")
        lo, hi = self._bounds(axis["signals"])
        zoom.limit_y_free(axis["vb"], lo, hi)
        if settings["auto"]:
            settings["min"], settings["max"] = y_axes.fit_range((lo, hi))
        axis["vb"].setYRange(settings["min"], settings["max"], padding=0)
        item = axis["axis"]
        major = settings["major"]
        if major > 0:
            minor = major / settings["minor"] if settings["minor"] > 0 else major
            item.setTickSpacing(major, minor)
        else:
            item.setTickSpacing()
        item.setGrid(77 if settings["grid"] else False)

    def _main_y_changed(self, *_):
        """
        Plage de l'axe principal modifiée : les autres échelles la suivent (déplacement ou
        zoom du graphique), sauf réglage programmé ou action sur l'axe principal seul.
        """
        if self._applying or getattr(self, "main_axis", None) is None:
            return
        for scale in self.extra_scales:
            if self.main_axis.direct:
                scale.store_relation()
            else:
                scale.follow()

    def _range_changed(self, vb, *_):
        """Plage d'un axe changée à la souris : échelle désormais fixée par l'utilisateur."""
        if self._applying:
            return
        for axis in self.axes:
            if axis["vb"] is vb:
                settings = self.settings(axis["key"])
                settings["auto"] = False
                settings["min"], settings["max"] = (float(v) for v in vb.viewRange()[1])
                if axis is self.selected_axis():
                    self._show_scale(axis)
        for scale in self.extra_scales:
            if scale.vb is vb:
                scale.store_relation()

    # ------------------------------------------------------------ arbre « Échelle »
    def selected_axis(self) -> dict | None:
        return next((a for a in self.axes if a["key"] == self._scale_key), None) or \
            (self.axes[0] if self.axes else None)

    def select_axis_of(self, name: str):
        """Axe du signal nommé choisi dans l'arbre « Échelle »."""
        for axis in self.axes:
            if any(s.name == name for s in axis["signals"]):
                self._scale_key = axis["key"]
                self._fill_scale_tree()
                return

    def _signal_current(self, item, _previous=None):
        if item is not None and item.data(ROLE) is not None:
            signal = self.inputs.get(item.data(ROLE))
            if signal is not None:
                self.select_axis_of(signal.name)

    def _fill_scale_tree(self):
        axis = self.selected_axis()
        self._scale_loading = True
        self.scale_root.clearChildren()
        if axis is None:
            self._scale_loading = False
            return
        self._scale_key = axis["key"]
        unit = axis["signals"][0].unit if len({s.unit for s in axis["signals"]}) == 1 else ""
        settings = self.settings(axis["key"])
        labels = {a["label"] or "axe": a["key"] for a in self.axes}
        current = next(k for k, v in labels.items() if v == axis["key"])
        number = {"type": "float", "suffix": unit, "siPrefix": bool(unit), "dec": False}
        self.scale_root.addChildren([
            {"name": "Axe", "type": "list", "limits": list(labels), "value": current,
             "tip": "Axe d'ordonnées réglé (cliquer un signal le choisit aussi)"},
            {"name": "Automatique", "type": "bool", "value": settings["auto"],
             "tip": "Plage ajustée aux courbes de l'axe"},
            dict(number, name="Min", value=settings["min"]),
            dict(number, name="Max", value=settings["max"]),
            dict(number, name="Graduation", value=settings["major"], limits=(0, None),
                 tip="Pas des graduations principales (0 : automatique)"),
            {"name": "Sous-graduations", "type": "int", "value": settings["minor"],
             "limits": (0, 20), "tip": "Intervalles entre deux graduations principales "
                                       "(0 : automatique)"},
            {"name": "Grille", "type": "bool", "value": settings["grid"],
             "tip": "Lignes horizontales aux graduations de cet axe"},
        ])
        self._labels = labels
        self._scale_loading = False

    def _show_scale(self, axis: dict):
        """Min / max de l'arbre mis à jour (axe déplacé à la souris)."""
        settings = self.settings(axis["key"])
        self._scale_loading = True
        for name, value in (("Automatique", settings["auto"]), ("Min", settings["min"]),
                            ("Max", settings["max"])):
            child = self.scale_root.child(name)
            if child is not None:
                child.setValue(value)
        self._scale_loading = False

    def _scale_changed(self, _param, changes):
        if self._scale_loading:
            return
        axis = self.selected_axis()
        for param, kind, data in changes:
            if kind != "value" or axis is None:
                continue
            name = param.name()
            if name == "Axe":
                self._scale_key = self._labels.get(data, self._scale_key)
                self._fill_scale_tree()
                return
            settings = self.settings(axis["key"])
            if name == "Automatique":
                settings["auto"] = bool(data)
            elif name in ("Min", "Max"):
                settings[name.lower()] = float(data)
                settings["auto"] = False
                if settings["max"] <= settings["min"]:
                    continue                    # plage incohérente : attendre l'autre borne
            elif name == "Graduation":
                settings["major"] = float(data)
            elif name == "Sous-graduations":
                settings["minor"] = int(data)
            elif name == "Grille":
                settings["grid"] = bool(data)
            self._applying = True
            try:
                self._apply_scale(axis)
            finally:
                self._applying = False
            for scale in self.extra_scales:
                scale.store_relation()
            self._show_scale(axis)

    def set_scale(self, **values):
        """Réglage de l'axe choisi comme dans l'arbre (tests, scripts) : Min=..., Grille=..."""
        for key, value in values.items():
            self.scale_root.child(key.replace("_", "-")).setValue(value)

    # ------------------------------------------------------------ curseur
    def set_cursor(self, t: float):
        self._cursor = float(t)
        self._loading = True
        for line in self.lines:
            line.setValue(self._cursor)
        self._loading = False
        self.refresh_readings()

    def _cursor_moved(self, line):
        if not self._loading:
            self.set_cursor(line.value())

    def readings(self) -> list:
        """[(nom, valeur, unité)] des signaux tracés au curseur."""
        if self._cursor is None:
            return []
        out = []
        for signal in self.shown():
            value = float(np.interp(self._cursor, signal.t, signal.y, left=np.nan,
                                    right=np.nan))
            out.append((signal.name, value, signal.unit))
        return out

    def refresh_readings(self):
        reads = self.readings()
        if not reads:
            self.view.readings.setText("")
            return
        parts = [f"<b>t = {_format(self._cursor, 's')}</b>"]
        colors = {s.name: s.color for s in self.shown()}
        for name, value, unit in reads:
            parts.append(f"<span style='color:{colors.get(name, '#888')}'>[{name}]</span> "
                         f"= {_format(value, unit)}")
        scalars = [(c.name, r) for c, r in zip(self.curves, self.results)
                   if r.value is not None and not r.error]
        for name, result in scalars:
            parts.append(f"{name} = {_format(result.value, result.unit)}")
        self.view.readings.setText(" ; ".join(parts))

    # ============================================================ export
    def export_csv(self, *_, path=None) -> bool:
        shown = self.shown()
        if not shown:
            self.view.statusBar().showMessage("Aucun signal tracé", 4000)
            return False
        if path is None:
            folder = pathlib.Path(self.options.get("last_dir") or "")
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self.view, "Signaux", str(folder / "signaux.csv"), "CSV (*.csv)")
            if not path:
                return False
            self.options["last_dir"] = str(pathlib.Path(path).parent)
        sep = self.options.get("separator", ";")
        dec = self.options.get("decimal", ",")
        t = np.unique(np.concatenate([s.t for s in shown]))     # instants de tous les signaux

        def number(v):
            return "" if not np.isfinite(v) else format(v, ".6g").replace(".", dec)

        columns = [np.interp(t, s.t, s.y, left=np.nan, right=np.nan) for s in shown]
        lines = [sep.join(["t (s)"] + [f"{s.name} ({s.unit})" if s.unit else s.name
                                       for s in shown])]
        for i, ti in enumerate(t):
            lines.append(sep.join([number(ti)] + [number(c[i]) for c in columns]))
        pathlib.Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.view.statusBar().showMessage(f"Signaux écrits : {path}", 5000)
        return True
