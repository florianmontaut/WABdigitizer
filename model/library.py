# model/library.py
"""
Librairie de composants : un dossier (local ou partagé), un sous-dossier par catégorie.

    <librairie>/<Catégorie>/<Référence>.json         fiche « ParamDigitizer component v1 »
                                                     (lue par le logiciel de dimensionnement)
    <librairie>/<Catégorie>/<Référence>.pdig.json    projet source : image, calibration,
                                                     masques (pour rouvrir et corriger)
    <librairie>/<Catégorie>/<Référence>.xml          description thermique PLECS
    <librairie>/_corbeille/<date>/...                entrées supprimées ou remplacées

Une entrée regroupe les fichiers de même nom d'un même dossier. Les fichiers rangés à la
main ailleurs (à plat, autres sous-dossiers) sont lus aussi ; une fiche seule, ou un projet
seul, est une entrée. Rien ici ne dépend de Qt.
"""
import datetime
import json
import os
import pathlib
import re
import shutil
from dataclasses import dataclass, field

from . import document, export, plecs

TRASH = "_corbeille"
UNSORTED = "Sans catégorie"
SHEET_SUFFIX = ".json"
PLECS_SUFFIX = ".xml"
_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class LibraryError(Exception):
    """Publication impossible (composant sans nom, écriture refusée...)."""


def safe_name(text: str) -> str:
    """Nom de fichier Windows valide : caractères interdits remplacés, sans point final."""
    return _FORBIDDEN.sub("_", str(text)).strip().rstrip(". ")


@dataclass
class Entry:
    """Un composant de la librairie et ses fichiers (None : absent)."""
    folder: pathlib.Path
    stem: str
    sheet_path: pathlib.Path | None = None
    project_path: pathlib.Path | None = None
    plecs_path: pathlib.Path | None = None
    name: str = ""
    manufacturer: str = ""
    part_number: str = ""
    category: str = ""
    notes: str = ""
    graphs: list = field(default_factory=list)      # noms des graphiques
    curves: int = 0

    @property
    def title(self) -> str:
        return self.part_number or self.name or self.stem

    @property
    def files(self) -> list:
        return [p for p in (self.sheet_path, self.project_path, self.plecs_path) if p]

    @property
    def data_path(self):
        """Fichier à lire pour les courbes : la fiche, sinon le projet."""
        return self.sheet_path or self.project_path

    @property
    def modified(self) -> float:
        times = [p.stat().st_mtime for p in self.files if p.exists()]
        return max(times) if times else 0.0

    @property
    def key(self) -> str:
        """Identifiant de l'entrée (dossier + nom), stable tant que rien n'est déplacé."""
        return str(self.folder / self.stem)


def _split(path: pathlib.Path):
    """(nom sans suffixe, rôle) d'un fichier de librairie, None s'il n'en est pas un."""
    name = path.name
    if name.lower().endswith(document.PROJECT_SUFFIX):
        return name[:-len(document.PROJECT_SUFFIX)], "project"
    suffix = path.suffix.lower()
    if suffix == SHEET_SUFFIX:
        return path.stem, "sheet"
    if suffix == PLECS_SUFFIX:
        return path.stem, "plecs"
    return None


def _describe(entry: Entry, data: dict, project: bool):
    """Renseigne l'entrée depuis une fiche ou un projet (sans décoder les images)."""
    entry.name = data.get("name", "")
    entry.manufacturer = data.get("manufacturer", "")
    entry.part_number = data.get("part_number", "")
    entry.category = data.get("category", "")
    entry.notes = data.get("notes", "")
    graphs = data.get("graphs", [])
    entry.graphs = [g.get("name", "") for g in graphs]
    entry.curves = sum(len(g.get("datasets" if project else "curves", [])) for g in graphs)


