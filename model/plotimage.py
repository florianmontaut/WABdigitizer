# model/plotimage.py
"""
Graphique incorporé en image (raster) : cadre, grille et graduations.

On trouve **où** sont les graduations (étiquettes sous le cadre et à sa gauche) : les
repères de calibration vont sur la première et la dernière de chaque axe. Leurs valeurs
sont lues sans moteur d'OCR : chaque chiffre est comparé aux chiffres dessinés avec les
polices du système (Arial, Calibri...), la police qui ressemble le mieux est retenue,
puis les valeurs doivent former une suite régulière (arithmétique, ou géométrique sur
un axe log) : une graduation mal lue est corrigée par les autres, une lecture
incohérente n'est pas proposée (saisie par l'utilisateur). Échelle log : suite
géométrique, sinon grille à traits secondaires irréguliers.
Repère : x = colonne, y = ligne (vers le bas), pixels de l'image.
"""
import functools
import math
import os
from dataclasses import dataclass, field

import numpy as np

LINE = 235          # gris en dessous duquel un pixel appartient à un trait (grille comprise)
INK = 140           # gris en dessous duquel un pixel est de l'encre (texte, courbes)
SPAN = 0.35         # longueur minimale d'un trait de grille, en fraction de l'image
END = 4             # tolérance sur les extrémités des traits de grille, en pixels


@dataclass
class PlotArea:
    frame: tuple                          # (gauche, haut, droite, bas) du tracé, pixels
    x_grid: list                          # abscisses des traits verticaux de la grille
    y_grid: list                          # ordonnées des traits horizontaux
    x_labels: list = field(default_factory=list)    # boîtes (x0, y0, x1, y1) des graduations X
    y_labels: list = field(default_factory=list)    # boîtes des graduations Y (de haut en bas)
    log_x: bool = False
    log_y: bool = False
    char: float = 0.0                     # hauteur des chiffres, pixels
    x_values: tuple | None = None         # (première, dernière) graduations X lues, ou None
    y_values: tuple | None = None         # (bas, haut) graduations Y lues, ou None
    x_texts: list = field(default_factory=list)     # textes lus (contrôle, avertissements)
    y_texts: list = field(default_factory=list)

    def markers(self) -> tuple:
        """Repères O, X2, Y2 (pixels) : premières et dernières graduations de chaque axe."""
        xa, xb = (self._snap((b[0] + b[2]) / 2, self.x_grid) for b in (self.x_labels[0],
                                                                       self.x_labels[-1]))
        # centre d'une graduation Y : haut de l'étiquette + demi-hauteur des chiffres (celle
        # du bas peut être coupée au bord du cadre)
        ya, yb = (self._snap(b[1] + (self.char - 1) / 2, self.y_grid) for b in (
            self.y_labels[-1], self.y_labels[0]))
        return (xa, ya), (xb, ya), (xa, yb)

    def read_values(self) -> dict:
        """Valeurs lues des repères : {"x1", "x2", "y1", "y2"} -> valeur ou None."""
        x = self.x_values or (None, None)
        y = self.y_values or (None, None)
        return {"x1": x[0], "x2": x[1], "y1": y[0], "y2": y[1]}

    @staticmethod
    def _snap(value, grid):
        """Trait de grille le plus proche (étiquette centrée sur sa graduation)."""
        if grid:
            near = min(grid, key=lambda g: abs(g - value))
            if abs(near - value) <= 6:
                return float(near)
        return float(value)


def _runs(mask: np.ndarray, gap: int = 1) -> list:
    """Suites de True d'un vecteur (trous de `gap` pixels comblés) : [(début, fin)], fin incluse."""
    idx = np.flatnonzero(mask)
    if not len(idx):
        return []
    cuts = np.flatnonzero(np.diff(idx) > gap + 1)
    starts = np.r_[idx[0], idx[cuts + 1]]
    ends = np.r_[idx[cuts], idx[-1]]
    return list(zip(starts.tolist(), ends.tolist()))


