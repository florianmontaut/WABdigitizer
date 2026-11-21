import json

from PyQt6 import QtCore, QtWidgets

import numpy as np
import pytest
from qtsocle import options_panel, theme

from helpers import dispose, make_controller
from model import document
from model.calibration import to_four_points
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


ORTHO_CLICKS = [CLICKS[0], CLICKS[1], CLICKS[3]]             # O, X2, Y2


def calibrated(ctrl):
    """Image + calibration par clics : 3 (repère orthonormé, défaut) ou 4 points."""
    ctrl.add_image(graph_image(), "VCE(IC)")
    clicks = ORTHO_CLICKS if ctrl.orthogonal else CLICKS
    for x, y in clicks:
        ctrl.canvas_pressed(x, y)
    assert len(ctrl.calibration_clicks) == len(clicks)
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
    vb = view.plot.getViewBox()                               # pas de dézoom infini
    vb.scaleBy((1e12, 1e12))
    x0, x1 = vb.viewRange()[0]
    assert x1 - x0 <= 2 * 200 + 1e-6                          # IC de 0 à 200 A
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


# ---------------------------------------------------------------- annuler / refaire, clavier
def click(ctrl, x, y, to=None):
    ctrl.canvas_pressed(x, y)
    if to is not None:
        ctrl.canvas_moved(*to, True)
    ctrl.canvas_released(*(to or (x, y)))


def key(ctrl, k, modifiers=QtCore.Qt.KeyboardModifier.NoModifier):
    from PyQt6 import QtTest
    QtTest.QTest.keyClick(ctrl.view.canvas, k, modifiers)


def test_annuler_refaire_ajout_deplacement_suppression(ctrl):
    graph = calibrated(ctrl)
    stack = ctrl.undo_stack
    click(ctrl, 300, 250)                                  # (5, 15)
    click(ctrl, 200, 300)                                  # (2.5, 10)
    click(ctrl, 200, 300, to=(220, 280))                   # déplacé en (3, 12)
    ctrl.set_mode(Mode.DELETE)
    click(ctrl, 300, 250)
    dataset = ctrl.dataset
    assert np.allclose(dataset.data(graph.calibration), [(3, 12)])
    assert stack.undoText() == "Supprimer un point"

    stack.undo()
    assert np.allclose(dataset.data(graph.calibration), [(3, 12), (5, 15)])
    stack.undo()
    assert np.allclose(dataset.data(graph.calibration), [(2.5, 10), (5, 15)])
    stack.undo()
    stack.undo()
    assert len(dataset) == 0
    for _ in range(4):
        stack.redo()
    assert np.allclose(dataset.data(graph.calibration), [(3, 12)])
    assert ctrl.view.table.rowCount() == 1


def test_clic_sans_mouvement_ne_remplit_pas_la_pile(ctrl):
    calibrated(ctrl)
    click(ctrl, 300, 250)
    count = ctrl.undo_stack.count()
    click(ctrl, 300.5, 250.5)                              # clic sur le point : sélection seule
    assert ctrl.undo_stack.count() == count and ctrl.selected_point == 0


def test_fleches_sur_le_point_selectionne(ctrl):
    calibrated(ctrl)
    click(ctrl, 300, 250)
    click(ctrl, 200, 300)                                  # sélectionné : le dernier placé
    assert ctrl.selected_point == 0                        # rangé par X
    count = ctrl.undo_stack.count()
    px = ctrl.view.canvas.pixel_size()                     # pixels de l'image par pixel d'écran
    key(ctrl, QtCore.Qt.Key.Key_Right)                     # +1 pixel d'écran
    key(ctrl, QtCore.Qt.Key.Key_Right, QtCore.Qt.KeyboardModifier.ShiftModifier)   # +10
    key(ctrl, QtCore.Qt.Key.Key_Up, QtCore.Qt.KeyboardModifier.ControlModifier)    # -0,1
    assert np.allclose(ctrl.dataset.pixels[0], (200 + 11 * px, 300 - 0.1 * px))
    assert ctrl.undo_stack.count() == count + 1            # appuis fusionnés
    assert ctrl.undo_stack.undoText() == "Ajuster un point"
    assert np.allclose(ctrl.view.canvas.selection_item.data["x"], [200 + 11 * px])
    ctrl.undo_stack.undo()
    assert np.allclose(ctrl.dataset.pixels[0], (200, 300))

    # le point dépasse son voisin en X : il est retrié et reste sélectionné
    presses = int(np.ceil(101 / (10 * px)))
    for _ in range(presses):
        key(ctrl, QtCore.Qt.Key.Key_Right, QtCore.Qt.KeyboardModifier.ShiftModifier)
    assert ctrl.selected_point == 1
    assert np.allclose(ctrl.dataset.pixels[1], (200 + 10 * px * presses, 300))
    assert ctrl.view.table.currentRow() == 1


