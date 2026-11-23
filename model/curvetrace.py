# model/curvetrace.py
"""
Relevé automatique des courbes d'un graphique en image (sans apprentissage, sans GPU).

    result = trace(image, area)          # area : plotimage.PlotArea (cadre, chiffres)
    result.curves                        # [TracedCurve] : polylignes en pixels, style
    result.legend                        # [LegendEntry] : échantillons de légende repérés

Étapes :
    1. encre de la zone de tracé : plus foncée que la grille (seuil tiré du gris des
       traits de grille), ou de couleur vive ;
    2. texte retiré (taches de la taille des chiffres, alignées en mots) ;
    3. points : chaque tache d'encre d'une colonne ;
    4. suivi : chaque courbe prédit sa position à la colonne suivante (pente) ; appariement
       global le moins coûteux avec les taches ; une tache épaisse peut servir à deux
       courbes qui se croisent ; trous des tirets et des pointillés franchis ; parcours
       depuis le côté où les courbes sont le plus séparées ;
    5. parties raides : même suivi ligne par ligne sur l'encre restante, raccordé aux bouts ;
    6. tri : traces trop courtes, nettement plus fines ou plus claires que les courbes
       (traits de rappel des étiquettes), droites posées sur un trait de grille écartées ;
       échantillons de légende (trait court juste à gauche d'un texte) mis de côté ;
       style (plein, tirets, pointillés) mesuré le long de la courbe.
Points en pixels de l'image (x = colonne, y = ligne vers le bas), reliés en une polyligne.
"""
from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage
from scipy.optimize import linear_sum_assignment

MIN_LENGTH = 0.06       # étendue minimale d'une courbe, en fraction de la largeur du cadre
MAX_GAP = 0.08          # trou maximal franchi (tirets), en fraction de la largeur du cadre
THIN = 0.6              # trace plus fine que THIN × l'épaisseur des courbes : trait de rappel
LIGHT = 60              # trace plus claire (gris) que la plus foncée de LIGHT : trait de rappel


@dataclass
class TracedCurve:
    points: np.ndarray                    # (n, 2) pixels, polyligne
    style: str = "plein"                  # « plein », « tirets », « pointillés »
    coverage: float = 1.0                 # part de la polyligne posée sur de l'encre
    width: float = 0.0                    # épaisseur, pixels
    dash: float = 0.0                     # longueur des tirets (plein : inf)
    label: str = ""                       # nom lu (légende ou étiquette), sinon « »
    label_source: str = ""                # « légende », « étiquette », « proximité »


@dataclass
class LegendEntry:
    style: str                            # style de l'échantillon
    text_box: tuple                       # (x0, y0, x1, y1) du texte à sa droite, pixels
    y: float = 0.0
    dash: float = 0.0                     # longueur des tirets (plein : inf)


@dataclass
class TraceResult:
    curves: list = field(default_factory=list)
    legend: list = field(default_factory=list)
    width: float = 0.0                    # épaisseur des courbes, pixels
    words: list = field(default_factory=list)   # boîtes des textes du cadre (x0, y0, x1, y1)
    labels: list = field(default_factory=list)  # textes lus hors légende (étiquettes)
    label_boxes: list = field(default_factory=list)  # leurs boîtes


@dataclass
class _Track:
    xs: list = field(default_factory=list)
    ys: list = field(default_factory=list)
    thick: list = field(default_factory=list)  # longueur de la tache appariée
    last: int = 0                               # dernière colonne où l'encre a été vue

    def predict(self, x):
        n = len(self.xs)
        if n == 1:
            return self.ys[-1], 0.0
        k = min(n, 8)
        xs, ys = np.array(self.xs[-k:], float), np.array(self.ys[-k:], float)
        slope = np.polyfit(xs, ys, 1)[0] if np.ptp(xs) > 0 else 0.0
        return self.ys[-1] + slope * (x - self.xs[-1]), slope

    def add(self, x, y, thick):
        self.xs.append(x)
        self.ys.append(y)
        self.thick.append(thick)
        self.last = x


# ================================================================ encre
def ink_threshold(gray: np.ndarray, area) -> float:
    """Gris de l'encre : nettement plus foncé que les traits de grille (sinon 120)."""
    l, t, r, b = area.frame
    samples = [gray[t + 3:b - 2, int(round(x))] for x in area.x_grid if l + 3 < x < r - 3]
    samples += [gray[int(round(y)), l + 3:r - 2] for y in area.y_grid if t + 3 < y < b - 3]
    if not samples:
        return 120.0
    values = np.concatenate(samples)
    grid = float(np.median(values[values < 245])) if (values < 245).any() else 220.0
    return float(np.clip(grid - 40, 90, 150))


