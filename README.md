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

## Construire l'exécutable

```
build_exe.bat
```

## Où sont les données

| Lancement | Réglages, librairie, journal des erreurs |
|---|---|
| Depuis les sources | `donnees_locales\` (ignoré par git) |
| Depuis l'exécutable | `%APPDATA%\ParamDigitizer\` |
