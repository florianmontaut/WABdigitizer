import json

from PyQt6 import QtCore

import numpy as np
import pytest
from qtsocle import options_panel, theme

from helpers import dispose, make_controller
from model import document
from view.canvas import Mode

CLICKS = [(100, 400), (500, 400), (100, 400), (100, 100)]   # X1, X2, Y1, Y2
VALUES = {"x1": 0, "x2": 10, "y1": 0, "y2": 30, "log_x": False, "log_y": False}


def graph_image():
    """Image 500 x 600 : droite rouge y = 2x + 3 (unités de CLICKS / VALUES), grille grise."""
    image = np.full((500, 600, 3), 255, np.uint8)
    image[100:401:50, 100:501] = (180, 180, 180)
    for col in range(140, 461):
        x = (col - 100) / 40.0
        row = int(round(400 - (2 * x + 3) * 10))
        image[row - 1:row + 2, col] = (220, 20, 20)
    return image


@pytest.fixture
def ctrl(tmp_path):
    controller = make_controller(tmp_path)
    yield controller
    dispose(controller)


def calibrated(ctrl):
    ctrl.add_image(graph_image(), "VCE(IC)")
    for x, y in CLICKS:
        ctrl.canvas_pressed(x, y)
    assert len(ctrl.calibration_clicks) == 4
    assert ctrl.apply_calibration(CLICKS, VALUES)
    return ctrl.graph


# ---------------------------------------------------------------- socle
def test_demarrage_avec_les_options_par_defaut(ctrl, tmp_path):
    assert ctrl.options["library_dir"] == str(tmp_path / "library")
    assert ctrl.options["dark_mode"] is False
    assert ctrl.options["separator"] == ";"


def test_theme_sombre(ctrl):
    ctrl.view.actionDark.setChecked(True)
    assert theme.colors() is theme.DARK
    ctrl.view.actionDark.setChecked(False)


def test_reglages_enregistres_a_la_fermeture(tmp_path):
    ctrl = make_controller(tmp_path)
    ctrl.view.actionDark.setChecked(True)
    dispose(ctrl)
    saved = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert saved["dark_mode"] is True
    ctrl = make_controller(tmp_path)
    assert ctrl.view.actionDark.isChecked()
    ctrl.view.actionDark.setChecked(False)
    dispose(ctrl)


def test_fenetre_d_options(ctrl, tmp_path):
    dialog = options_panel.OptionsPannel(ctrl.schema, ctrl.options, ctrl.view)
    values = dialog.getOptions()
    assert values["library_dir"] == str(tmp_path / "library")
    assert values["brush_radius"] == 8.0


# ---------------------------------------------------------------- numérisation
def test_image_puis_calibration(ctrl):
    graph = calibrated(ctrl)
    assert graph.calibrated
    assert ctrl.view.canvas.mode == Mode.ADD
    assert graph.extraction.grid_start == 0 and graph.extraction.grid_stop == 10
    assert ctrl.view.params["graph"]["Calibration"].startswith("X 0 → 10")
    assert ctrl.dirty


def test_calibration_invalide_refusee(ctrl):
    ctrl.add_image(graph_image())
    assert not ctrl.apply_calibration(CLICKS, {**VALUES, "x2": 0})
    assert not ctrl.graph.calibrated


def test_points_manuels_ajout_deplacement_suppression(ctrl):
    graph = calibrated(ctrl)
    ctrl.canvas_pressed(300, 250)                # x = 5, y = 15
    ctrl.canvas_released(300, 250)
    ctrl.canvas_pressed(200, 300)                # x = 2.5, y = 10
    ctrl.canvas_released(200, 300)
    dataset = ctrl.dataset
    assert np.allclose(dataset.data(graph.calibration), [(2.5, 10), (5, 15)])
    assert ctrl.view.table.rowCount() == 2

    # glisser le premier point
    ctrl.canvas_pressed(200.5, 300.5)
    ctrl.canvas_moved(220, 280, True)
    ctrl.canvas_released(220, 280)
    assert np.allclose(dataset.data(graph.calibration)[0], (3, 12))

    # saisie dans la table (virgule décimale)
    ctrl.view.table.item(1, 1).setText("16,5")
    assert dataset.data(graph.calibration)[1] == pytest.approx((5, 16.5))

    ctrl.set_mode(Mode.DELETE)
    ctrl.canvas_pressed(220, 280)
    assert len(dataset) == 1


