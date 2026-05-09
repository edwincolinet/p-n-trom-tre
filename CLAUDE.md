# Pénétromètre — Projet Silvavenir

Application desktop d'expertise arboricole. Logiciel d'aide à la décision
pour les expertises au pénétromètre (mesure de cavités dans les troncs).
Utilisé en interne par le cabinet **Silvavenir** (foresterie urbaine).

## Stack

- **Python 3.9+** (3.12 recommandé)
- **Tkinter** (UI) — bibliothèque standard, pas d'install à part
- **Pillow** (rendu PNG/PDF + chargement logo) — seule dépendance externe

Aucun framework, aucun build system. C'est volontaire : l'app doit pouvoir
être lancée d'un double-clic sur n'importe quel poste avec Python installé.

## Structure

```
resistographe.py        ← UI Tk + App + main (≈ 2200 lignes)
model.py                ← dataclasses (Sondage, Arbre, …) + logique métier
geometry.py             ← briques pures (spline, contreforts, barème, polaire)
pil_render.py           ← rendu PNG + fiche PDF A4
palette.py              ← couleurs partagées Tk ↔ PIL (COLOR_*, COULEUR_CLASSE)
export.py               ← exports XLSX/HTML du tableau PRBS d'un arbre
tests/                  ← suite unittest (95 tests, stdlib uniquement)
assets/
  silvavenir_logo.jpg   ← logo (header app + fiche PDF)
  Icone.jpeg            ← icône bureau pour Penetrometre.desktop
Lancer_Penetrometre.bat ← lanceur double-clic Windows
requirements.txt        ← Pillow + openpyxl (XLSX) pinnés
```

Le nom de fichier `resistographe.py` reste celui-ci pour des raisons
historiques même si le produit s'appelle « Pénétromètre » (Résistographe
est une marque déposée).

**Graphe de dépendances** (chaque module n'importe que vers le bas) :

```
geometry.py   (stdlib)
   ↑
model.py + palette.py
   ↑
export.py + pil_render.py
   ↑
resistographe.py  (Tk + main)
```

## Architecture

### `geometry.py` — fonctions pures (stdlib uniquement)

Module isolé de Tk et PIL, couvert par les tests :

**Logique métier**
- `classer_prbs(ratio_tR, port_arbre) -> str` — barème Silvavenir,
  renvoie un label `Vert | Orange | Rouge`. **Pas de couleur** : la
  couleur est une convention de présentation et vit côté UI.
- Constantes : `PORTS_ARBRE`, `PORTS_GROUPE_LIBRE`, `PORTS_GROUPE_STRICT`,
  `CLASSE_VERT`, `CLASSE_ORANGE`, `CLASSE_ROUGE`.

**Géométrie pure**
- `catmull_rom_closed` — interpolation spline fermée.
- `bell_max_at_grade(grade, contreforts)` — hauteur de cloche cosinus²
  maximale à un grade donné (max sur tous les contreforts qui
  couvrent ce grade).
- `contrefort_zones(contreforts)` — fusion des intervalles angulaires
  qui se chevauchent ou se touchent (une seule cloche unifiée par
  zone connectée, plus de V entre deux contreforts proches).

**Primitives de rendu partagées Tk ↔ PIL** (renvoient des listes de
points `(x, y)` en coordonnées écran, prêtes à passer à
`Canvas.create_polygon` ou à `ImageDraw.polygon`) :
- `polar_to_xy(cx, cy, scale, r_cm, grade)` — polaire → écran.
  Grade 0 = Nord, sens horaire.
- `polar_idx_to_xy(cx, cy, scale, r_cm, idx)` — variante indexée
  (idx ∈ [0,16) ↔ grade = idx × 25).
- `cavity_polygon(alteration_par_grade, cx, cy, scale)` — polygone
  lissé de la cavité d'altération.
- `contrefort_zone_outline(zone, contreforts, R, ep_cm, cx, cy,
  scale)` — dict `{wood_outer, base, bark_outer?, bark_inner?}` pour
  une zone fusionnée renvoyée par `contrefort_zones`.
- `degradation_externe_outline(deg, contreforts, R, ep_cm, cx, cy,
  scale)` — polygone d'une dégradation externe (bord externe qui suit
  `R+ep+cloche`, bord interne à `outer-profondeur`).

