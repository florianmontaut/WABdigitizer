from PyQt6 import QtCore
from PyQt6.QtCore import QObject, QEvent, QPointF, Qt
from PyQt6.QtGui import (QColor,QImage,QPainter,QPainterPath,QPen,)
import pyqtgraph as pg
import numpy as np


class MaskPainter(QObject):
    """
    Outil de dessin de masque directement dans le repère natif de l'image affichée
    par pyqtgraph.ImageItem.

    Points importants :
        - le masque a les mêmes dimensions que imageItem.image ;
        - les coordonnées souris sont converties Scene -> ImageItem local ;
        - le tracé est continu grâce à QPainterPath ;
        - le masque visuel RGBA et le masque binaire sont séparés.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.plotItem = None
        self.viewBox = None
        self.imageItem = None
        self.maskItem = None

        self.isDrawing = False
        self.lastImagePos = None
        self.currentPath = None

        self.brushSize = 20

        self.brushColor = QColor(255, 0, 0, 255)
        self.maskOpacity = 0.40


        self.imageWidth = 0
        self.imageHeight = 0

        self.visualQImage = None
        self.binaryQImage = None

        self.visualMaskArray = None
        self.binaryMaskArray = None

    # ============================================================
    # ATTACH / DETACH
    # ============================================================

    def attachToPlot(self, plotItem, imageItem):
        """
        Attache le MaskPainter à un PlotItem et à son ImageItem associé.

        plotItem : pyqtgraph.PlotItem
        imageItem : pyqtgraph.ImageItem
        """

        self.plotItem = plotItem
        self.viewBox = plotItem.getViewBox()
        self.imageItem = imageItem

        if self.imageItem is None:
            raise ValueError("MaskPainter: imageItem is None.")

        if self.maskItem is None:
            self.maskItem = pg.ImageItem()
            self.maskItem.setZValue(5)
            self.viewBox.addItem(self.maskItem)

        self.initializeMask()

        scene = self.plotItem.scene()
        scene.installEventFilter(self)

    def detachFromPlot(self):
        """
        Désactive le MaskPainter et retire l'eventFilter.
        """

        if self.plotItem is not None:
            try:
                self.plotItem.scene().removeEventFilter(self)
            except Exception:
                pass

        self.isDrawing = False
        self.lastImagePos = None
        self.currentPath = None

    # ============================================================
    # INITIALISATION MASQUE
    # ============================================================

    def initializeMask(self):
        """
        Initialise les calques de masque dans le repère de imageItem.image.

        Attention :
        pyqtgraph.ImageItem utilise usuellement une convention où la première
        dimension du tableau correspond à l'axe X affiché, et la seconde à l'axe Y.

        On crée donc :
            imageWidth  = image.shape[0]
            imageHeight = image.shape[1]
        """

        image = self.imageItem.image

        if image is None:
            raise ValueError("MaskPainter: imageItem.image is None.")

        self.imageWidth = int(image.shape[0])
        self.imageHeight = int(image.shape[1])

        self.visualQImage = QImage(
                                    self.imageWidth,
                                    self.imageHeight,
                                    QImage.Format.Format_RGBA8888
                                    )
        self.visualQImage.fill(QColor(0, 0, 0, 0))

        self.binaryQImage = QImage(
                                    self.imageWidth,
                                    self.imageHeight,
                                    QImage.Format.Format_Grayscale8
                                    )
        self.binaryQImage.fill(0)

        self.updateArraysFromQImages()
        self.updateMaskItem()

    def clearMask(self):
        """
        Efface complètement le masque.
        """

        if self.visualQImage is None or self.binaryQImage is None:
            return

        self.visualQImage.fill(QColor(0, 0, 0, 0))
        self.binaryQImage.fill(0)

        self.isDrawing = False
        self.lastImagePos = None
        self.currentPath = None

        self.updateArraysFromQImages()
        self.updateMaskItem()

    # ============================================================
    # EVENT FILTER
    # ============================================================

    def eventFilter(self, obj, event):
        """
        Intercepte les événements souris de la scène pyqtgraph.
        """

        if self.imageItem is None:
            return False

        event_type = event.type()

        if event_type == QEvent.Type.GraphicsSceneMousePress:
            return self.handleMousePress(event)

        if event_type == QEvent.Type.GraphicsSceneMouseMove:
            return self.handleMouseMove(event)

        if event_type == QEvent.Type.GraphicsSceneMouseRelease:
            return self.handleMouseRelease(event)

        return False

    def handleMousePress(self, event):
        """
        Clic gauche : début d'un tracé.
        Clic droit  : effacement du masque.
        """

        if event.button() == Qt.MouseButton.RightButton:
            self.clearMask()
            event.accept()
            return True

        if event.button() != Qt.MouseButton.LeftButton:
            return False

        image_pos = self.sceneToImagePos(event.scenePos())

        if image_pos is None:
            return False

        if not self.isInsideImage(image_pos):
            return False

        self.isDrawing = True
        self.lastImagePos = image_pos

        self.currentPath = QPainterPath()
        self.currentPath.moveTo(image_pos)


        self.drawDab(image_pos)
        self.refreshMask()

        event.accept()
        return True


    def handleMouseMove(self, event):
        """
        Dessin continu lorsque le clic gauche est maintenu.
        """

        if not self.isDrawing:
            return False

        image_pos = self.sceneToImagePos(event.scenePos())

        if image_pos is None:
            return False

        if not self.isInsideImage(image_pos):
            return False

        if self.lastImagePos is None:
            self.lastImagePos = image_pos
            return True

        segment_path = QPainterPath()
        segment_path.moveTo(self.lastImagePos)
        segment_path.lineTo(image_pos)

        if self.currentPath is not None:
            self.currentPath.lineTo(image_pos)

        self.drawPath(segment_path)

        self.lastImagePos = image_pos

        self.refreshMask()

        event.accept()
        return True

    def handleMouseRelease(self, event):
        """
        Fin du tracé.
        """

        if event.button() != Qt.MouseButton.LeftButton:
            return False

        self.isDrawing = False
        self.lastImagePos = None

        event.accept()
        return True

    # ============================================================
    # CONVERSIONS DE COORDONNEES
    # ============================================================

    def sceneToImagePos(self, scenePos):
        """
        Convertit une position scène vers le repère local de l'image.

        C'est cette ligne qui corrige le problème de translation appliquée
        dans setGraphGrid(), car elle passe par le mapping réel de imageItem.
        """

        if self.imageItem is None:
            return None

        try:
            return self.imageItem.mapFromScene(scenePos)
        except Exception:
            return None

    def isInsideImage(self, pos):
        """
        Vérifie que la position est dans les bornes de l'image.
        """

        return (
            0 <= pos.x() < self.imageWidth
            and
            0 <= pos.y() < self.imageHeight
        )

    # ============================================================
    # DESSIN
    # ============================================================

    def drawPath(self, path):
        """
        Dessine un segment continu dans :
            - le masque visuel RGBA ;
            - le masque binaire.
        La composition Source évite l'accumulation de transparence.
        """

        if path is None:
            return

        if self.visualQImage is None or self.binaryQImage is None:
            return

        # -------------------------------
        # Masque visuel
        # -------------------------------

        visual_painter = QPainter(self.visualQImage)

        # Important : évite les variations de transparence par recouvrement.
        visual_painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)

        # False = opacité plus uniforme.
        visual_painter.setRenderHint(QPainter.RenderHint.Antialiasing,False)

        visual_pen = QPen(self.brushColor)
        visual_pen.setWidth(self.brushSize)
        visual_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        visual_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        visual_painter.setPen(visual_pen)
        visual_painter.drawPath(path)
        visual_painter.end()

        # -------------------------------
        # Masque binaire
        # -------------------------------

        binary_painter = QPainter(self.binaryQImage)

        binary_painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)

        binary_painter.setRenderHint(QPainter.RenderHint.Antialiasing,False)

        binary_pen = QPen(QColor(255, 255, 255))
        binary_pen.setWidth(self.brushSize)
        binary_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        binary_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        binary_painter.setPen(binary_pen)
        binary_painter.drawPath(path)
        binary_painter.end()




    def drawDab(self, imagePos):
        """
        Dessine un point de pinceau circulaire.
        Utilisé au clic gauche simple.
        """

        if self.visualQImage is None or self.binaryQImage is None:
            return

        radius = self.brushSize / 2.0

        rect = QtCore.QRectF(
                            imagePos.x() - radius,
                            imagePos.y() - radius,
                            2.0 * radius,
                            2.0 * radius
                        )

        # -------------------------------
        # Masque visuel
        # -------------------------------

        visual_painter = QPainter(self.visualQImage)
        visual_painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        visual_painter.setRenderHint(QPainter.RenderHint.Antialiasing,False        )

        visual_painter.setPen(Qt.PenStyle.NoPen)
        visual_painter.setBrush(self.brushColor)
        visual_painter.drawEllipse(rect)
        visual_painter.end()

        # -------------------------------
        # Masque binaire
        # -------------------------------

        binary_painter = QPainter(self.binaryQImage)
        binary_painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        binary_painter.setRenderHint(QPainter.RenderHint.Antialiasing,False)
        binary_painter.setPen(Qt.PenStyle.NoPen)
        binary_painter.setBrush(QColor(255, 255, 255))
        binary_painter.drawEllipse(rect)
        binary_painter.end()



    def refreshMask(self):
        """
        Met à jour les tableaux numpy puis l'affichage pyqtgraph.
        """

        self.updateArraysFromQImages()
        self.updateMaskItem()

    # ============================================================
    # QIMAGE -> NUMPY
    # ============================================================

    def updateArraysFromQImages(self):
        """
        Convertit les QImage internes en numpy arrays.

        Convention :
            QImage est en mémoire [y, x]
            pyqtgraph.ImageItem attend ici [x, y]

        On transpose donc les deux premières dimensions pour retrouver
        l'orientation de imageItem.image.
        """

        self.visualMaskArray = self.qimageToRgbaArray(self.visualQImage)
        self.binaryMaskArray = self.qimageToGrayscaleArray(self.binaryQImage)

        self.visualMaskArray = np.swapaxes(self.visualMaskArray, 0, 1)
        self.binaryMaskArray = np.swapaxes(self.binaryMaskArray, 0, 1)

        self.binaryMaskArray = (self.binaryMaskArray > 0).astype(np.uint8)

    @staticmethod
    def qimageToRgbaArray(qimage):
        """
        Convertit une QImage RGBA8888 en ndarray uint8 [height, width, 4].
        """

        img = qimage.convertToFormat(QImage.Format.Format_RGBA8888)

        width = img.width()
        height = img.height()
        bytes_per_line = img.bytesPerLine()

        ptr = img.bits()
        ptr.setsize(height * bytes_per_line)

        arr = np.frombuffer(ptr, dtype=np.uint8)
        arr = arr.reshape((height, bytes_per_line))

        arr = arr[:, :width * 4]
        arr = arr.reshape((height, width, 4))

        return arr.copy()

    @staticmethod
    def qimageToGrayscaleArray(qimage):
        """
        Convertit une QImage Grayscale8 en ndarray uint8 [height, width].
        """

        img = qimage.convertToFormat(QImage.Format.Format_Grayscale8)

        width = img.width()
        height = img.height()
        bytes_per_line = img.bytesPerLine()

        ptr = img.bits()
        ptr.setsize(height * bytes_per_line)

        arr = np.frombuffer(ptr, dtype=np.uint8)
        arr = arr.reshape((height, bytes_per_line))

        arr = arr[:, :width]

        return arr.copy()

    # ============================================================
    # AFFICHAGE PYQTGRAPH
    # ============================================================

    def updateMaskItem(self):
        """
        Met à jour l'ImageItem du masque.

        Le maskItem reçoit :
            - la même transformation que imageItem ;
            - les mêmes coordonnées locales ;
            - une image RGBA dans la même convention [x, y, rgba].

        Le masque RGBA est opaque dans son tableau interne.
        La transparence visuelle est appliquée globalement via setOpacity().
        """
        

        if self.maskItem is None:
            return

        if self.visualMaskArray is None:
            return

        self.maskItem.setImage(
            self.visualMaskArray,
            levels=(0, 255),
            autoLevels=False
        )
        self.maskItem.setOpacity(self.maskOpacity)
        if self.imageItem is not None:
            self.maskItem.setTransform(self.imageItem.transform())
            self.maskItem.setPos(self.imageItem.pos())
            self.maskItem.setZValue(self.imageItem.zValue() + 10)

    # ============================================================
    # API PUBLIQUE
    # ============================================================

    def getBinaryMask(self):
        """
        Retourne le masque binaire dans le même repère que imageItem.image.
        """

        if self.binaryMaskArray is None:
            return None

        return self.binaryMaskArray.copy()

    def getVisualMask(self):
        """
        Retourne le masque RGBA dans le même repère que imageItem.image.
        """

        if self.visualMaskArray is None:
            return None

        return self.visualMaskArray.copy()

    def setBrushSize(self, size):
        self.brushSize = max(1, int(size))

    def setBrushColor(self, color):
        self.brushColor = color

