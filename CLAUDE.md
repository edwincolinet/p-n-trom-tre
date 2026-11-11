# Pénétromètre Silvavenir

Application desktop d'expertise arboricole (mesure de cavités dans les
troncs au pénétromètre). Logiciel d'Edwin Colinet.

## Stack

- **Python 3.10+** (3.13 recommandé), **Tkinter** (UI stdlib), **Pillow** (PNG/PDF)
- Aucun framework ; pas de build pour le **développement** (lancement par
  double-clic). **Empaquetage distribution** : PyInstaller (`penetrometre.spec`,
  installeurs Win/macOS/Linux via `.github/workflows/build.yml` sur tag `v*`)
  **ou** Nuitka (binaire compilé, `build/build_nuitka.py` — plus dur à
  décompiler).
- Dépendance optionnelle : openpyxl (export XLSX).
- Dépendance runtime : **fpdf2**
  (fiche d'expertise PDF **vectorielle** — texte sélectionnable, net au zoom,
  fichier ~3-4× plus léger ; cf. `fiche_pdf.py`).
- **Outillage dev** (`requirements-dev.txt`, versions **épinglées** pour ruff
  et Pillow → CI reproductible) : ruff (lint), mypy (types), pytest (runner de
  la suite) + hypothesis (property-tests, `tests/test_properties.py`), Nuitka,
  pyinstaller.

## Structure

```text
penetrometre.py        ← App Tk + main — orchestration
app_arbres.py          ← ArbreListMixin (liste d'arbres : filtre, état, CRUD)
app_recovery.py        ← RecoveryMixin (autosave anti-crash + récupération)
app_export_actions.py  ← ExportActionsMixin (les action_export_*)
app_fichier.py         ← FichierMixin (cycle de vie fichier mission : new/open/save/save_as + récents + ré-inspection)
app_layout.py          ← LayoutMixin (construction de l'UI : header, méta mission, barre d'état + bannières, 3 colonnes, sash)
app_reglages.py        ← ReglagesMixin (préférences : langue, barème, taille texte, contraste, logo/cabinet + mises à jour/bannières)
app_recent.py          ← RecentFilesStore (historique fichiers récents, pur)
app_settings.py        ← SettingsStore (réglages UI persistés : ui_scale, pur)
ui_fonts.py            ← échelle des polices + typographie/espacements nommés (design system, pur)
icons.py               ← glyphes d'icônes du chrome Tk, monochromes (design system, pur)
chrome_icons.py        ← icônes bitmap (PIL→PhotoImage) de secours Windows pour calendrier/Enregistrer
photo_paths.py         ← résolution CONFINÉE des chemins de photos (jail mission + whitelist, pur)
angle_units.py         ← unité d'affichage des angles grades/degrés (pur ; le modèle reste en grades)
section_canvas.py      ← SectionCanvas (rendu Tk section)
pane_identification.py ← onglet Identification
pane_sondages.py       ← onglet Sondages
pane_degradations.py   ← onglet Dégradations externes
pane_contreforts.py    ← onglet Contreforts
pane_diagnostic.py     ← onglet Diagnostic (résumé + tableau PRBS + préconisation)
comparaison.py         ← fenêtre de comparaison inter-missions (ré-inspection)
comparaison_render.py  ← rendu PIL de la comparaison (section d'évolution + page export PNG/PDF)
app_exports.py         ← actions d'export (adaptateur Tk, fonctions pures)
app_menu.py            ← barre de menu Tk
app_style.py           ← thème ttk
dialogs.py             ← primitives Tk génériques (ask_string/choice/date, ProgressDialog) + _make_modal
dialogs_saisie.py      ← dialogues d'édition détaillée (Sondage, Dégradation, Contrefort)
dialogs_cepee.py       ← éditeur de disposition d'une cépée (ask_cepee_layout, souris)
model.py               ← dataclasses + mutateurs + validation. Arbre (genet) = conteneur de Brin (ramet) ≥1
diagnostic.py          ← fonctions pures de diagnostic + sondage_render_data
diagnostic_comparaison.py ← comparaison inter-missions (ré-inspection), fonctions pures
persistence.py         ← I/O JSON (save/load + migration ; v3 = brins ; `file_stamp` = garde-fou multi-poste)
profil_cabinet.py      ← profil cabinet appliqué au 1er lancement (nom, logo, barème, dossier MàJ ; pur)
geometry.py            ← briques géométriques pures (spline, polaire, cernes, ellipse)
bareme.py              ← barème métier (classer_prbs, ports)
pil_render.py          ← rendu PNG de la section transversale
fiche_pdf.py           ← fiche expertise PDF A4 VECTORIELLE (fpdf2 ; dessin de section collé en raster)
palette.py             ← couleurs partagées Tk ↔ PIL
export.py              ← exports XLSX/HTML tableau PRBS d'un arbre
export_synthesis.py    ← synthèse mission (une ligne par arbre, XLSX/CSV)
undo.py                ← pile undo/redo (Ctrl+Z / Ctrl+Y, 50 snapshots)
tooltip.py             ← infobulle Tk légère (survol), n'importe quel widget
aide_repliable.py      ← widget d'aide repliable (ⓘ Aide ▸/▾), réutilisable
tests/                 ← suite de tests (intégration, golden PIL + Tk, undo, persistence, App + mixins, ellipse, cépées)
```

