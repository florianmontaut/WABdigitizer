import pathlib
import sys

from qtsocle import testing, theme

ROOT = pathlib.Path(__file__).resolve().parent.parent

# tests lancés sans écran, depuis n'importe quel dossier
testing.offscreen()
sys.path.insert(0, str(ROOT))
theme.add_icon_dir(ROOT / "ressources" / "icons")
