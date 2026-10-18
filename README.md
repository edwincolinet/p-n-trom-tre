# Pénétromètre — Application d'expertise arboricole

Application desktop Python dédiée au dessin
et à l'analyse de section transversale des troncs d'arbres sondés au
pénétromètre (Résistographe™ ou tout autre appareil équivalent).

## Aperçu

L'application reproduit la logique d'un classeur Excel d'expertise et
permet, pour chaque arbre d'une mission, de :

- saisir les caractéristiques (essence, rayon, port, longueur de mèche…) ;
- enregistrer des sondages au pénétromètre dans 16 directions
  (de 0 à 375 grades, par pas de 25 gr) ;
- documenter les dégradations externes visibles (arcs sur l'écorce) ;
- visualiser en temps réel la section transversale du tronc avec
  cernes de croissance, cavité d'altération et flèches de sondage ;
- obtenir un diagnostic complet avec PRBS, ratio t/R, classification
  Vert / Orange / Rouge ;
- exporter une fiche d'expertise PDF par arbre (ou un PDF global
  regroupant tous les arbres), un PNG du dessin, un tableau PRBS XLSX
  ou HTML par arbre, ou un CSV de toute la mission.

## Installation

```bash
# Prérequis : Python 3.10 ou plus récent (Python 3.13 recommandé)
pip install -r requirements.txt
```

Tkinter doit être disponible. C'est le cas par défaut sur Windows et macOS.
Sur Linux : `sudo apt install python3-tk`.

## Lancement

```bash
python3 penetrometre.py
```

Sur Windows, tu peux double-cliquer sur `Lancer_Penetrometre.bat`.

## Tests

```bash
pytest tests

# en CI (ou sans X local) pour exécuter aussi les tests Tk :
xvfb-run -a pytest tests
```

Les tests sont des `unittest.TestCase` : `python3 -m unittest discover tests`
reste fonctionnel si pytest n'est pas installé.

Un hook `pre-push` versionné (`.githooks/pre-push`) rejoue lint + tests
avant chaque `git push`. Activation (une fois par clone) :

```bash
git config core.hooksPath .githooks
```

La suite de tests unitaires couvre :

- le barème de classification Vert/Orange/Rouge ;
- la géométrie des contreforts (cloche cos², fusion de zones, wrap au
  grade 0) et les primitives polaires partagées Tk ↔ PIL ;
- le calcul PRBS, l'extrapolation pondérée, la répartition par classe
  et l'indicateur de fiabilité de l'extrapolation ;
- le résumé textuel diagnostic (`Arbre.diagnostic_summary_lines`) ;
- la migration des anciens fichiers JSON ET la robustesse aux clés
  inconnues d'un format futur, sans mutation du dict d'entrée ;
- la présence de `format_version` dans le JSON écrit ;
- l'absence du cache `alteration_par_grade` (verrouille le refactor) ;
- 4 **golden-image tests PIL** (arbre nu, écorce + sondages,
  contreforts fusionnés, dégradation traversant un contrefort) qui
  détectent toute régression du rendu PNG/PDF ;
- 4 **golden-dump tests Tk** (mêmes scénarios) qui comparent la liste
  d'items du `SectionCanvas` à des fixtures JSON. Skipped si pas
  de `DISPLAY` (CI sans Xvfb, SSH sans X11) ;
- un smoke test XLSX bout-en-bout ;
- des **property-tests** (hypothesis) sur le cœur pur : barème monotone,
  rayon d'ellipse borné, spline fermée (`tests/test_properties.py`).

Pour régénérer les fixtures après une évolution **intentionnelle** du
rendu :

```bash
# Côté PIL (PNG)
python3 -m tests.test_render --update

# Côté Tk (JSON) — DISPLAY requis, utiliser xvfb-run en CI
python3 -m tests.test_section_canvas --update
```

## Build / Distribution

Le lancement quotidien ne nécessite **aucun build** (`python3 penetrometre.py`).
Pour produire des exécutables distribuables, deux options :

