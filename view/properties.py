# view/properties.py
"""
Arbres de paramètres du panneau de droite. Un Parameter par groupe, pour que le
contrôleur n'écoute que le groupe concerné :
    component   fiche du composant
    graph       grandeurs et unités des axes, calibration
    dataset     courbe sélectionnée
    extraction  couleur, pinceau, algorithme, grille de X
    model       modèle ajusté sur la courbe
"""
import pyqtgraph.parametertree as ptree

from model.extraction import INTERPOLATIONS, METHODS
from model.fit import PRESETS
from model.plecs import ROLES

# libellé affiché -> rôle enregistré
PLECS_ROLES = {label: key for key, label in ROLES.items()}

CATEGORIES = ["", "IGBT", "MOSFET", "JFET", "Diode", "Thyristor", "Condensateur", "Inductance",
              "Transformateur", "Dissipateur", "Autre"]


def component() -> ptree.Parameter:
    return ptree.Parameter.create(name="Composant", type="group", children=[
        {"name": "Nom", "type": "str", "value": ""},
        {"name": "Fabricant", "type": "str", "value": ""},
        {"name": "Référence", "type": "str", "value": ""},
        {"name": "Catégorie", "type": "list", "limits": CATEGORIES, "value": ""},
        {"name": "Notes", "type": "text", "value": "", "expanded": False},
        {"name": "Export PLECS", "type": "group", "expanded": False, "children": [
            {"name": "Axe de courant (A)", "type": "str", "value": "",
             "tip": "« 0 10 20 ... » ; vide : axe automatique de 0 au plus fort courant relevé"},
            {"name": "Intervalles (axe auto)", "type": "int", "value": 10, "limits": (1, 200)},
            {"name": "Point (0, 0)", "type": "bool", "value": True,
             "tip": "Énergie et chute de tension nulles à courant nul"},
            {"name": "Ligne 0 V", "type": "bool", "value": True,
             "tip": "Énergie nulle à 0 V : PLECS la fait varier avec la tension"},
            {"name": "Facteur de sécurité Csecu", "type": "bool", "value": False,
             "tip": "Formules E*Csecu et v*Csecu, variable Csecu réglée dans PLECS"},
            {"name": "Modèle thermique Foster", "type": "text", "value": "",
             "tip": "Une ligne « R tau » par élément (K/W, s), collage Excel accepté"},
            {"name": "Exporter pour PLECS", "type": "action"},
        ]},
    ])


def graph() -> ptree.Parameter:
    return ptree.Parameter.create(name="Graphique", type="group", children=[
        {"name": "Nom", "type": "str", "value": ""},
        {"name": "Grandeur X", "type": "str", "value": "", "tip": "IC, VDS, f..."},
        {"name": "Unité X", "type": "str", "value": "", "tip": "A, V, kHz... (unités de formules)"},
        {"name": "Grandeur Y", "type": "str", "value": ""},
        {"name": "Unité Y", "type": "str", "value": ""},
        {"name": "Calibration", "type": "str", "value": "non calibré", "readonly": True},
        {"name": "Rôle PLECS", "type": "list", "limits": PLECS_ROLES, "value": ""},
        {"name": "Modifier les valeurs des axes", "type": "action"},
    ])


def dataset() -> ptree.Parameter:
    return ptree.Parameter.create(name="Courbe", type="group", children=[
        {"name": "Nom", "type": "str", "value": ""},
        {"name": "Condition", "type": "str", "value": "",
         "tip": "Condition de la courbe : Tj = 125 °C, VGE = 15 V..."},
        {"name": "Tj (°C)", "type": "str", "value": "",
         "tip": "Vide : lue dans la condition (« Tj = 125 °C »)"},
        {"name": "Tension (V)", "type": "str", "value": "",
         "tip": "Tension de commutation ; vide : lue dans la condition (« VCE = 600 V »)"},
        {"name": "Couleur", "type": "color", "value": "#d62728"},
        {"name": "Points", "type": "int", "value": 0, "readonly": True},
        {"name": "Trier par X", "type": "action"},
        {"name": "Effacer les points", "type": "action"},
    ])


def extraction() -> ptree.Parameter:
    return ptree.Parameter.create(name="Extraction automatique", type="group", children=[
        {"name": "Couleur de la courbe", "type": "color", "value": "#000000"},
        {"name": "Couleur dominante du masque", "type": "action"},
        {"name": "Tolérance couleur", "type": "float", "value": 120.0, "limits": (1, 442),
         "step": 5, "tip": "Distance RGB admise (0 à 441)"},
        {"name": "Rayon du pinceau", "type": "float", "value": 8.0, "limits": (1, 200),
         "suffix": "px"},
        {"name": "Méthode", "type": "list", "limits": list(METHODS), "value": METHODS[1]},
        {"name": "Fenêtre dx", "type": "float", "value": 5.0, "limits": (1, 500), "suffix": "px"},
        {"name": "Fenêtre dy", "type": "float", "value": 5.0, "limits": (1, 500), "suffix": "px"},
        {"name": "Lissage", "type": "float", "value": 0.0, "limits": (0, 100), "suffix": "px"},
        {"name": "Grille", "type": "group", "children": [
            {"name": "X début", "type": "float", "value": 0.0},
            {"name": "X fin", "type": "float", "value": 1.0},
            {"name": "Pas", "type": "float", "value": 0.1, "limits": (0, None)},
            {"name": "Nombre de points", "type": "int", "value": 0, "limits": (0, 100000),
             "tip": "> 0 : remplace le pas (espacement log sur un axe log)"},
            {"name": "Interpolation", "type": "list", "limits": list(INTERPOLATIONS),
             "value": INTERPOLATIONS[0]},
            {"name": "Extrapoler", "type": "bool", "value": False},
        ]},
        {"name": "Tolérance du squelette", "type": "float", "value": 1.0, "limits": (0, 50),
         "suffix": "px"},
        {"name": "Extraire", "type": "action"},
    ])


def model() -> ptree.Parameter:
    return ptree.Parameter.create(name="Modèle", type="group", children=[
        {"name": "Modèle type", "type": "list", "limits": ["", *PRESETS], "value": ""},
        {"name": "Formule", "type": "str", "value": "a*x + b",
         "tip": "Fonction de x ; les autres noms sont les paramètres ajustés"},
        {"name": "Erreur relative", "type": "bool", "value": False,
         "tip": "Minimise l'écart relatif (courbes sur plusieurs décades)"},
        {"name": "Ajuster", "type": "action"},
        {"name": "Résultat", "type": "text", "value": "", "readonly": True},
        {"name": "Supprimer le modèle", "type": "action"},
    ])