def _longest_runs(mask: np.ndarray, minimum: float) -> list:
    """
    Par ligne, la plus longue suite de True (trous d'un pixel comblés, comme `_runs`) d'au
    moins `minimum` pixels : [(ligne, début, fin)], fin incluse. Calcul vectorisé, toutes
    les lignes d'un coup.
    """
    mask = np.asarray(mask, bool)
    if not mask.size:
        return []
    filled = mask.copy()
    filled[:, 1:-1] |= mask[:, :-2] & mask[:, 2:]
    padded = np.zeros((mask.shape[0], mask.shape[1] + 2), np.int8)
    padded[:, 1:-1] = filled
    step = np.diff(padded, axis=1)
    rows, starts = np.nonzero(step == 1)
    _, ends = np.nonzero(step == -1)          # même ordre (ligne, colonne) que les débuts
    lengths = ends - starts
    keep = lengths >= minimum
    rows, starts, ends, lengths = rows[keep], starts[keep], ends[keep], lengths[keep]
    if not len(rows):
        return []
    order = np.lexsort((starts, -lengths, rows))    # par ligne : la plus longue, la première
    rows, starts, ends = rows[order], starts[order], ends[order]
    first = np.r_[True, rows[1:] != rows[:-1]]
    return list(zip(rows[first].tolist(), starts[first].tolist(), (ends[first] - 1).tolist()))


def _lines(mask: np.ndarray, minimum: float) -> list:
    """Traits horizontaux d'un masque : (ligne centrale, début, fin), lignes voisines réunies."""
    found = _longest_runs(mask, minimum)
    out = []
    for row, a, b in found:
        if out and row - out[-1][-1][0] <= 1 and abs(a - out[-1][-1][1]) <= END \
                and abs(b - out[-1][-1][2]) <= END:
            out[-1].append((row, a, b))
        else:
            out.append([(row, a, b)])
    return [(float(np.mean([r for r, _, _ in g])), min(a for _, a, _ in g),
             max(b for _, _, b in g)) for g in out]


def _logarithmic(grid, a, b) -> bool:
    """
    Échelle log : au moins 3 traits secondaires entre deux graduations voisines (a, b), à
    pas irrégulier (une décade). Les traits manquants d'une grille linéaire (cachés par une
    légende) ne suffisent pas.
    """
    a, b = sorted((a, b))
    inner = sorted(g for g in grid if a + 1.5 < g < b - 1.5)
    if len(inner) < 3:
        return False
    steps = np.diff([a] + inner + [b])
    return steps.max() > 1.8 * steps.min()


def _boxes(ink: np.ndarray, rows: tuple, cols: tuple, along: int, gap: float) -> list:
    """Étiquettes d'une bande : suites d'encre le long de `along` (1 : colonnes, 0 : lignes)."""
    r0, r1 = rows
    c0, c1 = cols
    band = ink[r0:r1 + 1, c0:c1 + 1]
    out = []
    for a, b in _runs(band.any(axis=1 - along), gap=int(gap)):
        sub = band[:, a:b + 1] if along == 1 else band[a:b + 1, :]
        rr = np.flatnonzero(sub.any(axis=1))
        cc = np.flatnonzero(sub.any(axis=0))
        if along == 1:
            out.append((c0 + a, r0 + rr[0], c0 + b, r0 + rr[-1]))
        else:
            out.append((c0 + cc[0], r0 + a, c0 + cc[-1], r0 + b))
    return out


def _band(profile: np.ndarray, start: int, step: int, limit: int, gap: int):
    """Première bande d'encre rencontrée en partant de `start` (pas ±1) : (début, fin) triés."""
    i, first = start, None
    while 0 <= i < len(profile) and abs(i - start) <= limit:
        if profile[i]:
            first = i
            break
        i += step
    if first is None:
        return None
    last, empty = first, 0
    i = first
    while 0 <= i < len(profile):
        if profile[i]:
            last, empty = i, 0
        else:
            empty += 1
            if empty > gap:
                break
        i += step
    return tuple(sorted((first, last)))


