# model/extraction.py
"""
Extraction automatique d'une courbe à partir des pixels retenus (voir mask.foreground).

Algorithmes (repris de WebPlotDigitizer et du brouillon WabDigitizer) :
    averaging_window   fenêtre glissante : un point par paquet de pixels (dx, dy)
    on_grid            abscisses imposées : fenêtre glissante, puis interpolation sur une
                       grille de X choisie (commune à toutes les courbes d'un composant)
    skeleton           squelette des pixels (scikit-image), puis simplification

Entrée : tableau booléen (lignes, colonnes). Sortie : points en pixels (x = colonne,
y = ligne), au centre des pixels. Les points sur grille sont rendus en pixels eux aussi :
le jeu de données garde ses points en pixels, recalculés en unités physiques par la
calibration.
"""
from dataclasses import dataclass

import numpy as np

METHODS = ("Fenêtre glissante", "Grille de X imposée", "Squelette")
INTERPOLATIONS = ("pchip", "linéaire", "spline")


@dataclass
class ExtractionSettings:
    method: str = METHODS[1]
    dx: float = 5.0                 # fenêtre glissante, pixels
    dy: float = 5.0
    smooth: float = 0.0             # lissage local (pixels), 0 = aucun
    grid_start: float = 0.0         # grille de X, unités physiques
    grid_stop: float = 1.0
    grid_step: float = 0.1          # pas (axe linéaire) ...
    grid_count: int = 0             # ... ou nombre de points (> 0 : prioritaire ; espacés
                                    # régulièrement en log sur un axe log)
    interpolation: str = INTERPOLATIONS[0]
    extrapolate: bool = False
    simplify: float = 1.0           # squelette : tolérance Douglas-Peucker (pixels)

    def to_dict(self) -> dict:
        return dict(vars(self))

    @classmethod
    def from_dict(cls, data: dict) -> "ExtractionSettings":
        known = {k: v for k, v in (data or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)


# ================================================================ fenêtre glissante
def averaging_window(binary: np.ndarray, dx: float = 5.0, dy: float = 5.0) -> np.ndarray:
    """
    Portage de l'algorithme « Averaging Window » de WebPlotDigitizer.
    1) chaque colonne : pixels regroupés en paquets de hauteur dy -> centre de chaque paquet ;
    2) les centres voisins (à moins de dx, dy) sont moyennés en un seul point.
    """
    binary = np.asarray(binary, dtype=bool)
    if binary.ndim != 2 or not binary.any():
        return np.empty((0, 2))
    dx, dy = max(float(dx), 1e-9), max(float(dy), 1e-9)

    centers = []
    for col in np.flatnonzero(binary.any(axis=0)):
        rows = np.flatnonzero(binary[:, col])
        # nouveau paquet dès qu'un pixel est à plus de dy du premier pixel du paquet
        start = 0
        first = rows[0]
        for i in range(1, len(rows) + 1):
            if i == len(rows) or rows[i] > first + dy:
                centers.append((col + 0.5, rows[start:i].mean() + 0.5))
                if i < len(rows):
                    start, first = i, rows[i]
    centers = np.array(centers)

    used = np.zeros(len(centers), dtype=bool)
    result = []
    for i in range(len(centers)):
        if used[i]:
            continue
        x0, y0 = centers[i]
        # centres triés par colonne : on ne regarde que jusqu'à 2 dx plus loin
        stop = np.searchsorted(centers[:, 0], x0 + 2.0 * dx, side="right")
        near = np.arange(i, stop)
        near = near[~used[near]]
        near = near[(np.abs(centers[near, 0] - x0) <= dx) & (np.abs(centers[near, 1] - y0) <= dy)]
        used[near] = True
        result.append(centers[near].mean(axis=0))
    return np.array(result)


def local_smooth(points: np.ndarray, width: float) -> np.ndarray:
    """Moyenne de chaque point avec ses voisins à moins de width pixels (en x et en y)."""
    points = np.asarray(points, dtype=float)
    if width <= 0 or len(points) < 3:
        return points
    out = np.empty_like(points)
    for i, (x, y) in enumerate(points):
        near = (np.abs(points[:, 0] - x) < width) & (np.abs(points[:, 1] - y) < width)
        out[i] = points[near].mean(axis=0)
    return out


# ================================================================ grille imposée
def make_grid(start: float, stop: float, step: float = 0.0, count: int = 0,
              log: bool = False) -> np.ndarray:
    """
    Abscisses de la grille, en unités physiques. count > 0 : count points régulièrement
    espacés (en log10 sur un axe log) ; sinon un pas constant step.
    """
    start, stop = float(start), float(stop)
    if stop < start:
        start, stop = stop, start
    if count and count > 0:
        if count < 2:
            raise ValueError("une grille demande au moins 2 points")
        if log:
            if start <= 0:
                raise ValueError("une grille logarithmique demande des X > 0")
            return np.logspace(np.log10(start), np.log10(stop), int(count))
        return np.linspace(start, stop, int(count))
    if step <= 0:
        raise ValueError("le pas de la grille doit être positif")
    if (stop - start) / step > 100000:
        raise ValueError("pas trop petit : plus de 100 000 points")
    return np.arange(start, stop + 0.5 * step, step)


def merge_duplicates(xs: np.ndarray, ys: np.ndarray):
    """Tri par x croissant ; les x égaux sont fusionnés (moyenne des y)."""
    order = np.argsort(xs, kind="stable")
    xs, ys = xs[order], ys[order]
    unique, inverse = np.unique(xs, return_inverse=True)
    sums = np.bincount(inverse, weights=ys)
    counts = np.bincount(inverse)
    return unique, sums / counts


def interpolate(xs, ys, x_new, method: str = "pchip", extrapolate: bool = False):
    """y(x_new) d'après les points (xs, ys) ; nan hors de la plage si pas d'extrapolation."""
    xs, ys = merge_duplicates(np.asarray(xs, float), np.asarray(ys, float))
    x_new = np.asarray(x_new, dtype=float)
    if len(xs) < 2:
        return np.full(x_new.shape, np.nan)
    if method == "linéaire" or len(xs) < 3:
        y_new = np.interp(x_new, xs, ys)
        if extrapolate:
            low, high = x_new < xs[0], x_new > xs[-1]
            y_new[low] = ys[0] + (x_new[low] - xs[0]) * (ys[1] - ys[0]) / (xs[1] - xs[0])
            y_new[high] = ys[-1] + (x_new[high] - xs[-1]) * (ys[-1] - ys[-2]) / (xs[-1] - xs[-2])
    else:
        from scipy import interpolate as sci
        if method == "spline":
            function = sci.CubicSpline(xs, ys, extrapolate=extrapolate)
        else:
            # pchip : pas de dépassement entre les points (courbes de fiches monotones)
            function = sci.PchipInterpolator(xs, ys, extrapolate=extrapolate)
        y_new = function(x_new)
    if not extrapolate:
        y_new = np.where((x_new >= xs[0]) & (x_new <= xs[-1]), y_new, np.nan)
    return y_new


def on_grid(binary, calibration, settings: ExtractionSettings) -> np.ndarray:
    """
    Points de la courbe aux abscisses de la grille, rendus en pixels. L'interpolation se
    fait dans l'espace calibré (log10 sur un axe log) : une courbe droite sur un graphique
    log-log le reste entre les points.
    """
    if calibration is None:
        raise ValueError("la grille de X demande des axes calibrés")
    dense = averaging_window(binary, settings.dx, settings.dy)
    dense = local_smooth(dense, settings.smooth)
    if len(dense) < 2:
        return np.empty((0, 2))
    scaled = calibration.pixel_to_scaled(dense)
    grid = make_grid(settings.grid_start, settings.grid_stop, settings.grid_step,
                     settings.grid_count, calibration.log_x)
    grid_scaled = calibration.data_to_scaled(np.column_stack((grid, np.ones_like(grid))))[:, 0]
    y_scaled = interpolate(scaled[:, 0], scaled[:, 1], grid_scaled,
                           settings.interpolation, settings.extrapolate)
    result = np.column_stack((grid_scaled, y_scaled))
    result = result[np.isfinite(result).all(axis=1)]
    return calibration.scaled_to_pixel(result)


# ================================================================ squelette
def chain(pieces) -> np.ndarray:
    """
    Morceaux d'une même courbe (polylignes (n, 2), dans le désordre et dans n'importe quel
    sens) -> une seule polyligne : on part du bout le plus à gauche, puis on ajoute le
    morceau dont un bout est le plus proche de la fin (retourné au besoin). Les parties
    raides ou verticales gardent leur ordre (pas de tri par X).
    """
    pieces = [np.asarray(p, dtype=float).reshape(-1, 2) for p in pieces]
    pieces = [p for p in pieces if len(p)]
    if not pieces:
        return np.empty((0, 2))
    starts = [min((p[0], p), (p[-1], p[::-1]), key=lambda t: (t[0][0], t[0][1]))[1]
              for p in pieces]
    first = min(range(len(pieces)), key=lambda i: (starts[i][0, 0], starts[i][0, 1]))
    out = [starts[first]]
    left = [p for i, p in enumerate(pieces) if i != first]
    while left:
        end = out[-1][-1]
        best = min([(np.hypot(*(p[0] - end)), i, False) for i, p in enumerate(left)]
                   + [(np.hypot(*(p[-1] - end)), i, True) for i, p in enumerate(left)])
        _, i, reverse = best
        piece = left.pop(i)
        out.append(piece[::-1] if reverse else piece)
    return np.vstack(out)


def skeleton(binary, tolerance: float = 1.0) -> np.ndarray:
    """Squelette des pixels, un point (médiane) par colonne, puis Douglas-Peucker."""
    try:
        from skimage.morphology import skeletonize
    except ImportError as error:
        raise RuntimeError("la méthode squelette demande scikit-image") from error
    thin = skeletonize(np.asarray(binary, dtype=bool))
    points = [(col + 0.5, np.median(np.flatnonzero(thin[:, col])) + 0.5)
              for col in np.flatnonzero(thin.any(axis=0))]
    if not points:
        return np.empty((0, 2))
    return simplify(np.array(points), tolerance)


def simplify(points: np.ndarray, tolerance: float, mode: str = "vertical") -> np.ndarray:
    """
    Douglas-Peucker (itératif) : garde les points dont l'écart au segment dépasse
    tolerance. « vertical » : écart en y, adapté aux courbes y = f(x).
    """
    points = np.asarray(points, dtype=float)
    if len(points) <= 2 or tolerance <= 0:
        return points
    keep = np.zeros(len(points), dtype=bool)
    keep[[0, -1]] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        inner = points[a + 1:b]
        (xa, ya), (xb, yb) = points[a], points[b]
        if mode == "vertical" and abs(xb - xa) > 1e-12:
            errors = np.abs(inner[:, 1] - (ya + (inner[:, 0] - xa) * (yb - ya) / (xb - xa)))
        else:
            ab = np.array([xb - xa, yb - ya])
            norm = np.hypot(*ab)
            rel = inner - points[a]
            errors = (np.abs(ab[0] * rel[:, 1] - ab[1] * rel[:, 0]) / norm if norm > 1e-12
                      else np.hypot(rel[:, 0], rel[:, 1]))
        worst = int(np.argmax(errors))
        if errors[worst] > tolerance:
            index = a + 1 + worst
            keep[index] = True
            stack += [(a, index), (index, b)]
    return points[keep]


# ================================================================ point d'entrée
def extract(binary, settings: ExtractionSettings, calibration=None) -> np.ndarray:
    """Points extraits en pixels, triés par x croissant."""
    if settings.method == METHODS[0]:
        points = local_smooth(averaging_window(binary, settings.dx, settings.dy),
                              settings.smooth)
    elif settings.method == METHODS[1]:
        points = on_grid(binary, calibration, settings)
    elif settings.method == METHODS[2]:
        points = skeleton(binary, settings.simplify)
    else:
        raise ValueError(f"méthode inconnue : {settings.method}")
    if len(points) == 0:
        return np.empty((0, 2))
    return points[np.argsort(points[:, 0], kind="stable")]
