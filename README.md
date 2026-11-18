# ParamDigitizer

Numérisation des courbes de fiches techniques (datasheets) de composants : relevé manuel
ou semi-automatique (pinceau + couleur, à la manière de WebPlotDigitizer), ajustement
d'un modèle, export vers le logiciel de dimensionnement de convertisseurs.

Construit sur **qtsocle** (thème, options, démarrage, chemins, exécutable) et
**formules** (modèles ajustés, unités, tables `interp(x; ...)`).

## Lancer

```
pip install -r requirements.txt
pip install -e ..\qtsocle
python main.py
python -m pytest tests
```

## Utilisation

1. **Image** : `Ctrl+I`, `Ctrl+V` (capture d'un PDF) ou glisser-déposer. Un composant
   regroupe plusieurs graphiques (VCE(IC), Eon(IC), Coss(VDS)...).
2. **Calibrer** (`C`) : cliquer X1, X2 sur l'axe X puis Y1, Y2 sur l'axe Y, saisir leurs
   valeurs (axes log possibles). Une image légèrement de travers est acceptée.
3. **Relever** une courbe :
   - à la main (`A`) : clic = point, glisser = déplacer ; `D` : supprimer ;
   - ou automatiquement : pinceau (`B`) le long de la courbe, pipette (`P`) sur la courbe
     (ou « Couleur dominante du masque »), puis **Extraire** (`Ctrl+E`). L'œil affiche
     les pixels retenus.
4. **Condition** de la courbe (« Tj = 125 °C ») et unités des axes dans le panneau de droite.
5. **Modèle** (`Ctrl+M`) : formule de x (`a*x^b`, `v0 + r*x + k*x^b`...) ajustée sur les
   points ; courbe du modèle en pointillés sur l'image pour vérification.
6. **Enregistrer** (`*.pdig.json`, image comprise) et **exporter**.

Clavier (cliquer d'abord dans l'image) :

| Touche | Effet |
|---|---|
| Flèches | calibration : dernier repère placé, ou repère cliqué ; ajout : point sélectionné. Un pixel de l'écran par appui (Maj ×10, Ctrl ×0,1) : plus on zoome, plus le déplacement est fin |
| Suppr | supprime le point sélectionné |
| Tab / Maj+Tab | point suivant / précédent |
| Ctrl+Z / Ctrl+Y | annuler / refaire : points (ajout, déplacement, suppression, extraction, table), calibration, coups de pinceau, courbes et graphiques |

Le point sélectionné (cerclé) est le dernier placé ou cliqué, ou la ligne choisie dans la
table. En mode calibration, un clic sur un repère existant le sélectionne : il se glisse
ou s'ajuste aux flèches, la calibration est recalculée.

Méthodes d'extraction :

| Méthode | Résultat |
|---|---|
| Fenêtre glissante | un point tous les dx pixels (algorithme « Averaging Window » de WPD) |
| Grille de X imposée | points aux X de la grille du graphique, commune à toutes ses courbes ; interpolation dans l'espace log sur un axe log |
| Squelette | squelette des pixels, simplifié (Douglas-Peucker) |

## Exports

| Export | Pour |
|---|---|
| Courbes du graphique (CSV) | Excel |
| Grille de X commune (CSV) | tables 2D (PLECS...) |
| Fiche du composant (JSON, `ParamDigitizer component v1`) | logiciel de dimensionnement : valeurs physiques, unités, conditions, modèles, sans images |
| Copier la courbe en table formules | `interp(x; x1; y1; ...)` collé dans une formule |
| Composant pour PLECS (XML) | description thermique PLECS (`SemiconductorLibrary` 1.1) : pertes en conduction, à la fermeture, à l'ouverture, modèle de Foster |

### Export PLECS

- Catégorie du composant : IGBT, MOSFET, Diode ou Thyristor.
- Chaque graphique reçoit un **rôle PLECS** : conduction v(i), Eon(i) ou Eoff(i) / Err(i).
  Unités contrôlées (courant en A ou multiple, énergie en J ou multiple, tension en V).
- Chaque courbe a sa **température** et, pour les énergies, sa **tension de commutation** :
  champs Tj (°C) et Tension (V), sinon lus dans la condition (« Tj = 125 °C, VCE = 600 V »).
- Toutes les courbes sont rééchantillonnées sur un axe de courant commun (saisi, ou
  automatique) ; options : point (0, 0), ligne 0 V d'énergie nulle, facteur de sécurité
  `Csecu`, modèle thermique de Foster (lignes « R tau »).

## Comparer des composants

Outils › Comparer des composants (`Ctrl+Shift+K`), fenêtre à côté de la numérisation.

- Composants lus : fiches et projets du **répertoire de la librairie** (sous-dossiers
  compris), fichiers ajoutés à la main, et le composant ouvert.
- **Caractéristique** : les courbes sont comparables quand leurs axes ont les mêmes
  dimensions physiques, quel que soit le type de composant : VCE(IC) d'un IGBT, VDS(ID)
  d'un MOSFET et VF(IF) d'une diode sont toutes « tension en fonction de courant ». Les
  unités sont converties vers celles de la première courbe cochée (kA, mV, µJ...).
- Cocher les courbes voulues (filtre par nom, catégorie, condition).
- **Curseur** vertical (déplaçable ou saisi) : valeur de chaque courbe, écart absolu et
  relatif à une courbe de référence. Interpolation en log sur un axe log.
- Exports : CSV des courbes cochées sur des X communs, image PNG du graphique.

## Construire l'exécutable

```
build_exe.bat
```

## Où sont les données

| Lancement | Réglages, librairie, journal des erreurs |
|---|---|
| Depuis les sources | `donnees_locales\` (ignoré par git) |
| Depuis l'exécutable | `%APPDATA%\ParamDigitizer\` |
