"""Relevé automatique des courbes d'un graphique en image."""
import numpy as np
import pytest

matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")

from model import curvetrace, plotimage                       # noqa: E402
from test_plotimage import X, chart                           # noqa: E402


def to_data(area, points, log=False):
    """Pixels -> valeurs, d'après les repères et les graduations lues."""
    (ox, oy), (x2, _), (_, y2) = area.markers()
    (a, b), (c, d) = area.x_values, area.y_values
    x = a + (points[:, 0] - ox) / (x2 - ox) * (b - a)
    if log:
        y = 10 ** (np.log10(c) + (points[:, 1] - oy) / (y2 - oy) * (np.log10(d) - np.log10(c)))
    else:
        y = c + (points[:, 1] - oy) / (y2 - oy) * (d - c)
    return x, y


def test_courbes_pleine_et_en_tirets():
    image, _ = chart()
    area = plotimage.find_plot(image)
    result = curvetrace.trace(image, area)
    assert [c.style for c in result.curves] == ["plein", "tirets"]   # de haut en bas
    for curve, slope in zip(result.curves, (8, 4)):
        x, y = to_data(area, curve.points)
        assert np.ptp(x) > 5.5                           # presque toute la largeur
        apart = x > 0.5                                  # au départ commun, traits confondus
        assert np.abs(y - (slope * x + 5))[apart].max() < 0.6   # au pixel près
        assert np.all(np.diff(x) > 0)                     # tirets reliés, dans l'ordre


def test_axe_log():
    image, _ = chart(log=True)
    area = plotimage.find_plot(image)
    (curve,) = curvetrace.trace(image, area).curves
    x, y = to_data(area, curve.points, log=True)
    assert np.abs(np.log10(y) - x / 2).max() < 0.03


def test_courbes_qui_se_croisent():
    """Deux droites en X : chacune garde sa pente après le croisement."""
    import io
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(4, 4), dpi=150)
    ax.plot(X, 10 * X, "k-", lw=2)
    ax.plot(X, 60 - 10 * X, "k-", lw=2)
    ax.set_xlim(0, 6)
    ax.set_ylim(0, 60)
    ax.grid(True, color="0.75")
    ax.tick_params(length=0)
    buffer = io.BytesIO()
    fig.savefig(buffer, format="rgba", dpi=150)
    w, h = fig.canvas.get_width_height()
    image = np.frombuffer(buffer.getvalue(), np.uint8).reshape(h, w, 4)[:, :, :3].copy()
    plt.close(fig)
    area = plotimage.find_plot(image)
    curves = curvetrace.trace(image, area).curves
    assert len(curves) == 2
    slopes = sorted(np.polyfit(*to_data(area, c.points), 1)[0] for c in curves)
    assert slopes[0] == pytest.approx(-10, abs=0.5) and slopes[1] == pytest.approx(10, abs=0.5)


def test_rien_a_relever():
    image, _ = chart()
    area = plotimage.find_plot(image)
    l, t, r, b = area.frame
    blank = image.copy()
    blank[t + 3:b - 2, l + 3:r - 2] = 255                 # zone de tracé vidée
    assert curvetrace.trace(blank, area).curves == []


def legend_chart():
    """Graphique d'énergies à légende (trait plein « Eoff », tirets « Eon »), style Excel."""
    import io
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(4, 4), dpi=150)
    ax.plot(X, 5 + 2 * X, "k-", lw=2, label="Eoff")
    ax.plot(X, 20 + 6 * X, "k--", lw=2, label="Eon")
    ax.set_xlim(0, 6)
    ax.set_ylim(0, 60)
    ax.grid(True, color="0.75")
    ax.tick_params(length=0)
    ax.legend(loc="upper left", frameon=False, fontsize=9)
    buffer = io.BytesIO()
    fig.savefig(buffer, format="rgba", dpi=150)
    w, h = fig.canvas.get_width_height()
    image = np.frombuffer(buffer.getvalue(), np.uint8).reshape(h, w, 4)[:, :, :3].copy()
    plt.close(fig)
    return image


def test_noms_par_la_legende():
    image = legend_chart()
    area = plotimage.find_plot(image)
    result = curvetrace.trace(image, area)
    assert len(result.legend) == 2                       # échantillons écartés des courbes
    curves = curvetrace.name_curves(result, image, area)
    names = {c.style: c.label for c in curves}
    assert names == {"tirets": "Eon", "plein": "Eoff"}
    assert all(c.label_source == "légende" for c in curves)


def test_lecture_des_mots():
    """Mots dessinés (police de matplotlib) : vocabulaire, nombres et unités, indices."""
    import io
    import matplotlib.pyplot as plt
    from model import labelread
    texts = ["Eoff", "td(on)", "19V", "25°C", "IDS=40A"]
    fig = plt.figure(figsize=(3, 3), dpi=150)
    for k, text in enumerate(texts):
        fig.text(0.1, 0.85 - 0.18 * k, text, fontsize=11)
    buffer = io.BytesIO()
    fig.savefig(buffer, format="rgba", dpi=150)
    w, h = fig.canvas.get_width_height()
    gray = np.frombuffer(buffer.getvalue(), np.uint8).reshape(h, w, 4)[:, :, :3].mean(axis=2)
    plt.close(fig)
    rows = np.flatnonzero((gray < 128).any(axis=1))
    bands = np.split(rows, np.flatnonzero(np.diff(rows) > 3) + 1)
    reader = labelread.Reader(gray)
    read = []
    for band in bands:
        cols = np.flatnonzero((gray[band[0]:band[-1] + 1] < 128).any(axis=0))
        word = reader.read((cols[0] - 4, band[0] - 4, cols[-1] + 5, band[-1] + 5))
        read.append(word.text if word else None)
    assert read == texts


def test_suivi_au_clic():
    """Clic sur la droite en tirets : suivie de bout en bout, trous franchis."""
    image, _ = chart()
    area = plotimage.find_plot(image)
    (ox, oy), (x2, _), (_, y2) = area.markers()

    def pixel(x, y):
        return ox + x / 6 * (x2 - ox), oy + y / 60 * (y2 - oy)
    points, color = curvetrace.follow(image, pixel(3.0, 4 * 3.0 + 5))
    assert color == (0, 0, 0)
    x, y = to_data(area, points)
    assert x.min() < 0.6 and x.max() > 5.6               # de bout en bout
    assert np.abs(y - (4 * x + 5))[x > 0.5].max() < 0.8
    # clic sur la droite pleine : elle seule
    points, _ = curvetrace.follow(image, pixel(4.0, 8 * 4.0 + 5))
    x, y = to_data(area, points)
    assert np.abs(y - (8 * x + 5))[x > 0.5].max() < 0.8
    # clic dans le vide
    assert len(curvetrace.follow(image, pixel(5.0, 5.0))[0]) == 0