**`App` = orchestration + 6 mixins + 1 helper.** C'est un
**partitionnement par responsabilité** (navigabilité, localité git-blame),
**pas une décomposition** : sauf `ExportActionsMixin`, les mixins lisent et
**mutent** l'état d'`App` (`chantier`, `current_idx`, `current_file`,
`_dirty`, …) et s'appellent même entre eux (`RecoveryMixin` invoque
`_refresh_tree_arbres` d'`ArbreListMixin`). Ça reste **un seul objet réparti
sur 6 fichiers**, avec un couplage total **assumé** — intrinsèque à une UI
maître-détail où sélectionner un arbre recharge tout le panneau de droite
(le « découpler » ne ferait que déplacer ce couplage dans une interface de
callbacks, pour un gain net faible). Découpage :

- `ArbreListMixin` (panneau gauche) — mute `current_idx`, `chantier.arbres`.
- `RecoveryMixin` (autosave/récupération) — réassigne l'état de session.
- `ExportActionsMixin` (les `action_export_*`, appelées par nom depuis
  `app_menu` → doivent rester des méthodes de `App`) : pur dispatcher
  en lecture seule, le seul mixin réellement découplé.
- `FichierMixin` (cycle de vie du fichier mission : `action_new`/`_open`/
  `_save`/`_save_as`, `_open_path`, récents, + ré-inspection
  `action_load_reference`/`_compare_arbre`/`_export_comparison`) — mute
  `chantier`, `current_file`, `_dirty`, `_reference_chantier` ; porte la
  constante `_BACKUP_PATH` (réimportée par `penetrometre` pour le menu).