def scan(folder) -> tuple:
    """
    (entrées triées par catégorie puis titre, erreurs) du dossier, sous-dossiers compris,
    corbeille exceptée. Un fichier illisible ou étranger est signalé et ignoré ; une
    référence présente deux fois aussi (les deux entrées restent listées).
    """
    folder = pathlib.Path(folder)
    if not folder.is_dir():
        return [], []
    groups, errors = {}, []
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or TRASH in path.relative_to(folder).parts:
            continue
        split = _split(path)
        if split is None:
            continue
        stem, role = split
        groups.setdefault((path.parent, stem.casefold()), {})[role] = path

    entries = []
    for (parent, _), files in groups.items():
        if "sheet" not in files and "project" not in files:
            continue                    # XML seul : ce n'est pas un composant de la librairie
        main = files.get("sheet") or files["project"]
        entry = Entry(folder=parent, stem=_split(main)[0], sheet_path=files.get("sheet"),
                      project_path=files.get("project"), plecs_path=files.get("plecs"))
        described = False
        for role, expected in (("sheet", export.COMPONENT_FORMAT),
                               ("project", document.PROJECT_FORMAT)):
            path = files.get(role)
            if path is None:
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                errors.append(f"{path.name} : illisible ({error})")
                setattr(entry, f"{role}_path", None)
                continue
            if not isinstance(data, dict) or data.get("format") != expected:
                errors.append(f"{path.name} : ni fiche ni projet ParamDigitizer")
                setattr(entry, f"{role}_path", None)
                continue
            if not described:
                _describe(entry, data, role == "project")
                described = True
        if entry.data_path is not None:
            entries.append(entry)

    seen = {}
    for entry in entries:
        key = entry.title.casefold()
        if key in seen:
            errors.append(f"référence en double : {entry.title} "
                          f"({_relative(seen[key], folder)} et {_relative(entry, folder)})")
        else:
            seen[key] = entry
    entries.sort(key=lambda e: (e.category.casefold(), e.title.casefold()))
    return entries, errors


def _relative(entry: Entry, folder) -> str:
    try:
        return str(entry.folder.relative_to(folder) / entry.stem)
    except ValueError:
        return str(entry.folder / entry.stem)


# ================================================================ publication
def target(folder, component) -> tuple:
    """(dossier, nom de fichier) d'un composant dans la librairie."""
    stem = safe_name(component.part_number or component.name)
    if not stem:
        raise LibraryError("Donnez une référence ou un nom au composant avant de le publier.")
    return pathlib.Path(folder) / (safe_name(component.category) or UNSORTED), stem


def conflicts(entries, folder, component) -> list:
    """Entrées que la publication remplacerait : même référence, ou mêmes fichiers."""
    directory, stem = target(folder, component)
    title = (component.part_number or component.name).casefold()
    return [e for e in entries
            if e.title.casefold() == title
            or (e.folder == directory and e.stem.casefold() == stem.casefold())]


def publish(component, folder, project=True) -> tuple:
    """
    Écrit la fiche, le projet (si project) et, si un graphique a un rôle PLECS, la
    description PLECS. Remplace les fichiers de même nom : l'appelant a vérifié les
    conflits (conflicts) et mis à la corbeille ce qui doit l'être.
    Retourne (entrée, avertissements).
    """
    directory, stem = target(folder, component)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        warnings = []
        sheet = directory / f"{stem}{SHEET_SUFFIX}"
        export.write_component(component, sheet)
        project_path = None
        if project:
            project_path = directory / f"{stem}{document.PROJECT_SUFFIX}"
            document.save(component, project_path)
        plecs_path = directory / f"{stem}{PLECS_SUFFIX}"
        if any(g.plecs_role for g in component.graphs):
            try:
                text, notes = plecs.build(component)
            except plecs.PlecsError as error:
                warnings.append(f"description PLECS non écrite : {error}")
                if plecs_path.exists():          # ancienne version : ne correspond plus
                    plecs_path.unlink()
                plecs_path = None
            else:
                export.write_text(plecs_path, text)
                warnings += [f"PLECS : {n}" for n in notes]
        elif not plecs_path.exists():
            plecs_path = None
    except OSError as error:
        raise LibraryError(f"Écriture impossible dans {directory} :\n{error}") from None
    entry = Entry(folder=directory, stem=stem, sheet_path=sheet, project_path=project_path,
                  plecs_path=plecs_path if plecs_path and plecs_path.exists() else None)
    _describe(entry, export.component_dict(component), False)
    return entry, warnings


def remove(entries, folder, now=None) -> pathlib.Path:
    """
    Déplace les fichiers des entrées dans la corbeille de la librairie, sous un dossier
    daté qui garde leur chemin relatif. Retourne ce dossier.
    """
    folder = pathlib.Path(folder)
    stamp = (now or datetime.datetime.now()).strftime("%Y-%m-%d_%H%M%S")
    trash = folder / TRASH / stamp
    index = 1
    while trash.exists():
        index += 1
        trash = folder / TRASH / f"{stamp}_{index}"
    for entry in entries:
        for path in entry.files:
            try:
                relative = path.relative_to(folder)
            except ValueError:
                relative = pathlib.Path(path.name)
            destination = trash / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(os.fspath(path), os.fspath(destination))
    return trash
