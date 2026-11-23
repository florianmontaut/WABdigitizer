"""Import de datasheets PDF vectorielles : PDF fabriqués par matplotlib (texte et tracés)."""
import numpy as np
import pytest

pytest.importorskip("pdfminer")
pytest.importorskip("pypdfium2")
matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")

from model import document, pdfimport                       # noqa: E402
from model.pdfimport import PdfImportError                   # noqa: E402

X = np.linspace(0.0, 4.0, 21)
CURVES = {"Tj = 25 °C": 80 * X ** 1.2, "Tj = 150 °C": 20 * X ** 1.2}
I = np.linspace(20.0, 600.0, 15)
LOSSES = {"Eon": 0.02 * I + 1e-4 * I ** 2, "Eoff": 0.5 + 0.03 * I}


def datasheet(path):
    """
    Page 1 : titre (référence, catégorie, fabricant). Page 2 : sortie (étiquettes dans le
    tracé) et pertes (axe log, légende par style, conditions sous la légende).
    """
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    style = {"pdf.fonttype": 42, "path.simplify": False}
    with matplotlib.rc_context(style), PdfPages(path) as pages:
        title = plt.figure(figsize=(8.27, 11.7))
        title.text(0.1, 0.9, "ESSAI120M4", fontsize=22)
        title.text(0.1, 0.86, "1200 V SiC power MOSFET", fontsize=14)
        title.text(0.1, 0.05, "www.infineon.com", fontsize=8)
        pages.savefig(title)
        plt.close(title)
        fig, (a, b) = plt.subplots(1, 2, figsize=(8.27, 4.5))
        fig.subplots_adjust(left=0.1, right=0.97, bottom=0.25, top=0.95, wspace=0.35)
        for label, y in CURVES.items():
            a.plot(X, y, "k-", lw=1.2)
            a.text(3.0, float(np.interp(3.0, X, y)) + 15, label, fontsize=8)
        a.set_xlim(0, 4)
        a.set_ylim(0, 500)
        a.grid(True)
        a.set_xlabel("VCE [V]")
        a.set_ylabel("IC [A]")
        b.semilogy(I, LOSSES["Eon"], "k-", lw=1.2, label="Eon")
        b.semilogy(I, LOSSES["Eoff"], "k--", lw=1.2, label="Eoff")
        b.set_xlim(0, 600)
        b.set_ylim(0.1, 100)
        b.grid(True, which="both")
        b.legend(loc="upper left", fontsize=8)
        b.set_xlabel("IC [A]")
        b.set_ylabel("E [mJ]")
        fig.text(0.1, 0.08, "Figure 1. Typical output characteristics", fontsize=10)
        fig.text(0.58, 0.08, "Figure 2. Switching losses", fontsize=10)
        fig.text(0.58, 0.035, "VCE = 600 V, Tj = 150 °C", fontsize=8)
        pages.savefig(fig)
        plt.close(fig)
    return path


@pytest.fixture(scope="module")
def pdf(tmp_path_factory):
    return datasheet(tmp_path_factory.mktemp("pdf") / "essai.pdf")


def test_lecture_des_graphiques(pdf):
    found = pdfimport.analyse(pdf)
    assert len(found) == 2
    out, loss = found                                    # de gauche à droite
    assert out.title.startswith("Figure 1.") and loss.title.startswith("Figure 2.")
    assert (out.x.log, out.y.log, loss.x.log, loss.y.log) == (False, False, False, True)
    assert max(out.x.residual, out.y.residual, loss.x.residual, loss.y.residual) < 0.05
    assert pdfimport.unit_split(out.x_title) == ("VCE", "V")
    assert pdfimport.unit_split(loss.y_title) == ("E", "mJ")
    # étiquettes posées près des courbes, légende rattachée par le style du trait
    assert sorted(pdfimport.plain(c.label) for c in out.curves) == sorted(CURVES)
    assert sorted(c.label for c in loss.curves) == ["Eoff", "Eon"]
    for graph, reference in ((out, CURVES), (loss, LOSSES)):
        for curve in graph.curves:
            x = graph.x.value(curve.points[:, 0])
            y = graph.y.value(curve.points[:, 1])
            ref = reference[pdfimport.plain(curve.label)]
            xs = X if graph is out else I
            assert np.allclose(x, xs, atol=1e-3 * np.ptp(xs))
            assert np.allclose(y, ref, rtol=2e-3, atol=1e-3)
    assert all(not w.startswith("axe") for g in found for w in g.warnings)