def test_pas_des_fleches_suit_le_zoom(ctrl):
    calibrated(ctrl)
    canvas = ctrl.view.canvas
    canvas.resize(800, 600)
    canvas.view_box.setRange(xRange=(0, 600), yRange=(0, 500), padding=0)
    wide = canvas.pixel_size()
    canvas.view_box.setRange(xRange=(290, 310), yRange=(240, 260), padding=0)
    close = canvas.pixel_size()
    assert close < wide / 10                               # zoomé : pixel d'écran plus petit
    click(ctrl, 300, 250)
    key(ctrl, QtCore.Qt.Key.Key_Right)
    assert ctrl.dataset.pixels[0][0] == pytest.approx(300 + close)
    assert close < 0.1                                     # bien plus fin qu'un pixel de l'image


def test_tab_et_suppr(ctrl):
    calibrated(ctrl)
    for x in (150, 250, 350):
        click(ctrl, x, 300)
    key(ctrl, QtCore.Qt.Key.Key_Tab)                       # du 3e au 1er (boucle)
    assert ctrl.selected_point == 0
    key(ctrl, QtCore.Qt.Key.Key_Tab)
    key(ctrl, QtCore.Qt.Key.Key_Backtab)
    key(ctrl, QtCore.Qt.Key.Key_Tab)
    assert ctrl.selected_point == 1
    key(ctrl, QtCore.Qt.Key.Key_Delete)
    assert np.allclose(ctrl.dataset.pixels[:, 0], [150, 350])
    assert ctrl.selected_point == 1
    ctrl.view.table.setCurrentCell(0, 0)                   # sélection depuis la table
    assert ctrl.selected_point == 0
    ctrl.set_mode(Mode.NAVIGATE)                           # hors édition : touches ignorées
    key(ctrl, QtCore.Qt.Key.Key_Delete)
    assert len(ctrl.dataset) == 2


def test_fleches_pendant_et_apres_la_calibration(ctrl):
    ctrl.add_image(graph_image())
    px = ctrl.view.canvas.pixel_size()
    ctrl.canvas_pressed(100 - px, 400 + px)                # O un pixel d'écran à côté
    key(ctrl, QtCore.Qt.Key.Key_Right)
    key(ctrl, QtCore.Qt.Key.Key_Up)
    assert ctrl.calibration_clicks == [pytest.approx((100, 400))]
    for x, y in ORTHO_CLICKS[1:]:
        ctrl.canvas_pressed(x, y)
    assert ctrl.apply_calibration(to_four_points(*ctrl.calibration_clicks), VALUES)
    graph = ctrl.graph
    stack = ctrl.undo_stack
    assert stack.undoText() == "Calibrer les axes"

    # repère X2 sélectionné puis ajusté : calibration recalculée, une étape
    ctrl.set_mode(Mode.CALIBRATE)
    click(ctrl, 500.5, 400.5)
    assert ctrl.calibration_marker == 1 and ctrl.calibration_clicks == []
    px = ctrl.view.canvas.pixel_size()
    for _ in range(4):
        key(ctrl, QtCore.Qt.Key.Key_Right, QtCore.Qt.KeyboardModifier.ShiftModifier)
    moved = 500 + 40 * px
    assert graph.calibration.px_x2 == pytest.approx((moved, 400.0))
    assert graph.calibration.pixel_to_data([(moved, 400)])[0] == pytest.approx((10, 0))
    assert stack.undoText() == "Ajuster un repère d'axe"
    stack.undo()
    assert graph.calibration.px_x2 == (500.0, 400.0)

    # repère glissé à la souris
    click(ctrl, 100, 100, to=(100, 90))
    assert graph.calibration.px_y2 == (100.0, 90.0)
    stack.undo()
    stack.undo()                                           # calibration elle-même
    assert not graph.calibrated
    stack.redo()
    assert graph.calibrated and graph.extraction.grid_stop == 10