def test_masque_extraction_et_modele(ctrl):
    graph = calibrated(ctrl)
    ctrl.set_mode(Mode.PAINT)
    ctrl.view.canvas.set_brush_radius(12)
    # trait le long de la droite (sans toucher la grille hors de la courbe)
    start = (150, 400 - (2 * 1.25 + 3) * 10)
    end = (450, 400 - (2 * 8.75 + 3) * 10)
    ctrl.canvas_pressed(*start)
    ctrl.canvas_moved(*end, True)
    ctrl.canvas_released(*end)
    assert ctrl.dataset.mask.any()

    ctrl.set_mode(Mode.PICK)
    ctrl.canvas_pressed(300, 400 - 13 * 10)      # x = 5 -> y = 13
    assert ctrl.dataset.curve_color == (220, 20, 20)

    ctrl.view.actionDetection.setChecked(True)
    grid = ctrl.view.params["extraction"].child("Grille")
    grid["X début"], grid["X fin"], grid["Pas"] = 2.0, 8.0, 0.5
    ctrl.extract()
    data = ctrl.dataset.data(graph.calibration)
    assert np.allclose(data[:, 0], np.arange(2.0, 8.01, 0.5))
    assert np.allclose(data[:, 1], 2 * data[:, 0] + 3, atol=0.15)

    model = ctrl.view.params["model"]
    model["Modèle type"] = "Linéaire"
    assert model["Formule"] == "a*x + b"
    ctrl.fit_model()
    assert ctrl.dataset.fit.parameters["a"] == pytest.approx(2, abs=0.03)
    assert "R²" in model["Résultat"]
    assert ctrl.model_pixels(graph, ctrl.dataset) is not None


def test_fenetre_glissante_depuis_les_parametres(ctrl):
    graph = calibrated(ctrl)
    dataset = ctrl.dataset
    graph.mask_of(dataset)[:, :] = True
    dataset.curve_color, dataset.tolerance = (220, 20, 20), 60
    ctrl.fill_extraction()
    ctrl.view.params["extraction"]["Méthode"] = "Fenêtre glissante"
    assert graph.extraction.method == "Fenêtre glissante"
    ctrl.extract()
    data = ctrl.dataset.data(graph.calibration)
    assert len(data) > 30
    assert np.max(np.abs(data[:, 1] - (2 * data[:, 0] + 3))) < 0.2


def test_courbes_arborescence_et_proprietes(ctrl):
    graph = calibrated(ctrl)
    ctrl.add_dataset()
    assert len(graph.datasets) == 2 and ctrl.dataset_index == 1
    ctrl.view.params["dataset"]["Condition"] = "Tj = 125 °C"
    assert graph.datasets[1].condition == "Tj = 125 °C"
    ctrl.view.params["graph"]["Unité Y"] = "V"
    assert graph.y_axis.unit == "V"
    root = ctrl.tree_model.item(0)
    assert root.rowCount() == 2 and "Tj = 125 °C" in root.child(1).text()
    ctrl.delete_selection()
    assert len(graph.datasets) == 1


def test_projet_enregistre_et_relu(ctrl, tmp_path):
    graph = calibrated(ctrl)
    ctrl.canvas_pressed(300, 250)
    ctrl.view.params["component"]["Référence"] = "FF450R12"
    path = tmp_path / ("essai" + document.PROJECT_SUFFIX)
    assert ctrl.write_project(path)
    assert not ctrl.dirty

    ctrl.new_component()
    assert ctrl.graph is None
    ctrl.load_project(path)
    assert ctrl.component.part_number == "FF450R12"
    assert ctrl.graph.calibrated and len(ctrl.dataset) == 1
    assert ctrl.view.params["component"]["Référence"] == "FF450R12"
    assert np.array_equal(ctrl.graph.image, graph.image)


def test_glisser_deposer_une_image(ctrl, tmp_path):
    from PyQt6 import QtGui
    path = tmp_path / "graphe.png"
    image = graph_image()
    qimage = QtGui.QImage(image.data, 600, 500, 1800, QtGui.QImage.Format.Format_RGB888)
    assert qimage.save(str(path))
    ctrl.open_files([str(path)])
    assert ctrl.graph.name == "graphe"
    assert np.array_equal(ctrl.graph.image, image)
    assert ctrl.view.canvas.mode == Mode.CALIBRATE


def test_masque_et_couleur_propres_a_chaque_courbe(ctrl):
    graph = calibrated(ctrl)
    first = ctrl.dataset
    ctrl.set_mode(Mode.PAINT)
    ctrl.canvas_pressed(200, 300)
    ctrl.canvas_released(200, 300)
    first.curve_color = (220, 20, 20)
    ctrl.add_dataset()
    second = ctrl.dataset
    assert second is not first and second.mask is None
    assert ctrl.view.canvas.mask_item.image is None        # masque de la nouvelle courbe : vide
    ctrl.dataset_index = 0
    ctrl.refresh_all()
    assert ctrl.view.canvas.mask_item.image is not None
    assert ctrl.view.params["extraction"]["Couleur de la courbe"].red() == 220


