# view/canvas.py
"""
Image du graphique à numériser et tout ce qui se dessine dessus : masque, pixels détectés,
points de calibration, courbes relevées et modèles ajustés.

Repère : celui de l'image, en pixels (x = colonne, y = ligne vers le bas). L'image est
affichée en « row-major » dans une ViewBox à Y inversé : un tableau (lignes, colonnes)
s'affiche tel quel, sans retournement ni transposition.

Le canevas ne décide de rien : hors du mode navigation, les clics gauches sont convertis
en pixels de l'image et émis (pressed, moved, released) ; le contrôleur les interprète.
La molette et le bouton droit restent au zoom de pyqtgraph dans tous les modes.
"""
import enum

import numpy as np
import pyqtgraph as pg
from PyQt6 import QtCore, QtGui, QtWidgets


class Mode(enum.Enum):
    NAVIGATE = "Navigation"
    CALIBRATE = "Calibration"
    ADD = "Ajout / déplacement de points"
    DELETE = "Suppression de points"
    PAINT = "Pinceau du masque"
    ERASE = "Gomme du masque"
    PICK = "Pipette (couleur de la courbe)"


CURSORS = {
    Mode.NAVIGATE: QtCore.Qt.CursorShape.OpenHandCursor,
    Mode.CALIBRATE: QtCore.Qt.CursorShape.CrossCursor,
    Mode.ADD: QtCore.Qt.CursorShape.CrossCursor,
    Mode.DELETE: QtCore.Qt.CursorShape.PointingHandCursor,
    Mode.PAINT: QtCore.Qt.CursorShape.BlankCursor,
    Mode.ERASE: QtCore.Qt.CursorShape.BlankCursor,
    Mode.PICK: QtCore.Qt.CursorShape.CrossCursor,
}

MASK_RGBA = (255, 200, 0, 255)
DETECTION_RGBA = (0, 200, 255, 255)
CALIBRATION_LABELS = ("X1", "X2", "Y1", "Y2")


def _rgba(color, alpha=255):
    c = pg.mkColor(color)
    return (c.red(), c.green(), c.blue(), alpha)


