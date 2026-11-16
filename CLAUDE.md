# ParamDigitizer — contexte pour Claude

Application de bureau Python : numérisation des courbes de fiches techniques de composants
(relevé manuel ou semi-automatique au pinceau, comme WebPlotDigitizer), ajustement de
modèles, export d'une fiche JSON. Destinée à devenir l'assistant de création de composants
(et l'outil de vérification de leurs courbes) d'un logiciel de dimensionnement de
convertisseurs de puissance.

Reprend et remplace le brouillon `..\..\WabDigitizer\brouillon` (WABDigitizerV0.py,
MaskPainter.py, extracteurs) : algorithmes conservés, repères d'image simplifiés.

## Travailler avec l'utilisateur

- Répondre en **français**. Avis francs, formulés avec douceur.
- Ne committer / pousser que sur demande explicite.
- Proposer et discuter l'approche avant un développement important.

## Environnement

- Python 3.11, PyQt6 6.4.2, pyqtgraph 0.13.3, numpy, scipy, pytest (`requirements.txt`) ;
  scikit-image facultatif (méthode « Squelette »).
- Interpréteur du poste : `..\..\env\Scripts\python.exe`.
- **qtsocle** (dépôt voisin, `pip install -e ..\qtsocle`) : thème, icônes, options,
  démarrage, chemins, exécutable. Ne pas recopier son code ici.
- **formules** (https://github.com/florianmontaut/formules) : modèles ajustés (`model/fit.py`),
  unités des axes (`formules.units`), tables `interp(x; ...)` (`model/export.py`),
  saisie des valeurs de calibration (« 10^-3 »).
- Lancer : `python main.py`. Tests : `python -m pytest tests`. Exécutable : `build_exe.bat`.

## Architecture

- `model/` (sans Qt) :
  - `calibration.py` : `AxisCalibration`, 4 points (X1, X2, Y1, Y2) comme WPD ; affine
    dans l'espace calibré (log10 sur un axe log) : accepte une image tournée.
  - `mask.py` : pinceau (disques numpy), filtre de couleur, couleur dominante.
  - `extraction.py` : fenêtre glissante (WPD), grille de X imposée (pchip / linéaire /
    spline, dans l'espace calibré), squelette + Douglas-Peucker.
  - `fit.py` : ajustement d'une formule formules de x (scipy `curve_fit`), départ par
    moindres carrés linéaires, formule numérique en sortie.
  - `document.py` : `Component` > `Graph` (image, calibration, axes, grille commune) >
    `Dataset` (points **en pixels**, condition, masque et couleur propres, modèle).
    Fichier `*.pdig.json` (« ParamDigitizer project v1 »), image et masques compressés dedans.
  - `export.py` : CSV, grille commune, `interp(...)`, fiche « ParamDigitizer component v1 ».
- `view/` : `canvas.py` (image en row-major dans une ViewBox à Y inversé : pixels de
  l'image = coordonnées de la vue ; émet pressed / moved / released en pixels),
  `main_window.py`, `properties.py` (groupes du ParameterTree), `dialogs.py`.
- `controller/main_controller.py` : modes du canevas, calibration, édition, extraction,
  modèle, fichiers, exports.
- `tests/` : `test_model.py` (calculs), `test_gui.py` (contrôleur sans écran).

## Choix de conception à respecter

- Repère unique : x = colonne, y = ligne (vers le bas), pixels de l'image. Pas de
  rot90 / flip / swapaxes (source d'erreurs du brouillon).
- Points gardés en pixels : une nouvelle calibration recalcule tout. Les valeurs
  physiques sont écrites en plus dans les fichiers, pour les lecteurs sans calibration.
- Données de l'utilisateur dans le dossier donné par `qtsocle.paths.user_data_dir`.
- Fermeture : destruction ordonnée par `qtsocle.app.run`, modèles Qt parentés à leurs
  vues, slots en méthodes liées ; `view.close_guard` est une `weakref.WeakMethod`.
- Tests d'interface : `dispose(ctrl)` en fin de test ; les boîtes de dialogue ne s'ouvrent
  pas sans écran (`finish_calibration`), les tests appellent `apply_calibration`.

## Non fait / pistes

- Annuler / refaire.
- Détection automatique des axes et de la grille (piste dans le brouillon `test_qpaint.py`).
- Loupe de pointage (WPD), courbes non fonctionnelles (hystérésis) : l'extraction trie par X.
- Intégration au logiciel de dimensionnement : par la fiche JSON (aucun import de code).
  Les paquets `model` / `view` / `controller` ont des noms génériques : à renommer
  (`paramdigitizer.model`...) si l'application doit être importée comme module.