def ink_mask(image: np.ndarray, area) -> tuple:
    """(encre des courbes dans le cadre, gris) : bords du cadre exclus."""
    rgb = np.asarray(image, dtype=float)[:, :, :3]
    gray = rgb.mean(axis=2)
    chroma = rgb.max(axis=2) - rgb.min(axis=2)
    mask = (gray < ink_threshold(gray, area)) | (chroma > 80)
    out = np.zeros_like(mask)
    l, t, r, b = area.frame
    out[t + 3:b - 2, l + 3:r - 2] = mask[t + 3:b - 2, l + 3:r - 2]
    return out, gray


def _run_lengths(mask: np.ndarray) -> np.ndarray:
    """Longueur, en chaque pixel d'encre, de sa tache verticale (0 hors encre)."""
    out = np.zeros(mask.shape, np.int32)
    for c, col in enumerate(mask.T):
        idx = np.flatnonzero(col)
        if len(idx):
            cuts = np.flatnonzero(np.diff(idx) > 1)
            starts = np.r_[0, cuts + 1]
            ends = np.r_[cuts, len(idx) - 1]
            for a, b in zip(starts, ends):
                out[idx[a]:idx[b] + 1, c] = b - a + 1
    return out


def stroke_width(mask: np.ndarray) -> float:
    """
    Épaisseur des courbes : en chaque pixel d'encre, le plus court de ses passages vertical
    et horizontal (une courbe raide donne de longues taches verticales, pas horizontales) ;
    valeur la plus fréquente, en nombre de pixels.
    """
    if not mask.any():
        return 2.0
    thick = np.minimum(_run_lengths(mask), _run_lengths(mask.T).T)[mask]
    thick = thick[thick <= 15]
    return float(np.bincount(thick).argmax()) if len(thick) else 2.0


def remove_text(mask: np.ndarray, char: float) -> tuple:
    """Taches de la taille d'un caractère, au moins deux alignées : retirées. Rend (masque, mots)."""
    labels, _ = ndimage.label(mask, structure=np.ones((3, 3)))
    boxes = ndimage.find_objects(labels)
    glyphs = [(i + 1, sl) for i, sl in enumerate(boxes) if sl is not None
              and 0.3 * char <= sl[0].stop - sl[0].start <= 1.3 * char
              and sl[1].stop - sl[1].start <= 1.4 * char]
    parent = {i: i for i, _ in glyphs}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for a, sa in glyphs:
        for b, sb in glyphs:
            if a < b:
                gap = max(sa[1].start, sb[1].start) - min(sa[1].stop, sb[1].stop)
                ca = (sa[0].start + sa[0].stop) / 2
                cb = (sb[0].start + sb[0].stop) / 2
                if gap <= 0.6 * char and abs(ca - cb) <= 0.5 * char:
                    parent[find(a)] = find(b)
    groups = {}
    for i, sl in glyphs:
        groups.setdefault(find(i), []).append((i, sl))
    out, words = mask.copy(), []
    for members in groups.values():
        # un mot a au moins un caractère de pleine hauteur (chiffre, majuscule) ; des
        # tirets alignés, eux, restent à la hauteur du trait
        tall = max(sl[0].stop - sl[0].start for _, sl in members) >= 0.6 * char
        if len(members) < 2 or not tall:
            continue
        for i, sl in members:
            out[sl] &= labels[sl] != i
        words.append((min(sl[1].start for _, sl in members), min(sl[0].start for _, sl in members),
                      max(sl[1].stop for _, sl in members), max(sl[0].stop for _, sl in members)))
    return out, words


# ================================================================ suivi
def _runs(mask: np.ndarray) -> list:
    """Par colonne : [(début, fin)] des taches d'encre (lignes, fin incluse)."""
    out = []
    for col in mask.T:
        idx = np.flatnonzero(col)
        if not len(idx):
            out.append([])
            continue
        cuts = np.flatnonzero(np.diff(idx) > 1)
        starts = np.r_[idx[0], idx[cuts + 1]]
        ends = np.r_[idx[cuts], idx[-1]]
        out.append(list(zip(starts.tolist(), ends.tolist())))
    return out


