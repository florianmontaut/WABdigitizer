# controller/library_controller.py
"""
Contrôleur du panneau de la librairie : lecture du dossier (model.library.scan), table
filtrée et triée, composants choisis. Les actions qui touchent au composant ouvert
(publier, ouvrir, comparer, supprimer) sont dans le contrôleur principal.
"""
import datetime
import pathlib

from PyQt6 import QtCore, QtGui

from model import library
from view.library_panel import HEADERS

KEY_ROLE = QtCore.Qt.ItemDataRole.UserRole + 1


class LibraryController(QtCore.QObject):

    def __init__(self, panel, options: dict):
        """options : réglages de l'application (library_dir), partagés."""
        super().__init__()
        self.panel = panel
        self.options = options
        self.entries = {}               # clé -> library.Entry
        self.errors = []
        # modèles parentés à la vue : détruits avec elle
        self.model = QtGui.QStandardItemModel(panel.table)
        self.proxy = QtCore.QSortFilterProxyModel(panel.table)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterKeyColumn(-1)                       # toutes les colonnes
        self.proxy.setFilterCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setSortRole(QtCore.Qt.ItemDataRole.UserRole)
        panel.table.setModel(self.proxy)
        panel.filter.textChanged.connect(self.proxy.setFilterFixedString)
        self.reload()

    @property
    def folder(self) -> pathlib.Path:
        return pathlib.Path(self.options["library_dir"])

    def reload(self, *_, select=None):
        """Relit le dossier ; garde les composants choisis (ou choisit la clé select)."""
        keep = [select] if select else [e.key for e in self.selected()]
        entries, self.errors = library.scan(self.folder)
        self.entries = {e.key: e for e in entries}
        model = self.model
        model.clear()
        model.setHorizontalHeaderLabels(HEADERS)
        for entry in entries:
            modified = datetime.datetime.fromtimestamp(entry.modified).strftime("%Y-%m-%d %H:%M") \
                if entry.modified else ""
            values = [entry.category or library.UNSORTED, entry.title, entry.manufacturer,
                      ", ".join(entry.graphs), entry.curves,
                      "oui" if entry.project_path else "non",
                      "oui" if entry.plecs_path else "", modified]
            tip = "\n".join(filter(None, [entry.name if entry.name != entry.title else "",
                                          entry.notes,
                                          *(str(p) for p in entry.files)]))
            row = []
            for value in values:
                item = QtGui.QStandardItem(str(value))
                item.setData(value if isinstance(value, int) else str(value).casefold(),
                             QtCore.Qt.ItemDataRole.UserRole)
                item.setData(entry.key, KEY_ROLE)
                item.setToolTip(tip)
                row.append(item)
            if entry.project_path is None:      # fiche seule : rien à rouvrir
                for item in row:
                    item.setForeground(QtGui.QBrush(QtGui.QColor("gray")))
            model.appendRow(row)
        table = self.panel.table
        header = table.horizontalHeader()
        if not 0 <= header.sortIndicatorSection() < len(HEADERS):
            table.sortByColumn(0, QtCore.Qt.SortOrder.AscendingOrder)
        table.resizeColumnsToContents()
        self.select_keys(keep)
        count = len(entries)
        self.panel.set_status(f"{count} composant{'s' if count > 1 else ''} — {self.folder}",
                              self.errors)

    def select_keys(self, keys):
        selection = self.panel.table.selectionModel()
        selection.clearSelection()
        flags = (QtCore.QItemSelectionModel.SelectionFlag.Select
                 | QtCore.QItemSelectionModel.SelectionFlag.Rows)
        for row in range(self.proxy.rowCount()):
            index = self.proxy.index(row, 0)
            if index.data(KEY_ROLE) in keys:
                selection.select(index, flags)
                self.panel.table.scrollTo(index)

    def selected(self) -> list:
        """Composants choisis, dans l'ordre de la table."""
        selection = self.panel.table.selectionModel()
        if selection is None:
            return []
        rows = sorted(selection.selectedRows(), key=lambda index: index.row())
        return [self.entries[k] for k in (index.data(KEY_ROLE) for index in rows)
                if k in self.entries]