**PyInstaller** (référence) — dossier autonome + installeurs natifs :

```bash
python3 build/build_icons.py     # génère les icônes
pyinstaller penetrometre.spec   # → dist/Penetrometre/
```

Les **installeurs** Windows (`.exe` Inno Setup), macOS (`.dmg` signé/notarisé)
et Linux (`.AppImage`) sont produits automatiquement par
`.github/workflows/build.yml` **au push d'un tag `vX.Y.Z`**, puis publiés en
GitHub Release. La signature de code est optionnelle (activée si les secrets
correspondants sont configurés).

**Nuitka** (option durcie) — binaire **compilé** (démarrage plus rapide, plus
difficile à décompiler qu'un bundle PyInstaller, en complément de la licence
Ed25519) :

```bash
python3 build/build_nuitka.py    # → dist-nuitka/  (nécessite un compilateur C)
```

## Fichiers à conserver ensemble

```text
mon-dossier/
├── penetrometre.py             ← App + main (orchestration Tk)
├── app_arbres.py               ← ArbreListMixin (liste d'arbres, filtres, CRUD)
├── app_recovery.py             ← RecoveryMixin (autosave anti-crash)
├── app_export_actions.py       ← ExportActionsMixin (action_export_*)
├── app_fichier.py              ← FichierMixin (cycle de vie fichier mission)
├── app_layout.py               ← LayoutMixin (construction de l'UI)
├── app_reglages.py             ← ReglagesMixin (préférences, mises à jour)
├── app_exports.py              ← actions d'export PNG/PDF/CSV/XLSX/HTML
├── app_menu.py                 ← barre de menu Tk
├── app_recent.py               ← RecentFilesStore (historique récents)
├── app_settings.py             ← SettingsStore (réglages UI persistés)
├── app_style.py                ← thème ttk (couleurs, polices, padding)
├── section_canvas.py           ← SectionCanvas (rendu Tk de la section)
├── pane_identification.py      ← onglet Identification (form + sync Ø↔R)
├── pane_sondages.py            ← onglet Sondages (grille 16 directions)
├── pane_degradations.py        ← onglet Dégradations externes
├── pane_contreforts.py         ← onglet Contreforts
├── pane_diagnostic.py          ← onglet Diagnostic (résumé + PRBS + exports)
├── comparaison.py              ← fenêtre de comparaison inter-missions
├── comparaison_render.py       ← rendu PIL de la comparaison (export PNG/PDF)
├── dialogs.py                  ← boîtes de dialogue Tk (Sondage, Dégradation,
│                                  Contrefort, Disposition de la cépée)
├── dialogs_license.py          ← fenêtre d'activation bloquante (licence)
├── dialogs_settings.py         ← dialogs préférences avancées (barème, logo)
├── dialogs_shared.py           ← helpers partagés entre dialogues
├── model.py                    ← dataclasses + mutateurs de cohérence
├── diagnostic.py               ← calculs purs (extrapolation, PRBS, t/R,
│                                  DiagnosticSnapshot, cépées)
├── persistence.py              ← I/O JSON des missions (save/load + migration)
├── bareme.py                   ← barème de classification (classer_prbs)
├── bareme_store.py             ← barème configurable (bareme.json)
├── geometry.py                 ← géométrie pure (spline, contreforts, polaire)
├── pil_render.py               ← rendu PNG de la section
├── fiche_pdf.py                ← fiche d'expertise PDF A4 vectorielle (fpdf2)
├── export.py                   ← exports XLSX/HTML
├── palette.py                  ← couleurs partagées Tk ↔ PIL
├── license.py                  ← vérification/chargement licence offline Ed25519
├── i18n.py                     ← internationalisation (gettext, catalogues)
├── update_checker.py           ← vérification mises à jour GitHub Releases
├── template_store.py           ← modèles de mission réutilisables
├── photo_gallery.py            ← galerie photos par arbre
├── undo.py                     ← pile undo/redo (50 snapshots)
├── tooltip.py                  ← infobulle Tk légère
├── aide_repliable.py           ← widget d'aide repliable
├── ui_fonts.py                 ← échelle des polices (facteur global)
├── translations/               ← catalogues i18n (fr.py, en.py, it.py)
├── exemples/
│   └── mission_demo.json       ← mission fictive (5 arbres, variété de cas)
├── docs/
│   └── guide_demarrage.html    ← guide de démarrage autonome (2 pages A4)
├── assets/
│   ├── Icone.png               ← icône bureau (.desktop) et source des icônes natives
│   ├── cropped-logo-silvavenir.png
│   └── fonts/                  ← Jost, Source Sans 3 (charte) + DejaVu embarquées
└── Lancer_Penetrometre.bat     ← double-clic Windows (optionnel)
```

