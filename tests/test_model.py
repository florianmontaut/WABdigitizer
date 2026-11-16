"""Couche model : calibration, masque, extraction, ajustement, fichier, exports."""
import json

import numpy as np
import pytest
from formules import FormulaError, lut, parse, evaluate as f_evaluate

from model import document, export, extraction, fit, mask
from model.calibration import AxisCalibration, CalibrationError


# ---------------------------------------------------------------- outils
def straight_calibration(log_x=False, log_y=False):
    """Zone 100..500 px en x, 400..100 px en y (y image vers le bas)."""
    x1, x2 = (1.0, 1000.0) if log_x else (0.0, 10.0)
    y1, y2 = (0.1, 100.0) if log_y else (0.0, 30.0)
    return AxisCalibration(px_x1=(100, 400), px_x2=(500, 400),
                           px_y1=(100, 400), px_y2=(100, 100),
                           x1=x1, x2=x2, y1=y1, y2=y2, log_x=log_x, log_y=log_y)


def draw_curve(calibration, function, x_values, shape=(500, 600), color=(200, 30, 30),
               width=2):
    """Image blanche avec la courbe y = function(x) tracée en couleur."""
    image = np.full(shape + (3,), 255, dtype=np.uint8)
    xs = np.linspace(x_values[0], x_values[-1], 4000) if not calibration.log_x else \
        np.logspace(np.log10(x_values[0]), np.log10(x_values[-1]), 4000)
    pixels = calibration.data_to_pixel(np.column_stack((xs, function(xs))))
    for x, y in pixels:
        c, r = int(x), int(y)
        image[max(r - width // 2, 0):r + width // 2 + 1, max(c, 0):c + 1] = color
    return image


# ---------------------------------------------------------------- calibration
def test_calibration_lineaire_aller_retour():
    cal = straight_calibration()
    assert np.allclose(cal.pixel_to_data([(100, 400), (500, 100), (300, 250)]),
                       [(0, 0), (10, 30), (5, 15)])
    data = np.array([[1.5, 2.5], [7.0, 29.0]])
    assert np.allclose(cal.pixel_to_data(cal.data_to_pixel(data)), data)
    assert cal.skew_degrees() == pytest.approx(0.0)


def test_calibration_log_log():
    cal = straight_calibration(log_x=True, log_y=True)
    assert np.allclose(cal.pixel_to_data([(300, 250)]), [(10 ** 1.5, 10 ** 0.5)])


def test_calibration_image_tournee_et_points_hors_origine():
    angle = np.radians(3.0)
    rot = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])

    def to_px(x, y):        # 40 px par unité en x, 10 px par unité en y, tourné
        return tuple(rot @ np.array([50 + 40 * x, 450 - 10 * y]))

    # X1, X2 sur l'axe y = 2 ; Y1, Y2 sur l'axe x = 1 (pas l'origine)
    cal = AxisCalibration(px_x1=to_px(2, 2), px_x2=to_px(8, 2), px_y1=to_px(1, 5),
                          px_y2=to_px(1, 35), x1=2, x2=8, y1=5, y2=35)
    assert np.allclose(cal.pixel_to_data([to_px(4.2, 17.0)]), [(4.2, 17.0)])
    assert cal.skew_degrees() == pytest.approx(0.0, abs=1e-9)
    assert AxisCalibration.from_dict(cal.to_dict()).pixel_to_data([to_px(3, 3)]) == \
        pytest.approx(np.array([[3, 3]]))


def test_calibration_invalide():
    with pytest.raises(CalibrationError):
        AxisCalibration((0, 0), (10, 0), (0, 0), (0, -10), 1, 1, 0, 1)
    with pytest.raises(CalibrationError):
        AxisCalibration((0, 0), (10, 0), (0, 0), (0, -10), 0, 10, 1, 10, log_x=True)
    with pytest.raises(CalibrationError):      # axes parallèles
        AxisCalibration((0, 0), (10, 0), (0, 5), (10, 5), 0, 1, 0, 1)