class ImageCanvas(pg.GraphicsLayoutWidget):
    pressed = QtCore.pyqtSignal(float, float)
    moved = QtCore.pyqtSignal(float, float, bool)       # x, y, bouton gauche enfoncé
    released = QtCore.pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mode = Mode.NAVIGATE
        self._left_down = False
        self._shape = None
        self.brush_radius = 8.0

        self.view_box = self.addViewBox(lockAspect=True, invertY=True)
        self.view_box.setMenuEnabled(False)
        self.image_item = pg.ImageItem(axisOrder="row-major")
        self.image_item.setZValue(-100)
        self.mask_item = pg.ImageItem(axisOrder="row-major")
        self.mask_item.setOpacity(0.35)
        self.mask_item.setZValue(-50)
        self.detection_item = pg.ImageItem(axisOrder="row-major")
        self.detection_item.setOpacity(0.8)
        self.detection_item.setZValue(-40)
        for item in (self.image_item, self.mask_item, self.detection_item):
            self.view_box.addItem(item)
        self._mask_rgba = None

        # calibration : repères, segments X1-X2 et Y1-Y2
        self.calibration_lines = [pg.PlotCurveItem(pen=pg.mkPen("#0B6BCB", width=1.5,
                                                                style=QtCore.Qt.PenStyle.DashLine))
                                  for _ in range(2)]
        self.calibration_points = pg.ScatterPlotItem(
            size=13, symbol="+", pen=pg.mkPen("#0B6BCB", width=2), brush=None, pxMode=True)
        self.calibration_texts = []
        for item in (*self.calibration_lines, self.calibration_points):
            item.setZValue(30)
            self.view_box.addItem(item)

        self.dataset_items = []          # (points, modèle) par courbe affichée

        # curseur du pinceau : cercle du rayon réel, en pixels de l'image
        self.brush_cursor = QtWidgets.QGraphicsEllipseItem()
        self.brush_cursor.setPen(pg.mkPen("#FF8800", width=1.5))
        self.brush_cursor.setZValue(50)
        self.brush_cursor.setVisible(False)
        self.view_box.addItem(self.brush_cursor, ignoreBounds=True)

        self.scene().installEventFilter(self)
        self.set_mode(Mode.NAVIGATE)

    # ============================================================ image et calques
    def set_image(self, image: np.ndarray | None):
        if image is None:
            self.image_item.clear()
            self._shape = None
            self.set_mask(None)
            self.set_detection(None)
            return
        self._shape = image.shape[:2]
        self.image_item.setImage(image, autoLevels=False, levels=(0, 255))
        self.view_box.autoRange(padding=0.02)

    def set_mask(self, mask: np.ndarray | None):
        """Masque entier (nouvelle image, effacement, chargement)."""
        if mask is None or not mask.any():
            self._mask_rgba = None if mask is None else np.zeros(mask.shape + (4,), np.uint8)
            self.mask_item.clear()
            return
        self._mask_rgba = np.zeros(mask.shape + (4,), np.uint8)
        self._mask_rgba[mask] = MASK_RGBA
        self.mask_item.setImage(self._mask_rgba, autoLevels=False, levels=(0, 255))

    def update_mask(self, mask: np.ndarray, x0: int, y0: int, x1: int, y1: int):
        """Recopie la zone [y0:y1, x0:x1] du masque (pendant un coup de pinceau)."""
        if self._mask_rgba is None or self._mask_rgba.shape[:2] != mask.shape:
            self.set_mask(mask)
            if self._mask_rgba is None:
                self._mask_rgba = np.zeros(mask.shape + (4,), np.uint8)
        region = self._mask_rgba[y0:y1, x0:x1]
        region[...] = 0
        region[mask[y0:y1, x0:x1]] = MASK_RGBA
        self.mask_item.setImage(self._mask_rgba, autoLevels=False, levels=(0, 255))

    def set_detection(self, binary: np.ndarray | None):
        """Pixels retenus par le filtre de couleur (aperçu), None pour masquer."""
        if binary is None:
            self.detection_item.clear()
            return
        rgba = np.zeros(binary.shape + (4,), np.uint8)
        rgba[binary] = DETECTION_RGBA
        self.detection_item.setImage(rgba, autoLevels=False, levels=(0, 255))

    # ============================================================ calibration
    def set_calibration_points(self, points):
        """Points pointés (0 à 4), dans l'ordre X1, X2, Y1, Y2."""
        for text in self.calibration_texts:
            self.view_box.removeItem(text)
        self.calibration_texts = []
        points = [tuple(p) for p in points]
        if points:
            self.calibration_points.setData(pos=points)
        else:
            self.calibration_points.clear()
        for label, (x, y) in zip(CALIBRATION_LABELS, points):
            text = pg.TextItem(label, color="#0B6BCB", anchor=(-0.15, 1.1))
            text.setPos(x, y)
            text.setZValue(31)
            self.view_box.addItem(text)
            self.calibration_texts.append(text)
        for line, pair in zip(self.calibration_lines, (points[0:2], points[2:4])):
            if len(pair) == 2:
                line.setData([pair[0][0], pair[1][0]], [pair[0][1], pair[1][1]])
            else:
                line.setData([], [])

    # ============================================================ courbes
    def set_datasets(self, curves):
        """
        curves : liste de dict {pixels, color, active, model} ; model : pixels (N, 2) de la
        courbe du modèle ajusté, ou None.
        """
        for points, model in self.dataset_items:
            self.view_box.removeItem(points)
            self.view_box.removeItem(model)
        self.dataset_items = []
        for curve in curves:
            pixels = np.asarray(curve["pixels"], dtype=float).reshape(-1, 2)
            active = curve.get("active", False)
            color = curve["color"]
            points = pg.PlotDataItem(
                pixels[:, 0], pixels[:, 1],
                pen=pg.mkPen(color, width=1.5 if active else 1),
                symbol="o", symbolSize=9 if active else 6,
                symbolPen=pg.mkPen("#000000" if active else color, width=1),
                symbolBrush=pg.mkBrush(_rgba(color, 230 if active else 150)))
            points.setZValue(20 if active else 10)
            model = pg.PlotCurveItem(pen=pg.mkPen(color, width=1.5,
                                                  style=QtCore.Qt.PenStyle.DashLine))
            model.setZValue(9)
            if curve.get("model") is not None and len(curve["model"]):
                m = np.asarray(curve["model"], dtype=float)
                model.setData(m[:, 0], m[:, 1], connect="finite")
            for item in (points, model):
                self.view_box.addItem(item, ignoreBounds=True)
            self.dataset_items.append((points, model))

    # ============================================================ modes et souris
    def set_mode(self, mode: Mode):
        self.mode = mode
        self.setCursor(CURSORS[mode])
        self.brush_cursor.setVisible(False)

    def set_brush_radius(self, radius: float):
        self.brush_radius = float(radius)

    def pixel_size(self) -> float:
        """Taille d'un pixel de l'écran en pixels de l'image (tolérance de clic)."""
        size = self.view_box.viewPixelSize()
        return float(max(size[0], size[1])) if size else 1.0

    def _image_pos(self, scene_pos):
        point = self.view_box.mapSceneToView(scene_pos)
        return point.x(), point.y()

    def _inside(self, scene_pos) -> bool:
        return self.view_box.sceneBoundingRect().contains(scene_pos)

    def _update_brush_cursor(self, x, y):
        if self.mode in (Mode.PAINT, Mode.ERASE):
            r = self.brush_radius
            self.brush_cursor.setRect(QtCore.QRectF(x - r, y - r, 2 * r, 2 * r))
            self.brush_cursor.setPen(pg.mkPen("#FF8800" if self.mode == Mode.PAINT else "#888888",
                                              width=1.5, cosmetic=True))
            self.brush_cursor.setVisible(True)

    def eventFilter(self, obj, event):
        if self.mode == Mode.NAVIGATE or self._shape is None:
            return False
        kind = event.type()
        Type = QtCore.QEvent.Type
        left = QtCore.Qt.MouseButton.LeftButton
        if kind == Type.GraphicsSceneMousePress:
            if event.button() != left or not self._inside(event.scenePos()):
                return False
            self._left_down = True
            self.pressed.emit(*self._image_pos(event.scenePos()))
            event.accept()
            return True
        if kind == Type.GraphicsSceneMouseMove:
            x, y = self._image_pos(event.scenePos())
            self._update_brush_cursor(x, y)
            down = self._left_down and bool(event.buttons() & left)
            self.moved.emit(x, y, down)
            return down
        if kind == Type.GraphicsSceneMouseRelease:
            if event.button() != left or not self._left_down:
                return False
            self._left_down = False
            self.released.emit(*self._image_pos(event.scenePos()))
            event.accept()
            return True
        return False

    def leaveEvent(self, event):
        self.brush_cursor.setVisible(False)
        super().leaveEvent(event)
