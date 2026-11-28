# model/scope.py
"""
Capture d'écran d'oscilloscope Tektronix (MSO / MDO, écran sauvegardé en PNG) : formes
d'onde numérisées automatiquement, sans moteur d'OCR (Qt non utilisé).

    capture = read_capture(image)        # image RGB (lignes, colonnes, 3)
    capture.channels                      # [ScopeChannel] : temps (s), valeurs, min, max

Disposition de l'écran (relevée sur les captures du service) :
    - écran cerné d'un cadre orange ; dessous, le panneau des réglages ;
    - grille de 10 × 10 divisions en pointillés ; le bord gauche est un trait continu, un
      tronçon par grille : capture zoomée = deux grilles, la vue complète en haut (petite,
      ignorée) et la vue zoomée en bas (la plus haute : celle qui est numérisée) ;
    - zéro de chaque voie : pastille ronde numérotée à gauche de la grille, flèche vers
      la grille ; une pastille peut en cacher une autre (même niveau) ;
    - déclenchement (t = 0) : repère orange ▼ au bord haut de la grille ;
    - panneau : échelles verticales derrière une pastille colorée (« C1 » 200V/div ; en
      zoom « Z1C1 » 200V 10.0µs −38.0µs 62.0µs : échelle, base de temps et bornes de la
      vue zoomée), base de temps « 100µs/div », curseurs (V1, V2), table des mesures
      (« C4 High 11.6a ») : celle-ci sert de contrôle (et à trouver un zéro caché).
Couleurs des voies : CH1 jaune, CH2 cyan, CH3 magenta, CH4 vert (REF pastel, MATH vives :
plus tard). Points en pixels de l'image, comme le reste de l'application.
"""
import re
from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage

from . import labelread

DIVISIONS = 10                      # divisions de la grille, en largeur et en hauteur
ORANGE = (208, 112, 16)             # cadre de l'écran, repère de déclenchement
CHANNEL_COLORS = {"CH1": (240, 240, 16), "CH2": (16, 240, 240), "CH3": (240, 16, 240),
                  "CH4": (16, 240, 16)}
COLOR_TOLERANCE = 70                # écart maximal (par composante) à la couleur d'une voie
UNIT_NAMES = {"v": "V", "a": "A"}   # le Tektronix écrit « 5.0v/div », « 5.0a/div »
PREFIX = {"": 1.0, "m": 1e-3, "µ": 1e-6, "u": 1e-6, "n": 1e-9, "p": 1e-12, "k": 1e3,
          "M": 1e6, "G": 1e9}

# vocabulaire du panneau (lecture des mots par labelread)
_UNITS = ("V/div", "v/div", "mV/div", "mv/div", "A/div", "a/div", "mA/div", "ma/div",
          "s/div", "ms/div", "µs/div", "ns/div", "MS/s", "GS/s", "kS/s", "ns/pt", "ps/pt",
          "µs/pt", "V", "v", "mV", "mv", "kV", "A", "a", "mA", "ma", "s", "ms", "µs", "ns",
          "Hz", "kHz", "MHz", "%", "M", "k", "V/s", "kV/s", "MV/s", "A/s", "kA/s", "MA/s")
_NAMES = tuple(f"{k}{i}" for k in "CRM" for i in range(1, 5)) + tuple(
    f"Z1{k}{i}" for k in "CRM" for i in range(1, 5)) + (
    "High", "Low", "Max", "Min", "Mean", "Value", "Count", "Info", "Stopped", "Auto", "Run",
    "StDev", "Pk-Pk", "RMS", "Freq", "Period", "Rise", "Fall", "Amplitude", "acqs", "1MΩ",
    "50Ω", "V1", "V2", "ΔV", "t1", "t2", "Δt", "a", "b", "Single", "Seq", "Preview")
VOCABULARY = labelread.Vocabulary(_NAMES, _UNITS, ())
QUANTITY = re.compile(r"^([−-]?\d+(?:[.,]\d+)?)\s*([pnuµmkMG]?)([A-Za-zΩ]+)(/div|/s|/pt)?$")
# base de temps dans un mot, même collé au suivant (« 50.0µs/div500MS/s »)
TIMEBASE = re.compile(r"(\d+(?:[.,]\d+)?)([pnuµm]?)s/div")


@dataclass
class Graticule:
    x0: float                          # bords de la grille, pixels
    y0: float
    x1: float
    y1: float

    @property
    def div_x(self) -> float:
        return (self.x1 - self.x0) / DIVISIONS

    @property
    def div_y(self) -> float:
        return (self.y1 - self.y0) / DIVISIONS


@dataclass
class PanelWord:
    text: str
    box: tuple                         # (x0, y0, x1, y1), pixels


