# model/labelread.py
"""
Lecture des petits textes d'un graphique en image (légendes, étiquettes de courbes), sans
moteur d'OCR : chaque caractère est comparé aux caractères dessinés avec les polices du
système (comme les graduations, `plotimage`), puis le mot est confronté à un vocabulaire
attendu (noms usuels, « nombre + unité », « symbole = valeur ») : la lecture retenue est
le mot du vocabulaire le plus ressemblant, ce qui corrige les caractères mal lus. Un mot
hors vocabulaire n'est proposé que s'il est lu nettement.

    reader = Reader(gray)                 # image en gris (0..255)
    word = reader.read(box, symbols)      # box : (x0, y0, x1, y1) ; symbols : du graphique
    word.text, word.cost                  # « VGS=15V », écart moyen aux modèles
"""
import functools
import itertools
from dataclasses import dataclass

import numpy as np

from . import plotimage

# caractères comparés aux modèles ; « . », « - », « = », « ° » : par leur forme
CHARS = ("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz()/,µΩ")
UNITS = ("V", "A", "mA", "°C", "Ω", "mΩ", "W", "ns", "µs", "µJ", "mJ", "nC", "µC", "pF",
         "nF", "K/W", "A/µs", "kHz", "%")
NAMES = ("Eon", "Eoff", "Etot", "Erec", "Err", "Ets", "Esw", "Ciss", "Coss", "Crss", "Cies",
         "Coes", "Cres", "td(on)", "td(off)", "tr", "tf", "trr", "Qrr", "Irrm", "Irr", "Qg",
         "Rth(j-c,max)", "Rth(j-c,typ)", "max", "typ", "min", "Single Pulse", "IGBT",
         "Diode", "MOSFET")
SYMBOLS = ("VGS", "VGE", "VDS", "VCE", "VDD", "VCC", "IDS", "ID", "IC", "IF", "ISD", "Tj",
           "Tvj", "Tc", "TC", "RG", "D")
ACCEPT = 0.26           # écart moyen maximal d'une lecture retenue (vocabulaire)
FREE = 0.14             # écart moyen maximal d'un mot hors vocabulaire


@dataclass
class Word:
    text: str                             # lecture (indices non marqués : « VGS=15V »)
    cost: float                           # écart moyen aux modèles des caractères
    box: tuple                            # (x0, y0, x1, y1), pixels
    known: bool = False                   # mot du vocabulaire


@dataclass
class _Glyph:
    shape: str                            # « tall » (comparé), ou « . », « - », « = », « ° », « ? »
    ink: np.ndarray | None = None
    ratio: float = 0.0                    # largeur / hauteur
    height: float = 0.0                   # hauteur / hauteur des capitales du mot
    sub: bool = False                     # indice
    raw: np.ndarray | None = None         # encre d'origine (découpe d'un caractère double)
    cap: float = 0.0                      # hauteur des capitales du mot, pixels


@functools.lru_cache(maxsize=None)
def _templates(path: str):
    """CHARS d'une police : (noms, encres GLYPH, largeur / hauteur, hauteur / capitales)."""
    from PIL import Image, ImageDraw, ImageFont
    try:
        font = ImageFont.truetype(path, 100)
    except OSError:
        return None
    names, inks, ratios, heights = [], [], [], []
    cap = None
    for c in "H" + CHARS:
        im = Image.new("L", (260, 260), 255)
        ImageDraw.Draw(im).text((60, 40), c, font=font, fill=0)
        ink = 1 - np.asarray(im, float) / 255
        cropped = plotimage._crop(ink)
        if cropped is None:
            continue
        if cap is None:
            cap = cropped.shape[0]
            continue
        names.append(c)
        inks.append(plotimage._resized(cropped))
        ratios.append(cropped.shape[1] / cropped.shape[0])
        heights.append(cropped.shape[0] / cap)
    return names, np.array(inks), np.array(ratios), np.array(heights)


def fonts() -> list:
    try:
        return [f for f in (_templates(p) for p in plotimage.font_paths()) if f is not None]
    except ImportError:                    # Pillow absent
        return []


@dataclass(frozen=True)
class Vocabulary:
    """Mots attendus : noms fixes, unités (« nombre unité »), symboles (« symbole = … »)."""
    names: tuple = NAMES
    units: tuple = UNITS
    symbols: tuple = SYMBOLS


DATASHEET = Vocabulary()