def _point(a, b, predicted, width) -> float:
    """
    Point d'une courbe dans une tache (a, b) : le plus près de la prédiction, à une
    demi-épaisseur des bords au moins. Tache d'une seule courbe : son centre ; tache de
    deux courbes (croisement) ou de courbe raide : le point suit la pente.
    """
    low, high = a + (width - 1) / 2, b - (width - 1) / 2
    if low >= high:
        return (a + b) / 2
    return float(np.clip(predicted, low, high))


def _track(runs, columns, width, max_gap) -> list:
    """Suivi des courbes le long des colonnes données (dans l'ordre du parcours)."""
    live, done = [], []
    for x in columns:
        spans = runs[x]
        preds = [t.predict(x) for t in live]
        cost = np.full((len(live), len(spans)), 1e6)
        for i, (p, slope) in enumerate(preds):
            gate = 2.5 * width + abs(slope) * 1.5 + 0.5 * abs(x - live[i].last)
            for j, (a, b) in enumerate(spans):
                # distance au point que la courbe prendrait dans la tache (pas 0 dans les
                # marges : deux taches contiguës après un croisement se distinguent)
                d = abs(p - _point(a, b, p, width))
                if d <= gate:
                    cost[i, j] = d
        used_tracks, used_spans = set(), set()
        if live and spans:
            rows, cols = linear_sum_assignment(cost)
            for i, j in zip(rows, cols):
                if cost[i, j] < 1e6:
                    used_tracks.add(i)
                    used_spans.add(j)
                    a, b = spans[j]
                    p, _ = preds[i]
                    y = _point(a, b, p, width)
                    live[i].add(x, y, b - a + 1)
        # courbes non appariées : tache partagée (croisement) si la prédiction y tombe
        for i, (p, _) in enumerate(preds):
            if i in used_tracks:
                continue
            for j, (a, b) in enumerate(spans):
                if a - 0.5 * width <= p <= b + 0.5 * width:
                    live[i].add(x, _point(a, b, p, width), b - a + 1)
                    used_tracks.add(i)
                    used_spans.add(j)
                    break
        for j, (a, b) in enumerate(spans):
            if j not in used_spans:
                live.append(_Track([x], [(a + b) / 2], [b - a + 1], x))
        keep = []
        for t in live:
            (keep if abs(x - t.last) <= max_gap else done).append(t)
        live = keep
    return done + live


def _thickness(track) -> float:
    """Épaisseur perpendiculaire médiane, sur les parties peu pentues."""
    xs, ys = np.array(track.xs, float), np.array(track.ys, float)
    if len(xs) < 3:
        return float(np.median(track.thick))
    slope = np.gradient(ys, xs) if np.ptp(xs) > 0 else np.zeros_like(xs)
    flat = np.abs(slope) < 1.0
    thick = np.array(track.thick, float) * np.cos(np.arctan(slope))
    return float(np.median(thick[flat] if flat.any() else thick))


