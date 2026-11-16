# model/plecs.py
"""
Export d'un composant au format de description thermique PLECS (XML
« SemiconductorLibrary » 1.1, espace de noms http://www.plexim.com/xml/semiconductors/).

Chaque graphique a un rôle :
    conduction   chute de tension v(i)        -> <ConductionLoss>, table v[T][i]
    turn_on      énergie à la fermeture E(i)  -> <TurnOnLoss>,     table E[T][V][i]
    turn_off     énergie à l'ouverture E(i)   -> <TurnOffLoss>     (Eoff, ou Err d'une diode)
Chaque courbe porte sa température de jonction (°C) et, pour les énergies, la tension
de commutation (V) : champs de la courbe, sinon lus dans sa condition (« Tj = 125 °C,
VCE = 600 V »).

Tables : toutes les courbes d'un rôle sont rééchantillonnées sur le même axe de courant
(interpolation linéaire, comme PLECS ; prolongement linéaire au-delà des points relevés,
signalé). Options :
    origin         ajoute le point (0, 0) à chaque courbe (énergie / chute nulles à i = 0)
    zero_voltage   ajoute une tension 0 V d'énergie nulle (PLECS interpole alors
                   l'énergie proportionnellement à la tension)
    safety_factor  variable Csecu et formules E*Csecu / v*Csecu (« Table and formula »)
Les valeurs sont écrites dans l'unité de l'axe Y (mJ...) avec l'attribut scale vers le SI,
le courant est converti en ampères.
"""
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import numpy as np
from formules import lut, units

NAMESPACE = "http://www.plexim.com/xml/semiconductors/"
VERSION = "1.1"

ROLES = {
    "": "Aucun",
    "conduction": "Conduction : chute de tension v(i)",
    "turn_on": "Fermeture : énergie Eon(i)",
    "turn_off": "Ouverture : énergie Eoff(i) / Err(i)",
}
# rôle -> (élément XML, élément des valeurs, variable de la formule, dimension Y)
ELEMENTS = {
    "turn_on": ("TurnOnLoss", "Energy", "E", "J"),
    "turn_off": ("TurnOffLoss", "Energy", "E", "J"),
    "conduction": ("ConductionLoss", "VoltageDrop", "v", "V"),
}
# catégorie du composant -> classe PLECS
CLASSES = {"IGBT": "IGBT", "MOSFET": "MOSFET", "Diode": "Diode", "Thyristor": "Thyristor"}
SAFETY_VARIABLE = "Csecu"
EXTRAPOLATION_WARNING = 0.05      # prolongement signalé au-delà de 5 % de la plage relevée

_NUMBER = r"(-?\d+(?:[.,]\d+)?)"
_TEMPERATURE = re.compile(r"\bT\w*\s*=\s*" + _NUMBER + r"\s*°?\s*C\b", re.IGNORECASE)
# tension de commutation : VCE, VDS, VCC, VDD, VR, VKA, VDC, Vbus (pas VGE / VGS)
_VOLTAGE = re.compile(r"\bV(?:CE|DS|CC|DD|R|KA|DC|bus|ce|ds|cc|dd|r|ka|dc)\w*\s*=\s*"
                      + _NUMBER + r"\s*(k?)V\b")


class PlecsError(ValueError):
    """Composant incomplet pour PLECS : message affichable tel quel."""