def test_annuler_le_masque_et_l_extraction(ctrl):
    calibrated(ctrl)
    ctrl.set_mode(Mode.PAINT)
    click(ctrl, 150, 345, to=(450, 195))
    dataset = ctrl.dataset
    painted = dataset.mask.copy()
    assert painted.any()
    command = ctrl.undo_stack.command(ctrl.undo_stack.index() - 1)
    assert command.region_before.size < painted.size / 2      # seule la zone touchée
    dataset.curve_color = (220, 20, 20)
    ctrl.extract()
    assert len(dataset) > 5
    ctrl.clear_mask()
    assert not dataset.mask.any()

    ctrl.undo_stack.undo()                                 # effacer le masque
    assert np.array_equal(dataset.mask, painted)
    ctrl.undo_stack.undo()                                 # extraction
    assert len(dataset) == 0
    ctrl.undo_stack.undo()                                 # coup de pinceau
    assert not dataset.mask.any()
    ctrl.undo_stack.redo()
    assert np.array_equal(dataset.mask, painted)


def test_annuler_courbes_et_graphiques(ctrl):
    graph = calibrated(ctrl)
    click(ctrl, 300, 250)
    first = ctrl.dataset
    ctrl.add_dataset()
    assert len(graph.datasets) == 2
    ctrl.delete_selection()                                # la nouvelle courbe
    ctrl.dataset_index = 0
    ctrl.delete_selection()                                # la première, avec son point
    assert graph.datasets == []
    ctrl.undo_stack.undo()
    assert graph.datasets == [first] and len(first) == 1 and ctrl.dataset is first

    ctrl.add_image(graph_image(), "second")
    assert len(ctrl.component.graphs) == 2 and ctrl.graph.name == "second"
    ctrl.undo_stack.undo()
    assert len(ctrl.component.graphs) == 1 and ctrl.graph is graph

    ctrl.dataset_index = None
    ctrl.delete_selection()                                # le graphique entier
    assert ctrl.component.graphs == [] and ctrl.graph is None
    ctrl.undo_stack.undo()
    assert ctrl.component.graphs == [graph] and ctrl.graph is graph


def test_etat_modifie_suit_la_pile(ctrl, tmp_path):
    calibrated(ctrl)
    click(ctrl, 300, 250)
    assert ctrl.dirty and ctrl.view.windowTitle().startswith("* ")
    path = tmp_path / ("p" + document.PROJECT_SUFFIX)
    assert ctrl.write_project(path)
    assert not ctrl.dirty
    ctrl.undo_stack.undo()
    assert ctrl.dirty
    ctrl.undo_stack.redo()
    assert not ctrl.dirty                                  # retour à l'état enregistré
    ctrl.view.params["dataset"]["Condition"] = "Tj = 25 °C"   # propriété : hors pile
    assert ctrl.dirty
    ctrl.load_project(path)
    assert not ctrl.dirty and ctrl.undo_stack.count() == 0
    assert not ctrl.view.actionUndo.isEnabled()


