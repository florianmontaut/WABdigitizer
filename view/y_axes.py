# view/y_axes.py
"""
Axes d'ordonnées multiples d'un graphique temporel (repris de loggerFPGA,
logger_app/controller/y_axes.py, sans l'alignement des zéros sur des repères).

Les signaux sont répartis en groupes, un axe par groupe, MAX_AXES au plus : la première
moitié à gauche du graphique, le reste à droite. Le premier groupe garde la ViewBox et
l'axe de gauche du PlotItem (zoom, déplacement, curseur) ; chaque autre groupe a une
AxisScale : une ViewBox sous la principale, de même géométrie et d'axe X lié, et son axe
dans une colonne ajoutée à la mise en page du PlotItem.

Souris :
    - molette dans le graphique : zoom en X seulement (TimeViewBox) ;
    - déplacement dans le graphique : les autres échelles suivent la principale par une
      relation affine (y = a * y_principal + b), toutes les courbes bougent ensemble ;
    - glisser ou molette SUR un axe : seule l'échelle de cet axe change.
"""
import pyqtgraph as pg

MAX_AXES = 8
AXIS_WIDTH = 58             # largeur d'un axe supplémentaire (px)
LEFT_COLUMNS = 3            # colonnes réservées à gauche de l'axe principal
RIGHT_COLUMNS = 4           # colonnes à droite du graphique
MAIN_COLUMN = LEFT_COLUMNS  # colonne de l'axe de gauche du PlotItem après reserve_columns
FIT_MARGIN = 0.03           # marge de l'ajustement aux données, en part de l'étendue

# répartition des signaux (liste de la barre d'outils)
MODES = {"unit": "Un axe par unité", "channel": "Un axe par voie", "single": "Axe unique",
         "split": "Graphiques séparés"}


def groups(keys: list, unit_of, mode: str) -> list:
    """
    Signaux répartis par axe (ou par graphique en mode « split », par unité).
    « channel » au-delà de MAX_AXES signaux : par unité ; groupes au-delà de MAX_AXES :
    réunis sur le dernier axe (sauf « split », sans limite).
    """
    keys = list(keys)
    if mode == "single" or len(keys) <= 1:
        return [keys] if keys else []
    if mode == "channel" and len(keys) <= MAX_AXES:
        return [[k] for k in keys]
    by_unit = {}
    for k in keys:
        by_unit.setdefault(unit_of(k) or "", []).append(k)
    result = list(by_unit.values())
    if mode != "split" and len(result) > MAX_AXES:
        result[MAX_AXES - 1:] = [sum(result[MAX_AXES - 1:], [])]
    return result


def columns(count: int) -> list:
    """(côté, colonne de la mise en page) de chaque groupe ; le premier : axe principal."""
    left = (count + 1) // 2
    return [("left", MAIN_COLUMN - g) if g < left
            else ("right", MAIN_COLUMN + 3 + g - left) for g in range(count)]


def reserve_columns(plot: pg.PlotItem):
    """
    Mise en page du PlotItem décalée de LEFT_COLUMNS colonnes : place des axes
    supplémentaires à gauche (pyqtgraph met l'axe de gauche en colonne 0).
    """
    layout = plot.layout
    items = [(plot.titleLabel, 0, 1), (plot.getAxis("top"), 1, 1),
             (plot.getAxis("left"), 2, 0), (plot.vb, 2, 1), (plot.getAxis("right"), 2, 2),
             (plot.getAxis("bottom"), 3, 1)]
    for item, _row, _col in items:
        layout.removeItem(item)
    for item, row, col in items:
        layout.addItem(item, row, col + LEFT_COLUMNS)
    total = LEFT_COLUMNS + 3 + RIGHT_COLUMNS
    for col in range(total):
        layout.setColumnPreferredWidth(col, 0)
        layout.setColumnMinimumWidth(col, 0)
        layout.setColumnSpacing(col, 0)
        layout.setColumnStretchFactor(col, 1)
    layout.setColumnStretchFactor(MAIN_COLUMN + 1, 100)
    for col in list(range(LEFT_COLUMNS)) + list(range(MAIN_COLUMN + 3, total)):
        layout.setColumnFixedWidth(col, 0)


