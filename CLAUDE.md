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
penetrometre.py        ← App + main (≈ 590 lignes — orchestration Tk)
section_canvas.py      ← SectionCanvas (rendu Tk de la section, ≈ 430 l.)
pane_identification.py  ← onglet Identification (10 vars + sync Ø↔R)
pane_sondages.py        ← onglet Sondages (table + add/edit/del)
pane_degradations.py    ← onglet Dégradations externes (idem)
pane_contreforts.py     ← onglet Contreforts (idem)
pane_diagnostic.py      ← onglet Diagnostic (scroll + résumé + PRBS + exports)
app_exports.py          ← actions d'export (PNG/PDF/CSV/XLSX/HTML)
                          — adaptateur Tk vers les rendus purs
app_menu.py             ← barre de menu Tk (Fichier/Arbres/?, raccourcis)
app_style.py            ← thème ttk (couleurs, polices, padding)
dialogs.py              ← 3 dialogues Tk (Sondage, Dégradation, Contrefort)
model.py                ← dataclasses (Sondage, Arbre, …) + logique métier
persistence.py          ← I/O JSON des missions (save/load + migration)
geometry.py             ← briques pures (spline, contreforts, polaire)
bareme.py               ← barème métier Silvavenir (classer_prbs, ports, classes)
pil_render.py           ← rendu PNG + fiche PDF A4
palette.py              ← couleurs partagées Tk ↔ PIL (COLOR_*, COULEUR_CLASSE)
export.py               ← exports XLSX/HTML du tableau PRBS d'un arbre
tests/                  ← suite unittest (137 tests dont 4 golden-images
                          PIL et 4 golden-dumps Tk)
tests/_fixtures.py      ← scénarios d'arbre partagés (PIL + Tk)
tests/fixtures/         ← PNG (golden PIL) + JSON (golden dump Tk)
assets/
  silvavenir_logo.jpg   ← logo (header app + fiche PDF)
  Icone.jpeg            ← icône bureau pour Penetrometre.desktop
  fonts/                ← DejaVu Serif Bold + Sans + Sans-Bold + LICENSE
Lancer_Penetrometre.bat ← lanceur double-clic Windows
.github/workflows/      ← CI (matrix Python 3.9/3.12, unittest + py_compile)
requirements.txt        ← Pillow + openpyxl (XLSX) pinnés
```

Note marque : le produit s'appelle « Pénétromètre » (terme générique).
« Résistographe » est une marque déposée et n'apparaît plus dans le code
ni dans les noms de fichier.

**Graphe de dépendances** (chaque module n'importe que vers le bas) :

```
geometry.py + bareme.py   (stdlib)
   ↑
model.py + palette.py
   ↑
export.py + pil_render.py + persistence.py + dialogs.py   (dialogs.py est Tk-only)
   ↑
section_canvas.py + pane_*.py + app_exports.py + app_menu.py + app_style.py
   ↑
