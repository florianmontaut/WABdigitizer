"""Export PLECS : comparaison avec un fichier fait à la main, cas d'erreur."""
import pathlib

import numpy as np
import pytest

from model import document, plecs
from model.calibration import AxisCalibration
from model.plecs import PlecsError, PlecsSettings

REFERENCE = pathlib.Path(__file__).parent / "plecs_reference_PMF75-120.xml"

# courbes du fichier de référence (MOSFET Mitsubishi PMF75-120, Tj = 125 °C, 600 V)
CURRENT = [10, 20, 30, 40, 50, 60, 70, 80]
EON = [0.63, 0.89, 1.14, 1.39, 1.66, 1.89, 2.14, 2.4]          # mJ
EOFF = [0.28, 0.41, 0.55, 0.69, 0.86, 1.08, 1.41, 1.73]        # mJ
VDROP = ([20, 40, 60, 80], [0.62, 1.31, 2.08, 2.9])            # V


def calibration(x_max=100.0, y_max=10.0):
    return AxisCalibration(px_x1=(0, 1000), px_x2=(1000, 1000), px_y1=(0, 1000),
                           px_y2=(0, 0), x1=0, x2=x_max, y1=0, y2=y_max)


def add_graph(component, name, role, x_unit, y_unit, curves, y_max=10.0):
    graph = component.add_graph(np.full((10, 10, 3), 255, np.uint8), name)
    graph.set_calibration(calibration(y_max=y_max))
    graph.plecs_role = role
    graph.x_axis = document.Axis("ID", x_unit)
    graph.y_axis = document.Axis(name, y_unit)
    graph.datasets.clear()
    for condition, xs, ys in curves:
        dataset = graph.add_dataset()
        dataset.condition = condition
        dataset.set_data(np.column_stack((xs, ys)), graph.calibration)
    return graph


def reference_component():
    component = document.Component(name="PMF75-120", manufacturer="Mitsubishi",
                                   part_number="PMF75-120-S002_Mosfet", category="MOSFET")
    add_graph(component, "Eon", "turn_on", "A", "mJ", [("Tj = 125 °C, VDS = 600 V", CURRENT, EON)])
    add_graph(component, "Eoff", "turn_off", "A", "mJ", [("Tj = 125 °C, VDS = 600 V", CURRENT, EOFF)])
    add_graph(component, "VDS(ID)", "conduction", "A", "V", [("Tj = 125 °C", *VDROP)])
    component.plecs = PlecsSettings(current_points=8, safety_factor=True, foster="0,41\t0,1")
    return component


# ---------------------------------------------------------------- conditions
@pytest.mark.parametrize("text, expected", [
    ("Tj = 125 °C, VCE = 600 V", (125.0, 600.0)),
    ("Tvj=25°C ; VGE = 15 V ; VCC = 1,2 kV", (25.0, 1200.0)),
    ("T = -40 °C", (-40.0, None)),
    ("VGS = 15 V", (None, None)),
    ("", (None, None)),
])
def test_conditions_lues_dans_le_texte(text, expected):
    assert plecs.parse_condition(text) == expected


def test_champs_prioritaires_sur_la_condition():
    dataset = document.Dataset("c", condition="Tj = 25 °C, VCE = 600 V", temperature=150.0)
    assert plecs.curve_conditions(dataset) == (150.0, 600.0)


def test_pas_rond():
    assert plecs.nice_step(80, 8) == 10
    assert plecs.nice_step(450, 10) == 50
    assert plecs.nice_step(37, 10) == 5


# ---------------------------------------------------------------- fichier de référence
def test_reproduit_le_fichier_fait_a_la_main():
    text, warnings = plecs.build(reference_component())
    ours, ref = plecs.read_tables(text), plecs.read_tables(REFERENCE.read_text(encoding="utf-8"))
    assert ours["class"] == ref["class"] == "MOSFET"
    assert ours["foster"] == ref["foster"] == [(0.41, 0.1)]

    for element, rows in (("TurnOnLoss", EON), ("TurnOffLoss", EOFF)):
        mine, theirs = ours[element], ref[element]
        assert (mine["method"], mine["formula"]) == (theirs["method"], theirs["formula"])
        assert mine["scale"] == theirs["scale"] == 0.001
        assert mine["temperature"] == theirs["temperature"] == [125.0]
        assert mine["current"] == [0, 10, 20, 30, 40, 50, 60, 70, 80]
        assert mine["voltage"] == [0.0, 600.0]
        assert np.allclose(mine["values"][0][0], 0)                    # 0 V
        assert np.allclose(mine["values"][0][1][1:], rows)             # 600 V, 10..80 A
        # mêmes valeurs que la référence aux mêmes courants
        ref_600 = theirs["values"][0][theirs["voltage"].index(600.0)]
        assert np.allclose(mine["values"][0][1][1:], np.array(ref_600)[3:])

    mine, theirs = ours["ConductionLoss"], ref["ConductionLoss"]
    assert mine["formula"] == theirs["formula"] == "v*Csecu"
    at = [mine["current"].index(i) for i in theirs["current"]]
    assert np.allclose(mine["values"][0][at], theirs["values"][0])
    assert warnings == []


