# model/mask.py
"""
Masque de la zone à numériser et filtre de couleur.

Le masque est un tableau booléen (lignes, colonnes) de la taille de l'image : le pinceau
y peint la zone où chercher la courbe (comme le « pen » de WebPlotDigitizer). Les pixels
retenus pour l'extraction sont ceux du masque dont la couleur est proche de celle de la
courbe : les quadrillages, légendes et autres courbes hors masque sont ignorés.
"""
import numpy as np


def empty_mask(image: np.ndarray) -> np.ndarray:
    return np.zeros(image.shape[:2], dtype=bool)


def paint_disk(mask: np.ndarray, x: float, y: float, radius: float, value: bool = True):
    """Disque de rayon radius (pixels) centré en (x, y) = (colonne, ligne)."""
    height, width = mask.shape
    r = max(0.5, float(radius))
    x0, x1 = int(np.floor(x - r)), int(np.ceil(x + r)) + 1
    y0, y1 = int(np.floor(y - r)), int(np.ceil(y + r)) + 1
    cx0, cx1, cy0, cy1 = max(x0, 0), min(x1, width), max(y0, 0), min(y1, height)
    if cx0 >= cx1 or cy0 >= cy1:
        return
    cols = np.arange(cx0, cx1) + 0.5
    rows = np.arange(cy0, cy1) + 0.5
    inside = (cols[None, :] - x) ** 2 + (rows[:, None] - y) ** 2 <= r * r
    region = mask[cy0:cy1, cx0:cx1]
    region[inside] = value


def paint_stroke(mask: np.ndarray, start, end, radius: float, value: bool = True):
    """Trait continu de start à end : disques espacés d'au plus un demi-rayon."""
    (xa, ya), (xb, yb) = start, end
    length = float(np.hypot(xb - xa, yb - ya))
    steps = max(1, int(np.ceil(length / max(0.5, radius / 2.0))))
    for t in np.linspace(0.0, 1.0, steps + 1):
        paint_disk(mask, xa + t * (xb - xa), ya + t * (yb - ya), radius, value)


def rgb(image: np.ndarray) -> np.ndarray:
    """Image (lignes, colonnes[, canaux]) -> RGB flottant (lignes, colonnes, 3)."""
    image = np.asarray(image)
    if image.ndim == 2:
        return np.repeat(image[..., None].astype(float), 3, axis=2)
    return image[..., :3].astype(float)


def color_distance(image: np.ndarray, color) -> np.ndarray:
    """Distance euclidienne RGB (0..441) de chaque pixel à color."""
    return np.linalg.norm(rgb(image) - np.asarray(color, dtype=float)[:3], axis=2)


def color_filter(image: np.ndarray, color, tolerance: float) -> np.ndarray:
    """Pixels dont la couleur est à moins de tolerance de color."""
    return color_distance(image, color) <= float(tolerance)


def dominant_color(image: np.ndarray, region: np.ndarray, background_threshold=200.0):
    """
    Couleur la plus fréquente parmi les pixels non clairs de region : couleur probable
    de la courbe peinte. None si la région ne contient que du fond.
    """
    pixels = rgb(image)[region]
    if pixels.size == 0:
        return None
    pixels = pixels[pixels.mean(axis=1) < background_threshold]
    if len(pixels) == 0:
        return None
    # couleurs regroupées par cases de 16 niveaux, puis moyenne de la case la plus remplie
    keys = (pixels // 16).astype(int)
    codes = keys[:, 0] * 256 + keys[:, 1] * 16 + keys[:, 2]
    values, counts = np.unique(codes, return_counts=True)
    best = codes == values[np.argmax(counts)]
    return tuple(int(round(v)) for v in pixels[best].mean(axis=0))


def foreground(image: np.ndarray, mask: np.ndarray | None, color, tolerance: float):
    """
    Pixels de la courbe : couleur proche de color, dans le masque (toute l'image si le
    masque est absent ou vide).
    """
    selected = color_filter(image, color, tolerance)
    if mask is not None and mask.any():
        selected &= mask
    return selected
