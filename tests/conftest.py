import pathlib
import sys

from qtsocle import testing, theme

ROOT = pathlib.Path(__file__).resolve().parent.parent

# tests lancés sans écran, depuis n'importe quel dossier
testing.offscreen()
sys.path.insert(0, str(ROOT))
theme.add_icon_dir(ROOT / "ressources" / "icons")


import traceback  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def no_slot_errors():
    """
    Une exception dans un slot Qt ne fait pas échouer le test (PyQt l'envoie à
    sys.excepthook) : on la recueille et le test échoue, fermeture de la fenêtre comprise.
    """
    errors = []
    previous = sys.excepthook
    sys.excepthook = lambda *exc: errors.append("".join(traceback.format_exception(*exc)))
    yield
    testing.process_events()
    sys.excepthook = previous
    assert not errors, "exception dans un slot Qt :\n" + "\n".join(errors)