Les missions sont enregistrées au format JSON.

## Fonctionnalités

### Mission multi-arbres

Une **mission** regroupe plusieurs arbres dans un seul fichier `.json`.
Liste à gauche, ajout / duplication / suppression d'arbres en un clic
(également via **clic droit** sur un arbre — menu contextuel
Renommer/Dupliquer/Supprimer).

Chaque arbre affiche **deux indicateurs distincts** dans la liste, pour
ne pas mélanger « où en est la saisie » et « quel est le risque » :

- colonne **État** = avancement de la saisie, porté par la **forme**
  (lisible même en cas de daltonisme) :
  - ○ : aucun sondage (ou rayon non renseigné)
  - ◐ : 1 ou 2 sondages (diagnostic non fiable)
  - ● : 3 sondages ou plus (diagnostic fiable)
- colonne **Risque** = classe globale **Vert / Orange / Rouge** (le mot)
  dès que le diagnostic est fiable, « — » sinon.

Le seuil fiable (● = ≥ 3 sondages) est **aligné** sur la règle de
publication du diagnostic global. La **couleur de la ligne** ne code plus
qu'une seule chose — la **classe de risque** (les arbres encore
incomplets restent en gris neutre) — pour repérer les arbres dangereux
d'un coup d'œil sans ouvrir l'onglet Diagnostic. Un footer sous la liste
compte les arbres avec diagnostic fiable (« 3/12 arbres avec diagnostic
fiable »).

Le menu **Fichier → Ouvrir récent** garde un historique des 8 dernières
missions ouvertes (persisté dans `~/.penetrometre/recent.json`).

### Identification d'un arbre

Le formulaire est groupé en 4 blocs pour clarifier les unités :

- **Arbre** : N° (doit contenir au moins un chiffre — « 1 », « 42 »,
  « 12 bis » acceptés ; « bis » seul refusé), essence, hauteur de
  l'arbre (m), port (libre / semi-libre / délaissé / architecturé /
  traumatique)
- **Tronc** : diamètre sous écorce (cm) ↔ rayon (cm) (synchro
  bidirectionnelle : Ø ÷ 2 = rayon, rayon × 2 = Ø), épaisseur
  d'écorce (cm, purement visuelle)
- **Sondage** : longueur de mèche (cm, limite la profondeur des
  flèches), hauteur du sondage (cm)
- **Notes** : commentaire libre

Tous les champs numériques **filtrent la frappe** : seuls les chiffres
et un séparateur décimal (`,` ou `.`) sont acceptés. Le format français
(`2,5`) est interprété comme `2.5`.

### Sondages

Chaque sondage est associé à une direction (16 grades disponibles).
Une seule mesure par direction (doublon interdit). La PRBS (bois sain)
et le bois altéré sont liés par le rayon (`sain + altéré = rayon`) avec
calcul automatique. La compartimentation peut être renseignée
(active / absente / non renseignée).

**Robustesse** : si le rayon est corrigé après saisie de sondages, la PRBS
(mesure physique du pénétromètre) est conservée et le bois altéré est
recalculé automatiquement (`altéré = rayon − sain`).