def test_structure_du_fichier():
    text, _ = plecs.build(reference_component())
    assert text.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<SemiconductorLibrary '
                           'xmlns="http://www.plexim.com/xml/semiconductors/" version="1.1">')
    assert '<Package class="MOSFET" vendor="Mitsubishi" partnumber="PMF75-120-S002_Mosfet">' in text
    assert "<Name>Csecu</Name>" in text and "ns0:" not in text
    order = [text.index(tag) for tag in ("<Variables>", "<TurnOnLoss>", "<TurnOffLoss>",
                                         "<ConductionLoss>", "<ThermalModel>", "<Comment>")]
    assert order == sorted(order)


# ---------------------------------------------------------------- tables à plusieurs dimensions
def test_plusieurs_temperatures_et_tensions_unites_mixtes():
    component = document.Component(part_number="X", category="IGBT")
    add_graph(component, "Eon 25", "turn_on", "A", "mJ", [
        ("Tj = 25 °C, VCE = 300 V", [10, 100], [0.5, 5.0]),
        ("Tj = 25 °C, VCE = 600 V", [10, 100], [1.0, 10.0])])
    add_graph(component, "Eon 150", "turn_on", "A", "µJ", [
        ("Tj = 150 °C, VCE = 300 V", [10, 100], [800, 8000]),
        ("Tj = 150 °C, VCE = 600 V", [10, 100], [1600, 16000])], y_max=20000)
    component.plecs = PlecsSettings(current_axis="0 50 100", zero_voltage=False)
    tables = plecs.read_tables(plecs.build(component)[0])["TurnOnLoss"]
    assert tables["voltage"] == [300, 600] and tables["temperature"] == [25, 150]
    assert tables["method"] == "Table only" and tables["formula"] == "E"
    assert tables["scale"] == 0.001                            # unité de la 1re courbe : mJ
    assert np.allclose(tables["values"][1][1], [0, 8, 16])     # 150 °C, 600 V, en mJ


def test_prolongement_signale():
    component = reference_component()
    component.plecs.current_axis = "0 50 100 150"
    _, warnings = plecs.build(component)
    assert any("prolongée" in w for w in warnings)


def test_diode_sans_fermeture_ni_modele_thermique():
    component = document.Component(part_number="D", category="Diode")
    add_graph(component, "Err", "turn_off", "A", "mJ", [("Tj = 125 °C, VR = 600 V", CURRENT, EOFF)])
    add_graph(component, "VF", "conduction", "A", "V", [("Tj = 125 °C", *VDROP)])
    text, warnings = plecs.build(component)
    assert "TurnOnLoss" not in text
    assert warnings == ["modèle thermique vide : à compléter (lignes « R tau »)"]


# ---------------------------------------------------------------- erreurs
def test_erreurs_explicites():
    component = reference_component()
    component.category = ""
    with pytest.raises(PlecsError, match="catégorie"):
        plecs.build(component)

    component = reference_component()
    component.graphs[0].datasets[0].condition = "VDS = 600 V"
    with pytest.raises(PlecsError, match="température de jonction inconnue"):
        plecs.build(component)

    component = reference_component()
    component.graphs[0].y_axis.unit = "V"
    with pytest.raises(PlecsError, match="n'est pas une unité d'énergie"):
        plecs.build(component)

    component = reference_component()
    component.graphs[0].y_axis.unit = "bidule"
    with pytest.raises(PlecsError, match="non reconnue"):
        plecs.build(component)

    component = reference_component()      # 25 °C à 600 V seulement : 25 °C / 300 V manque
    graph = component.graphs[0]
    extra = graph.add_dataset()
    extra.condition = "Tj = 25 °C, VDS = 600 V"
    extra.set_data([(10, 0.5), (80, 2.0)], graph.calibration)
    other = graph.add_dataset()
    other.condition = "Tj = 125 °C, VDS = 300 V"
    other.set_data([(10, 0.3), (80, 1.2)], graph.calibration)
    with pytest.raises(PlecsError, match="il manque : 25 °C / 300 V"):
        plecs.build(component)

    component = reference_component()
    component.plecs.foster = "0.4 -1"
    with pytest.raises(PlecsError, match="positifs"):
        plecs.build(component)


def test_reglages_enregistres_dans_le_projet(tmp_path):
    component = reference_component()
    component.graphs[0].datasets[0].voltage = 650.0
    path = tmp_path / "p.pdig.json"
    document.save(component, path)
    loaded = document.load(path)
    assert loaded.plecs == component.plecs
    assert loaded.graphs[2].plecs_role == "conduction"
    assert loaded.graphs[0].datasets[0].voltage == 650.0