# ---------------------------------------------------------------- repère orthonormé
def test_calibration_en_trois_clics_ramenes_sur_les_axes(ctrl):
    assert ctrl.orthogonal                                 # option par défaut
    ctrl.add_image(graph_image())
    canvas = ctrl.view.canvas
    ctrl.canvas_pressed(100, 400)                          # O
    ctrl.canvas_moved(480, 391, False)                     # survol : X2 suit, sur l'axe
    assert canvas.calibration_points.data["y"].tolist() == [400, 400]
    ctrl.canvas_pressed(500, 397)                          # X2 un peu haut
    ctrl.canvas_moved(97, 120, False)
    assert canvas.calibration_points.data["x"].tolist() == [100, 500, 100]
    assert [t.toPlainText() for t in canvas.calibration_texts] == ["O", "X2", "Y2"]
    ctrl.canvas_pressed(103, 100)                          # Y2 un peu à droite : 3e et dernier
    assert ctrl.calibration_clicks == [(100, 400), (500, 397), (103, 100)]
    assert ctrl.apply_calibration(to_four_points(*ctrl.calibration_clicks), VALUES)
    cal = ctrl.graph.calibration
    assert cal.orthogonal and cal.px_x2 == (500, 400) and cal.px_y2 == (100, 100)
    assert cal.skew_degrees() == pytest.approx(0)


def test_origine_deplacee_aux_fleches(ctrl):
    graph = calibrated(ctrl)
    ctrl.set_mode(Mode.CALIBRATE)
    assert len(ctrl.view.canvas.calibration_texts) == 3    # O, X2, Y2
    click(ctrl, 100.5, 400.5)                              # O
    assert ctrl.calibration_marker == 0
    px = ctrl.view.canvas.pixel_size()
    key(ctrl, QtCore.Qt.Key.Key_Down, QtCore.Qt.KeyboardModifier.ShiftModifier)
    cal = graph.calibration
    assert cal.orthogonal
    assert cal.px_x1 == pytest.approx((100, 400 + 10 * px))
    assert cal.px_x2 == pytest.approx((500, 400 + 10 * px))     # axe X suit O
    assert cal.px_y2 == pytest.approx((100, 100))
    click(ctrl, 500, 400 + 10 * px, to=(520, 380))          # X2 glissé en biais
    assert graph.calibration.px_x2 == pytest.approx((520, 400 + 10 * px))   # reste sur l'axe


def test_option_quatre_points(ctrl):
    ctrl.options["orthogonal_axes"] = False
    graph = calibrated(ctrl)                               # 4 clics
    assert graph.calibrated
    ctrl.set_mode(Mode.CALIBRATE)
    # CLICKS est exactement orthonormé (X1 = Y1...) : reconnu comme tel à l'affichage
    assert [t.toPlainText() for t in ctrl.view.canvas.calibration_texts] == ["O", "X2", "Y2"]

    ctrl.add_image(graph_image())                          # tourné : 4 points libres
    for x, y in [(100, 400), (500, 410), (90, 400), (100, 100)]:
        ctrl.canvas_pressed(x, y)
    assert len(ctrl.calibration_clicks) == 4
    assert ctrl.apply_calibration(ctrl.calibration_clicks, VALUES)
    assert not ctrl.graph.calibration.orthogonal

    # option remise : une calibration à 4 points garde ses 4 repères
    ctrl.options["orthogonal_axes"] = True
    ctrl.set_mode(Mode.CALIBRATE)
    assert [t.toPlainText() for t in ctrl.view.canvas.calibration_texts] == ["X1", "X2", "Y1", "Y2"]


def test_option_dans_les_reglages(ctrl):
    dialog = options_panel.OptionsPannel(ctrl.schema, ctrl.options, ctrl.view)
    assert dialog.getOptions()["orthogonal_axes"] is True
    from view.dialogs import CalibrationDialog
    texts = [w.text() for w in CalibrationDialog({}, ctrl.view, True).findChildren(
        QtWidgets.QLabel)]
    assert any("origine O" in t for t in texts)


# ---------------------------------------------------------------- librairie
def digitized(ctrl, part="FF600R12", category="IGBT"):
    """Composant ouvert : un graphique calibré, deux points, référence et catégorie."""
    calibrated(ctrl)
    for x, y in [(100, 400), (500, 100)]:
        ctrl.canvas_pressed(x, y)
        ctrl.canvas_released(x, y)
    ctrl.view.params["graph"]["Unité X"] = "A"
    ctrl.view.params["graph"]["Unité Y"] = "V"
    ctrl.view.params["component"]["Référence"] = part
    ctrl.view.params["component"]["Catégorie"] = category


