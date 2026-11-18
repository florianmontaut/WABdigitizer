"""Comparaison de composants : lecture, regroupement par dimensions, curseur, export."""
import json

import numpy as np
import pytest

from model import compare, document, export
from model.calibration import AxisCalibration
from model.compare import CompareError, Frame


def sheet(part, category, graphs):
    """Fiche « ParamDigitizer component v1 » : graphs = [(nom, (qX, uX, logX), (qY, uY, logY), courbes)]."""
    return {"format": export.COMPONENT_FORMAT, "name": part, "part_number": part,
            "category": category,
            "graphs": [{"name": name,
                        "x": {"quantity": x[0], "unit": x[1], "log": x[2]},
                        "y": {"quantity": y[0], "unit": y[1], "log": y[2]},
                        "curves": [{"name": n, "condition": c, "x": list(xs), "y": list(ys)}
                                   for n, c, xs, ys in curves]}
                       for name, x, y, curves in graphs]}


def write(folder, name, data):
    path = folder / name
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def library(tmp_path):
    """IGBT, MOSFET (courant en kA !), diode et une énergie : un dossier de librairie."""
    write(tmp_path, "igbt.json", sheet("IGBT1", "IGBT", [
        ("VCE(IC)", ("IC", "A", False), ("VCE", "V", False),
         [("Tj 125", "Tj = 125 °C", [0, 100, 200], [0.8, 1.6, 2.4])]),
        ("Eon(IC)", ("IC", "A", False), ("Eon", "mJ", False),
         [("Eon", "Tj = 125 °C", [10, 200], [1, 20])])]))
    write(tmp_path, "mosfet.json", sheet("MOS1", "MOSFET", [
        ("VDS(ID)", ("ID", "kA", False), ("VDS", "mV", False),
         [("Tj 125", "Tj = 125 °C", [0, 0.1, 0.2], [0, 1000, 2000])])]))
    sub = tmp_path / "diodes"
    sub.mkdir()
    write(sub, "diode.json", sheet("D1", "Diode", [
        ("VF(IF)", ("IF", "A", False), ("VF", "V", False),
         [("125", "Tj = 125 °C", [0, 50, 150], [0.7, 1.2, 1.9])])]))
    write(tmp_path, "settings.json", {"dark_mode": True})            # étranger : signalé
    (tmp_path / "casse.json").write_text("{", encoding="utf-8")       # illisible : signalé
    return tmp_path


def test_lecture_de_la_librairie(library):
    files = compare.library_files(library)
    assert len(files) == 5                                            # sous-dossier compris
    curves, errors = compare.load_files(files)
    assert sorted(c.component for c in curves) == ["D1", "IGBT1", "IGBT1", "MOS1"]
    assert len(errors) == 2 and any("ni fiche ni projet" in e for e in errors)


def test_regroupement_par_dimensions_tous_types(library):
    curves, _ = compare.load_files(compare.library_files(library))
    groups = {}
    for c in curves:
        groups.setdefault(c.characteristic, []).append(c.component)
    conduction = [g for g in groups.values() if len(g) == 3]
    assert sorted(conduction[0]) == ["D1", "IGBT1", "MOS1"]           # V(A) : IGBT, MOSFET, diode
    labels = sorted(compare.characteristic_label(k) for k in groups)
    assert labels == ["tension en fonction de courant (V, A)",
                      "énergie en fonction de courant (J, A)"]


def test_conversion_des_unites_et_curseur(library):
    curves, _ = compare.load_files(compare.library_files(library))
    conduction = [c for c in curves if c.y_axis.quantity in ("VCE", "VDS", "VF")]
    conduction.sort(key=lambda c: c.component)                        # D1, IGBT1, MOS1
    frame = Frame.for_curves(conduction)
    assert (frame.x_axis.unit, frame.y_axis.unit) == ("A", "V")       # unités de la 1re
    assert frame.x_axis.quantity == "IF / IC / ID"
    x, y = frame.convert(conduction[2])                               # MOSFET : kA, mV -> A, V
    assert np.allclose(x, [0, 100, 200]) and np.allclose(y, [0, 1, 2])

    reads = compare.readings(conduction, 100, reference=1, frame=frame)
    assert [r.value for r in reads] == pytest.approx([1.55, 1.6, 1.0])
    assert reads[2].delta == pytest.approx(-0.6)
    assert reads[2].relative == pytest.approx(-0.375)                 # MOSFET 37,5 % sous l'IGBT
    assert reads[1].delta == 0
    assert np.isnan(compare.readings(conduction, 180, frame=frame)[0].value)   # hors plage diode


def test_courbes_incomparables_refusees(library):
    curves, _ = compare.load_files(compare.library_files(library))
    energy = next(c for c in curves if c.y_axis.unit == "mJ")
    voltage = next(c for c in curves if c.y_axis.unit == "V")
    with pytest.raises(CompareError, match="n'est pas comparable"):
        Frame.for_curves([voltage, energy])
    with pytest.raises(CompareError):
        Frame.for_curves([])


def test_interpolation_log_log():
    x, y = [1, 100], [1, 10000]                                       # y = x² : droite en log-log
    assert compare.value_at(x, y, 10, log_x=True, log_y=True) == pytest.approx(100)
    assert compare.value_at(x, y, 10) == pytest.approx(1 + 9 * 9999 / 99)


def test_unites_absentes_regroupees_par_nom():
    a = compare.Curve("A", "", "a", "g", "c", "", compare.Axis("Rg", "", False),
                      compare.Axis("k", "", False), np.array([0, 1.0]), np.array([1, 2.0]))
    b = compare.Curve("B", "", "b", "g", "c", "", compare.Axis("Rg", "", False),
                      compare.Axis("k", "", False), np.array([0, 1.0]), np.array([1, 3.0]))
    assert a.characteristic == b.characteristic == ("names", "Rg", "k")
    assert Frame.for_curves([a, b]).convert(b)[1].tolist() == [1, 3]


def test_projet_lu_comme_une_fiche(tmp_path):
    component = document.Component(name="Projet", category="IGBT")
    graph = component.add_graph(np.full((10, 10, 3), 255, np.uint8), "VCE(IC)")
    graph.set_calibration(AxisCalibration((0, 100), (100, 100), (0, 100), (0, 0), 0, 100, 0, 5))
    graph.x_axis, graph.y_axis = document.Axis("IC", "A"), document.Axis("VCE", "V")
    graph.datasets[0].set_data([(10, 1), (90, 3)], graph.calibration)
    path = tmp_path / "p.pdig.json"
    document.save(component, path)
    curves, errors = compare.load_files([path])
    assert errors == [] and curves[0].component == "Projet"
    assert np.allclose(curves[0].y, [1, 3])


def test_export_csv(library):
    curves, _ = compare.load_files(compare.library_files(library))
    conduction = sorted((c for c in curves if c.y_axis.quantity in ("VCE", "VF")),
                        key=lambda c: c.component)
    frame = Frame.for_curves(conduction)
    axis = compare.default_axis(conduction, frame, count=3)
    assert np.allclose(axis, [0, 100, 200])
    lines = compare.csv_text(conduction, axis, frame).splitlines()
    assert lines[0] == "IF / IC (A);VF / VCE (V) [D1 — 125 (Tj = 125 °C)];" \
                       "VF / VCE (V) [IGBT1 — Tj 125 (Tj = 125 °C)]"
    assert lines[2] == "100;1,55;1,6"
    assert lines[3] == "200;;2,4"                                     # hors plage de la diode