### Extrapolation

Pour les directions non sondées, le bois altéré est estimé par
**moyenne pondérée linéaire** entre les deux sondages voisins
(à partir de 2 sondages minimum).

### Dégradations externes

Une dégradation externe est un arc continu sur l'écorce, défini par :

- un grade de début et un grade de fin (sens horaire) ;
- une profondeur radiale en cm depuis l'écorce.

Trois modes de saisie liés automatiquement : grade de fin, largeur en
grades ou largeur en cm sur l'écorce. Les arcs ne doivent pas se
chevaucher (les arcs mitoyens bout-à-bout sont autorisés). Les
dégradations externes sont **intégrées au calcul PRBS** : elles
soustraient leur profondeur de la PRBS de la direction concernée.

### Contreforts

Un contrefort est un empattement saillant à la base du tronc, défini par
une orientation (grade central), une largeur angulaire et une longueur
radiale. Un seul contrefort par grade central (doublon interdit). Élément
purement descriptif : n'impacte pas le diagnostic.

### Diagnostic

- **PRBS ajustée** par sondage (= bois sain mesuré – dégradation externe
  qui couvre la direction)
- **Ratio t/R** = PRBS / Rayon, et classification Vert / Orange / Rouge
  selon le port
- **Répartition** sur les 16 directions du pourtour (extrapolées)
- **Classe** = barème appliqué au **t/R minimal** des 16 directions
  (la rupture part de la paroi la plus mince : aucune moyenne n'est
  calculée ni publiée)
- **Préconisation** (la décision d'expertise) : par arbre, un niveau
  d'**urgence** (Immédiate / Court terme / Moyen terme / Surveillance /
  Sans objet), une **échéance** d'intervention facultative et une
  **action recommandée** en texte libre. Reprise dans la synthèse de
  mission (colonnes triables, urgence colorée) et sur la fiche PDF.
- **Comparaison inter-missions (ré-inspection)** : *Fichier → Comparer
  l'arbre courant à une mission…* charge une campagne antérieure et ouvre
  une vue **côte à côte** — section de référence, section courante et une
  **section d'évolution** où la couronne de bois sain **perdu depuis la
  référence** est surlignée en orange (sur la géométrie réelle, 16
  directions extrapolées). Un **tableau chiffré** quantifie l'aggravation :
  **perte moyenne de bois sain par direction (cm)**, taux annualisé (cm/an,
  seulement si l'intervalle est suffisant), compartimentation perdue, t/R
  moyen, classe, direction la plus aggravée ;
  avec un **verdict** (aggravation / stable / amélioration). La comparaison
  est **exportable en PNG et en PDF** (page A4 livrable au client). La
  mission de référence est chargée le temps de la session (rien n'est écrit
  dans le fichier courant).
- **Fiabilité de l'extrapolation** : ligne « N/16 directions sondées —
  écart angulaire maximal entre voisins : X gr » affichée dans le
  diagnostic Tk et la fiche PDF. Permet de juger au coup d'œil la
  robustesse du diagnostic. Les exports XLSX/HTML ne reprennent pas ce
  bloc — il reste consultable dans l'onglet Diagnostic et sur la fiche
  PDF.
- **Diagnostic non publié si n_sondages < 3** : en-dessous de 3
  directions sondées, trop peu de mesures réelles sur le pourtour (les
  directions non sondées sont extrapolées ou supposées saines) pour
  publier un diagnostic global honnête. Le t/R minimal et la classe
  sont alors **supprimés** de la fiche PDF (et des exports
  XLSX/HTML/CSV), remplacés par un avertissement explicite ; saisir au
  moins 3 sondages dans des directions différentes pour obtenir un
  diagnostic global. Ce seuil de fiabilité est volontairement découplé
  du minimum mathématique de l'extrapolation de la cavité (2 points,
  cf. ci-dessus) : le dessin reste tracé dès 2 sondages.

