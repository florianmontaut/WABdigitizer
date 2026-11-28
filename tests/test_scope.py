"""
Captures d'oscilloscope Tektronix : capture synthétique dans le style de l'écran (cadre
orange, grille 10 × 10 en pointillés, pastilles de zéro, repère de déclenchement, tracés
de couleur, pastilles du panneau). Le texte du panneau est donné tel que lu (la police de
l'écran n'est pas reproduite ici) : le reste de la chaîne est vérifié de bout en bout.
"""
import numpy as np
import pytest

from model import scope

X0, Y0, DX, DY = 16, 3, 100, 52          # grille : bords, division (pixels)
YELLOW, CYAN = (240, 240, 16), (16, 240, 240)
ORANGE = (255, 165, 0)


def disk(img, cx, cy, r, color):
    yy, xx = np.mgrid[:img.shape[0], :img.shape[1]]
    img[(xx - cx) ** 2 + (yy - cy) ** 2 <= r * r] = color


def capture(zero1=420, zero2=470, trigger_div=2):
    """
    Écran 1024 × 736 : CH1 (jaune, 100 V/div) créneau de 0 à 300 V entre 1 et 6 div ;
    CH2 (cyan, 5 V/div) rampe de 0 à 15 V ; t = 0 à trigger_div divisions du bord.
    """
    img = np.zeros((736, 1024, 3), np.uint8)
    img[:, :13] = (84, 104, 168)                      # bande bleue de gauche
    img[0:2, 13:1019] = (208, 112, 16)                # cadre orange
    img[524:526, 13:1019] = (208, 112, 16)
    img[0:526, 13:15] = (208, 112, 16)
    img[0:526, 1017:1019] = (208, 112, 16)
    grid = (49, 46, 40)
    for k in range(11):                               # grille : bords et pointillés
        y = Y0 + k * DY
        x = X0 + k * DX
        if k in (0, 5):
            img[y, X0:X0 + 10 * DX + 1] = grid
        else:
            img[y, X0:X0 + 10 * DX + 1:20] = grid
        img[Y0:Y0 + 10 * DY + 1:10, x] = grid
    img[Y0:Y0 + 10 * DY + 1, X0] = grid               # bords gauche et droit continus
    img[Y0:Y0 + 10 * DY + 1, X0 + 10 * DX] = grid
    # repère de déclenchement ▼
    tx = X0 + trigger_div * DX
    for r in range(8):
        img[Y0 + 1 + r, tx - 7 + r:tx + 8 - r] = ORANGE
    # pastilles de zéro (sur la bande et le cadre)
    disk(img, 7, zero1, 7, YELLOW)
    disk(img, 7, zero2, 7, CYAN)
    # tracés
    xs = np.arange(X0 + 3, X0 + 10 * DX - 2)
    divs = (xs - X0) / DX
    ch1 = np.where((divs > 1) & (divs < 6), 300.0, 0.0)
    ch2 = 15.0 * (divs / 10)
    for values, zero, scale, color in ((ch1, zero1, 100.0, YELLOW), (ch2, zero2, 5.0, CYAN)):
        ys = np.round(zero - values / scale * DY).astype(int)
        for i, (x, y) in enumerate(zip(xs, ys)):
            prev = ys[i - 1] if i else y
            a, b = sorted((prev, y))
            img[a:b + 2, x] = color
    # pastilles du panneau (C1, C2) et d'une mesure (C1 Max)
    for y, color in ((542, YELLOW), (563, CYAN), (663, YELLOW)):
        img[y:y + 10, 31:61] = color
        img[y + 3:y + 7, 40:50] = (0, 0, 0)           # texte sombre de la pastille
    return img


PANEL = [scope.PanelWord("100V/div", (66, 539, 120, 553)),
         scope.PanelWord("5.0v/div", (66, 560, 120, 574)),
         scope.PanelWord("100µs/div", (788, 539, 850, 553)),
         scope.PanelWord("Max", (68, 660, 95, 674)),
         scope.PanelWord("300.0V", (128, 660, 170, 674))]


@pytest.fixture
def panel(monkeypatch):
    monkeypatch.setattr(scope, "read_panel", lambda rgb, top, reader=None: list(PANEL))


def test_quantites_lues():
    assert scope.parse_quantity("200V/div") == (200.0, "V", "/div")
    assert scope.parse_quantity("5.0a/div") == (5.0, "A", "/div")
    value, unit, per = scope.parse_quantity("-38.0µs")
    assert value == pytest.approx(-38e-6) and (unit, per) == ("s", "")
    assert scope.parse_quantity("100MS/s")[1:] == ("S", "/s")
    assert scope.parse_quantity("Auto") is None
    assert scope._standard(1e-5) and scope._standard(4e-4) and not scope._standard(9e-6)


