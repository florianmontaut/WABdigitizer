# model/calibration.py
"""
Calibration des axes d'un graphique : passage pixels de l'image <-> unités physiques.

Même principe que WebPlotDigitizer (axes XY) : l'utilisateur pointe deux points de l'axe X
(X1, X2) et deux points de l'axe Y (Y1, Y2) dont il connaît la valeur. La transformation
est affine dans l'espace « calibré » (log10 de la valeur pour un axe logarithmique) : elle
prend en compte une image légèrement tournée ou cisaillée (scan, capture de PDF).

Convention pixels : x = colonne, y = ligne (y vers le bas), en pixels de l'image.
"""
from dataclasses import dataclass

import numpy as np


class CalibrationError(ValueError):
    """Calibration impossible (points confondus, valeurs égales, log d'une valeur <= 0)."""


@dataclass(frozen=True)
class AxisCalibration:
    # pixels pointés (x, y) des quatre points de référence
    px_x1: tuple
    px_x2: tuple
    px_y1: tuple
    px_y2: tuple
    # valeurs physiques correspondantes
    x1: float
    x2: float
    y1: float
    y2: float
    log_x: bool = False
    log_y: bool = False

    def __post_init__(self):
        for name in ("x1", "x2", "y1", "y2"):
            object.__setattr__(self, name, float(getattr(self, name)))
        for name in ("px_x1", "px_x2", "px_y1", "px_y2"):
            object.__setattr__(self, name, tuple(float(v) for v in getattr(self, name)))
        self._solve()

    # ------------------------------------------------------------ résolution
    def _scaled(self, value, log):
        if log:
            if value <= 0:
                raise CalibrationError("un axe logarithmique demande des valeurs > 0")
            return float(np.log10(value))
        return float(value)

    def _solve(self):
        sx1, sx2 = self._scaled(self.x1, self.log_x), self._scaled(self.x2, self.log_x)
        sy1, sy2 = self._scaled(self.y1, self.log_y), self._scaled(self.y2, self.log_y)
        if sx1 == sx2:
            raise CalibrationError("X1 et X2 doivent avoir des valeurs différentes")
        if sy1 == sy2:
            raise CalibrationError("Y1 et Y2 doivent avoir des valeurs différentes")
        p_x1, p_x2 = np.array(self.px_x1), np.array(self.px_x2)
        p_y1, p_y2 = np.array(self.px_y1), np.array(self.px_y2)
        # pixels par unité calibrée, le long de chaque axe
        ex = (p_x2 - p_x1) / (sx2 - sx1)
        ey = (p_y2 - p_y1) / (sy2 - sy1)
        matrix = np.column_stack((ex, ey))
        if abs(np.linalg.det(matrix)) < 1e-12 * max(1.0, np.abs(matrix).max() ** 2):
            raise CalibrationError("les axes X et Y pointés sont parallèles ou dégénérés")
        # pixel = M @ (X, Y) + c. X1 est sur l'axe X (Y inconnu = Yx), Y1 sur l'axe Y
        # (X inconnu = Xy) : p_x1 - p_y1 = M @ (sx1 - Xy, Yx - sy1)
        u, v = np.linalg.solve(matrix, p_x1 - p_y1)
        y_on_x_axis = sy1 + v
        offset = p_x1 - matrix @ np.array([sx1, y_on_x_axis])
        object.__setattr__(self, "_matrix", matrix)
        object.__setattr__(self, "_inverse", np.linalg.inv(matrix))
        object.__setattr__(self, "_offset", offset)

    # ------------------------------------------------------------ conversions
    def pixel_to_scaled(self, points) -> np.ndarray:
        """Pixels (N, 2) -> coordonnées calibrées (log10 sur un axe log)."""
        points = np.asarray(points, dtype=float).reshape(-1, 2)
        return (points - self._offset) @ self._inverse.T

    def scaled_to_pixel(self, scaled) -> np.ndarray:
        scaled = np.asarray(scaled, dtype=float).reshape(-1, 2)
        return scaled @ self._matrix.T + self._offset

    def scaled_to_data(self, scaled) -> np.ndarray:
        scaled = np.array(scaled, dtype=float).reshape(-1, 2)
        if self.log_x:
            scaled[:, 0] = np.power(10.0, scaled[:, 0])
        if self.log_y:
            scaled[:, 1] = np.power(10.0, scaled[:, 1])
        return scaled

    def data_to_scaled(self, data) -> np.ndarray:
        data = np.array(data, dtype=float).reshape(-1, 2)
        with np.errstate(divide="ignore", invalid="ignore"):
            if self.log_x:
                data[:, 0] = np.where(data[:, 0] > 0, np.log10(np.abs(data[:, 0])), np.nan)
            if self.log_y:
                data[:, 1] = np.where(data[:, 1] > 0, np.log10(np.abs(data[:, 1])), np.nan)
        return data

    def pixel_to_data(self, points) -> np.ndarray:
        return self.scaled_to_data(self.pixel_to_scaled(points))

    def data_to_pixel(self, data) -> np.ndarray:
        return self.scaled_to_pixel(self.data_to_scaled(data))

    # ------------------------------------------------------------ qualité
    def skew_degrees(self) -> float:
        """Écart à l'orthogonalité des axes pointés (0° pour une image bien droite)."""
        ex, ey = self._matrix[:, 0], self._matrix[:, 1]
        cos = abs(ex @ ey) / (np.linalg.norm(ex) * np.linalg.norm(ey))
        return float(np.degrees(np.arcsin(min(1.0, cos))))

    # ------------------------------------------------------------ fichier
    def to_dict(self) -> dict:
        return {"px_x1": list(self.px_x1), "px_x2": list(self.px_x2),
                "px_y1": list(self.px_y1), "px_y2": list(self.px_y2),
                "x1": self.x1, "x2": self.x2, "y1": self.y1, "y2": self.y2,
                "log_x": self.log_x, "log_y": self.log_y}

    @classmethod
    def from_dict(cls, data: dict) -> "AxisCalibration":
        return cls(**{key: data[key] for key in (
            "px_x1", "px_x2", "px_y1", "px_y2", "x1", "x2", "y1", "y2")},
            log_x=bool(data.get("log_x", False)), log_y=bool(data.get("log_y", False)))
