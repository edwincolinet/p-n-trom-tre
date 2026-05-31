# Pénétromètre — Application d'expertise arboricole

Application desktop Python pour le cabinet **Silvavenir**, dédiée au dessin
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
# Prérequis : Python 3.9 ou plus récent (Python 3.12 recommandé)
pip install -r requirements.txt
```

Tkinter doit être disponible. C'est le cas par défaut sur Windows et macOS.
Sur Linux : `sudo apt install python3-tk`.

## Lancement

```bash
python penetrometre.py
```

Sur Windows, tu peux double-cliquer sur `Lancer_Penetrometre.bat`.

## Tests

```bash
python -m unittest discover tests

# en CI (ou sans X local) pour exécuter aussi les tests Tk :
xvfb-run -a python -m unittest discover tests
```

174 tests unitaires couvrent :

- le barème Silvavenir et la classification Vert/Orange/Rouge ;
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
- un smoke test XLSX bout-en-bout.

Pour régénérer les fixtures après une évolution **intentionnelle** du
rendu :

```bash
# Côté PIL (PNG)
python -m tests.test_render --update

# Côté Tk (JSON) — DISPLAY requis, utiliser xvfb-run en CI
python -m tests.test_section_canvas --update
```

## Fichiers à conserver ensemble

```text
mon-dossier/
├── penetrometre.py             ← App + main (orchestration Tk)
├── section_canvas.py           ← SectionCanvas (rendu Tk de la section)
├── pane_identification.py      ← onglet Identification (form + sync Ø↔R)
├── pane_sondages.py            ← onglet Sondages (table + add/edit/del)
├── pane_degradations.py        ← onglet Dégradations externes
├── pane_contreforts.py         ← onglet Contreforts
├── pane_diagnostic.py          ← onglet Diagnostic (résumé + PRBS + exports)
├── app_exports.py              ← actions d'export PNG/PDF/CSV/XLSX/HTML
├── app_menu.py                 ← barre de menu Tk (Fichier/Arbres/?)
├── app_style.py                ← thème ttk (couleurs, polices, padding)
├── dialogs.py                  ← boîtes de dialogue Tk (Sondage,
│                                  Dégradation externe, Contrefort)
├── model.py                    ← dataclasses + mutateurs de cohérence
├── diagnostic.py               ← calculs purs (extrapolation, PRBS, t/R,
│                                  DiagnosticSnapshot, résumé textuel)
├── persistence.py              ← I/O JSON des missions (save/load + migration)
├── bareme.py                   ← barème Silvavenir (classer_prbs)
├── geometry.py                 ← géométrie pure (spline, contreforts, polaire)
├── pil_render.py               ← rendu PNG de la section
├── fiche_pdf.py                ← layout de la fiche d'expertise PDF A4
├── export.py                   ← exports XLSX/HTML
├── palette.py                  ← couleurs partagées Tk ↔ PIL
├── assets/
│   ├── silvavenir_logo.jpg     ← logo (header app + fiche PDF)
│   ├── Icone.jpeg              ← icône bureau (.desktop)
│   └── fonts/                  ← DejaVu embarquée (rendu reproductible)
└── Lancer_Penetrometre.bat     ← double-clic Windows (optionnel)
```

Les missions sont enregistrées au format JSON.

## Fonctionnalités

### Mission multi-arbres

Une **mission** regroupe plusieurs arbres dans un seul fichier `.json`.
Liste à gauche, ajout / duplication / suppression d'arbres en un clic
(également via **clic droit** sur un arbre — menu contextuel
Renommer/Dupliquer/Supprimer).

Chaque arbre affiche un **indicateur d'état visuel** dans la liste :

- ● rouge bordeaux : aucun sondage (ou rayon non renseigné)
- ● orange ambre : 1 ou 2 sondages (instrumentation minimale)
- ● vert foncé : 3 sondages ou plus (instrumentation solide)

Toute la ligne est teintée selon l'état, et un footer sous la liste
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
  selon le port (barème Silvavenir)
- **Répartition** sur les 16 directions du pourtour (extrapolées)
- **Classe globale** = barème Silvavenir appliqué au **t/R moyen**
  sur les 16 directions
- **Fiabilité de l'extrapolation** : ligne « N/16 directions sondées —
  écart angulaire maximal entre voisins : X gr » affichée dans le
  diagnostic Tk et la fiche PDF. Permet de juger au coup d'œil la
  robustesse du diagnostic. Les exports XLSX/HTML, calqués sur la
  fiche Excel d'origine, ne reprennent pas ce bloc — il reste
  consultable dans l'onglet Diagnostic et sur la fiche PDF.
- **Diagnostic non publié si n_sondages < 2** : avec 0 ou 1 sondage,
  l'extrapolation par voisins n'a pas de sens (toutes les directions
  héritent de la même valeur). Le t/R moyen et la classe globale sont
  alors **supprimés** de la fiche PDF, remplacés par un avertissement
  explicite ; saisir au moins 2 sondages dans des directions
  différentes pour obtenir un diagnostic.

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
- La checkbox **« Afficher l'emplacement des sondages »** sous le
  dessin contrôle l'affichage des pastilles (utile pour exporter un
  PNG vierge sans annotations).

### Exports

- **PDF arbre** : fiche complète A4 avec en-tête mission, logo
  Silvavenir, identité de l'arbre, dessin annoté, tableau PRBS coloré,
  diagnostic avec barre de répartition Vert / Orange / Rouge.
  La colonne PRBS affiche la valeur pure (sans mention des dégradations
  externes).
- **PDF mission** : un seul fichier PDF multi-pages regroupant toutes
  les fiches arbres de la mission.
- **PNG** : dessin haute résolution 2400×2400, avec scaling automatique
  des polices et pastilles pour rester lisible une fois réduit dans
  un rapport Word.
- **XLSX** : tableau PRBS d'un arbre, **une ligne par sondage**
  (calqué sur la fiche Excel d'origine du cabinet), en-têtes et méta
  sur fond vert Silvavenir, alternance de lignes, largeurs de colonnes
  auto-ajustées, compartimentation ✓ / ✗ colorée, colonne t/R
  color-codée par classe. Nécessite
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

## Barème PRBS (Silvavenir)

Application du barème selon le port de l'arbre :

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
Ctrl+Z/Y, double-clic et clic droit sur un arbre).

## Crédits

- Algorithme d'interpolation : Catmull-Rom spline fermée (Catmull & Rom, 1974)
- Convention PRBS : méthode VTA de Mattheck & Breloer (1994)
- Barème de classification : convention Silvavenir
- Logo : Silvavenir, Foresterie urbaine
- Polices embarquées : DejaVu (`assets/fonts/`) sous licence Bitstream
  Vera. Voir `assets/fonts/LICENSE`.