- `LayoutMixin` (fabrique de widgets : `_build_layout`/`_build_left`/
  `_build_center`/`_build_right`/`_build_statusbar` + sash). Quasi-pur
  *builder* : il **crée et assigne** la plupart des attributs UI d'`App`
  (`tree_arbres`, `nb`, `section`, `var_*`, les 5 panes…) que
  l'orchestrateur lit/mute ensuite. Les panes/`SectionCanvas` attendent un
  `host` satisfaisant leur Protocol (toute la surface d'`App`) → `host=self`
  passe par un `cast("App", self)` (no-op runtime, l'objet EST l'App).
- `ReglagesMixin` (préférences + mises à jour : `action_set_language`/
  `_set_ui_scale`/`_set_high_contrast`/`_bareme_settings`/`_cabinet_settings`,
  `_apply_ui_scale`/`_apply_styles`/`_apply_bareme` appelés au démarrage, le
  cycle de vérification de version + bannière, `action_restart`). Lit/mute
  `_settings`, le `_logo_frame` et les bannières construites par
  `LayoutMixin`. `__version__` reste dans `penetrometre` (import local lazy
  pour éviter le cycle).
- `RecentFilesStore` (composition, pur).

`App` garde le câblage des évènements (binds clavier, menu, undo/redo), la
synchro modèle, le debounce de redraw, les réglages/màj et les callbacks de
saisie (le cycle de vie fichier est passé à `FichierMixin`, la construction
de l'UI à `LayoutMixin`). Les mixins dérivent de `tk.Tk` **uniquement sous
`TYPE_CHECKING`** (`_MixinBase`) — `object` au runtime — pour que mypy
voie `self` comme un widget sans problème de MRO ; les attributs/méthodes
d'`App` requis sont déclarés dans un bloc `TYPE_CHECKING`. **Ces blocs
documentent la surface de couplage (greppable) mais ne l'encapsulent pas**
— au runtime un mixin peut toucher n'importe quel attribut d'`App`.
**Garde-fous** : mypy refuse tout accès *non déclaré* ; l'inverse (déclaré
mais plus fourni par `App`, que mypy ne voit pas puisque `App` hérite des
déclarations) est couvert par `tests/test_surfaces_mixins.py`, qui compare
chaque bloc `TYPE_CHECKING` à une `App` réellement instanciée (existence +
arité). **Ajouter une dépendance à un mixin = la déclarer dans son bloc.**

**Graphe de dépendances** (chaque module importe uniquement vers le bas) :

```text
geometry.py + bareme.py   (stdlib)
   ↑
model.py + palette.py + angle_units.py + tooltip.py + aide_repliable.py + app_recent.py + app_settings.py + ui_fonts.py + icons.py + chrome_icons.py + photo_paths.py
   ↑
diagnostic.py
   ↑
export.py + pil_render.py + persistence.py + dialogs.py + diagnostic_comparaison.py
   ↑
dialogs_cepee.py + dialogs_saisie.py (dépendent aussi de dialogs.py, même palier)
   +  export_synthesis.py (dépend aussi de export.py — ChantierLike, _defuse)
   ↑
fiche_pdf.py + comparaison_render.py
   ↑
section_canvas.py + pane_*.py + comparaison.py + app_exports.py + app_menu.py + app_style.py
   ↑
app_arbres.py + app_recovery.py + app_export_actions.py + app_fichier.py + app_layout.py + app_reglages.py  (mixins de App)
   ↑
penetrometre.py  (Tk + main) ← undo.py
```

## Conventions métier

> Règles essentielles. Le « pourquoi », les dates et les pièges corrigés :
> `.claude/docs/conventions-metier.md` (à lire avant de toucher au barème,
> aux dégradations, aux cépées ou au diamètre local).

- **Grades** : 0 à 375 par pas de 25 (16 directions), 0 = Nord, sens horaire.
  **Le modèle, les fichiers et le diagnostic restent TOUJOURS en grades** ;
  l'option Affichage → *Unité des angles* (Grades/Degrés, `SettingsStore.angle_unit`)
  ne change que l'affichage, la saisie et les exports. Source unique
  `angle_units.py` : toute chaîne d'angle passe par `fmt`/`nombre`/`valeur`/
  `suffixe`/`titre_colonne` (**jamais de « gr » en dur**), toute saisie par
  `angle_units.parse`/`depuis_unite`. Piège : `_(variable)` est invisible au
  test d'i18n → vérifier à la main.
- **PRBS** = Paroi Résiduelle de Bois Sain (mesure physique invariante) : si le
  rayon change, la PRBS reste, `bois_altéré` s'ajuste.
- **t/R** = PRBS / Rayon **local** (0–1). **Chaque direction** est classée
  Vert/Orange/Rouge par le barème ; la **classe mise en avant** est celle du
  **t/R minimal** des 16 directions (la rupture part de la paroi la plus
  mince). **Aucun t/R moyen** n'est calculé ni publié. `classe_globale` reste
  le nom du champ (cépée : pire brin fiable).
- **Genet / brin** : `Arbre` (genet) porte l'identité partagée (n°, essence,
  port, hauteurs, mèche, préconisation) + ≥ 1 `Brin` (ramet) qui porte
  géométrie et mesures (rayon, sondages, dégradations, contreforts, position).
  Des propriétés-relais sur `Arbre` (→ `brins[0]`) gardent le code mono-caule.
  Cépée : `ajouter_brin`/`supprimer_brin`, rendu par `geometry.brins_layout`
  (mono-brin = chemin verbatim → goldens intacts), **une échelle radiale par
  brin**, diagnostic `genet_diagnostic` = **pire classe parmi les brins fiables**
  (rayon + ≥ 3 sondages). Brin courant : `App._current_brin()` ; les onglets
  Sondages/Dégradations/Contreforts et la géométrie d'Identification éditent le
  brin courant, l'identité reste genet. Rotation d'un brin = purement visuelle
  (le diagnostic ne change pas). Détail et plan : `.claude/docs/archives/cepees-plan.md`.