def test_composant_brouillon(pdf):
    component, warnings = pdfimport.import_pdf(pdf, dpi=150)
    # identité lue en première page
    identity = (component.part_number, component.manufacturer, component.category)
    assert identity == ("ESSAI120M4", "Infineon", "MOSFET")
    assert component.name == "essai" and "Importé de essai.pdf" in component.notes
    assert "1200 V SiC power MOSFET" in component.notes
    # Eon et Eoff d'un même graphique : deux graphiques, un rôle PLECS chacun
    out, eon, eoff = component.graphs
    assert out.name.startswith("Figure 1.") and out.source == "essai.pdf p.2"
    assert eon.name.endswith("Eon") and eoff.name.endswith("Eoff") and eon.image is eoff.image
    assert [g.plecs_role for g in component.graphs] == ["conduction", "turn_on", "turn_off"]
    assert (out.x_axis.quantity, out.x_axis.unit) == ("VCE", "V")
    assert (eon.y_axis.quantity, eon.y_axis.unit) == ("Eon", "mJ")
    assert out.calibration.orthogonal and eon.calibration.log_y
    assert out.image.ndim == 3 and out.image.dtype == np.uint8
    # pixels de l'image recadrée -> valeurs d'origine ; conditions complétées
    for dataset in out.datasets:
        data = dataset.data(out.calibration)
        assert np.allclose(data[:, 1], CURVES[dataset.name], rtol=2e-3, atol=0.5)
        assert dataset.temperature in (25.0, 150.0) and dataset.condition == dataset.name
    (on,) = eon.datasets
    assert np.allclose(on.data(eon.calibration)[:, 1], LOSSES["Eon"], rtol=2e-3)
    assert on.condition == "Eon, VCE = 600 V, Tj = 150 °C" and on.temperature == 150.0
    # export PLECS direct : conduction lue sur IC(VCE) (axes échangés), énergies à 600 V
    from model import plecs
    xml, _ = plecs.build(component)
    assert "ConductionLoss" in xml and "TurnOnLoss" in xml and "TurnOffLoss" in xml
    # le composant s'enregistre comme un projet
    data = document.Component.from_dict(component.to_dict())
    assert len(data.graphs[1].datasets) == 1 and data.graphs[0].plecs_role == "conduction"


def test_sans_graphique_ou_illisible(tmp_path):
    import matplotlib.pyplot as plt
    with matplotlib.rc_context({"pdf.fonttype": 42}):
        fig = plt.figure(figsize=(8.27, 11.7))
        fig.text(0.1, 0.9, "Datasheet : texte seulement, 12 V, 300 A")
        fig.savefig(tmp_path / "texte.pdf")
        plt.close(fig)
    assert pdfimport.analyse(tmp_path / "texte.pdf") == []
    with pytest.raises(PdfImportError, match="aucun graphique"):
        pdfimport.import_pdf(tmp_path / "texte.pdf")
    (tmp_path / "faux.pdf").write_text("pas un PDF", "utf-8")
    with pytest.raises(PdfImportError, match="illisible"):
        pdfimport.analyse(tmp_path / "faux.pdf")


def test_textes_et_nombres():
    assert pdfimport.number("−1,5") == -1.5 and pdfimport.number("1e-3") == 1e-3
    assert pdfimport.number("V") is None
    assert pdfimport.unit_split("I_D, Drain Current (A)") == ("I_D, Drain Current", "A")
    assert pdfimport.unit_split("R_DS(on) [mΩ]") == ("R_DS(on)", "mΩ")
    assert pdfimport.unit_split("T_j") == ("T_j", "")
    assert pdfimport.plain("V_GS = −5 V") == "VGS = −5 V"
    assert pdfimport.clean(chr(0xF0B0)) == "°" and pdfimport.clean("(cid:2)") == "¤"
    fit = pdfimport.fit_axis([(0.0, 1.0, "1"), (10.0, 10.0, "10"), (20.0, 100.0, "100")])
    assert fit.log and fit.residual < 1e-9 and np.isclose(fit.value(15.0), 10 ** 1.5)


def test_courbes_en_double_et_point_commun(tmp_path):
    """Tracé répété (une seule courbe) ; courbes issues d'un même coin : pas recollées."""
    import matplotlib.pyplot as plt
    with matplotlib.rc_context({"pdf.fonttype": 42, "path.simplify": False}):
        fig = plt.figure(figsize=(8.27, 6))
        a = fig.add_axes([0.15, 0.2, 0.45, 0.5])          # cadre < 35 % de la page
        v = np.linspace(-4.0, 0.0, 12)
        for k in range(3):                             # trois courbes depuis (0, 0)
            a.plot(v, (k + 1) * 10 * v, "k-", lw=1)
        a.plot(v, 10 * v, "k-", lw=1)                   # la première, dessinée deux fois
        a.plot(v[::-1][:6], 5 * v[::-1][:6], "k-", lw=1)  # finit au coin (0, 0)... à l'envers
        a.set_xlim(-4, 0)
        a.set_ylim(-120, 0)
        a.grid(True)
        a.set_xlabel("VDS [V]")
        a.set_ylabel("ID [A]")
        fig.savefig(tmp_path / "coin.pdf")
        plt.close(fig)
    (graph,) = pdfimport.analyse(tmp_path / "coin.pdf")
    assert len(graph.curves) == 4
    for curve in graph.curves:                          # aucune courbe ne revient en arrière
        assert np.all(np.diff(curve.points[:, 0]) > 0)


