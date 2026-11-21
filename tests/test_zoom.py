"""Limites de zoom : pas de dézoom (ni de zoom) infini qui ferait planter pyqtgraph."""
import numpy as np
import pyqtgraph as pg

from helpers import dispose, make_controller
from view import zoom

from test_gui import calibrated


def width(vb, axis=0):
    lo, hi = vb.viewRange()[axis]
    return hi - lo


def test_bornes():
    assert zoom.bounds([1, np.nan, 3, -2]) == (-2, 3)
    assert zoom.bounds([0, 10, 1000], log=True) == (1, 3)     # 0 écarté, log10
    assert zoom.bounds([np.nan]) is None and zoom.bounds([-1], log=True) is None


def test_graphique_borne_puis_libre(tmp_path):
    make_controller(tmp_path).view.close()            # application Qt prête
    plot = pg.PlotItem()
    zoom.limit_plot(plot, [np.array([0.0, 10.0])], [np.array([5.0, 5.0])])
    vb = plot.getViewBox()
    vb.scaleBy((1e12, 1e12))
    assert width(vb, 0) <= 20.0 + 1e-9                # 10 + 2 x 0,5 x 10
    assert 0 < width(vb, 1) <= 1.0 + 1e-9             # courbe plate : étendue non nulle
    vb.scaleBy((1e-15, 1e-15))
    assert width(vb, 0) >= 10 * zoom.MIN_FRACTION * 0.999
    zoom.clear(vb)
    vb.setRange(xRange=(-1e6, 1e6), padding=0)
    assert width(vb, 0) > 1e5


def test_canevas_image(tmp_path):
    ctrl = make_controller(tmp_path)
    try:
        calibrated(ctrl)
        vb = ctrl.view.canvas.view_box
        vb.scaleBy((1e9, 1e9))                        # molette : dézoom
        assert width(vb, 0) <= 600 * (1 + 2 * zoom.IMAGE_MARGIN) + 1e-6
        assert width(vb, 1) <= 600 * (1 + 2 * zoom.IMAGE_MARGIN) + 1e-6
        vb.scaleBy((1e-12, 1e-12))                    # zoom au plus fort
        assert min(width(vb, 0), width(vb, 1)) >= zoom.IMAGE_MIN_PIXELS * 0.999
        # aperçu en unités physiques, axe log compris
        dataset = ctrl.dataset
        dataset.pixels = np.array([(150.0, 380.0), (450.0, 120.0)])
        ctrl.refresh_preview()
        preview = ctrl.view.preview_plot.getViewBox()
        preview.scaleBy((1e12, 1e12))
        span = np.ptp(dataset.data(ctrl.graph.calibration)[:, 0])
        assert width(preview, 0) <= 2 * span + 1e-9
    finally:
        dispose(ctrl)


def test_vues_vides_a_l_ouverture(tmp_path):
    """Application juste ouverte : aperçu, image et comparateur vides, déjà bornés."""
    ctrl = make_controller(tmp_path)
    try:
        assert ctrl.graph is None
        preview = ctrl.view.preview_plot.getViewBox()
        canvas = ctrl.view.canvas.view_box
        ctrl.open_compare()
        compare = ctrl.compare.view.plot.getViewBox()
        assert not ctrl.compare.selected_curves()
        limit = (zoom.EMPTY_RANGE[1] - zoom.EMPTY_RANGE[0]) * (1 + 2 * zoom.EMPTY_MARGIN)
        for vb in (preview, compare):
            vb.scaleBy((1e12, 1e12))
            assert width(vb, 0) <= limit + 1e-9 and width(vb, 1) <= limit + 1e-9
        canvas.scaleBy((1e12, 1e12))
        assert width(canvas, 0) <= zoom.EMPTY_IMAGE * (1 + 2 * zoom.IMAGE_MARGIN) + 1e-6
        # vue vidée après une courbe : de nouveau les bornes par défaut
        calibrated(ctrl)
        ctrl.new_component()
        preview.scaleBy((1e12, 1e12))
        assert width(preview, 0) <= limit + 1e-9
    finally:
        dispose(ctrl)