- **Diamètre local par direction** : `Brin.diametres_locaux` (grade → Ø cm),
  **indépendant de tout sondage** ; direction absente → diamètre général.
  Source unique `Brin.rayon_a_grade` (interpolation cosinus entre directions
  mesurées, bornée). `Brin.a_rayon_variable` choisit entre primitive cercle
  native et `contour_polygon`. Saisie en ligne dans la grille Sondages via
  `Brin.set_diametre_local` (ne touche jamais la PRBS d'un sondage).
- **Diagnostic non fiable si < 3 sondages** → exports masquent t/R minimal +
  classe. **Couverture angulaire** : ≥ 3 sondages mais un secteur > 180° sans
  sondage → classe publiée + **avertissement non bloquant**
  (`diagnostic.couverture_insuffisante`).
- **Dégradations externes** consomment du bois sain : `PRBS_ajustée = sain −
  profondeur_bois_deg`. **L'écorce n'est jamais du bois sain.**
  `DegradationExterne.comprend_ecorce` (défaut True, sélecteur « Zone dégradée »)
  : True → `profondeur_bois = max(0, profondeur − épaisseur_écorce)` ; False →
  toute la profondeur est du bois perdu (`profondeur_bois_cm(ep)`, pilote calcul
  **et** rendu). La dégradation suit toujours la saillie des contreforts. Le
  sondage mesure la paroi **totale** ; l'app déduit la profondeur. Fusion : le
  cumul est écrêté à 0 (`prbs_par_grade`) et **signalé** par un « ⚠ » ambre
  (`fusion_ecretee_par_grade`/`degradation_ecretee`), jamais silencieux.
- **Pastille sondage = PRBS ajustée** (jamais brute). **Contreforts** = cloche
  cosinus², fusion si adjacents. **Écorce** : R_ext = R + ep, seule incidence
  diagnostic = déduction ci-dessus.
- **COLOR_BARK ≠ COLOR_ROT** : ne jamais unifier.
- **Barème configurable par groupes de ports** (`~/.penetrometre/bareme.json`,
  `bareme.GroupeBareme`) : réglage de **poste** ; un port isolé n'est qu'un
  groupe à un port. `classer_prbs(ratio, port)` ne plante jamais (repli sur
  `GROUPES_DEFAUT`). **Traçabilité** : les groupes en vigueur à l'enregistrement
  sont écrits dans `Chantier.bareme_seuils` et **cités dans chaque livrable** ;
  **ouvrir une mission n'applique JAMAIS son barème** (écart seulement signalé,
  `App._avertir_bareme_different`). Libellés : `bareme.description_seuils*`.
- **Unicité** : un sondage par direction, un contrefort par grade central
  (garanties par construction, grilles 16 directions) ; pas de dégradations qui
  se chevauchent (`model.degradations_chevauchements`).

## Conventions de code

> Règles essentielles. Le « pourquoi », les dates et les pièges corrigés :
> `.claude/docs/conventions-code.md` et `.claude/docs/ui-reference.md`.

- Pas de dépendance sans bonne raison. Compat Python 3.10+. Tout en français
  (UI + docstrings). Pas de `print` : logger applicatif
  (`~/.penetrometre/penetrometre.log`). Exports : `log.exception(...)` avant
  `messagebox.showerror`.
- **Photos = entrée semi-fiable** : toute résolution passe par
  `photo_paths.resolve_photo` (extension whitelist, chemin confiné à la mission,
  absolu toléré mais signalé) ; `photo_gallery._view_photo` vérifie que le fichier
  est décodable comme image. Légende PDF « Photo n », **jamais** le nom de fichier.