penetrometre.py  (Tk + main, classe App)
```

Chaque `pane_*.py` est un widget Tk autonome qui possède ses propres
vars / table / boutons / refresh / actions, et ne tape sur l'`App` que
via un `Protocol` (`_*Host`) déclaré en tête du module. C'est ce qui
permet à `penetrometre.py` (la classe `App`) de tenir en ~590 lignes au
lieu de ~1400 et d'éviter le god-module. Le rendu Tk de la section a
lui aussi été extrait dans `section_canvas.py` pour rester symétrique
à `pil_render.py`.

## Architecture

### `bareme.py` — barème métier Silvavenir (stdlib uniquement)

Module dédié à la règle métier de classification :
- `classer_prbs(ratio_tR, port_arbre) -> str` — barème Silvavenir,
  renvoie un label `Vert | Orange | Rouge`. **Pas de couleur** : la
  couleur est une convention de présentation et vit dans `palette.py`.
- `normaliser_port(value) -> str` — strip + lower puis vérifie
  l'appartenance à `PORTS_ARBRE`. Renvoie `""` si valeur inconnue ;
  utilisé par `Chantier.from_dict` pour valider `port_arbre` au
  chargement JSON (faute de frappe → log + fallback `"libre"`).
- Constantes : `PORTS_ARBRE` (`libre`, `semi-libre`, `délaissé`,
  `architecturé`, `traumatique`), `PORTS_GROUPE_LIBRE`,
  `PORTS_GROUPE_STRICT`, `CLASSE_VERT`, `CLASSE_ORANGE`, `CLASSE_ROUGE`.
  Le port `délaissé` est rangé dans `PORTS_GROUPE_LIBRE` (mêmes seuils
  30 % / 15 % que `libre`).

Séparé de `geometry.py` pour que le rôle de chaque module soit
mono-préoccupation : `geometry.py` = géométrie pure, `bareme.py` =
règle métier.

### `geometry.py` — fonctions pures (stdlib uniquement)

Module isolé de Tk et PIL, couvert par les tests :

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
- `adaptive_ruler_step_cm(scale_px_per_cm, min_gap_px)` — pas de
  graduation (en cm) tel que deux étiquettes consécutives soient
  séparées d'au moins `min_gap_px` pixels. Choisit dans
  `(1, 2, 5, 10, 20, 50, 100)`. Utilisé par les deux renderers (Tk
  `min_gap_px=24`, PIL `min_gap_px=50`) pour que les nombres de la
  règle ne se chevauchent plus sur les gros troncs.

### `export.py` — exports tableau PRBS

Module dédié aux deux exports stylés du tableau PRBS d'un arbre.
Le tableau est calqué sur la fiche Excel d'origine du cabinet
(`docs/tableau souhaité.png`) : **une ligne par sondage** (pas une
ligne par direction), triée par numéro de saisie, avec une ligne méta
arbre au-dessus (N° arbre / Hauteur sondage / Ø sondage sous écorce /
Hauteur de l'arbre) et une ligne de légende ✓/✗ sous le tableau.

- `prbs_table_rows_par_sondage(arbre, classer_prbs)` — pure : un dict
  par sondage (`numero`, `grade`, `rayon_cm`, `prbs_cm`,
  `bois_altere_cm`, `compartimentation`, `ratio_tR` ajusté, `classe`,
  `commentaire`). Le `ratio_tR` retourné est ajusté de la dégradation
  externe — cohérent avec la pastille colorée du dessin (cf. piège
  « Pastille du sondage = PRBS ajustée » dans la section **Pièges
  connus**).
- `export_prbs_xlsx(arbre, chantier, path, couleur_classe,
  classer_prbs)` — fichier Excel stylé. Nécessite openpyxl (dégradé
  proprement avec `RuntimeError` clair sinon — `HAS_OPENPYXL` flag).
  Colonne « Compartimentation » : glyphe ✓ vert si active, ✗ rouge si
  absente, — gris sinon. Colonne « Proportion de bois sain sur le
  rayon (%) » (= t/R) : fond coloré par classe.
- `export_prbs_html(arbre, chantier, path, couleur_classe,
  classer_prbs)` — fichier HTML autonome (CSS embarqué, imprimable
  en PDF via le navigateur). Aucune dépendance.

`couleur_classe` (le dict `COULEUR_CLASSE`) est injecté depuis l'UI
pour ne pas créer de cycle d'import (export.py n'importe pas
penetrometre.py). Les arbres et chantiers sont reçus en duck-typing.

### `model.py` — dataclasses + logique métier

Module sans dépendance Tk ni PIL (stdlib + `geometry`), couvert par
les tests :

- `Sondage` — une mesure ponctuelle dans une direction.
- `DegradationExterne` — un arc d'écorce dégradée.
- `Contrefort` — empattement à la base (cloche cosinus²).
- `Arbre` — sondages, dégradations, contreforts. Méthodes calculées
  **pures** (aucune ne mute l'arbre) :
  - `compute_alteration_par_grade()` — extrapolation par moyenne
    pondérée linéaire entre voisins. **Unique** point d'accès à
    l'altération extrapolée : pas de cache stocké sur l'arbre. Les
    appelants (renderers, exports, diagnostic) stockent le résultat
    dans une variable locale au moment où ils en ont besoin.
    Verrouillé par `test_arbre_n_expose_plus_de_cache_alteration`.
  - `prbs_par_grade()`, `ratio_tR_par_grade()`,
    `repartition_classes()` — composent par-dessus
    `compute_alteration_par_grade()` + `degradation_externe_par_grade()`.
    `repartition_classes()` renvoie un **`DiagnosticSnapshot`** (et non
    un dict) : dataclass typée qui porte la répartition par classe
    (`vert`/`orange`/`rouge` : `ClasseRepartition(n, grades, pct)`),
    les ratios bruts, la direction critique, le t/R moyen, la classe
    globale, et l'état de fiabilité (`n_sondees`, `diagnostic_fiable`,
    `extrapolation_text`). Verrouillé par `RepartitionClassesTests`.
    Le snapshot est **self-contained** : il porte `ratios` (les 16
    t/R) et `extrapolation_text` (phrase de fiabilité) pour que les
    callers (`diagnostic_summary_lines`, fiche PDF, XLSX, HTML) n'aient
    pas à rappeler `ratio_tR_par_grade()` ni
    `extrapolation_summary_text()` derrière — sinon on rejoue la
    chaîne `compute_alteration_par_grade` une seconde fois pour rien.
    Pour itérer par label (Vert/Orange/Rouge), utiliser
    `snap.par_classe(cls)` plutôt que les attributs directs — ça permet
    de garder les boucles `for cls in (...)` héritées du code dict.
    `diagnostic_fiable` est `True` dès `n_sondees >= 2` : les exports
    XLSX/HTML/PDF affichent un avertissement plutôt qu'un t/R moyen
    trompeur si `False`. **Tous les exports doivent passer par la
    propriété `snap.diagnostic_global`** qui renvoie
    `Optional[Tuple[float, str]]` (`(tR_moyen, classe_globale)` ou
    `None`) — un seul point d'entrée pour la règle de publication, au
    lieu de tester `diagnostic_fiable` puis de lire les champs à la
    main. Verrouillé par `test_diagnostic_global_*`.
    `ratio_tR_par_grade()` clampe explicitement à `[0, 1]` (alignement
    sur `Sondage.ratio_tR_brut`).
  - `set_rayon(new_R)` — **mutateur unique** pour changer le rayon
    en conservant la PRBS (règle métier : « PRBS invariante,
    `bois_altere` s'ajuste »). Synchronise aussi
    `degradations_externes[i].profondeur_cm <= R`. Renvoie `True` si
    le rayon a effectivement changé (l'UI doit alors rafraîchir
    tables sondages, dégradations et contreforts). L'UI passe par ce
    mutateur — ne jamais muter `rayon_tronc_cm` directement.
    Verrouillé par `SetRayonTests` (9 tests).
  - `renumeroter_sondages()` / `renumeroter_degradations()` /
    `renumeroter_contreforts()` — mutateurs explicites appelés après
    ajout/suppression depuis l'UI pour recoller les numéros 1..N.
- `Chantier` — pure dataclass : nom, adresse, opérateur, date, et
  liste d'arbres. La persistance JSON (chargement, sauvegarde,
  migration) vit dans **`persistence.py`** pour garder le modèle métier
  focalisé sur ses dataclasses et sa logique d'extrapolation.

### `persistence.py` — I/O JSON des missions

- `chantier_to_dict(chantier)` / `chantier_from_dict(d)` —
  sérialisation symétrique. `chantier_to_dict` écrit
  `format_version: FORMAT_VERSION` ; `chantier_from_dict` tolère son
  absence (anciens fichiers) **et** log un WARNING (sans bloquer) si
  le fichier est d'un format plus récent que celui que l'app sait
  lire — les champs inconnus sont alors ignorés silencieusement par
  le filtre `__dataclass_fields__`.
- `save_chantier(chantier, path)` / `load_chantier(path)` — wrappers
  fichier indenté UTF-8.
- Migration ascendante : `chantier_from_dict` mappe les anciens
  libellés de port (v3.1 → v3.2) et retombe sur `"libre"` si le port
  est inconnu (faute de frappe dans un JSON édité à la main).
- Migration descendante : filtre chaque dict d'entrée par
  `Class.__dataclass_fields__` avant `Class(**kwargs)` à tous les
  niveaux (`Arbre`, `Sondage`, `DegradationExterne`, `Contrefort`).

### `pane_*.py` — onglets autonomes (Identification, Sondages, Dégrad., Contreforts, Diagnostic)

Cinq widgets Tk indépendants. Chaque pane :

- hérite de `ttk.Frame`, est ajouté au `ttk.Notebook` de l'`App` ;
- **possède** ses propres widgets (`StringVar`, `Treeview`, boutons) ;
- expose une méthode `refresh()` (ou `load_from_arbre()` pour
  l'Identification) appelée par l'App quand l'arbre courant change
  ou après un redraw debounce ;
- déclare en tête du module un `Protocol` (`_*Host`) qui formalise la
  surface attendue de l'App — typiquement `_current_arbre()` +
  un callback `_debounced_redraw()` ou `on_*_changed(...)`.

Tables `Treeview` (Sondages, Dégradations, Contreforts) : le pane
inclut son propre cycle add/edit/del (boutons + double-clic → dialogue
de `dialogs.py` → renumérotation → refresh → debounced redraw via le
host). Plus de `app_actions.py` séparé.

`IdentificationPane` est le plus chargé : il porte les 10 `StringVar`,
la règle de cohérence Ø ↔ Rayon (`Arbre.set_rayon`), un
`_suspend_sync` interne pour les chargements, et notifie l'App via
`on_identification_changed(rayon_adjusted=...)` qui cascade le refresh
des autres panes si le rayon a bougé.

`DiagnosticPane` enveloppe son contenu dans un sous-`tk.Canvas`
scrollable verticalement (5 boutons d'export, résumé textuel,
checkbox `show_sondages`, table PRBS 16 directions). Les bindings
molette sont locaux (`<Enter>`/`<Leave>`) — ils n'interfèrent pas avec
le scroll des autres onglets.

### `app_exports.py` — actions d'export Tk

Adaptateur Tk pour les 5 actions d'export utilisateur (PNG, PDF, CSV
mission, XLSX, HTML). Chaque fonction :
- vérifie les prérequis (`HAS_PIL`, `HAS_OPENPYXL`) avec un
  `messagebox.showinfo` clair si manquant ;
- gère le `filedialog` (nom suggéré + filtres) ;
- entoure l'écriture d'un `try/except` qui logge via
  `log.exception(...)` et notifie via `messagebox.showerror`.

`App.action_export_*` sont des thin wrappers d'une ligne qui passent
`self._current_arbre()` / `self.chantier` aux fonctions du module.
Aucune dépendance vers `penetrometre.py` (pas de cycle).

### `palette.py` — couleurs partagées Tk ↔ PIL

Petit module sans logique : centralise les `COLOR_*` (panneaux,
bois, écorce, cernes, dégradation, sondage) et le dict
`COULEUR_CLASSE` (label → hex). Importé à la fois par
`penetrometre.py` (Tk) et `pil_render.py` (PIL). Sans ce module
intermédiaire, les deux auraient un cycle d'import.

### `pil_render.py` — rendu PNG + fiche PDF A4

- `render_arbre_to_pil_image(arbre, …)` — section transversale
  identique à celle du `SectionCanvas` Tk, mais sur une `PIL.Image`.
  Orchestrateur d'une 70aine de lignes qui enchaîne les helpers
  `_pil_draw_*` (un par couche logique : bois sain, cernes, cavité,
  écorce, contreforts, dégradations, ticks, lettres cardinales,
  sondages, règle, titre). Structure symétrique aux `_draw_*` de
  `SectionCanvas` : modifier le helper concerné, pas l'orchestrateur.
- `render_fiche_arbre_to_pdf_page(arbre, chantier)` — page A4
  150 DPI complète : en-tête mission + logo, identité de l'arbre,
  dessin, légende horizontale, tableau PRBS ajustée, diagnostic.
- Helpers : `_pil_load_fonts()` (multi-OS avec fallback),
  `_fit_text()` (troncature ellipsis), `_draw_horizontal_legend_pil()`.
- `HAS_PIL` exposé : `False` si Pillow absent ; les actions d'export
  côté UI affichent alors un message clair et n'appellent pas le
  rendu.

**Tkinter (`section_canvas.SectionCanvas`) et PIL partagent les
primitives géométriques** définies dans `geometry.py` (`polar_to_xy`,
`cavity_polygon`, `contrefort_zone_outline`,
`degradation_externe_outline`). La géométrie ne peut donc plus
diverger entre les deux moteurs. Restent spécifiques à chaque
renderer : la typographie, l'API de dessin (`Canvas.create_*` vs
`d.polygon/ellipse/line`), la couche d'écorce (cf. piège
`outline+width` ci-dessous), et tout ce qui est purement
présentation (échelle, lettres cardinales, règle graduée).

### `dialogs.py` — boîtes de dialogue Tk

Trois fonctions de niveau module, indépendantes de la classe `App` :
`edit_sondage`, `edit_degradation`, `edit_contrefort`. Chacune reçoit
`(parent, arbre, obj)`, **mute l'objet métier en place** et renvoie
`True/False` selon validation/annulation. Aucun cycle d'import avec
`penetrometre.py` : ce module ne dépend que de `geometry`, `model`,
`palette`. Helpers internes : `_grade_choices`, `_parse_grade`,
`_round_to_25` (factorisation des liens automatiques largeur ↔ grade,
bois sain ↔ altéré).

### `section_canvas.py` — rendu Tkinter de la section

- `class SectionCanvas(tk.Canvas)` : dessine la section transversale
  en temps réel dans la fenêtre. `redraw()` est un orchestrateur d'une
  quarantaine de lignes qui enchaîne les helpers `_draw_*` (un par
  couche logique : bois sain, cernes, cavité, écorce, contreforts,
  dégradations, ticks, lettres cardinales, sondages, règle graduée,
  titre). L'ordre d'appel dans `redraw` est l'ordre de superposition
  (cf. « Ordre global des couches » plus bas).
- Pendant non-PIL de `pil_render.render_arbre_to_pil_image` :
  géométrie partagée via `geometry.py`, seuls subsistent ici les
  paramètres visuels propres à Tk (polices, `outline+width` semantics,
  splines `smooth=True`, flèches natives de `create_line`). Toute
  modification d'une couche se fait dans LES DEUX fichiers
  (cf. tableau « Pendants Tk ↔ PIL »).

### `penetrometre.py` — application Tk + main

Organisé en deux sections séparées par des bandeaux de commentaires :

1. **Imports + logger applicatif** (`logging.getLogger("penetrometre")`).
2. **Application** — `class App(tk.Tk)` : fenêtre principale, layout
   3 colonnes, liste d'arbres, instanciation des panes, callbacks
   communs (cascade quand le rayon change, toggle show_sondages,
   maj de la ligne de tree_arbres), actions Fichier (new/open/save/
   save_as) et export CSV mission. Délégations :
   - onglets (Identification / Sondages / Dégradations / Contreforts /
     Diagnostic) → `pane_*.py` (chaque pane possède ses widgets et
     ses actions add/edit/del).
   - dialogues d'ajout/édition → `dialogs.py` (appelés par les panes).
   - actions d'export (PNG/PDF/CSV/XLSX/HTML) → `app_exports.py`,
     déclenchées soit par le `DiagnosticPane`, soit par la barre de
     menu (`app_menu.py`).
   - persistance JSON (open/save) → `load_chantier` /
     `save_chantier` dans `persistence.py`.
   - renumérotation 1..N après ajout/suppression →
     `Arbre.renumeroter_*()` (appelée par les panes).
3. **`main()`** — configure `_setup_logging()` puis lance
   `App().mainloop()`. Le logger écrit dans
   `~/.penetrometre/penetrometre.log` (RotatingFileHandler), ce qui
   rend les exceptions visibles même en double-clic Windows. Toutes
   les actions d'export catchent leurs exceptions avec
   `log.exception(...)` avant le `messagebox.showerror`
   (dans `app_exports.py`).

## Conventions métier importantes

- **Grades** : 0 à 375 par pas de 25 (16 directions). 0 = Nord, sens
  horaire. **Pas de symbole `°`** — afficher `100 gr` (gradian).
- **PRBS** = Paroi Résiduelle de Bois Sain = épaisseur de bois sain
  mesurée par le foret. C'est la mesure invariante (physique) — quand
  le rayon change, la PRBS reste, c'est `bois_altéré` qui s'ajuste.
- **t/R** = PRBS / Rayon, ratio entre 0 et 1.
- **Classe globale** = barème Silvavenir appliqué au **t/R moyen** sur
  les 16 directions (pas au minimum, ni au pourcentage de directions).
- **Diagnostic non fiable si n_sondages < 2** : avec 0 ou 1 sondage,
  l'extrapolation par voisins n'a pas de sens (toutes les 16 directions
  héritent de la même valeur), ce qui donne un t/R moyen trompeur. Dans
  ce cas `repartition_classes()` met `diagnostic_fiable=False` et les
  exports (PDF, XLSX, HTML) **n'affichent pas** de t/R moyen ni de
  classe globale — un avertissement explicite remplace ces champs.
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
- **Règle graduée** sous la section : **demi-règle asymétrique**, `0`
  au centre de l'arbre, graduation seulement vers la droite jusqu'à
  `R` (bord du bois). La portion bois est en trait noir fin ; la barre
  écorce (si `ep > 0`) prolonge la règle jusqu'à `R+ep`, **sans label
  numérique** (l'épaisseur d'écorce reste lisible dans l'onglet
  Diagnostic). Le pas de graduation est calculé par
  `geometry.adaptive_ruler_step_cm(scale, min_gap_px)` pour que deux
  étiquettes consécutives soient toujours séparées d'au moins
  `min_gap_px` pixels — empêche les nombres de se chevaucher sur les
  gros troncs.
- **Couleurs `BARK` et `ROT` distinctes** : `COLOR_BARK = #5C3A1E`
  (écorce intacte) ≠ `COLOR_ROT = #140804` (quasi-noir chaud). Le
  contraste est volontairement fort : la « plaie » d'une dégradation
  doit être lisible quand elle traverse l'écorce. **Ne jamais
  réunifier les deux couleurs** — la légende des exports les présente
  comme deux entrées distinctes (« Bois dégradé » vs « Écorce »).

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

