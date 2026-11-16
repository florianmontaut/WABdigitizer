# ressources/app_settings.py
"""
Schéma des options de l'application (voir qtsocle.options_panel) : un onglet par groupe
de premier niveau, « key » est le nom de l'option dans les réglages.
"""


def schema(default_library: str) -> dict:
    return {
        "Général": {
            "type": "group",
            "children": {
                # par défaut dans le dossier de données de l'utilisateur ; à régler vers
                # un dossier partagé pour une librairie commune
                "Répertoire de la librairie": {
                    "type": "file",
                    "fileMode": "Directory",
                    "default": default_library,
                    "key": "library_dir",
                },
            },
        },
        "Numérisation": {
            "type": "group",
            "children": {
                "Rayon du pinceau (px)": {"type": "float", "default": 8.0,
                                          "limits": [1, 200], "key": "brush_radius"},
                "Tolérance couleur par défaut": {"type": "float", "default": 120.0,
                                                 "limits": [1, 442], "key": "tolerance"},
            },
        },
        "Export": {
            "type": "group",
            "children": {
                "Séparateur CSV": {"type": "list", "limits": [";", ",", "\t"],
                                   "default": ";", "key": "separator"},
                "Séparateur décimal": {"type": "list", "limits": [",", "."],
                                       "default": ",", "key": "decimal"},
            },
        },
    }
