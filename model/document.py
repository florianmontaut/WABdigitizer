# model/document.py
"""
Document numérisé : un composant, ses graphiques (une image de la fiche chacun, calibrée)
et les courbes relevées sur chaque graphique.

    Component           nom, fabricant, référence, notes ; liste de Graph
    Graph               image, calibration, axes (grandeur, unité), grille de X commune ;
                        liste de Dataset
    Dataset             points en pixels (vérité de l'image), condition (« Tj = 125 °C »),
                        masque et couleur propres pour l'extraction automatique

Les points sont gardés en pixels, comme dans WebPlotDigitizer : une nouvelle calibration
recalcule toutes les valeurs. Le fichier enregistre aussi les valeurs physiques, pour un
lecteur (logiciel de dimensionnement) qui n'a pas la calibration.

Fichier : JSON « ParamDigitizer project v1 » (*.pdig.json), image et masque compressés
dedans (le projet se déplace d'un poste à l'autre sans ses images).
"""
import base64
import json
import os
import pathlib
import zlib
from dataclasses import dataclass, field

import numpy as np

from .calibration import AxisCalibration
from .extraction import ExtractionSettings
from . import signals
from .fit import FitResult
from .plecs import PlecsSettings

PROJECT_FORMAT = "ParamDigitizer project v1"
PROJECT_SUFFIX = ".pdig.json"

# couleurs successives des courbes d'un graphique
PALETTE = ("#d62728", "#1f77b4", "#2ca02c", "#ff7f0e", "#9467bd",
           "#8c564b", "#e377c2", "#17becf", "#bcbd22", "#7f7f7f")


# ================================================================ tableaux <-> texte
def encode_array(array: np.ndarray | None) -> dict | None:
    if array is None:
        return None
    array = np.ascontiguousarray(array)
    if array.dtype == bool:
        payload = np.packbits(array, axis=None).tobytes()
    else:
        payload = array.tobytes()
    return {"shape": list(array.shape), "dtype": str(array.dtype),
            "zlib_base64": base64.b64encode(zlib.compress(payload, 6)).decode("ascii")}


def decode_array(data: dict | None) -> np.ndarray | None:
    if not data:
        return None
    raw = zlib.decompress(base64.b64decode(data["zlib_base64"]))
    shape = tuple(data["shape"])
    if data["dtype"] == "bool":
        count = int(np.prod(shape))
        return np.unpackbits(np.frombuffer(raw, dtype=np.uint8), count=count).astype(bool).reshape(shape)
    return np.frombuffer(raw, dtype=np.dtype(data["dtype"])).reshape(shape).copy()


