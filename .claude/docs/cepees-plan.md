# Plan d'implémentation — Cépées & formes singulières

> **But du document** : trace durable du chantier « cépées » (arbres
> multi-brins) pour qu'une session puisse reprendre où la précédente s'est
> arrêtée. Décisions métier figées, design technique par étape, garde-fous.
> Compagnon de la mémoire `project_cepees-formes` (résumé) et de
> `CLAUDE.md` (conventions). **Tenir à jour** : cocher les étapes faites,
> noter les écarts.

## 1. Contexte

L'`Arbre` était un **cercle** de rayon scalaire unique centré sur un cœur
unique — seul vrai angle mort partagé avec l'Excel d'origine du cabinet. On
généralise vers : formes **singulières** (ovale) et **cépées** (un genet =
plusieurs brins/ramets, chacun avec sa forme, son diamètre, sa position).

Vocabulaire (botanique des plantes clonales) : `Arbre` = **genet** (individu
inventorié) ; `Brin` = **ramet** (tige physique autonome).

## 2. Décisions métier (validées par Edwin — NE PAS re-trancher)

- **Diagnostic d'une cépée** : une classe **par brin** (vue individuelle) ET
  une **classe globale = pire brin** (approche sécuritaire). La globale
  s'agrège sur les *classes* des brins, **jamais** sur un t/R moyen
  inter-brins (repères polaires distincts, ça n'a pas de sens physique).
- **Forme singulière** : **ellipse paramétrique** (grand axe / petit axe /
  orientation). FAIT (Étape 1). Pas de rayon-par-direction ni de spline libre.
- **Position des brins** : **placement à la souris** (à affiner si besoin).
- **UX** : tout ce qui touche formes/cépées vit dans un **éditeur avancé
  dédié** (`dialogs.ask_forme_tronc`, à faire grandir), PAS en ligne dans le
  formulaire — le cas par défaut (tronc circulaire mono-brin) reste simple.

## 3. État d'avancement

- [x] **Étape 0** — `Brin` (ramet) extrait d'`Arbre` (genet),
  `Arbre.brins: List[Brin]` ≥ 1, shims de compat (`brins[0]`), persistence
  v3 + migration. Invisible. (`e89ac60`)
- [x] **Étape 1** — tronc **ovale** : modèle/diagnostic (t/R local),
  rendu elliptique PIL+Tk (goldens préservés), éditeur avancé `ask_forme_tronc`.
  (`059fed6` `7ede5bb` `d5c8515` `d6291e2`)
- [ ] **Étape 2** — rendu **multi-brins** (lecture seule). ← PROCHAINE
- [ ] **Étape 3** — diagnostic par brin + classe globale (pire brin) + exports.
- [ ] **Étape 4** — éditeur souris (ajouter/déplacer/pivoter brins ; sélecteur
  de brin pour la grille de saisie 16 directions).

## 4. Modèle de données (déjà en place)

`Brin` porte déjà tout le nécessaire (cf. `model.py`) :
`rayon_tronc_cm` (demi-grand-axe), `rayon_petit_axe_cm`, `orientation_grade`,
`epaisseur_ecorce_cm`, `diametre_sous_ecorce_cm`, `sondages`,
`degradations_externes`, `contreforts`, et **`pos_x_cm`, `pos_y_cm`,
`rotation_grades`** (réservés, = 0 pour un brin unique centré).
`label` (« a », « b », …).

À ajouter au fil des étapes : peut-être un helper `Brin.extent_cm()` (rayon
d'encombrement = max rayon + écorce + plus longue saillie de contrefort) pour
le cadrage multi-brins (Étape 2).

## 5. Étape 2 — Rendu multi-brins (lecture seule)

**But** : afficher une cépée (N brins positionnés) dans le canvas Tk et le PNG
PIL. Aucune édition fine de position encore (vient en Étape 4) — les positions
sont lues du modèle.

**Livrable visible — DÉCIDÉ (Edwin, 2026-06-07)** : action minimale **« ＋ Brin »**
dans l'onglet Identification (à côté de « Forme du tronc… »). Elle ajoute un brin
hérité (forme/essence du brin courant) décalé d'un offset par défaut sur l'axe
E-O : `pos_x = R(courant) + R(nouveau) + marge`, `pos_y = 0`. Placement grossier
(non déplaçable avant l'Étape 4) mais l'opérateur **voit** une cépée et peut la
saisir. Prévoir aussi « Supprimer brin » (au moins via menu/éditeur) et le
sélecteur de brin pour la grille de saisie (peut glisser en Étape 4).

**Invariant CRITIQUE** : un genet **à brin unique** (99 % des arbres) doit
rendre **strictement comme aujourd'hui** → goldens byte-identiques. Donc :
`if len(arbre.brins) == 1 and pos == (0,0)`: chemin actuel inchangé.

**Design technique** (PIL `render_arbre_to_pil_image` + Tk `SectionCanvas.redraw`,
en miroir) :

1. **Extraire un `_draw_brin(...)`** : prend `(brin, cx_brin, cy_brin, scale,
   …)` et dessine UNE section (bois, cernes, cavité, écorce, contreforts,
   dégradations, pastilles de sondage) à un centre écran donné. C'est en gros
   le corps actuel de `render`/`redraw` SANS le calcul de cadrage, le titre,
   la règle, les cardinales. **Refactor à goldens constants** : pour 1 brin
   centré, le résultat pixel doit être identique.
2. **Cadrage global** : calculer la bounding box en cm sur tous les brins :
   pour chaque brin, centre `(pos_x, pos_y)` ± `extent_cm()`. En déduire un
   `scale` unique (fit dans la zone dispo) et l'origine écran. Convertir
   chaque `(pos_x, pos_y)` cm → `(cx_brin, cy_brin)` px.
3. **Décorations GLOBALES (une seule fois, pas par brin)** : la rose des vents
   (cardinales N/E/S/O), les ticks et la **règle graduée** sont une référence
   d'orientation/échelle commune à toute la planche — les dessiner une fois
   autour de la bbox globale (ou en marge), pas autour de chaque brin.
   *Décision* : cardinales = orientation partagée par tous les brins (même
   boussole). À trancher : ticks autour de la bbox ou de chaque brin.
4. **Labels de brin** : afficher `brin.label` (a/b/c…) près de chaque brin.
5. **Sondages** : `sondage_render_data` prend déjà un `arbre` ; le généraliser
   pour pointer un `brin` (ou lui passer le brin). Les pastilles se placent au
   rayon local du brin.

**Convention de coordonnées** : `pos_x_cm`/`pos_y_cm` = position du cœur du
brin dans le plan du genet, origine = cœur du brin[0] (ou centroïde — à
trancher). x → Est, y → Sud (cohérent avec l'écran ; grade 0 = Nord = -y).

**Tests** : fixture « cepee » (2-3 brins positionnés, dont un ovale) → goldens
PIL + Tk. Vérifier que les 5 fixtures existantes restent byte-identiques
(genet 1 brin). Test unitaire `extent_cm` + cadrage (bbox attendue).

**⚠ Trouvaille technique (à ne pas redécouvrir)** : `_draw_brin` a besoin du
**genet ET du brin**. Les couches de contour (bois/écorce/cernes/contreforts/
dégradations) ne lisent que des attributs présents sur `Brin`
(`est_ovale`, `rayon_a_grade`, `contreforts`, `epaisseur_ecorce_cm`,
`rayon_tronc_cm`) → changer leur signature `arbre` → `brin` (duck-typing : un
`Arbre` via shims ou un `Brin` natif marchent tous deux, donc mono-brin reste
identique). **MAIS** `sondage_render_data` lit aussi `port_arbre` et `meche_cm`
qui sont **GENET-level** (sur `Arbre`, pas `Brin`) : il faut lui passer le brin
**et** le port/mèche du genet (signature à étendre, p. ex.
`sondage_render_data(brin, port, meche, cx, cy, scale, …)`). Le point central du
dessin (la moelle, `d.ellipse` COLOR_INK) se trace par brin à son centre.

**Risque** : le refactor `_draw_brin` est la partie sensible aux goldens.
Faire l'extraction d'abord à comportement constant (1 brin), committer (vérifier
goldens inchangés), PUIS ajouter le cadrage multi-brins et le « ＋ Brin ».

## 6. Étape 3 — Diagnostic par brin + classe globale + exports

- **`diagnostic.py`** : les fonctions pures prennent aujourd'hui un `arbre` et
  opèrent sur `brins[0]` via shims. Les généraliser pour opérer **par brin**
  (signature `brin`, ou helper `repartition_classes_brin(brin, port)`). Le
  niveau `Arbre` agrège : `classe_globale_genet = pire classe parmi les brins`
  (ordre Rouge > Orange > Vert ; « non fiable » si un brin < 3 sondages — règle
  à confirmer pour l'agrégat). Exposer une liste `(label, snapshot)` par brin.
- **Fiche PDF** (`fiche_pdf.py`) : pour une cépée, lister les brins (un bloc
  diagnostic par brin) + la classe globale en tête. Mono-brin : inchangé.
- **Synthèse mission** (`diagnostic.mission_synthesis_rows`) : ligne genet =
  classe globale (pire brin) ; éventuelles sous-lignes par brin. Décider du
  rayon « représentatif » d'un genet multi-brins (max ? somme ?).
- **Liste d'arbres** (`App._arbre_etat`) : la pastille de classe d'un genet
  multi-brins = pire brin. Le seuil « fiable ≥ 3 sondages » s'applique par brin.
- **Exports tableau** (`export.py`, PRBS XLSX/HTML) : par brin.

## 7. Étape 4 — Éditeur souris (le gros morceau UX)

Faire grandir `ask_forme_tronc` (ou un nouveau Toplevel plus large) en
**éditeur de cépée** :

- Un **canvas d'édition** montrant les brins ; cliquer-glisser un brin le
  déplace (`pos_x/pos_y`) ; molette/poignée pour `rotation_grades` ; bouton
  « ＋ Brin » / « Supprimer brin » ; champ label.
- Par brin sélectionné : ses paramètres de forme (rayon, ellipse) — réutilise
  la logique Étape 1.
- **Sélecteur de brin** pour la **grille de saisie 16 directions**
  (`pane_sondages`) : aujourd'hui elle édite `brins[0]` via shims. Ajouter un
  sélecteur (combobox/onglets « Brin a / b / c ») qui repointe la grille sur le
  brin courant. C'est ici que les **shims `brins[0]` doivent commencer à être
  remplacés** par un « brin courant » explicite porté par l'App.
- Undo/redo : chaque opération souris = un `push_undo` (au drop, pas pendant
  le drag).

## 8. Invariants & garde-fous (à respecter à CHAQUE étape)

- **Goldens** : genet mono-brin centré circulaire/ovale = rendu byte-identique.
  Toute couche de rendu branche sur le cas simple AVANT le cas multi/ovale.
  Régénérer les goldens ne doit modifier AUCUNE fixture existante (seules les
  nouvelles s'ajoutent) — c'est le test de non-régression.
- **Compat fichier** : champs additifs avec défaut = OK (pas de bump). Un bump
  de `FORMAT_VERSION` seulement si renommage/suppression ; migration explicite.
- **Shims `brins[0]`** : couche de compat temporaire. Ne PAS l'étendre
  gratuitement ; commencer à la retirer en Étape 4 (brin courant explicite).
- **Pureté `diagnostic.py`/`geometry.py`** : pas de Tk, pas de mutation.
- **Qualité** : `python -m unittest discover tests`, `ruff check .`, et la
  liste mypy de CLAUDE.md doivent rester verts (exit 0) à chaque commit.
  Golden Tk : `DISPLAY=:0 python -m tests.test_section_canvas` (xvfb-run absent
  sur cette machine — utiliser `DISPLAY=:0`). Golden PIL : `python -m
  tests.test_render`. Régénération : `--update`.

## 9. Points ouverts & défauts retenus

- [x] **Étape 2 : action « ＋ Brin » minimale dès maintenant** (DÉCIDÉ Edwin
  2026-06-07) — cf. § 5.
- [ ] *Défaut retenu (révisable)* **Origine du repère de position** = cœur du
  `brins[0]` (le 1er brin reste en (0,0) ; les suivants se placent autour). Plus
  simple que le centroïde et stable quand on ajoute/retire des brins.
- [ ] *Défaut retenu (révisable)* **Cardinales/ticks** dessinés **une fois**
  globalement (boussole partagée par tous les brins, même orientation) autour de
  la bbox globale ; la **moelle et les pastilles** restent par brin. Règle
  graduée : une seule, globale.
- [ ] **Étape 3 (à trancher quand on y arrive)** : un genet est-il « non fiable »
  dès qu'UN brin a < 3 sondages, ou fiabilité par brin seulement ? Rayon
  « représentatif » du genet en synthèse (max des brins ? proposé par défaut).