### `export.py` — exports tableau PRBS

Module dédié aux deux exports stylés du tableau PRBS d'un arbre :
- `prbs_table_rows(arbre, classer_prbs)` — pure : 16 dicts (un par
  direction), inclut sondées + extrapolées + dégradation externe.
- `export_prbs_xlsx(arbre, chantier, path, couleur_classe,
  classer_prbs)` — fichier Excel stylé. Nécessite openpyxl (dégradé
  proprement avec `RuntimeError` clair sinon — `HAS_OPENPYXL` flag).
- `export_prbs_html(arbre, chantier, path, couleur_classe,
  classer_prbs)` — fichier HTML autonome (CSS embarqué, imprimable
  en PDF via le navigateur). Aucune dépendance.

`couleur_classe` (le dict `COULEUR_CLASSE`) est injecté depuis l'UI
pour ne pas créer de cycle d'import (export.py n'importe pas
resistographe.py). Les arbres et chantiers sont reçus en duck-typing.

### `model.py` — dataclasses + logique métier

Module sans dépendance Tk ni PIL (stdlib + `geometry`), couvert par
les tests :

- `Sondage` — une mesure ponctuelle dans une direction.
- `DegradationExterne` — un arc d'écorce dégradée.
- `Contrefort` — empattement à la base (cloche cosinus²).
- `Arbre` — sondages, dégradations, contreforts. Méthodes calculées :
  - `compute_alteration_par_grade()` — **pure** (ne mute pas).
    Extrapolation par moyenne pondérée linéaire entre voisins.
  - `recompute_alteration_from_sondages()` — **mutateur explicite**.
    Met à jour le cache `self.alteration_par_grade` (qui est aussi
    sérialisé en JSON via `asdict`). Seul moyen de rafraîchir le
    cache. À appeler avant tout dessin qui lit
    `arbre.alteration_par_grade` directement.
  - `prbs_par_grade()`, `ratio_tR_par_grade()`,
    `repartition_classes()` — purs : utilisent
    `compute_alteration_par_grade()` à la volée. Ils n'écrivent
    JAMAIS dans `self.alteration_par_grade` (verrou par test).
- `Chantier` — mission qui regroupe plusieurs arbres. `to_dict` /
  `from_dict` pour la persistance. **`from_dict` filtre les clés
  inconnues** par `__dataclass_fields__` à chaque niveau, ce qui
  rend l'ouverture robuste à un JSON futur qui contient des champs
  qu'une ancienne version de l'app ne connaît pas encore.

### `palette.py` — couleurs partagées Tk ↔ PIL

Petit module sans logique : centralise les `COLOR_*` (panneaux,
bois, écorce, cernes, dégradation, sondage) et le dict
`COULEUR_CLASSE` (label → hex). Importé à la fois par
`resistographe.py` (Tk) et `pil_render.py` (PIL). Sans ce module
intermédiaire, les deux auraient un cycle d'import.

### `pil_render.py` — rendu PNG + fiche PDF A4

- `render_arbre_to_pil_image(arbre, …)` — section transversale
  identique à celle du `SectionCanvas` Tk, mais sur une `PIL.Image`.
- `render_fiche_arbre_to_pdf_page(arbre, chantier)` — page A4
  150 DPI complète : en-tête mission + logo, identité de l'arbre,
  dessin, légende horizontale, tableau PRBS ajustée, diagnostic.
- Helpers : `_pil_load_fonts()` (multi-OS avec fallback),
  `_fit_text()` (troncature ellipsis), `_draw_horizontal_legend_pil()`.