# ================================================================ courbe
@dataclass
class Dataset:
    name: str
    color: str = PALETTE[0]
    condition: str = ""                 # condition de la courbe : « Tj = 125 °C », « VGE = 15 V »
    pixels: np.ndarray = field(default_factory=lambda: np.empty((0, 2)))
    visible: bool = True
    fit: FitResult | None = None
    notes: str = ""
    # extraction automatique : zone peinte et couleur de cette courbe
    mask: np.ndarray | None = None      # (lignes, colonnes) bool
    curve_color: tuple = (0, 0, 0)
    tolerance: float = 120.0            # distance RGB admise
    # export PLECS : conditions numériques (sinon lues dans condition)
    temperature: float | None = None    # °C
    voltage: float | None = None        # V, tension de commutation

    def __post_init__(self):
        self.pixels = np.asarray(self.pixels, dtype=float).reshape(-1, 2)

    def __len__(self):
        return len(self.pixels)

    # ------------------------------------------------------------ édition
    def add_pixel(self, x: float, y: float, calibration: AxisCalibration | None = None) -> int:
        """
        Ajoute un point ; renvoie son indice. Points rangés par X physique croissant
        (pixel X sans calibration) : un clic au milieu de la courbe s'insère à sa place.
        """
        point = np.array([[float(x), float(y)]])
        key = self._sort_keys(np.vstack((self.pixels, point)), calibration)
        index = int(np.searchsorted(key[:-1], key[-1], side="right"))
        self.pixels = np.insert(self.pixels, index, point, axis=0)
        return index

    def move_pixel(self, index: int, x: float, y: float):
        self.pixels[index] = (float(x), float(y))

    def remove_pixel(self, index: int):
        self.pixels = np.delete(self.pixels, index, axis=0)

    def nearest(self, x: float, y: float, radius: float) -> int | None:
        """Indice du point le plus proche de (x, y) à moins de radius pixels."""
        if len(self.pixels) == 0:
            return None
        distance = np.hypot(self.pixels[:, 0] - x, self.pixels[:, 1] - y)
        index = int(np.argmin(distance))
        return index if distance[index] <= radius else None

    def sort(self, calibration: AxisCalibration | None = None, follow: int | None = None):
        """
        Range les points par X croissant. follow : indice d'un point avant le tri ;
        renvoie son indice après (None si follow est None).
        """
        if not len(self.pixels):
            return None
        order = np.argsort(self._sort_keys(self.pixels, calibration), kind="stable")
        self.pixels = self.pixels[order]
        if follow is None:
            return None
        return int(np.flatnonzero(order == follow)[0])

    @staticmethod
    def _sort_keys(pixels, calibration):
        if calibration is None:
            return pixels[:, 0]
        return calibration.pixel_to_scaled(pixels)[:, 0]

    # ------------------------------------------------------------ valeurs
    def data(self, calibration: AxisCalibration | None) -> np.ndarray:
        """Points en unités physiques (pixels si le graphique n'est pas calibré)."""
        if calibration is None:
            return self.pixels.copy()
        return calibration.pixel_to_data(self.pixels)

    def set_data(self, data, calibration: AxisCalibration):
        self.pixels = calibration.data_to_pixel(data)

    # ------------------------------------------------------------ fichier
    def to_dict(self, calibration=None) -> dict:
        out = {"name": self.name, "color": self.color, "condition": self.condition,
               "visible": self.visible, "notes": self.notes,
               "pixels": self.pixels.tolist()}
        if calibration is not None:
            out["data"] = self.data(calibration).tolist()
        if self.fit is not None:
            out["fit"] = self.fit.to_dict()
        out["curve_color"] = list(self.curve_color)
        out["tolerance"] = self.tolerance
        out["temperature"] = self.temperature
        out["voltage"] = self.voltage
        out["mask"] = encode_array(self.mask) if self.mask is not None and self.mask.any() else None
        return out

    @classmethod
    def from_dict(cls, data: dict) -> "Dataset":
        return cls(name=data["name"], color=data.get("color", PALETTE[0]),
                   condition=data.get("condition", ""), visible=data.get("visible", True),
                   notes=data.get("notes", ""),
                   pixels=np.asarray(data.get("pixels", []), dtype=float).reshape(-1, 2),
                   fit=FitResult.from_dict(data["fit"]) if data.get("fit") else None,
                   mask=decode_array(data.get("mask")),
                   curve_color=tuple(data.get("curve_color", (0, 0, 0))),
                   tolerance=float(data.get("tolerance", 120.0)),
                   temperature=data.get("temperature"), voltage=data.get("voltage"))


# ================================================================ graphique
@dataclass
class Axis:
    quantity: str = ""          # grandeur : « IC », « VCE », « Eon »
    unit: str = ""              # unité lue par formules.units : « A », « V », « mJ »

    def label(self, default: str) -> str:
        text = self.quantity or default
        return f"{text} ({self.unit})" if self.unit else text


