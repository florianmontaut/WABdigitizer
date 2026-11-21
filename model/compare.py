# model/compare.py
"""
Comparaison de courbes numérisées entre composants, de types quelconques.

Deux courbes sont comparables quand leurs axes ont les mêmes dimensions physiques
(formules.units), quels que soient leurs noms : VCE(IC) d'un IGBT, VDS(ID) d'un MOSFET et
VF(IF) d'une diode sont toutes une « tension en fonction d'un courant ». Les unités sont
converties vers celles de la première courbe choisie (mJ / µJ, kA / A...).

Sources : fiches « ParamDigitizer component v1 » et projets *.pdig.json (entrées de
model.library, ou fichiers ajoutés), lus dans la même forme (model.export.component_dict).
"""
import json
import pathlib
from dataclasses import dataclass

import numpy as np
from formules import units

from . import document, export, library


class CompareError(ValueError):
    """Fichier illisible ou courbes incomparables : message affichable."""


# ================================================================ courbes
@dataclass(frozen=True)
class Axis:
    quantity: str
    unit: str
    log: bool

    @property
    def parsed(self):
        """Unité lue par formules, None si absente ou inconnue."""
        try:
            return units.parse_unit(self.unit)
        except units.UnitError:
            return None

    @property
    def dims(self):
        unit = self.parsed
        return unit.dims if unit is not None else None

    @property
    def scale(self) -> float:
        unit = self.parsed
        return unit.scale if unit is not None else 1.0

    def label(self) -> str:
        return f"{self.quantity} ({self.unit})" if self.unit else self.quantity or "?"


@dataclass(frozen=True)
class Curve:
    component: str          # nom affiché du composant
    category: str
    source: str             # fichier d'origine (ou « composant ouvert »)
    graph: str
    name: str
    condition: str
    x_axis: Axis
    y_axis: Axis
    x: np.ndarray           # dans l'unité de son axe
    y: np.ndarray

    @property
    def key(self) -> str:
        """Identifiant stable dans une session : source / graphique / courbe."""
        return f"{self.source}|{self.graph}|{self.name}"

    @property
    def label(self) -> str:
        text = f"{self.component} — {self.name}"
        return f"{text} ({self.condition})" if self.condition else text

    @property
    def characteristic(self):
        return characteristic_of(self.x_axis, self.y_axis)


def characteristic_of(x_axis: Axis, y_axis: Axis):
    """
    Clé de regroupement : dimensions (X, Y) si les deux unités sont connues, sinon les
    noms des grandeurs (seules les courbes de mêmes noms sont alors comparées).
    """
    if x_axis.dims is not None and y_axis.dims is not None:
        return ("dims", x_axis.dims, y_axis.dims)
    return ("names", x_axis.label(), y_axis.label())


def characteristic_label(key) -> str:
    """« tension en fonction de courant (V, A) »."""
    if key[0] == "names":
        return f"{key[2]} en fonction de {key[1]}"
    x_name, y_name = units.quantity(key[1]), units.quantity(key[2])
    x_unit, y_unit = units.dims_text(key[1]), units.dims_text(key[2])
    return f"{y_name or y_unit} en fonction de {x_name or x_unit} ({y_unit}, {x_unit})"


# ================================================================ lecture
def sheet_of(path) -> dict:
    """Fiche composant (forme de export.component_dict) d'une fiche ou d'un projet."""
    path = pathlib.Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise CompareError(f"{path.name} : illisible ({error})") from None
    if not isinstance(data, dict):
        raise CompareError(f"{path.name} : format inconnu")
    if data.get("format") == export.COMPONENT_FORMAT:
        return data
    if data.get("format") == document.PROJECT_FORMAT:
        return export.component_dict(document.Component.from_dict(data))
    raise CompareError(f"{path.name} : ni fiche ni projet ParamDigitizer")


def curves_of(sheet: dict, source: str) -> list:
    """Courbes d'au moins 2 points d'une fiche."""
    name = sheet.get("part_number") or sheet.get("name") or source
    out = []
    for graph in sheet.get("graphs", []):
        x_axis = Axis(graph["x"].get("quantity", ""), graph["x"].get("unit", ""),
                      bool(graph["x"].get("log", False)))
        y_axis = Axis(graph["y"].get("quantity", ""), graph["y"].get("unit", ""),
                      bool(graph["y"].get("log", False)))
        for curve in graph.get("curves", []):
            x = np.asarray(curve.get("x", []), dtype=float)
            y = np.asarray(curve.get("y", []), dtype=float)
            keep = np.isfinite(x) & np.isfinite(y)
            if keep.sum() < 2:
                continue
            order = np.argsort(x[keep], kind="stable")
            out.append(Curve(component=name, category=sheet.get("category", ""),
                             source=source, graph=graph.get("name", ""),
                             name=curve.get("name", ""), condition=curve.get("condition", ""),
                             x_axis=x_axis, y_axis=y_axis,
                             x=x[keep][order], y=y[keep][order]))
    return out


def library_files(folder) -> list:
    """
    Un fichier par composant de la librairie (sous-dossiers compris, corbeille exceptée) :
    sa fiche, sinon son projet. Un composant publié (fiche + projet) n'est lu qu'une fois.
    """
    return [entry.data_path for entry in library.scan(folder)[0]]


