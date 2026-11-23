# model/datasheet.py
"""
Sens d'une datasheet : règles sur le texte lu par model.pdfimport (ni PDF, ni Qt).

    identify      référence, fabricant, catégorie, description (première page)
    axis          titre d'axe -> grandeur (symbole), unité, description
    fix_symbols   lettres dessinées perdues (« _j = 25 °C » -> « T_j = 25 °C »)
    parameter     « parameter: VGS » ; curve_condition « 8 V » -> « VGS = 8 V »
    expand_range  « VGS = 6~18V, 2V step » -> 6, 8, ... 18 V ; assign_range
    classify      type de caractéristique (sortie, énergies, Zth...) ; energy_kind
    diode_graph   graphique de la diode d'un module IGBT ; plecs_role

Règles explicites (vocabulaire normé des datasheets), testées sur des extraits de
datasheets de plusieurs fabricants. Le texte garde les marques de pdfimport : « _ »
devant un indice, « ^ » devant un exposant.
"""
import re
from dataclasses import dataclass

import numpy as np
from formules import units

# ================================================================ identité
# nom affiché -> mots cherchés (texte de la première page, URL, nom du fichier)
MANUFACTURERS = {
    "Infineon": ("infineon",), "STMicroelectronics": ("stmicroelectronics", "www.st.com"),
    "ROHM": ("rohm",), "onsemi": ("onsemi", "on semiconductor"),
    "Wolfspeed": ("wolfspeed", "cree"), "Mitsubishi Electric": ("mitsubishi",),
    "Fuji Electric": ("fuji electric", "fujielectric"), "SEMIKRON": ("semikron",),
    "Vishay": ("vishay",), "Littelfuse": ("littelfuse", "ixys"), "Nexperia": ("nexperia",),
    "Toshiba": ("toshiba",), "Microchip": ("microchip", "microsemi"),
    "Texas Instruments": ("texas instruments",), "Hitachi": ("hitachi",),
    "Danfoss": ("danfoss",), "Navitas": ("navitas",), "GaN Systems": ("gan systems",),
    "Qorvo": ("qorvo", "unitedsic"), "Renesas": ("renesas",), "Diodes": ("diodes incorporated",),
}
# catégorie -> mot du titre ; ordre de priorité (« diode » est partout : diode intrinsèque)
CATEGORY_WORDS = (("IGBT", r"\bIGBT"), ("MOSFET", r"\bMOSFET"), ("JFET", r"\bJFET"),
                  ("Thyristor", r"\b(thyristor|SCR)\b"), ("Diode", r"\bdiode"))
PART = re.compile(r"\b[A-Z0-9][A-Z0-9\-]{4,}[A-Z0-9]\b")


@dataclass
class Identity:
    part_number: str = ""
    manufacturer: str = ""
    category: str = ""
    description: str = ""


def identify(lines, filename: str = "") -> Identity:
    """
    lines : [(texte, taille)] de la première page. Référence : mot de lettres et de
    chiffres le plus grand (bonus s'il figure dans le nom du fichier) ; fabricant : liste
    connue (texte, puis nom du fichier) ; catégorie : mots du titre, par priorité.
    """
    stem = re.sub(r"[^a-z0-9]", "", filename.lower())
    best, best_score = "", -1.0
    for text, size in lines:
        for token in PART.findall(plain(text)):
            letters = sum(ch.isalpha() for ch in token)
            digits = sum(ch.isdigit() for ch in token)
            if letters < 2 or digits < 2:
                continue
            score = size + (8 if token.lower().replace("-", "") in stem else 0)
            if score > best_score:
                best, best_score = token, score
    every = " ".join(t for t, _ in lines).lower()
    manufacturer = ""
    for where in (every, filename.lower()):
        found = [(m.start(), name) for name, aliases in MANUFACTURERS.items() for a in aliases
                 for m in [re.search(r"(?<![a-z])" + re.escape(a) + r"(?![a-z])", where)] if m]
        if found:
            manufacturer = min(found)[1]
            break
    big = max((s for _, s in lines), default=0)
    title = [t for t, s in lines if s >= 0.6 * big]
    category, description = "", ""
    for texts in (title, [t for t, _ in lines]):
        for name, pattern in CATEGORY_WORDS:
            hit = next((t for t in texts if re.search(pattern, plain(t), re.I)), None)
            if hit:
                category, description = name, plain(hit)
                break
        if category:
            break
    return Identity(best, manufacturer, category, description)


