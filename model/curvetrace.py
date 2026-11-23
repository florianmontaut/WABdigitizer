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


@dataclass
class LegendEntry:
    style: str                            # style de l'échantillon
    text_box: tuple                       # (x0, y0, x1, y1) du texte à sa droite, pixels
    y: float = 0.0


@dataclass
class TraceResult:
    curves: list = field(default_factory=list)
    legend: list = field(default_factory=list)
    width: float = 0.0                    # épaisseur des courbes, pixels


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


def _style(coverage) -> str:
    if coverage > 0.9:
        return "plein"
    return "tirets" if coverage > 0.55 else "pointillés"


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
    result = TraceResult(width=width)
    flat, raised = [], []
    for (p, w, is_steep), shade in zip(tracks, shades):
        # échantillon de légende : trait court et plat, juste à gauche d'un texte
        xmin, xmax = p[:, 0].min(), p[:, 0].max()
        y = float(np.median(p[:, 1]))
        word = next((wd for wd in words if xmax - 0.5 * char <= wd[0] <= xmax + 1.5 * char
                     and wd[1] - 0.3 * char <= y <= wd[3] + 0.3 * char), None)
        if word is not None and xmax - xmin < 0.2 * span and np.ptp(p[:, 1]) < 0.5 * char:
            result.legend.append(LegendEntry(_style(_coverage(p, grown)), word, y))
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
        cov = _coverage(p, grown)
        result.curves.append(TracedCurve(p, _style(cov), cov, width))
    result.curves.sort(key=lambda c: c.points[np.argmax(c.points[:, 0]), 1])
    result.legend.sort(key=lambda e: e.y)
    return result
