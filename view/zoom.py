# view/zoom.py
"""
Limites de zoom des graphiques (repris de loggerFPGA, logger_app/ressources/zoom.py).

Sans limite, la molette dézoome jusqu'à des étendues de 1e30 : pyqtgraph échoue alors
(« Maximum allowed dimension exceeded », QPainter inutilisable sous Windows) et
l'application plante. Chaque vue est donc bornée par ViewBox.setLimits :

    - dézoom maximal : étendue du contenu + marge de chaque côté ;
    - zoom maximal   : une fraction de l'étendue (ou quelques pixels de l'image).

Échelles log (PlotItem.setLogMode) : la ViewBox travaille en log10 ; les bornes sont
calculées sur les valeurs positives, en log10.
"""
import numpy as np
import pyqtgraph as pg

ZOOM_OUT_MARGIN = 0.5           # graphiques : dézoom jusqu'à une demi-étendue de chaque côté
MIN_FRACTION = 1e-6             # zoom maximal : 1e-6 de l'étendue
IMAGE_MARGIN = 1.5              # image : 1,5 fois sa plus grande dimension de chaque côté
IMAGE_MIN_PIXELS = 2.0          # image : zoom jusqu'à 2 pixels à l'écran au plus fort
NO_LIMIT = 1e307                # bornes « libres » de pyqtgraph (ViewBox.__init__)
EMPTY_RANGE = (0.0, 1.0)        # vue vide : étendue par défaut de pyqtgraph...
EMPTY_MARGIN = 5.0              # ... dézoomable jusqu'à 11 fois
EMPTY_IMAGE = 1000              # canevas sans image : comme une image de 1000 pixels


def bounds(values, log=False):
    """(min, max) des valeurs finies (positives et en log10 sur un axe log), ou None."""
    values = np.asarray(values, dtype=float).ravel()
    values = values[np.isfinite(values)]
    if log:
        values = values[values > 0]
        values = np.log10(values) if values.size else values
    if not values.size:
        return None
    return float(values.min()), float(values.max())


def _span(lo, hi) -> float:
    """Étendue ; un contenu plat (une valeur) garde une étendue non nulle."""
    width = hi - lo
    if width > 0:
        return width
    return max(abs(lo), abs(hi)) * 0.1 or 1.0


def limit_axis(vb: pg.ViewBox, axis: str, lo, hi, margin=ZOOM_OUT_MARGIN):
    """Bornes d'un axe ('x' ou 'y') autour de [lo, hi] (coordonnées de la vue)."""
    width = _span(lo, hi)
    m = margin * width
    vb.setLimits(**{f"{axis}Min": lo - m, f"{axis}Max": hi + m,
                    f"max{axis.upper()}Range": width + 2 * m,
                    f"min{axis.upper()}Range": width * MIN_FRACTION})


def clear(vb: pg.ViewBox):
    """Limites levées (à n'employer que si la vue est bornée autrement)."""
    vb.setLimits(xMin=-NO_LIMIT, xMax=NO_LIMIT, yMin=-NO_LIMIT, yMax=NO_LIMIT,
                 minXRange=None, maxXRange=None, minYRange=None, maxYRange=None)


def limit_plot(plot: pg.PlotItem, xs, ys, log_x=False, log_y=False,
               margin=ZOOM_OUT_MARGIN):
    """
    Graphique de courbes : bornes sur les données tracées (listes de tableaux ou
    tableaux). Sans donnée affichable sur un axe (graphique vide, à l'ouverture de
    l'application) : bornes par défaut, jamais de dézoom libre.
    """
    vb = plot.getViewBox()
    for axis, values, log in (("x", xs, log_x), ("y", ys, log_y)):
        b = bounds(np.concatenate([np.ravel(v) for v in values]) if len(values) else [], log)
        if b is None:
            limit_axis(vb, axis, *EMPTY_RANGE, margin=EMPTY_MARGIN)
        else:
            limit_axis(vb, axis, *b, margin=margin)


def limit_y_free(vb: pg.ViewBox, lo: float, hi: float, factor: float = 20.0):
    """
    Graphique à plusieurs échelles (repris de loggerFPGA) : seul le dézoom vertical est
    borné (`factor` fois l'étendue des données) ; la position reste libre (une voie peut
    être décalée par rapport aux autres, comme sur un oscilloscope).
    """
    width = _span(lo, hi)
    reach = factor * width
    vb.setLimits(yMin=lo - reach, yMax=hi + reach, maxYRange=2 * reach,
                 minYRange=width * MIN_FRACTION)


def limit_empty(plot: pg.PlotItem):
    """Graphique sans courbe : bornes par défaut."""
    limit_plot(plot, [], [])


def limit_image(vb: pg.ViewBox, shape):
    """
    Image (lignes, colonnes) dans une ViewBox à rapport d'aspect fixe : mêmes bornes
    d'étendue sur les deux axes (l'aspect impose l'un par l'autre), assez larges pour
    toute fenêtre ; zoom jusqu'à IMAGE_MIN_PIXELS pixels de l'image. Sans image : comme
    une image de EMPTY_IMAGE pixels.
    """
    rows, cols = shape[:2] if shape is not None else (EMPTY_IMAGE, EMPTY_IMAGE)
    size = float(max(rows, cols, 1))
    m = IMAGE_MARGIN * size
    vb.setLimits(xMin=-m, xMax=cols + m, yMin=-m, yMax=rows + m,
                 maxXRange=size + 2 * m, maxYRange=size + 2 * m,
                 minXRange=IMAGE_MIN_PIXELS, minYRange=IMAGE_MIN_PIXELS)