# ---------------------------------------------------------------- masque
def test_pinceau_et_filtre_couleur():
    m = np.zeros((50, 80), dtype=bool)
    mask.paint_stroke(m, (10, 25), (70, 25), radius=3)
    assert m[25, 10:71].all() and not m[10, 40]
    mask.paint_stroke(m, (40, 25), (40, 25), radius=3, value=False)
    assert not m[25, 40]

    image = np.full((50, 80, 3), 255, np.uint8)
    image[20, :] = (0, 0, 200)
    image[30, :] = (200, 0, 0)
    selected = mask.foreground(image, None, (0, 0, 200), 60)
    assert selected[20].all() and not selected[30].any()
    assert mask.dominant_color(image, np.ones((50, 80), bool)) in [(0, 0, 200), (200, 0, 0)]


# ---------------------------------------------------------------- extraction
def test_fenetre_glissante_sur_une_droite():
    binary = np.zeros((100, 200), dtype=bool)
    for col in range(20, 180):
        row = int(80 - 0.25 * col)
        binary[row:row + 3, col] = True
    points = extraction.averaging_window(binary, dx=5, dy=5)
    assert 25 <= len(points) <= 40
    expected = 80 - 0.25 * (points[:, 0] - 0.5) + 1.5
    assert np.max(np.abs(points[:, 1] - expected)) < 1.5


def test_fenetre_glissante_separe_deux_courbes():
    binary = np.zeros((100, 200), dtype=bool)
    binary[20:22, 10:190] = True
    binary[70:72, 10:190] = True
    points = extraction.averaging_window(binary, 5, 5)
    assert set(np.round(points[:, 1]).astype(int)) == {21, 71}


def test_grille_imposee_log_log():
    """Loi en puissance sur un graphique log-log : relevée à 2 % près sur la grille."""
    cal = straight_calibration(log_x=True, log_y=True)

    def law(x):
        return 0.2 * x ** 0.8

    image = draw_curve(cal, law, [2.0, 800.0])
    binary = mask.foreground(image, None, (200, 30, 30), 80)
    settings = extraction.ExtractionSettings(method=extraction.METHODS[1], dx=3, dy=3,
                                             grid_start=5, grid_stop=500, grid_count=12)
    points = extraction.extract(binary, settings, cal)
    data = cal.pixel_to_data(points)
    assert len(data) == 12
    assert np.allclose(data[:, 0], np.logspace(np.log10(5), np.log10(500), 12))
    assert np.max(np.abs(data[:, 1] / law(data[:, 0]) - 1)) < 0.02


def test_grille_sans_extrapolation():
    cal = straight_calibration()
    image = draw_curve(cal, lambda x: 2 * x + 3, [2.0, 8.0])
    binary = mask.foreground(image, None, (200, 30, 30), 80)
    settings = extraction.ExtractionSettings(method=extraction.METHODS[1], grid_start=0,
                                             grid_stop=10, grid_step=1)
    data = cal.pixel_to_data(extraction.extract(binary, settings, cal))
    # courbe tracée de 2 à 8 : aucun point de la grille 0..10 en dehors
    assert data[0, 0] in (2, 3) and data[-1, 0] in (7, 8)
    assert np.allclose(data[:, 1], 2 * data[:, 0] + 3, atol=0.15)


def test_squelette_et_simplification():
    binary = np.zeros((60, 120), dtype=bool)
    binary[29:32, 5:115] = True
    points = extraction.extract(binary, extraction.ExtractionSettings(
        method=extraction.METHODS[2], simplify=1.0))
    assert 2 <= len(points) <= 4
    assert np.allclose(points[:, 1], 30.5, atol=1)
    line = np.column_stack((np.arange(10.0), np.r_[np.zeros(5), np.arange(1.0, 6.0) * 3]))
    assert len(extraction.simplify(line, 0.1)) == 3


def test_grille_parametres():
    assert np.allclose(extraction.make_grid(0, 1, 0.25), [0, .25, .5, .75, 1])
    with pytest.raises(ValueError):
        extraction.make_grid(0, 1, 0)
    with pytest.raises(ValueError):
        extraction.make_grid(0, 10, count=5, log=True)


# ---------------------------------------------------------------- ajustement
def test_ajustement_puissance():
    x = np.linspace(1, 100, 30)
    y = 0.3 * x ** 1.7
    result = fit.fit("a*x^b", x, y)
    assert result.parameters["a"] == pytest.approx(0.3, rel=1e-4)
    assert result.parameters["b"] == pytest.approx(1.7, rel=1e-4)
    assert result.r2 > 0.9999
    # la formule numérique se relit avec formules
    numeric = result.numeric_formula()
    assert np.allclose(f_evaluate(parse(numeric), {"x": x}), y, rtol=1e-4)