- Ascendante : migration silencieuse dans `chantier_from_dict`
  (`persistence.py` — par ex. mapping des anciens libellés de port
  `"Libre, semi-libre ou traumatique"` → `"libre"`). **Ne jamais
  casser cette compat sans ajouter une migration.**
- Descendante : `chantier_from_dict` filtre chaque dict d'entrée par
  `Class.__dataclass_fields__` avant `Class(**kwargs)`. Les clés JSON
  inconnues sont ignorées silencieusement à tous les niveaux
  (`Chantier`, `Arbre`, `Sondage`, `DegradationExterne`, `Contrefort`).
  Verrouillé par `test_champs_inconnus_ignores`.

## Commandes utiles

```bash
# Vérifier la syntaxe avant commit
python -c "import ast; ast.parse(open('penetrometre.py').read())"

# Lancer l'app
python penetrometre.py

# Lancer la suite de tests (stdlib unittest, aucune dépendance)
python -m unittest discover tests

# Lint + vérif de types (nécessite `pip install -r requirements-dev.txt`).
# Ruff couvre tous les .py ; mypy ne vérifie que le cœur métier + le
# rendu PIL — la config par-module dans `mypy.ini` est en mode strict
# pour ces 7 fichiers (bareme, geometry, palette, model, persistence,
# export, pil_render). Toute évolution du modèle / barème / géométrie /
# rendu PNG-PDF doit laisser mypy vert.
ruff check .
python -m mypy bareme.py geometry.py palette.py model.py persistence.py export.py pil_render.py
```