def test_grille_et_reperes():
    img = capture()
    screen = scope.screen_box(img)
    (g,) = scope.find_graticules(img, screen)
    assert (g.x0, g.x1) == (X0, X0 + 10 * DX)
    assert g.y0 == pytest.approx(Y0, abs=1) and g.div_y == pytest.approx(DY, abs=0.3)
    assert scope._trigger_x(img, g) == pytest.approx(X0 + 2 * DX, abs=1.5)
    zeros = scope._zero_badges(scope.channel_masks(img), g, screen)
    assert zeros["CH1"] == pytest.approx(420, abs=1) and zeros["CH2"] == pytest.approx(470, abs=1)


def test_capture_numerisee(panel):
    cap = scope.read_capture(capture())
    assert not cap.zoomed and cap.time_per_div == pytest.approx(1e-4)
    ch1, ch2 = cap.channels
    assert (ch1.name, ch1.scale, ch1.unit) == ("CH1", 100.0, "V")
    assert (ch2.name, ch2.scale, ch2.unit) == ("CH2", 5.0, "V")
    t = cap.times(ch1.pixels[:, 0])
    v = ch1.values(ch1.pixels[:, 1])
    # au zéro, les premiers pixels sont exclus (flèche de la pastille de zéro, même couleur)
    assert t.min() < -1.75e-4 and t.max() == pytest.approx(8e-4, abs=5e-6)
    high = (t > -0.9e-4) & (t < 3.9e-4)                # créneau à 300 V entre 1 et 6 div
    low = (t > 4.1e-4)
    assert np.abs(v[high] - 300).max() < 5 and np.abs(v[low]).max() < 5
    v2 = ch2.values(ch2.pixels[:, 1])
    ramp = 15.0 * (cap.times(ch2.pixels[:, 0]) + 2e-4) / 1e-3
    assert np.abs(v2 - ramp).max() < 0.25              # au pixel près
    assert cap.measurements == [("CH1", "Max", 300.0, "V")]
    assert not ch1.warnings                            # la mesure de la table se retrouve


def test_zero_cache_retrouve_par_la_mesure(panel):
    """Pastille de CH1 cachée sous celle de CH2 : zéro pris sous celle-ci, mesure à l'appui."""
    img = capture(zero1=470, zero2=470)
    img[460:481, 0:15] = 0
    scope_disk = (16, 240, 240)
    disk(img, 7, 470, 7, scope_disk)                   # seule la pastille cyan reste visible
    cap = scope.read_capture(img)
    ch1 = cap.channels[0]
    assert ch1.zero_y == pytest.approx(470, abs=1)
    assert any("zéro caché" in w for w in ch1.warnings)


def test_etiquette_et_curseur_vertical_ignores(panel):
    """Un nom de voie écrit dans la grille et un curseur vertical en pointillés (même
    couleur) ne touchent pas au tracé."""
    img = capture()
    for k in range(4):                                  # « mot » jaune : 4 lettres serrées
        img[150:162, 300 + 5 * k:302 + 5 * k] = YELLOW
        img[150:152, 300 + 5 * k:305 + 5 * k] = YELLOW
    img[Y0 + 2:Y0 + 10 * DY - 1:6, 812] = YELLOW        # curseur vertical en pointillés
    img[Y0 + 3:Y0 + 10 * DY - 1:6, 812] = YELLOW
    img[Y0 + 4:Y0 + 10 * DY - 1:6, 812] = YELLOW
    cap = scope.read_capture(img)
    ch1 = cap.channels[0]
    v = ch1.values(ch1.pixels[:, 1])
    t = cap.times(ch1.pixels[:, 0])
    assert v.max() < 305 and ch1.values(ch1.top).max() < 320   # ni l'étiquette, ni le curseur
    assert np.abs(v[(t > 4.1e-4)]).max() < 5


def test_vue_zoomee_bornes_coherentes():
    g = scope.Graticule(16, 114, 1016, 496)
    cap = scope.ScopeCapture(g, zoomed=True)
    rows = {"CH1": ([], [(1e-5, "s", ""), (-38e-6, "s", ""), (62e-6, "s", "")])}
    scope._zoom_axis(cap, rows)
    assert cap.zoom_window == pytest.approx((-38e-6, 62e-6))
    assert cap.t0_x == pytest.approx(16 + 3.8 * 100)
    # une borne mal lue (« 52.0µs ») : corrigée par la base de temps standard
    cap = scope.ScopeCapture(g, zoomed=True)
    rows = {"CH1": ([], [(1e-5, "s", ""), (-38e-6, "s", ""), (52e-6, "s", "")])}
    scope._zoom_axis(cap, rows)
    assert cap.zoom_window == pytest.approx((-38e-6, 62e-6))
    assert any("incohérents" in w for w in cap.warnings)


def test_pas_d_oscilloscope():
    with pytest.raises(ValueError):
        scope.read_capture(np.full((300, 400, 3), 255, np.uint8))