class Reader:
    """
    Lecture des mots d'une image ; police choisie une fois (la plus ressemblante).
    Texte clair sur fond sombre (écran d'oscilloscope) : donner l'image inversée.
    `vocabulary` : mots attendus (par défaut ceux d'une datasheet).
    """

    def __init__(self, gray: np.ndarray, vocabulary: Vocabulary = DATASHEET, fonts_=None):
        self.gray = np.asarray(gray, dtype=float)
        self.fonts = fonts() if fonts_ is None else fonts_
        self.font = None
        self.vocabulary = vocabulary

    # ------------------------------------------------------------ caractères
    def glyphs(self, box) -> list:
        """
        Caractères d'un mot, de gauche à droite : composantes connexes d'encre ; le point
        d'un « i » ou d'un « j » et les deux barres d'un « = » rattachés (mêmes colonnes).
        """
        from scipy import ndimage
        x0, y0, x1, y1 = (int(v) for v in box)
        sub = self.gray[max(y0, 0):max(y1, 0), max(x0, 0):max(x1, 0)]
        if not sub.size:
            return []
        dark = sub.min()
        ink = np.clip((0.5 * (dark + 255) + 40 - sub) / 80, 0, 1)
        labels, n = ndimage.label(ink > plotimage.GLYPH_INK, structure=np.ones((3, 3)))
        if not n:
            return []
        boxes = [[sl[1].start, sl[0].start, sl[1].stop - 1, sl[0].stop - 1, {i + 1}]
                 for i, sl in enumerate(ndimage.find_objects(labels))]
        cap = max(b[3] - b[1] + 1 for b in boxes)
        small = [b for b in boxes if b[3] - b[1] + 1 < 0.45 * cap]
        merged = [b for b in boxes if b not in small]
        for b in small:                    # point de i / j, seconde barre de « = »
            host = None
            for m in merged:
                overlap = min(b[2], m[2]) - max(b[0], m[0]) + 1
                if overlap >= 0.6 * min(b[2] - b[0] + 1, m[2] - m[0] + 1) and (
                        m in small or m[3] - m[1] + 1 >= 0.45 * cap and b[3] < m[1]):
                    host = m
                    break
            if host is None:
                merged.append(b)
                continue
            host[0], host[1] = min(host[0], b[0]), min(host[1], b[1])
            host[2], host[3] = max(host[2], b[2]), max(host[3], b[3])
            host[4] |= b[4]
        merged.sort(key=lambda b: b[0])
        tall = [b for b in merged if b[3] - b[1] + 1 >= 0.75 * cap]
        base = float(np.median([b[3] for b in tall])) if tall else float(max(b[3] for b in merged))
        top_line = float(np.median([b[1] for b in tall])) if tall else 0.0
        out = []
        for bx0, by0, bx1, by1, ids in merged:
            g = np.where(np.isin(labels[by0:by1 + 1, bx0:bx1 + 1], list(ids)),
                         ink[by0:by1 + 1, bx0:bx1 + 1], 0.0)
            h, w = by1 - by0 + 1, bx1 - bx0 + 1
            mid = (by0 + by1) / 2
            if h < 0.45 * cap:
                if len(ids) >= 2:
                    out.append(_Glyph("="))
                elif mid < top_line + 0.35 * cap and w <= 1.6 * h + 1:
                    out.append(_Glyph("°"))
                elif mid > base - 0.2 * cap and w <= 1.6 * h + 1:
                    out.append(_Glyph("."))
                elif w > 1.3 * h:
                    out.append(_Glyph("-"))
                else:
                    out.append(_Glyph("?"))
                continue
            if w > 1.6 * cap:              # trait de rappel, échantillon de légende
                out.append(_Glyph("?"))
                continue
            rows = plotimage._runs(g.max(axis=1) > plotimage.GLYPH_INK, gap=0)
            if h < 0.75 * cap and len(rows) >= 2 and w >= 0.8 * h:
                out.append(_Glyph("="))    # deux barres jointes par l'anticrénelage
                continue
            is_sub = h < 0.85 * cap and by1 > base + 0.12 * cap
            out.append(_Glyph("tall", plotimage._resized(g), w / h, h / cap, is_sub, g, cap))
        return out

    def _costs(self, glyphs, font) -> np.ndarray:
        """
        Écart de chaque caractère « tall » à chaque caractère de la police ; une police
        relevée sur des captures a plusieurs modèles par caractère : le plus proche compte.
        """
        names, inks, ratios, heights = font
        unique, inverse = _groups(names)
        rows = []
        for g in glyphs:
            if g.shape != "tall":
                rows.append(None)
                continue
            cost = (np.abs(inks - g.ink).mean(axis=1) + 0.3 * np.abs(ratios - g.ratio))
            if not g.sub:                  # hauteur relative : « o » / « O », « 0 »
                cost = cost + 0.4 * np.abs(heights - g.height)
            if len(unique) != len(names):
                best = np.full(len(unique), np.inf)
                np.minimum.at(best, inverse, cost)
                cost = best
            rows.append(cost)
        return rows

    # ------------------------------------------------------------ mots
    def read(self, box, symbols=()) -> Word | None:
        """Lecture d'un mot : vocabulaire d'abord, sinon lecture libre si nette ; None."""
        glyphs = self.glyphs(box)
        if not glyphs or not self.fonts:
            return None
        candidates = self.fonts if self.font is None else [self.font]
        best = None
        for font in candidates:
            for variant in [glyphs] + _split_variants(glyphs):
                costs = self._costs(variant, font)
                found = _decode(variant, costs, _groups(font[0])[0], tuple(symbols),
                                self.vocabulary)
                if found and (best is None or (found[2], -found[1]) > (best[2], -best[1])):
                    best = (found[0], found[1], found[2], font)
                if best is not None and best[2] and best[1] <= ACCEPT:
                    break                  # lu sans découper : les découpes ne servent pas
        if best is None:
            return None
        text, cost, known, font = best
        if self.font is None and known:
            self.font = font               # police retenue pour les mots suivants
        if cost > (ACCEPT if known else FREE):
            return None
        return Word(text, cost, tuple(box), known)


