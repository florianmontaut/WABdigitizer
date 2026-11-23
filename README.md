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
2. **Calibrer** (`C`) : cliquer l'origine **O** (croisement des axes), **X2** sur l'axe X
   et **Y2** sur l'axe Y, puis saisir les valeurs (X et Y à l'origine, X2, Y2 ; axes log
   possibles). X2 est ramené à la hauteur de O et Y2 à son abscisse : un clic
   approximatif suffit, l'aperçu suit la souris.
   Graphique tourné, ou axes qui ne se croisent pas à l'origine : décocher Options ›
   Numérisation › « Repère orthonormé » pour pointer 4 points libres X1, X2, Y1, Y2.
3. **Relever** une courbe :
   - à la main (`A`) : clic = point, glisser = déplacer ; `D` : supprimer ;
   - ou automatiquement : pinceau (`B`) le long de la courbe, pipette (`P`) sur la courbe
     (ou « Couleur dominante du masque »), puis **Extraire** (`Ctrl+E`). L'œil affiche
     les pixels retenus.
   - ou **Suivre la courbe** (`F`) : un clic sur la courbe la suit dans les deux sens
     (croisements traversés, trous des tirets et pointillés franchis, arrêt aux coudes)
     et remplace ses points ; `Maj+clic` ajoute le morceau suivi bout à bout (flanc
     vertical d'une SOA après le coude). Toute image, pas seulement les imports PDF.
   - deux courbes relevées comme une seule (allers-retours en dents de scie) : peindre au
     pinceau les points de l'une, puis **Séparer les points du masque** (`Ctrl+Shift+X`) :
     ils forment une nouvelle courbe (une seule étape d'annulation).
   - une courbe relevée en plusieurs morceaux : les sélectionner dans l'arborescence
     (`Ctrl+clic`), puis **Fusionner les courbes** (menu contextuel, `Ctrl+Shift+J`) :
     morceaux reliés bout à bout en une seule courbe (une seule étape d'annulation).
4. **Condition** de la courbe (« Tj = 125 °C ») et unités des axes dans le panneau de droite.
5. **Modèle** (`Ctrl+M`) : formule de x (`a*x^b`, `v0 + r*x + k*x^b`...) ajustée sur les
   points ; courbe du modèle en pointillés sur l'image pour vérification.
6. **Enregistrer** (`*.pdig.json`, image comprise) et **publier** dans la librairie
   (`Ctrl+Shift+P`).

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

## Importer une datasheet PDF

Fichier › **Importer une datasheet PDF...** (`Ctrl+Shift+O`, ou glisser-déposer un
`.pdf`) : les graphiques d'une datasheet **vectorielle** (la plupart des datasheets
récentes) sont lus dans les tracés et le texte du PDF, sans passer par une image, et
forment un **nouveau composant**, à vérifier puis enregistrer ou publier.

La fenêtre d'import montre :
- le **composant** : référence, fabricant et catégorie lus en première page
  (modifiables) ; pour un **module IGBT + diode**, la partie importée (IGBT ou Diode :
  deux composants, un import chacun ; référence « … (diode) ») ;
- les **graphiques** trouvés : page, nom, caractéristique reconnue (sortie, transfert,
  diode, énergies, Zth, capacités, SOA…), **rôle PLECS** proposé (modifiable), axes,
  courbes, points à vérifier ; à cocher ;
- l'**aperçu** du graphique choisi (courbes lues par-dessus l'image), ses courbes avec
  leurs conditions, ses avertissements.

Ce qui est lu :
- **Graphiques** : repérés par leur cadre et leur grille ; image = diagramme rendu
  (200 dpi) et recadré.
- **Calibration** automatique : graduations lues (exposants 10^n, virgule décimale, axes
  log), ajustement sur toutes les graduations ; repères posés sur les graduations
  extrêmes.
- **Courbes** : sommets exacts du PDF (pas de rééchantillonnage), morceaux et pointillés
  recollés (jamais à un point où partent plusieurs courbes) ; tracés en double écartés.
  Nom : étiquette posée près de la courbe (encadrée ou non), ou entrée de légende
  rapprochée par la couleur, le pointillé, l'épaisseur.
- **Axes** : grandeur (symbole : « ID » de « Drain Current : ID ») et unité (« ºC » ->
  « °C », « P.U. » -> sans unité) ; titres sur une ou deux lignes, tournés ou au-dessus
  de l'axe.
- **Conditions** de chaque courbe : son étiquette (« 8 V » + « parameter: VGS » ->
  « VGS = 8 V »), puis les conditions du graphique (légende de la figure, encadrés :
  « Tj = 25 °C », « VCE = 600 V ») ; Tj renseignée. Les lettres dessinées des
  conditions sont reconstituées (« _j = 25 °C » -> « Tj = 25 °C »).
- **Plages et listes** (« VGS = 6~18 V, 2 V step », « VGS = 12, 14, 16, 18 V », encadré
  d'une valeur par ligne) : une valeur par courbe sans étiquette, dans l'ordre du courant
  (sortie, transfert, diode), signalé « à vérifier ».
- **Énergies** : Eon et Eoff (ou Erec) d'un même graphique séparés en deux graphiques
  (même image), un rôle PLECS chacun.
- **Rôles PLECS** proposés : conduction (caractéristique de sortie ou v(i), une courbe
  par température ; diode d'un module : partie Diode), fermeture (Eon(i)), ouverture
  (Eoff(i), Erec(i) de la diode). Un réseau de courbes selon VGS à une seule température
  n'a pas de rôle (pas une table PLECS).

**Graphiques incorporés en image** (graphiques Excel collés, par exemple IMW120R045M1) :
repérés comme graphiques (grande image avec un cadre quadrillé et des graduations ; les
dessins du boîtier sont écartés), avec leur nom, leurs conditions et leur caractéristique
d'après la légende de la figure, les axes d'après « ISD = f(VSD) » (unités V, A, °C, W
seulement : à vérifier). Les **graduations sont lues** dans l'image (sans moteur d'OCR :
chiffres comparés à ceux des polices du système) et doivent former une suite régulière
(arithmétique, ou géométrique : échelle log) ; une graduation mal lue est corrigée par
les autres. Le graphique arrive **calibré** sur la première et la dernière graduation de
chaque axe, encadrées dans la fenêtre avec leur extrait : un champ vide garde la valeur
lue (en gris), une saisie la remplace. Lecture incohérente : valeurs à saisir (sinon
import sans calibration). Les **courbes sont relevées automatiquement** (sans GPU, environ
0,2 s par graphique) : suivi colonne par colonne, croisements, tirets et pointillés
reliés en une seule polyligne, parties raides (flanc d'une SOA) ; texte, traits de rappel
des étiquettes, échantillons de légende et grille écartés. **Courbes nommées** d'après
l'image : la **légende** (échantillon de trait + texte : « Eoff », « Ciss », « 25°C »,
appariés par le style du trait), les **étiquettes** à trait de rappel (le trait est suivi
jusqu'à la courbe) ; les valeurs d'un paramètre (« 19V »… « 7V », « VGS=0V ») sont
attribuées dans l'ordre du courant (sortie, transfert, diode), à vérifier. Textes lus
sans moteur d'OCR (caractères comparés aux polices du système, mots confrontés à un
vocabulaire). Le sens suit : « VGS = 19 V » (paramètre de la légende de la figure), Tj
(« 25°C »), Eon / Eoff séparés et rôles PLECS proposés. Sinon « Courbe 1 (plein) »…
À vérifier : courbes qui se touchent longtemps ou presque superposées (fusionner,
séparer, reprendre au pinceau).

Limites : PDF scanné (rien n'est lu) ; courbes de même style
sans étiquette (à nommer) ; étiquettes absentes à la source (ST : seulement les courbes
extrêmes) ; datasheets anciennes tout en noir à pointillés dessinés tiret par tiret
(FF300R12KT4) : calibration juste, courbes et étiquettes à reprendre.

PDF scanné : rien n'est trouvé, capturer les graphiques (`Ctrl+V`) ou les ajouter comme
images. Paquets facultatifs : `pdfminer.six`, `pypdfium2` (et `matplotlib` pour les
tests) ; sans eux, la commande est grisée. Depuis Python :
`component, warnings = model.pdfimport.import_pdf("datasheet.pdf")`.

## Exports

| Export | Pour |
|---|---|
| Courbes du graphique (CSV) | Excel |
| Grille de X commune (CSV) | tables 2D (PLECS...) |
| Fiche du composant (JSON, `ParamDigitizer component v1`) | logiciel de dimensionnement : valeurs physiques, unités, conditions, modèles, sans images. Fichier isolé ; pour la librairie : Publier |
| Copier la courbe en table formules | `interp(x; x1; y1; ...)` collé dans une formule |
| Composant pour PLECS (XML) | description thermique PLECS (`SemiconductorLibrary` 1.1) : pertes en conduction, à la fermeture, à l'ouverture, modèle de Foster |

### Export PLECS

- Catégorie du composant : IGBT, MOSFET, JFET (exporté comme MOSFET, signalé), Diode
  ou Thyristor.
- Chaque graphique reçoit un **rôle PLECS** : conduction v(i), Eon(i) ou Eoff(i) / Err(i).
  La conduction accepte une caractéristique de sortie i(v) (axes échangés à l'export)
  et le 3e quadrant (valeurs absolues).
  Unités contrôlées (courant en A ou multiple, énergie en J ou multiple, tension en V).
- Chaque courbe a sa **température** et, pour les énergies, sa **tension de commutation** :
  champs Tj (°C) et Tension (V), sinon lus dans la condition (« Tj = 125 °C, VCE = 600 V »).
- Toutes les courbes sont rééchantillonnées sur un axe de courant commun (saisi, ou
  automatique) ; options : point (0, 0), ligne 0 V d'énergie nulle, facteur de sécurité
  `Csecu`, modèle thermique de Foster (lignes « R tau »).

## Librairie de composants

Panneau « Librairie » sous la fenêtre (`Ctrl+L` pour l'afficher ou le masquer), menu
Librairie. Le dossier est l'option Général › « Répertoire de la librairie » (un partage
réseau pour une librairie commune).

```
<librairie>/<Catégorie>/<Référence>.json         fiche (lue par le logiciel de dimensionnement)
<librairie>/<Catégorie>/<Référence>.pdig.json    projet source : image, calibration, masques
<librairie>/<Catégorie>/<Référence>.xml          description PLECS (si un graphique a un rôle PLECS)
<librairie>/_corbeille/<date>/...                composants supprimés ou remplacés
```

- **Publier** (`Ctrl+Shift+P`) : écrit les trois fichiers du composant ouvert. Il faut
  une référence (ou un nom) ; sans catégorie : « Sans catégorie ». Une autre entrée de
  même référence est remplacée après confirmation, ses fichiers vont à la corbeille.
  Un projet sans fichier, ou ouvert depuis la librairie, devient celui de la librairie :
  republier après une correction met l'entrée à jour sans question, et un changement
  de catégorie la déplace.
- **Ouvrir** (double-clic) : le projet source, pour vérifier ou corriger les relevés.
  Une fiche seule (sans projet, en gris) s'ouvre en **lecture seule** : pas d'image
  d'origine, ses courbes et modèles sont redessinés sur un fond quadrillé ; table,
  aperçu, exports CSV et comparaison disponibles, rien n'est modifiable (titre
  « [lecture seule] »). Une fiche s'ouvre aussi par Ouvrir un projet ou glisser-déposer.
- **Comparer** : le comparateur s'ouvre, les courbes des composants choisis cochées
  (Ctrl+clic ou Maj+clic pour en choisir plusieurs ; caractéristique la plus partagée).
- **Mettre à la corbeille**, **Afficher dans l'explorateur**, **Actualiser**.
- Filtre sur toutes les colonnes ; colonnes triables. Les fichiers rangés à la main
  (à plat, autres sous-dossiers) sont lus aussi ; un fichier illisible ou une référence
  en double est signalé sous la table (détail en infobulle).

## Comparer des composants

Outils › Comparer des composants (`Ctrl+Shift+K`), fenêtre à côté de la numérisation.

- Composants lus : ceux de la **librairie** (fiche, sinon projet : un composant publié
  n'est lu qu'une fois), fichiers ajoutés à la main, et le composant ouvert.
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