def load_files(paths) -> tuple:
    """(courbes, erreurs) : les fichiers illisibles ou étrangers sont signalés, pas bloquants."""
    curves, errors = [], []
    for path in paths:
        try:
            curves += curves_of(sheet_of(path), str(path))
        except (CompareError, KeyError, TypeError) as error:
            errors.append(str(error) if isinstance(error, CompareError)
                          else f"{pathlib.Path(path).name} : {error!r}")
    return curves, errors


# ================================================================ affichage commun
@dataclass(frozen=True)
class Frame:
    """Axes communs d'une comparaison : unités d'affichage et échelles."""
    x_axis: Axis
    y_axis: Axis

    @classmethod
    def for_curves(cls, curves) -> "Frame":
        """Unités de la première courbe ; erreur si une courbe a d'autres dimensions."""
        if not curves:
            raise CompareError("aucune courbe choisie")
        first = curves[0]
        for curve in curves[1:]:
            if curve.characteristic != first.characteristic:
                raise CompareError(f"« {curve.label} » n'est pas comparable à « {first.label} » "
                                   f"({characteristic_label(curve.characteristic)})")
        quantity = lambda attr: " / ".join(dict.fromkeys(getattr(c, attr).quantity
                                                           for c in curves if getattr(c, attr).quantity))
        return cls(Axis(quantity("x_axis"), first.x_axis.unit, first.x_axis.log),
                   Axis(quantity("y_axis"), first.y_axis.unit, first.y_axis.log))

    def convert(self, curve: Curve) -> tuple:
        """(x, y) de la courbe dans les unités communes."""
        return (curve.x * curve.x_axis.scale / self.x_axis.scale,
                curve.y * curve.y_axis.scale / self.y_axis.scale)


def value_at(x, y, at, log_x=False, log_y=False):
    """
    y(at) par interpolation linéaire, en log sur un axe log (une droite d'un graphique
    log-log le reste) ; nan hors de la plage relevée.
    """
    x, y = np.asarray(x, float), np.asarray(y, float)
    at = np.asarray(at, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        xs = np.log10(x) if log_x else x
        ys = np.log10(y) if log_y else y
        target = np.log10(at) if log_x else at
        valid = np.isfinite(xs) & np.isfinite(ys)
        xs, ys = xs[valid], ys[valid]
        if len(xs) < 2:
            return np.full(at.shape, np.nan)
        result = np.interp(target, xs, ys)
        result = np.where((target >= xs[0]) & (target <= xs[-1]), result, np.nan)
        return np.power(10.0, result) if log_y else result


@dataclass
class Reading:
    curve: Curve
    value: float
    delta: float            # écart à la référence (unités communes)
    relative: float         # écart relatif à la référence


def readings(curves, at: float, reference: int | None = None, frame: Frame | None = None,
             log_x: bool | None = None, log_y: bool | None = None) -> list:
    """Valeur de chaque courbe à X = at et écart à la courbe d'indice reference."""
    frame = frame or Frame.for_curves(curves)
    log_x = frame.x_axis.log if log_x is None else log_x
    log_y = frame.y_axis.log if log_y is None else log_y
    values = [float(value_at(*frame.convert(c), at, log_x, log_y)) for c in curves]
    ref = values[reference] if reference is not None and 0 <= reference < len(values) else np.nan
    out = []
    for curve, value in zip(curves, values):
        delta = value - ref
        with np.errstate(divide="ignore", invalid="ignore"):
            relative = delta / ref if ref != 0 else np.nan
        out.append(Reading(curve, value, float(delta), float(relative)))
    return out


def common_table(curves, x_values, frame: Frame | None = None,
                 log_x: bool | None = None, log_y: bool | None = None) -> np.ndarray:
    """Tableau (len(x), 1 + courbes) : X puis chaque courbe interpolée, unités communes."""
    frame = frame or Frame.for_curves(curves)
    log_x = frame.x_axis.log if log_x is None else log_x
    log_y = frame.y_axis.log if log_y is None else log_y
    x_values = np.asarray(x_values, dtype=float)
    columns = [x_values] + [value_at(*frame.convert(c), x_values, log_x, log_y) for c in curves]
    return np.column_stack(columns)


def default_axis(curves, frame: Frame, count: int = 50, log: bool | None = None) -> np.ndarray:
    """X communs : de la plus petite à la plus grande abscisse relevée, count points."""
    log = frame.x_axis.log if log is None else log
    xs = np.concatenate([frame.convert(c)[0] for c in curves])
    low, high = float(xs.min()), float(xs.max())
    if log and low > 0:
        return np.logspace(np.log10(low), np.log10(high), count)
    return np.linspace(low, high, count)


def csv_text(curves, x_values, frame: Frame | None = None, separator=";", decimal=",",
             log_x=None, log_y=None) -> str:
    frame = frame or Frame.for_curves(curves)
    table = common_table(curves, x_values, frame, log_x, log_y)
    header = [frame.x_axis.label()] + [f"{frame.y_axis.label()} [{c.label}]" for c in curves]
    lines = [separator.join(header)]
    for row in table:
        lines.append(separator.join("" if not np.isfinite(v) else
                                    format(v, ".8g").replace(".", decimal) for v in row))
    return "\n".join(lines) + "\n"