def test_ajustement_lineaire_en_parametres_et_relatif():
    x = np.linspace(0, 200, 40)
    y = 0.8 + 0.01 * x + 0.05 * x ** 0.5
    result = fit.fit("v0 + r*x + k*x^0.5", x, y, relative=True)
    assert result.parameters == pytest.approx({"k": 0.05, "r": 0.01, "v0": 0.8}, rel=1e-6)


def test_modele_invalide():
    with pytest.raises(FormulaError):
        fit.parameters_of("a + b")             # pas de x
    with pytest.raises(FormulaError):
        fit.fit("a*x", [1.0], [])


def test_substitution_ne_touche_pas_les_fonctions():
    result = fit.FitResult("a*exp(-x/e1)", {"a": 2.0, "e1": -3.0}, 0, 0, 1)
    assert result.numeric_formula() == "2*exp(-x/(-3))"


# ---------------------------------------------------------------- document et exports
def make_component():
    cal = straight_calibration()
    component = document.Component(name="IGBT test", manufacturer="ACME", category="IGBT")
    image = np.full((500, 600, 3), 255, np.uint8)
    graph = component.add_graph(image, "VCE(IC)")
    graph.set_calibration(cal)
    graph.x_axis = document.Axis("IC", "A")
    graph.y_axis = document.Axis("VCE", "V")
    first = graph.datasets[0]
    graph.mask_of(first)[10:20, 10:20] = True
    first.condition = "Tj = 25 °C"
    for x, y in [(8, 20), (2, 5), (5, 12)]:
        first.add_pixel(*cal.data_to_pixel([(x, y)])[0], calibration=cal)
    first.fit = fit.fit("a*x + b", *first.data(cal).T)
    second = graph.add_dataset()
    second.set_data([(1, 1), (9, 9)], cal)
    return component


def test_points_ranges_et_edition():
    component = make_component()
    graph = component.graphs[0]
    data = graph.datasets[0].data(graph.calibration)
    assert np.allclose(data[:, 0], [2, 5, 8])
    index = graph.datasets[0].nearest(*graph.calibration.data_to_pixel([(5, 12)])[0], radius=2)
    assert index == 1
    graph.datasets[0].remove_pixel(index)
    assert len(graph.datasets[0]) == 2


def test_projet_aller_retour(tmp_path):
    component = make_component()
    path = tmp_path / ("essai" + document.PROJECT_SUFFIX)
    document.save(component, path)
    loaded = document.load(path)
    graph, original = loaded.graphs[0], component.graphs[0]
    assert loaded.name == "IGBT test" and graph.name == "VCE(IC)"
    assert np.array_equal(graph.image, original.image)
    assert np.array_equal(graph.datasets[0].mask, original.datasets[0].mask)
    assert graph.datasets[1].mask is None
    assert graph.y_axis.unit == "V"
    assert np.allclose(graph.datasets[0].pixels, original.datasets[0].pixels)
    assert graph.datasets[0].fit.parameters == pytest.approx(original.datasets[0].fit.parameters)
    assert graph.datasets[0].condition == "Tj = 25 °C"
    with pytest.raises(ValueError):
        document.Component.from_dict({"format": "autre"})


def test_exports(tmp_path):
    component = make_component()
    graph = component.graphs[0]
    text = export.csv_text(graph)
    assert text.splitlines()[0].startswith("IC (A) [Courbe 1];VCE (V) [Courbe 1]")
    assert text.splitlines()[1] == "2;5;1;1"

    table = export.common_grid(graph, [2, 5, 9])
    assert np.allclose(table[:, 2], [2, 5, 9])
    assert np.isnan(table[2, 1])                  # 9 > 8 : hors de la courbe 1

    formula = export.lut_formula(graph, graph.datasets[0])
    assert formula.startswith("interp(x; 2; 5; 5; 12; 8; 20")
    assert f_evaluate(parse(formula), {"x": 6.5}) == pytest.approx(16)

    path = tmp_path / "fiche.json"
    export.write_component(component, path)
    sheet = json.loads(path.read_text(encoding="utf-8"))
    assert sheet["format"] == export.COMPONENT_FORMAT
    curve = sheet["graphs"][0]["curves"][0]
    assert curve["x"] == pytest.approx([2, 5, 8]) and "model" in curve
