# model/export.py
"""
Sorties des courbes numérisées :
    csv_text            une courbe ou toutes les courbes d'un graphique (x, y par courbe)
    common_grid         toutes les courbes sur les mêmes X (tableau 2D, tables PLECS)
    lut_formula         table de correspondance du paquet formules : interp(x; x1; y1; ...)
    component_dict      fiche du composant sans images (« ParamDigitizer component v1 »),
                        lue par le logiciel de dimensionnement
"""
import json
import os
import pathlib

import numpy as np
from formules import lut

from .extraction import interpolate

COMPONENT_FORMAT = "ParamDigitizer component v1"


def _number(value: float, decimal: str) -> str:
    text = format(float(value), ".8g") if np.isfinite(value) else ""
    return text.replace(".", decimal) if decimal != "." else text


def csv_text(graph, datasets=None, separator: str = ";", decimal: str = ",") -> str:
    """Colonnes x, y côte à côte, une paire par courbe (longueurs différentes admises)."""
    datasets = graph.datasets if datasets is None else datasets
    columns, header = [], []
    x_label = graph.x_axis.label("X")
    y_label = graph.y_axis.label("Y")
    for dataset in datasets:
        data = dataset.data(graph.calibration)
        suffix = f" [{dataset.name}]"
        header += [x_label + suffix, y_label + suffix]
        columns += [data[:, 0], data[:, 1]]
    rows = [separator.join(header)]
    length = max((len(c) for c in columns), default=0)
    for i in range(length):
        rows.append(separator.join(_number(c[i], decimal) if i < len(c) else "" for c in columns))
    return "\n".join(rows) + "\n"


def common_grid(graph, x_values, datasets=None, method: str = "pchip",
                extrapolate: bool = False) -> np.ndarray:
    """
    Tableau (len(x), 1 + nombre de courbes) : X puis Y de chaque courbe interpolée sur X,
    dans l'espace calibré (log sur un axe log). nan hors de la plage relevée.
    """
    calibration = graph.calibration
    if calibration is None:
        raise ValueError("graphique non calibré")
    datasets = graph.datasets if datasets is None else datasets
    x_values = np.asarray(x_values, dtype=float)
    x_scaled = calibration.data_to_scaled(np.column_stack((x_values, np.ones_like(x_values))))[:, 0]
    table = [x_values]
    for dataset in datasets:
        if len(dataset) < 2:
            table.append(np.full(x_values.shape, np.nan))
            continue
        scaled = calibration.pixel_to_scaled(dataset.pixels)
        y_scaled = interpolate(scaled[:, 0], scaled[:, 1], x_scaled, method, extrapolate)
        y = calibration.scaled_to_data(np.column_stack((x_scaled, y_scaled)))[:, 1]
        table.append(y)
    return np.column_stack(table)


def lut_formula(graph, dataset, variable: str = "x", function: str = "interp") -> str:
    """Courbe sous forme de table formules : interp(x; x1; y1; x2; y2...)."""
    data = dataset.data(graph.calibration)
    data = data[np.isfinite(data).all(axis=1)]
    data = data[np.argsort(data[:, 0], kind="stable")]
    return lut.format_call(function, variable, [tuple(row) for row in data])


def component_dict(component) -> dict:
    """Fiche du composant pour le logiciel de dimensionnement : valeurs physiques seules."""
    graphs = []
    for graph in component.graphs:
        if graph.calibration is None:
            continue
        curves = []
        for dataset in graph.datasets:
            data = dataset.data(graph.calibration)
            data = data[np.argsort(data[:, 0], kind="stable")]
            entry = {"name": dataset.name, "condition": dataset.condition,
                     "x": data[:, 0].tolist(), "y": data[:, 1].tolist()}
            if dataset.fit is not None:
                entry["model"] = dataset.fit.to_dict()
            curves.append(entry)
        graphs.append({"name": graph.name,
                       "x": {"quantity": graph.x_axis.quantity, "unit": graph.x_axis.unit,
                             "log": graph.calibration.log_x},
                       "y": {"quantity": graph.y_axis.quantity, "unit": graph.y_axis.unit,
                             "log": graph.calibration.log_y},
                       "curves": curves})
    return {"format": COMPONENT_FORMAT, "name": component.name,
            "manufacturer": component.manufacturer, "part_number": component.part_number,
            "category": component.category, "notes": component.notes, "graphs": graphs}


def write_text(path, text: str) -> None:
    path = pathlib.Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def write_component(component, path) -> None:
    write_text(path, json.dumps(component_dict(component), ensure_ascii=False, indent=1))