### Visualisation

- Bois sain en beige doré, dégradations en brun foncé uniforme
- Cernes de croissance en trait fin noir (effacés naturellement par
  la cavité dans la zone dégradée)
- Pastilles colorées (Vert / Orange / Rouge) à l'intérieur du tronc,
  juste sous l'écorce, indiquant la classe de chaque sondage
- Lettres cardinales (N, NE, E, SE, S, SO, O, NO) à l'extérieur
- Règle graduée symétrique sous le tronc : de -R à +R, avec barres
  d'écorce aux extrémités, pas adaptatif selon la taille du dessin
- Section ronde (interpolation Catmull-Rom des points de sondage)
- **Dessin interactif** : un clic sur une pastille de sondage, un arc
  de dégradation externe ou un contrefort ouvre directement le
  dialogue d'édition de l'élément. Le curseur passe en main au
  survol. Pas besoin de retrouver la ligne dans la table d'onglet.
  Un clic sur une **direction libre** du dessin ajoute un sondage à ce
  grade (pré-rempli) ; un clic sur une direction déjà sondée l'édite.
- La checkbox **« Afficher l'emplacement des sondages »** sous le
  dessin contrôle l'affichage des pastilles (utile pour exporter un
  PNG vierge sans annotations).

### Exports

- **PDF arbre** : fiche complète A4 avec en-tête mission, logo
  Pénétromètre Silvavenir, identité de l'arbre, dessin annoté, tableau PRBS coloré,
  diagnostic avec barre de répartition Vert / Orange / Rouge.
  La colonne PRBS affiche la valeur pure (sans mention des dégradations
  externes).
- **PDF mission** : un seul fichier PDF multi-pages regroupant toutes
  les fiches arbres de la mission.
- **PNG** : dessin haute résolution 2400×2400, avec scaling automatique
  des polices et pastilles pour rester lisible une fois réduit dans
  un rapport Word.