def library_rows(ctrl):
    proxy = ctrl.library.proxy
    return [proxy.index(row, 1).data() for row in range(proxy.rowCount())]


def test_publier_puis_republier(ctrl, tmp_path):
    folder = tmp_path / "library"
    ctrl.new_component()
    assert not ctrl.publish() and "rien à publier" in ctrl.view.last_error
    digitized(ctrl)
    assert ctrl.path is None and ctrl.dirty
    assert ctrl.publish()
    assert (folder / "IGBT" / "FF600R12.json").is_file()
    assert ctrl.path == folder / "IGBT" / "FF600R12.pdig.json" and not ctrl.dirty
    assert library_rows(ctrl) == ["FF600R12"]
    assert [e.title for e in ctrl.library.selected()] == ["FF600R12"]

    # projet de la librairie : republié sans question, à sa place
    ctrl.view.params["component"]["Notes"] = "corrigé"
    ctrl.view.last_question = None
    assert ctrl.publish() and ctrl.view.last_question is None
    assert library_rows(ctrl) == ["FF600R12"]
    assert ctrl.library.selected()[0].notes == "corrigé"

    # catégorie changée : l'entrée suit, l'ancienne va à la corbeille
    ctrl.view.params["component"]["Catégorie"] = "MOSFET"
    assert ctrl.publish() and ctrl.view.last_question is None
    assert ctrl.path == folder / "MOSFET" / "FF600R12.pdig.json"
    assert not (folder / "IGBT" / "FF600R12.json").exists()
    assert list((folder / "_corbeille").rglob("FF600R12.json"))
    assert library_rows(ctrl) == ["FF600R12"]


def test_publier_une_reference_deja_presente(ctrl, tmp_path):
    folder = tmp_path / "library"
    digitized(ctrl)
    assert ctrl.publish()
    ctrl.new_component()
    digitized(ctrl)                                            # autre projet, même référence
    ctrl.view.answer = False
    assert not ctrl.publish() and "déjà" in ctrl.view.last_question
    assert ctrl.path is None
    ctrl.view.answer = True
    assert ctrl.publish()
    assert len(list((folder / "_corbeille").rglob("FF600R12.pdig.json"))) == 1
    assert library_rows(ctrl) == ["FF600R12"]


def test_ouvrir_comparer_supprimer(ctrl, tmp_path):
    folder = tmp_path / "library"
    digitized(ctrl, "A1")
    assert ctrl.publish()
    ctrl.new_component()
    digitized(ctrl, "B2", "MOSFET")
    assert ctrl.publish()
    ctrl.new_component()
    ctrl.library.reload()
    assert library_rows(ctrl) == ["A1", "B2"]

    ctrl.library.select_keys([e.key for e in ctrl.library.entries.values() if e.title == "A1"])
    assert ctrl.library_open()
    assert ctrl.component.part_number == "A1" and ctrl.graph.calibrated

    ctrl.library.select_keys(list(ctrl.library.entries))
    assert ctrl.library_compare() == 2                         # une courbe par composant
    assert len(ctrl.compare.selected) == 2
    assert ctrl.library_reveal() == ctrl.library.selected()[0].sheet_path

    # corbeille : le projet ouvert (A1) n'a plus de fichier
    ctrl.library.select_keys([e.key for e in ctrl.library.entries.values() if e.title == "A1"])
    assert ctrl.library_remove()
    assert ctrl.path is None and ctrl.dirty
    assert library_rows(ctrl) == ["B2"]
    assert ctrl.library.selected() == []


def test_changer_de_librairie(ctrl, tmp_path):
    digitized(ctrl)
    assert ctrl.publish()
    other = tmp_path / "partage"
    ctrl.apply_options({"library_dir": str(other)})
    assert library_rows(ctrl) == [] and str(other) in ctrl.view.library.status.text()
    ctrl.view.library.filter.setText("igbt")
    ctrl.apply_options({"library_dir": str(tmp_path / "library")})
    assert library_rows(ctrl) == ["FF600R12"]                  # filtre sur la catégorie
    ctrl.view.library.filter.setText("mosfet")
    assert library_rows(ctrl) == []