def _groups(names) -> tuple:
    """(noms distincts, indice du nom distinct de chaque modèle)."""
    key = tuple(names)
    if key not in _GROUPS:
        unique = list(dict.fromkeys(names))
        position = {c: i for i, c in enumerate(unique)}
        _GROUPS[key] = (unique, np.array([position[c] for c in names]))
    return _GROUPS[key]


_GROUPS = {}


def _split_variants(glyphs) -> list:
    """
    Mots où un caractère large (« ff » collés, « rr ») est coupé en deux à sa colonne la
    plus maigre : une variante par caractère large.
    """
    out = []
    for i, g in enumerate(glyphs):
        if g.shape != "tall" or g.raw is None or g.ratio < 0.75:
            continue
        h, w = g.raw.shape
        profile = g.raw.sum(axis=0)
        lo, hi = int(0.3 * w), int(0.7 * w)
        if hi - lo < 1:
            continue
        cut = lo + int(np.argmin(profile[lo:hi]))
        parts = []
        for piece in (g.raw[:, :cut], g.raw[:, cut:]):
            if not piece.size:                 # coupe au bord : pas de découpe
                break
            cropped = plotimage._crop(piece)
            if cropped is None:
                break
            ph, pw = cropped.shape
            parts.append(_Glyph("tall", plotimage._resized(cropped), pw / ph,
                                ph / max(g.cap, 1), g.sub, cropped, g.cap))
        if len(parts) == 2:
            out.append(glyphs[:i] + parts + glyphs[i + 1:])
    return out


# ================================================================ vocabulaire
def _number_patterns(n):
    """Nombres de n caractères : [-]chiffres[.chiffres] (motifs de classes)."""
    digits = set("0123456789")
    out = []
    for sign in (0, 1):
        rest = n - sign
        if rest < 1:
            continue
        shapes = [[digits] * rest]
        for k in range(1, rest - 1):       # point décimal après k chiffres
            shapes.append([digits] * k + [{"."}] + [digits] * (rest - k - 1))
        for s in shapes:
            out.append(([{"-"}] if sign else []) + s)
    return out


def _literal(text):
    """Motif d'un texte ; la virgule, trop petite pour un modèle, se lit comme un point."""
    return [{",", "."} if c == "," else {c} for c in text]


SHAPES = {".", ",", "-", "=", "°"}          # signes lus par leur forme, pas par un modèle


def _signature(pattern) -> tuple:
    """Forme d'un motif : None (caractère comparé) ou le signe attendu, position par position."""
    return tuple(None if not allowed <= SHAPES else ("." if "." in allowed else next(iter(allowed)))
                 for allowed in pattern)