- `HAS_PIL` exposé : `False` si Pillow absent ; les actions d'export
  côté UI affichent alors un message clair et n'appellent pas le
  rendu.

**Tkinter (`resistographe.SectionCanvas`) et PIL partagent les
primitives géométriques** définies dans `geometry.py` (`polar_to_xy`,
`cavity_polygon`, `contrefort_zone_outline`,
`degradation_externe_outline`). La géométrie ne peut donc plus
diverger entre les deux moteurs. Restent spécifiques à chaque
renderer : la typographie, l'API de dessin (`Canvas.create_*` vs
`d.polygon/ellipse/line`), la couche d'écorce (cf. piège
`outline+width` ci-dessous), et tout ce qui est purement
présentation (échelle, lettres cardinales, règle graduée).

### `resistographe.py` — application Tk + main

Organisé en sections séparées par des bandeaux de commentaires :

1. **Imports + logger applicatif** (`logging.getLogger("penetrometre")`).
2. **Rendu Tkinter** — `class SectionCanvas(tk.Canvas)` : dessine la
   section transversale en temps réel dans la fenêtre.
3. **Application** — `class App(tk.Tk)` : fenêtre principale,
   onglets, sync UI ↔ modèle, actions (ajouter/dupliquer arbre,
   exports PNG/PDF/CSV/XLSX/HTML, …).
4. **`main()`** — configure `_setup_logging()` puis lance
   `App().mainloop()`. Le logger écrit dans
   `~/.penetrometre/penetrometre.log` (RotatingFileHandler), ce qui
   rend les exceptions visibles même en double-clic Windows. Toutes
   les actions d'export catchent leurs exceptions avec
   `log.exception(...)` avant le `messagebox.showerror`.

Les dataclasses du modèle et le rendu PIL sont **importés** depuis
`model` et `pil_render` ; ils ne sont plus définis ici.

## Conventions métier importantes

- **Grades** : 0 à 375 par pas de 25 (16 directions). 0 = Nord, sens
  horaire. **Pas de symbole `°`** — afficher `100 gr` (gradian).
- **PRBS** = Paroi Résiduelle de Bois Sain = épaisseur de bois sain
  mesurée par le foret. C'est la mesure invariante (physique) — quand
  le rayon change, la PRBS reste, c'est `bois_altéré` qui s'ajuste.
- **t/R** = PRBS / Rayon, ratio entre 0 et 1.
- **Classe globale** = barème Silvavenir appliqué au **t/R moyen** sur
  les 16 directions (pas au minimum, ni au pourcentage de directions).
- Les **dégradations externes consomment** du bois sain :
  `PRBS_ajustée = bois_sain − profondeur_dégradation_externe`.
- **Écorce du tronc** : épaisseur `epaisseur_ecorce_cm` ajoutée vers
  l'extérieur du rayon (purement visuel, n'intervient pas dans la PRBS
  ni le diagnostic). Rayon externe = `R + ep`.
- **Contreforts** : un contrefort = noyau de bois (cloche cosinus² qui
  culmine à `R + longueur` au centre, redescend à `R` aux extrémités)
  recouvert d'une couche d'écorce de **même épaisseur** que celle du
  tronc (sommet externe à `R + longueur + ep`).
- **Fusion des contreforts adjacents** : quand plusieurs contreforts se
  chevauchent ou se touchent, ils sont rendus comme **une seule cloche
  unifiée** dont la hauteur en chaque grade est le max des hauteurs
  individuelles. Cette fusion (helpers `bell_max_at_grade` /
  `contrefort_zones`) évite l'encoche en V qui apparaissait quand
  chaque contrefort était dessiné isolément.
- **Dégradations externes et contreforts** : la dégradation suit la
  surface réelle de l'arbre — son bord externe est à `R + ep + cloche`
  et son bord interne à `outer − profondeur`. Une dégradation qui
  traverse un contrefort y mord à concurrence de sa profondeur.
