
import numpy as np


class CoordinateTransformer:
    """
    Transformation entre coordonnées pixel/plot et coordonnées physiques.

    Convention :
        points_pixel[:, 0] = x pixel dans la zone graphique
        points_pixel[:, 1] = y pixel dans la zone graphique

    La zone graphique correspond au rectangle défini après calibration.
    """

    def __init__(
            self,
            plot_origin,
            scale):

        """
        Parameters
        ----------
        plot_origin : tuple/list
            [x0, y0, x1, y1] ou [x0, y0, width, height]
            selon ta convention actuelle issue de graph_area.rect().getCoords().

        scale : list
            [xmin, xmax, ymin, ymax, logX, logY]
        """

        self.origin = plot_origin
        self.scale = scale

        self.xmin = float(scale[0])
        self.xmax = float(scale[1])
        self.ymin = float(scale[2])
        self.ymax = float(scale[3])

        self.log_x = bool(scale[4])
        self.log_y = bool(scale[5])

        self.update()

    def update(self):
        """
        Prépare les coefficients de transformation.
        """

        x0, y0, x1, y1 = self.origin

        self.x0 = float(x0)
        self.y0 = float(y0)
        self.x1 = float(x1)
        self.y1 = float(y1)

        self.width = self.x1 - self.x0
        self.height = self.y1 - self.y0

        if abs(self.width) < 1e-12:
            raise ValueError("Invalid graph width.")

        if abs(self.height) < 1e-12:
            raise ValueError("Invalid graph height.")

        if self.log_x:
            if self.xmin <= 0 or self.xmax <= 0:
                raise ValueError("Log X axis requires positive bounds.")

            self.xmin_scaled = np.log10(self.xmin)
            self.xmax_scaled = np.log10(self.xmax)

        else:
            self.xmin_scaled = self.xmin
            self.xmax_scaled = self.xmax

        if self.log_y:
            if self.ymin <= 0 or self.ymax <= 0:
                raise ValueError("Log Y axis requires positive bounds.")

            self.ymin_scaled = np.log10(self.ymin)
            self.ymax_scaled = np.log10(self.ymax)

        else:
            self.ymin_scaled = self.ymin
            self.ymax_scaled = self.ymax

    # ============================================================
    # PIXEL -> DATA
    # ============================================================

    def pixel_to_data(self, points_pixel):
        """
        Convertit des points pixels en unités physiques.
        """

        points_pixel = np.asarray(points_pixel, dtype=float)

        if points_pixel.ndim != 2 or points_pixel.shape[1] != 2:
            return np.empty((0, 2), dtype=float)

        x_pix = points_pixel[:, 0]
        y_pix = points_pixel[:, 1]

        x_norm = (x_pix - self.x0) / self.width
        y_norm = (y_pix - self.y0) / self.height

        x_scaled = (
            self.xmin_scaled
            + x_norm * (self.xmax_scaled - self.xmin_scaled)
        )

        y_scaled = (
            self.ymin_scaled
            + y_norm * (self.ymax_scaled - self.ymin_scaled)
        )

        if self.log_x:
            x_data = np.power(10.0, x_scaled)
        else:
            x_data = x_scaled

        if self.log_y:
            y_data = np.power(10.0, y_scaled)
        else:
            y_data = y_scaled

        return np.column_stack((x_data, y_data))

    # Alias plus lisible pour ton pipeline
    image_to_data = pixel_to_data

    # ============================================================
    # DATA -> PIXEL
    # ============================================================

    def data_to_pixel(self, points_data):
        """
        Convertit des points physiques en coordonnées pixel/plot.
        """

        points_data = np.asarray(points_data, dtype=float)

        if points_data.ndim != 2 or points_data.shape[1] != 2:
            return np.empty((0, 2), dtype=float)

        x_data = points_data[:, 0]
        y_data = points_data[:, 1]

        if self.log_x:
            x_scaled = np.log10(x_data)
        else:
            x_scaled = x_data

        if self.log_y:
            y_scaled = np.log10(y_data)
        else:
            y_scaled = y_data

        x_norm = (
            (x_scaled - self.xmin_scaled)
            / (self.xmax_scaled - self.xmin_scaled)
        )

        y_norm = (
            (y_scaled - self.ymin_scaled)
            / (self.ymax_scaled - self.ymin_scaled)
        )

        x_pix = self.x0 + x_norm * self.width
        y_pix = self.y0 + y_norm * self.height

        return np.column_stack((x_pix, y_pix))
