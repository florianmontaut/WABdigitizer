
import numpy as np
from skimage.morphology import skeletonize

from curve_simplifier import CurveSimplifier


class CurveExtractor:
    """
    Extraction automatique d'une courbe depuis :
        - l'image affichée par pyqtgraph.ImageItem ;
        - le masque binaire dessiné par MaskPainter.

    Les deux tableaux doivent être dans le même repère.
    """

    def __init__(self):
        self.grayThreshold = 240

        self.simplifier = CurveSimplifier(
            tolerance=2.0,
            mode="vertical"
        )

        self.enableSimplification = True

    def extract(self, image, binaryMask):
        """
        Retourne un tableau Nx2 de points [x, y] dans le repère imageItem.image.
        """

        if image is None:
            raise ValueError("CurveExtractor: image is None.")

        if binaryMask is None:
            raise ValueError("CurveExtractor: binaryMask is None.")

        if image.shape[:2] != binaryMask.shape:
            raise ValueError(
                f"Image and mask dimensions mismatch: "
                f"image={image.shape[:2]}, mask={binaryMask.shape}"
            )

        gray = self.toGray(image)

        candidates = gray < self.grayThreshold
        candidates &= binaryMask > 0

        skeleton = skeletonize(candidates)

        raw_points = self.skeletonToPoints(skeleton)

        if not self.enableSimplification:
            return raw_points

        simplified_points = self.simplifier.simplify(
            raw_points
        )

        return simplified_points

    @staticmethod
    def toGray(image):
        """
        Convertit une image RGB/RGBA/grayscale en grayscale.
        """

        if image.ndim == 2:
            return image.astype(float)

        if image.ndim == 3:
            return np.mean(image[..., :3], axis=2)

        raise ValueError(f"Unsupported image shape: {image.shape}")

    @staticmethod
    def skeletonToPoints(skeleton):
        """
        Convertit un squelette binaire en points [x, y].

        Convention utilisée ici :
            - axis 0 = X
            - axis 1 = Y
        """

        points = []

        width = skeleton.shape[0]

        for x in range(width):

            ys = np.where(
                skeleton[x, :]
            )[0]

            if len(ys) == 0:
                continue

            y = np.median(ys)

            points.append([x, y])

        if len(points) == 0:
            return np.empty((0, 2), dtype=float)

        return np.array(points, dtype=float)

    def setSimplificationTolerance(self, tolerance):
        """
        Définit la tolérance de simplification en pixels.
        """

        self.simplifier.tolerance = float(tolerance)

    def setSimplificationMode(self, mode):
        """
        Définit le mode de simplification :
            - "vertical"
            - "perpendicular"
        """

        if mode not in ("vertical", "perpendicular"):
            raise ValueError(
                "mode must be 'vertical' or 'perpendicular'"
            )

        self.simplifier.mode = mode


