# controller/commands.py
"""
Commandes annuler / refaire (QUndoStack), même mécanisme que GLviewer : chaque commande
modifie le modèle puis demande au contrôleur de rafraîchir la vue.

Les commandes gardent l'état avant et après (instantanés) : redo() et undo() appliquent
l'un ou l'autre, et peuvent être rejouées sans effet de bord. Une action déjà faite à
l'écran (glisser un point, un coup de pinceau) est poussée à la fin : le redo() de
QUndoStack.push la réapplique à l'identique.

Les objets (graphiques, courbes) sont désignés par référence, pas par indice : une courbe
supprimée puis rétablie est le même objet.
"""
from PyQt6.QtGui import QUndoCommand

import numpy as np

NUDGE_ID = 1          # flèches sur un point : appuis successifs fusionnés
CALIBRATION_NUDGE_ID = 2


# ================================================================ points d'une courbe
def points_state(dataset) -> dict:
    """Ce que les actions sur les points modifient : les points et le modèle ajusté."""
    return {"pixels": dataset.pixels.copy(), "fit": dataset.fit}


class PointsCommand(QUndoCommand):
    """Points (et modèle) d'une courbe : ajout, déplacement, suppression, extraction..."""

    def __init__(self, ctrl, graph, dataset, before: dict, after: dict, text: str,
                 selected_before=None, selected_after=None, merge=False):
        super().__init__(text)
        self.ctrl, self.graph, self.dataset = ctrl, graph, dataset
        self.before, self.after = before, after
        self.selected_before, self.selected_after = selected_before, selected_after
        self.merge = merge

    def _apply(self, state, selected):
        self.dataset.pixels = state["pixels"].copy()
        self.dataset.fit = state["fit"]
        self.ctrl.show_points(self.graph, self.dataset, selected)

    def redo(self):
        self._apply(self.after, self.selected_after)

    def undo(self):
        self._apply(self.before, self.selected_before)

    def id(self):
        return NUDGE_ID if self.merge else -1

    def mergeWith(self, other) -> bool:
        """Appuis de flèches successifs sur le même point : une seule étape."""
        if (other.dataset is not self.dataset or not other.merge
                or other.selected_before != self.selected_after):
            return False
        self.after, self.selected_after = other.after, other.selected_after
        return True


def same_points(a: dict, b: dict) -> bool:
    return (a["fit"] is b["fit"] and a["pixels"].shape == b["pixels"].shape
            and np.array_equal(a["pixels"], b["pixels"]))


# ================================================================ calibration
class CalibrationCommand(QUndoCommand):
    """Calibration d'un graphique (et grille d'extraction réglée à la première)."""

    def __init__(self, ctrl, graph, before, after, extraction_before, extraction_after,
                 text="Calibrer les axes", marker=None):
        super().__init__(text)
        self.ctrl, self.graph = ctrl, graph
        self.before, self.after = before, after
        self.extraction_before, self.extraction_after = extraction_before, extraction_after
        self.marker = marker          # repère déplacé aux flèches (fusion), sinon None

    def _apply(self, calibration, extraction):
        self.graph.set_calibration(calibration)
        self.graph.extraction = extraction
        self.ctrl.show_calibration(self.graph, self.marker)

    def redo(self):
        self._apply(self.after, self.extraction_after)

    def undo(self):
        self._apply(self.before, self.extraction_before)

    def id(self):
        return CALIBRATION_NUDGE_ID if self.marker is not None else -1

    def mergeWith(self, other) -> bool:
        if other.graph is not self.graph or other.marker != self.marker:
            return False
        self.after, self.extraction_after = other.after, other.extraction_after
        return True


# ================================================================ masque
class MaskCommand(QUndoCommand):
    """Coup de pinceau ou de gomme : seule la zone modifiée est gardée."""

    def __init__(self, ctrl, graph, dataset, before: np.ndarray, after: np.ndarray,
                 text="Peindre le masque"):
        super().__init__(text)
        self.ctrl, self.graph, self.dataset = ctrl, graph, dataset
        changed = before != after
        rows, cols = np.nonzero(changed)
        if len(rows):
            self.box = (rows.min(), rows.max() + 1, cols.min(), cols.max() + 1)
            r0, r1, c0, c1 = self.box
            self.region_before = before[r0:r1, c0:c1].copy()
            self.region_after = after[r0:r1, c0:c1].copy()
        else:
            self.box = None
        self.empty = self.box is None

    def _apply(self, region):
        r0, r1, c0, c1 = self.box
        self.graph.mask_of(self.dataset)[r0:r1, c0:c1] = region
        self.ctrl.show_mask(self.graph, self.dataset)

    def redo(self):
        if self.box is not None:
            self._apply(self.region_after)

    def undo(self):
        if self.box is not None:
            self._apply(self.region_before)


# ================================================================ structure
class InsertCommand(QUndoCommand):
    """Ajout (insert=True) ou suppression d'un élément d'une liste : courbe, graphique."""

    def __init__(self, ctrl, items: list, index: int, item, insert: bool, text: str,
                 graph=None):
        super().__init__(text)
        self.ctrl, self.items, self.index, self.item = ctrl, items, index, item
        self.insert = insert
        self.graph = graph            # graphique de la courbe (None pour un graphique)

    def _add(self):
        self.items.insert(self.index, self.item)
        self.ctrl.show_structure(self.graph, self.item)

    def _remove(self):
        self.items.remove(self.item)
        self.ctrl.show_structure(self.graph, None)

    def redo(self):
        self._add() if self.insert else self._remove()

    def undo(self):
        self._remove() if self.insert else self._add()
