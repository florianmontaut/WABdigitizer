# model/pdfimport.py
"""
Import d'une datasheet PDF vectorielle : graphiques, calibration et courbes lus dans les
tracés et le texte du PDF (pas dans une image), puis convertis en composant brouillon.

    found = analyse("datasheet.pdf")            # graphiques trouvés (coordonnées PDF)
    component, warnings = to_component("datasheet.pdf", found)

Étapes, page par page :
    1. page aplatie (pdfminer.six) : caractères, tracés, images ; glyphes dessinés (−, Ω)
       remis en texte
    2. cadres : traits horizontaux et verticaux qui se croisent (cadre + grille)
    3. graduations : nombres sous le cadre et à sa gauche (exposants 10^n recollés),
       ajustement linéaire ou log par moindres carrés sur toutes les graduations
    4. titres d'axes (nom et unité), courbes (sommets exacts, morceaux et tirets recollés),
       étiquettes (légende par le style du trait, sinon texte le plus proche)
    5. légende de la figure (« Figure 7. ... », « Diagram 5: ... ») et conditions
Conversion (pypdfium2) : diagramme rendu en image, recadré ; calibration orthonormée sur
les graduations extrêmes ; points en pixels de cette image (repère unique de l'application).

Graphique incorporé en image (Excel collé...) : repéré par une grande image légendée,
cadre, grille et graduations trouvés dans l'image (`plotimage` : valeurs lues par
comparaison aux chiffres des polices du système, suite régulière exigée) ; calibré sur
les valeurs lues, que l'utilisateur vérifie ou remplace (`Draft.calibrate`) ; courbes
relevées automatiquement (`curvetrace` : suivi colonne par colonne), à vérifier.

Ce qui n'est pas lu est signalé (avertissements) : l'import propose, l'utilisateur vérifie.
Dépendances facultatives : pdfminer.six (MIT), pypdfium2 (Apache / BSD).
"""
import importlib.util
import pathlib
import re
from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from . import curvetrace, datasheet, plotimage
from .calibration import AxisCalibration, CalibrationError, to_four_points
from .document import PALETTE, Axis, Component, Dataset, Graph


class PdfImportError(ValueError):
    """PDF illisible, ou paquets manquants."""


def available() -> bool:
    """pdfminer.six et pypdfium2 installés."""
    return all(importlib.util.find_spec(name) is not None for name in ("pdfminer", "pypdfium2"))


# ================================================================ primitives
# glyphes dessinés (blocs de dessin nommés d'après la police : « F1-DejaVuSans-minus »)
GLYPHS = {"minus": "−", "Omega": "Ω", "mu": "µ", "degree": "°", "plusminus": "±",
          "multiply": "×", "periodcentered": "·", "Delta": "Δ", "theta": "θ"}
# police Symbol en zone privée (U+F0xx)
SYMBOL = {0xB0: "°", 0x6D: "µ", 0x57: "Ω", 0x2D: "−", 0xB1: "±", 0x44: "Δ", 0x71: "θ",
          0x74: "τ", 0xA3: "≤", 0xB3: "≥", 0xB4: "×", 0x77: "ω", 0x61: "α", 0x62: "β"}
UNKNOWN = "¤"                             # caractère sans correspondance Unicode
CAPTION = re.compile(r"^(Fig(ure)?\.?\s*\d+|Diagram\s*\d+|Abb(ildung)?\.?\s*\d+)", re.I)
REFCODE = re.compile(r"^[A-Z0-9_]{12,}$")     # code de dessin (« GPDP0507202413... »)
NUMBER = re.compile(r"^-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")


@dataclass
class Char:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float          # hauteur de fonte (repère de la page)
    bx: float            # origine de la ligne de base
    by: float
    upright: bool        # False : texte tourné de 90°
    bold: bool = False
    glyph: bool = False  # dessiné (pas une police)

    @property
    def cx(self):
        return (self.x0 + self.x1) / 2

    @property
    def cy(self):
        return (self.y0 + self.y1) / 2


@dataclass
class Stroke:
    pts: np.ndarray
    color: str
    width: float
    stroke: bool
    fill: bool
    dash: str = ""

    @property
    def axis_aligned(self) -> bool:
        if len(self.pts) != 2:
            return False
        d = self.pts[1] - self.pts[0]
        return abs(d[0]) < 1e-3 or abs(d[1]) < 1e-3

    @property
    def length(self) -> float:
        if len(self.pts) < 2:
            return 0.0
        return float(np.sum(np.hypot(*np.diff(self.pts, axis=0).T)))


def clean(text: str) -> str:
    if len(text) == 1 and ord(text) < 32:
        return " "                        # espace codée en caractère de contrôle (FF300R12KT4)
    if len(text) == 1 and 0xF000 <= ord(text) <= 0xF0FF:
        return SYMBOL.get(ord(text) - 0xF000, UNKNOWN)
    if text.startswith("(cid:"):
        return UNKNOWN
    return text