- **XLSX** : tableau PRBS d'un arbre, **une ligne par sondage**.
  Titre mission + identité de l'arbre en toutes lettres, puis les
  colonnes N° · Direction (N/NE/…) · Grade · Rayon · PRBS bois sain ·
  Bois altéré · t/R (color-codé par classe) · Classe · Compartimentation
  ✓ / ✗ / –. Sous le tableau : une ligne **Diagnostic** (t/R minimal +
  classe, alignée sur la fiche PDF), une légende des glyphes
  puis une légende des classes. Thème Pénétromètre Silvavenir (en-têtes vert forêt), alternance de
  lignes, en-tête gelé. Nécessite
  [openpyxl](https://pypi.org/project/openpyxl/)
  (`pip install -r requirements.txt`).
- **HTML** autonome : même tableau, même thème vert, en page imprimable.
  CSS embarqué, ouvrable dans n'importe quel navigateur, aucune
  dépendance.
- **CSV** : tous les sondages de la mission, séparateur `;`,
  encodage UTF-8 avec BOM (compatible Excel). Colonnes ajustées
  uniquement (PRBS et t/R tiennent compte des dégradations externes,
  Bois altéré inclut la dégradation externe pour que
  `PRBS + Bois altéré = Rayon`).

Chaque export réussi est confirmé dans la **barre d'état** en bas de
fenêtre (sans pop-up à fermer), avec deux boutons **« Ouvrir le
fichier »** / **« Ouvrir le dossier »** pour accéder directement au
résultat. Le raccourci **Ctrl+E** exporte la fiche PDF de l'arbre
courant.

## Barème PRBS

Application du barème selon le port de l'arbre — répartition par défaut
(entièrement reconfigurable, cf. « Barème configurable » plus bas) :

| Port de l'arbre                | Vert      | Orange  | Rouge  |
| ------------------------------ | --------- | ------- | ------ |
| libre / semi-libre / délaissé  | t/R > 30% | 15–30%  | < 15%  |
| architecturé / traumatique     | t/R > 20% | 10–20%  | < 10%  |

## Format de fichier

Les missions sont enregistrées en **JSON lisible** (`.json`). L'écriture
est **atomique** (write-tmp-then-rename) : un crash pendant la sauvegarde
ne corrompt pas le fichier existant. Les fichiers des versions
précédentes sont migrés automatiquement à l'ouverture. Réciproquement,
un JSON contenant des champs inconnus (par exemple issu d'une version
plus récente de l'app) est chargé en ignorant silencieusement ces
champs au lieu de planter.

Note technique : la classe Python interne s'appelle toujours `Chantier`
pour rester compatible avec les fichiers déjà enregistrés. Seuls les
libellés affichés à l'utilisateur ont été changés en « Mission ».

### Internationalisation

Le menu **Affichage → Langue** permet de basculer entre le **français**,
l'**anglais** et l'**italien**. L'interface, les exports PDF/XLSX et les
labels de diagnostic s'adaptent. Un redémarrage est requis.

### Galerie photos

L'onglet **Identification** accueille une galerie de photos par arbre.
Les photos sont stockées dans un dossier compagnon `<mission>_photos/`
à côté du fichier `.json`. Une **page photo dédiée** peut être incluse
dans la fiche PDF.

### Modèles de mission

**Fichier → Nouveau depuis un modèle…** : enregistrez et réutilisez un
gabarit (méta-données, opérateur, barème) pour démarrer rapidement une
nouvelle mission sans ressaisir les informations récurrentes.

### Barème configurable

Le menu **Réglages → Barème…** permet de composer soi-même les **groupes
de ports** qui partagent un même seuil t/R Vert/Orange/Rouge : un seuil par
port individuel, ou plusieurs ports regroupés — au choix, sans recompiler.
Chaque port appartient toujours à un seul groupe (garanti par l'éditeur,
pas seulement vérifié) ; la répartition par défaut ci-dessus reste la
valeur d'origine et un bouton la restaure en un clic. Les groupes sont
persistés dans `~/.penetrometre/bareme.json` (poste), et les seuils
réellement appliqués à l'enregistrement sont tracés dans chaque mission et
cités dans les livrables (fiche PDF, exports XLSX/HTML/CSV) — deux
opérateurs aux réglages différents savent ainsi toujours avec quel barème
une classe Vert/Orange/Rouge a été obtenue.

### Licence et mode essai

Pénétromètre Silvavenir est un logiciel propriétaire. Un système de **licence offline**
(Ed25519, binding machine optionnel) et un **mode essai gratuit 30 jours**
sont intégrés. Pour obtenir une licence : `e.colinet@silvavenir.fr`.

## En cas de problème

Toutes les exceptions (échec d'export PDF/PNG/XLSX/HTML, problème
d'ouverture de mission, etc.) sont journalisées avec leur stack
trace complète dans :

```text
~/.penetrometre/penetrometre.log
```

(`%USERPROFILE%\.penetrometre\penetrometre.log` sous Windows.)

Le menu **Aide → Ouvrir le fichier de log** ouvre ce fichier
directement avec l'éditeur par défaut du système — c'est ce qu'il
faut joindre quand on signale un bug. Le menu **Aide → Raccourcis
clavier…** rappelle tous les raccourcis disponibles (Ctrl+N/O/S/T,
Ctrl+E pour exporter la fiche PDF de l'arbre courant, Ctrl+Z/Y,
double-clic et clic droit sur un arbre).

## Crédits

- Algorithme d'interpolation : Catmull-Rom spline fermée (Catmull & Rom, 1974)
- Convention PRBS : méthode VTA de Mattheck & Breloer (1994)
- Barème de classification : convention Pénétromètre Silvavenir
- Logo : personnalisable (Affichage → Logo et nom du cabinet)
- Polices embarquées : DejaVu (`assets/fonts/`) sous licence Bitstream
  Vera. Voir `assets/fonts/LICENSE`.