def find_plot(image: np.ndarray):
    """Zone de tracé d'une image de graphique, ou None (pas de cadre quadrillé ni de graduations)."""
    gray = np.asarray(image, dtype=float)
    if gray.ndim == 3:
        gray = gray[:, :, :3].mean(axis=2)
    H, W = gray.shape
    line, ink = gray < LINE, gray < INK
    horizontal = _lines(line, SPAN * W)
    vertical = _lines(line.T, SPAN * H)
    if len(horizontal) < 2 or len(vertical) < 2:
        return None
    _, left, right = max(horizontal, key=lambda h: h[2] - h[1])
    rows = [h for h in horizontal if abs(h[1] - left) <= END and abs(h[2] - right) <= END]
    top, bottom = min(r for r, _, _ in rows), max(r for r, _, _ in rows)
    cols = [v for v in vertical if abs(v[1] - top) <= END and abs(v[2] - bottom) <= END
            and left - END <= v[0] <= right + END]
    if len(rows) < 3 or len(cols) < 3 or bottom - top < 0.3 * H or right - left < 0.3 * W:
        return None
    left = min(left, min(c for c, _, _ in cols))
    right = max(right, max(c for c, _, _ in cols))
    l, t, r, b = (int(round(v)) for v in (left, top, right, bottom))
    # graduations X : première bande d'encre sous le cadre (colonnes à partir du bord gauche,
    # pour ne pas prendre le « 0 » de l'axe Y)
    xb = _band(ink[:, max(l - 2, 0):].any(axis=1), b + 3, 1, int(0.12 * H), 2)
    if xb is None:
        return None
    char = xb[1] - xb[0] + 1                  # hauteur des chiffres
    x_labels = [bx for bx in _boxes(ink, xb, (0, W - 1), 1, 0.4 * char) if bx[2] >= l]
    # graduations Y : première bande d'encre à gauche du cadre (lignes jusqu'au bas du cadre)
    # (le titre tourné de l'axe, plus à gauche, est séparé par un blanc d'un quart de chiffre)
    yb = _band(ink[:max(b - 2, 0), :].any(axis=0), l - 3, -1, int(0.15 * W),
               max(2, int(0.25 * char)))
    if yb is None:
        return None
    y_labels = [_extend_left(ink, bx, char)
                for bx in _boxes(ink, (max(t - char, 0), b), yb, 0, 0.4 * char)
                if bx[3] - bx[1] <= 1.6 * char]
    if len(x_labels) < 2 or len(y_labels) < 2:
        return None
    area = PlotArea((l, t, r, b), sorted(c for c, _, _ in cols), sorted(r_ for r_, _, _ in rows),
                    x_labels, y_labels, char=char)
    (xa, ya), _, _ = area.markers()
    nx = area._snap((x_labels[1][0] + x_labels[1][2]) / 2, area.x_grid)
    ny = area._snap(y_labels[-2][1] + (char - 1) / 2, area.y_grid)
    # échelle log : traits secondaires, même partiels (une légende en cache une partie),
    # sauf ceux qui longent un trait noir (bord adouci d'une courbe presque droite)
    area.log_x = _logarithmic(_minor(line.T, ink.T, (t, b), (l, r)), xa, nx)
    area.log_y = _logarithmic(_minor(line, ink, (l, r), (t, b)), ya, ny)
    _read_ticks(area, gray)
    return area


def _extend_left(ink, box, char) -> tuple:
    """
    Étiquette Y prolongée vers la gauche : chiffre séparé par un large blanc (« 1 » d'Arial
    gras : 6 pixels pour 22 de haut), mais pas le titre tourné de l'axe, qui dépasse en
    hauteur.
    """
    x0, y0, x1, y1 = box
    pad = max(int(char / 2), 2)
    x, gap = x0 - 1, 0
    while x >= 0 and gap <= 0.45 * char:
        inside = ink[y0:y1 + 1, x].any()
        outside = ink[max(y0 - pad, 0):y0, x].any() or ink[y1 + 1:y1 + 1 + pad, x].any()
        if inside and outside:
            break
        if inside:
            x0, gap = x, 0
        else:
            gap += 1
        x -= 1
    return x0, y0, x1, y1


def _minor(line, ink, along, across, fraction=0.15) -> list:
    """Traits (même partiels) d'une grille, dans le cadre, hors courbes noires."""
    a0, a1 = along
    black = [p for p, _, _ in _lines(ink, fraction * (a1 - a0))]
    return [p for p, a, z in _lines(line, fraction * (a1 - a0))
            if across[0] < p < across[1] and a >= a0 - END and z <= a1 + END
            and all(abs(p - q) > 4 for q in black)]