def _sweep(mask, width, span, lo, hi) -> list:
    """Suivi colonne par colonne entre lo et hi, depuis le côté le plus encombré."""
    runs = _runs(mask)
    count = np.array([len(c) for c in runs])
    edge = max((hi - lo) // 5, 1)
    leftwards = count[hi - edge:hi].mean() > count[lo:lo + edge].mean()
    columns = range(hi, lo - 1, -1) if leftwards else range(lo, hi + 1)
    tracks = _track(runs, list(columns), width, MAX_GAP * span)
    out = []
    for tr in tracks:
        pts = np.column_stack([tr.xs, tr.ys])
        if leftwards:
            pts = pts[::-1]
        out.append((pts, _thickness(tr)))
    return out


def _samples(points, shape) -> tuple:
    """Pixels (lignes, colonnes) de la polyligne, au pas d'un pixel."""
    seg = np.diff(points, axis=0)
    n = np.maximum(np.ceil(np.hypot(seg[:, 0], seg[:, 1])).astype(int), 1)
    samples = np.vstack([points[i] + np.outer(np.arange(k) / k, seg[i])
                         for i, k in enumerate(n)] + [points[-1:]])
    r = np.clip(np.round(samples[:, 1]).astype(int), 0, shape[0] - 1)
    c = np.clip(np.round(samples[:, 0]).astype(int), 0, shape[1] - 1)
    return r, c


def _coverage(points, grown) -> float:
    """Part de la polyligne posée sur de l'encre (encre élargie d'un pixel)."""
    r, c = _samples(points, grown.shape)
    return float(grown[r, c].mean())


def _darkness(points, dark, grown) -> float:
    """Gris médian de la polyligne, là seulement où elle est sur de l'encre (trous des tirets
    exclus ; minimum local 3 × 3)."""
    r, c = _samples(points, dark.shape)
    on = grown[r, c]
    return float(np.median(dark[r, c][on])) if on.any() else 255.0


def _leader(points, words, char) -> bool:
    """Trait de rappel d'une étiquette : segment droit dont un bout touche un texte."""
    if len(points) < 3:
        return False
    x, y = points[:, 0], points[:, 1]
    if np.ptp(x) >= np.ptp(y):
        fit = np.polyfit(x, y, 1)
        residual = np.abs(np.polyval(fit, x) - y).max()
    else:
        fit = np.polyfit(y, x, 1)
        residual = np.abs(np.polyval(fit, y) - x).max()
    if residual > 1.5:
        return False
    for end in (points[0], points[-1]):
        for x0, y0, x1, y1 in words:
            dx = max(x0 - end[0], 0, end[0] - x1)
            dy = max(y0 - end[1], 0, end[1] - y1)
            if np.hypot(dx, dy) <= 1.0 * char:
                return True
    return False


def _measure(points, grown, width) -> tuple:
    """
    (style, part posée sur l'encre) : plein si presque tout est encré ; sinon tirets ou
    pointillés selon la longueur médiane des traits encrés (pointillés : au plus 2,5 fois
    l'épaisseur).
    """
    dash, coverage = dash_length(points, grown)
    if coverage > 0.9:
        return "plein", coverage
    return ("pointillés" if dash <= 2.5 * width + 2 else "tirets"), coverage


def dash_length(points, grown) -> tuple:
    """(longueur médiane des traits encrés, part encrée) le long de la polyligne ; plein : inf."""
    r, c = _samples(points, grown.shape)
    on = grown[r, c]
    coverage = float(on.mean()) if len(on) else 0.0
    if coverage > 0.9:
        return float("inf"), coverage
    runs = [b - a + 1 for a, b in _segments(on)]
    return (float(np.median(runs)) if runs else 0.0), coverage


def _segments(flags) -> list:
    """Suites de True d'un vecteur : [(début, fin)]."""
    idx = np.flatnonzero(flags)
    if not len(idx):
        return []
    cuts = np.flatnonzero(np.diff(idx) > 1)
    return list(zip(np.r_[idx[0], idx[cuts + 1]].tolist(), np.r_[idx[cuts], idx[-1]].tolist()))


def _paint(shape, polylines, radius) -> np.ndarray:
    """Masque des pixels à moins de radius des polylignes."""
    painted = np.zeros(shape, bool)
    for points in polylines:
        r, c = _samples(points, shape)
        painted[r, c] = True
    k = int(2 * radius + 1)
    return ndimage.binary_dilation(painted, np.ones((k, k), bool))


def _join(flat, steep, width) -> list:
    """
    Parties raides raccordées aux courbes dont un bout touche le leur (flanc vertical
    d'une SOA, montée d'une diode) ; deux courbes ordinaires ne sont jamais raccordées.
    """
    curves = list(flat)
    for q in steep:
        best = None
        for i, p in enumerate(curves):
            for pp, qq in ((p, q), (p, q[::-1]), (p[::-1], q), (p[::-1], q[::-1])):
                d = np.hypot(*(pp[-1] - qq[0]))
                if d <= 2 * width + 2 and (best is None or d < best[0]):
                    best = (d, i, pp, qq)
        if best is None:
            curves.append(q)
        else:
            _, i, pp, qq = best
            curves[i] = np.vstack([pp, qq])
    return curves


def _on_grid(points, area) -> bool:
    """Trace droite posée sur un trait de grille (grille plus foncée que prévu)."""
    if np.ptp(points[:, 1]) <= 2:
        return any(abs(np.median(points[:, 1]) - y) <= 2 for y in area.y_grid)
    if np.ptp(points[:, 0]) <= 2:
        return any(abs(np.median(points[:, 0]) - x) <= 2 for x in area.x_grid)
    return False


def trace(image: np.ndarray, area) -> TraceResult:
    """Courbes d'un graphique en image, échantillons de légende."""
    l, t, r, b = area.frame
    char = area.char or 20
    ink, gray = ink_mask(image, area)
    mask, words = remove_text(ink, char)
    width = stroke_width(mask)
    # traits fins (rappels d'étiquettes) retirés avant le suivi, qui sinon passerait du
    # trait à la courbe ; le style se mesure ensuite sur l'encre d'origine
    # (disque, pas carré : la diagonale d'un carré ne tient pas dans un trait incliné)
    k = int(round(THIN * width))
    if k >= 2:
        yy, xx = np.mgrid[:k, :k] - (k - 1) / 2
        mask = ndimage.binary_opening(mask, (xx ** 2 + yy ** 2) <= (k / 2) ** 2)
    span = r - l
    grown = ndimage.binary_dilation(ink, np.ones((3, 3), bool))
    dark = ndimage.minimum_filter(gray, size=3)
    # colonne par colonne
    found = [(p, w) for p, w in _sweep(mask, width, span, l + 3, r - 3)
             if np.ptp(p[:, 0]) >= MIN_LENGTH * span]
    # parties raides : ligne par ligne sur l'encre restante
    rest = mask & ~_paint(mask.shape, [p for p, _ in found], width)
    steep = [(p[:, ::-1], w) for p, w in _sweep(rest.T, width, b - t, t + 3, b - 3)
             if np.ptp(p[:, 0]) >= MIN_LENGTH * (b - t)]
    tracks = [(p, w, k >= len(found)) for k, (p, w) in enumerate(found + steep)
              if w >= THIN * width]
    shades = [_darkness(p, dark, grown) for p, _, _ in tracks]
    darkest = min(shades) if shades else 0.0
    result = TraceResult(width=width, words=words)
    flat, raised = [], []
    for (p, w, is_steep), shade in zip(tracks, shades):
        # échantillon de légende : trait court et plat, juste à gauche d'un texte
        xmin, xmax = p[:, 0].min(), p[:, 0].max()
        y = float(np.median(p[:, 1]))
        word = next((wd for wd in words if xmax - 0.5 * char <= wd[0] <= xmax + 1.5 * char
                     and wd[1] - 0.3 * char <= y <= wd[3] + 0.3 * char), None)
        if word is not None and xmax - xmin < 0.2 * span and np.ptp(p[:, 1]) < 0.5 * char:
            result.legend.append(LegendEntry(_measure(p, grown, width)[0], word, y,
                                             dash_length(p, grown)[0]))
            continue
        # trait de rappel : nettement plus clair que la courbe la plus foncée, ou segment
        # droit contre un texte, plus fin ou plus clair que les courbes
        if shade > darkest + LIGHT:
            continue
        # droite posée sur un trait de grille, plus claire que les courbes : la grille
        # (le flanc d'une SOA sur un trait de grille, aussi foncé qu'elles, reste)
        if _on_grid(p, area) and shade > darkest + 20:
            continue
        if _leader(p, words, char) and (w < 0.85 * width or shade > darkest + 20):
            continue
        (raised if is_steep else flat).append(p)
    for p in _join(flat, raised, width):
        style, cov = _measure(p, grown, width)
        result.curves.append(TracedCurve(p, style, cov, width, dash_length(p, grown)[0]))
    result.curves.sort(key=lambda c: c.points[np.argmax(c.points[:, 0]), 1])
    result.legend.sort(key=lambda e: e.y)
    return result



# ================================================================ noms des courbes
def merge_words(words, char) -> list:
    """Mots d'une même ligne séparés de moins d'un caractère (« IDS= » « 40A ») réunis."""
    merged = []
    for b in sorted(words, key=lambda b: b[0]):
        for m in merged:
            if abs((m[1] + m[3]) / 2 - (b[1] + b[3]) / 2) <= 0.4 * char \
                    and -0.2 * char <= b[0] - m[2] <= 1.0 * char:
                m[1], m[2], m[3] = min(m[1], b[1]), max(m[2], b[2]), max(m[3], b[3])
                break
        else:
            merged.append(list(b))
    return [tuple(m) for m in merged]


def _distance(points, xy) -> float:
    """Distance d'un point à une polyligne (à ses sommets, assez denses ici)."""
    return float(np.min(np.hypot(points[:, 0] - xy[0], points[:, 1] - xy[1])))


def name_curves(result: TraceResult, image: np.ndarray, area, symbols=()) -> list:
    """
    Noms des courbes lus dans l'image ; renseigne `label` et `label_source` de chaque
    courbe et rend les mots lus non attribués. Ordre :
      1. légende : chaque échantillon nomme la courbe de même style (seule de ce style, ou
         dans l'ordre de haut en bas si la légende en a autant) ;
      2. étiquette à trait de rappel : le trait, suivi depuis le texte, désigne la courbe
         qu'il touche ;
      3. étiquette posée près d'une courbe (à moins de deux caractères).
    """
    from . import labelread
    char = area.char or 20
    gray = np.asarray(image, dtype=float)[:, :, :3].mean(axis=2)
    reader = labelread.Reader(gray)
    pad = int(0.3 * char)
    words = merge_words(result.words, char)

    def read(box):
        x0, y0, x1, y1 = box
        return reader.read((x0 - pad, y0 - pad, x1 + pad, y1 + pad), symbols)
    curves = result.curves
    used_words = set()
    # 1. légende
    entries = []
    for entry in result.legend:
        box = next((w for w in words if w[0] <= entry.text_box[0] + 2
                    and w[2] >= entry.text_box[2] - 2 and w[1] <= entry.y <= w[3]), entry.text_box)
        word = read(box)
        if word is not None:
            entries.append((entry, word))
            used_words.add(box)
    _match_legend(entries, curves)
    # mot de légende sans échantillon repéré (pointillés trop fins) : s'il reste une seule
    # courbe libre et un seul mot aligné sur la colonne de la légende, ils vont ensemble
    if entries:
        x_col = np.median([w.box[0] for _, w in entries])
        free_words = []
        for box in words:
            if box in used_words or abs(box[0] - x_col) > 1.5 * char:
                continue
            if not any(abs(box[1] - w.box[1]) < 0.5 * char for _, w in entries) and \
                    min(abs(box[1] - w.box[1]) for _, w in entries) <= 2.5 * char:
                word = read(box)
                if word is not None and word.known:
                    free_words.append((box, word))
        free_curves = [c for c in curves if not c.label]
        if len(free_words) == 1 and len(free_curves) == 1:
            free_curves[0].label, free_curves[0].label_source = free_words[0][1].text, "légende"
            used_words.add(free_words[0][0])
    # 2. et 3. étiquettes
    l, t, r, b = area.frame
    painted = _paint(gray.shape, [c.points for c in curves], result.width + 1) if curves \
        else np.zeros(gray.shape, bool)
    ink, _ = ink_mask(image, area)
    rest = ink & ~painted
    for box in words:
        if box in used_words:
            continue
        word = read(box)
        if word is None:
            continue
        result.labels.append(word.text)
        result.label_boxes.append(box)
        x0, y0, x1, y1 = box
        target = _leader_target(rest, box, curves, char, result.width)
        source = "étiquette"
        if target is None:
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            near = [(_distance(c.points, (cx, cy)), k) for k, c in enumerate(curves)]
            near = [(d, k) for d, k in near if d <= 2 * char]
            target = min(near)[1] if near else None
            source = "proximité"
        if target is not None and not curves[target].label:
            curves[target].label, curves[target].label_source = word.text, source
    return curves


def _match_legend(entries, curves):
    """
    Échantillons de légende -> courbes : même ordre de longueur de tirets (plein, tirets
    longs, courts, pointillés) ; à égalité (deux pleins), de haut en bas.
    """
    from scipy.optimize import linear_sum_assignment
    if not entries:
        return
    free = [c for c in curves if not c.label]
    if not free:
        return

    def key(dash):
        return 12.0 if not np.isfinite(dash) else float(np.log2(max(dash, 1.0)))
    cost = np.zeros((len(entries), len(free)))
    for i, (entry, _) in enumerate(entries):
        for j, curve in enumerate(free):
            cost[i, j] = abs(key(entry.dash) - key(curve.dash))
    # à égalité de style : l'ordre vertical départage (légende et courbes de haut en bas)
    order_e = np.argsort([e.y for e, _ in entries]).argsort() / max(len(entries), 1)
    order_c = np.argsort([c.points[np.argmax(c.points[:, 0]), 1] for c in free]).argsort() \
        / max(len(free), 1)
    cost += 0.1 * np.abs(order_e[:, None] - order_c[None, :])
    rows, cols = linear_sum_assignment(cost)
    for i, j in zip(rows, cols):
        if cost[i, j] <= 1.2:              # longueurs de tirets du même ordre
            free[j].label, free[j].label_source = entries[i][1].text, "légende"


def _leader_target(rest, box, curves, char, width):
    """
    Courbe désignée par le trait de rappel qui part du texte (None sans trait) : le trait
    est prolongé en ligne droite au-delà des courbes qu'il croise, jusqu'à son vrai bout.
    """
    if not curves:
        return None
    x0, y0, x1, y1 = box
    m = int(max(3, 1.0 * char))            # le trait commence à quelques pixels du texte
    window = np.zeros(rest.shape, bool)
    window[max(y0 - m, 0):y1 + m, max(x0 - m, 0):x1 + m] = True
    labels, n = ndimage.label(rest, structure=np.ones((3, 3)))
    if not n:
        return None
    touching = set(np.unique(labels[window & rest])) - {0}
    all_pts = np.column_stack(np.nonzero(rest)[::-1]).astype(float)     # (x, y)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    best = None
    for k in touching:
        rr, cc = np.nonzero(labels == k)
        inside = (cc >= x0 - 1) & (cc <= x1 + 1) & (rr >= y0 - 1) & (rr <= y1 + 1)
        rr, cc = rr[~inside], cc[~inside]
        if len(rr) < char:                 # trop court pour un trait de rappel
            continue
        pts = np.column_stack([cc, rr]).astype(float)
        # départ du trait : son point le plus proche du bord droit du mot, à mi-hauteur
        # (le trait d'une étiquette voisine peut passer tout près)
        gap = float(np.min(np.hypot(pts[:, 0] - x1, pts[:, 1] - (y0 + y1) / 2)))
        followed = _follow(pts, all_pts, (cx, cy), width)
        if followed is None:
            continue                       # pas une droite
        end = followed
        d, i = min((_distance(c.points, end), i) for i, c in enumerate(curves))
        # le trait qui part au plus près du texte
        if d <= 2 * width + 4 and (best is None or gap < best[0]):
            best = (gap, i)
    return None if best is None else best[1]


def _follow(pts, all_pts, origin, width):
    """
    Bout d'un trait droit, prolongé morceau par morceau au-delà des croisements (direction
    réajustée à chaque morceau) ; None si le premier morceau n'est pas droit.
    """
    pts = pts.copy()
    for step in range(30):
        center = pts.mean(axis=0)
        _, _, vt = np.linalg.svd(pts - center, full_matrices=False)
        direction = vt[0]
        if np.dot(center - origin, direction) < 0:
            direction = -direction         # du texte vers la courbe
        normal = np.array([-direction[1], direction[0]])
        if step == 0 and np.abs((pts - center) @ normal).max() > 2.0:
            return None
        reach = ((pts - center) @ direction).max()
        rel = all_pts - center
        along, across = rel @ direction, np.abs(rel @ normal)
        # saut permis : une courbe effacée (épaisseur + marges) entre deux morceaux
        ahead = (along > reach + 0.5) & (along <= reach + 3 * width + 12) & (across <= 2.0)
        if not ahead.any():
            break
        nxt = along[ahead].min()
        chunk = ahead & (along <= nxt + 3 * width) | ((along > reach) & (along <= nxt + 3 * width)
                                                    & (across <= 2.0))
        pts = np.vstack([pts, all_pts[chunk]])
    center = pts.mean(axis=0)
    _, _, vt = np.linalg.svd(pts - center, full_matrices=False)
    direction = vt[0] if np.dot(center - origin, vt[0]) >= 0 else -vt[0]
    return center + ((pts - center) @ direction).max() * direction


# ================================================================ suivi depuis un clic
TURN = 0.5              # cosinus de l'angle maximal entre deux pas (60°) : au-delà, coude


def follow(image: np.ndarray, seed, tolerance: float = 120.0, max_gap: float | None = None):
    """
    Courbe suivie depuis un clic (outil « Suivre la courbe ») : (polyligne (n, 2) en
    pixels, couleur RGB) ; polyligne vide si rien n'est trouvé près du clic.
    Couleur : la plus foncée ou la plus vive près du clic ; encre : pixels à moins de
    `tolerance` (distance RGB) de cette couleur. Le suivi avance par pas d'une épaisseur
    dans les deux sens en gardant sa direction (croisements traversés), franchit les trous
    des tirets (jusqu'à `max_gap` pixels) et s'arrête à un coude brusque (bord du cadre,
    autre courbe) ou au bord de l'image.
    """
    rgb = np.asarray(image, dtype=float)[:, :, :3]
    H, W = rgb.shape[:2]
    x, y = int(round(seed[0])), int(round(seed[1]))
    if not (0 <= x < W and 0 <= y < H):
        return np.empty((0, 2)), None
    # couleur : la plus foncée ou la plus vive à 8 pixels du clic (un clic un peu à côté
    # de la courbe, près d'un trait de grille plus clair, retient la courbe)
    r = 8
    win = rgb[max(y - r, 0):y + r + 1, max(x - r, 0):x + r + 1].reshape(-1, 3)
    strength = (255 - win.mean(axis=1)) + (win.max(axis=1) - win.min(axis=1))
    color = win[int(np.argmax(strength))]
    if strength.max() < 60:                # clic sur le fond
        return np.empty((0, 2)), None
    mask = np.sqrt(((rgb - color) ** 2).sum(axis=2)) <= tolerance
    near = mask[max(y - 60, 0):y + 61, max(x - 60, 0):x + 61]
    width = stroke_width(near) if near.any() else 2.0
    if max_gap is None:
        max_gap = max(0.04 * max(H, W), 6 * width)
    # départ : encre la plus proche du clic, recentrée sur le trait
    ys, xs = np.nonzero(mask[max(y - 15, 0):y + 16, max(x - 15, 0):x + 16])
    if not len(xs):
        return np.empty((0, 2)), None
    xs, ys = xs + max(x - 15, 0), ys + max(y - 15, 0)
    k = int(np.argmin(np.hypot(xs - x, ys - y)))
    start = _centroid(mask, np.array([xs[k], ys[k]], float), max(width, 2.0))
    # direction : axe principal de l'encre autour du départ
    ys, xs = np.nonzero(mask[max(int(start[1]) - int(3 * width) - 2, 0):
                             int(start[1]) + int(3 * width) + 3,
                             max(int(start[0]) - int(3 * width) - 2, 0):
                             int(start[0]) + int(3 * width) + 3])
    pts = np.column_stack([xs + max(int(start[0]) - int(3 * width) - 2, 0),
                           ys + max(int(start[1]) - int(3 * width) - 2, 0)]).astype(float)
    if len(pts) >= 3:
        _, _, vt = np.linalg.svd(pts - pts.mean(axis=0), full_matrices=False)
        direction = vt[0]
    else:
        direction = np.array([1.0, 0.0])
    if direction[0] < 0:
        direction = -direction             # vers la droite d'abord
    ahead = _walk(mask, start, direction, width, max_gap)
    behind = _walk(mask, start, -direction, width, max_gap)
    points = np.vstack([behind[::-1], [start], ahead]) if len(behind) or len(ahead) \
        else np.array([start])
    if points[0, 0] > points[-1, 0]:
        points = points[::-1]              # de gauche à droite
    return points, tuple(int(v) for v in color)


def _centroid(mask, p, radius):
    """Centre de l'encre dans un disque autour de p (p si aucune encre)."""
    H, W = mask.shape
    r = int(np.ceil(radius))
    x0, x1 = max(int(p[0]) - r, 0), min(int(p[0]) + r + 1, W)
    y0, y1 = max(int(p[1]) - r, 0), min(int(p[1]) + r + 1, H)
    if x0 >= x1 or y0 >= y1:
        return p
    ys, xs = np.nonzero(mask[y0:y1, x0:x1])
    xs, ys = xs + x0, ys + y0
    inside = np.hypot(xs - p[0], ys - p[1]) <= radius
    if not inside.any():
        return p
    return np.array([xs[inside].mean(), ys[inside].mean()])


def _walk(mask, start, direction, width, max_gap) -> np.ndarray:
    """Pas successifs dans une direction (inertie) ; trous franchis ; arrêt aux coudes."""
    H, W = mask.shape
    step = max(width, 2.0)
    radius = max(0.75 * width, 1.5)
    p, d = np.asarray(start, float), np.asarray(direction, float)
    out = []
    for _ in range(int(4 * (H + W) / step)):
        found = None
        for k in range(1, int(max_gap / step) + 2):
            q = p + d * step * k
            if not (0 <= q[0] < W and 0 <= q[1] < H):
                break
            c = _centroid(mask, q, radius + 0.1 * k * step)
            if c is not q:
                found = c
                break
        if found is None:
            break
        nd = found - p
        norm = np.hypot(*nd)
        if norm < 0.5:
            break
        nd = nd / norm
        if float(np.dot(nd, d)) < TURN:
            break                          # coude brusque : bord du cadre, autre courbe
        d = 0.6 * d + 0.4 * nd
        d = d / np.hypot(*d)
        p = found
        out.append(p)
    return np.array(out).reshape(-1, 2)
