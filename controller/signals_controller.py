# controller/signals_controller.py
"""
Contrôleur de la fenêtre « Calculs entre signaux » : signaux du composant ouvert (courbes
des graphiques calibrés), voies calculées du composant (Component.computed, enregistrées
dans le projet, hors de la pile d'annulation comme les autres propriétés), recalcul à
chaque modification, tracés regroupés par unité, curseur, export CSV.
"""
import pathlib

import numpy as np
import pyqtgraph as pg
import pyqtgraph.parametertree as ptree
from PyQt6 import QtCore, QtWidgets

from model import signals
from model.signals import AUTO, PERIOD, ComputedCurve
from qtsocle import theme
from view import zoom

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
        self.plots = []             # [(unité, PlotItem, InfiniteLine)]
        self._loading = False
        self._cursor = None         # instant du curseur (s)

        self.root = ptree.Parameter.create(name=GROUP, type="group")
        view.tree.setParameters(self.root, showTop=True)
        self.root.sigTreeStateChanged.connect(self._tree_changed)
        view.actionAdd.triggered.connect(self.add_curve)
        view.actionRefresh.triggered.connect(self.reload)
        view.actionExport.triggered.connect(self.export_csv)
        view.signals.itemChanged.connect(self._signal_checked)
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
    def refresh_plots(self):
        layout = self.view.plots
        layout.clear()
        self.plots = []
        shown = self.shown()
        groups = {}
        for signal in shown:
            groups.setdefault(signal.unit, []).append(signal)
        if not groups:
            plot = layout.addPlot(row=0, col=0)
            zoom.limit_empty(plot)
            plot.setLabel("bottom", "temps", units="s")
            self.plots.append(("", plot, None))
            self.refresh_readings()
            return
        first = None
        for row, (unit, group) in enumerate(groups.items()):
            plot = layout.addPlot(row=row, col=0)
            theme.style_plot(plot)
            plot.showGrid(x=True, y=True, alpha=0.3)
            plot.addLegend(offset=(10, 5))
            plot.setLabel("left", unit or "sans unité")
            if row == len(groups) - 1:
                plot.setLabel("bottom", "temps", units="s")
            for signal in group:
                plot.plot(signal.t, signal.y, name=f"[{signal.name}]",
                          pen=pg.mkPen(signal.color, width=1.5), connect="finite")
            zoom.limit_plot(plot, [s.t for s in group], [s.y for s in group])
            if first is None:
                first = plot
            else:
                plot.setXLink(first)
            line = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen("#888", width=1))
            plot.addItem(line, ignoreBounds=True)
            line.sigPositionChanged.connect(self._cursor_moved)
            self.plots.append((unit, plot, line))
        t = np.concatenate([s.t for s in shown])
        lo, hi = float(np.nanmin(t)), float(np.nanmax(t))
        if self._cursor is None or not lo <= self._cursor <= hi:
            self._cursor = (lo + hi) / 2
        self.set_cursor(self._cursor)

    def set_cursor(self, t: float):
        self._cursor = float(t)
        self._loading = True
        for _, _, line in self.plots:
            if line is not None:
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
