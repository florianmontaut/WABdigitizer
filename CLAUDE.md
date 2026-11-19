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
    Repère orthonormé (option `orthogonal_axes`, par défaut) : 3 clics O, X2, Y2,
    `to_four_points` -> X1 = Y1 = O, X2 à la hauteur de O, Y2 à son abscisse. Une
    calibration est reconnue orthonormée par sa géométrie (`orthogonal`), pas par
    l'option : ses repères (`markers()`) sont alors O, X2, Y2, déplacés sous contrainte
    (`with_markers`) ; une calibration à 4 points garde ses 4 repères.
  - `mask.py` : pinceau (disques numpy), filtre de couleur, couleur dominante.
  - `extraction.py` : fenêtre glissante (WPD), grille de X imposée (pchip / linéaire /
    spline, dans l'espace calibré), squelette + Douglas-Peucker.
  - `fit.py` : ajustement d'une formule formules de x (scipy `curve_fit`), départ par
    moindres carrés linéaires, formule numérique en sortie.
  - `document.py` : `Component` > `Graph` (image, calibration, axes, grille commune) >
    `Dataset` (points **en pixels**, condition, masque et couleur propres, modèle).
    Fichier `*.pdig.json` (« ParamDigitizer project v1 »), image et masques compressés dedans.
  - `export.py` : CSV, grille commune, `interp(...)`, fiche « ParamDigitizer component v1 ».
  - `plecs.py` : description thermique PLECS (XML « SemiconductorLibrary » 1.1). Rôle
    par graphique (`Graph.plecs_role`), Tj / tension par courbe, réglages dans
    `Component.plecs`. Référence : `tests/plecs_reference_PMF75-120.xml`, fichier fait à
    la main par l'utilisateur, que `test_plecs.py` reproduit. Les XSD de l'ancien dépôt
    (générés depuis ce seul exemple) ne sont pas fiables : non utilisés.
  - `compare.py` : comparaison entre composants de tous types. Courbes regroupées par
    dimensions physiques (X, Y) de leurs unités (`formules.units`), sinon par noms des
    grandeurs ; `Frame` : unités communes (celles de la première courbe) ; valeurs au
    curseur et écarts, table sur X communs. Lit fiches et projets via
    `export.component_dict`.
- `view/compare_window.py` + `controller/compare_controller.py` : fenêtre de comparaison
  non modale, enfant de la fenêtre principale, créée une fois (`MainController.open_compare`),
  composant ouvert lu par `weakref.WeakMethod`, réglages partagés (`options`).
- `view/` : `canvas.py` (image en row-major dans une ViewBox à Y inversé : pixels de
  l'image = coordonnées de la vue ; émet pressed / moved / released en pixels),
  `main_window.py`, `properties.py` (groupes du ParameterTree), `dialogs.py`.
- `controller/main_controller.py` : modes du canevas, calibration, édition, extraction,
  modèle, fichiers, exports.
- `controller/commands.py` : annuler / refaire (`QUndoStack` du contrôleur, mécanisme de
  GLviewer, sans son code). Commandes par instantanés avant / après, objets désignés par
  référence : `PointsCommand` (points + modèle ; flèches fusionnées par `mergeWith`),
  `CalibrationCommand`, `MaskCommand` (zone modifiée seulement), `InsertCommand`
  (courbes, graphiques). Une action déjà faite à l'écran (glisser, pinceau) est poussée
  au relâchement. Les propriétés (noms, unités, réglages) restent hors de la pile :
  `set_dirty()` ; l'étoile du titre = hors pile ou pile non propre.
- `tests/` : `test_model.py` (calculs), `test_plecs.py`, `test_compare.py`, `test_gui.py`
  (contrôleurs sans écran).

## Choix de conception à respecter

- Repère unique : x = colonne, y = ligne (vers le bas), pixels de l'image. Pas de
  rot90 / flip / swapaxes (source d'erreurs du brouillon).
- Points gardés en pixels : une nouvelle calibration recalcule tout. Les valeurs
  physiques sont écrites en plus dans les fichiers, pour les lecteurs sans calibration.
- Données de l'utilisateur dans le dossier donné par `qtsocle.paths.user_data_dir`.
- Fermeture : destruction ordonnée par `qtsocle.app.run`, modèles Qt parentés à leurs
  vues, slots en méthodes liées ; `view.close_guard` est une `weakref.WeakMethod`.
- Toute modification des points, de la calibration, du masque ou de la structure passe
  par une commande de la pile (`MainController.push`, `change_points`).
- Tests d'interface : `dispose(ctrl)` en fin de test ; les boîtes de dialogue ne s'ouvrent
  pas sans écran (`finish_calibration`), les tests appellent `apply_calibration`.

## Non fait / pistes

- Comparaison : grandeurs dérivées (pertes P = v·i, mise en parallèle de n composants).

- Export PLECS : jamais importé dans PLECS lui-même ; classes « IGBT with Diode » /
  « MOSFET with Diode », modèle de Cauer, ajustement de Foster sur une courbe Zth(t).

- Détection automatique des axes et de la grille (piste dans le brouillon `test_qpaint.py`).
- Loupe de pointage (WPD), courbes non fonctionnelles (hystérésis) : l'extraction trie par X.
- Intégration au logiciel de dimensionnement : par la fiche JSON (aucun import de code).
  Les paquets `model` / `view` / `controller` ont des noms génériques : à renommer
  (`paramdigitizer.model`...) si l'application doit être importée comme module.