@functools.lru_cache(maxsize=128)
def _patterns(n, symbols, vocabulary=DATASHEET) -> dict:
    """
    Motifs de n caractères (noms, « nombre unité », « symbole = nombre unité »), rangés par
    signature : seuls ceux de même forme que le mot lu sont comparés.
    """
    out = [_literal(name.replace(" ", "")) for name in vocabulary.names
           if len(name.replace(" ", "")) == n]
    syms = list(dict.fromkeys(list(symbols) + list(vocabulary.symbols)))
    for unit in vocabulary.units:
        for prefix in [""] + [s + "=" for s in syms if _unit_fits(s, unit)]:
            k = n - len(prefix) - len(unit)
            if 1 <= k <= 7:
                for num in _number_patterns(k):
                    out.append(_literal(prefix) + num + _literal(unit))
    for s in syms:
        if len(s) == n:
            out.append(_literal(s))
    index = {}
    for pattern in out:
        index.setdefault(_signature(pattern), []).append(pattern)
    return index


LETTER_UNITS = {"V": ("V",), "I": ("A", "mA"), "T": ("°C",), "R": ("Ω", "mΩ"), "P": ("W",),
                "E": ("µJ", "mJ"), "t": ("ns", "µs"), "Q": ("nC", "µC"), "C": ("pF", "nF")}


def _unit_fits(symbol, unit) -> bool:
    """« VGS=15W » n'est pas une lecture possible : l'unité suit la lettre du symbole."""
    allowed = LETTER_UNITS.get(symbol[:1])
    return allowed is None or unit in allowed


def _junk(glyphs) -> list:
    """
    Positions des signes qui peuvent être des débris : bouts du mot, « ? », « . », et les
    morceaux bas et larges (trait de rappel passant sous le texte).
    """
    n = len(glyphs)
    return sorted({0, n - 1} | {i for i, g in enumerate(glyphs) if g.shape in ("?", ".")
                                or (g.shape == "tall" and g.sub and g.ratio > 1.2)})


def _decode(glyphs, costs, names, symbols, vocabulary=DATASHEET):
    """
    Meilleure lecture : (texte, écart moyen, du vocabulaire) ; libre si rien ne colle.
    Jusqu'à deux signes parasites (bout de trait de rappel, d'échantillon de légende :
    en bout de mot, ou « ? » / « . » au milieu) peuvent être ignorés, avec une pénalité.
    """
    best = None
    n = len(glyphs)
    junk = _junk(glyphs)
    for drop in [()] + [(i,) for i in junk] + list(itertools.combinations(junk, 2)):
        if n - len(drop) < 1:
            continue
        keep = [i for i in range(n) if i not in drop]
        found = _decode_exact([glyphs[i] for i in keep], [costs[i] for i in keep],
                              names, symbols, vocabulary)
        if found is not None and found[2]:
            score = found[1] + 0.01 * len(drop)
            if best is None or score < best[1]:
                best = (found[0], score, True)
    if best is not None:
        return best
    return _decode_exact(glyphs, costs, names, symbols, vocabulary)


def _decode_exact(glyphs, costs, names, symbols, vocabulary=DATASHEET):
    n = len(glyphs)
    if not n:
        return None
    index = {c: i for i, c in enumerate(names)}
    signature = tuple(None if g.shape == "tall" else g.shape for g in glyphs)
    tall = max(sum(g.shape == "tall" for g in glyphs), 1)
    best = None
    for pattern in _patterns(n, symbols, vocabulary).get(signature, []):
        total, text, ok = 0.0, "", True
        for g, row, allowed in zip(glyphs, costs, pattern):
            if g.shape != "tall":
                text += "," if allowed == {",", "."} else g.shape
                continue
            options = [(row[index[c]], c) for c in allowed if c in index]
            if not options:
                ok = False
                break
            c_cost, c = min(options)
            total += c_cost
            text += c
        if ok and (best is None or total / tall < best[1]):
            best = (text, total / tall, True)
    if best is not None:
        return best
    # lecture libre : meilleur modèle de chaque caractère
    text, total, count = "", 0.0, 0
    for g, row in zip(glyphs, costs):
        if g.shape != "tall":
            text += g.shape
            continue
        k = int(np.argmin(row))
        text += names[k]
        total += float(row[k])
        count += 1
    return (text, total / max(count, 1), False) if count else None