@dataclass
class PlecsSettings:
    current_axis: str = ""          # « 0 10 20 ... » ; vide : axe automatique
    current_points: int = 10        # axe automatique : nombre d'intervalles
    origin: bool = True
    zero_voltage: bool = True
    safety_factor: bool = False
    foster: str = ""                # lignes « R tau » (K/W, s), collées depuis Excel

    def to_dict(self) -> dict:
        return dict(vars(self))

    @classmethod
    def from_dict(cls, data: dict | None) -> "PlecsSettings":
        known = {k: v for k, v in (data or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)


# ================================================================ conditions
def _number(text: str) -> float:
    return float(text.replace(",", "."))


def parse_condition(text: str) -> tuple:
    """(température °C, tension V) lues dans « Tj = 125 °C, VCE = 600 V » ; None si absentes."""
    text = text or ""
    match = _TEMPERATURE.search(text)
    temperature = _number(match.group(1)) if match else None
    match = _VOLTAGE.search(text)
    voltage = None
    if match:
        voltage = _number(match.group(1)) * (1000.0 if match.group(2) else 1.0)
    return temperature, voltage


def curve_conditions(dataset) -> tuple:
    """(T, V) de la courbe : champs saisis, sinon lus dans la condition."""
    parsed_t, parsed_v = parse_condition(dataset.condition)
    t = dataset.temperature if dataset.temperature is not None else parsed_t
    v = dataset.voltage if dataset.voltage is not None else parsed_v
    return t, v


# ================================================================ axes et unités
def _unit_scale(unit_text: str, dimension: str, what: str) -> float:
    """Facteur vers le SI de l'unité d'un axe, après contrôle de sa dimension."""
    try:
        unit = units.parse_unit(unit_text)
    except units.UnitError:
        raise PlecsError(f"{what} : unité « {unit_text} » non reconnue "
                         f"(attendue : {dimension} ou multiple)") from None
    if unit.dims != units.parse_unit(dimension).dims:
        name = units.quantity(units.parse_unit(dimension).dims)
        article = "d'" if name[:1] in "aeéiouy" else "de "
        raise PlecsError(f"{what} : « {unit_text} » n'est pas une unité {article}{name}")
    return unit.scale


def nice_step(span: float, intervals: int) -> float:
    """Pas « rond » (1, 2, 2,5 ou 5 × 10^k) donnant environ intervals intervalles."""
    raw = span / max(1, intervals)
    power = 10.0 ** np.floor(np.log10(raw))
    for factor in (1.0, 2.0, 2.5, 5.0, 10.0):
        if raw <= factor * power * (1 + 1e-9):
            return factor * power
    return 10.0 * power


def current_axis(settings: PlecsSettings, curves) -> np.ndarray:
    """Axe de courant commun (A), saisi ou automatique de 0 au plus fort courant relevé."""
    if settings.current_axis.strip():
        try:
            values = [lut.parse_number(v) for v in re.split(r"[\s;]+", settings.current_axis.strip())]
        except ValueError as error:
            raise PlecsError(f"axe de courant : « {error} » n'est pas un nombre") from None
        axis = np.array(values)
        if len(axis) < 2 or np.any(np.diff(axis) <= 0):
            raise PlecsError("axe de courant : au moins 2 valeurs strictement croissantes")
        return axis
    i_max = max(curve["i"].max() for curve in curves)
    if i_max <= 0:
        raise PlecsError("courants relevés tous négatifs ou nuls")
    step = nice_step(i_max, settings.current_points)
    return np.arange(0.0, np.ceil(i_max / step - 1e-9) * step + step / 2, step)


def resample(i, y, axis, origin: bool) -> tuple:
    """y(axis) par interpolation linéaire, prolongée linéairement ; (valeurs, prolongement)."""
    order = np.argsort(i, kind="stable")
    i, y = np.asarray(i, float)[order], np.asarray(y, float)[order]
    if origin and i[0] > 0:
        i, y = np.r_[0.0, i], np.r_[0.0, y]
    values = np.interp(axis, i, y)
    low, high = axis < i[0], axis > i[-1]
    if len(i) >= 2:
        values[low] = y[0] + (axis[low] - i[0]) * (y[1] - y[0]) / (i[1] - i[0])
        values[high] = y[-1] + (axis[high] - i[-1]) * (y[-1] - y[-2]) / (i[-1] - i[-2])
    span = i[-1] - i[0]
    beyond = max(0.0, i[0] - axis.min(), axis.max() - i[-1])
    return values, beyond > EXTRAPOLATION_WARNING * span


# ================================================================ courbes d'un rôle
def collect(component, role: str) -> list:
    """
    Courbes des graphiques de ce rôle, en unités SI pour le courant :
    {name, T, V, i (A), y (unité de l'axe Y), y_scale}.
    """
    element, _, _, dimension = ELEMENTS[role]
    curves = []
    for graph in component.graphs:
        if graph.plecs_role != role:
            continue
        where = f"« {graph.name} »"
        if graph.calibration is None:
            raise PlecsError(f"{where} : graphique non calibré")
        i_scale = _unit_scale(graph.x_axis.unit, "A", f"{where}, axe X")
        y_scale = _unit_scale(graph.y_axis.unit, dimension, f"{where}, axe Y")
        for dataset in graph.datasets:
            if len(dataset) < 2:
                continue
            name = f"{where} / « {dataset.name} »"
            temperature, voltage = curve_conditions(dataset)
            if temperature is None:
                raise PlecsError(f"{name} : température de jonction inconnue "
                                 "(champ Tj, ou « Tj = 125 °C » dans la condition)")
            if role != "conduction" and voltage is None:
                raise PlecsError(f"{name} : tension de commutation inconnue "
                                 "(champ Tension, ou « VCE = 600 V » dans la condition)")
            data = dataset.data(graph.calibration)
            data = data[np.isfinite(data).all(axis=1)]
            curves.append({"name": name, "T": float(temperature),
                           "V": None if voltage is None else float(voltage),
                           "i": data[:, 0] * i_scale, "y": data[:, 1], "y_scale": y_scale})
    return curves


def _common_scale(curves) -> float:
    """Unité d'écriture : celle de la première courbe ; les autres y sont converties."""
    scale = curves[0]["y_scale"]
    for curve in curves:
        curve["y"] = curve["y"] * curve["y_scale"] / scale
    return scale


def _format(values) -> str:
    return " " + " ".join(lut.format_number(round(float(v), 12)) for v in values)


# ================================================================ construction du XML
def _loss_element(parent, role, curves, settings, warnings):
    element, values_tag, variable, _ = ELEMENTS[role]
    axis = current_axis(settings, curves)
    scale = _common_scale(curves)
    temperatures = sorted({c["T"] for c in curves})
    node = ET.SubElement(parent, element)
    if settings.safety_factor:
        ET.SubElement(node, "ComputationMethod").text = "Table and formula"
        ET.SubElement(node, "Formula").text = f"{variable}*{SAFETY_VARIABLE}"
    else:
        ET.SubElement(node, "ComputationMethod").text = "Table only"
        ET.SubElement(node, "Formula").text = variable
    ET.SubElement(node, "CurrentAxis").text = _format(axis)

    def row(curve):
        values, extrapolated = resample(curve["i"], curve["y"], axis, settings.origin)
        if extrapolated:
            warnings.append(f"{curve['name']} : prolongée au-delà des points relevés "
                            f"(axe de courant {axis[0]:g} à {axis[-1]:g} A)")
        return values

    if role == "conduction":
        by_temperature = {}
        for curve in curves:
            if curve["T"] in by_temperature:
                raise PlecsError(f"conduction : deux courbes à {curve['T']:g} °C "
                                 f"({by_temperature[curve['T']]['name']}, {curve['name']})")
            by_temperature[curve["T"]] = curve
        ET.SubElement(node, "TemperatureAxis").text = _format(temperatures)
        table = ET.SubElement(node, values_tag, scale=lut.format_number(scale))
        for t in temperatures:
            ET.SubElement(table, "Temperature").text = _format(row(by_temperature[t]))
        return

    voltages = sorted({c["V"] for c in curves})
    added_zero = settings.zero_voltage and 0.0 not in voltages
    if added_zero:
        voltages = [0.0] + voltages
    grid = {}
    for curve in curves:
        key = (curve["T"], curve["V"])
        if key in grid:
            raise PlecsError(f"{element} : deux courbes à {key[0]:g} °C et {key[1]:g} V "
                             f"({grid[key]['name']}, {curve['name']})")
        grid[key] = curve
    missing = [(t, v) for t in temperatures for v in voltages
               if (t, v) not in grid and not (added_zero and v == 0.0)]
    if missing:
        text = ", ".join(f"{t:g} °C / {v:g} V" for t, v in missing)
        raise PlecsError(f"{element} : la table demande une courbe pour chaque couple "
                         f"température / tension ; il manque : {text}")
    ET.SubElement(node, "VoltageAxis").text = _format(voltages)
    ET.SubElement(node, "TemperatureAxis").text = _format(temperatures)
    table = ET.SubElement(node, values_tag, scale=lut.format_number(scale))
    for t in temperatures:
        block = ET.SubElement(table, "Temperature")
        for v in voltages:
            values = np.zeros_like(axis) if (t, v) not in grid else row(grid[(t, v)])
            ET.SubElement(block, "Voltage").text = _format(values)


def foster_elements(text: str) -> list:
    """Lignes « R tau » -> [(R, tau)] ; PlecsError si illisible ou non positif."""
    if not (text or "").strip():
        return []
    try:
        rows = lut.parse_rows(text)
    except ValueError as error:
        raise PlecsError(f"modèle thermique : {error}") from None
    if any(r <= 0 or tau <= 0 for r, tau in rows):
        raise PlecsError("modèle thermique : R et tau doivent être positifs")
    return rows


def build(component, settings: PlecsSettings | None = None) -> tuple:
    """(texte XML, avertissements). PlecsError si le composant ne peut pas être exporté."""
    settings = settings or component.plecs
    device = CLASSES.get(component.category)
    if device is None:
        raise PlecsError(f"catégorie « {component.category or 'aucune'} » : choisir "
                         + ", ".join(CLASSES) + " pour un export PLECS")
    warnings = []
    roles = [role for role in ("turn_on", "turn_off", "conduction")
             if any(g.plecs_role == role for g in component.graphs)]
    if not roles:
        raise PlecsError("aucun graphique n'a de rôle PLECS (conduction, Eon, Eoff / Err)")

    ET.register_namespace("", NAMESPACE)
    q = f"{{{NAMESPACE}}}"
    root = ET.Element(q + "SemiconductorLibrary", version=VERSION)
    package = ET.SubElement(root, q + "Package", {
        "class": device, "vendor": component.manufacturer,
        "partnumber": component.part_number or component.name})
    if settings.safety_factor:
        variable = ET.SubElement(ET.SubElement(package, q + "Variables"), q + "Variable")
        ET.SubElement(variable, q + "Name").text = SAFETY_VARIABLE
        ET.SubElement(variable, q + "Description").text = "Losses Security Factor"
    data = ET.SubElement(package, q + "SemiconductorData", type=device)
    for role in roles:
        curves = collect(component, role)
        if not curves:
            raise PlecsError(f"{ROLES[role]} : aucune courbe d'au moins 2 points")
        _loss_element(data, role, curves, settings, warnings)
    for missing in ("turn_on", "turn_off", "conduction"):
        if missing not in roles and not (device == "Diode" and missing == "turn_on"):
            warnings.append(f"pas de graphique « {ROLES[missing]} »")

    thermal = ET.SubElement(package, q + "ThermalModel")
    branch = ET.SubElement(thermal, q + "Branch", type="Foster")
    rows = foster_elements(settings.foster)
    for r, tau in rows:
        ET.SubElement(branch, q + "RTauElement", R=lut.format_number(r),
                      Tau=lut.format_number(tau))
    if not rows:
        warnings.append("modèle thermique vide : à compléter (lignes « R tau »)")
    comment = ET.SubElement(package, q + "Comment")
    lines = (component.notes or "").splitlines() or [""]
    for line in lines:
        ET.SubElement(comment, q + "Line").text = line

    # éléments sans préfixe : sous-éléments créés sans espace de noms -> on le leur donne
    for element in root.iter():
        if not element.tag.startswith("{"):
            element.tag = q + element.tag
    ET.indent(root, space="    ")
    text = ET.tostring(root, encoding="unicode", xml_declaration=False)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + text + "\n", warnings


# ================================================================ relecture
def read_tables(text: str) -> dict:
    """
    Relecture d'un fichier PLECS (tests, vérification) :
    {élément: {"current": [...], "voltage": [...], "temperature": [...], "scale": s,
               "values": tableau [T][V][i] (conduction : [T][i])}}.
    """
    root = ET.fromstring(text.encode("utf-8"))
    q = f"{{{NAMESPACE}}}"

    def floats(node):
        return [float(v) for v in node.text.split()] if node is not None and node.text else []

    out = {"class": root.find(q + "Package").get("class")}
    for element, values_tag, _, _ in ELEMENTS.values():
        node = root.find(f"{q}Package/{q}SemiconductorData/{q}{element}")
        if node is None:
            continue
        table = node.find(q + values_tag)
        if values_tag == "VoltageDrop":
            values = [floats(t) for t in table.findall(q + "Temperature")]
        else:
            values = [[floats(v) for v in t.findall(q + "Voltage")]
                      for t in table.findall(q + "Temperature")]
        out[element] = {"method": node.find(q + "ComputationMethod").text,
                        "formula": node.find(q + "Formula").text,
                        "current": floats(node.find(q + "CurrentAxis")),
                        "voltage": floats(node.find(q + "VoltageAxis")),
                        "temperature": floats(node.find(q + "TemperatureAxis")),
                        "scale": float(table.get("scale")), "values": np.array(values)}
    out["foster"] = [(float(e.get("R")), float(e.get("Tau")))
                     for e in root.iter(q + "RTauElement")]
    return out
