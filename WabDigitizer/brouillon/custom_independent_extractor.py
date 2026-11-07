
import numpy as np
from scipy.interpolate import CubicSpline

from averaging_window_extractor import AveragingWindowExtractor


class CustomIndependentExtractor:
    """
    Extraction avec abscisses physiques imposées.

    Pipeline :

        masque binaire
            ↓
        extraction dense en repère image
            ↓
        conversion image -> plot
            ↓
        conversion plot -> unités physiques
            ↓
        nettoyage / moyennage local
            ↓
        spline cubique
            ↓
        évaluation sur les X physiques imposés
            ↓
        résultat en unités physiques

    Ce mode est particulièrement adapté aux modèles PLECS, car il impose
    une grille X commune à toutes les courbes.
    """

    def __init__(
            self,
            curve_width_px=5.0,
            x_step_px=5.0,
            y_step_px=5.0,
            allow_extrapolation=False):

        self.curve_width_px = float(curve_width_px)
        self.x_step_px = float(x_step_px)
        self.y_step_px = float(y_step_px)
        self.allow_extrapolation = bool(allow_extrapolation)

    # ============================================================
    # API PRINCIPALE
    # ============================================================

    def extract(
            self,
            binary_mask,
            coordinate_transformer,
            x_values,
            image_to_plot_func=None):
        """
        Extrait une courbe sur des abscisses physiques imposées.

        Parameters
        ----------
        binary_mask : ndarray
            Masque binaire dans le repère local de imageItem.image.

        coordinate_transformer : CoordinateTransformer
            Convertisseur plot <-> unités physiques.

        x_values : array-like
            Abscisses physiques sur lesquelles évaluer la courbe.

        image_to_plot_func : callable or None
            Fonction transformant des points image locaux en points plot.
            Signature attendue :

                points_plot = image_to_plot_func(points_image)

            Si None, on suppose que les points extraits sont déjà dans le
            repère plot. Dans ton application actuelle, il faut fournir
            MainWindow.imagePointsToPlot.
        """

        x_values = self.prepare_x_values(x_values)

        if len(x_values) == 0:
            return np.empty((0, 2), dtype=float)

        # --------------------------------------------------------
        # 1) Extraction dense en repère image
        # --------------------------------------------------------

        averaging = AveragingWindowExtractor(
            x_step=self.x_step_px,
            y_step=self.y_step_px
        )

        dense_image_points = averaging.extract(binary_mask)

        if len(dense_image_points) < 4:
            return np.empty((0, 2), dtype=float)

        # --------------------------------------------------------
        # 2) Repère image -> repère plot
        # --------------------------------------------------------

        if image_to_plot_func is not None:
            dense_plot_points = image_to_plot_func(dense_image_points)
        else:
            dense_plot_points = dense_image_points

        if len(dense_plot_points) < 4:
            return np.empty((0, 2), dtype=float)

        # --------------------------------------------------------
        # 3) Repère plot -> unités physiques
        # --------------------------------------------------------

        dense_data_points = coordinate_transformer.pixel_to_data(
            dense_plot_points
        )

        dense_data_points = self.clean_data_curve(
            dense_data_points
        )

        if len(dense_data_points) < 4:
            return np.empty((0, 2), dtype=float)

        # --------------------------------------------------------
        # 4) Moyennage local optionnel, basé sur la distance pixel plot
        # --------------------------------------------------------

        dense_data_points = self.local_average_by_pixel_distance(
            dense_data_points,
            coordinate_transformer
        )

        dense_data_points = self.clean_data_curve(
            dense_data_points
        )

        if len(dense_data_points) < 4:
            return np.empty((0, 2), dtype=float)

        # --------------------------------------------------------
        # 5) Domaine autorisé
        # --------------------------------------------------------

        xmin = np.min(dense_data_points[:, 0])
        xmax = np.max(dense_data_points[:, 0])

        if not self.allow_extrapolation:
            valid = (
                (x_values >= xmin)
                &
                (x_values <= xmax)
            )
            x_values_eval = x_values[valid]
        else:
            x_values_eval = x_values

        if len(x_values_eval) == 0:
            return np.empty((0, 2), dtype=float)

        # --------------------------------------------------------
        # 6) Spline cubique
        # --------------------------------------------------------

        spline = CubicSpline(
            dense_data_points[:, 0],
            dense_data_points[:, 1],
            extrapolate=self.allow_extrapolation
        )

        y_values = spline(x_values_eval)

        result = np.column_stack(
            (
                x_values_eval,
                y_values
            )
        )

        result = result[
            np.isfinite(result).all(axis=1)
        ]

        return result

    # ============================================================
    # GRILLES D'ABSCISSES
    # ============================================================

    def extract_uniform_grid(
            self,
            binary_mask,
            coordinate_transformer,
            xmin,
            xmax,
            step,
            image_to_plot_func=None):
        """
        Extraction avec grille uniforme :

            xmin, xmin + step, ..., xmax
        """

        if step <= 0:
            raise ValueError("Step must be positive.")

        x_values = np.arange(
            xmin,
            xmax + 0.5 * step,
            step
        )

        return self.extract(
            binary_mask=binary_mask,
            coordinate_transformer=coordinate_transformer,
            x_values=x_values,
            image_to_plot_func=image_to_plot_func
        )

    def extract_linspace_grid(
            self,
            binary_mask,
            coordinate_transformer,
            xmin,
            xmax,
            point_count,
            image_to_plot_func=None):
        """
        Extraction avec nombre fixe de points.
        """

        if point_count < 2:
            raise ValueError("point_count must be >= 2.")

        x_values = np.linspace(
            xmin,
            xmax,
            int(point_count)
        )

        return self.extract(
            binary_mask=binary_mask,
            coordinate_transformer=coordinate_transformer,
            x_values=x_values,
            image_to_plot_func=image_to_plot_func
        )

    def extract_reference_grid(
            self,
            binary_mask,
            coordinate_transformer,
            reference_curve,
            image_to_plot_func=None):
        """
        Extraction sur les mêmes abscisses qu'une courbe de référence.

        reference_curve : ndarray Nx2 en unités physiques.
        """

        reference_curve = np.asarray(
            reference_curve,
            dtype=float
        )

        if (
            reference_curve.ndim != 2
            or
            reference_curve.shape[1] != 2
        ):
            return np.empty((0, 2), dtype=float)

        x_values = reference_curve[:, 0]

        return self.extract(
            binary_mask=binary_mask,
            coordinate_transformer=coordinate_transformer,
            x_values=x_values,
            image_to_plot_func=image_to_plot_func
        )

    # ============================================================
    # UTILITAIRES
    # ============================================================

    @staticmethod
    def prepare_x_values(x_values):
        """
        Nettoie les abscisses utilisateur.
        """

        x_values = np.asarray(
            x_values,
            dtype=float
        )

        x_values = x_values[
            np.isfinite(x_values)
        ]

        if len(x_values) == 0:
            return x_values

        x_values = np.unique(x_values)
        x_values.sort()

        return x_values

    @staticmethod
    def clean_data_curve(points):
        """
        Trie la courbe par X croissant et fusionne les doublons numériques
        de X par moyenne des Y.
        """

        points = np.asarray(points, dtype=float)

        if points.ndim != 2 or points.shape[1] != 2:
            return np.empty((0, 2), dtype=float)

        points = points[
            np.isfinite(points).all(axis=1)
        ]

        if len(points) == 0:
            return points

        order = np.argsort(points[:, 0])
        points = points[order]

        x = points[:, 0]
        y = points[:, 1]

        unique_x = []
        mean_y = []

        i = 0

        while i < len(points):

            xi = x[i]
            values = [y[i]]

            j = i + 1

            while j < len(points) and abs(x[j] - xi) < 1e-12:
                values.append(y[j])
                j += 1

            unique_x.append(xi)
            mean_y.append(float(np.mean(values)))

            i = j

        return np.column_stack(
            (
                np.asarray(unique_x),
                np.asarray(mean_y)
            )
        )

    def local_average_by_pixel_distance(
            self,
            data_points,
            coordinate_transformer):
        """
        Moyennage local inspiré de WebPlotDigitizer.

        Ici, les points sont en unités physiques, mais on repasse en coordonnées
        plot pour appliquer une notion de largeur de courbe en pixels.
        """

        if self.curve_width_px <= 0:
            return data_points

        if len(data_points) < 2:
            return data_points

        pixel_points = coordinate_transformer.data_to_pixel(
            data_points
        )

        averaged = []

        step_size = int(self.curve_width_px / 2.0)

        if step_size < 1:
            step_size = 1

        for idx in range(0, len(data_points), step_size):

            current_px = pixel_points[idx]

            neighbor_indices = []

            for n_idx in range(len(data_points)):

                n_px = pixel_points[n_idx]

                if (
                    abs(current_px[0] - n_px[0]) < self.curve_width_px
                    and
                    abs(current_px[1] - n_px[1]) < self.curve_width_px
                ):
                    neighbor_indices.append(n_idx)

            if len(neighbor_indices) == 0:
                continue

            mean_x = np.mean(
                data_points[neighbor_indices, 0]
            )

            mean_y = np.mean(
                data_points[neighbor_indices, 1]
            )

            averaged.append(
                [
                    mean_x,
                    mean_y
                ]
            )

        if len(averaged) == 0:
            return data_points

        return np.asarray(
            averaged,
            dtype=float
        )
