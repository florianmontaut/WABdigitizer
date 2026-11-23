"""Graphique en image : cadre, grille, graduations (sans OCR), échelle log."""
import io

import numpy as np
import pytest

matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")

from model import plotimage                                   # noqa: E402

X = np.linspace(0.0, 6.0, 40)


def chart(log=False, dpi=150):
    """
    Graphique dans le style d'Excel (grille grise, pas de marques de graduation) rendu en
    image RGB ; rend (image, repères attendus O, X2, Y2 en pixels).
    """
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FixedLocator, ScalarFormatter
    fig, ax = plt.subplots(figsize=(4, 4), dpi=dpi)
    fig.subplots_adjust(left=0.2, right=0.92, bottom=0.18, top=0.92)
    if log:
        ax.semilogy(X, 10 ** (X / 2), "k-", lw=2)
        ax.set_ylim(1, 1000)
        ax.yaxis.set_major_locator(FixedLocator([1, 10, 100, 1000]))
        ax.yaxis.set_major_formatter(ScalarFormatter())
        ax.grid(True, which="both", color="0.8", lw=0.8)
        y_first, y_last = 1, 1000
    else:
        ax.plot(X, 8 * X + 5, "k-", lw=2)
        ax.plot(X, 4 * X + 5, "k--", lw=2)
        ax.set_ylim(0, 60)
        ax.grid(True, color="0.75", lw=0.8)
        y_first, y_last = 0, 60
    ax.set_xlim(0, 6)
    ax.tick_params(length=0, labelsize=9)
    for spine in ax.spines.values():
        spine.set_color("0.6")
    ax.set_xlabel("VSD [V]", fontweight="bold")
    ax.set_ylabel("ISD [A]", fontweight="bold")
    fig.canvas.draw()
    to_px = ax.transData.transform
    height = fig.canvas.get_width_height()[1]
    expected = [(px, height - py) for px, py in to_px([(0, y_first), (6, y_first), (0, y_last)])]
    buffer = io.BytesIO()
    fig.savefig(buffer, format="rgba", dpi=dpi)
    w, h = fig.canvas.get_width_height()
    image = np.frombuffer(buffer.getvalue(), np.uint8).reshape(h, w, 4)[:, :, :3].copy()
    plt.close(fig)
    return image, expected


@pytest.mark.parametrize("log", [False, True])
def test_reperes_des_graduations(log):
    image, expected = chart(log)
    area = plotimage.find_plot(image)
    assert area is not None
    for got, want in zip(area.markers(), expected):
        assert np.hypot(got[0] - want[0], got[1] - want[1]) <= 2.0
    assert len(area.x_labels) == 7                        # 0 à 6
    assert len(area.y_labels) == (4 if log else 7)
    assert (area.log_x, area.log_y) == (False, log)
    assert area.char > 5
    # valeurs lues (police de matplotlib, ou du système)
    assert area.x_values == (0, 6)
    assert area.y_values == ((1, 1000) if log else (0, 60))


def test_suite_des_graduations():
    positions = [0, 50, 100, 150, 200]
    seq = plotimage.tick_sequence
    assert seq(["0", "10", "20", "30", "40"], positions) == (0, 40, False)
    # graduations mal lues (signe perdu, chiffre en trop) : corrigées par les autres
    assert seq(["40", "0", "40", "80", "120"], positions) == (-40, 120, False)
    assert seq(["0", "10", "20", "30", "400"], positions) == (0, 40, False)
    assert seq(["0", "10", "?", "30", "40"], positions) == (0, 40, False)
    # graduation absente (cachée) : les positions gardent la suite
    assert seq(["0", "1", "2", "4", "5"], [0, 50, 100, 200, 250]) == (0, 5, False)
    # suite géométrique : échelle log, même si la grille ne l'a pas montré
    assert seq(["0.1", "1", "10", "100"], [0, 50, 100, 150]) == (0.1, 100, True)
    assert seq(["1E-6", "1E-5", "1E-4"], [0, 50, 100], log=True) == (1e-6, 1e-4, True)
    # incohérent ou trop peu lu : pas de valeur proposée
    assert seq(["0", "13", "7", "50"], [0, 50, 100, 150]) is None
    assert seq(["0", "?", "?", "30"], [0, 50, 100, 150]) is None
    assert seq(["5"], [0]) is None


def test_pas_un_graphique():
    blank = np.full((300, 300, 3), 255, np.uint8)
    assert plotimage.find_plot(blank) is None
    drawing = blank.copy()                                # cadre sans grille ni graduations
    drawing[50, 50:250] = drawing[250, 50:250] = 0
    drawing[50:250, 50] = drawing[50:250, 250] = 0
    drawing[120:180, 100:200] = 0
    assert plotimage.find_plot(drawing) is None