- **Journal = artefact de support** (envoyé par le client) : pas d'email en clair,
  pas de chemin complet de mission.
- **Threads et Tk : ne pas mélanger.** Tâches longues découpées en tranches sur
  la boucle Tk (`dialogs.ProgressDialog`, `app_exports.export_pdf_mission`),
  jamais dans un worker (`after()` hors main loop, GC qui abort le process).
  Seule exception : `update_checker`, sans widget.
- **Perf rendu** : `pil_render._pil_font` sous `lru_cache` ; redraw **débouncé**
  partout (`SectionCanvas` 80 ms, `App._debounced_redraw`).
- **Rendu de forme** : les primitives de `geometry` acceptent un `RadiusSpec`
  (scalaire OU `grade→rayon`). **Cas circulaire = primitive native conservée**
  (`d.ellipse`/`create_oval`) sous `if a_rayon_variable` → goldens byte-identiques.
  **Anneaux** (écorce, bande de contrefort) : toujours via
  `geometry.ring_polygon_points`, jamais `outer + inner[::-1]` à la main.
- **Compat fichier** : ajout de champ = OK (défaut) ; renommage/suppression =
  migration explicite dans `persistence.chantier_from_dict`. Format v3 = brins.
  Écriture atomique (`.tmp` + `os.replace`).
- **Sauvegardes glissantes** (`write_backup`, 12 par mission dans
  `~/.penetrometre/backups/`) : best-effort, n'interrompent jamais l'enregistrement.
  **Autosave** (`~/.penetrometre/recovery/autosave.json`, 60 s, si `_dirty`) :
  effacé à tout état propre et à la fermeture normale ⟹ sa présence au démarrage
  = crash avec travail non enregistré.
- **Champs numériques** : `dialogs.validate_numeric` à la frappe, `dialogs.to_float`
  (`2,5` et `2.5`), `_parse_float("")` → `None`. `set_rayon` seulement au
  focus-out. **N° d'arbre** : au moins un chiffre.
- **Compartimentation** : `"active"`/`"absente"`/`"non renseignée"` ; glyphes
  ✓/✗/– source unique dans `dialogs_shared` (`compart_*`), à changer là seulement.
- **Saisie en grilles** (sondages, contreforts) et tableau en place
  (dégradations) : case vide = absent, valeur (même 0) = présent, effacer =
  supprimer **au focus-out** (jamais à la frappe) ; undo capturé au focus-in,
  empilé au focus-out si changé ; callbacks de dégradation par **identité** (`is`).
- **Dialogues modaux** : toujours `dialogs._make_modal(dlg, parent)` APRÈS la
  création des widgets (sinon dialogue vide sous X11). Edition : `<Return>` valide,
  `<Escape>` annule, focus initial sur le 1er champ.
- **ttk** : workaround bpo-36468 (`app_style._fixed_map`) pour que les tags
  `Treeview` colorent les lignes ; contraste des cases à cocher via `s.map`.
- **Liste d'arbres** : État `○ ◐ ●` (≥ 3 sondages), Risque Vert/Orange/Rouge
  (`—` si non fiable), couleur de ligne = classe de risque seule. Filtres cumulés
  (ET) qui ne font que **masquer** (`iid = a{index}` stable, footer sur toute la
  mission). Vert/Orange/Rouge et niveaux d'urgence restent en français partout.
- **Raccourcis** : `Ctrl+T` ajout, `Ctrl+E` export PDF (ignoré si Entry/Combobox
  a le focus), `Ctrl+PgUp/PgDn` arbre précédent/suivant, `Ctrl+Z/Y` undo/redo,
  `Ctrl+Tab` onglets. Menu **Export** = point d'entrée unique des exports.
- **Accessibilité** : `ui_scale` [0.8, 1.6] et `high_contrast` = réglages de poste ;
  le levier est la taille des polices via `ui_fonts.font` (**le dessin n'est PAS
  scalé** — goldens). Point unique `App._apply_styles()`.
- **Fiche PDF vectorielle (fpdf2)** : texte/tableaux/diagnostic en vectoriel,
  dessin de section et légende en raster collé ; unité = 1 px @150 DPI ; **ni ⚠
  ni emoji** (▲). Pas de golden pixel (smoke tests).
