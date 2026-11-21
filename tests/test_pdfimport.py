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
    """Une page : sortie (étiquettes dans le tracé) et pertes (axe log, légende par style)."""
    import matplotlib.pyplot as plt
    with matplotlib.rc_context({"pdf.fonttype": 42, "path.simplify": False}):
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
        fig.savefig(path)
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
    assert component.name == "essai" and len(component.graphs) == 2
    assert "Importé de essai.pdf" in component.notes
    out, loss = component.graphs
    assert out.name.startswith("Figure 1.") and out.source == "essai.pdf p.1"
    assert (out.x_axis.quantity, out.x_axis.unit) == ("VCE", "V")
    assert (loss.y_axis.quantity, loss.y_axis.unit) == ("E", "mJ")
    assert out.calibration.orthogonal and loss.calibration.log_y
    assert out.image.ndim == 3 and out.image.dtype == np.uint8
    # pixels de l'image recadrée -> valeurs d'origine
    for dataset in out.datasets:
        data = dataset.data(out.calibration)
        assert np.allclose(data[:, 1], CURVES[dataset.name], rtol=2e-3, atol=0.5)
        assert dataset.temperature in (25.0, 150.0) and dataset.condition == dataset.name
    eon = next(d for d in loss.datasets if d.name == "Eon")
    assert np.allclose(eon.data(loss.calibration)[:, 1], LOSSES["Eon"], rtol=2e-3)
    # le composant s'enregistre comme un projet
    data = document.Component.from_dict(component.to_dict())
    assert len(data.graphs[1].datasets) == 2


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