def test_export_plecs_depuis_l_interface(ctrl, tmp_path):
    from model import plecs
    graph = calibrated(ctrl)
    ctrl.view.params["graph"]["Rôle PLECS"] = "turn_on"
    ctrl.view.params["graph"]["Unité X"] = "A"
    ctrl.view.params["graph"]["Unité Y"] = "mJ"
    assert graph.plecs_role == "turn_on"
    for x, y in [(100, 400), (300, 250), (500, 100)]:       # 0..10 A -> 0..30 mJ
        ctrl.canvas_pressed(x, y)
        ctrl.canvas_released(x, y)

    path = tmp_path / "x.xml"
    assert not ctrl.export_plecs(path)                       # pas de catégorie
    assert "catégorie" in ctrl.view.last_error

    ctrl.view.params["component"]["Catégorie"] = "IGBT"
    ctrl.view.params["dataset"]["Condition"] = "Tj = 150 °C"
    assert not ctrl.export_plecs(path)
    assert "tension de commutation" in ctrl.view.last_error
    ctrl.view.params["dataset"]["Tension (V)"] = "600"
    assert ctrl.dataset.voltage == 600.0

    group = ctrl.view.params["component"].child("Export PLECS")
    group["Intervalles (axe auto)"] = 5
    group["Modèle thermique Foster"] = "0.1\t0.01\n0.2\t0.1"
    assert ctrl.component.plecs.current_points == 5
    assert ctrl.export_plecs(path)
    tables = plecs.read_tables(path.read_text(encoding="utf-8"))
    on = tables["TurnOnLoss"]
    assert on["temperature"] == [150] and on["voltage"] == [0, 600]
    assert on["current"] == [0, 2, 4, 6, 8, 10]
    assert np.allclose(on["values"][0][1], [0, 6, 12, 18, 24, 30], atol=0.05)
    assert tables["foster"] == [(0.1, 0.01), (0.2, 0.1)]


def test_comparateur(ctrl, tmp_path):
    """Librairie (IGBT, MOSFET, diode) + composant ouvert, comparés en conduction."""
    from test_compare import sheet, write
    library = tmp_path / "library"
    library.mkdir(exist_ok=True)
    write(library, "igbt.json", sheet("IGBT1", "IGBT", [
        ("VCE(IC)", ("IC", "A", False), ("VCE", "V", False),
         [("Tj 125", "Tj = 125 °C", [0, 100, 200], [0.8, 1.6, 2.4])])]))
    write(library, "mosfet.json", sheet("MOS1", "MOSFET", [
        ("VDS(ID)", ("ID", "kA", False), ("VDS", "mV", False),
         [("Tj 125", "Tj = 125 °C", [0, 0.1, 0.2], [0, 1000, 2000])])]))
    write(library, "e.json", sheet("IGBT2", "IGBT", [
        ("Eon", ("IC", "A", False), ("Eon", "mJ", False), [("Eon", "", [1, 2], [1, 2])])]))

    graph = calibrated(ctrl)                                  # composant ouvert : 0..10 A, 0..30 V
    ctrl.view.params["graph"]["Unité X"] = "A"
    ctrl.view.params["graph"]["Unité Y"] = "V"
    ctrl.view.params["component"]["Nom"] = "Ouvert"
    for x, y in [(100, 400), (500, 100)]:
        ctrl.canvas_pressed(x, y)
        ctrl.canvas_released(x, y)

    ctrl.open_compare()
    cmp = ctrl.compare
    view = cmp.view
    assert "tension en fonction de courant" in view.characteristic.currentText()
    assert "3 composant(s)" in view.characteristic.currentText()
    assert cmp.tree_model.rowCount() == 3                     # Eon dans une autre caractéristique
    keys = {c.component: c.key for c in cmp.curves}
    assert "Ouvert" in keys

    cmp.set_checked([keys["IGBT1"], keys["MOS1"], keys["Ouvert"]])
    assert cmp.frame.y_axis.unit == "V" and cmp.frame.x_axis.unit == "A"
    cmp.set_cursor(100.0)
    assert view.table.rowCount() == 3
    assert view.table.item(0, 2).text() == "référence"
    assert view.table.item(1, 1).text() == "1 V"              # MOSFET converti (kA, mV)
    assert view.table.item(1, 3).text() == "-37.5 %"
    assert view.table.item(2, 1).text() == "hors plage"       # ouvert : 0..10 A

    view.filter.setText("mos")
    assert cmp.tree_model.rowCount() == 1
    assert len(cmp.selected) == 3                              # le filtre ne décoche pas

    csv_path, png_path = tmp_path / "c.csv", tmp_path / "c.png"
    assert cmp.export_csv(csv_path) and cmp.export_image(png_path)
    assert csv_path.read_text(encoding="utf-8").splitlines()[0].startswith("IC / ID (A);")
    assert png_path.stat().st_size > 1000

    index = view.characteristic.findText("énergie", QtCore.Qt.MatchFlag.MatchContains)
    view.characteristic.setCurrentIndex(index)
    assert cmp.selected == [] and view.table.rowCount() == 0
    ctrl.view.actionDark.setChecked(True)                     # thème propagé sans erreur
    ctrl.view.actionDark.setChecked(False)