def test_fiche_sans_projet_en_lecture_seule(ctrl, tmp_path):
    folder = tmp_path / "library"
    digitized(ctrl, "A1")
    assert ctrl.publish()
    ctrl.fit_model()                                           # modèle gardé dans la fiche
    assert ctrl.publish()
    (folder / "IGBT" / "A1.pdig.json").unlink()                # projet perdu : fiche seule
    ctrl.new_component()
    ctrl.library.reload()
    ctrl.library.select_keys(list(ctrl.library.entries))
    assert ctrl.library_open()
    assert ctrl.read_only and "[lecture seule]" in ctrl.view.windowTitle()
    graph = ctrl.graph
    assert graph.calibrated and graph.image.shape == (600, 900, 3)
    assert np.allclose(graph.datasets[0].data(graph.calibration), [(0, 0), (10, 30)])
    assert graph.datasets[0].fit is not None
    assert ctrl.view.table.rowCount() == 2

    # rien n'est modifiable, rien ne marque le projet modifié
    view = ctrl.view
    assert not view.actionSave.isEnabled() and not view.actionPublish.isEnabled()
    assert not view.modeActions[Mode.ADD].isEnabled() and not view.parameters.isEnabled()
    ctrl.set_mode(Mode.ADD)
    assert view.canvas.mode == Mode.NAVIGATE and "lecture seule" in view.statusBar().currentMessage()
    ctrl.canvas_pressed(300, 300)
    ctrl.selected_point = 0
    ctrl.nudge(5, 5)
    ctrl.key_command("delete")
    ctrl.add_dataset()
    ctrl.delete_selection()
    assert not ctrl.save_project() and not ctrl.publish()
    assert len(graph.datasets) == 1 and len(graph.datasets[0]) == 2
    assert ctrl.undo_stack.count() == 0 and not ctrl.dirty
    ctrl.view.tree.model().item(0).child(0).setCheckState(QtCore.Qt.CheckState.Unchecked)
    assert not graph.datasets[0].visible and not ctrl.dirty

    # exports et comparaison : la fiche n'est comptée qu'une fois
    csv = tmp_path / "c.csv"
    ctrl._save_name = lambda *args: str(csv)
    ctrl.export_csv()
    assert len(csv.read_text("utf-8").splitlines()) == 3      # en-tête + 2 points
    assert ctrl.current_sheet() is None
    assert ctrl.library_compare() == 1

    # nouveau composant : modifiable de nouveau
    ctrl.new_component()
    assert not ctrl.read_only and view.actionSave.isEnabled() and view.parameters.isEnabled()


def test_fiche_ouverte_comme_un_fichier(ctrl, tmp_path):
    digitized(ctrl, "A1")
    path = tmp_path / "a1.json"
    from model import export as export_
    export_.write_component(ctrl.component, path)
    ctrl.new_component()
    ctrl.open_files([str(path)])                               # glisser-déposer
    assert ctrl.read_only and ctrl.component.part_number == "A1"
    ctrl.load_project(tmp_path / "library" / "absent.json")
    assert "absent.json" in ctrl.view.last_error and ctrl.read_only