# ================================================================ texte et unités
def plain(text: str) -> str:
    """Marques d'indice (_) et d'exposant (^) retirées, espaces simples."""
    return re.sub(r"\s+", " ", (text or "").replace("_", "").replace("^", "")).strip()


def clean(text: str) -> str:
    """Caractères perdus courants : « ¤C » -> « °C », « ¤s » -> « µs », « º » -> « ° »."""
    text = (text or "").replace("º", "°").replace("℃", "°C")
    text = re.sub(r"¤\s*C\b", "°C", text)
    text = re.sub(r"(?<=\d)\s*\^?o\s*C\b", "°C", text)            # « 25oC » : o en exposant
    text = re.sub(r"(?<=[\d\s])¤(?=[smAVFJ]\b)", "µ", text)
    return text


# grandeur (formules.units.quantity) -> lettre du symbole
LETTERS = {"température": "T", "tension": "V", "courant": "I", "résistance électrique": "R",
           "temps": "t", "énergie": "E", "puissance": "P", "capacité": "C", "charge": "Q",
           "résistance thermique": "Z", "fréquence": "f"}
SYMBOLS = {letter: name for name, letter in LETTERS.items()}      # « E » -> « énergie »
PREFIX = "pnuµmkMG"


def dimension(unit: str) -> str:
    """Nom de la grandeur d'une unité (« courant », « énergie »...), « » si inconnue."""
    unit = (unit or "").strip()
    for candidate in (unit, unit[1:] if len(unit) > 1 and unit[0] in PREFIX else None):
        if not candidate:
            continue
        try:
            return units.quantity(units.parse_unit(candidate).dims)
        except (units.UnitError, KeyError, ValueError):
            continue
    return ""


NORMALIZED = re.compile(r"^(p\.?\s*u\.?|norm(\.|alized|alisée?)?.*|a\.?\s*u\.?|-|1)$", re.I)


def axis(name: str, unit: str) -> tuple:
    """
    Titre d'axe découpé (nom, unité) -> (grandeur, unité, description). Grandeur : le
    symbole (« I_D » de « I_D, Drain Current » ou de « Drain Current : I_D ») ; unité
    normalisée (« ºC » -> « °C », « P.U. » -> « », la description dit « normalisée »).
    """
    name, unit = clean(name).strip(), clean(unit).strip()
    description = []
    if NORMALIZED.match(unit) or unit.lower().startswith("normalized"):
        description.append("normalisée")
        unit = ""
    unit = {"mohm": "mΩ", "ohm": "Ω", "Ohm": "Ω", "kohm": "kΩ"}.get(unit, unit)
    parts = [p.strip() for p in re.split(r"\s*[,:]\s+|\s+:\s*", name) if p.strip()]

    def symbolic(p):
        return (" " not in p and len(p) <= 16 and re.match(r"^[A-Za-zΔτη]", p) is not None
                and not re.fullmatch(r"[A-Z]?[a-z]{3,}", p))     # pas un mot (« Current »)
    symbols = [p for p in parts if symbolic(p)]
    symbols.sort(key=lambda p: ("_" not in p, len(p)))
    quantity = symbols[0] if symbols else (parts[0] if parts else "")
    description += [p for p in parts if p != quantity]
    return quantity, unit, ", ".join(description)


VALUE = r"([−-]?\d+(?:[.,]\d+)?)"


def fix_symbols(text: str, known=()) -> str:
    """
    Lettre d'un symbole dessinée (italique en tracé, non lue) : « _j = 25 °C » -> « T_j »,
    « f( _DS) » -> « f(V_DS) » si un axe s'appelle V_DS (known : symboles des axes).
    """
    known = [k for k in known if "_" in k]

    def repl(m):
        sub = m.group(1)
        for k in known:
            if k.endswith("_" + sub):
                return k
        after = text[m.end():]
        unit = re.match(r"\s*=\s*" + VALUE + r"\s*([^\s,;.)]+)", after)
        if unit:
            letter = LETTERS.get(dimension(clean(unit.group(2))))
            if letter:
                return f"{letter}_{sub}"
        return m.group(0)
    return re.sub(r"(?<![A-Za-z0-9)\]])_(\w+)", repl, text or "")