- **Exports XLSX ↔ HTML** : garder les deux **alignés** (même contenu, 9 colonnes,
  ligne Diagnostic masquée si < 3 sondées) ; colonne **PRBS = mesure brute**,
  **t/R = ajusté** de la dégradation externe. Parité testée dans
  `tests/test_export.py`.
- **Autres** : comparaison inter-missions (calcul `diagnostic_comparaison`, rendu
  `comparaison_render`, 16 directions sur la PRBS extrapolée, verdict sur le t/R
  minimal) ; case « Afficher sondages » (`var_show_sondages`) gouverne aussi les
  exports ; préconisation = champs genet, **valeur persistée toujours française**
  (`translate_values` / `untranslate_value`) ; synthèse mission =
  `diagnostic.mission_synthesis_rows`. Détail : `ui-reference.md`.

## Commandes utiles

```bash
python3 penetrometre.py                      # Lancer l'app
./run_tests.sh                              # suite complète, Tk inclus (venv + xvfb-run, sinon Xephyr)
venv/bin/python -m pytest tests --ignore=tests/test_app.py --ignore=tests/test_section_canvas.py \
  --ignore=tests/test_export_async.py       # sans affichage (tests Tk exclus)
venv/bin/ruff check .                       # Lint
venv/bin/python -m mypy bareme.py geometry.py palette.py model.py diagnostic.py \
  persistence.py export.py export_synthesis.py diagnostic_comparaison.py pil_render.py fiche_pdf.py app_exports.py app_menu.py \
  app_recent.py app_settings.py ui_fonts.py app_arbres.py app_recovery.py app_export_actions.py app_fichier.py app_layout.py app_reglages.py \
  pane_identification.py pane_sondages.py pane_degradations.py \
  pane_contreforts.py pane_diagnostic.py dialogs.py dialogs_cepee.py dialogs_saisie.py section_canvas.py \
  comparaison.py comparaison_render.py undo.py tooltip.py aide_repliable.py \
  penetrometre.py photo_gallery.py \
  dialogs_settings.py dialogs_shared.py i18n.py bareme_store.py \
  template_store.py update_checker.py profil_cabinet.py photo_paths.py icons.py chrome_icons.py
```

> NB mypy : la liste ci-dessus passe **proprement (exit 0)** sous mypy
> ≥ 1.20. Le bruit « Cannot infer type of lambda » des callbacks Tk
> (`pane_sondages`, `pane_identification`) est neutralisé par module via
> `disable_error_code = misc` dans `mypy.ini` ; le faux positif du
> workaround bpo de `app_style` est réglé par `_fixed_map -> list[Any]`.
> Ne **pas** faire `mypy .` : il agrège les tests (hors périmètre typé).
> S'en tenir à la liste.

Golden-tests :