@dataclass
class ScopeChannel:
    name: str                          # « CH1 »…
    color: tuple
    scale: float | None = None         # unités par division
    unit: str = ""                     # « V », « A »
    zero_y: float | None = None        # ligne du zéro, pixels
    div_y: float = 1.0                 # hauteur d'une division, pixels
    pixels: np.ndarray = field(default_factory=lambda: np.empty((0, 2)))  # médiane par colonne
    top: np.ndarray = field(default_factory=lambda: np.empty(0))     # bande : haut, bas (pixels)
    bottom: np.ndarray = field(default_factory=lambda: np.empty(0))
    warnings: list = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return self.scale is not None and self.zero_y is not None and len(self.pixels) > 1

    def values(self, y) -> np.ndarray:
        """Ordonnées (pixels) -> valeurs dans l'unité de la voie."""
        return (self.zero_y - np.asarray(y, float)) * self.scale / self.div_y

    def pixel_of(self, value) -> float:
        """Valeur -> ordonnée (pixels)."""
        return self.zero_y - value / self.scale * self.div_y


@dataclass
class ScopeCapture:
    graticule: Graticule
    zoomed: bool = False
    time_per_div: float | None = None  # s / division de la vue numérisée
    t0_x: float | None = None          # abscisse de t = 0 (pixels)
    channels: list = field(default_factory=list)
    measurements: list = field(default_factory=list)   # (voie, grandeur, valeur, unité)
    cursors: list = field(default_factory=list)        # (voie, valeur, unité), de haut en bas
    zoom_window: tuple | None = None   # (début, fin) en s de la vue zoomée
    words: list = field(default_factory=list)          # mots lus du panneau
    warnings: list = field(default_factory=list)

    def times(self, x) -> np.ndarray:
        """Abscisses (pixels) -> temps (s) ; en divisions si la base de temps est inconnue."""
        per_div = self.time_per_div if self.time_per_div else 1.0
        return (np.asarray(x, float) - self.t0_x) * per_div / self.graticule.div_x


# ================================================================ quantités lues
def parse_quantity(text: str):
    """« 200V/div » -> (200.0, « V », « /div ») ; « 10.0µs » -> (1e-05, « s », « ») ; None."""
    m = QUANTITY.match((text or "").strip())
    if not m:
        return None
    number, prefix, unit, per = m.groups()
    unit = UNIT_NAMES.get(unit, unit)
    if unit in ("mv", "ma"):
        prefix, unit = "m", unit[1].upper()
    value = float(number.replace("−", "-").replace(",", ".")) * PREFIX.get(prefix, 1.0)
    return value, unit, per or ""


# ================================================================ disposition
def _color_mask(rgb, color, tolerance=COLOR_TOLERANCE) -> np.ndarray:
    return (np.abs(rgb.astype(np.int16) - np.array(color, np.int16)).max(axis=2) <= tolerance)


def _hue(rgb):
    """(teinte en degrés, saturation 0..1, valeur 0..1) de chaque pixel."""
    a = rgb[:, :, :3].astype(np.float32) / 255.0
    mx, mn = a.max(axis=2), a.min(axis=2)
    delta = mx - mn
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    safe = np.where(delta > 0, delta, 1.0)
    hue = np.where(mx == r, ((g - b) / safe) % 6, np.where(mx == g, (b - r) / safe + 2,
                                                         (r - g) / safe + 4)) * 60.0
    sat = np.where(mx > 0, delta / np.where(mx > 0, mx, 1.0), 0.0)
    return hue, sat, mx


HUES = {"CH1": 60.0, "CH2": 180.0, "CH3": 300.0, "CH4": 120.0}   # jaune, cyan, magenta, vert
# tolérance de teinte : le jaune est serré (l'orange vif du repère de déclenchement est à 39°)
HUE_TOLERANCE = {"CH1": 15.0, "CH2": 22.0, "CH3": 22.0, "CH4": 22.0}


def channel_masks(rgb, hsv=None, min_sat=0.55, min_val=0.35) -> dict:
    """Pixels de chaque voie, par leur teinte (couleurs vives, dégradés compris)."""
    hue, sat, val = hsv if hsv is not None else _hue(rgb)
    vivid = (sat >= min_sat) & (val >= min_val)
    out = {}
    for name, h in HUES.items():
        d = np.abs((hue - h + 180.0) % 360.0 - 180.0)
        out[name] = vivid & (d <= HUE_TOLERANCE[name])
    return out


def _runs(flags) -> list:
    idx = np.flatnonzero(flags)
    if not len(idx):
        return []
    cuts = np.flatnonzero(np.diff(idx) > 1)
    return list(zip(idx[np.r_[0, cuts + 1]].tolist(), idx[np.r_[cuts, len(idx) - 1]].tolist()))


def screen_box(rgb) -> tuple:
    """Écran : intérieur du cadre orange (x0, y0, x1, y1) ; image entière sans cadre."""
    H, W = rgb.shape[:2]
    orange = _color_mask(rgb, ORANGE, 40)
    rows = [r for r, c in enumerate(orange.sum(axis=1)) if c > 0.8 * W]
    cols = [c for c, n in enumerate(orange.sum(axis=0)) if n > 0.5 * H]
    if len(rows) < 2 or len(cols) < 2:
        return 0, 0, W - 1, H - 1
    top = min(rows)
    bottom = min((r for r in rows if r > top + 0.3 * H), default=max(rows))
    return min(cols), top, max(cols), bottom


def _full_rows(neutral, fraction=0.9) -> list:
    """Lignes de gris presque pleine largeur (bords hauts, lignes centrales) ; voisines réunies."""
    rows = np.flatnonzero(neutral.sum(axis=1) >= fraction * neutral.shape[1])
    return [float(np.mean(r)) for r in np.split(rows, np.flatnonzero(np.diff(rows) > 1) + 1)
            if len(r)]


