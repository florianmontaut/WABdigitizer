"""Décimer / lisser une partie des points d'une courbe (model/pointops.py)."""
import numpy as np

from model import pointops


def line(n=21):
    x = np.arange(n, dtype=float)
    return np.c_[x, 2 * x]


def test_morceaux_contigus():
    assert pointops.runs([5, 1, 2, 3, 7, 6]) == [(1, 3), (5, 7)]
    assert pointops.runs([]) == []


def test_decimer_un_sur_n_garde_les_bouts_et_le_reste():
    pixels = line()
    keep = pointops.decimate(pixels, range(5, 16), "every", 3)
    assert keep[:5].all() and keep[16:].all()                 # hors sélection : intact
    assert np.flatnonzero(~keep).tolist() == [6, 7, 9, 10, 12, 13]
    assert keep[15]                                           # bout du morceau gardé


def test_decimer_par_tolerance_et_espacement():
    pixels = line()
    pixels[10, 1] += 5                                        # coude : gardé
    keep = pointops.decimate(pixels, range(21), "tolerance", 1.0)
    assert np.flatnonzero(keep).tolist() == [0, 9, 10, 11, 20]
    keep = pointops.decimate(line(), range(21), "spacing", 4.0)   # pas de √5 ≈ 2,24 px
    kept = line()[keep]
    assert keep[0] and keep[-1]
    assert np.all(np.hypot(*np.diff(kept, axis=0).T) >= 4.0)


def test_lisser_seulement_la_selection():
    rng = np.random.default_rng(1)
    x = np.arange(50.0)
    scaled = np.c_[x, 3 * x + rng.normal(0, 1, 50)]
    out = pointops.smooth(scaled, range(10, 40), "savgol", 11, 1)
    assert np.array_equal(out[:10], scaled[:10]) and np.array_equal(out[40:], scaled[40:])
    assert np.array_equal(out[:, 0], scaled[:, 0])            # X inchangés
    assert np.abs(out[10:40, 1] - 3 * x[10:40]).std() < np.abs(scaled[10:40, 1] - 3 * x[10:40]).std()
    spike = np.c_[x, np.zeros(50)]
    spike[25, 1] = 100
    assert np.allclose(pointops.smooth(spike, range(20, 30), "median", 5)[:, 1], 0)
    mean = pointops.smooth(np.c_[x, x], range(50), "mean", 4)    # fenêtre paire -> 5
    assert np.allclose(mean[2:-2, 1], x[2:-2])