@dataclass
class Graph:
    name: str
    image: np.ndarray | None = None              # (lignes, colonnes, 3|4) uint8
    calibration: AxisCalibration | None = None
    x_axis: Axis = field(default_factory=Axis)
    y_axis: Axis = field(default_factory=Axis)
    datasets: list = field(default_factory=list)
    extraction: ExtractionSettings = field(default_factory=ExtractionSettings)  # grille commune
    plecs_role: str = ""                         # voir model.plecs.ROLES
    source: str = ""                             # fichier d'origine (information)

    @property
    def calibrated(self) -> bool:
        return self.calibration is not None

    def mask_of(self, dataset: Dataset) -> np.ndarray:
        """Masque de la courbe, créé à la taille de l'image au besoin."""
        if dataset.mask is None or dataset.mask.shape != self.image.shape[:2]:
            dataset.mask = np.zeros(self.image.shape[:2], dtype=bool)
        return dataset.mask

    def add_dataset(self, name: str | None = None, tolerance: float | None = None) -> Dataset:
        used = {d.name for d in self.datasets}
        if name is None:
            n = len(self.datasets) + 1
            while f"Courbe {n}" in used:
                n += 1
            name = f"Courbe {n}"
        dataset = Dataset(name=name, color=PALETTE[len(self.datasets) % len(PALETTE)])
        if tolerance is not None:
            dataset.tolerance = float(tolerance)
        self.datasets.append(dataset)
        return dataset

    def set_calibration(self, calibration: AxisCalibration | None):
        self.calibration = calibration
        for dataset in self.datasets:
            dataset.sort(calibration)

    def to_dict(self) -> dict:
        return {"name": self.name, "source": self.source,
                "x_axis": vars(self.x_axis), "y_axis": vars(self.y_axis),
                "calibration": self.calibration.to_dict() if self.calibration else None,
                "extraction": self.extraction.to_dict(), "plecs_role": self.plecs_role,
                "datasets": [d.to_dict(self.calibration) for d in self.datasets],
                "image": encode_array(self.image)}

    @classmethod
    def from_dict(cls, data: dict) -> "Graph":
        return cls(name=data["name"], source=data.get("source", ""),
                   image=decode_array(data.get("image")),
                   calibration=(AxisCalibration.from_dict(data["calibration"])
                                if data.get("calibration") else None),
                   x_axis=Axis(**data.get("x_axis", {})), y_axis=Axis(**data.get("y_axis", {})),
                   datasets=[Dataset.from_dict(d) for d in data.get("datasets", [])],
                   extraction=ExtractionSettings.from_dict(data.get("extraction")),
                   plecs_role=data.get("plecs_role", ""))


# ================================================================ composant
@dataclass
class Component:
    name: str = "Nouveau composant"
    manufacturer: str = ""
    part_number: str = ""
    category: str = ""          # IGBT, MOSFET, diode, condensateur, inductance...
    notes: str = ""
    graphs: list = field(default_factory=list)
    plecs: PlecsSettings = field(default_factory=PlecsSettings)
    computed: list = field(default_factory=list)   # voies calculées (signals.ComputedCurve)

    def add_graph(self, image: np.ndarray, name: str | None = None, source: str = "") -> Graph:
        graph = Graph(name=name or f"Graphique {len(self.graphs) + 1}", image=image,
                      source=source)
        graph.add_dataset()
        self.graphs.append(graph)
        return graph

    def to_dict(self) -> dict:
        return {"format": PROJECT_FORMAT, "name": self.name,
                "manufacturer": self.manufacturer, "part_number": self.part_number,
                "category": self.category, "notes": self.notes,
                "plecs": self.plecs.to_dict(),
                "graphs": [g.to_dict() for g in self.graphs],
                "computed": [c.to_dict() for c in self.computed]}

    @classmethod
    def from_dict(cls, data: dict) -> "Component":
        if data.get("format") != PROJECT_FORMAT:
            raise ValueError(f"format de projet inconnu : {data.get('format')!r}")
        return cls(name=data.get("name", ""), manufacturer=data.get("manufacturer", ""),
                   part_number=data.get("part_number", ""), category=data.get("category", ""),
                   notes=data.get("notes", ""),
                   graphs=[Graph.from_dict(g) for g in data.get("graphs", [])],
                   plecs=PlecsSettings.from_dict(data.get("plecs")),
                   computed=[signals.ComputedCurve.from_dict(c)
                             for c in data.get("computed", [])])


def save(component: Component, path) -> None:
    """Écriture dans un fichier voisin puis remplacement (pas de projet à moitié écrit)."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(component.to_dict(), ensure_ascii=False, indent=1),
                         encoding="utf-8")
    os.replace(temporary, path)


def load(path) -> Component:
    return Component.from_dict(json.loads(pathlib.Path(path).read_text(encoding="utf-8")))
