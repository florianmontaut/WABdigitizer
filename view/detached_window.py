# view/detached_window.py
"""
Fenêtre d'un panneau détaché de la fenêtre principale (aperçu en unités physiques,
librairie) : vraie fenêtre de premier niveau (barre des tâches, plein écran, second
écran), enfant de la fenêtre principale, sans retenir l'application ouverte.
Repris de GLviewer (view/detached_graph_window.py) : la fermer réintègre le panneau à sa
place (fermeture refusée, signal `closed`, la fenêtre principale le remet et masque la
fenêtre) ; la fenêtre n'est pas détruite avant la fenêtre principale et sert au
détachement suivant (position et taille gardées pendant la session).
"""
from PyQt6 import QtCore, QtWidgets


class DetachedWindow(QtWidgets.QWidget):

    # croix de la fenêtre : panneau (widget) à réintégrer
    closed = QtCore.pyqtSignal(object)

    def __init__(self, parent: QtWidgets.QWidget | None = None, size=(1000, 600)):
        super().__init__(parent, QtCore.Qt.WindowType.Window)
        self.content = None
        # ne retient pas l'application ouverte : elle se ferme avec la fenêtre principale
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_QuitOnClose, False)
        self._layout = QtWidgets.QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self.resize(*size)

    def assign(self, widget: QtWidgets.QWidget, title: str):
        """Le panneau passe dans la fenêtre (il quitte sa place d'origine)."""
        self.content = widget
        self._layout.addWidget(widget)
        widget.show()
        self.setWindowTitle(title)

    def release(self) -> QtWidgets.QWidget | None:
        """Panneau rendu (à remettre à sa place) ; fenêtre masquée, prête pour le suivant."""
        widget, self.content = self.content, None
        if widget is not None:
            self._layout.removeWidget(widget)
        self.hide()
        return widget

    def closeEvent(self, event):
        if self.content is None:
            event.accept()
            return
        # fermeture refusée : la fenêtre principale réintègre le panneau et masque la fenêtre
        event.ignore()
        self.closed.emit(self.content)
