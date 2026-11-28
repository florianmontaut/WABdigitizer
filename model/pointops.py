# model/pointops.py
"""
Opérations sur une partie des points d'une courbe (sélection par zone) : décimer, lisser.

La sélection est une liste d'indices de points (courbe rangée par X). Elle est traitée par
morceaux contigus (`runs`) : un rectangle peut prendre deux bouts d'une courbe qui revient
sur elle-même. Les points hors sélection ne changent jamais.

Décimation : en pixels de l'image (tolérance et espacement comme à l'écran) ; les deux bouts
de chaque morceau sont gardés, la courbe reste raccordée au reste.
Lissage : sur Y seulement, en coordonnées calibrées (log10 sur un axe log, image tournée
redressée), calculé sur toute la courbe : les points voisins hors sélection servent de
contexte, le morceau lissé se raccorde sans marche.
"""
import numpy as np
from scipy import ndimage, signal

from .extraction import simplify_mask

DECIMATE = {"every": "Garder 1 point sur n",
            "tolerance": "Douglas-Peucker (tolérance en pixels)",
            "spacing": "Espacement minimal (pixels)"}
FILTERS = {"mean": "Moyenne glissante",
           "savgol": "Savitzky-Golay",
           "median": "Médiane (points aberrants)"}


def runs(indices) -> list:
    """Morceaux contigus (premier, dernier) d'indices, inclus, dans l'ordre."""
    indices = np.unique(np.asarray(indices, dtype=int))
    if not len(indices):
        return []
    cuts = np.flatnonzero(np.diff(indices) > 1)
    starts = np.r_[indices[0], indices[cuts + 1]]
    stops = np.r_[indices[cuts], indices[-1]]
    return list(zip(starts.tolist(), stops.tolist()))


def _keep_run(points: np.ndarray, method: str, value: float) -> np.ndarray:
    """Points gardés d'un morceau (les deux bouts toujours)."""
    count = len(points)
    keep = np.zeros(count, dtype=bool)
    keep[[0, -1]] = True
    if method == "every":
        n = max(1, int(round(value)))
        keep[::n] = True
    elif method == "tolerance":
        keep |= simplify_mask(points, float(value), mode="perpendicular")
    elif method == "spacing":
        last = points[0]
        for i in range(1, count - 1):
            if np.hypot(*(points[i] - last)) >= value and np.hypot(*(points[-1] - points[i])) >= value:
                keep[i] = True
                last = points[i]
    else:
        raise ValueError(f"décimation inconnue : {method}")
    return keep


def decimate(pixels, indices, method: str, value: float) -> np.ndarray:
    """Masque des points gardés de toute la courbe (hors sélection : tous)."""
    pixels = np.asarray(pixels, dtype=float).reshape(-1, 2)
    keep = np.ones(len(pixels), dtype=bool)
    for a, b in runs(indices):
        if b - a >= 2:
            keep[a:b + 1] = _keep_run(pixels[a:b + 1], method, value)
    return keep


def _odd(window: int, count: int) -> int:
    window = max(3, int(window))
    window += 1 - window % 2
    if window > count:
        window = count if count % 2 else count - 1
    return window


def filtered(y, method: str, window: int, order: int = 2) -> np.ndarray:
    """Y filtré sur toute la longueur (fenêtre impaire, ramenée au nombre de points)."""
    y = np.asarray(y, dtype=float)
    if len(y) < 3:
        return y.copy()
    window = _odd(window, len(y))
    if method == "mean":
        return ndimage.uniform_filter1d(y, window, mode="nearest")
    if method == "median":
        return ndimage.median_filter(y, size=window, mode="nearest")
    if method == "savgol":
        order = int(min(max(order, 0), window - 1))
        return signal.savgol_filter(y, window, order, mode="interp")
    raise ValueError(f"filtre inconnu : {method}")


def smooth(scaled, indices, method: str, window: int, order: int = 2) -> np.ndarray:
    """
    Points (coordonnées calibrées, rangés par X) dont seuls les Y sélectionnés sont
    remplacés par les Y filtrés.
    """
    scaled = np.asarray(scaled, dtype=float).reshape(-1, 2).copy()
    indices = np.unique(np.asarray(indices, dtype=int))
    if len(indices) and len(scaled) >= 3:
        scaled[indices, 1] = filtered(scaled[:, 1], method, window, order)[indices]
    return scaled
