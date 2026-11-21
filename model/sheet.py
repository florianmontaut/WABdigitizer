# model/sheet.py
"""
Fiche « ParamDigitizer component v1 » -> composant affichable, pour l'ouverture en
lecture seule d'une fiche sans projet (venue d'ailleurs, ou dont le projet est perdu).

La fiche n'a ni image ni calibration : chaque graphique reçoit une image blanche
quadrillée et une calibration orthonormée qui en couvre les données (log10 sur un axe
log), avec une marge. Les points sont convertis en pixels de cette image : le canevas,
la table, l'aperçu et les exports fonctionnent comme pour un projet.
"""
import numpy as np

from . import document, export
from .calibration import AxisCalibration, to_four_points
from .fit import FitResult

WIDTH, HEIGHT = 900, 600            # image de remplacement (pixels)
MARGIN = 60
DIVISIONS = 10
GRID = (215, 215, 215)
FRAME = (120, 120, 120)


class SheetError(ValueError):
    """Fiche inutilisable : message affichable."""


def _range(values, log: bool) -> tuple:
    """Bornes de l'espace calibré (log10 sur un axe log), jamais de largeur nulle."""
    values = np.asarray(values, dtype=float)
    scaled = np.log10(values) if log else values
    low, high = float(scaled.min()), float(scaled.max())
    if high - low < 1e-12:
        pad = 0.5 if log else max(abs(low) * 0.1, 1.0)
        low, high = low - pad, high + pad
    return low, high


def _image() -> np.ndarray:
    """Fond blanc, cadre et quadrillage aux dixièmes de la zone de tracé."""
    image = np.full((HEIGHT, WIDTH, 3), 255, np.uint8)
    left, right, top, bottom = MARGIN, WIDTH - MARGIN, MARGIN, HEIGHT - MARGIN
    for i in range(DIVISIONS + 1):
        col = int(round(left + (right - left) * i / DIVISIONS))
        row = int(round(top + (bottom - top) * i / DIVISIONS))
        color = FRAME if i in (0, DIVISIONS) else GRID
        image[top:bottom + 1, col] = color
        image[row, left:right + 1] = color
    return image


def _calibration(x_range, y_range, log_x, log_y) -> AxisCalibration:
    left, right, top, bottom = MARGIN, WIDTH - MARGIN, MARGIN, HEIGHT - MARGIN

    def value(scaled, log):
        return 10.0 ** scaled if log else scaled

    points = to_four_points((left, bottom), (right, bottom), (left, top))
    return AxisCalibration(*points, x1=value(x_range[0], log_x), x2=value(x_range[1], log_x),
                           y1=value(y_range[0], log_y), y2=value(y_range[1], log_y),
                           log_x=log_x, log_y=log_y)


def component_from_sheet(sheet: dict, source: str = "") -> tuple:
    """(composant, avertissements) d'une fiche. Les points inaffichables sont écartés."""
    if not isinstance(sheet, dict) or sheet.get("format") != export.COMPONENT_FORMAT:
        raise SheetError("ce fichier n'est pas une fiche ParamDigitizer")
    component = document.Component(
        name=sheet.get("name", ""), manufacturer=sheet.get("manufacturer", ""),
        part_number=sheet.get("part_number", ""), category=sheet.get("category", ""),
        notes=sheet.get("notes", ""))
    warnings = []
    for g, data in enumerate(sheet.get("graphs", [])):
        x_info, y_info = data.get("x", {}), data.get("y", {})
        log_x, log_y = bool(x_info.get("log", False)), bool(y_info.get("log", False))
        name = data.get("name", "") or f"Graphique {g + 1}"
        curves = []
        for c, curve in enumerate(data.get("curves", [])):
            x = np.asarray(curve.get("x", []), dtype=float)
            y = np.asarray(curve.get("y", []), dtype=float)
            if x.shape != y.shape:
                warnings.append(f"{name} : courbe {curve.get('name', c + 1)} ignorée "
                                "(x et y de longueurs différentes)")
                continue
            keep = np.isfinite(x) & np.isfinite(y)
            if log_x:
                keep &= x > 0
            if log_y:
                keep &= y > 0
            if (~keep).any():
                warnings.append(f"{name} : {int((~keep).sum())} point(s) inaffichable(s) "
                                f"écarté(s) dans « {curve.get('name', '')} »")
            curves.append((curve, x[keep], y[keep]))
        xs = np.concatenate([x for _, x, _ in curves]) if curves else np.empty(0)
        ys = np.concatenate([y for _, _, y in curves]) if curves else np.empty(0)
        if not len(xs):
            xs, ys = np.array([1.0, 10.0]), np.array([1.0, 10.0])
        calibration = _calibration(_range(xs, log_x), _range(ys, log_y), log_x, log_y)
        graph = document.Graph(name=name, image=_image(), source=source,
                               x_axis=document.Axis(x_info.get("quantity", ""),
                                                    x_info.get("unit", "")),
                               y_axis=document.Axis(y_info.get("quantity", ""),
                                                    y_info.get("unit", "")))
        graph.calibration = calibration
        for c, (curve, x, y) in enumerate(curves):
            dataset = document.Dataset(name=curve.get("name", "") or f"Courbe {c + 1}",
                                       color=document.PALETTE[c % len(document.PALETTE)],
                                       condition=curve.get("condition", ""))
            dataset.set_data(np.column_stack((x, y)), calibration)
            if curve.get("model"):
                try:
                    dataset.fit = FitResult.from_dict(curve["model"])
                except (KeyError, TypeError, ValueError):
                    warnings.append(f"{name} : modèle de « {dataset.name} » illisible")
            graph.datasets.append(dataset)
        component.graphs.append(graph)
    return component, warnings