# ================================================================ lecture des graduations
FONT_FILES = ("arial.ttf", "arialbd.ttf", "calibri.ttf", "calibrib.ttf", "segoeui.ttf",
              "segoeuib.ttf", "tahoma.ttf", "tahomabd.ttf", "verdana.ttf", "verdanab.ttf",
              "times.ttf", "timesbd.ttf", "DejaVuSans.ttf", "DejaVuSans-Bold.ttf",
              "LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf")
TALL = "0123456789E+"       # caractères comparés aux modèles (les autres : par leur forme)
GLYPH = (14, 20)            # taille commune d'un caractère comparé, pixels
GLYPH_INK = 0.6             # encre (0..1) qui sépare deux caractères


@functools.lru_cache(maxsize=1)
def font_paths() -> tuple:
    """Polices du système (Windows, Linux, macOS), puis celles de matplotlib si présent."""
    folders = [os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
               os.path.expanduser("~/.fonts"), "/Library/Fonts", "/System/Library/Fonts"]
    for root in ("/usr/share/fonts", os.path.expanduser("~/.local/share/fonts")):
        if os.path.isdir(root):
            folders += [d for d, _, _ in os.walk(root)]
    try:
        import matplotlib
        folders.append(os.path.join(matplotlib.get_data_path(), "fonts", "ttf"))
    except ImportError:
        pass
    found, seen = [], set()
    for name in FONT_FILES:
        for folder in folders:
            path = os.path.join(folder, name)
            if name.lower() not in seen and os.path.isfile(path):
                found.append(path)
                seen.add(name.lower())
    return tuple(found)


def _resized(ink: np.ndarray) -> np.ndarray:
    from PIL import Image
    im = Image.fromarray(np.uint8(255 * (1 - ink))).resize(GLYPH, Image.BILINEAR)
    return (1 - np.asarray(im, float) / 255).ravel()


def _crop(ink: np.ndarray):
    rr = np.flatnonzero(ink.max(axis=1) > GLYPH_INK)
    cc = np.flatnonzero(ink.max(axis=0) > GLYPH_INK)
    return ink[rr[0]:rr[-1] + 1, cc[0]:cc[-1] + 1] if len(rr) and len(cc) else None


@functools.lru_cache(maxsize=None)
def _templates(path: str):
    """Caractères TALL d'une police : (noms, encres ramenées à GLYPH, largeur / hauteur)."""
    from PIL import Image, ImageDraw, ImageFont
    try:
        font = ImageFont.truetype(path, 100)
    except OSError:
        return None
    names, inks, ratios = [], [], []
    for c in TALL:
        im = Image.new("L", (240, 240), 255)
        ImageDraw.Draw(im).text((40, 40), c, font=font, fill=0)
        ink = _crop(1 - np.asarray(im, float) / 255)
        if ink is not None:
            names.append(c)
            inks.append(_resized(ink))
            ratios.append(ink.shape[1] / ink.shape[0])
    return names, np.array(inks), np.array(ratios)


def _glyphs(ink: np.ndarray, box, char) -> list:
    """
    Caractères d'une étiquette, de gauche à droite : ("tall", encre, rapport) pour un
    chiffre, une lettre ; « . » (bas, petit), « - » (milieu, large) ; « ? » sinon.
    """
    x0, y0, x1, y1 = box
    y1 = max(y1, int(y0 + char))          # « 0 » du bas de l'axe Y, coupé au bord du cadre
    sub = ink[y0:y1 + 1, x0:x1 + 1]
    out = []
    for a, b in _runs(sub.max(axis=0) > GLYPH_INK, gap=0):
        g = sub[:, a:b + 1]
        rr = np.flatnonzero(g.max(axis=1) > GLYPH_INK)
        g = g[rr[0]:rr[-1] + 1]
        h, w = g.shape
        if h >= 0.45 * char:
            out.append(("tall", _resized(g), w / h))
        elif (rr[0] + rr[-1]) / 2 > 0.7 * char:
            out.append(".")                # point ou virgule décimale, sur la ligne de base
        elif w > 1.3 * h:
            out.append("-")
        else:
            out.append("?")
    return out