# ================================================================ conditions
def parameter(text: str):
    """Symbole du paramètre des courbes : « parameter: V_GS » -> « V_GS »."""
    m = re.search(r"param(?:eter|ètre)\s*:?\s*([A-Za-z][\w(),]*)", text or "", re.I)
    return m.group(1) if m else None


BARE = re.compile(r"^" + VALUE + r"\s*([a-zA-Zµ°Ω/]*)$")
SINGLE = re.compile(r"^[A-Za-z][\w(),]*\s*=\s*" + VALUE + r"\s*[a-zA-Zµ°Ω/]*$")   # « TJ = 25 °C »


def curve_condition(label: str, param) -> str:
    """Étiquette réduite à une valeur (« 8 V ») + paramètre -> « V_GS = 8 V »."""
    label = (label or "").strip()
    if param and BARE.match(label):
        return f"{param} = {label}"
    return label


RANGE = re.compile(r"([A-Za-z][\w()]*(?:,[A-Za-z]\w*)?)\s*=\s*" + VALUE + r"\s*([^\s~∼～,]*)\s*[~∼～]\s*" + VALUE
                   + r"\s*([^\s,]*)\s*,\s*" + VALUE + r"\s*[^\s,]*\s*step", re.I)


LIST = re.compile(r"([A-Za-z][\w()]*(?:,[A-Za-z]\w*)?)\s*=\s*(" + VALUE + r"(?:\s*,\s*" + VALUE + r")+)\s*([^\s,;]+)")


def expand_range(text: str):
    """
    « V_GS = 6~18V, 2V step » -> (« V_GS », [6, 8, ... 18], « V ») ; une liste
    « VGS= 12, 14, 16, 18 V » aussi ; sinon None.
    """
    m = RANGE.search(text or "")
    if not m:
        m = LIST.search(text or "")
        if not m or not dimension(clean(m.group(m.lastindex))):
            return None
        values = [float(v.replace("−", "-").replace(",", "."))
                  for v in re.findall(VALUE, m.group(2))]
        return m.group(1), sorted(values), m.group(m.lastindex)
    symbol, a, unit_a, b, unit_b, step = m.groups()
    a, b, step = (float(v.replace("−", "-").replace(",", ".")) for v in (a, b, step))
    if step <= 0 or b < a:
        return None
    count = int(round((b - a) / step)) + 1
    if count > 50 or abs(a + (count - 1) * step - b) > 1e-6 * max(abs(b), 1):
        return None
    return symbol, [a + k * step for k in range(count)], unit_b or unit_a


def assign_range(magnitudes, values) -> list:
    """
    Valeurs d'une plage pour des courbes rangées par amplitude moyenne |y| croissante (le
    paramètre croît avec le courant : sortie, 3e quadrant). Rend la valeur de chaque
    courbe, dans l'ordre donné ; None si les nombres ne correspondent pas.
    """
    if len(magnitudes) != len(values):
        return None
    order = np.argsort(magnitudes)
    out = [None] * len(values)
    for rank, index in enumerate(order):
        out[int(index)] = values[rank]
    return out


def format_value(value: float, unit: str) -> str:
    text = f"{value:g}".replace("-", "−")
    return f"{text} {unit}".strip()


FUNCTION = re.compile(r"([A-Za-z][\w(),]*?)\s*=\s*f\s*\(\s*([A-Za-z][\w(),]*?)\s*[,)]")


def function_axes(text: str):
    """« (I_SD = f(V_SD), T_vj = 25 °C) » -> (« I_SD », « V_SD ») : grandeurs Y et X ; None."""
    m = FUNCTION.search(plain(text or ""))
    return (m.group(1), m.group(2)) if m else None


