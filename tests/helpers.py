"""Outils communs aux tests de l'interface (sans écran)."""
from qtsocle import testing

from controller.main_controller import MainController
from view.main_window import MainWindow


def make_controller(tmp_path):
    """Contrôleur sur un dossier de données temporaire."""
    testing.get_app()
    return MainController(MainWindow(), tmp_path)


def dispose(ctrl):
    testing.dispose(ctrl.view)