def _read(glyphs, font) -> tuple:
    """Textes des étiquettes avec une police, et l'écart total aux modèles."""
    names, inks, ratios = font
    texts, total = [], 0.0
    for label in glyphs:
        text = ""
        for g in label:
            if isinstance(g, str):
                text += g
                continue
            _, ink, ratio = g
            cost = np.abs(inks - ink).mean(axis=1) + 0.3 * np.abs(ratios - ratio)
            k = int(np.argmin(cost))
            text += names[k]
            total += float(cost[k])
        texts.append(text)
    return texts, total


def _value(text: str):
    try:
        return float(text)
    except ValueError:
        return None


def tick_sequence(texts, positions, log=False):
    """
    Suite régulière qui explique le plus de graduations lues : valeur linéaire en position
    (log10 de la valeur sur un axe log). Rend (valeur de la première, de la dernière, log)
    ou None (moins de 70 % des graduations expliquées, ou moins de 3 sur 3 et plus).
    Une extrémité mal lue prend la valeur de la suite : nombre entier de pas depuis une
    graduation bien lue, pas exact tiré des deux bien lues les plus éloignées.
    """
    n = len(texts)
    values = [_value(t) for t in texts]
    if n < 2:
        return None
    spacing = float(np.median(np.abs(np.diff(positions))))
    if spacing <= 0:
        return None
    best = None
    for use_log in (False, True):
        vs = [(math.log10(v) if v is not None and v > 0 else None) if use_log else v
              for v in values]
        for i in range(n):
            for j in range(i + 1, n):
                if vs[i] is None or vs[j] is None or vs[i] == vs[j] \
                        or positions[j] == positions[i]:
                    continue
                slope = (vs[j] - vs[i]) / (positions[j] - positions[i])
                step = slope * spacing
                ok = [k for k in range(n) if vs[k] is not None and
                      abs(vs[i] + slope * (positions[k] - positions[i]) - vs[k]) <= 0.1 * abs(step)]
                key = (len(ok), use_log == log)
                if best is None or key > best[0]:
                    best = (key, use_log, vs, i, slope, step, ok)
    if best is None:
        return None
    (count, _), use_log, vs, i, slope, step, ok = best
    if count < max(2, math.ceil(0.7 * n)) or (n >= 3 and count < 3):
        return None
    a, z = min(ok, key=lambda k: positions[k]), max(ok, key=lambda k: positions[k])
    steps = round((positions[z] - positions[a]) / spacing)
    exact = (vs[z] - vs[a]) / steps if steps else step
    ends = []
    for k in (0, n - 1):
        if k in ok:
            ends.append(values[k])
            continue
        v = vs[a] + round((positions[k] - positions[a]) / spacing) * exact
        ends.append(float(f"{(10 ** v if use_log else v):.10g}"))
    return ends[0], ends[1], use_log


def _read_ticks(area: PlotArea, gray: np.ndarray):
    """Valeurs des graduations : police la plus ressemblante, puis suite régulière."""
    try:
        fonts = [f for f in (_templates(p) for p in font_paths()) if f is not None]
    except ImportError:                    # Pillow absent : saisie par l'utilisateur
        return
    if not fonts:
        return
    ink = np.clip((200.0 - gray) / 140.0, 0.0, 1.0)
    glyphs = [_glyphs(ink, box, area.char) for box in area.x_labels + area.y_labels]
    texts, _ = min((_read(glyphs, f) for f in fonts), key=lambda r: r[1])
    nx = len(area.x_labels)
    area.x_texts, area.y_texts = texts[:nx], texts[nx:]
    x = tick_sequence(area.x_texts, [(b[0] + b[2]) / 2 for b in area.x_labels], area.log_x)
    # Y : étiquettes de haut en bas ; suite prise de bas en haut (première = celle du bas)
    y = tick_sequence(area.y_texts[::-1], [-(b[1] + area.char / 2) for b in area.y_labels[::-1]],
                      area.log_y)
    if x:
        area.x_values, area.log_x = (x[0], x[1]), x[2]
    if y:
        area.y_values, area.log_y = (y[0], y[1]), y[2]