def raster_datasheet(path):
    """
    Page avec un graphique en image (style Excel) légendé « Figure 3. ... (ISD = f(VSD),
    Tvj = 25 °C) » et un dessin quadrillé sans graduations ni légende (écarté).
    """
    import matplotlib.pyplot as plt
    from test_plotimage import chart
    image, _ = chart()
    drawing = np.full((300, 300, 3), 255, np.uint8)
    drawing[40:260:20, 40:260] = 0
    drawing[40:260, 40:260:20] = 0
    with matplotlib.rc_context({"pdf.fonttype": 42}):
        fig = plt.figure(figsize=(8.27, 11.7))
        for box, picture in (([0.08, 0.5, 0.4, 0.4], image), ([0.55, 0.5, 0.4, 0.4], drawing)):
            ax = fig.add_axes(box)
            ax.imshow(picture, interpolation="none")
            ax.axis("off")
        fig.text(0.1, 0.47, "Figure 3. Typical body diode forward current", fontsize=9)
        fig.text(0.1, 0.4555, "(ISD = f(VSD), Tvj = 25 °C, tP = 20 µs)", fontsize=9)
        fig.savefig(path)
        plt.close(fig)
    return path


def test_graphique_en_image(tmp_path):
    pdf = raster_datasheet(tmp_path / "image.pdf")
    draft = pdfimport.prepare(pdf)
    assert len(draft.graphs) == 1                        # le dessin est écarté
    dg = draft.graphs[0]
    graph = dg.graph
    assert dg.plot is not None and dg.found.raster
    assert graph.name.startswith("Figure 3.")
    assert (graph.x_axis.quantity, graph.x_axis.unit) == ("VSD", "V")
    assert (graph.y_axis.quantity, graph.y_axis.unit) == ("ISD", "A")
    assert dg.kind == "diode" and graph.plecs_role == ""
    assert "Tvj = 25 °C" in dg.conditions
    assert graph.datasets[0].temperature == 25
    assert any("graphique en image" in w for w in dg.warnings)
    # graduations lues dans l'image : calibré dès l'import, signalé « à vérifier »
    assert graph.calibrated and dg.plot.read_values() == {"x1": 0, "x2": 6, "y1": 0, "y2": 60}
    assert any("graduations lues" in w and "à vérifier" in w for w in dg.warnings)
    calibration = graph.calibration
    bottom = dg.plot.frame[3]
    xs = calibration.pixel_to_data([(x, bottom) for x in dg.plot.x_grid])[:, 0]
    ys = calibration.pixel_to_data([(dg.plot.frame[0], y) for y in dg.plot.y_grid])[:, 1]
    assert np.allclose(xs, np.round(xs), atol=0.03)      # traits de grille : 0, 1, ... 6
    assert np.allclose(ys, np.round(ys / 10) * 10, atol=0.3)
    # courbes relevées dans l'image : droite pleine 8x + 5, droite en tirets 4x + 5
    assert [d.name for d in graph.datasets] == ["Courbe 1 (plein)", "Courbe 2 (tirets)"]
    assert all(d.temperature == 25 for d in graph.datasets)
    for dataset, slope in zip(graph.datasets, (8, 4)):
        x, y = calibration.pixel_to_data(dataset.pixels).T
        apart = x > 0.5                                  # départ commun : traits confondus
        assert np.ptp(x) > 5 and np.abs(y - (slope * x + 5))[apart].max() < 0.6
    assert any("relevée(s) automatiquement" in w for w in dg.warnings)
    component, warnings = draft.component()
    assert component.graphs == [graph] and any("graphique en image" in w for w in warnings)
    calibration = draft.calibrate(0, 1, 5, 10, 50)          # valeurs corrigées à la main
    assert graph.calibration is calibration and calibration.x2 == 5
    vector = pdfimport.DraftGraph(graph, dg.found)        # sans graduations repérées
    with pytest.raises(ValueError, match="vectoriel"):
        pdfimport.Draft(draft.path, draft.identity, [vector], []).calibrate(0, 0, 1, 0, 1)


def test_graphique_en_image_sans_lecture(tmp_path, monkeypatch):
    """Sans police pour lire les chiffres : repères posés, calibration à saisir."""
    from model import plotimage
    monkeypatch.setattr(plotimage, "font_paths", lambda: ())
    draft = pdfimport.prepare(raster_datasheet(tmp_path / "image.pdf"))
    dg = draft.graphs[0]
    assert not dg.graph.calibrated and dg.plot.x_values is None
    assert any("non lues" in w for w in dg.warnings)
    draft.calibrate(0, 0, 6, 0, 60)
    assert dg.graph.calibrated
