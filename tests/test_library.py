"""Librairie de composants : lecture du dossier, publication, corbeille."""
import datetime
import json

import numpy as np
import pytest

from model import document, export, library
from model.calibration import AxisCalibration
from model.library import LibraryError

from test_plecs import reference_component


def component(part="FF600R12", category="IGBT", name="Module"):
    c = document.Component(name=name, manufacturer="Infineon", part_number=part,
                           category=category)
    graph = c.add_graph(np.full((10, 10, 3), 255, np.uint8), "VCE(IC)")
    graph.set_calibration(AxisCalibration((0, 100), (100, 100), (0, 100), (0, 0), 0, 100, 0, 5))
    graph.x_axis, graph.y_axis = document.Axis("IC", "A"), document.Axis("VCE", "V")
    graph.datasets[0].set_data([(10, 1), (90, 3)], graph.calibration)
    return c


def test_nom_de_fichier_valide():
    assert library.safe_name('IKW40N120H3 / "rev2"?') == "IKW40N120H3 _ _rev2__"
    assert library.safe_name(" a.b. ") == "a.b"


def test_publication_puis_lecture(tmp_path):
    entry, warnings = library.publish(component(), tmp_path)
    assert warnings == [] and entry.folder == tmp_path / "IGBT"
    assert entry.sheet_path.name == "FF600R12.json"
    assert entry.project_path.name == "FF600R12.pdig.json" and entry.plecs_path is None
    sheet = json.loads(entry.sheet_path.read_text("utf-8"))
    assert sheet["format"] == export.COMPONENT_FORMAT
    assert document.load(entry.project_path).part_number == "FF600R12"

    entries, errors = library.scan(tmp_path)
    assert errors == [] and len(entries) == 1
    read = entries[0]
    assert (read.title, read.manufacturer, read.category) == ("FF600R12", "Infineon", "IGBT")
    assert read.graphs == ["VCE(IC)"] and read.curves == 1
    assert read.data_path == read.sheet_path and read.project_path is not None
    assert read.key == entry.key and read.modified > 0


def test_sans_categorie_ni_reference(tmp_path):
    entry, _ = library.publish(component(part="", category="", name="Essai"), tmp_path)
    assert entry.folder.name == library.UNSORTED and entry.stem == "Essai"
    with pytest.raises(LibraryError, match="référence ou un nom"):
        library.publish(component(part="", name=""), tmp_path)


def test_export_plecs_dans_la_librairie(tmp_path):
    entry, warnings = library.publish(reference_component(), tmp_path)
    assert entry.plecs_path is not None and entry.plecs_path.suffix == ".xml"
    assert "SemiconductorLibrary" in entry.plecs_path.read_text("utf-8")
    entries, _ = library.scan(tmp_path)
    assert entries[0].plecs_path == entry.plecs_path


def test_fichiers_ranges_a_la_main_et_erreurs(tmp_path):
    # fiche seule à plat, projet seul dans un autre dossier, fichiers étrangers
    export.write_component(component("A1", "Diode"), tmp_path / "a1.json")
    other = tmp_path / "anciens"
    other.mkdir()
    document.save(component("B2", "MOSFET"), other / "b2.pdig.json")
    (tmp_path / "settings.json").write_text('{"dark_mode": true}', "utf-8")
    (tmp_path / "casse.json").write_text("{", "utf-8")
    (tmp_path / "seul.xml").write_text("<x/>", "utf-8")
    entries, errors = library.scan(tmp_path)
    assert [e.title for e in entries] == ["A1", "B2"]                # Diode, MOSFET
    assert entries[0].project_path is None and entries[1].sheet_path is None
    assert entries[1].data_path.name == "b2.pdig.json" and entries[1].curves == 1
    assert len(errors) == 2


def test_projet_et_fiche_comptes_une_fois(tmp_path):
    library.publish(component(), tmp_path)
    from model import compare
    files = compare.library_files(tmp_path)
    assert len(files) == 1 and files[0].name == "FF600R12.json"
    curves, _ = compare.load_files(files)
    assert len(curves) == 1


def test_conflits_et_reference_en_double(tmp_path):
    library.publish(component(), tmp_path)
    entries, _ = library.scan(tmp_path)
    # même référence, autre catégorie : conflit quand même
    moved = component(category="MOSFET")
    assert library.conflicts(entries, tmp_path, moved) == entries
    assert library.conflicts(entries, tmp_path, component(part="Autre")) == []
    library.publish(moved, tmp_path)
    entries, errors = library.scan(tmp_path)
    assert len(entries) == 2 and len(errors) == 1 and "en double" in errors[0]


def test_corbeille(tmp_path):
    library.publish(component(), tmp_path)
    library.publish(component("D1", "Diode"), tmp_path)
    entries, _ = library.scan(tmp_path)
    now = datetime.datetime(2026, 11, 21, 10, 30, 0)
    trash = library.remove([e for e in entries if e.title == "D1"], tmp_path, now)
    assert trash == tmp_path / "_corbeille" / "2026-11-21_103000"
    assert (trash / "Diode" / "D1.json").is_file()
    assert (trash / "Diode" / "D1.pdig.json").is_file()
    entries, errors = library.scan(tmp_path)                         # corbeille ignorée
    assert [e.title for e in entries] == ["FF600R12"] and errors == []
    second = library.remove(entries, tmp_path, now)                  # même seconde
    assert second.name == "2026-11-21_103000_2"


def test_fiche_vers_composant_affichable():
    from model import sheet
    from model.sheet import SheetError
    data = export.component_dict(component())
    data["graphs"][0]["y"]["log"] = True
    data["graphs"][0]["curves"][0]["y"][0] = 0.0                     # inaffichable en log
    data["graphs"][0]["curves"].append({"name": "un point", "x": [5], "y": [2]})
    data["graphs"].append({"name": "", "x": {}, "y": {}, "curves": []})
    comp, warnings = sheet.component_from_sheet(data, "f.json")
    assert comp.part_number == "FF600R12" and len(comp.graphs) == 2
    graph = comp.graphs[0]
    assert graph.calibration.log_y and graph.calibration.orthogonal
    assert np.allclose(graph.datasets[0].data(graph.calibration), [(90, 3)])
    assert np.allclose(graph.datasets[1].data(graph.calibration), [(5, 2)])
    assert len(warnings) == 1 and "inaffichable" in warnings[0]
    assert comp.graphs[1].name == "Graphique 2" and comp.graphs[1].calibrated
    with pytest.raises(SheetError):
        sheet.component_from_sheet({"format": "autre"})