def color(text) -> tuple:
    """Couleur de tracé pdfminer -> (r, g, b) entre 0 et 1 (gris : un nombre ; CMJN)."""
    nums = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", str(text or ""))]
    if len(nums) == 1:
        return (nums[0],) * 3
    if len(nums) == 3:
        return tuple(nums)
    if len(nums) == 4:
        c, m, y, k = nums
        return ((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
    return (0.0, 0.0, 0.0)


def plain(text: str) -> str:
    """Texte lisible : marques d'indice (_) et d'exposant (^) retirées."""
    return re.sub(r"\s+", " ", text.replace("_", "").replace("^", "")).strip()


def flatten(page):
    """Caractères, tracés et boîtes d'images de toute une page pdfminer."""
    from pdfminer.layout import LTChar, LTCurve, LTFigure, LTImage, LTRect, LTTextContainer
    chars, strokes, images = [], [], []

    def char(c):
        a, b, cc, d, e, f = c.matrix
        upright = abs(b) <= 1e-3 * abs(a)          # un italique (cc != 0) reste horizontal
        return Char(clean(c.get_text()), c.x0, c.y0, c.x1, c.y1,
                    c.size if upright else (c.x1 - c.x0), e, f, upright, "Bold" in c.fontname)

    def rec(container):
        for o in container:
            if isinstance(o, LTChar):
                chars.append(char(o))
            elif isinstance(o, LTTextContainer):
                rec(o)
            elif isinstance(o, LTImage):
                images.append(o.bbox)
            elif isinstance(o, LTFigure):
                inner = list(o)
                name = o.name or ""
                if inner and "-" in name and all(isinstance(i, LTCurve) for i in inner):
                    gx0, gy0 = min(i.x0 for i in inner), min(i.y0 for i in inner)
                    gx1, gy1 = max(i.x1 for i in inner), max(i.y1 for i in inner)
                    if gx1 - gx0 < 15 and gy1 - gy0 < 15:       # glyphe de police dessiné
                        text = GLYPHS.get(name.rsplit("-", 1)[-1])
                        if text is None:
                            text = "−" if gy1 - gy0 < 0.3 * (gx1 - gx0) else UNKNOWN
                        chars.append(Char(text, gx0, gy0, gx1, gy1, max(gy1 - gy0, 4),
                                          gx0, gy0, True, glyph=True))
                        continue
                rec(o)                    # bloc de dessin : son contenu, à sa place
            elif isinstance(o, LTCurve):  # LTLine et LTRect en dérivent
                pts = np.array(o.pts, float)
                if isinstance(o, LTRect):
                    pts = np.vstack([pts, pts[:1]])
                dash = getattr(o, "dashing_style", None)
                strokes.append(Stroke(pts, str(o.stroking_color), float(o.linewidth or 0),
                                      bool(o.stroke), bool(o.fill),
                                      str(dash) if dash and dash[0] else ""))
    rec(page)
    real = [c for c in chars if not c.glyph]
    for g in chars:                       # glyphe : taille et ligne de base de son voisin
        if not g.glyph or not real:
            continue
        near = min(real, key=lambda c: abs(c.cy - g.cy) * 3 + min(abs(c.x0 - g.x1), abs(g.x0 - c.x1)))
        if abs(near.cy - g.cy) < near.size and min(abs(near.x0 - g.x1), abs(g.x0 - near.x1)) < near.size:
            g.size, g.by, g.upright, g.bold = near.size, near.by, near.upright, near.bold
            if not near.upright:
                g.bx = near.bx
    return chars, strokes, images


# ================================================================ texte
def lines(chars) -> list:
    """
    Lignes de texte horizontales : caractères de même ligne de base (indices et exposants
    rattachés), triés par x. Rend [(texte, [Char])] ; indices « _ », exposants « ^ ».
    """
    # 1. même ligne de base (les grands caractères d'abord : un indice rejoint sa ligne)
    bands = []
    for c in sorted((c for c in chars if c.upright), key=lambda c: -c.size):
        for band in bands:
            if abs(c.by - band[0].by) < 0.45 * band[0].size:
                band.append(c)
                break
        else:
            bands.append([c])
    # 2. coupée aux grands trous (colonnes, textes voisins), une fois triée par x
    out = []
    for band in bands:
        band.sort(key=lambda c: c.x0)
        gap = 2.0 * max(c.size for c in band)
        row = [band[0]]
        for c in band[1:]:
            if c.x0 - max(r.x1 for r in row) > gap:
                out.append((join(row), row))
                row = []
            row.append(c)
        out.append((join(row), row))
    return out


def join(row) -> str:
    main = max(c.size for c in row)
    base = next(c.by for c in row if c.size == main)
    text, prev, state = "", None, "n"
    for c in row:
        if prev is not None and c.x0 - prev.x1 > 0.22 * main:
            text += " "
        s = "n"
        if c.size < 0.85 * main:
            s = "^" if c.by > base + 0.15 * main else "_"
        if s != state and s != "n":
            text += s
        text += c.text
        state, prev = s, c
    return re.sub(r"\s+", " ", text).strip()


def rot_text(chars) -> str:
    """
    Texte tourné de 90° (titre d'axe Y), lu de bas en haut ; sur plusieurs lignes
    (colonnes, de gauche à droite), indices décalés vers la droite.
    """
    if not chars:
        return ""
    main = max(c.size for c in chars)
    columns = []                          # lignes de base des grands caractères
    for c in sorted((c for c in chars if c.size >= 0.85 * main), key=lambda c: c.bx):
        if columns and abs(c.bx - columns[-1][-1]) < 0.45 * main:
            columns[-1].append(c.bx)
        else:
            columns.append([c.bx])
    bases = [float(np.mean(col)) for col in columns]
    groups = [[] for _ in bases]
    for c in chars:
        groups[int(np.argmin([abs(c.bx - b) for b in bases]))].append(c)
    out = []
    for base, group in zip(bases, groups):
        text, prev, state = "", None, "n"
        for c in sorted(group, key=lambda c: c.y0):
            if prev is not None and c.y0 - prev.y1 > 0.22 * main:
                text += " "
            s = "n"
            if abs(c.bx - base) > 0.15 * main:
                s = "_" if c.bx > base else "^"
            if s != state and s != "n":
                text += s
            text += c.text
            state, prev = s, c
        out.append(text)
    return re.sub(r"\s+", " ", " ".join(out)).strip()


def words(chars) -> list:
    """Mots horizontaux, sans rattacher les exposants : pour les graduations."""
    out = []
    for c in sorted((c for c in chars if c.upright), key=lambda c: (round(-c.by, 1), c.x0)):
        for w in out:
            last = w[-1]
            if abs(c.by - last.by) < 0.15 * last.size \
                    and -0.3 * last.size < c.x0 - last.x1 < 0.3 * last.size \
                    and abs(c.size - last.size) < 0.1 * last.size:
                w.append(c)
                break
        else:
            out.append([c])
    return out


def number(text: str):
    text = text.replace("−", "-").replace(",", ".").replace(" ", "")
    return float(text) if NUMBER.match(text) else None


def tick_labels(chars) -> list:
    """Nombres isolés ; « 10 » suivi d'un petit nombre surélevé : 10^n."""
    ws = words(chars)
    exponents = {}
    for i, w in enumerate(ws):
        if "".join(c.text for c in w).replace(" ", "") not in ("10", "1×10", "1·10"):
            continue
        for j, e in enumerate(ws):
            if j != i and j not in exponents.values() and e[0].size < 0.85 * w[0].size \
                    and -0.1 * w[0].size <= e[0].x0 - w[-1].x1 < 0.5 * w[0].size \
                    and e[0].by > w[0].by + 0.15 * w[0].size \
                    and number("".join(c.text for c in e)) is not None:
                exponents[i] = j
                break
    items = []
    for i, w in enumerate(ws):
        if i in exponents.values():
            continue
        text = "".join(c.text for c in w).replace(" ", "")
        x0, x1 = w[0].x0, w[-1].x1
        y0, y1 = min(c.y0 for c in w), max(c.y1 for c in w)
        if i in exponents:
            e = ws[exponents[i]]
            exp = number("".join(c.text for c in e))
            value, text = 10.0 ** exp, f"10^{exp:g}"
            x1, y1 = e[-1].x1, max(y1, max(c.y1 for c in e))
            w = w + e
        else:
            value = number(text)
        if value is not None:
            items.append(dict(text=text, value=value, x0=x0, x1=x1, y0=y0, y1=y1,
                              cx=(x0 + x1) / 2, cy=(y0 + y1) / 2, size=w[0].size, chars=w))
    return items


def unit_split(title: str) -> tuple:
    """« V_DS [V] », « I_D (A) », « E / mJ » -> (nom, unité)."""
    m = re.match(r"^(.*?)\s*\[([^\]]*)\]\s*$", title)        # « V_DS [V] »
    if m:
        return m.group(1).strip(), m.group(2).strip()
    m = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", title)         # « Z_thJC (°C/W) »
    if m and not m.group(1).endswith(("(", "_")):
        return m.group(1).strip(), m.group(2).strip()
    m = re.match(r"^(.*?)\s*/\s*(\S+)$", title)               # « E / mJ »
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return title.strip(), ""


# ================================================================ géométrie
@dataclass
class AxisFit:
    """valeur (ou log10 de la valeur) = a * position + b, position en points du PDF."""
    log: bool
    a: float
    b: float
    residual: float                       # écart maximal des graduations, en points
    ticks: list = field(default_factory=list)   # [(position, valeur, texte)]
    snapped: int = 0                      # graduations posées sur un trait

    def value(self, pos):
        v = self.a * np.asarray(pos, dtype=float) + self.b
        return 10.0 ** v if self.log else v


def fit_axis(ticks):
    """Linéaire ou log, le plus petit résidu ; log seulement sur une grande étendue."""
    if len(ticks) < 2:
        return None
    pos = np.array([t[0] for t in ticks], dtype=float)
    val = np.array([t[1] for t in ticks], dtype=float)
    best = None
    for log in (False, True):
        if log and (np.any(val <= 0) or val.max() / val.min() < 20):
            continue
        y = np.log10(val) if log else val
        if np.ptp(y) == 0 or np.ptp(pos) == 0:
            continue
        a, b = np.polyfit(pos, y, 1)
        if a == 0:
            continue
        residual = float(np.max(np.abs((y - b) / a - pos)))
        if best is None or residual < best.residual:
            best = AxisFit(log, float(a), float(b), residual, list(ticks))
    return best


def find_frames(strokes, page_area=None) -> list:
    """
    Cadres de graphiques : composantes connexes de traits horizontaux et verticaux qui se
    croisent (cadre + grille + graduations), au moins 2 + 2 longs traits, boîte >= 60 pt.
    Les paliers des courbes dessinées en petits segments ne comptent pas comme grille.
    """
    oblique, straight = Counter(), Counter()
    for p in strokes:
        if len(p.pts) < 2:
            continue
        d = np.diff(p.pts, axis=0)
        ok = (np.abs(d[:, 0]) < 0.05) | (np.abs(d[:, 1]) < 0.05)
        key = (p.color, round(p.width, 2), p.dash)
        straight[key] += int(ok.sum())
        oblique[key] += int((~ok).sum())
    curve_styles = {k for k in oblique if oblique[k] > straight[k]}
    hs, vs = [], []
    for p in strokes:
        if not (p.stroke or p.fill) or len(p.pts) < 2:
            continue
        if (p.color, round(p.width, 2), p.dash) in curve_styles and p.length < 25:
            continue
        d = np.diff(p.pts, axis=0)
        if not np.all((np.abs(d[:, 0]) < 0.05) | (np.abs(d[:, 1]) < 0.05)):
            continue
        for a, b in zip(p.pts[:-1], p.pts[1:]):
            if abs(a[1] - b[1]) < 0.05 and abs(a[0] - b[0]) >= 3:
                hs.append((min(a[0], b[0]), max(a[0], b[0]), (a[1] + b[1]) / 2))
            elif abs(a[0] - b[0]) < 0.05 and abs(a[1] - b[1]) >= 3:
                vs.append((min(a[1], b[1]), max(a[1], b[1]), (a[0] + b[0]) / 2))
    n = len(hs) + len(vs)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    H = np.array(hs) if hs else np.zeros((0, 3))
    for j, (vy0, vy1, vx) in enumerate(vs):
        if not len(H):
            break
        hit = np.nonzero((H[:, 0] - 1 <= vx) & (vx <= H[:, 1] + 1) &
                         (vy0 - 1 <= H[:, 2]) & (H[:, 2] <= vy1 + 1))[0]
        for i in hit:
            a, b = find(int(i)), find(len(hs) + j)
            if a != b:
                parent[a] = b
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    frames = []
    for members in groups.values():
        hh = [hs[i] for i in members if i < len(hs)]
        vv = [vs[i - len(hs)] for i in members if i >= len(hs)]
        if len(hh) < 2 or len(vv) < 2:
            continue
        x0 = min(min(h[0] for h in hh), min(v[2] for v in vv))
        x1 = max(max(h[1] for h in hh), max(v[2] for v in vv))
        y0 = min(min(v[0] for v in vv), min(h[2] for h in hh))
        y1 = max(max(v[1] for v in vv), max(h[2] for h in hh))
        W, Hh = x1 - x0, y1 - y0
        if W < 60 or Hh < 50 or (page_area and W * Hh > 0.35 * page_area):
            continue                      # trop petit, ou cadre de page
        long_h = [h for h in hh if h[1] - h[0] > 0.6 * W]
        long_v = [v for v in vv if v[1] - v[0] > 0.6 * Hh]
        if len(long_h) < 2 or len(long_v) < 2:
            continue
        frames.append(dict(frame=(min(v[2] for v in long_v), min(h[2] for h in long_h),
                                  max(v[2] for v in long_v), max(h[2] for h in long_h)),
                           vgrid=sorted({round(v[2], 3) for v in long_v}),
                           hgrid=sorted({round(h[2], 3) for h in long_h})))

    # cadres emboîtés : un simple encadré autour d'un graphique, ou dans un graphique
    # quadrillé (légende), est écarté
    def inside(a, o):
        return o[0] - 1 <= a[0] and a[2] <= o[2] + 1 and o[1] - 1 <= a[1] and a[3] <= o[3] + 1

    def simple(f):
        return len(f["vgrid"]) <= 2 and len(f["hgrid"]) <= 2
    drop = set()
    for i, f in enumerate(frames):
        for j, o in enumerate(frames):
            if i != j and f["frame"] != o["frame"] and inside(f["frame"], o["frame"]):
                drop.add(j if simple(o) else i)
    return [f for i, f in enumerate(frames) if i not in drop]


def short_ticks(strokes, frame) -> tuple:
    """Traits courts perpendiculaires aux bords bas et gauche du cadre."""
    x0, y0, x1, y1 = frame
    size = max(x1 - x0, y1 - y0)
    xt, yt = [], []
    for p in strokes:
        if len(p.pts) == 2 and p.axis_aligned and p.length < 0.05 * size:
            (ax, ay), (bx, by) = p.pts
            if abs(ax - bx) < 1e-3 and min(abs(ay - y0), abs(by - y0)) < 1:
                xt.append(ax)
            elif abs(ay - by) < 1e-3 and min(abs(ax - x0), abs(bx - x0)) < 1:
                yt.append(ay)
    return xt, yt


def snap(pos, candidates, tol) -> tuple:
    if not candidates:
        return pos, False
    c = min(candidates, key=lambda v: abs(v - pos))
    return (c, True) if abs(c - pos) < tol else (pos, False)


def best_row(items, key, tol) -> list:
    """Rangée (ou colonne) de graduations : le groupe aligné le plus nombreux."""
    groups = []
    for item in sorted(items, key=lambda i: i[key]):
        if groups and abs(item[key] - groups[-1][-1][key]) < tol * item["size"]:
            groups[-1].append(item)
        else:
            groups.append([item])
    return max(groups, key=len) if groups else []


def margin_box(frame) -> tuple:
    """Cadre élargi : graduations, titres d'axes, étiquettes au bout des courbes."""
    x0, y0, x1, y1 = frame
    return (x0 - min(0.4 * (x1 - x0), 75), y0 - 50, x1 + 45, y1 + 30)


def rect_dist(x, y, r) -> float:
    dx = max(r[0] - x, 0, x - r[2])
    dy = max(r[1] - y, 0, y - r[3])
    return (dx * dx + dy * dy) ** 0.5


def dist_to_polyline(p, pts) -> float:
    if len(pts) == 1:
        return float(np.hypot(*(pts[0] - p)))
    a, b = pts[:-1], pts[1:]
    d = b - a
    t = np.clip(np.sum((p - a) * d, axis=1) / np.maximum(np.sum(d * d, axis=1), 1e-12), 0, 1)
    proj = a + d * t[:, None]
    return float(np.min(np.hypot(*(proj - p).T)))


def join_fragments(raw, tol=0.6, straight=False) -> list:
    """
    Morceaux d'une même courbe recollés : bouts communs (même style), puis tirets d'un
    pointillé dessiné tiret par tiret (trou court, même direction) ; le motif (tiret /
    trou) devient alors le style « dash » de la courbe.
    """
    seen, unique = set(), []
    for c in raw:                         # tracé dessiné deux fois : une seule fois
        key = (c["color"], c["width"], c["dash"], tuple(np.round(c["pts"], 1).ravel()))
        if key not in seen:
            seen.add(key)
            unique.append(c)
    curves = _join_ends([dict(c) for c in unique], tol)
    for c in curves:                      # sens de lecture : x croissant
        if c["pts"][0][0] > c["pts"][-1][0]:
            c["pts"] = c["pts"][::-1]
        c["pieces"] = [float(np.sum(np.hypot(*np.diff(c["pts"], axis=0).T)))]
        c["gaps"] = []
    # tirets : lien fin -> début le plus proche, chaque début pris une fois
    n = len(curves)
    links = []
    if n > 1:
        starts = np.array([c["pts"][0] for c in curves])
        sdir = np.array([c["pts"][min(1, len(c["pts"]) - 1)] - c["pts"][0] for c in curves])
        nb = np.hypot(sdir[:, 0], sdir[:, 1])
        for i, a in enumerate(curves):
            if len(a["pts"]) < 2:
                continue
            ea, da = a["pts"][-1], a["pts"][-1] - a["pts"][-2]
            na = np.hypot(*da)
            if na < 1e-6:
                continue
            v = starts - ea
            d = np.hypot(v[:, 0], v[:, 1])
            with np.errstate(invalid="ignore", divide="ignore"):
                ok = (d > 0.3) & (d < 6 + 3 * a["width"]) & (nb > 1e-6) \
                    & ((v @ da) / (na * d) > 0.8) & (np.sum(sdir * v, axis=1) / (nb * d) > 0.8)
            if straight:
                ok &= np.abs(v[:, 1]) < 0.1
            ok &= np.array([(c["color"], c["width"]) == (a["color"], a["width"]) for c in curves])
            ok[i] = False
            links += [(float(d[j]), i, int(j)) for j in np.nonzero(ok)[0]]
    links.sort()
    nxt, prv, gap = {}, {}, {}
    for d, i, j in links:
        if i in nxt or j in prv:
            continue
        k = j
        while k in nxt:                   # pas de boucle
            k = nxt[k]
        if k == i:
            continue
        nxt[i], prv[j], gap[i] = j, i, d
    out = []
    for i in range(n):
        if i in prv:
            continue
        c, k = curves[i], i
        while k in nxt:
            j = nxt[k]
            c["pts"] = np.vstack([c["pts"], curves[j]["pts"]])
            c["pieces"] += curves[j]["pieces"]
            c["gaps"].append(gap[k])
            k = j
        if c["gaps"] and not c["dash"]:
            c["dash"] = f"motif {np.median(c['pieces']):.1f}/{np.median(c['gaps']):.1f}"
        del c["pieces"], c["gaps"]
        out.append(c)
    return out


def drop_duplicates(curves, tol=0.4) -> tuple:
    """
    Courbes en double (tracé répété, ou morceau déjà couvert par une autre courbe) :
    une courbe dont tous les points sont à moins de tol d'une autre, plus longue ou
    égale, est écartée. Rend (courbes gardées, nombre écarté).
    """
    order = sorted(range(len(curves)), key=lambda i: -len(curves[i]["pts"]))
    kept = []
    for i in order:
        pts = curves[i]["pts"]
        if any(all(dist_to_polyline(p, curves[k]["pts"]) < tol for p in pts) for k in kept):
            continue
        kept.append(i)
    kept.sort()
    return [curves[i] for i in kept], len(curves) - len(kept)


def _join_ends(curves, tol) -> list:
    """Morceaux de même style bout à bout (extrémités à moins de tol) : chaînés."""
    out = []
    groups = {}
    for c in curves:
        groups.setdefault((c["color"], c["width"], c["dash"]), []).append(c)
    for group in groups.values():
        cells = {}                        # case de la grille -> [(indice, bout)]
        for i, c in enumerate(group):
            for end in (0, -1):
                x, y = c["pts"][end]
                cells.setdefault((int(x // tol), int(y // tol)), []).append((i, end))

        def match(point, used, me):
            """
            Morceau libre qui touche point, s'il est le seul autre bout en ce point. Un
            point où se rejoignent plus de deux bouts (origine, coin du cadre où partent
            plusieurs courbes) n'est jamais un raccord : courbes distinctes.
            """
            cx, cy = int(point[0] // tol), int(point[1] // tol)
            near = [(i, end) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                    for i, end in cells.get((cx + dx, cy + dy), ())
                    if i not in me and np.hypot(*(group[i]["pts"][end] - point)) < tol]
            if len(near) == 1 and near[0][0] not in used:
                return near[0]
            return None
        used = set()
        for i, c in enumerate(group):
            if i in used:
                continue
            used.add(i)
            pts, chain = c["pts"], {i}
            for forward in (True, False):
                while True:
                    m = match(pts[-1] if forward else pts[0], used, chain)
                    if m is None:
                        break
                    j, end = m
                    other = group[j]["pts"]
                    if end == (-1 if forward else 0) and len(other) > 1 and len(pts) > 1:
                        # morceau retourné : seulement s'il prolonge sans demi-tour
                        # (deux courbes issues d'un même point divergent)
                        mine = pts[-1] - pts[-2] if forward else pts[0] - pts[1]
                        theirs = other[-2] - other[-1] if forward else other[1] - other[0]
                        if np.dot(mine, theirs) <= 0:
                            break
                    used.add(j)
                    chain.add(j)
                    if forward:
                        pts = np.vstack([pts, (other if end == 0 else other[::-1])[1:]])
                    else:
                        pts = np.vstack([(other if end == -1 else other[::-1])[:-1], pts])
            out.append(dict(c, pts=pts))
    return out


# ================================================================ un graphique
@dataclass
class Curve:
    points: np.ndarray                    # (n, 2) en points du PDF (y vers le haut)
    label: str = ""                       # étiquette ou entrée de légende, telle que lue
    color: tuple = (0.0, 0.0, 0.0)        # r, g, b entre 0 et 1
    width: float = 0.0
    dash: str = ""


@dataclass
class FoundGraph:
    page: int                             # numéro de page (1 = première)
    frame: tuple                          # cadre du tracé (image : toute l'image), points du PDF
    x: AxisFit | None                     # None : graphique en image (graduations non lues)
    y: AxisFit | None
    x_title: str = ""
    y_title: str = ""
    caption: list = field(default_factory=list)     # légende de la figure, conditions
    curves: list = field(default_factory=list)
    notes: list = field(default_factory=list)       # encadrés, textes non rattachés
    warnings: list = field(default_factory=list)
    raster: bool = False                  # graphique incorporé en image

    @property
    def title(self) -> str:
        return plain(self.caption[0]) if self.caption else f"Page {self.page}"

    @property
    def crop(self) -> tuple:
        return self.frame if self.raster else margin_box(self.frame)


def _analyse_frame(info, chars, strokes, page_no):
    """Un cadre : (FoundGraph, caractères employés), ou (None, ...) si pas de graduations."""
    x0, y0, x1, y1 = info["frame"]
    W, H = x1 - x0, y1 - y0
    warnings, notes = [], []
    xt, yt = short_ticks(strokes, info["frame"])
    labels = tick_labels(chars)
    below = best_row([l for l in labels if y0 - 0.15 * H - 10 < l["y1"] <= y0 + 1
                      and x0 - 0.6 * l["size"] <= l["cx"] <= x1 + 0.6 * l["size"]], "y1", 0.5)
    left = best_row([l for l in labels if x0 - 0.25 * W - 10 < l["x1"] <= x0 + 1
                     and y0 - 0.6 * l["size"] <= l["cy"] <= y1 + 0.6 * l["size"]], "x1", 2.5)
    fits = {}
    for name, items, grid, major, key in (("x", below, info["vgrid"], xt, "cx"),
                                          ("y", left, info["hgrid"], yt, "cy")):
        ticks, snapped = [], 0
        for l in items:
            pos, ok = snap(l[key], major, 0.6 * l["size"])     # trait de graduation d'abord
            if not ok:
                pos, ok = snap(l[key], major + grid, 0.6 * l["size"])
            snapped += ok
            ticks.append((pos, l["value"], l["text"]))
        fit = fit_axis(ticks)
        if fit is None:
            return None, set()            # tableau, encadré, schéma : pas un graphique
        while fit.residual > 1.0 and len(ticks) > 3:      # nombre égaré (graphique voisin)
            trials = [fit_axis(ticks[:i] + ticks[i + 1:]) for i in range(len(ticks))]
            i = int(np.argmin([t.residual if t else 1e9 for t in trials]))
            warnings.append(f"axe {name} : graduation « {ticks[i][2]} » écartée")
            ticks, fit = ticks[:i] + ticks[i + 1:], trials[i]
        fit.snapped = snapped
        if fit.residual > 1.0:
            warnings.append(f"axe {name} : graduations mal alignées ({fit.residual:.1f} pt)")
        fits[name] = fit
    used = set()
    for l in below + left:
        for c in chars:
            if l["x0"] - 0.1 <= c.cx <= l["x1"] + 0.1 and l["y0"] - 0.1 <= c.cy <= l["y1"] + 0.1:
                used.add(id(c))

    # titre X : juste sous les graduations, sinon au bout de leur rangée
    xl_bottom = min((l["y0"] for l in below), default=y0)
    free = [c for c in chars if c.upright and id(c) not in used]
    tx = lines([c for c in free if c.y1 <= xl_bottom + 0.5 and x0 - 0.1 * W <= c.cx <= x1 + 0.1 * W])
    tx = sorted((t for t in tx if xl_bottom - t[1][0].y1 < 3 * t[1][0].size),
                key=lambda t: -t[1][0].by)
    if not tx and below:
        row_y = np.mean([l["cy"] for l in below])
        tx = lines([c for c in free if c.x0 >= max(l["x1"] for l in below) - 1
                    and abs(c.cy - row_y) < 8])
    if len(tx) > 1 and tx[0][1][0].by - tx[1][1][0].by < 1.8 * tx[0][1][0].size:
        tx = [(tx[0][0] + " " + tx[1][0], tx[0][1] + tx[1][1])]     # titre sur deux lignes
    x_title = tx[0][0] if tx else ""
    if tx:
        used.update(id(c) for c in tx[0][1])
    # titre Y : tourné à gauche, sinon au-dessus du coin haut gauche (une ou deux lignes)
    yl_left = min((l["x0"] for l in left), default=x0)
    rot = sorted((c for c in chars if not c.upright and c.x1 <= yl_left + 0.5), key=lambda c: c.y0)
    y_title = rot_text(rot)
    used.update(id(c) for c in rot)
    if not rot:
        above = [t for t in lines([c for c in chars if c.upright and id(c) not in used
                                   and ((y1 - 2 < c.y0 < y1 + 30 and x0 - 40 < c.cx < x0 + 0.2 * W)
                                        or (c.x1 <= x0 + 1 and y1 - 12 < c.cy < y1 + 30))])
                 if t[1][-1].x1 - t[1][0].x0 < 0.3 * W]
        above.sort(key=lambda t: -t[1][0].by)
        y_title = " ".join(t for t, _ in above[:2])
        for _, row in above[:2]:
            used.update(id(c) for c in row)
    for name, title in (("x", x_title), ("y", y_title)):
        if not title:
            warnings.append(f"axe {name} : titre non trouvé")

    # courbes, traits de légende, encadrés
    raw, samples, boxes = [], [], []
    for p in strokes:
        if len(p.pts) < 2:
            continue
        d = np.diff(p.pts, axis=0)
        aligned = np.all((np.abs(d[:, 0]) < 0.05) | (np.abs(d[:, 1]) < 0.05))
        if aligned and len(p.pts) >= 4 and np.ptp(p.pts[:, 0]) > 3 and np.ptp(p.pts[:, 1]) > 3:
            lo, hi = p.pts.min(axis=0), p.pts.max(axis=0)
            if hi[0] - lo[0] < 0.9 * W and p.stroke and min(color(p.color)) < 0.95:
                boxes.append((lo[0], lo[1], hi[0], hi[1]))
            continue
        if p.stroke and np.ptp(p.pts[:, 1]) < 0.05 and p.length < 0.15 * W \
                and x0 < p.pts[0][0] < x1 and y0 < p.pts[0][1] < y1:
            samples.append(dict(pts=p.pts[[0, -1]], color=p.color, width=p.width, dash=p.dash))
            continue
        if not p.stroke or aligned:
            continue
        if len(p.pts) > 4 and np.allclose(p.pts[0], p.pts[-1], atol=0.5):
            continue                      # contour fermé : encadré arrondi, flèche pleine
        inside = (p.pts[:, 0] >= x0 - 0.5) & (p.pts[:, 0] <= x1 + 0.5) & \
                 (p.pts[:, 1] >= y0 - 0.5) & (p.pts[:, 1] <= y1 + 0.5)
        if inside.sum() < 2:
            continue
        raw.append(dict(pts=np.clip(p.pts[inside], [x0, y0], [x1, y1]), color=p.color,
                        width=p.width, dash=p.dash, label=""))
    curves, doubles = drop_duplicates(join_fragments(raw))
    if doubles:
        notes.append(f"{doubles} tracé(s) en double écarté(s)")
    samples = join_fragments(samples, straight=True)
    sizes = Counter((round(b[2] - b[0]), round(b[3] - b[1])) for b in boxes)
    boxes = [b for b in boxes if sizes[(round(b[2] - b[0]), round(b[3] - b[1]))] < 4]  # pas la grille
    if curves:                            # annotations : pointes et flèches
        wmax = max(c["width"] for c in curves)
        keep = []
        for c in curves:
            r, g, b = color(c["color"])
            grey = abs(r - g) < 0.02 and abs(g - b) < 0.02 and 0.3 < r < 0.95
            if np.hypot(*np.ptp(c["pts"], axis=0)) < 0.04 * min(W, H):
                continue
            if (len(c["pts"]) == 2 and c["width"] < 0.75 * wmax) or grey:
                notes.append("flèche ou trait d'annotation écarté")
                continue
            keep.append(c)
        curves = keep

    # textes : légende (trait + texte), encadrés, étiquettes au plus près
    rest = [c for c in chars if id(c) not in used]
    text_lines = [(t, row) for t, row in lines(rest) if t and not REFCODE.match(t.replace(" ", ""))]
    legend, taken = [], set()
    for smp in samples:
        sx1, sy = max(smp["pts"][:, 0]), smp["pts"][0][1]
        for t, row in text_lines:
            cy = sum(c.cy for c in row) / len(row)
            if abs(cy - sy) < 0.7 * row[0].size and 0 <= row[0].x0 - sx1 < 2.5 * row[0].size:
                legend.append((smp, t, row))
                break
    for smp, t, row in legend:
        # couleur la plus proche, puis même pointillé, puis même épaisseur
        dist = [float(np.max(np.abs(np.subtract(color(c["color"]), color(smp["color"])))))
                for c in curves]
        dmin = min(dist, default=1.0)
        match = [c for c, d in zip(curves, dist) if d <= dmin + 0.05] if dmin < 0.35 else []
        for key, val in (("dash", smp["dash"]), ("width", round(smp["width"], 2))):
            if len(match) > 1:
                sub = [c for c in match if (round(c[key], 2) if key == "width" else c[key]) == val]
                match = sub or match
        if len(match) == 1:
            match[0]["label"] = t
        else:
            warnings.append(f"légende « {plain(t)} » : {len(match)} courbes de même style")
        taken.add(id(row[0]))
        used.update(id(c) for c in row)
    box_lines = Counter()                 # lignes de texte de chaque encadré
    for t, row in text_lines:
        cx = (row[0].x0 + row[-1].x1) / 2
        cy = sum(c.cy for c in row) / len(row)
        for b in boxes:
            if b[0] - 1 <= cx <= b[2] + 1 and b[1] - 1 <= cy <= b[3] + 1:
                box_lines[b] += 1
    assigned = {}
    for t, row in text_lines:
        if id(row[0]) in taken:
            continue
        cx = (row[0].x0 + row[-1].x1) / 2
        cy = sum(c.cy for c in row) / len(row)
        if re.search(r"\b(in|de)creas(e|ing)\b", t, re.I):
            notes.append(f"texte : {plain(t)}")             # flèche « VGS increase »
            used.update(id(c) for c in row)
            continue
        ds = [dist_to_polyline(np.array([cx, cy]), c["pts"]) for c in curves]
        k = int(np.argmin(ds)) if curves else -1
        # encadré : conditions de mesure, sauf une étiquette (« 10 V », « Eon », ou
        # « T_J = 25 °C » posé contre une courbe)
        box = next((b for b in boxes if b[0] - 1 <= cx <= b[2] + 1 and b[1] - 1 <= cy <= b[3] + 1),
                   None)
        alone = box is None or box_lines.get(box, 0) <= 1     # un encadré à plusieurs lignes :
        label_like = alone and (                                # conditions de mesure
            datasheet.BARE.match(plain(t)) or datasheet.energy_kind(t) or (
                datasheet.SINGLE.match(plain(t)) and curves and ds[k] < 3 * row[0].size))
        if not label_like and box is not None:
            notes.append(f"encadré : {plain(t)}")
            used.update(id(c) for c in row)
            continue
        if not curves:
            continue
        inside = x0 <= cx <= x1 and y0 <= cy <= y1
        if not inside and not re.search(r"\d", t):
            continue                      # hors du cadre, un mot (suite de légende) : pas une étiquette
        if ds[k] > (0.3 * min(W, H) if inside else 2.5 * row[0].size):
            if inside:
                notes.append(f"texte : {plain(t)}")
                used.update(id(c) for c in row)
            continue
        used.update(id(c) for c in row)
        if not curves[k]["label"]:
            assigned.setdefault(k, []).append((ds[k], t))
    for k, items in assigned.items():
        items.sort()
        curves[k]["label"] = items[0][1]
        if len(items) > 1:
            warnings.append(f"courbe {k + 1} : plusieurs textes proches "
                            f"({', '.join(plain(t) for _, t in items)})")
    unlabeled = sum(1 for c in curves if not c["label"])
    if len(curves) > 1 and unlabeled:
        warnings.append(f"{unlabeled} courbe(s) sans étiquette")
    if not curves:
        warnings.append("aucune courbe vectorielle")
    found = FoundGraph(page_no, tuple(float(v) for v in info["frame"]), fits["x"], fits["y"],
                       x_title, y_title, [],
                       [Curve(c["pts"], c["label"], color(c["color"]), c["width"], c["dash"])
                        for c in curves], notes, warnings)
    return found, used


# ================================================================ légendes de figures
def _split_captions(page_lines) -> list:
    """
    Deux légendes côte à côte sur la même ligne (« Figure 9. ...  Figure 10. ... »), même
    collées (« ...as aFigure 4 ») quand la seconde commence à l'abscisse d'une autre
    légende de la page.
    """
    starts = [row[0].x0 for t, row in page_lines if CAPTION.match(t)]
    out = []
    for t, row in page_lines:
        cuts = [0]
        for i in range(1, len(row)):
            rest = "".join(c.text for c in row[i:i + 12])
            if not CAPTION.match(rest):
                continue
            spaced = row[i].x0 - row[i - 1].x1 > 0.15 * row[i].size
            aligned = (CAPTION.match(t) and row[i].x0 > row[0].x0 + 50
                       and any(abs(row[i].x0 - x) < 3 for x in starts))
            if spaced or aligned:
                cuts.append(i)
        cuts.append(len(row))
        out += [(join(row[a:b]), row[a:b]) for a, b in zip(cuts[:-1], cuts[1:])]
    return out


def _caption_blocks(page_lines, frames) -> list:
    """Légendes numérotées et leurs lignes de suite (même taille, hors des cadres)."""
    rows = sorted(_split_captions(page_lines), key=lambda t: -t[1][0].by)

    def in_frame(row):
        cx = (row[0].x0 + row[-1].x1) / 2
        cy = sum(c.cy for c in row) / len(row)
        return any(f["frame"][0] - 2 <= cx <= f["frame"][2] + 2 and
                   f["frame"][1] - 2 <= cy <= f["frame"][3] - 2 for f in frames)
    blocks = []
    for i, (t, row) in enumerate(rows):
        if not CAPTION.match(t):
            continue
        block, last = [(t, row)], row
        for t2, row2 in rows[i + 1:]:
            gap = last[0].by - row2[0].by
            if gap <= 0:
                continue
            if gap > 1.7 * max(c.size for c in last):
                break
            if min(c.x1 for c in row2) > max(c.x1 for c in last) \
                    or max(c.x0 for c in row2) < min(c.x0 for c in last) - 5:
                continue                  # autre colonne (avant le test de légende : la
            if CAPTION.match(t2):         # légende voisine, un peu plus bas, n'arrête rien)
                break
            ratio = max(c.size for c in row2) / max(c.size for c in last)
            if not 0.75 <= ratio <= 1.3 or in_frame(row2):
                continue
            block.append((t2, row2))
            last = row2
        blocks.append(dict(text=[t for t, _ in block],
                           x0=min(c.x0 for _, r in block for c in r),
                           x1=max(c.x1 for _, r in block for c in r),
                           top=max(c.y1 for c in row), bottom=min(c.y0 for c in block[-1][1]),
                           chars={id(c) for _, r in block for c in r}))
    return blocks


def _match_captions(frames, blocks) -> dict:
    """
    Légendes toutes au-dessus ou toutes au-dessous des graphiques : la disposition la moins
    coûteuse. Coût d'une paire : écart vertical, plus la part du graphique que la légende
    ne recouvre pas en largeur ; paires retenues de la moins chère à la plus chère (deux
    graphiques côte à côte : chacun la légende de sa colonne, même un peu plus loin).
    """
    best = None
    for side in ("above", "below"):
        cands = []
        for k, f in enumerate(frames):
            x0, y0, x1, y1 = f["frame"]
            for i, b in enumerate(blocks):
                if b["x1"] < x0 - 20 or b["x0"] > x1 + 20:
                    continue
                d = b["bottom"] - y1 if side == "above" else y0 - b["top"]
                if 0 <= d < 110:
                    overlap = max(min(x1, b["x1"]) - max(x0, b["x0"]), 0.0)
                    cands.append((d + 60 * (1 - overlap / max(x1 - x0, 1e-9)), k, i))
        cost, pairs, taken = 0.0, {}, set()
        for c, k, i in sorted(cands):
            if k not in pairs and i not in taken:
                pairs[k] = i
                taken.add(i)
                cost += c
        cost += 150 * (len(frames) - len(pairs))
        if best is None or cost < best[0]:
            best = (cost, pairs)
    return best[1]


# ================================================================ document
IMAGE_MIN = 100     # côté minimal d'une image de graphique, points du PDF


def _image_frames(images, frames, page_area) -> list:
    """Grandes images hors des cadres vectoriels : graphiques en image possibles."""
    out = []
    for b in images:
        w, h = b[2] - b[0], b[3] - b[1]
        if w < IMAGE_MIN or h < IMAGE_MIN or w * h > 0.6 * page_area:
            continue
        if any(min(b[2], f["frame"][2]) - max(b[0], f["frame"][0]) > 0.2 * w and
               min(b[3], f["frame"][3]) - max(b[1], f["frame"][1]) > 0.2 * h for f in frames):
            continue
        if any(abs(b[0] - o["frame"][0]) < 1 and abs(b[1] - o["frame"][1]) < 1 for o in out):
            continue                      # image répétée
        out.append({"frame": tuple(float(v) for v in b), "raster": True})
    return out


def analyse_page(page, page_no) -> list:
    """
    Graphiques d'une page pdfminer (LTPage) : vectoriels, et candidats en image (grandes
    images, légendées ou non ; `_build` écarte celles sans cadre quadrillé).
    """
    chars, strokes, images = flatten(page)
    vector = find_frames(strokes, page.width * page.height)
    frames = vector + _image_frames(images, vector, page.width * page.height)
    if not frames:
        return []
    page_lines = [t for t in lines(chars) if t[0]]
    blocks = _caption_blocks(page_lines, frames)
    pairs = _match_captions(frames, blocks)
    caption_ids = set().union(*(b["chars"] for b in blocks)) if blocks else set()
    # chaque caractère et tracé : au graphique le plus proche (dans sa marge) ;
    # un texte tourné (titre Y) va au graphique à sa droite
    boxes = [margin_box(f["frame"]) if not f.get("raster") else (0, 0, -1, -1) for f in frames]
    own_c = [[] for _ in frames]
    own_s = [[] for _ in frames]
    for c in chars:
        if id(c) in caption_ids:
            continue
        ks = [k for k, b in enumerate(boxes) if b[0] <= c.cx <= b[2] and b[1] <= c.cy <= b[3]]
        if not ks:
            continue
        if not c.upright:
            ks = [k for k in ks if c.cx < frames[k]["frame"][0]] or ks
        own_c[min(ks, key=lambda k: rect_dist(c.cx, c.cy, frames[k]["frame"]))].append(c)
    for p in strokes:
        cx, cy = p.pts.mean(axis=0)
        ks = [k for k, b in enumerate(boxes) if b[0] <= cx <= b[2] and b[1] <= cy <= b[3]]
        if ks:
            own_s[min(ks, key=lambda k: rect_dist(cx, cy, frames[k]["frame"]))].append(p)
    used_all = set(caption_ids)
    found = []
    for k, f in enumerate(frames):
        if f.get("raster"):
            g, used = FoundGraph(page_no, f["frame"], None, None, raster=True), set()
            g.warnings.append("graphique en image")
        else:
            g, used = _analyse_frame(f, own_c[k], own_s[k], page_no)
        if g is None:
            continue
        used_all |= used
        if k in pairs:
            g.caption = list(blocks[pairs[k]]["text"])
        x0, y0, x1, y1 = f["frame"]
        if not g.raster and any(b[0] < x1 and b[2] > x0 and b[1] < y1 and b[3] > y0 and
               (b[2] - b[0]) * (b[3] - b[1]) > 0.2 * (x1 - x0) * (y1 - y0) for b in images):
            g.warnings.append("image dans le cadre : courbes peut-être en image, non lues")
        found.append((k, g))
    # légende sans numéro (lignes libres juste au-dessus) et conditions juste au-dessous
    free_lines = [t for t in lines([c for c in chars if id(c) not in used_all]) if t[0]]
    for k, g in found:
        x0, y0, x1, y1 = frames[k]["frame"]
        top = max([y1] + [c.y1 for c in own_c[k] if id(c) in used_all and c.cy > y1])
        if not g.caption:
            up = sorted(((t, r) for t, r in free_lines if top < r[0].by < top + 75
                         and min(c.x0 for c in r) < x1 and max(c.x1 for c in r) > x0 - 60),
                        key=lambda t: -t[1][0].by)
            g.caption = [t for t, _ in up]
        bottom = min([y0] + [c.y0 for c in own_c[k] if id(c) in used_all and c.cy < y0])
        down = sorted(((t, r) for t, r in free_lines if bottom - 32 < r[0].by < bottom
                       and min(c.x0 for c in r) < x1 and max(c.x1 for c in r) > x0),
                      key=lambda t: -t[1][0].by)
        g.caption += [t for t, _ in down]
    return reading_order([g for _, g in found])


def reading_order(graphs) -> list:
    """De haut en bas par rangées (hauts à moins de 15 points près), de gauche à droite."""
    rows = []
    for g in sorted(graphs, key=lambda g: -g.frame[3]):
        if rows and rows[-1][0].frame[3] - g.frame[3] < 15:
            rows[-1].append(g)
        else:
            rows.append([g])
    return [g for row in rows for g in sorted(row, key=lambda g: g.frame[0])]


def analyse(path, pages=None) -> list:
    """Graphiques de tout le PDF (ou des pages données, numérotées à partir de 1)."""
    if not available():
        raise PdfImportError("import PDF indisponible : installez pdfminer.six et pypdfium2")
    from pdfminer.high_level import extract_pages
    from pdfminer.pdfparser import PDFSyntaxError
    numbers = None if pages is None else [p - 1 for p in pages]
    found = []
    try:
        for i, page in enumerate(extract_pages(str(path), page_numbers=numbers)):
            found += analyse_page(page, (pages[i] if pages else i + 1))
    except (PDFSyntaxError, OSError, ValueError, TypeError, KeyError) as error:
        raise PdfImportError(f"{pathlib.Path(path).name} : PDF illisible ({error})") from error
    return found


# ================================================================ conversion en composant
TEMPERATURE = re.compile(r"\bT[\w,]*\s*=\s*([−-]?\d+(?:[.,]\d+)?)\s*[°º]\s*C")
PAIR = re.compile(r"([A-Za-z][\w()]*(?:,[A-Za-z]\w*)?)\s*=\s*([^,;]+)")    # « R_G,ext = 2 Ω »


def _nominal(fit: AxisFit, pos: float, value: float) -> float:
    """Valeur lue sur la graduation si l'ajustement la retrouve, sinon celle de l'ajustement."""
    fitted = float(fit.value(pos))
    return value if abs(fitted - value) <= 1e-3 * max(abs(value), 1e-12) else fitted


@dataclass
class DraftGraph:
    """Graphique converti, avec ce que le texte en dit (type, partie, énergie, avertissements)."""
    graph: Graph
    found: FoundGraph
    kind: str = "other"                   # clé de datasheet.KINDS
    energy: str = ""                      # « on », « off », « rec »... (énergies)
    diode: bool = False                   # graphique de diode (module IGBT + diode)
    part: str = ""                        # composant auquel il revient (« IGBT », « Diode »)
    conditions: list = field(default_factory=list)  # conditions communes, lisibles
    warnings: list = field(default_factory=list)
    plot: plotimage.PlotArea | None = None  # graphique en image : cadre, graduations repérées


@dataclass
class Draft:
    """Import préparé : identité lue, graphiques convertis, parties (module : IGBT + diode)."""
    path: pathlib.Path
    identity: datasheet.Identity
    graphs: list
    parts: list

    def component(self, indices=None, part=None, part_number=None, manufacturer=None,
                  category=None) -> tuple:
        """
        Composant d'une partie (la première par défaut) : graphiques indices (sinon tous
        ceux de la partie), identité lue ou donnée. Rend (Component, avertissements).
        """
        part = part or self.parts[0]
        chosen = [dg for i, dg in enumerate(self.graphs)
                  if (i in indices if indices is not None else dg.part == part)]
        diode_part = part == "Diode" and len(self.parts) > 1
        identity = self.identity
        if part_number is None:
            part_number = identity.part_number + (
                " (diode)" if diode_part and identity.part_number else "")
        if category is None:
            category = "Diode" if diode_part else identity.category
        component = Component(
            name=self.path.stem + (" (diode)" if diode_part else ""),
            part_number=part_number, category=category,
            manufacturer=identity.manufacturer if manufacturer is None else manufacturer)
        component.graphs = [dg.graph for dg in chosen]
        component.notes, warnings = _notes(self.path.name, identity, chosen)
        return component, warnings

    def calibrate(self, index, x1, x2, y1, y2, log_x=False, log_y=False):
        """
        Graphique en image : valeurs des graduations repérées (première et dernière de chaque
        axe) -> calibration orthonormée sur ces repères. CalibrationError si incohérentes.
        """
        dg = self.graphs[index]
        if dg.plot is None:
            raise ValueError("graphique vectoriel : déjà calibré")
        calibration = _raster_calibration(dg.plot, x1, x2, y1, y2, log_x, log_y)
        dg.graph.set_calibration(calibration)
        return calibration


def _raster_calibration(plot, x1, x2, y1, y2, log_x, log_y) -> AxisCalibration:
    """Calibration orthonormée sur les repères d'un graphique en image (O, X2, Y2)."""
    origin, px2, py2 = plot.markers()
    return AxisCalibration(*to_four_points(origin, px2, py2), x1=x1, x2=x2, y1=y1, y2=y2,
                           log_x=log_x, log_y=log_y)


def _notes(filename, identity, chosen) -> tuple:
    """Notes du composant (description, conditions lues, points à vérifier)."""
    described, warnings = [], []
    for dg in chosen:
        where = f"{dg.graph.name} (p.{dg.found.page})"
        if dg.conditions:
            described.append(f"{where} : " + " ; ".join(dg.conditions))
        warnings += [f"{where} : {w}" for w in dg.warnings]
    text = [f"Importé de {filename} : {len(chosen)} graphique(s)."]
    if identity is not None and identity.description:
        text.append(identity.description)
    if described:
        text += ["", "Conditions lues :"] + [f"- {d}" for d in described]
    if warnings:
        text += ["", "À vérifier :"] + [f"- {w}" for w in warnings]
    return "\n".join(text), warnings


def _texts(g: FoundGraph, known) -> tuple:
    """Légende, encadrés et textes du graphique, nettoyés (lettres dessinées, symboles)."""
    def fix(t):
        return datasheet.clean(datasheet.fix_symbols(t, known))
    caption = [fix(t) for t in g.caption]
    boxed = [fix(t.split(" : ", 1)[1]) for t in g.notes if t.startswith("encadré")]
    loose = [fix(t.split(" : ", 1)[1]) for t in g.notes if t.startswith("texte")]
    return caption, boxed, loose


def _graph_conditions(texts) -> list:
    """(symbole, valeur) des textes communs, sans les « I_D = f(V_DS) »."""
    out = []
    for text in texts:
        if datasheet.expand_range(text):
            continue                      # plage ou liste de valeurs : une par courbe
        for symbol, value in PAIR.findall(text):
            value = value.strip()
            if value.count(")") > value.count("("):
                value = value[:value.rfind(")")].strip()     # « (T_J = 25 °C) »
            if re.search(r"\bf\s*\(", value) or symbol.lower().startswith("param"):
                continue
            out.append((symbol, value))
    return out


def _build(path, found, dpi=200) -> list:
    """Graphiques convertis : image, calibration, axes, courbes et leurs conditions."""
    import pypdfium2 as pdfium
    path = pathlib.Path(path)
    scale = dpi / 72.0
    rendered, out = {}, []
    try:
        doc = pdfium.PdfDocument(str(path))
    except Exception as error:            # pypdfium2 : PdfiumError
        raise PdfImportError(f"{path.name} : PDF illisible ({error})") from error
    try:
        for g in found:
            if g.page not in rendered:
                page = doc[g.page - 1]
                left, bottom, right, top = page.get_cropbox()
                image = np.asarray(page.render(scale=scale).to_pil().convert("RGB"))
                rendered[g.page] = (image, left, top)
            image, left, top = rendered[g.page]
            bx0, by0, bx1, by1 = g.crop
            c0 = max(int(np.floor((bx0 - left) * scale)), 0)
            c1 = min(int(np.ceil((bx1 - left) * scale)), image.shape[1])
            r0 = max(int(np.floor((top - by1) * scale)), 0)
            r1 = min(int(np.ceil((top - by0) * scale)), image.shape[0])

            if g.raster:
                crop = np.ascontiguousarray(image[r0:r1, c0:c1])
                area = plotimage.find_plot(crop)
                if area is not None:      # sinon : dessin, photo... pas un graphique
                    out.append(_interpret_raster(g, crop, area, f"{path.name} p.{g.page}"))
                continue

            def to_pixels(points, c0=c0, r0=r0, left=left, top=top):
                points = np.asarray(points, dtype=float).reshape(-1, 2)
                return np.column_stack([(points[:, 0] - left) * scale - c0,
                                        (top - points[:, 1]) * scale - r0])
            xs, ys = sorted(g.x.ticks), sorted(g.y.ticks)
            (xa, xva, _), (xb, xvb, _) = xs[0], xs[-1]
            (ya, yva, _), (yb, yvb, _) = ys[0], ys[-1]
            origin, x2, y2 = to_pixels([(xa, ya), (xb, ya), (xa, yb)])
            calibration = AxisCalibration(
                *to_four_points(origin, x2, y2),
                x1=_nominal(g.x, xa, xva), x2=_nominal(g.x, xb, xvb),
                y1=_nominal(g.y, ya, yva), y2=_nominal(g.y, yb, yvb),
                log_x=g.x.log, log_y=g.y.log)
            out += _interpret(g, np.ascontiguousarray(image[r0:r1, c0:c1]), calibration,
                              to_pixels, f"{path.name} p.{g.page}")
    finally:
        doc.close()
    return out


def _interpret(g, image, calibration, to_pixels, source) -> list:
    """Sens d'un graphique : axes, conditions, plages, type ; Eon et Eoff séparés."""
    (xq, xu, _), (yq, yu, _) = (datasheet.axis(*unit_split(t)) for t in (g.x_title, g.y_title))
    caption, boxed, loose = _texts(g, (xq, yq))
    title = datasheet.plain(caption[0]) if caption else f"Page {g.page}"
    param = datasheet.parameter(" ".join(caption + boxed))
    warnings = list(g.warnings)
    labels = [datasheet.clean(datasheet.fix_symbols(c.label, (xq, yq))) for c in g.curves]
    # plage « V_GS = 6~18V, 2V step », liste « VGS= 12, 14, 16 V », ou encadré d'une valeur
    # par ligne (« VGS = -4V », « VGS = 0V »...) : une valeur par courbe sans étiquette
    spans = [(text, datasheet.expand_range(text)) for text in labels + boxed + loose + caption]
    spans = [(text, span) for text, span in spans if span]
    kind = datasheet.classify(xq, xu, yq, yu, " ".join(caption))
    stacked = {}
    for text in boxed + loose:
        single = datasheet.SINGLE.match(datasheet.plain(text))
        pair = PAIR.match(text) if single else None
        if pair:
            stacked.setdefault(datasheet.plain(pair.group(1)), []).append(pair.group(2).strip())
    for symbol, values in stacked.items():
        numbers = [datasheet.BARE.match(v) for v in values]
        if len(values) > 1 and all(numbers):
            unit = numbers[0].group(2)
            spans.append((None, (symbol, sorted(float(m.group(1).replace("−", "-").replace(",", "."))
                                               for m in numbers), unit)))
    used_texts = set()
    for text, (symbol, values, unit) in spans[:1]:
        targets = [i for i, label in enumerate(labels) if not label or label == text]
        if kind not in ("output", "diode", "transfer"):
            warnings.append(f"valeurs de « {datasheet.plain(text or symbol)} » non attribuées : "
                            "ordre des courbes inconnu pour ce graphique")
            break
        magnitudes = [float(np.mean(np.abs(g.y.value(g.curves[i].points[:, 1]))))
                      for i in targets]
        assigned = datasheet.assign_range(magnitudes, values)
        what = datasheet.plain(text) if text else f"{datasheet.plain(symbol)} = " + ", ".join(
            f"{v:g}" for v in values) + f" {unit}"
        if assigned is None:
            warnings.append(f"« {what} » : {len(values)} valeurs pour {len(targets)} courbe(s) "
                            "sans étiquette, non attribuées")
        else:
            for i, value in zip(targets, assigned):
                labels[i] = f"{symbol} = {datasheet.format_value(value, unit)}"
            warnings = [w for w in warnings if "sans étiquette" not in w]
            warnings.append(f"valeurs de « {what} » attribuées dans l'ordre du courant : "
                            "à vérifier")
            used_texts = {datasheet.plain(symbol).lower()} if text is None else set()
    if used_texts:                         # valeurs empilées : plus des conditions communes
        boxed = [t for t in boxed if not (PAIR.match(t) and datasheet.plain(
            PAIR.match(t).group(1)).lower() in used_texts)]
    if kind not in ("output", "diode", "transfer"):
        stacked_symbols = {k.lower() for k, v in stacked.items() if len(v) > 1}
        boxed = [t for t in boxed if not (PAIR.match(t) and datasheet.plain(
            PAIR.match(t).group(1)).lower() in stacked_symbols)]
    pairs = _graph_conditions(caption[1:] + boxed)
    conditions = [f"{datasheet.plain(s)} = {datasheet.plain(v)}" for s, v in pairs]
    curves = []
    for i, (curve, label) in enumerate(zip(g.curves, labels)):
        own = datasheet.curve_condition(label, param)
        present = {datasheet.plain(s).lower() for s, _ in PAIR.findall(own)}
        extra = [c for (s, _), c in zip(pairs, conditions)
                 if datasheet.plain(s).lower() not in present]
        condition = datasheet.plain(", ".join(([own] if own else []) + extra))
        pixels = to_pixels(curve.points)
        keep = np.ones(len(pixels), bool)
        keep[1:] = np.any(np.abs(np.diff(pixels, axis=0)) > 1e-6, axis=1)
        dataset = Dataset(name=datasheet.plain(own) or f"Courbe {i + 1}",
                          condition=condition if "=" in condition else "",
                          pixels=pixels[keep])
        dataset.curve_color = tuple(int(round(255 * v)) for v in curve.color)
        m = TEMPERATURE.search(condition)
        if m:
            dataset.temperature = float(m.group(1).replace("−", "-").replace(",", "."))
        energy = (datasheet.energy_kind(label) or datasheet.energy_kind(yq)
                  or datasheet.energy_kind(title) or "")
        curves.append((dataset, energy))
    # énergies de fermeture et d'ouverture sur un même graphique : un graphique chacune
    groups = {}
    for dataset, energy in curves:
        groups.setdefault(energy if kind == "energy" else "", []).append(dataset)
    if len(groups) > 1:
        warnings.append("énergies séparées en "
                        + ", ".join(f"E{k}" if k else "sans nom" for k in groups)
                        + " (même image)")
    diode = datasheet.diode_graph(" ".join(caption), xq, yq, labels)
    out = []
    for energy, datasets in (groups.items() if groups else [("", [])]):
        split = len(groups) > 1
        graph = Graph(name=f"{title} — E{energy or '?'}" if split else title,
                      image=image, source=source)
        graph.x_axis = Axis(datasheet.plain(xq), xu)
        graph.y_axis = Axis(f"E{energy}" if split and energy else datasheet.plain(yq), yu)
        for k, dataset in enumerate(datasets):
            dataset.color = PALETTE[k % len(PALETTE)]
        graph.datasets = datasets or [Dataset(name="Courbe 1")]
        graph.set_calibration(calibration)
        out.append(DraftGraph(graph, g, kind, energy, diode, "", conditions, list(warnings)))
    return out


# unités sûres d'après la lettre du symbole (les autres dépendent d'un préfixe : µJ, nC, ns...)
SYMBOL_UNITS = {"V": "V", "I": "A", "T": "°C", "P": "W"}


def _interpret_raster(g, image, area, source) -> DraftGraph:
    """
    Graphique en image : nom, conditions et type d'après la légende de la figure ; axes
    d'après « Y = f(X) » ; calibration sur les graduations lues ; courbes relevées
    automatiquement (`curvetrace`), nommées par leur rang et leur style.
    """
    caption, _, _ = _texts(g, ())
    title = datasheet.plain(caption[0]) if caption else f"Page {g.page}"
    yq, xq = datasheet.function_axes(" ".join(caption)) or ("", "")
    xu, yu = (SYMBOL_UNITS.get(q[:1], "") for q in (xq, yq))
    kind = datasheet.classify(xq, xu, yq, yu, " ".join(caption))
    pairs = _graph_conditions(caption[1:] if len(caption) > 1 else caption)
    conditions = [f"{datasheet.plain(s)} = {datasheet.plain(v)}" for s, v in pairs]
    warnings = list(g.warnings)
    if xq or yq:
        warnings.append("axes d'après la légende (« Y = f(X) ») : unités à vérifier")
    values = area.read_values()
    calibration = None
    if None not in values.values():
        try:
            calibration = _raster_calibration(area, log_x=area.log_x, log_y=area.log_y,
                                              **values)
            warnings.append(f"graduations lues dans l'image (X de {values['x1']:g} à "
                            f"{values['x2']:g}, Y de {values['y1']:g} à {values['y2']:g}) : "
                            "à vérifier")
        except CalibrationError as error:
            warnings.append(f"graduations lues incohérentes ({error}) : à saisir")
    else:
        missing = [axis for axis, v in (("X", values["x1"]), ("Y", values["y1"])) if v is None]
        warnings.append(f"graduations {' et '.join(missing)} non lues : valeurs à saisir")
    graph = Graph(name=title, image=image, source=source)
    graph.x_axis = Axis(datasheet.plain(xq), xu)
    graph.y_axis = Axis(datasheet.plain(yq), yu)
    traced = curvetrace.trace(image, area).curves
    m = TEMPERATURE.search(", ".join(conditions))
    datasets = []
    for k, curve in enumerate(traced or [None]):
        name = f"Courbe {k + 1}" + (f" ({curve.style})" if curve is not None else "")
        dataset = Dataset(name=name, condition=", ".join(conditions),
                          pixels=curve.points.copy() if curve is not None else np.empty((0, 2)))
        if m:
            dataset.temperature = float(m.group(1).replace("−", "-").replace(",", "."))
        dataset.color = PALETTE[k % len(PALETTE)]
        datasets.append(dataset)
    if traced:
        warnings.append(f"{len(traced)} courbe(s) relevée(s) automatiquement dans l'image "
                        "(noms, croisements, courbes proches) : à vérifier")
    else:
        warnings.append("aucune courbe relevée : à relever dans l'application")
    graph.set_calibration(calibration)
    graph.datasets = datasets          # après la calibration : ordre de la polyligne gardé
    diode = datasheet.diode_graph(" ".join(caption), xq, yq)
    return DraftGraph(graph, g, kind, "", diode, "", conditions, warnings, plot=area)


def _assign_parts(graphs, category) -> list:
    """Parties et rôles PLECS : module IGBT avec graphiques de diode -> IGBT + Diode."""
    module = category == "IGBT" and any(dg.diode for dg in graphs)
    parts = ["IGBT", "Diode"] if module else [category or "Composant"]
    for dg in graphs:
        dg.part = "Diode" if module and dg.diode else parts[0]
        temperatures = [d.temperature for d in dg.graph.datasets]
        dg.graph.plecs_role = "" if dg.plot is not None else datasheet.plecs_role(
            dg.kind, temperatures, dg.energy, diode_part=module and dg.diode)
    return parts


def read_identity(path) -> datasheet.Identity:
    """Référence, fabricant, catégorie et description lus en première page."""
    from pdfminer.high_level import extract_pages
    try:
        page = next(iter(extract_pages(str(path), page_numbers=[0])))
    except (StopIteration, OSError, ValueError, TypeError, KeyError):
        return datasheet.Identity()
    chars, _, _ = flatten(page)
    rows = [(datasheet.clean(t), max(c.size for c in row)) for t, row in lines(chars) if t]
    return datasheet.identify(rows, pathlib.Path(path).name)


def prepare(path, dpi=200, pages=None) -> Draft:
    """Import préparé, avant le choix de l'utilisateur ; PdfImportError sans graphique."""
    path = pathlib.Path(path)
    found = analyse(path, pages)
    graphs = _build(path, found, dpi) if found else []
    if not graphs:
        raise PdfImportError(f"{path.name} : aucun graphique trouvé (PDF scanné ?)")
    identity = read_identity(path)
    return Draft(path, identity, graphs, _assign_parts(graphs, identity.category))


def to_component(path, found, dpi=200, name=None) -> tuple:
    """
    Tous les graphiques trouvés, convertis (image recadrée, calibration orthonormée sur
    les graduations extrêmes, courbes en pixels, conditions), sans lire l'identité.
    Rend (Component, avertissements).
    """
    path = pathlib.Path(path)
    graphs = _build(path, found, dpi)
    _assign_parts(graphs, "")
    component = Component(name=name or path.stem)
    component.graphs = [dg.graph for dg in graphs]
    component.notes, warnings = _notes(path.name, None, graphs)
    return component, warnings


def import_pdf(path, dpi=200, pages=None) -> tuple:
    """prepare + composant de la première partie. Rend (Component, avertissements)."""
    return prepare(path, dpi, pages).component()