# ---------------------------------------------------------------- import PDF
def test_importer_une_datasheet_pdf(ctrl, tmp_path):
    pytest.importorskip("pdfminer")
    pytest.importorskip("pypdfium2")
    pytest.importorskip("matplotlib")
    from test_pdfimport import datasheet
    pdf = datasheet(tmp_path / "essai.pdf")
    calibrated(ctrl)                                    # composant en cours, remplacé
    assert ctrl.view.actionImportPdf.isEnabled()
    assert ctrl.import_pdf(pdf, choose=[1])            # le second graphique seulement
    c = ctrl.component
    assert c.name == "essai" and len(c.graphs) == 1 and ctrl.path is None
    assert ctrl.dirty and ctrl.undo_stack.count() == 0 and not ctrl.read_only
    graph = c.graphs[0]
    assert graph.name.startswith("Figure 2.") and graph.calibration.log_y
    assert sorted(d.name for d in graph.datasets) == ["Eoff", "Eon"]
    assert "Importé de essai.pdf : 1 graphique(s)" in c.notes and "Figure 1." not in c.notes
    assert ctrl.graph is graph and ctrl.dataset is graph.datasets[0]
    # sans écran, sans choix : tous ; aussi par glisser-déposer
    ctrl.open_files([str(pdf)])
    assert len(ctrl.component.graphs) == 2
    # rien de choisi, PDF sans graphique, fichier illisible : composant gardé
    assert not ctrl.import_pdf(pdf, choose=[])
    (tmp_path / "faux.pdf").write_text("pas un PDF", "utf-8")
    assert not ctrl.import_pdf(tmp_path / "faux.pdf")
    assert "illisible" in ctrl.view.last_error and len(ctrl.component.graphs) == 2
    # le composant importé s'enregistre et se rouvre
    assert ctrl.write_project(tmp_path / "essai.pdig.json")
    ctrl.load_project(tmp_path / "essai.pdig.json")
    assert len(ctrl.component.graphs) == 2 and ctrl.component.graphs[1].calibrated


def test_dialogue_d_import_pdf(tmp_path):
    pytest.importorskip("pdfminer")
    pytest.importorskip("pypdfium2")
    pytest.importorskip("matplotlib")
    from model import pdfimport
    from test_pdfimport import datasheet
    from view.pdf_import_dialog import PdfImportDialog
    pdf = datasheet(tmp_path / "essai.pdf")
    found = pdfimport.analyse(pdf)
    component, _ = pdfimport.to_component(pdf, found, dpi=100)
    app = QtWidgets.QApplication.instance()
    dialog = PdfImportDialog("essai.pdf", component.graphs, found)
    assert dialog.selected() == [0, 1] and dialog.table.rowCount() == 2
    assert dialog.table.item(1, 4).text().startswith("E [mJ]") and "log" in dialog.table.item(1, 4).text()
    dialog.uncheck_all()
    assert dialog.selected() == []
    dialog.table.item(1, 0).setCheckState(QtCore.Qt.CheckState.Checked)
    assert dialog.selected() == [1]
    dialog.table.selectRow(1)
    assert "Eon" in dialog.details.toPlainText() and not dialog.preview.pixmap().isNull()
    dialog.deleteLater()
    app.processEvents()


def test_separer_les_points_du_masque(ctrl):
    graph = calibrated(ctrl)
    dataset = ctrl.dataset
    zigzag = np.array([(150 + 20 * i, 300 if i % 2 else 200) for i in range(10)], float)
    dataset.pixels = zigzag.copy()
    assert not ctrl.split_points()                       # pas de masque : pinceau proposé
    assert ctrl.view.canvas.mode == Mode.PAINT
    mask = graph.mask_of(dataset)
    mask[290:311, :] = True                              # la courbe du bas
    count = ctrl.undo_stack.count()
    assert ctrl.split_points()
    assert ctrl.undo_stack.count() == count + 1          # une seule étape
    first, second = graph.datasets
    assert np.allclose(first.pixels[:, 1], 200) and len(first) == 5
    assert np.allclose(second.pixels[:, 1], 300) and len(second) == 5
    assert second.name == f"{first.name} (2)" and not first.mask.any()
    assert ctrl.dataset is second
    ctrl.undo_stack.undo()
    assert len(graph.datasets) == 1 and len(dataset) == 10 and dataset.mask.any()
    ctrl.undo_stack.redo()
    assert len(graph.datasets) == 2 and len(graph.datasets[0]) == 5
    # masque sur tous les points : refusé
    ctrl.select(0, 1)
    graph.mask_of(ctrl.dataset)[:, :] = True
    assert not ctrl.split_points() and len(graph.datasets) == 2