- PIL : `venv/bin/python -m tests.test_render --update`
- Tk : `xvfb-run -a venv/bin/python -m tests.test_section_canvas --update` (sans Xvfb : `DISPLAY` d'un Xephyr, cf. `run_tests.sh`)

Build / empaquetage (distribution uniquement — le dev tourne sans build) :

- PyInstaller (référence) : `pyinstaller penetrometre.spec` → `dist/Penetrometre/`
  (installeurs Win/macOS/Linux produits par `.github/workflows/build.yml` sur
  tag `v*`).
- Nuitka (binaire compilé, option durcie) : `python3 build/build_nuitka.py` →
  `dist-nuitka/` (compilateur C requis ; réplique le spec).

**Fichiers embarqués (`datas` du spec / `--include-data-*` de Nuitka)** :
`assets/`, `exemples/`, `docs/` (contient `guide_demarrage.html`, ouvert par
`action_open_guide`). Nuitka doit
rester le **miroir exact** des `datas` du spec PyInstaller — toute
modification de l'un doit être reportée sur l'autre.

**Logiciel interne de cabinet** (2026-10-26) : plus de licence, d'essai ni
de contenu de commercialisation (le système de licence Ed25519, la fenêtre
d'activation, `gen_license.py`, la CLU/PRIVACY et le plan commercial ont été
retirés). L'app se lance directement, en développement comme en binaire.

## Quand tu modifies l'app

1. **Repérer le bon module** :
   - Barème métier → `bareme.py`
   - Géométrie pure → `geometry.py`
   - Modèle / mutateurs → `model.py` ; migration JSON → `persistence.py`
   - Diagnostic (calculs purs) → `diagnostic.py` ; comparaison inter-missions
     (ré-inspection) → `diagnostic_comparaison.py`
   - Rendu PNG section → `pil_render.py` ; fiche PDF A4 vectorielle (fpdf2) → `fiche_pdf.py`
   - Couleurs → `palette.py` ; exports tableau PRBS par arbre → `export.py` ;
     synthèse mission (une ligne par arbre) → `export_synthesis.py`
   - Dialogues Tk génériques (ask_string/choice/date, progression) → `dialogs.py` ;
     édition Sondage/Dégradation/Contrefort → `dialogs_saisie.py` ; disposition
     d'une cépée → `dialogs_cepee.py` ; onglet UI → `pane_*.py`
   - Actions export → `app_exports.py` ; rendu Tk section → `section_canvas.py`
   - Liste d'arbres → `app_arbres.py` ; autosave/récup → `app_recovery.py`
   - Méthodes `action_export_*` (dispatch pur) → `app_export_actions.py` ;
     menu Export (entrées groupées par format) → `app_menu.py`
   - Cycle de vie fichier mission (new/open/save/save_as, récents, ré-inspection) → `app_fichier.py`
   - Construction de l'UI (`_build_*`, barre d'état, sash) → `app_layout.py`
   - Préférences/réglages + mises à jour (langue, barème, taille, contraste, logo) → `app_reglages.py`
   - Fichiers récents → `app_recent.py`
   - Orchestration App (câblage évènements, synchro, undo) → `penetrometre.py`
2. **Géométrie partagée** : modifier `geometry.py` une fois, les deux renderers héritent. Pour le visuel spécifique (traits, polices, écorce) → modifier Tk **et** PIL.
3. **Modèle** : ajout de champ = OK. Renommage/suppression → migration dans `persistence.py`.
4. **Tests** : lancer la suite avant tout commit touchant modèle/géométrie/exports.
5. **Valider** : lancer l'app + sauvegarder/recharger un `.json`.

Pour les détails d'architecture, de rendu et les pièges, voir :

- `.claude/docs/architecture.md` — description détaillée de chaque module
- `.claude/docs/rendu-et-pieges.md` — pendants Tk↔PIL, pièges, ordre des couches
- `.claude/docs/conventions-metier.md` / `conventions-code.md` — **détail** des
  conventions résumées plus haut (le « pourquoi », dates, pièges corrigés).
- `.claude/docs/ui-reference.md` — **référence détaillée** des comportements
  UI (liste d'arbres, filtres, saisie en grilles, comparaison, fiche PDF,
  accessibilité…) : le « pourquoi », les dates et les pièges corrigés ; les
  règles essentielles sont résumées plus haut.
- `.claude/docs/archives/` — plans de chantiers **terminés** (cépées/formes,
  fpdf2) conservés comme trace de conception. À lire avant de toucher au
  rendu multi-brins (`cepees-plan.md`).
- `.claude/docs/design-system.md` — **design system du chrome Tk** :
  tokens couleur (`palette.py`), typographie/espacements (`ui_fonts.py`),
  icônes (`icons.py`). Charte **SILVAVENIR** appliquée (2026-10-18, dossier
  `design system SILVAVENIR/`) : orange de marque = action principale,
  vert forêt = accent. `COLOR_ACCENT` (chrome) est volontairement
  **distinct** de `COLOR_RENDER_ACCENT` (dessin/PDF/comparaison,
  golden-testés ; les goldens ont été régénérés à cette occasion) et de
  `COULEUR_CLASSE` (diagnostic de risque, **non alignée** sur l'échelle de
  la charte par choix) — ne jamais les confondre. Aucun emoji couleur dans le chrome :
  glyphes Unicode monochromes (`icons.py`) ou texte seul.
