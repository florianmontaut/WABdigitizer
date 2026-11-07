
import numpy as np


class AveragingWindowExtractor:
    """
    Portage Python simplifié de l'algorithme Averaging Window
    de WebPlotDigitizer.

    Entrée :
        binary_mask : ndarray bool/uint8, shape = (width, height)
                        ou même convention que imageItem.image.

    Sortie :
        points : ndarray Nx2 en pixels image/plot
    """

    def __init__(
            self,
            x_step=10,
            y_step=10):

        self.x_step = float(x_step)
        self.y_step = float(y_step)

    def extract(self, binary_mask):
        """
        Extrait une courbe sous forme de points pixels.
        """

        if binary_mask is None:
            return np.empty((0, 2), dtype=float)

        mask = binary_mask > 0

        if mask.ndim != 2:
            return np.empty((0, 2), dtype=float)

        width = mask.shape[0]
        height = mask.shape[1]

        x_points = []

        # ========================================================
        # 1) Scan vertical colonne par colonne
        # ========================================================

        for col in range(width):

            blobs = []
            first_blob_y = -2.0 * self.y_step

            current_count = 0
            current_avg = 0.0

            for row in range(height):

                if not mask[col, row]:
                    continue

                if row > first_blob_y + self.y_step:

                    blobs.append(float(row))
                    current_count = 1
                    current_avg = float(row)
                    first_blob_y = float(row)

                else:

                    current_count += 1

                    current_avg = (
                        current_avg * (current_count - 1)
                        + float(row)
                    ) / current_count

                    blobs[-1] = current_avg

            for blob_y in blobs:
                x_points.append(
                    [
                        float(col) + 0.5,
                        float(blob_y) + 0.5,
                        True
                    ]
                )

        if len(x_points) == 0:
            return np.empty((0, 2), dtype=float)

        # ========================================================
        # 2) Regroupement local
        # ========================================================

        result = []

        for i in range(len(x_points)):

            if x_points[i][2] is False:
                continue

            old_x = x_points[i][0]
            old_y = x_points[i][1]

            avg_x = old_x
            avg_y = old_y

            matches = 1

            j = i + 1

            while j < len(x_points):

                new_x = x_points[j][0]
                new_y = x_points[j][1]

                if (
                    abs(new_x - old_x) <= self.x_step
                    and
                    abs(new_y - old_y) <= self.y_step
                    and
                    x_points[j][2] is True
                ):

                    avg_x = (
                        avg_x * matches
                        + new_x
                    ) / (matches + 1.0)

                    avg_y = (
                        avg_y * matches
                        + new_y
                    ) / (matches + 1.0)

                    matches += 1

                    x_points[j][2] = False

                if new_x > old_x + 2.0 * self.x_step:
                    break

                j += 1

            x_points[i][2] = False

            result.append([avg_x, avg_y])

        if len(result) == 0:
            return np.empty((0, 2), dtype=float)

        return np.array(result, dtype=float)