- **Règle graduée** sous la section : étendue de `-R_ext` à `+R_ext`.
  La portion bois `[-R, +R]` est en trait noir fin ; les portions
  écorce sont des barres brun foncé épaisses.
- **Couleurs `BARK` et `ROT` distinctes** : `COLOR_BARK = #5C3A1E`
  (écorce intacte) ≠ `COLOR_ROT = #3E2510` (bois dégradé, bien plus
  foncé). C'est essentiel pour que la « plaie » d'une dégradation soit
  lisible quand elle traverse l'écorce. **Ne jamais réunifier les deux
  couleurs** — la légende des exports les présente comme deux entrées
  distinctes (« Bois dégradé » vs « Écorce »).

## Conventions de code

- Pas de dépendance ajoutée sans bonne raison. Tkinter pur + Pillow
  (+ openpyxl optionnel pour XLSX).
- Compatibilité Python 3.9+ (annotations `Optional[X]` plutôt que `X | None`
  pour les positions critiques, mais `tuple[str, str]` est OK car Python 3.9
  supporte le PEP 585 dans ce contexte).
- Tout en français côté UI et docstrings (le projet est franco-français).
- Pas de `print` en production — l'utilisateur voit les erreurs via
  `messagebox`, et le détail (stack trace) part dans le logger applicatif
  (`logging.getLogger("penetrometre")`, fichier
  `~/.penetrometre/penetrometre.log`, configuré par `_setup_logging()`
  au démarrage). Toute action d'export doit logger ses exceptions via
  `log.exception(...)` avant le `messagebox.showerror`.

## Compatibilité ascendante ET descendante des fichiers

Les missions sont enregistrées en JSON. **L'app doit toujours pouvoir
ouvrir les anciens fichiers** (compat ascendante) ET un fichier produit
par une version plus récente avec des champs qu'on ne connaît pas
encore (compat descendante).

- Ascendante : migration silencieuse dans `Chantier.from_dict` (par ex.
  mapping des anciens libellés de port
  `"Libre, semi-libre ou traumatique"` → `"libre"`). **Ne jamais
  casser cette compat sans ajouter une migration.**
- Descendante : `from_dict` filtre chaque dict d'entrée par
  `Class.__dataclass_fields__` avant `Class(**kwargs)`. Les clés JSON
  inconnues sont ignorées silencieusement à tous les niveaux
  (`Chantier`, `Arbre`, `Sondage`, `DegradationExterne`, `Contrefort`).
  Verrouillé par `test_champs_inconnus_ignores`.

## Commandes utiles

```bash
# Vérifier la syntaxe avant commit
python -c "import ast; ast.parse(open('resistographe.py').read())"

# Lancer l'app
python resistographe.py

# Lancer la suite de tests (stdlib unittest, aucune dépendance)
python -m unittest discover tests
```

La suite couvre les fonctions pures à risque métier : barème
`classer_prbs`, géométrie des contreforts (`bell_max_at_grade`,
`contrefort_zones`), primitives de rendu partagées Tk↔PIL
(`polar_to_xy`, `cavity_polygon`, `contrefort_zone_outline`,
`degradation_externe_outline`), extrapolation de l'altération,
calcul PRBS, migration JSON et données du tableau exporté
(`prbs_table_rows`). Un smoke test XLSX est exécuté si openpyxl est
installé (skip sinon). Lancer la suite avant tout commit qui touche
au modèle, aux helpers géométriques ou aux exports.

## Pièges connus

- Le rendu Tkinter et le rendu PIL sont **deux moteurs distincts** qui
  partagent désormais leurs primitives géométriques (cf. `geometry.py`
  → `polar_to_xy`, `cavity_polygon`, `contrefort_zone_outline`,
  `degradation_externe_outline`). La géométrie ne peut donc plus
  diverger. Restent à synchroniser à la main : la palette/typographie,
  l'API de dessin, l'écorce/anneau (cf. piège `outline+width`
  ci-dessous) et tout ce qui est spécifique à chaque renderer
  (lettres cardinales, règle graduée, légende, échelle).