class MainAxis(pg.AxisItem):
    """
    Axe de gauche du PlotItem. `direct` est vrai pendant un glissement ou une molette sur
    l'axe : les autres échelles ne suivent pas (seule celle de cet axe change).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.direct = False

    def mouseDragEvent(self, event):
        self.direct = True
        try:
            super().mouseDragEvent(event)
        finally:
            self.direct = False

    def wheelEvent(self, event):
        self.direct = True
        try:
            super().wheelEvent(event)
        finally:
            self.direct = False


def style_axis(axis: pg.AxisItem, text: str, unit: str | None, color=None):
    """Titre, unité et couleur (celle du signal d'un axe à un seul signal)."""
    if color is None:
        axis.setPen()
        axis.setTextPen()
    else:
        axis.setPen(pg.mkPen(color))
        axis.setTextPen(pg.mkPen(color))
    axis.setLabel(text, units=unit or None)


def fit_range(bounds: tuple) -> tuple:
    """Plage ajustée à des données (bornes y0, y1), avec une petite marge."""
    y0, y1 = bounds
    width = y1 - y0
    if width <= 0:
        width = max(abs(y0), abs(y1)) * 0.1 or 1.0
        y0, y1 = y0 - width / 2, y1 + width / 2
    margin = FIT_MARGIN * width
    return y0 - margin, y1 + margin


class TimeViewBox(pg.ViewBox):
    """
    ViewBox d'un graphique temporel : la molette dans la zone de tracé ne zoome qu'en X.
    L'échelle verticale se règle sur son axe (molette ou glissement sur ses graduations,
    AxisItem.wheelEvent précise alors l'axe).
    """

    def wheelEvent(self, ev, axis=None):
        super().wheelEvent(ev, axis=0 if axis is None else axis)


class ScaleViewBox(TimeViewBox):
    """
    ViewBox d'une échelle ajoutée : elle ne répond qu'à son axe (glissement ou molette
    sur ses graduations). Dans la zone de tracé, la souris va à la ViewBox principale.
    """

    def mouseDragEvent(self, ev, axis=None):
        if axis is None:
            ev.ignore()
        else:
            super().mouseDragEvent(ev, axis=axis)

    def wheelEvent(self, ev, axis=None):
        if axis is None:
            ev.ignore()
        else:
            super().wheelEvent(ev, axis=axis)

    def mouseClickEvent(self, ev):
        ev.ignore()


class AxisScale:
    """Échelle d'un groupe de signaux au-delà du premier : sa ViewBox et son axe."""

    def __init__(self, plot: pg.PlotItem, side: str, column: int):
        self.plot = plot
        self.main_vb = plot.vb
        self.side = side
        self.column = column
        self.a, self.b = 1.0, 0.0
        self.vb = ScaleViewBox(enableMenu=False)
        self.vb.setParentItem(plot)
        # sous la ViewBox principale : elle reçoit la souris (zoom, déplacement, curseur)
        self.vb.setZValue(self.main_vb.zValue() - 1)
        self.vb.setMouseEnabled(x=False, y=True)
        self.vb.setXLink(self.main_vb)
        self.vb.setGeometry(self.main_vb.geometry())
        self.axis = pg.AxisItem(side)
        self.axis.linkToView(self.vb)
        self.axis.setWidth(AXIS_WIDTH)
        plot.layout.addItem(self.axis, 2, column)
        plot.layout.setColumnFixedWidth(column, AXIS_WIDTH)
        self.main_vb.sigResized.connect(self._sync_geometry)
        self.vb.sigRangeChangedManually.connect(self.store_relation)

    def _sync_geometry(self):
        self.vb.setGeometry(self.main_vb.geometry())
        self.vb.linkedViewChanged(self.main_vb, self.vb.XAxis)

    def follow(self):
        """Plage déduite de celle de l'axe principal (zoom / déplacement du graphique)."""
        m0, m1 = self.main_vb.viewRange()[1]
        self.vb.setYRange(self.a * m0 + self.b, self.a * m1 + self.b, padding=0)

    def store_relation(self, *_):
        """Relation entre la plage de cette échelle et celle de l'axe principal."""
        m0, m1 = self.main_vb.viewRange()[1]
        s0, s1 = self.vb.viewRange()[1]
        if m1 - m0 == 0:
            return
        self.a = (s1 - s0) / (m1 - m0)
        self.b = s0 - self.a * m0