def find_graticules(rgb, screen) -> list:
    """
    Grilles de l'écran, de haut en bas. Un bord haut et la ligne centrale (traits gris
    pleine largeur) distants de 5 divisions donnent une grille de 10 divisions ; les
    lignes de division en pointillés la confirment. Le bord bas peut être caché (cadre).
    Bords gauche et droit : colonnes les plus fournies en gris aux deux extrémités.
    """
    sx0, sy0, sx1, sy1 = screen
    sub = rgb[sy0:sy1 + 1, sx0:sx1 + 1].astype(np.int16)
    sat = sub.max(axis=2) - sub.min(axis=2)
    gray = sub.mean(axis=2)
    neutral = (sat < 40) & (gray > 25) & (gray < 200)
    H, W = neutral.shape
    cols = neutral.sum(axis=0)
    left = int(np.argmax(cols[:W // 4]))
    right = W - W // 4 + int(np.argmax(cols[W - W // 4:]))
    full = _full_rows(neutral[:, left:right + 1])
    counts = neutral[:, left:right + 1].sum(axis=1)
    found = []
    for i, top in enumerate(full):
        for center in full[i + 1:]:
            div = (center - top) / 5
            bottom = center + 5 * div
            if div < 4 or bottom > H + 2:
                continue
            # lignes de division (pointillés) aux positions attendues
            rows = [int(round(top + k * div)) for k in range(1, 10) if k != 5]
            dotted = sum(counts[max(r - 1, 0):r + 2].max() >= 0.04 * (right - left)
                         for r in rows if r < H)
            if dotted >= 6:
                found.append((top, bottom))
                break
    out, last = [], -1.0
    for top, bottom in sorted(found):
        if top >= last - 1:                 # grilles disjointes, de haut en bas
            out.append(Graticule(sx0 + left, sy0 + top, sx0 + right, sy0 + bottom))
            last = bottom
    return out


# ================================================================ panneau
def _long_runs(mask, n) -> np.ndarray:
    """Pixels appartenant à une suite horizontale de plus de n pixels (traits d'encadrés)."""
    m = np.asarray(mask, bool)
    padded = np.zeros((m.shape[0], m.shape[1] + 2), np.int8)
    padded[:, 1:-1] = m
    step = np.diff(padded, axis=1)
    rows, starts = np.nonzero(step == 1)
    _, ends = np.nonzero(step == -1)
    out = np.zeros_like(m)
    for r, a, b in zip(rows, starts, ends):
        if b - a > n:
            out[r, a:b] = True
    return out


def _panel_text(rgb, top: int) -> tuple:
    """(texte clair du panneau sans les traits d'encadrés, gris où ces traits sont effacés)."""
    a = rgb.astype(np.int16)
    gray = a.mean(axis=2)
    sat = a.max(axis=2) - a.min(axis=2)
    text = (gray > 150) & (sat < 60)
    text[:top] = False
    lines = _long_runs(text, 30) | _long_runs(text.T, 18).T
    text &= ~lines
    clean = gray.copy()
    clean[lines] = 0
    return text, clean


def panel_gray(rgb, top: int) -> np.ndarray:
    """Gris du panneau, traits d'encadrés effacés (à inverser pour la lecture)."""
    return _panel_text(rgb, top)[1]


_FONT = None


def tektronix_font():
    """Police de l'écran Tektronix relevée sur des captures (ressources/fonts), ou None."""
    global _FONT
    if _FONT is None:
        import pathlib
        path = pathlib.Path(__file__).resolve().parents[1] / "ressources" / "fonts" / "tektronix.npz"
        try:
            data = np.load(path)
            _FONT = ([str(c) for c in data["names"]], data["inks"], data["ratios"], data["heights"])
        except (OSError, KeyError):
            _FONT = False
    return _FONT or None


def panel_reader(rgb, top: int):
    """Lecteur du panneau : police Tektronix d'abord, polices du système ensuite."""
    font = tektronix_font()
    fonts = ([font] if font else []) + labelread.fonts()
    reader = labelread.Reader(255 - panel_gray(rgb, top), VOCABULARY, fonts)
    if font:
        reader.font = font                 # la police de l'écran, toujours la même
    return reader


def read_panel(rgb, top: int, reader=None) -> list:
    """
    Mots clairs du panneau (sous l'écran) : traits d'encadrés effacés, lignes de texte,
    mots séparés par un blanc ; lus par labelread (police la plus ressemblante,
    vocabulaire de l'oscilloscope). Rend [PanelWord] (mots illisibles omis).
    """
    text, _ = _panel_text(rgb, top)
    if reader is None:
        reader = panel_reader(rgb, top)
    out = []
    rows = np.flatnonzero(text.any(axis=1))
    for band in np.split(rows, np.flatnonzero(np.diff(rows) > 1) + 1) if len(rows) else []:
        if len(band) < 6:
            continue
        y0, y1 = int(band[0]), int(band[-1])
        cols = np.flatnonzero(text[y0:y1 + 1].any(axis=0))
        h = y1 - y0 + 1
        for w in np.split(cols, np.flatnonzero(np.diff(cols) > max(3, 0.45 * h)) + 1):
            box = (int(w[0]) - 2, y0 - 2, int(w[-1]) + 3, y1 + 3)
            word = reader.read(box)
            if word is not None:
                out.append(PanelWord(word.text, box))
    return out


def find_badges(rgb, top: int) -> list:
    """
    Pastilles colorées du panneau (« C1 », « Z1C1 »…) : (voie, boîte, zoom), zoom quand la
    pastille est nettement plus large (« Z1C1 »).
    """
    out = []
    for name, mask in channel_masks(rgb).items():
        mask[:top] = False
        mask = ndimage.binary_closing(mask, np.ones((3, 3), bool))  # texte noir dans la pastille
        labels, n = ndimage.label(mask)
        for sl in ndimage.find_objects(labels):
            h = sl[0].stop - sl[0].start
            w = sl[1].stop - sl[1].start
            if 8 <= h <= 20 and 1.4 * h <= w <= 5 * h:
                out.append((name, (sl[1].start, sl[0].start, sl[1].stop, sl[0].stop), w > 2.6 * h))
    return sorted(out, key=lambda t: (t[1][1], t[1][0]))


ROW_GAP = 90         # blanc (pixels) qui termine la ligne d'une pastille (cadre voisin)


def _row_words(words, badge_box, next_x) -> list:
    """
    Mots de la ligne d'une pastille, à sa droite, avant la pastille suivante et avant le
    premier grand blanc (le cadre voisin du panneau commence après).
    """
    x0, y0, x1, y1 = badge_box
    cy = (y0 + y1) / 2
    # un mot collé à la pastille commence sur elle (« C1 400V/div ») : il la dépasse
    row = sorted((w for w in words if w.box[1] <= cy <= w.box[3] and w.box[2] > x1 + 2
                  and x0 - 3 <= w.box[0] < next_x), key=lambda w: w.box[0])
    out, last = [], x1
    for w in row:
        if w.box[0] - last > ROW_GAP:
            break
        out.append(w)
        last = w.box[2]
    return out


# ================================================================ lecture complète
MEASURES = ("High", "Low", "Max", "Min", "Mean", "Pk-Pk", "RMS", "Amplitude")
STEPS = (1.0, 2.0, 2.5, 4.0, 5.0)          # suites de réglages d'un oscilloscope (1-2-4-5)


def _standard(value) -> bool:
    """Réglage plausible : mantisse 1, 2, 2,5, 4 ou 5 (×10^n)."""
    if not value or value <= 0:
        return False
    mantissa = value / 10 ** np.floor(np.log10(value))
    return any(abs(mantissa - s) < 0.02 for s in STEPS) or abs(mantissa - 10) < 0.2


def _rows(words, badges) -> list:
    """Lignes du panneau : (voie, boîte de la pastille, textes à sa droite)."""
    out = []
    for name, box, _ in badges:
        same = [b[1][0] for b in badges if abs(b[1][1] - box[1]) < 5 and b[1][0] > box[0]]
        next_x = min(same + [10 ** 6])
        out.append((name, box, [w.text for w in _row_words(words, box, next_x)]))
    return out


def _zero_badges(masks, graticule, screen) -> dict:
    """
    Pastilles de zéro au bord gauche de la grille : voie -> ordonnée de leur centre. Une
    pastille cachée par une autre (même niveau) n'est pas trouvée ici.
    """
    out = {}
    x0 = 0                                  # pastilles dessinées sur la bande à gauche du cadre
    x1 = int(graticule.x0) + 1
    y0, y1 = max(int(graticule.y0) - 8, 0), int(graticule.y1) + 8
    for name, mask in masks.items():
        labels, _ = ndimage.label(mask[y0:y1, x0:x1])
        best = None
        for k, sl in enumerate(ndimage.find_objects(labels)):
            h, w = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
            fill = (labels[sl] == k + 1).sum() / (h * w)
            # pastille pleine (pas l'anneau orangé de la voie sélectionnée)
            if h >= 8 and w >= 6 and fill >= 0.45 and (best is None or h * w > best[0]):
                best = (h * w, (sl[0].start + sl[0].stop - 1) / 2 + y0)
        if best is not None:
            out[name] = best[1]
    return out


def _trigger_x(rgb, graticule):
    """Repère orange ▼ du déclenchement au bord haut de la grille : son abscisse, ou None."""
    hue, sat, val = _hue(rgb)
    orange = (np.abs(hue - 35.0) <= 15.0) & (sat >= 0.6) & (val >= 0.6)
    y0 = int(graticule.y0)
    x0 = int(graticule.x0) + 2
    band = orange[max(y0 - 2, 0):y0 + 12, x0:int(graticule.x1) - 1].copy()
    band[band.sum(axis=1) >= 0.5 * band.shape[1]] = False          # le cadre de l'écran
    cols = np.flatnonzero(band.sum(axis=0) >= 3)
    if not len(cols):
        return None
    groups = np.split(cols, np.flatnonzero(np.diff(cols) > 2) + 1)
    widest = max(groups, key=len)
    return float(np.mean(widest)) + x0


JOIN_GAP = 4         # trou comblé dans une tache verticale (une autre voie qui la croise)
STUCK = 3            # colonnes rejetées de suite : une tache lointaine est acceptée…
LONG = 0.5           # … si elle appartient à un morceau d'encre large d'une demi-division au
                     # moins (un tronçon de tracé, pas une étiquette ni un repère)
JUMP = 0.5           # saut maximal (divisions) vers une petite tache isolée


def _column_runs(column) -> list:
    """Taches verticales d'une colonne (trous de JOIN_GAP pixels comblés) : [(haut, bas)]."""
    idx = np.flatnonzero(column)
    if not len(idx):
        return []
    cuts = np.flatnonzero(np.diff(idx) > JOIN_GAP + 1)
    return list(zip(idx[np.r_[0, cuts + 1]].tolist(), idx[np.r_[cuts, len(idx) - 1]].tolist()))


def _without_vertical_cursors(sub) -> np.ndarray:
    """
    Curseurs verticaux (t1, t2 : traits pleins ou pointillés sur presque toute la hauteur) :
    colonne remplie sur plus de 60 % de la hauteur, ses voisines à deux pixels peu remplies.
    """
    counts = sub.sum(axis=0)
    H = sub.shape[0]
    left = np.r_[np.zeros(2), counts[:-2]]
    right = np.r_[counts[2:], np.zeros(2)]
    cursor = (counts > 0.35 * H) & (left < 0.1 * H) & (right < 0.1 * H)
    if not cursor.any():
        return sub
    out = sub.copy()
    for c in np.flatnonzero(cursor):
        out[:, max(c - 1, 0):c + 2] = False
    return out


def _trace(mask, graticule, exclude) -> tuple:
    """
    Tracé d'une voie, colonne par colonne de la grille : parmi les taches verticales de sa
    couleur, celle qui prolonge la colonne précédente (une étiquette, un repère de bord, la
    flèche du niveau de déclenchement sont des taches à l'écart ; une rafale de bruit part
    du tracé). Rend (pixels (x, médiane), haut, bas) ; colonnes sans tache retenue omises.
    """
    x0, y0 = int(np.ceil(graticule.x0)) + 2, int(np.ceil(graticule.y0)) + 2
    x1, y1 = int(graticule.x1) - 1, int(graticule.y1) - 1
    sub = mask[y0:y1, x0:x1] & ~exclude[y0:y1, x0:x1]
    sub = _without_vertical_cursors(sub)
    runs = [_column_runs(sub[:, c]) for c in range(sub.shape[1])]
    pieces, _ = ndimage.label(sub, structure=np.ones((3, 3)))
    widths = np.zeros(pieces.max() + 1)
    for k, sl in enumerate(ndimage.find_objects(pieces)):
        widths[k + 1] = sl[1].stop - sl[1].start
    long_enough = LONG * graticule.div_x
    single = [c for c, r in enumerate(runs) if len(r) == 1]
    if not single:
        single = [c for c, r in enumerate(runs) if r]
    if not single:
        return np.empty((0, 2)), np.empty(0), np.empty(0)
    # départ : la plus longue suite de colonnes à une seule tache (le tracé seul)
    start = max(np.split(np.array(single), np.flatnonzero(np.diff(single) > 1) + 1), key=len)
    start = int(start[len(start) // 2])
    jump = JUMP * graticule.div_y
    chosen = {}

    def pick(c, previous, stuck):
        # écart à la tache retenue dans la colonne précédente (tout son haut et son bas :
        # après un front vertical, le palier suivant touche le bout du front)
        pa, pb = previous
        best = None
        for a, b in runs[c]:
            d = max(a - pb, pa - b, 0)
            if best is None or d < best[0]:
                best = (d, a, b)
        if best is None:
            return None
        d, a, b = best
        if d <= jump:
            return a, b
        # tache éloignée : le tracé revient après un passage caché, sur un tronçon long ;
        # une étiquette, un repère lointain sont de petits morceaux
        if stuck >= STUCK:
            piece = pieces[a:b + 1, c].max()
            if widths[piece] >= long_enough:
                return a, b
        return None

    for direction in (1, -1):
        previous = None
        stuck = 0
        c = start
        while 0 <= c < len(runs):
            if previous is None:
                a, b = max(runs[c], key=lambda r: r[1] - r[0])
                found = (a, b)
            else:
                found = pick(c, previous, stuck)
                stuck = stuck + 1 if found is None and runs[c] else 0
            if found is not None:
                a, b = found
                column = np.flatnonzero(sub[a:b + 1, c]) + a
                median = float(np.median(column))
                chosen[c] = (median, float(a), float(b))
                previous = (a, b)
            c += direction
    cols = np.array(sorted(chosen))
    med = np.array([chosen[c][0] for c in cols])
    top = np.array([chosen[c][1] for c in cols])
    bottom = np.array([chosen[c][2] for c in cols])
    pixels = np.column_stack([cols + x0, med + y0]).astype(float)
    return pixels, top + y0, bottom + y0


def _measure(channel, kind):
    """Grandeur de la table des mesures, recalculée sur le tracé numérisé (None si inconnue)."""
    if not channel.ready:
        return None
    median = channel.values(channel.pixels[:, 1])
    if kind == "Max":
        return float(channel.values(channel.top).max())
    if kind == "Min":
        return float(channel.values(channel.bottom).min())
    if kind in ("High", "Low"):
        # niveau haut / bas : valeur la plus fréquente de la moitié haute / basse
        mid = 0.5 * (median.max() + median.min())
        part = median[median >= mid] if kind == "High" else median[median <= mid]
        if not len(part):
            return None
        hist, edges = np.histogram(part, bins=50)
        k = int(np.argmax(hist))
        return float(0.5 * (edges[k] + edges[k + 1]))
    if kind == "Mean":
        return float(np.mean(median))
    if kind == "Pk-Pk":
        return float(channel.values(channel.top).max() - channel.values(channel.bottom).min())
    return None


LABEL_HEIGHT = 18     # hauteur maximale d'une étiquette écrite dans la grille (pixels)


def _without_text(mask, graticule) -> np.ndarray:
    """
    Noms de voies écrits dans la grille (« Stage », « Current »…) retirés du masque d'une
    couleur. La police de l'écran est grasse et serrée : les lettres d'un mot se touchent.
    Une petite tache basse (au plus LABEL_HEIGHT), dont les lignes croisent en moyenne au
    moins deux traits (des lettres), et isolée (aucun autre pixel de la couleur à moins de
    4 pixels) est une étiquette ; un tronçon de tracé bruité, lui, touche ses voisins.
    """
    out = np.zeros_like(mask)
    x0, y0, x1, y1 = (int(v) for v in (graticule.x0, graticule.y0, graticule.x1, graticule.y1))
    sub = mask[y0:y1 + 1, x0:x1 + 1].copy()
    labels, _ = ndimage.label(sub, structure=np.ones((3, 3)))
    H, W = sub.shape
    for k, sl in enumerate(ndimage.find_objects(labels)):
        h, w = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        if not (6 <= h <= LABEL_HEIGHT and 5 <= w <= 300):
            continue
        piece = labels[sl] == k + 1
        padded = np.zeros((h, w + 2), np.int8)
        padded[:, 1:-1] = piece
        crossings = (np.diff(padded, axis=1) == 1).sum(axis=1)
        if crossings[crossings > 0].mean() < 1.8:
            continue
        r0, r1 = max(sl[0].start - 4, 0), min(sl[0].stop + 4, H)
        c0, c1 = max(sl[1].start - 4, 0), min(sl[1].stop + 4, W)
        around = labels[r0:r1, c0:c1]
        if np.any((around > 0) & (around != k + 1)):
            continue                        # touche d'autres pixels : un tronçon de tracé
        sub[sl] &= ~piece
    out[y0:y1 + 1, x0:x1 + 1] = sub
    return out


def _cursor_rows(capture, channel, shape) -> np.ndarray:
    """
    Traits des curseurs de cette voie (valeurs lues, dans sa couleur), à ignorer :
    horizontaux pour les niveaux (V1, V2), verticaux pour les temps (t1, t2).
    """
    out = np.zeros(shape[:2], bool)
    g = capture.graticule
    for name, value, unit in capture.cursors:
        if name != channel.name:
            continue
        if unit == "s" and capture.time_per_div and capture.t0_x is not None:
            x = int(round(capture.t0_x + value / capture.time_per_div * g.div_x))
            if g.x0 <= x <= g.x1:
                out[:, max(x - 2, 0):x + 3] = True
        elif unit == channel.unit and channel.zero_y is not None and channel.scale:
            y = int(round(channel.pixel_of(value)))
            out[max(y - 1, 0):y + 2, :] = True
    return out


def _hidden_zero(channel, zeros, capture):
    """
    Zéro caché sous la pastille d'une autre voie : la pastille visible qui explique le mieux
    la mesure de la table, sinon la plus proche du début du tracé ; signalé.
    """
    candidates = sorted(set(zeros.values()))
    if not candidates:
        channel.warnings.append("zéro introuvable : à saisir")
        return
    measures = [(k, v) for n, k, v, _ in capture.measurements if n == channel.name]
    best = None
    for y in candidates:
        channel.zero_y = y
        if measures:
            score = max(abs((_measure(channel, k) or np.inf) - v) for k, v in measures)
        else:
            # le niveau où le tracé passe le plus de temps (un signal de puissance reste
            # souvent à zéro avant ou après la commutation)
            score = -float(np.sum(np.abs(channel.pixels[:, 1] - y) <= 3)) if len(
                channel.pixels) else 0.0
        if best is None or score < best[0]:
            best = (score, y)
    channel.zero_y = best[1]
    how = "d'après la table des mesures" if measures else "d'après le niveau le plus fréquent"
    channel.warnings.append(f"zéro caché sous une autre pastille, pris à y = {best[1]:.0f} "
                            f"({how}) : à vérifier")


def _zoom_axis(capture, zoom_rows):
    """Vue zoomée : base de temps et bornes lues (« 10.0µs −38.0µs 62.0µs »), cohérence."""
    triples = [tuple(t[0] for t in times[-3:]) for _, times in zoom_rows.values()]
    g = capture.graticule
    if not triples:
        capture.warnings.append("réglages de la vue zoomée non lus : à saisir")
        capture.t0_x = g.x0
        return
    tdiv, start, end = max(set(triples), key=triples.count)     # le plus fréquent (une par voie)
    if abs(start + DIVISIONS * tdiv - end) > 0.02 * abs(DIVISIONS * tdiv):
        # une des trois lectures est fausse : la base de temps est un réglage standard
        if _standard(tdiv):
            end = start + DIVISIONS * tdiv
        else:
            tdiv = (end - start) / DIVISIONS
        capture.warnings.append("réglages de la vue zoomée incohérents, corrigés : à vérifier")
    capture.time_per_div = tdiv
    capture.zoom_window = (start, end)
    capture.t0_x = g.x0 - start / tdiv * g.div_x


def _check(capture, channels):
    """Mesures de la table recalculées sur les tracés : écart signalé au-delà de 3 % d'écran."""
    for name, kind, value, unit in capture.measurements:
        ch = channels.get(name)
        if ch is None or not ch.ready:
            continue
        got = _measure(ch, kind)
        if got is None:
            continue
        if abs(got - value) > 0.03 * DIVISIONS * ch.scale:
            ch.warnings.append(f"{kind} relevé {got:.4g} {unit} pour {value:g} {unit} lu à "
                               "l'écran : à vérifier")


def read_capture(image) -> ScopeCapture:
    """
    Capture d'écran Tektronix -> ScopeCapture : grille (la vue zoomée si deux grilles),
    échelles et zéros des voies, axe des temps, tracés, mesures (contrôle), avertissements.
    ValueError si aucune grille n'est trouvée.
    """
    rgb = np.ascontiguousarray(np.asarray(image)[:, :, :3])
    screen = screen_box(rgb)
    graticules = find_graticules(rgb, screen)
    if not graticules:
        raise ValueError("grille de l'oscilloscope introuvable")
    graticule = max(graticules, key=lambda g: g.y1 - g.y0)
    capture = ScopeCapture(graticule, zoomed=len(graticules) > 1)
    top = int(screen[3]) + 2
    words = read_panel(rgb, top)
    capture.words = words
    badges = find_badges(rgb, top)
    masks = channel_masks(rgb)
    channels, zoom_rows = {}, {}
    half = rgb.shape[1] / 2
    for name, box, texts in _rows(words, badges):
        quantities = [q for q in (parse_quantity(t) for t in texts) if q is not None]
        kinds = [t for t in texts if t in MEASURES]
        per_div = [q for q in quantities if q[2] == "/div" and q[1] != "s"]
        times = [q for q in quantities if q[1] == "s" and not q[2]]
        if kinds and quantities:          # « C4 High 11.6a … » (colonnes de statistiques)
            capture.measurements.append((name, kinds[0], quantities[0][0], quantities[0][1]))
        elif per_div and box[0] < half:   # « C1 200V/div 1MΩ … »
            ch = channels.setdefault(name, ScopeChannel(name, CHANNEL_COLORS[name]))
            ch.scale, ch.unit = per_div[0][0], per_div[0][1]
        elif len(times) >= 3:             # « Z1C1 200V 10.0µs −38.0µs 62.0µs »
            zoom_rows[name] = (quantities, times)
        elif len(quantities) == 1 and not per_div:   # curseur « V1 830.16V »
            capture.cursors.append((name, quantities[0][0], quantities[0][1]))
    # base de temps : mot « …s/div » (cadre de droite)
    tdivs = [m for m in (TIMEBASE.search(w.text) for w in words) if m]
    capture.time_per_div = (float(tdivs[0].group(1).replace(",", ".")) * PREFIX[tdivs[0].group(2)]
                            if tdivs else None)
    if capture.zoomed:
        _zoom_axis(capture, zoom_rows)
        for name, (quantities, _) in zoom_rows.items():
            scale = [q for q in quantities if q[1] != "s"]
            if scale and name in channels:
                channels[name].scale = scale[0][0]    # échelle de la vue zoomée
    else:
        capture.t0_x = _trigger_x(rgb, graticule)
        if capture.t0_x is None:
            capture.warnings.append("repère de déclenchement introuvable : t = 0 au bord gauche")
            capture.t0_x = graticule.x0
    if capture.time_per_div is None:
        capture.warnings.append("base de temps non lue : à saisir")
    # zéros, puis tracés (sans les pastilles de zéro, les noms de voies, les curseurs)
    zeros = _zero_badges(masks, graticule, screen)
    exclude = np.zeros(rgb.shape[:2], bool)
    trigger = _trigger_x(rgb, graticule)
    if trigger is not None:                 # repère ▼ du déclenchement
        y0 = int(graticule.y0)
        exclude[max(y0 - 2, 0):y0 + 14, max(int(trigger) - 10, 0):int(trigger) + 11] = True
    for y in zeros.values():
        exclude[max(int(y) - 9, 0):int(y) + 10, :int(graticule.x0) + 18] = True
    # flèches du niveau de déclenchement (◂ au bord droit de la grille) : taches compactes
    x1 = int(graticule.x1)
    for mask in masks.values():
        # la flèche (et sa queue) tient dans les 40 derniers pixels ; un tracé se prolonge
        # au-delà, vers la gauche
        strip = mask[:, x1 - 40:x1 + 3]
        labels, _ = ndimage.label(strip, structure=np.ones((3, 3)))
        for sl in ndimage.find_objects(labels):
            if sl[0].stop - sl[0].start >= 6 and sl[1].start > 0 and sl[1].stop > 30:
                exclude[max(sl[0].start - 2, 0):sl[0].stop + 2,
                        x1 - 40 + sl[1].start:x1 + 3] = True
    hidden = []
    for name, ch in channels.items():
        ch.div_y = graticule.div_y
        ch.zero_y = zeros.get(name)
        if ch.zero_y is None:
            hidden.append(ch)
    for ch in hidden:                       # zéro caché : d'abord un tracé provisoire
        ch.pixels, ch.top, ch.bottom = _trace(_without_text(masks[ch.name], graticule),
                                              graticule, exclude)
        _hidden_zero(ch, zeros, capture)
    for ch in channels.values():
        mask = _without_text(masks[ch.name], graticule) & ~_cursor_rows(capture, ch, rgb.shape)
        ch.pixels, ch.top, ch.bottom = _trace(mask, graticule, exclude)
        if not len(ch.pixels):
            ch.warnings.append("aucun tracé de cette couleur dans la grille")
        else:
            seen = len(ch.pixels) / max(graticule.x1 - graticule.x0 - 3, 1)
            if seen < 0.8:                  # une autre voie dessinée par-dessus
                ch.warnings.append(f"tracé visible sur {100 * seen:.0f} % de la largeur "
                                   "(caché ailleurs par une autre voie) : trous laissés")
    _check(capture, channels)
    capture.channels = [channels[n] for n in sorted(channels)]
    return capture


# ================================================================ composant
def channel_calibration(capture: ScopeCapture, channel: ScopeChannel):
    """
    Calibration orthonormée d'une voie : X = temps (bords de la grille), Y = valeur (zéro de
    la voie, 5 divisions au-dessus, ou en dessous si le zéro est haut dans la grille).
    """
    from .calibration import AxisCalibration, to_four_points
    g = capture.graticule
    zero = channel.zero_y
    step = 5 * g.div_y if zero - 5 * g.div_y >= g.y0 - 1 else -5 * g.div_y
    origin, x2, y2 = (g.x0, zero), (g.x1, zero), (g.x0, zero - step)
    t0, t1 = (float(v) for v in capture.times([g.x0, g.x1]))
    return AxisCalibration(*to_four_points(origin, x2, y2), x1=t0, x2=t1, y1=0.0,
                           y2=float(channel.scale * step / g.div_y))


def to_component(capture: ScopeCapture, image, name: str = "Capture d'oscilloscope",
                 source: str = "", choose=None, labels=None) -> tuple:
    """
    Capture lue -> (Component, avertissements) : un graphique par voie, sur la même image,
    chacun calibré (temps commun, échelle et zéro de la voie) ; courbe = médiane du tracé,
    points en pixels. choose : noms des voies retenues (toutes par défaut) ; labels :
    voie -> nom donné par l'utilisateur.
    """
    from .document import Axis, Component, Dataset, Graph
    labels = labels or {}
    component = Component(name=name)
    warnings = list(capture.warnings)
    for ch in capture.channels:
        if choose is not None and ch.name not in choose:
            continue
        label = labels.get(ch.name) or ch.name
        graph = Graph(name=label, image=np.ascontiguousarray(np.asarray(image)[:, :, :3]),
                      source=source)
        graph.x_axis = Axis("t", "s")
        graph.y_axis = Axis(label, ch.unit)
        dataset = Dataset(name=label, color="#%02x%02x%02x" % tuple(int(c) for c in ch.color),
                          pixels=ch.pixels.copy())
        dataset.curve_color = tuple(int(c) for c in ch.color)
        if ch.scale is not None and ch.zero_y is not None and capture.time_per_div:
            graph.set_calibration(channel_calibration(capture, ch))
        else:
            warnings.append(f"{label} : échelle, zéro ou base de temps inconnu, non calibré")
        graph.datasets = [dataset]          # après la calibration : ordre gardé
        component.graphs.append(graph)
        warnings += [f"{label} : {w}" for w in ch.warnings]
    zoom = (f", vue zoomée de {capture.zoom_window[0] * 1e6:g} à {capture.zoom_window[1] * 1e6:g} µs"
            if capture.zoom_window else "")
    lines = [f"Capture d'oscilloscope{' ' + source if source else ''} : "
             f"{len(component.graphs)} voie(s), "
             f"{(capture.time_per_div or 0) * 1e6:g} µs/div{zoom}."]
    if capture.measurements:
        lines.append("Mesures de l'écran : " + " ; ".join(
            f"{n} {k} {v:g} {u}" for n, k, v, u in capture.measurements))
    if warnings:
        lines += ["", "À vérifier :"] + [f"- {w}" for w in warnings]
    component.notes = "\n".join(lines)
    return component, warnings


def looks_like_capture(image) -> bool:
    """Écran Tektronix reconnu : cadre orange et grille de 10 divisions."""
    rgb = np.ascontiguousarray(np.asarray(image)[:, :, :3])
    screen = screen_box(rgb)
    if screen == (0, 0, rgb.shape[1] - 1, rgb.shape[0] - 1):
        return False
    return bool(find_graticules(rgb, screen))