- Les positions des éléments hors-tronc (lettres cardinales, pastilles
  de sondage, règle graduée) sont en **pixels absolus** (pas en cm)
  pour rester constantes quel que soit le rayon de l'arbre.
- Le titre + méta-données du dessin sont placés au-dessus de la zone
  de la lettre N (tout en haut). Toujours laisser une marge suffisante
  pour ne pas que la lettre N soit tronquée.
- **Différence Tkinter ↔ PIL pour `outline + width` sur ellipse** :
  Tkinter `create_oval(outline, width)` centre le trait sur la
  frontière du bounding box ; PIL `d.ellipse(outline, width)` dessine
  le trait **entièrement à l'intérieur** du bounding box. Conséquence
  pour l'anneau d'écorce : en PIL, le bbox doit être à `R_ext`
  (= `R + ep`) pour que l'outline de largeur `ep_px` tombe exactement
  sur `[R, R_ext]`. En Tkinter, le bbox est à `R + ep/2` (pour que
  l'outline centré couvre `[R, R_ext]`).
- **Ordre de dessin des contreforts** : pour éviter toute raie visible
  entre le contrefort et l'anneau d'écorce du tronc, on dessine
  d'abord la couche d'écorce du contrefort avec bord interne à `R`
  constant (fusionne avec l'anneau du tronc), puis le polygone bois
  par-dessus pour révéler le noyau. Le polygone bois descend à
  `cf_inner_r = R - 1/scale` pour ne laisser aucun trou pixel.
- **Ordre global des couches** dans la section (Tkinter et PIL doivent
  rester alignés) :
  1. disque bois sain
  2. cernes de croissance
  3. cavité d'altération (spline interne)
  4. anneau d'écorce
  5. contreforts fusionnés (une cloche par zone connectée)
  6. **dégradations externes en DERNIER** — leur bord externe suit la
     surface (`R + ep + cloche`) afin de mordre dans l'écorce et les
     contreforts qu'elles traversent.
- **Légende des exports** : `render_arbre_to_pil_image(...,
  show_legend=True)` réserve une bande **sous la règle graduée** pour
  une légende horizontale sur une ligne. Pour le PDF, la légende est
  rendue **directement par `render_fiche_arbre_to_pdf_page`** (et non
  dans l'image du tronc) afin de profiter de la pleine largeur de la
  page A4 — sinon les items à droite sont tronqués.
- **Dimensionnement adaptatif du PDF** : `render_fiche_arbre_to_pdf_page`
  estime la place que prendront le tableau, le diagnostic, la légende
  et le pied de page, puis alloue le reste au dessin (entre 420 et
  900 px). Au-delà de 8/12 sondages, la hauteur de ligne et la police
  du tableau se resserrent (38/35/32 px, 17/16/15 pt) pour que la
  page reste sur une feuille A4 unique.
- **XLSX et cellules fusionnées** : pour appliquer les largeurs de
  colonnes dans `export_prbs_xlsx`, utiliser
  `openpyxl.utils.get_column_letter(i)` et **PAS**
  `ws.cell(row=1, column=i).column_letter`. La ligne 1 contient un
  titre fusionné A1:J1 : openpyxl renvoie alors des `MergedCell` pour
  les colonnes 2..10, et `MergedCell` n'expose pas `column_letter`.
  Couvert par `XlsxSmokeTests.test_export_complet_ne_plante_pas`.
- **Pastille du sondage = PRBS ajustée**, jamais PRBS brute. Les deux
  renderers (Tk `SectionCanvas`, PIL `render_arbre_to_pil_image`)
  calculent `prbs_adj = max(0, s.prbs_cm - deg_ext_par_grade[grade])`
  puis `classer_prbs(prbs_adj / R, port)`. Ne pas régresser sur
  `s.ratio_tR(R)` qui ignore la dégradation externe — la pastille
  serait alors incohérente avec le tableau Diagnostic et la fiche PDF.
- **`prbs_par_grade()` est un getter pur**. Il ne mute PAS
  `self.alteration_par_grade`. Pour rafraîchir le cache (par exemple
  avant un dessin qui le lit directement), passer **explicitement**
  par `recompute_alteration_from_sondages()`. Verrou de pureté :
  `test_prbs_par_grade_ne_mute_pas_l_alteration`.

## Quand tu modifies l'app

1. **Avant** de toucher au code : repérer le bon module en fonction de
   la nature du changement.
   - **Métier pur** (barème, géométrie, primitives polaires) →
     `geometry.py`.
   - **Modèle** (dataclasses, extrapolation, calcul PRBS, migration
     JSON) → `model.py`.
   - **Rendu PNG/PDF** → `pil_render.py`.
   - **Couleurs partagées Tk/PIL** → `palette.py`.
   - **Exports tableau** (XLSX/HTML) → `export.py`.
   - **UI Tk + dialogues + actions** → `resistographe.py`.
2. **Géométrie partagée** : si tu changes la géométrie d'un élément
   (cavité, contreforts, dégradation), modifie `geometry.py` une fois ;
   les deux renderers Tk et PIL héritent automatiquement. Pour les
   aspects spécifiques à un renderer (couleurs, traits, écorce,
   typographie, règle graduée, lettres cardinales), modifie côté Tk
   **et** côté PIL.
3. Pour les changements de modèle : penser à la migration JSON
   (`Chantier.from_dict`). Si tu **ajoutes** un champ dataclass, les
   anciens JSON le verront avec sa valeur par défaut (OK). Si tu
   **renommes** ou **supprimes** un champ, ajouter une migration
   ascendante explicite.
4. **Lancer la suite de tests** (`python -m unittest discover tests`,
   95 tests) avant tout commit qui touche au modèle, à la géométrie
   ou aux exports.
5. Tester en lançant l'app et en sauvegardant / rechargeant un `.json`.
6. Pour valider les exports PNG/PDF, générer un échantillon avec
   plusieurs cas (avec/sans écorce, avec/sans contreforts, avec/sans
   sondages, avec une dégradation externe traversant un contrefort) —
   les bugs de raster PIL n'apparaissent pas toujours dans Tkinter.
7. Pour valider les exports XLSX/HTML, ouvrir réellement le fichier
   produit (LibreOffice/Excel pour XLSX, navigateur pour HTML) :
   l'écriture peut réussir sans que le résultat soit visuellement
   correct. Le smoke test couvre la non-régression mécanique
   (taille, structure), pas l'esthétique.
8. Pour les changements de légende : tester en condition « stress »
   (16 sondages + commentaire long) pour s'assurer que la fiche PDF
   reste sur une seule page.
9. En cas de bug remonté par un utilisateur : lui demander
   `~/.penetrometre/penetrometre.log` (ou
   `%USERPROFILE%\.penetrometre\penetrometre.log` sous Windows). Toutes
   les exceptions des actions d'export y sont consignées avec leur
   stack trace via `log.exception(...)`.

## Limites connues (non corrigées)

- **Duplication de rendu Tk ↔ PIL au-delà de la géométrie**.
  `geometry.py` partage les primitives polaires et les contours
  (cavité, contreforts, dégradations). Restent dupliqués entre Tk
  (`SectionCanvas.redraw`) et PIL (`render_arbre_to_pil_image`) :
  l'écorce/anneau, les cernes, la règle graduée, les pastilles, les
  ticks et lettres cardinales — chacun avec ses paramètres en pixels
  spécifiques (`outline+width`, anchors, polices). Toute modif
  visuelle de ces éléments doit être faite côté Tk **et** côté PIL.
- **Pas de tests visuels (golden images)** sur les rendus PIL. La
  validation est manuelle via les exports d'échantillon (cf. point 6
  ci-dessus). Une régression visuelle silencieuse (palette, marge,
  alignement) ne sera pas détectée par `unittest discover`.
