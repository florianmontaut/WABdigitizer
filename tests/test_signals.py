"""Calculs entre signaux (model/signals.py) : désignation, base de temps, fonctions, unités."""
import numpy as np
import pytest

from model import document
from model.calibration import AxisCalibration
from model.document import Axis, Component, Dataset, Graph
from model.signals import (AUTO, PERIOD, ComputedCurve, Signal, component_signals, evaluate,
                           evaluate_all)

T_END = 1e-5                                       # 10 µs sur 1000 pixels


def calibration():
    """1000 px = 10 µs en X, 1000 px = 100 en Y (vers le haut)."""
    return AxisCalibration((0, 1000), (1000, 1000), (0, 1000), (0, 0), 0, T_END, 0, 100)


def graph(name, unit, t, y, curve=None):
    pixels = np.c_[t / T_END * 1000, 1000 - y * 10]
    g = Graph(name, calibration=calibration(), x_axis=Axis("t", "s"), y_axis=Axis(name, unit))
    g.datasets.append(Dataset(curve or name, pixels=pixels))
    return g


def component():
    """V : rampe 0 -> 100 V (1001 points) ; I : 20 A constant (101 points, plus lent)."""
    c = Component(name="essai")
    t = np.linspace(0, T_END, 1001)
    c.graphs.append(graph("Vce", "V", t, 100 * t / T_END))
    t = np.linspace(0, T_END, 101)
    c.graphs.append(graph("Ic", "A", t, np.full_like(t, 20.0)))
    return c


def run(formula, signals=None, **kw):
    return evaluate(ComputedCurve(formula=formula, **kw), signals or component_signals(component()))


def test_signaux_d_un_composant_et_designation():
    c = component()
    c.graphs.append(graph("Deux", "V", np.linspace(0, T_END, 11), np.ones(11), "a"))
    c.graphs[-1].datasets.append(Dataset("b", pixels=c.graphs[-1].datasets[0].pixels))
    c.graphs.append(Graph("brut"))                                 # sans calibration : ignoré
    s = component_signals(c)
    assert {"Vce", "Ic", "Vce:Vce", "Deux:a", "Deux:b", "a", "b"} <= set(s)
    assert "Deux" not in s and "brut" not in s
    assert s["Vce"].unit == "V" and np.allclose(s["Vce"].y[-1], 100)
    assert run("[vce]").ok                                          # sans casse
    assert run("[Deux:a] + 1", s).ok


def test_puissance_energie_et_unites():
    p = run("[Vce]*[Ic]")
    assert p.ok and p.unit == "W" and np.allclose(p.y[-1], 2000, rtol=1e-3)
    assert len(p.t) == 1001                       # base de temps du signal le plus fin
    assert any("plus lent" in w for w in p.warnings)
    e = run("integ([Vce]*[Ic]; 0; 1e-5)")
    assert e.value == pytest.approx(0.01, rel=1e-3) and e.unit == "J"
    assert run("integ([Vce]*[Ic])").unit == "J"
    d = run("deriv([Vce])")
    assert d.unit == "V/s" and np.allclose(d.y, 1e7, rtol=1e-3)
    assert run("integ([Ic])").unit == "C"                         # A·s nommé
    assert run("integ([Vce])").unit == "V·s"
    assert run("mean([Vce])").value == pytest.approx(50, rel=1e-3)
    assert run("rms([Ic]; 2e-6; 4e-6)").value == pytest.approx(20)
    assert run("pkpk([Vce])").value == pytest.approx(100, rel=1e-3)
    assert run("[Vce]*[Ic]", unit="kW").unit == "kW"             # unité saisie


def test_temps_moyenne_glissante_et_pas_propre():
    r = run("[Ic] * sin(2*pi*1e5*t)")
    assert r.ok and r.y[25] == pytest.approx(20, rel=1e-3)         # t = 2,5 µs
    m = run("movavg([Vce]; 5)")
    assert np.allclose(m.y[2:-2], run("[Vce]").y[2:-2])          # rampe : inchangée
    p = run("[Vce]", base=PERIOD, period=1e-6)
    assert len(p.t) == 11 and np.allclose(p.y, np.arange(11) * 10, atol=1e-6)
    assert not run("[Vce]", base=PERIOD, period=1e-15).ok          # trop de points


def test_signaux_non_synchrones_intervalle_commun():
    s = {"A": Signal("A", np.linspace(0, 10, 11), np.arange(11.0), "V"),
         "B": Signal("B", np.linspace(5, 20, 151), np.ones(151), "V")}
    r = evaluate(ComputedCurve(formula="[A]+[B]"), s)
    assert r.t[0] == 5 and r.t[-1] == 10                          # intervalle commun
    assert np.allclose(r.y, r.t + 1)
    s["C"] = Signal("C", np.array([30.0, 40.0]), np.zeros(2))
    assert "commun" in evaluate(ComputedCurve(formula="[A]+[C]"), s).error


def test_erreurs():
    assert "inconnu" in run("[Vge]").error and "[Vce]" in run("[Vge]").error
    assert run("").error == "formule vide"
    assert "argument" in run("deriv([Vce]; 2)").error
    assert "signal" in run("deriv(3)").error
    assert "entier" in run("movavg([Vce]; 1.5)").error
    assert run("[Vce]*(").error


def test_voies_calculees_en_chaine_et_enregistrees(tmp_path):
    c = component()
    c.computed = [ComputedCurve("P", "[Vce]*[Ic]"), ComputedCurve("E", "integ([P])"),
                  ComputedCurve("Vce", "1")]
    results = evaluate_all(c.computed, component_signals(c))
    assert results[0].unit == "W" and results[1].ok and results[1].unit == "J"
    assert np.allclose(results[1].y[-1], 0.01, rtol=1e-3)
    assert "déjà pris" in results[2].error
    path = tmp_path / "p.pdig.json"
    document.save(c, path)
    back = document.load(path).computed
    assert [(v.name, v.formula, v.base) for v in back] == [
        ("P", "[Vce]*[Ic]", AUTO), ("E", "integ([P])", AUTO), ("Vce", "1", AUTO)]
