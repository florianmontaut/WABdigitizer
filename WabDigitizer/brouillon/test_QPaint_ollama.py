from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QImage, QPixmap
from PyQt6.QtWidgets import QGraphicsRectItem
import pyqtgraph as pg
import numpy as np

class MaskPainter(pg.GraphicsObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.isDrawing = False
        self.lastPos = QPointF()
        self.maskImage = None
        self.maskItem = None
        self.brushSize = 10
        self.brushColor = QColor(255, 0, 0, 100)  # Semi-transparent red
        self.points = []  # Store drawing points for mask generation

    def attachToView(self, view):
        """Attach the mask painter to a view"""
        self.view = view

        # Create mask overlay item
        self.maskItem = pg.ImageItem()
        self.maskItem.setZValue(5)  # Above image but below curves/ROIs
        view.addItem(self.maskItem)

        # Initialize with transparent mask
        self.clearMask()

        # Connect mouse events
        view.scene().sigMouseClicked.connect(self.mouseClickEvent)
        view.scene().sigMouseMoved.connect(self.mouseMoveEvent)

    def detachFromView(self):
        """Detach from view and clean up"""
        if hasattr(self, 'view'):
            try:
                self.view.scene().sigMouseClicked.disconnect(self.mouseClickEvent)
                self.view.scene().sigMouseMoved.disconnect(self.mouseMoveEvent)
            except:
                pass
            if self.maskItem and self.maskItem.scene():
                self.view.removeItem(self.maskItem)

    def clearMask(self):
        """Clear the mask to transparent"""
        if hasattr(self, 'view') and self.view:
            rect = self.view.sceneRect()
            size = (int(rect.height()), int(rect.width()))
            self.maskImage = np.zeros((size[0], size[1], 4), dtype=np.uint8)  # RGBA
            self.maskItem.setImage(self.maskImage, levels=(0, 255))
        self.points = []

    def mouseClickEvent(self, event):
        """Handle mouse clicks"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.isDrawing = True
            self.lastPos = self.view.mapSceneToView(event.scenePos())
            self.points = [self.lastPos]
            self.drawPoint(self.lastPos)
        elif event.button() == Qt.MouseButton.RightButton:
            self.clearMask()

    def mouseMoveEvent(self, pos):
        """Handle mouse movement"""
        if not self.isDrawing or not hasattr(self, 'view'):
            return

        scenePos = pos
        viewPos = self.view.mapSceneToView(scenePos)

        # Add point if far enough from last point
        if self.lastPos and self.lastPos.distanceTo(viewPos) > 2:
            self.points.append(viewPos)
            self.lastPos = viewPos
            self.drawPoint(viewPos)

    def mouseReleaseEvent(self, event):
        """Handle mouse release"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.isDrawing = False

    def drawPoint(self, pos):
        """Draw a single point on the mask"""
        if self.maskImage is None:
            return

        # Convert view coordinates to mask image coordinates
        viewRect = self.view.sceneRect()
        maskWidth = self.maskImage.shape[1]
        maskHeight = self.maskImage.shape[0]

        # Map view position to mask coordinates
        x = int((pos.x() - viewRect.x()) / viewRect.width() * maskWidth)
        y = int((pos.y() - viewRect.y()) / viewRect.height() * maskHeight)

        # Clamp to mask boundaries
        x = max(0, min(maskWidth - 1, x))
        y = max(0, min(maskHeight - 1, y))

        # Draw circle brush
        radius = self.brushSize // 2
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dx*dx + dy*dy <= radius*radius:
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < maskWidth and 0 <= ny < maskHeight:
                        # Semi-transparent red
                        self.maskImage[ny, nx] = [255, 0, 0, 100]

        # Update the displayed mask
        self.maskItem.setImage(self.maskImage, levels=(0, 255))

    def paint(self, painter, option, widget=None):
        """Required for GraphicsObject - not used as we use ImageItem"""
        pass

    def boundingRect(self):
        """Required for GraphicsObject"""
        if hasattr(self, 'view'):
            return self.view.sceneRect()
        return QRectF()

    def getMaskCoordinates(self):
        """Get coordinates of masked pixels in view coordinates"""
        if self.maskImage is None:
            return []

        # Find non-transparent pixels
        mask = self.maskImage[:, :, 3] > 0  # Alpha channel > 0
        ys, xs = np.where(mask)

        if len(xs) == 0:
            return []

        # Convert mask coordinates to view coordinates
        viewRect = self.view.sceneRect()
        maskWidth = self.maskImage.shape[1]
        maskHeight = self.maskImage.shape[0]

        points = []
        for x, y in zip(xs, ys):
            viewX = viewRect.x() + (x / maskWidth) * viewRect.width()
            viewY = viewRect.y() + (y / maskHeight) * viewRect.height()
            points.append(QPointF(viewX, viewY))

        return points

    def getMaskedImageRegion(self, originalImage):
        """
        Extract the region of the original image that corresponds to the mask
        Returns: numpy array of the masked region or None
        """
        if self.maskImage is None or originalImage is None:
            return None

        # Create binary mask from alpha channel
        binaryMask = self.maskImage[:, :, 3] > 0

        # Apply mask to original image (assuming same dimensions)
        if originalImage.shape[:2] == self.maskImage.shape[:2]:
            masked = originalImage.copy()
            # Set non-masked areas to transparent or zero
            if len(originalImage.shape) == 3:
                masked[~binaryMask] = [0, 0, 0, 0] if originalImage.shape[2] == 4 else [0, 0, 0]
            else:
                masked[~binaryMask] = 0
            return masked
        return None