La suite couvre les fonctions pures à risque métier : barème
`classer_prbs`, géométrie des contreforts (`bell_max_at_grade`,
`contrefort_zones`), primitives de rendu partagées Tk↔PIL
(`polar_to_xy`, `cavity_polygon`, `contrefort_zone_outline`,
`degradation_externe_outline`), extrapolation de l'altération,
calcul PRBS, migration JSON et données du tableau exporté
(`prbs_table_rows_par_sondage`). Un smoke test XLSX est exécuté si openpyxl est
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
  puis `classer_prbs(prbs_adj / R, port)`. `Sondage.ratio_tR_brut(R)`
  est volontairement nommé « brut » : il ignore la dégradation externe
  et n'est utilisé QUE par la colonne « t/R brut » du CSV mission
  (compat ré-analyses Excel existantes). Pour toute logique de
  diagnostic, c'est `Arbre.ratio_tR_par_grade()` qui fait foi.
- **Pas de cache `alteration_par_grade` sur `Arbre`.** L'altération
  extrapolée se calcule uniquement par `compute_alteration_par_grade()`
  (pure). Le champ dataclass et le mutateur `recompute_...` ont été
  retirés pour fermer la classe de bugs « cache périmé avant dessin ».
  Verrou : `test_arbre_n_expose_plus_de_cache_alteration` (vérifie
  l'absence du champ ET du mutateur).

## Quand tu modifies l'app

1. **Avant** de toucher au code : repérer le bon module en fonction de
   la nature du changement.
   - **Barème métier** (`classer_prbs`, ports, classes) → `bareme.py`.
   - **Géométrie pure** (spline, contreforts, primitives polaires) →
     `geometry.py`.
   - **Modèle** (dataclasses, extrapolation, calcul PRBS, migration
     JSON) → `model.py`.
   - **Rendu PNG/PDF** → `pil_render.py`.
   - **Couleurs partagées Tk/PIL** → `palette.py`.
   - **Exports tableau** (XLSX/HTML) → `export.py`.
   - **Dialogues Tk** (Sondage, Dégradation, Contrefort) → `dialogs.py`.
   - **Onglet** (widgets, refresh, actions add/edit/del) → le
     `pane_*.py` correspondant. C'est presque toujours le bon endroit
     pour un changement d'UI métier (table, boutons, sync UI ↔ modèle).
   - **Actions d'export** (PNG/PDF/CSV/XLSX/HTML) → `app_exports.py`.
   - **Rendu Tk de la section transversale** (cavité, contreforts,
     règle, pastilles…) → `section_canvas.py`.
   - **UI Tk hors onglet + orchestration** → `penetrometre.py`
     (`App`, callbacks `on_*_changed`).
2. **Géométrie partagée** : si tu changes la géométrie d'un élément
   (cavité, contreforts, dégradation), modifie `geometry.py` une fois ;
   les deux renderers Tk et PIL héritent automatiquement. Pour les
   aspects spécifiques à un renderer (couleurs, traits, écorce,
   typographie, règle graduée, lettres cardinales), modifie côté Tk
   **et** côté PIL.
3. Pour les changements de modèle : penser à la migration JSON
   (`persistence.chantier_from_dict`). Si tu **ajoutes** un champ
   dataclass, les
   anciens JSON le verront avec sa valeur par défaut (OK). Si tu
   **renommes** ou **supprimes** un champ, ajouter une migration
   ascendante explicite.
4. **Lancer la suite de tests** (`python -m unittest discover tests`,
   137 tests) avant tout commit qui touche au modèle, à la géométrie
   ou aux exports. Deux familles de golden-tests :
   - **PIL** (`tests/test_render.py`, 4 scénarios) — régénération :
     `python -m tests.test_render --update` (commit les `.png`).
   - **Tk** (`tests/test_section_canvas.py`, 4 scénarios) — régénération :
     `xvfb-run -a python -m tests.test_section_canvas --update` en CI,
     ou `python -m tests.test_section_canvas --update` avec X local
     (commit les `.json`). Skipped silencieusement si `DISPLAY`
     indisponible (CI sans Xvfb, SSH sans X11).
   Les scénarios sont définis une seule fois dans `tests/_fixtures.py`
   (`build_arbre(scenario)` + `SCENARIOS`).
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

## Pendants Tk ↔ PIL (helpers de rendu)

Chaque couche de la section transversale a deux implémentations
parallèles, une par moteur, à modifier ensemble. Le tableau ci-dessous
est la source de vérité (rappelé en commentaire au-dessus des deux
blocs de helpers).

| Couche               | Tk (`SectionCanvas`)                  | PIL (`pil_render`)         |
|----------------------|---------------------------------------|----------------------------|
| placeholder          | `_draw_placeholder`                   | `_pil_draw_placeholder`    |
| bois sain            | `_draw_bois_sain`                     | `_pil_draw_bois_sain`      |
| cernes               | `_draw_cernes`                        | `_pil_draw_cernes`         |
| cavité d'altération  | `_draw_cavite`                        | `_pil_draw_cavite`         |
| écorce               | `_draw_ecorce`                        | `_pil_draw_ecorce`         |
| contreforts          | `_draw_contreforts_canvas`            | `_pil_draw_contreforts`    |
| dégradations ext.    | `_draw_degradation_externe_canvas`    | `_pil_draw_degradations`   |
| ticks 16 grades      | `_draw_ticks`                         | `_pil_draw_ticks`          |
| lettres cardinales   | `_draw_cardinales`                    | `_pil_draw_cardinales`     |
| sondages (flèches+pastilles) | `_draw_sondages`              | `_pil_draw_sondages`       |
| règle graduée        | `_draw_regle`                         | `_pil_draw_regle`          |
| titre + méta         | `_draw_titre`                         | `_pil_draw_titre`          |

Géométrie : partagée via `geometry.py` (`polar_to_xy`, `cavity_polygon`,
`contrefort_zone_outline`, `degradation_externe_outline`). Constantes
de layout (marges, offsets en px, nombre de cernes, échantillonnage du
spline) : tunées indépendamment côté Tk (`SectionCanvas.*_PX`,
`N_CERNES`, …) et côté PIL (constantes module-level), car les
moteurs de dessin diffèrent (hinting, épaisseurs de trait, semantics
d'`outline+width` sur ellipse).

Cf. aussi le piège « différence Tkinter ↔ PIL pour `outline + width`
sur ellipse » dans la section **Pièges connus** ci-dessous.

## Limites connues (non corrigées)

- **Duplication de rendu Tk ↔ PIL au-delà de la géométrie**.
  `geometry.py` partage les primitives polaires et les contours
  (cavité, contreforts, dégradations). Restent dupliqués entre Tk
  (helpers `SectionCanvas._draw_*`) et PIL (helpers `_pil_draw_*` de
  `pil_render.py`) : l'écorce/anneau, les cernes, la règle graduée,
  les pastilles, les ticks et lettres cardinales — chacun avec ses
  paramètres en pixels spécifiques (`outline+width`, anchors, polices).
  Les deux jeux de helpers sont **symétriques par nom** (`_draw_ticks`
  ↔ `_pil_draw_ticks`, etc.) : toute modif visuelle se fait sur le
  helper concerné dans LES DEUX fichiers.
- **Couverture visuelle des deux moteurs** : depuis l'ajout de
  `tests/test_section_canvas.py`, le rendu Tk a son propre jeu de
  golden-fixtures (dump JSON des items du Canvas, pas un screenshot).
  Une régression purement Tk (palette, marge spécifique, item oublié
  après refactor des `_build_*`) sera détectée par la CI sous Xvfb.
  Limite résiduelle : le diff porte sur la structure du Canvas, pas
  sur le rendu glyph par glyph — un changement de police système ne
  fait pas régresser le test (et c'est ce qu'on veut).