# ================================================================ caractéristiques
KINDS = {
    "output": "Caractéristique de sortie",
    "conduction": "Chute de tension v(i)",
    "diode": "Caractéristique de la diode",
    "transfer": "Caractéristique de transfert",
    "energy": "Énergies de commutation",
    "energy_other": "Énergies (autre variable)",
    "zth": "Impédance thermique",
    "capacitance": "Capacités",
    "charge": "Charges",
    "resistance": "Résistance à l'état passant",
    "soa": "Aire de sécurité",
    "other": "Autre",
}
DIODE_WORDS = re.compile(r"diode|reverse(?! bias)|3rd|third|quadrant|freewheel|recovery|"
                         r"Durchlass|Sperrverz", re.I)
DIODE_SYMBOLS = re.compile(r"^(I_?F|V_?F|V_?SD|I_?SD|I_?S|V_?EC|E_?r(ec|r)|Q_?rr|I_?rr)\b", re.I)
GATE = re.compile(r"_?(GS|GE)\b", re.I)


def classify(x_quantity, x_unit, y_quantity, y_unit, caption: str) -> str:
    """Type de caractéristique d'après les grandeurs des axes et la légende."""
    xq, yq = x_quantity or "", y_quantity or ""
    # sans unité (graphique en image : axes lus dans « Y = f(X) ») : lettre du symbole
    dx = dimension(x_unit) or (SYMBOLS.get(xq[:1], "") if not x_unit else "")
    dy = dimension(y_unit) or (SYMBOLS.get(yq[:1], "") if not y_unit else "")
    cap = plain(caption).lower()
    if re.search(r"safe operat|\bsoa\b|\brbsoa\b|arbeitsbereich", cap):
        return "soa"
    if dy == "résistance thermique" or "thermal impedance" in cap or yq.lower().startswith("z"):
        return "zth"
    if dy == "capacité" or (not dy and re.match(r"^C", yq) and y_unit.endswith("F")):
        return "capacitance"
    if dy == "énergie":
        return "energy" if dx == "courant" else "energy_other"
    if "charge" in (dx, dy):
        return "charge"
    if dy == "résistance électrique":
        return "resistance"
    if dx == "tension" and dy == "courant":
        if GATE.search(xq) or "transfer" in cap or "übertragung" in cap:
            return "transfer"
        if DIODE_WORDS.search(cap) or DIODE_SYMBOLS.match(plain(xq)) or DIODE_SYMBOLS.match(plain(yq)):
            return "diode"
        return "output"
    if dx == "courant" and dy == "tension":
        if DIODE_WORDS.search(cap) or DIODE_SYMBOLS.match(plain(yq)):
            return "diode"
        return "conduction"
    return "other"


ENERGY = re.compile(r"\bE\s*_?\s*(on|off|rr|rec|ts|tot|sw)\b", re.I)


def energy_kind(text: str):
    """« E_on, T_vj = 125 °C » -> « on » ; « Erec » -> « rec » ; None."""
    m = ENERGY.search(text or "")
    return m.group(1).lower() if m else None


def diode_graph(caption: str, x_quantity: str, y_quantity: str, labels=()) -> bool:
    """Graphique de la diode d'un module (IGBT + diode) : légende ou grandeurs de diode."""
    cap = plain(caption)
    if re.search(r"\bdiode", cap, re.I) and not re.search(r"\bIGBT", cap):
        return True
    if DIODE_SYMBOLS.match(plain(x_quantity)) or DIODE_SYMBOLS.match(plain(y_quantity)):
        return True
    return any(energy_kind(t) in ("rr", "rec") for t in labels)


def plecs_role(kind: str, temperatures, energy=None, diode_part=False) -> str:
    """
    Rôle PLECS proposé : conduction (sortie, v(i), diode), fermeture / ouverture
    (énergies selon le courant). Conduction seulement avec une courbe par température
    (les réseaux de courbes selon VGS ne sont pas une table PLECS).
    """
    if kind in ("output", "conduction", "diode"):
        if kind == "diode" and not diode_part:
            return ""                     # diode intrinsèque d'un MOSFET : pas de rôle
        if kind != "diode" and diode_part:
            return ""
        known = [t for t in temperatures if t is not None]
        if known and len(known) == len(temperatures) and len(set(known)) == len(known):
            return "conduction"
        return ""
    if kind == "energy":
        if energy == "on" and not diode_part:
            return "turn_on"
        if energy == "off" and not diode_part:
            return "turn_off"
        if energy in ("rr", "rec") and diode_part:
            return "turn_off"
    return ""
