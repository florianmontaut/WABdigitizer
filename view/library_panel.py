# view/library_panel.py
"""
Panneau de la librairie (dans un dock de la fenêtre principale) :
    barre d'actions (publier, ouvrir, comparer, supprimer, explorateur, actualiser)
    filtre (toutes les colonnes, sans tenir compte de la casse)
    table triable, sélection de plusieurs lignes
    ligne d'état (nombre de composants, fichiers ignorés en infobulle)
Les actions sont créées par la fenêtre principale (menu Librairie) et reprises ici.
"""
from PyQt6 import QtCore, QtWidgets

HEADERS = ["Catégorie", "Référence", "Fabricant", "Graphiques", "Courbes", "Projet",
           "PLECS", "Modifié le"]


class LibraryPanel(QtWidgets.QWidget):

    def __init__(self, actions, parent=None):
        super().__init__(parent)
        bar = QtWidgets.QToolBar()
        bar.setIconSize(QtCore.QSize(18, 18))
        for action in actions:
            if action is None:
                bar.addSeparator()
            else:
                bar.addAction(action)
        self.filter = QtWidgets.QLineEdit()
        self.filter.setPlaceholderText("Filtrer (référence, fabricant, catégorie, graphique)")
        self.filter.setClearButtonEnabled(True)

        table = QtWidgets.QTableView()
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSortingEnabled(True)
        table.setShowGrid(False)
        table.setWordWrap(False)
        table.verticalHeader().hide()
        table.verticalHeader().setDefaultSectionSize(22)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setHighlightSections(False)
        table.setToolTip("Double-clic : ouvrir le projet du composant. "
                         "Ctrl+clic / Maj+clic : plusieurs composants à comparer")
        table.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.ActionsContextMenu)
        for action in actions:
            if action is not None:
                table.addAction(action)
        self.table = table

        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 4)
        layout.setSpacing(4)
        layout.addWidget(bar)
        layout.addWidget(self.filter)
        layout.addWidget(table, 1)
        layout.addWidget(self.status)

    def set_status(self, text: str, errors=()):
        if errors:
            text += f" — {len(errors)} fichier(s) ignoré(s), voir l'infobulle"
        self.status.setText(text)
        self.status.setToolTip("\n".join(errors))
