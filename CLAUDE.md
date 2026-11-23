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
  scikit-image facultatif (méthode « Squelette ») ; pdfminer.six + pypdfium2 facultatifs
  (import PDF), Pillow (rendu, lecture des graduations en image), matplotlib pour ses
  tests. pip du poste : `--use-feature=truststore`
  (sinon erreur de certificat SSL).
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
    `Component.plecs`. Conduction : i(v) (sortie) échangée en v(i), 3e quadrant en
    valeurs absolues ; catégorie JFET exportée en MOSFET (avertissement). Référence : `tests/plecs_reference_PMF75-120.xml`, fichier fait à
    la main par l'utilisateur, que `test_plecs.py` reproduit. Les XSD de l'ancien dépôt
    (générés depuis ce seul exemple) ne sont pas fiables : non utilisés.
  - `library.py` : librairie de composants (dossier, partageable) :
    `<librairie>/<Catégorie>/<Référence>` + `.json` (fiche), `.pdig.json` (projet source),
    `.xml` (PLECS). `scan` (entrées = fichiers de même nom d'un même dossier, métadonnées
    lues sans décoder les images, erreurs et références en double signalées), `target`,
    `conflicts`, `publish`, `remove` (vers `_corbeille/<date>/`, jamais de suppression).
    Repris de CoolingTool (`model/library.py`), en écriture.
  - `sheet.py` : fiche -> `Component` affichable (lecture seule d'une fiche sans projet) :
    image blanche quadrillée (900 × 600) et calibration orthonormée couvrant les données
    (log10 sur un axe log) ; points inaffichables écartés et signalés ; modèles repris.
  - `pdfimport.py` : import d'une datasheet PDF **vectorielle** (pas d'image, pas d'IA).
    `analyse` -> `FoundGraph` (coordonnées PDF, y vers le haut) : page aplatie
    (`flatten`, blocs de dessin parcourus, glyphes dessinés −/Ω remis en texte), cadres
    par composantes connexes de traits H/V (`find_frames`), texte rattaché au cadre le
    plus proche, graduations (`tick_labels`, `fit_axis` lin/log, résidu en points),
    titres d'axes, courbes (`join_fragments` : tracés répétés retirés, bouts raccordés
    seulement là où deux bouts exactement se touchent et sans demi-tour, puis tirets ;
    `drop_duplicates` : courbe couverte par une autre), étiquettes (légende
    par couleur / pointillé / épaisseur, sinon texte le plus proche), légendes de
    figures numérotées (`_match_captions` : toutes dessus ou toutes dessous).
    Les caractères en italique (matrice cisaillée) restent horizontaux ; une espace codée
    en caractère de contrôle (FF300) redevient une espace. `prepare` -> `Draft` :
    `read_identity` (première page), `_build` (image recadrée par pypdfium2 à 200 dpi,
    calibration orthonormée sur les graduations extrêmes, points en pixels), `_interpret`
    (sens par `datasheet` : axes, conditions, plages, type ; Eon / Eoff séparés en deux
    `Graph` sur la même image), `_assign_parts` (module IGBT + diode -> parties, rôles).
    `Draft.component(indices, part, identité)` : un composant par partie, notes
    (description, conditions, avertissements). `to_component` : tous les graphiques,
    sans identité.
    Graphique en image (J4) : grandes images hors des cadres vectoriels (`_image_frames`)
    -> `FoundGraph(raster=True, x=y=None)`, légendes rattachées comme les autres ;
    `_build` les écarte si `plotimage.find_plot` ne trouve rien, sinon
    `_interpret_raster` (légende, axes par `datasheet.function_axes`, `DraftGraph.plot`,
    calibré sur les valeurs lues s'il y en a, courbes relevées par `curvetrace.trace`,
    posées après la calibration pour garder l'ordre des polylignes).
    `Draft.calibrate(i, x1, x2, y1, y2, log)` : valeurs saisies -> calibration
    orthonormée sur `PlotArea.markers()`. Légendes : `_match_captions` choisit les paires
    de la moins chère à la plus chère (écart vertical + largeur non recouverte) ;
    `reading_order` : rangées puis gauche à droite.
    Corpus de mise au point (fichiers de l'utilisateur, jamais versionnés) : voir la
    mémoire du projet ; `tests/test_pdfimport.py` fabrique ses PDF avec matplotlib.
  - `datasheet.py` : sens d'une datasheet, règles explicites sur le texte (pas de LLM :
    déterministe, hors ligne, testé par `test_datasheet.py` sur des extraits de plusieurs
    fabricants). `identify` (référence, fabricant par liste connue puis nom du fichier,
    catégorie par priorité IGBT > MOSFET > JFET > Thyristor > Diode), `axis`,
    `fix_symbols` (lettre dessinée d'après le symbole d'un axe ou l'unité), `clean`,
    `parameter` / `curve_condition`, `expand_range` (plage ou liste) / `assign_range`
    (ordre du courant moyen), `classify` (`KINDS`), `energy_kind`, `diode_graph`,
    `plecs_role`. `dimension` contourne « pF » (préfixe pico inconnu de formules).
  - `curvetrace.py` : relevé automatique des courbes d'un graphique en image (numpy,
    scipy ; pas d'apprentissage). Encre plus foncée que la grille (`ink_threshold`) ;
    texte retiré (`remove_text` : caractères alignés, dont un de pleine hauteur, sinon
    des tirets) ; épaisseur (`stroke_width` : plus court passage vertical / horizontal
    par pixel) ; traits fins retirés par ouverture (disque, pas carré) ; suivi colonne par
    colonne (`_track` : prédiction par la pente, `linear_sum_assignment`, coût = distance
    au point `_point` pris dans la tache, tache partagée aux croisements, trous des tirets
    franchis), depuis le côté le plus encombré ; parties raides ligne par ligne sur
    l'encre restante, raccordées (`_join`) ; tri : traits de rappel (plus clairs, ou
    droits contre un texte et plus fins), grille, échantillons de légende
    (`LegendEntry`, gardés pour nommer) ; style par la part posée sur l'encre.
  - `plotimage.py` : graphique en image : `find_plot` -> `PlotArea` (cadre = traits de
    grille de même étendue, graduations = premières bandes d'encre sous le cadre et à sa
    gauche, découpées en étiquettes, prolongées à gauche sans le titre tourné ;
    `markers()` : O, X2, Y2 sur les graduations extrêmes, recalées sur la grille ; log si
    au moins 3 traits secondaires irréguliers entre deux graduations, traits partiels
    compris, hors courbes noires). Valeurs (`_read_ticks`, sans moteur d'OCR) : chiffres
    comparés aux modèles dessinés par Pillow avec les polices du système (`font_paths`,
    police la plus ressemblante pour tout le graphique ; « . » et « - » par leur forme),
    puis `tick_sequence` : suite linéaire (ou en log10) des positions qui explique le plus
    de graduations (70 % et 3 au moins), extrémités mal lues prises de la suite.
  - `compare.py` : comparaison entre composants de tous types. Courbes regroupées par
    dimensions physiques (X, Y) de leurs unités (`formules.units`), sinon par noms des
    grandeurs ; `Frame` : unités communes (celles de la première courbe) ; valeurs au
    curseur et écarts, table sur X communs. Lit fiches et projets via
    `export.component_dict` ; la librairie par `library.scan` (une fiche ou un projet par
    composant).
- `view/compare_window.py` + `controller/compare_controller.py` : fenêtre de comparaison
  non modale, enfant de la fenêtre principale, créée une fois (`MainController.open_compare`),
  composant ouvert lu par `weakref.WeakMethod`, réglages partagés (`options`).
- `view/pdf_import_dialog.py` : import d'une datasheet PDF : identité modifiable, partie
  (module), table cochable avec caractéristique et rôle PLECS (liste par ligne, écrit
  dans `Graph.plecs_role`), aperçu et détail ; graphique en image : graduations
  encadrées, extraits, valeurs lues en texte gris (champ vide = valeur lue, saisie =
  remplacement ; `Draft.calibrate` dès que les quatre sont connues). `choice()` -> arguments de `Draft.component`. `MainController.open_pdf` / `import_pdf` (`choose` : indices sans
  dialogue ; sans écran : graphiques de la partie `part`, la première par défaut) :
  nouveau composant sans fichier, marqué modifié, pile vidée (comme une ouverture).
  Commande grisée sans les paquets.
- `view/library_panel.py` (dock « Librairie » de la fenêtre principale, actions créées
  par `MainWindow`) + `controller/library_controller.py` (lecture, table filtrée et triée,
  sélection). Publier, ouvrir, comparer, supprimer : `MainController` (`publish`,
  `library_*`), questions par `view.ask` (sans écran : `view.answer`, `last_question`).
- `view/zoom.py` (repris de loggerFPGA `logger_app/ressources/zoom.py`) : limites de zoom
  par `ViewBox.setLimits`, sans quoi un dézoom infini fait planter pyqtgraph. Image :
  `limit_image` (étendue ≤ 4 × sa plus grande dimension, zoom jusqu'à 2 pixels), dans
  `ImageCanvas.set_image`. Courbes : `limit_plot` sur les données tracées (marge d'une
  demi-étendue, log10 sur un axe log), dans `refresh_preview` et le comparateur. Jamais
  de vue sans limite : vue vide = bornes par défaut (`limit_empty`, [0, 1] dézoomable
  11 fois ; canevas sans image comme une image de 1000 pixels), posées dès la création
  des vues (avant tout rafraîchissement).
- `view/` : `canvas.py` (image en row-major dans une ViewBox à Y inversé : pixels de
  l'image = coordonnées de la vue ; émet pressed / moved / released en pixels),
  `main_window.py`, `properties.py` (groupes du ParameterTree), `dialogs.py`.
- `controller/main_controller.py` : modes du canevas, calibration, édition, extraction,
  modèle, fichiers, exports. `split_points` : points de la courbe dans son masque ->
  nouvelle courbe (macro de la pile : points, masque effacé, insertion). `merge_curves` :
  courbes sélectionnées d'un même graphique (arborescence en sélection multiple) -> la
  première, morceaux reliés par `extraction.chain`, masques réunis (macro).
  `rebuild_tree` : met à jour sur place quand la structure est la même (pas de saut).
- `controller/commands.py` : annuler / refaire (`QUndoStack` du contrôleur, mécanisme de
  GLviewer, sans son code). Commandes par instantanés avant / après, objets désignés par
  référence : `PointsCommand` (points + modèle ; flèches fusionnées par `mergeWith`),
  `CalibrationCommand`, `MaskCommand` (zone modifiée seulement), `InsertCommand`
  (courbes, graphiques). Une action déjà faite à l'écran (glisser, pinceau) est poussée
  au relâchement. Les propriétés (noms, unités, réglages) restent hors de la pile :
  `set_dirty()` ; l'étoile du titre = hors pile ou pile non propre.
- `tests/` : `test_model.py` (calculs), `test_plecs.py`, `test_compare.py`, `test_zoom.py`,
  `test_library.py`, `test_pdfimport.py`, `test_datasheet.py`, `test_plotimage.py`,
  `test_curvetrace.py`,
  `test_gui.py`
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
- Lecture seule (`MainController.read_only`, fiche ouverte par `open_sheet`, aussi via
  `load_project` qui reconnaît le format) : `_apply_read_only` désactive les actions de
  modification, les propriétés et l'édition de la table ; chaque point d'entrée qui
  modifie appelle `_editable()`. Rien ne passe par la pile, rien ne marque le projet
  modifié (la visibilité des courbes reste libre). `current_sheet` rend None : le
  comparateur lit déjà la fiche dans la librairie.
- Librairie : le projet ouvert devient celui de la librairie à la publication s'il
  n'avait pas de fichier ou s'il en venait déjà (republier = mise à jour en place, sans
  question) ; une autre entrée de même référence n'est remplacée qu'après confirmation,
  et part à la corbeille. Les exports isolés (fiche, PLECS) ne vont plus dans la librairie.
- Tests d'interface : `dispose(ctrl)` en fin de test ; les boîtes de dialogue ne s'ouvrent
  pas sans écran (`finish_calibration`), les tests appellent `apply_calibration`.

## Non fait / pistes

- Comparaison : grandeurs dérivées (pertes P = v·i, mise en parallèle de n composants).
- Lecture seule : pas de conversion d'une fiche en projet (il faudrait l'image d'origine).
- Librairie : librairie livrée avec
  l'exécutable ; suivi des changements du dossier partagé (bouton Actualiser seulement) ;
  vidage de la corbeille (à la main). Jamais essayée sur un vrai partage réseau.

- Export PLECS : jamais importé dans PLECS lui-même ; classes « IGBT with Diode » /
  « MOSFET with Diode », modèle de Cauer, ajustement de Foster sur une courbe Zth(t).

- Import PDF (J0 à J4 faits) : graphiques en image : graduations en exposant (10^n) non
  lues ; courbes nommées par rang et style (pas encore par la légende ni les étiquettes
  « 19V ») ; courbes qui se touchent longtemps (réseau de sortie près de l'origine) ou
  presque superposées (temps de commutation) mal séparées ; outil « suivre la courbe au
  clic » à faire ; relevé ~0,2 s par graphique (à paralléliser si besoin) ; unités des
  axes devinées seulement pour V, A, °C, W. Faible sur
  les datasheets anciennes tout en noir (FF300R12KT4 : pointillés tiret par tiret,
  légendes sans numéro, Ω de la police Symbol lu « W ») ; caractères sans Unicode
  (« ¤ ») ; conduction sur un réseau de courbes selon VGS (choisir la tension de grille) ;
  plages « VGS = −5 … 18 V » sans pas (ST). formules : préfixe pico (« pF »).
- Détection automatique des axes d'une image (raster) : piste dans le brouillon
  `test_qpaint.py`.
- Loupe de pointage (WPD), courbes non fonctionnelles (hystérésis) : l'extraction trie par X.
- Intégration au logiciel de dimensionnement : par la fiche JSON (aucun import de code).
  Les paquets `model` / `view` / `controller` ont des noms génériques : à renommer
  (`paramdigitizer.model`...) si l'application doit être importée comme module.
