
import numpy as np


class CurveSimplifier:
    """
    Réduction du nombre de points d'une courbe par algorithme
    de Douglas-Peucker.

    Deux modes sont disponibles :

        - "vertical" :
            erreur verticale entre la courbe et le segment.
            Recommandé pour les caractéristiques de datasheet y = f(x).

        - "perpendicular" :
            distance géométrique perpendiculaire classique.
    """

    def __init__(self, tolerance=2.0, mode="vertical"):
        self.tolerance = float(tolerance)
        self.mode = mode

    # ============================================================
    # API PRINCIPALE
    # ============================================================

    def simplify(self, points):
        """
        Réduit un tableau Nx2 de points.

        Parameters
        ----------
        points : np.ndarray
            Tableau de points [[x0, y0], [x1, y1], ...]

        Returns
        -------
        np.ndarray
            Points simplifiés.
        """

        points = self.prepare_points(points)

        if len(points) <= 2:
            return points

        keep_indexes = self._douglas_peucker(points,0,len(points) - 1)
        keep_indexes = sorted(set(keep_indexes))

        return points[keep_indexes]

    # ============================================================
    # PRETRAITEMENT
    # ============================================================

    @staticmethod
    def prepare_points(points):
        """
        Nettoie et trie les points par x croissant.

        Cette étape est importante car l'extraction automatique retourne
        normalement déjà les points dans l'ordre des colonnes, mais il est
        préférable de sécuriser le pipeline.
        """

        if points is None:
            return np.empty((0, 2), dtype=float)

        points = np.asarray(points, dtype=float)

        if points.ndim != 2 or points.shape[1] != 2:
            return np.empty((0, 2), dtype=float)

        if len(points) == 0:
            return points

        # Suppression NaN / Inf
        finite_mask = np.isfinite(points).all(axis=1)
        points = points[finite_mask]

        if len(points) == 0:
            return points

        # Tri par X croissant
        order = np.argsort(points[:, 0])
        points = points[order]

        # Suppression des doublons exacts sur x,y
        _, unique_indices = np.unique(points,axis=0,return_index=True)

        unique_indices = np.sort(unique_indices)

        return points[unique_indices]

    # ============================================================
    # DOUGLAS-PEUCKER
    # ============================================================

    def _douglas_peucker(self, points, start_index, end_index):
        """
        Version récursive de Douglas-Peucker.
        """

        if end_index <= start_index + 1:
            return [start_index, end_index]

        start_point = points[start_index]
        end_point = points[end_index]

        max_error = -1.0
        max_index = None

        for i in range(start_index + 1, end_index):

            point = points[i]

            if self.mode == "perpendicular":
                error = self.perpendicular_distance(
                                                    point,
                                                    start_point,
                                                    end_point
                                                    )
            else:
                error = self.vertical_error(
                                                point,
                                                start_point,
                                                end_point
                                            )

            if error > max_error:
                max_error = error
                max_index = i

        if max_error > self.tolerance and max_index is not None:

            left = self._douglas_peucker(
                                            points,
                                            start_index,
                                            max_index
                                        )

            right = self._douglas_peucker(
                                            points,
                                            max_index,
                                            end_index
                                        )

            return left[:-1] + right

        return [start_index, end_index]

    # ============================================================
    # ERREURS
    # ============================================================

    @staticmethod
    def vertical_error(point, start_point, end_point):
        """
        Erreur verticale entre un point et le segment start-end.

        On interpole y_segment au x du point, puis on mesure :

            abs(y_point - y_segment)
        """

        x, y = point

        x1, y1 = start_point
        x2, y2 = end_point

        dx = x2 - x1

        if abs(dx) < 1e-12:
            return abs(y - y1)

        alpha = (x - x1) / dx

        y_line = y1 + alpha * (y2 - y1)

        return abs(y - y_line)

    @staticmethod
    def perpendicular_distance(point, start_point, end_point):
        """
        Distance perpendiculaire classique d'un point à un segment.
        """

        p = np.asarray(point, dtype=float)
        a = np.asarray(start_point, dtype=float)
        b = np.asarray(end_point, dtype=float)

        ab = b - a

        norm_ab = np.linalg.norm(ab)

        if norm_ab < 1e-12:
            return np.linalg.norm(p - a)

        return abs(np.cross(ab, a - p)) / norm_ab
