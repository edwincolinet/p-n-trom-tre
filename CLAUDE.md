# Pénétromètre — Pénétromètre

Application desktop d'expertise arboricole (mesure de cavités dans les
troncs au pénétromètre). Logiciel d'Edwin Colinet.

## Stack

- **Python 3.10+** (3.13 recommandé), **Tkinter** (UI stdlib), **Pillow** (PNG/PDF)
- Aucun framework ; pas de build pour le **développement** (lancement par
  double-clic). **Empaquetage distribution** : PyInstaller (`penetrometre.spec`,
  installeurs Win/macOS/Linux via `.github/workflows/build.yml` sur tag `v*`)
  **ou** Nuitka (binaire compilé, `build/build_nuitka.py` — plus dur à
  décompiler ; `license.is_bundled()` détecte les deux).
- Dépendance optionnelle : openpyxl (export XLSX).
- Dépendances runtime : cryptography (licence Ed25519 offline) ; **fpdf2**
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
ui_fonts.py            ← échelle des polices (facteur global + helper font(), pur)
section_canvas.py      ← SectionCanvas (rendu Tk section)
pane_identification.py ← onglet Identification
pane_sondages.py       ← onglet Sondages
pane_degradations.py   ← onglet Dégradations externes
pane_contreforts.py    ← onglet Contreforts
pane_diagnostic.py     ← onglet Diagnostic (exports + résumé + préconisation)
comparaison.py         ← fenêtre de comparaison inter-missions (ré-inspection)
comparaison_render.py  ← rendu PIL de la comparaison (section d'évolution + page export PNG/PDF)
app_exports.py         ← actions d'export (adaptateur Tk, fonctions pures)
app_menu.py            ← barre de menu Tk
app_style.py           ← thème ttk
dialogs.py             ← dialogues Tk (Sondage, Dégradation, Contrefort, Forme du tronc)
model.py               ← dataclasses + mutateurs + validation. Arbre (genet) = conteneur de Brin (ramet) ≥1
diagnostic.py          ← fonctions pures de diagnostic + sondage_render_data
persistence.py         ← I/O JSON (save/load + migration ; v3 = brins)
geometry.py            ← briques géométriques pures (spline, polaire, cernes, ellipse)
bareme.py              ← barème métier (classer_prbs, ports)
pil_render.py          ← rendu PNG de la section transversale
fiche_pdf.py           ← fiche expertise PDF A4 VECTORIELLE (fpdf2 ; dessin de section collé en raster)
palette.py             ← couleurs partagées Tk ↔ PIL
export.py              ← exports XLSX/HTML tableau PRBS + synthèse mission (XLSX/CSV)
undo.py                ← pile undo/redo (Ctrl+Z / Ctrl+Y, 50 snapshots)
tooltip.py             ← infobulle Tk légère (survol), n'importe quel widget
aide_repliable.py      ← widget d'aide repliable (ⓘ Aide ▸/▾), réutilisable
license.py             ← vérification/chargement/sauvegarde de licence offline (Ed25519, pur)
dialogs_license.py     ← fenêtre d'activation bloquante (premier lancement sans licence valide)
gen_license.py         ← outil interne d'émission de clés (NON distribué aux clients)
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
  `app_menu`/`pane_diagnostic` → doivent rester des méthodes de `App`) :
  pur dispatcher en lecture seule, le seul mixin réellement découplé.
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

**Graphe de dépendances** (chaque module importe uniquement vers le bas) :

```text
geometry.py + bareme.py   (stdlib)
   ↑
model.py + palette.py + tooltip.py + aide_repliable.py + app_recent.py + app_settings.py + ui_fonts.py
   ↑
diagnostic.py
   ↑
export.py + pil_render.py + persistence.py + dialogs.py
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

- **Grades** : 0 à 375 par pas de 25 (16 directions). 0 = Nord, sens horaire.
  Afficher `100 gr` (pas de symbole °).
- **PRBS** = Paroi Résiduelle de Bois Sain (mesure physique invariante).
  Quand le rayon change, la PRBS reste, `bois_altéré` s'ajuste.
- **t/R** = PRBS / Rayon **local** (0–1). **Classe globale** = barème sur t/R **moyen** 16 dir.
- **Genet / brin (ramet)** : `Arbre` = individu inventorié (= *genet*) ; il porte
  l'identité partagée + une liste de `Brin` (= *ramets*, ≥ 1). Un arbre mono-caule
  = un genet à brin unique ; une **cépée** = plusieurs brins. La géométrie et les
  mesures (rayon, sondages, dégradations, contreforts, position) vivent sur le
  **brin** ; des propriétés-relais sur `Arbre` (→ `brins[0]`) gardent le code écrit
  avant les cépées fonctionnel. **Cépée** : `Arbre.ajouter_brin` / `supprimer_brin`
  (boutons « ＋ Brin » / « − Brin » de l'onglet Identification) ; les brins sont
  composés par `_pil_draw_cepee` / `SectionCanvas._draw_cepee` via le cadrage pur
  `geometry.brins_layout` (mono-brin centré = chemin verbatim → goldens intacts).
  Une cépée étant large, `brins_layout` la cadre sur la largeur ; les deux
  renderers **centrent ensuite verticalement** les brins (post-ajustement de
  `origin_y`) ; en **export PNG** (`show_legend`), la **légende** occupe la
  bande basse. **Échelle radiale par brin** : chaque brin (mono-brin compris)
  porte sa propre échelle graduée — « 0 » au centre, multiples du pas
  adaptatif (repli : graduation **médiane** si aucun multiple ne tient →
  toujours ≥ 1 segment intermédiaire), terminal « N cm » au **bout de
  l'écorce** (R+ep) — le long de l'axe **Est**, ou de la direction libre la
  plus proche si un sondage y est rendu **et que les sondages sont affichés**
  (esquive pure `geometry.radial_ruler_grade`, conditionnée à
  `show_sondages` — masqués, pas de flèche à éviter → plein Est ; géométrie
  `geometry.radial_ruler_data` ; dessin `_pil_draw_echelle_radiale` /
  `SectionCanvas._draw_echelle_radiale`).
  Dessinée **en dernier** (premier plan) avec halo blanc pour rester lisible
  par-dessus cavité/dégradations. A remplacé la règle -R..+R du mono-brin et
  la barre « N cm » de la cépée (les brins ont des rayons distincts — une
  échelle par brin est la seule lecture fiable).
  **Diagnostic cépée** : `diagnostic.genet_diagnostic(arbre)` agrège un
  `repartition_classes_brin(section, port)` par brin → classe globale = **pire
  classe parmi les brins fiables** (rayon + ≥3 sondages) ; un brin non fiable
  est rapporté mais ne bloque pas (fiabilité par brin). Propagé partout
  (pastille de liste, onglet, fiche PDF, synthèse mission, exports PRBS) avec
  un détail par brin. **Chantier cépées/formes : Étapes 0-4 FAITES** (brin +
  ovale + rendu/saisie + diagnostic multi-brins + sélecteur de brin + éditeur
  de disposition souris) ; détail dans la mémoire `project_cepees-formes` et
  `.claude/docs/cepees-plan.md`. **Brin courant (4a)** : `App._current_brin()` /
  `_current_brin_idx` (remis à 0 au changement d'arbre, borné si un brin est
  retiré) / `set_current_brin(idx)` ; barre « Brin a/b/c » au-dessus des onglets
  (`_refresh_brin_selector`, masquée pour un mono-caule). Les onglets
  **Sondages/Dégradations/Contreforts** et la **géométrie** de l'onglet
  Identification (rayon/diamètre/écorce/forme) éditent `_current_brin()` ;
  l'identité (n°, essence, port, hauteurs, mèche) reste **genet**. Les dialogues
  `edit_sondage/degradation/contrefort` acceptent `Section = Union[Arbre, Brin]`.
  En complément du sélecteur, les grilles **Sondages/Dégradations/Contreforts**
  affichent en tête un **écho du brin courant** (`_brin_title`, accent, « ▸ Saisie
  du brin b ») — au plus près des yeux pendant la saisie, pour ne pas remplir une
  grille sur le mauvais brin ; dépacké (invisible) en mono-caule → pane inchangé.
  **Disposition de la cépée (4b)** : `dialogs.ask_cepee_layout` (canvas,
  glisser-déposer les brins → `pos_x/pos_y` ; brin « a » = ancre fixe en (0,0) ;
  contour fidèle via `contour_polygon`, cadrage figé par `brins_layout` ; travail
  sur copie → Annuler = no-op). `App.edit_cepee_layout` applique (undo + redraw) ;
  bouton « Disposition… » de l'onglet Identification (activé si ≥ 2 brins). La
  **rotation** d'un brin (`rotation_grades`) est éditable à la **molette** dans
  cet éditeur et **appliquée au rendu** (Tk + PIL) : les helpers purs
  `contour_polygon` / `cavity_polygon` / `contrefort_zone_outline` /
  `degradation_externe_outline` / `diagnostic.sondage_render_data` prennent un
  `rotation_grades` (défaut 0.0) qui **décale l'angle de placement** tout en
  évaluant le rayon au grade LOCAL → la forme (ovale comprise), la cavité, les
  sondages, contreforts et dégradations pivotent ensemble ; la **boussole**
  (ticks/cardinales) reste au Nord du monde. Un **cercle étant invariant par
  rotation**, le cas circulaire garde sa primitive native (`create_oval`/
  `d.ellipse`) → goldens byte-identiques (`rotation_grades=0` ⟹ `g+0.0==g`). Le
  diagnostic (classes, t/R) est inchangé : la rotation est purement visuelle.
- **Section ovale (ellipse)** : `Brin.rayon_petit_axe_cm` (0 = circulaire,
  sentinelle) + `orientation_grade`. Si renseigné, `rayon_tronc_cm` devient le
  demi-**grand** axe et le rayon est **local par direction** (`Brin.rayon_a_grade`
  / `geometry.ellipse_radius`) — d'où le t/R local ci-dessus. Saisie via l'**éditeur
  avancé** `dialogs.ask_forme_tronc` (bouton « Forme du tronc… » de l'onglet
  Identification), pas en ligne, pour ne pas alourdir le cas circulaire courant.
- **Diagnostic non fiable si < 3 sondages** → exports masquent t/R moyen + classe.
- **Dégradations externes** consomment du bois sain : `PRBS_ajustée = sain −
  profondeur_bois_deg`. **L'écorce n'est jamais du bois sain** (le rayon est
  déjà sous écorce) — invariant. Le champ `DegradationExterne.comprend_ecorce:
  bool = True` décrit la **géométrie** de la dégradation. Saisi via le
  sélecteur **« Zone dégradée »** (combobox *readonly* « Écorce + bois »
  [True, défaut] / « Bois seul » [False]) de la grille **et** du dialogue
  `edit_degradation` — libellés et helpers source-unique dans `dialogs`
  (`ZONE_DEGRADEE_CHOICES`, `zone_degradee_label`/`zone_degradee_to_bool`,
  rappel `ZONE_DEGRADEE_AIDE` sous la grille). A remplacé une case à cocher
  nue dont le sens et l'impact PRBS étaient illisibles sur le terrain :
  - **comprend l'écorce** (défaut) : la zone dégradée part de la **surface
    extérieure** (écorce visuellement dégradée). La bande d'écorce traversée
    ne réduit pas la PRBS → `profondeur_bois = max(0, profondeur −
    épaisseur_écorce)`.
  - **commence sous l'écorce** : l'écorce reste **intacte** au dessin, la
    dégradation part de la **surface du bois** → toute la profondeur est du
    bois perdu.
  Pilote à la fois le **calcul** (helper pur
  `DegradationExterne.profondeur_bois_cm(ep)`, utilisé par
  `diagnostic.degradation_externe_par_grade`/`degradation_ecretee`) **et le
  rendu** (`geometry.degradation_externe_outline`). **Rendu** : la dégradation
  suit **toujours** la saillie des contreforts (cloche `bell_max(g)`, le bois
  gonfle), dans les deux modes ; le rayon de départ est `R + bell + ep` si elle
  comprend l'écorce, `R + bell` sinon. Le bord externe est prolongé d'un léger
  **recouvrement anti-couture** (`geometry._BARK_SEAM_PX`, ~1 px, dans les deux
  modes) : deux remplissages jointifs (dégradation / écorce ou / bord
  d'écorce) laissent sinon un liseré d'anti-aliasing (bois ou fond) visible
  entre eux. Cas par défaut (True) ⟹ dessin **inchangé** → goldens intacts.
  Fichiers antérieurs corrigés rétroactivement (défaut True au load).
  **Convention confirmée (protocole terrain)** : le sondage mesure la paroi
  **totale** en ignorant la dégradation externe (mèche posée à côté de la
  zone dégradée) — l'app déduit ensuite la profondeur. **Fusion** : les deux
  zones dégradées (altération centrale + bande périphérique) ne peuvent pas
  cumuler plus que le rayon — `prbs_par_grade` écrête à 0 (= union des
  zones), valeur utilisée partout (pastille, tableaux, exports). L'écrêtage
  est **signalé, pas silencieux** : garde-fou non bloquant « ⚠ » ambre
  (`COLOR_WARN`) sur la colonne Altéré de la grille de sondages, sur la
  ligne de dégradation fautive (tooltip) et dans le tableau PRBS de
  l'onglet Diagnostic. Helpers purs `diagnostic.fusion_ecretee_par_grade`
  (par direction) / `degradation_ecretee` (par objet — ne marque pas la
  voisine mitoyenne d'un arc profond). Recalcul via
  `refresh_fusion_warnings()` des deux panes, câblé sur `App._redraw_all`
  (labels en lecture seule uniquement → sûr pendant la frappe).
- **Pastille sondage = PRBS ajustée** (jamais brute).
- **Contreforts** = cloche cosinus², fusion si adjacents (`contrefort_zones`).
- **Écorce** = visuelle pour le rayon (R_ext = R + ep, le bois sain reste
  mesuré sous écorce). **Seule incidence sur le diagnostic** : son épaisseur est
  déduite de la profondeur des dégradations externes qui **comprennent l'écorce**
  (cf. ci-dessus) — l'écorce abîmée ne compte pas comme bois sain perdu.
- **COLOR_BARK ≠ COLOR_ROT** : ne jamais unifier (contraste dégradation/écorce).
- **Unicité** : un seul sondage par direction, pas de dégradations qui se
  chevauchent (arcs mitoyens bout-à-bout autorisés), un seul contrefort par
  grade central. Sondages et contreforts : **garantie par construction**
  (grilles 16 directions, une ligne par grade). Dégradations : helper pur
  `model.degradations_chevauchements` (exclut les grades-frontières
  mitoyens), partagé entre `dialogs.edit_degradation` (clic Valider) et la
  saisie en place de `pane_degradations` (valeur fautive rétablie).

## Conventions de code

- Pas de dépendance sans bonne raison. Compat Python 3.10+.
- Tout en français (UI + docstrings).
- Pas de `print` — logger applicatif (`~/.penetrometre/penetrometre.log`).
- Exports : `log.exception(...)` avant `messagebox.showerror`.
- Compat fichier bidirectionnelle : ajout champ = OK (default) ; renommage/suppression = migration explicite dans `persistence.chantier_from_dict`. **Format v3** : la géométrie/mesures sont passées d'`arbre` à `arbre.brins[i]` ; un fichier v≤2 (champs à plat) est migré en un genet à **brin unique** (cf. `_brin_from_dict`).
- **Rendu de forme (cercle vs ellipse)** : les primitives partagées de `geometry` (`contrefort_zone_outline`, `degradation_externe_outline`, `tick_endpoints`, `cardinal_label_positions`) acceptent un rayon `RadiusSpec` = **scalaire OU fonction `grade→rayon`** ; `contour_polygon` échantillonne le contour ovale. Les renderers passent `arbre.rayon_a_grade` (constant si circulaire). **Cas circulaire = chemin primitif natif** (`d.ellipse` / `create_oval`) conservé sous une branche `if est_ovale` → rendu **byte-identique**, goldens intacts (seule la fixture `ovale` s'ajoute). Toute évolution du contour doit garder cette branche pour ne pas casser les goldens circulaires.
- Écriture atomique : `save_chantier` écrit dans un `.tmp` puis `os.replace` — le fichier original survit en cas de crash.
- **Sauvegardes glissantes** (`persistence.write_backup`/`list_backups`/`_prune_backups`, purs) : à chaque `action_save` réussi, une **copie horodatée** `stem_AAAAMMJJ-HHMMSS.json` est déposée dans `~/.penetrometre/backups/` et les anciennes purgées (on garde `BACKUP_KEEP_DEFAULT=12` par mission, identifiée par `stem`+`suffix`). **Best-effort** : un échec est loggé et **n'interrompt jamais** l'enregistrement réel (`write_backup` renvoie `None`). Complémentaire de l'autosave : l'autosave protège du **crash**, le backup de l'**écrasement/corruption** (une mission = une journée de relevés). Accès via **Fichier → Ouvrir le dossier des sauvegardes…** (`App.action_open_backups_folder`). `list_backups` trie du plus récent au plus ancien (nom horodaté ⟹ ordre lexicographique = chronologique).
- **Autosave anti-crash** (`persistence.save_recovery`/`load_recovery`/`clear_recovery`, câblage dans `App`) : tick `after` toutes les 60 s (`_AUTOSAVE_INTERVAL_MS`) qui n'écrit `~/.penetrometre/recovery/autosave.json` **que si `_dirty`**. Le fichier enveloppe `chantier_to_dict` + métadonnées (`saved_at`, `original_file`). **Invariant clé** : l'autosave est effacé dès qu'on atteint un état propre (`action_save`, `action_new`, `_open_path`) **et à la fermeture normale** (`_on_close`, même en abandonnant des modifs) — donc sa seule présence au démarrage ⟺ crash précédent avec travail non enregistré. `_check_recovery_on_startup` (programmé via `after(200, …)` pour s'afficher sur une UI déjà mappée) propose la reprise ; `_restore_recovery` recharge l'UI, repointe `current_file` sur l'original s'il existe encore, et remet `_dirty=True`. Écriture atomique (`.tmp` + `os.replace`) comme `save_chantier`.
- **Champs numériques UI** : filtrage à la frappe via `dialogs.validate_numeric` (validateur Tk `validate="key"`) — seuls chiffres + un séparateur décimal `.`/`,` acceptés. Parsing via `dialogs.to_float` (accepte `2,5` et `2.5`). Branché sur les 3 dialogues (Sondage/Dégradation/Contrefort) + les 6 champs numériques de `pane_identification`. `_parse_float("")` renvoie `None` (pas `0.0`). `set_rayon` n'est appelé qu'au focus-out (jamais pendant la frappe) pour éviter la destruction irréversible des PRBS par valeurs intermédiaires.
- **N° d'arbre** : doit contenir au moins un chiffre (« 1 », « 42 », « 12 bis » OK ; « bis » seul refusé). Règle appliquée dans `pane_identification._revert_num_if_invalid` (revert au focus-out) et `App.action_rename_arbre` (boucle de retry pré-remplie).
- **Compartimentation** : valeurs `"active"`, `"absente"`, `"non renseignée"` (anciennement `"-"`, migré silencieusement au load via `persistence.chantier_from_dict`). **Symboles source-unique** dans `dialogs_shared` (`COMPART_GLYPH`/`COMPART_COLOR` + `compart_glyph`/`compart_color`/`compart_visual`) : **✔** active (vert) · **✘** absente (rouge) · **—** non renseignée (gris). Le **même** glyphe est affiché à la **saisie** (combobox « ✔ active » via `compart_label`/`compart_from_label`, qui préfixe/retire le glyphe) **et** dans **tous les exports** (cellule XLSX/HTML/PDF, symbole seul + légende). Coche/croix renforcées U+2714/U+2718 (présentes dans DejaVu → rendu PDF garanti). `export.py` et `fiche_pdf.py` importent ces helpers (openpyxl : `.lstrip("#")` sur la couleur).
- **Indicateurs d'état de la liste d'arbres** : `App._arbre_etat(arbre)` renvoie `(glyphe, risque, tag)` pour **deux colonnes distinctes** (`État` + `Risque`), qui lèvent l'ancienne ambiguïté où la **couleur de ligne** signifiait *complétude* pour `○/◐` mais *classe de risque* pour `●` (ttk.Treeview ne colore qu'une ligne entière, pas une cellule → un seul sens possible par couleur). Désormais :
  - **Colonne État = forme du glyphe = complétude** (lisible en daltonisme rouge-vert) : `○` `etat_vide` (0 sondage OU rayon=0), `◐` `etat_partiel` (1-2 sondages), `●` (≥3 sondages, fiable).
  - **Colonne Risque = mot** « Vert/Orange/Rouge » (= `gd.classe_globale`, qui EST déjà la chaîne) dès que fiable, `—` sinon → risque lisible **sans dépendre de la couleur**.
  - **Couleur de ligne (`tag`) = uniquement la classe de risque** : `etat_ok_vert`/`_orange`/`_rouge` (via `COULEUR_CLASSE`) pour les fiables ; **les incomplets `○/◐` sont en gris NEUTRE** (`etat_vide`/`etat_partiel` → `COLOR_MUTED`), plus en rouge/orange. La couleur ne signifie donc plus qu'une chose. Repli `etat_ok` (vert) si fiable mais classe indispo.
  Le seuil **fiable ≥ 3** est **aligné** sur la règle métier de fiabilité (« < 3 sondages → exports masqués »). NB : l'extrapolation géométrique de la cavité (`compute_alteration_par_grade`) reste active dès 2 sondages — découplé du seuil de fiabilité. Refresh ligne par ligne via `_refresh_current_arbre_etat()` appelé dans `_redraw_all` (après toute mutation, debounce). Footer `lbl_etat_footer` = **vue de triage macro** de la mission (`_update_etat_footer`, sans argument, recalculé sur **toute** la mission — jamais la sous-liste filtrée) : répartition `N rouge · N orange · N vert · N à finir (total)` (classes via `_arbre_etat`, « à finir » = incomplets `○/◐`). Répond au « puis-je quitter le site ? » sans ouvrir l'export de synthèse. Son **compagnon de triage** : le bouton « ⏭ Prochain arbre à finir » (sous le footer) + l'entrée menu Arbres → `action_next_a_finir` saute au prochain arbre non fiable en **bouclant** (parcours cyclique depuis le courant), **vide les filtres** si besoin pour rendre la cible visible. Les largeurs des 4 colonnes + la largeur par défaut du panneau gauche (`PanedWindow`) sont calibrées pour que `Risque` tienne malgré la scrollbar verticale ; le panneau reste élargissable à la souris.
- **Workaround bpo-36468 (ttk.Treeview)** : depuis Python 3.7, les `tag_configure(foreground=…)` sont ignorés à cause d'entrées par défaut dans `style.map`. `app_style._fixed_map` retire les entrées `("!disabled", "!selected", …)` pour que les tags prennent la main. Sans ça, les pastilles d'état resteraient blanches.
- **Filtre de la liste d'arbres** : deux filtres **cumulés** (ET) dans `_arbre_matches_filter` — (1) champ 🔎 texte (`var_filter`), sous-chaîne insensible à la casse sur **n° OU essence** ; (2) combobox **classe de risque** (`var_risk_filter`, constantes `_RISK_FILTER_*` d'`app_arbres` : Tous / Vert / Orange / Rouge / Non fiable, « Non fiable » = colonne Risque à « — »). `_refresh_tree_arbres` masque les lignes non concordantes **mais conserve les `iid = a{index}`** indexés sur la position réelle (cf. `_on_select_arbre`) — le filtre n'altère jamais le modèle. Le **footer reste sur toute la mission** (vue macro), pas sur la sous-liste. `Échap` dans le champ vide le filtre texte. Les **deux** filtres sont **remis à zéro** au chargement d'une mission (new/open) et à la **création d'un arbre** (`_clear_filter_if_set` — un arbre neuf est « Non fiable », il resterait masqué par un filtre risque actif). La **navigation clavier** (`_select_arbre_relative`) parcourt uniquement les arbres **visibles** quand un filtre est actif.
- **Ajout d'arbre en série** : le bouton « ＋ Ajouter » est un `Menubutton` (`Accent.TMenubutton`) à 2 entrées. **« Arbre vierge »** (`action_add_arbre`, `Ctrl+T`) = tous champs par défaut. **« Hériter du précédent »** (`action_add_arbre_inherit`) reprend les champs d'identité/protocole de l'arbre courant (essence, port, mèche, épaisseur d'écorce, hauteur de sondage) mais **PAS** la géométrie mesurée (rayon/diamètre/hauteur d'arbre laissés à défaut, à re-mesurer) ni les sondages/dégradations/contreforts — pensé pour les alignements d'arbres identiques. N° via `_next_arbre_numero` (max numérique + 1).
- **Navigation clavier entre arbres** : `Ctrl+PgDown`/`Ctrl+PgUp` → `action_next_arbre`/`action_prev_arbre` → `_select_arbre_relative(±1)` (bornée, sans boucle). Donne d'abord le focus clavier à la liste (`tree_arbres.focus_set()`) pour déclencher le `<FocusOut>` d'une case de grille en cours d'édition avant de basculer. Libre de conflit avec la navigation entre **onglets** : `nb.enable_traversal()` (appelé dans `_build_center`) lie `Ctrl+Tab`/`Ctrl+Maj+Tab` pour compléter le flux de saisie au clavier (rayon → onglet suivant → sondages…) — disjoint de `Ctrl+PgUp/PgDown` (arbres) et `Ctrl+Z/Y`. Documenté dans le popup `action_shortcuts`.
- **Menu contextuel clic droit** sur la liste d'arbres : Renommer/Dupliquer/Supprimer. `tk_popup` SANS `grab_release()` (anti-pattern qui annule le grab) + `bind("<FocusOut>")` sur le menu pour fermeture au clic externe.
- **Canvas interactif** : `section_canvas.SectionCanvas` accepte un `host` optionnel (l'App) ; `tag_bind("sondage_item"/"degradation_item"/"contrefort_item", "<Button-1>")` ouvre le dialogue d'édition correspondant. Curseur `hand2` au survol. Dispatch via tags `<type>_idx_<i>` pour retrouver l'objet métier.
- **Dialogues modaux** : `dialogs._make_modal(dlg, parent)` séquence `update_idletasks → transient → wait_visibility → grab_set → focus_set`. Appeler `grab_set` avant que le WM ait mappé la fenêtre fait apparaître le dialogue **vide** sur Linux/X11 (race entre grab et rendu). Tous les dialogues passent par ce helper, qui est appelé APRÈS la création des widgets. Chaque dialogue d'édition (Sondage/Dégradation/Contrefort) bind `<Return>`→Valider, `<Escape>`→Annuler, et pose le focus initial sur son 1er champ utile.
- **Saisie texte thémée** : `dialogs.ask_string(parent, title, prompt, initial, info=…)` remplace `simpledialog.askstring` (look système incohérent). Renvoie `None` si annulé, la chaîne (sans `strip`) si validé — `""` validé ≠ `None`. Utilisé par `action_rename_arbre`.
- **Barre d'état** : `App._build_statusbar()` (bas de fenêtre, packée `side="bottom"` AVANT le body). `App.notify_export(path, label)` y affiche le succès d'un export (non-modal) et active les boutons « Ouvrir le fichier / le dossier » (`App._open_in_system`). `app_exports._notify_export` route vers `notify_export` si l'hôte le fournit, sinon `messagebox` (contexte test). À gauche, un **bouton « 💾 Enregistrer » toujours visible** (= `action_save`) + un **indicateur d'état d'enregistrement persistant** (`lbl_save_state`) : `App._update_save_indicator()` (appelé par `_update_title`, donc à jour à chaque changement du dirty flag) montre `● Modifications non enregistrées` (ambre, bouton actif) / `✓ Enregistré` (vert, bouton désactivé) / `Mission non enregistrée` (gris, mission neuve sans fichier, bouton actif). Le `•` du titre ne suffisait pas (masquable par le WM) — c'est la réponse au « ai-je enregistré ? » de l'opérateur terrain.
- **Date du relevé** : deux saisies complémentaires. (1) **Clavier** : champ libre normalisé au format `JJ/MM/AAAA` au focus-out via le helper pur `dialogs.normaliser_date` (accepte séparateurs `/ - .`/espace, ordre français ou ISO, année 2 ou 4 chiffres ; valide via `datetime.date`, rejette 31/02). Handlers dédiés `App._date_focus_in`/`_date_focus_out` (les 3 autres champs méta gardent `_meta_focus_*`) : une saisie non interprétable **rétablit la valeur d'avant l'édition** + message de barre d'état (motif de revert comme le n° d'arbre). `normaliser_date("")` → `""` (date facultative), saisie illisible → `None`. (2) **Calendrier** : bouton « 📅 » → `dialogs.ask_date` (mini-calendrier **Tkinter pur**, aucune dépendance type `tkcalendar`/`babel` ; mois FR lundi-d'abord, nav ◀▶, jour sélectionné/aujourd'hui accentués, boutons Aujourd'hui/Effacer/Annuler). `App._pick_date` applique avec undo ; renvoie `""` si effacée, `None` si annulée (no-op).
- **Infobulles** : `tooltip.Tooltip(widget, texte)` — bindings `add="+"` pour ne pas écraser ceux du widget. Sert à rappeler les accélérateurs (bouton « ＋ Ajouter » → Ctrl+T) et décrire le bandeau d'export (2 boutons + menu « Tableau »).
- **Aide repliable** : `aide_repliable.AideRepliable(parent, *paragraphes, titre="Aide", wraplength=…)` — bloc d'aide derrière un en-tête cliquable « ⓘ Aide ▸/▾ », **replié par défaut** (discret pour l'opérateur expérimenté, dépliable au clic à la 1ʳᵉ utilisation). Remplace les libellés `Muted.TLabel` ⓘ permanents (identification : couplage Ø↔rayon + invariance PRBS ; sondages : sémantique case vide/effacer ; canevas : clic = éditer/ajouter). Fonctionne en `grid` comme en `pack` (gère sa disposition interne ; le parent place le widget). État conservé tant que le widget vit — les panes ne sont construits qu'une fois, pas par arbre. S'appuie sur les styles `Panel.TFrame`/`Muted.TLabel`.
- **Canevas — ajout par clic** : un clic sur une direction libre du dessin ajoute un sondage à ce grade (`App.open_add_sondage`) ; un clic sur une direction déjà sondée l'édite. `SectionCanvas._on_click_background` convertit le pixel en grade (inverse de `geometry.polar_to_xy`), mémorise la géométrie du dernier rendu dans `self._geom`, et ignore les clics sur un élément interactif (garde par tags).
- **Raccourci export** : `Ctrl+E` → `App.action_export_pdf_arbre`. Bind dans `App.__init__` (comme Ctrl+Z/Y) via `_on_export_shortcut`, qui **ne déclenche pas** si un `Entry`/`Combobox` a le focus (Ctrl+E = « fin de ligne » dans les widgets Tk).
- **Fichiers récents** : `~/.penetrometre/recent.json` (8 entrées max). `App._push_recent_file(path)` appelé après chaque open/save. Sous-menu `Fichier → Ouvrir récent` reconstruit par `app_menu.refresh_recent_menu(app)`.
- **Adaptation petits écrans** : `App.__init__` clampe la geometry à 95 % de l'écran et fixe `minsize(1100, 680)` pour rester utilisable sur laptops 1366×768.
- **Disposition 3 colonnes redimensionnable** : le `body` est une `tk.PanedWindow` horizontale (`self._paned`) à 3 panneaux **à poignées** — liste d'arbres (`minsize=190`, `stretch="never"`), saisie/onglets (`minsize=400`, `stretch="never"`), dessin (`minsize=360`, `stretch="always"` → absorbe le redim. fenêtre). `tk.PanedWindow` (classique, pas `ttk`) pour le `minsize` par panneau. Répond à deux besoins : élargir le tableau de saisie au détriment du dessin (onglets Dégradations/Contreforts peu denses) et réallouer l'espace sur petit écran. `SectionCanvas` se redessine sur `<Configure>` → s'adapte à la largeur du panneau sans code spécifique. **Positions persistées** : `App._save_sash_positions` (sur `<ButtonRelease-1>` de la PanedWindow) → `SettingsStore.set_sash_positions` ; `App._restore_sash_positions` les ré-applique via `sash_place` **différé** (`after(150,…)`, sinon TclError tant que la PanedWindow n'est pas dimensionnée). `get_sash_positions()` tolérant → `[]` si jamais réglé / corrompu (défauts d'`add`).
- **Taille du texte (accessibilité)** : réglage `ui_scale` persisté dans `~/.penetrometre/settings.json` (`app_settings.SettingsStore`, pur, borné `[0.8, 1.6]`). **`tk scaling` est inopérant** sur plusieurs builds Tk/Linux (métriques de police indépendantes du facteur) — le seul levier fiable est de **multiplier le nombre de taille** de chaque police. Centralisé dans `ui_fonts` : facteur global de processus (`set_ui_scale`/`get_ui_scale`) + helper `font(family, size, *opts)` qui applique le facteur (identité à 1.0 → aucune régression ni golden-test par défaut). `App.__init__` fixe le facteur **avant** la création des widgets (`_apply_ui_scale` → `set_ui_scale`). Toutes les polices de la couche UI passent par `ui_fonts.font` : styles ttk (`app_style`, `_f`), et tuples explicites de `penetrometre`/`pane_sondages`/`pane_diagnostic`/`dialogs` (`ui_font`). `app_style` scale aussi le `rowheight` du Treeview. **Le dessin (`section_canvas`) n'est PAS scalé** (géométrie en pixels fixes, golden-testé). Menu **Affichage → Taille du texte** (radiobuttons Petit/Normal/Grand/Très grand → `action_set_ui_scale`) : persiste, met à jour le facteur, **ré-applique `apply_ttk_styles` à chaud** (effet immédiat sur la majorité de l'UI) ; les quelques widgets à police en tuple déjà réalisés ne se redimensionnent qu'au redémarrage (message de barre d'état).
- **Contraste élevé (accessibilité plein soleil)** : réglage booléen `high_contrast` persisté (`SettingsStore`). `apply_ttk_styles(root, *, high_contrast=False)` passe le texte courant en **noir pur** et le texte atténué (Muted/Sub, onglets inactifs) à un gris **bien plus sombre** (`#2C3631`) — **les accents verts et les fonds sont inchangés**, et **le dessin n'est pas concerné** (golden-testé). Identité au défaut → aucune régression. Menu **Affichage → Contraste élevé** (checkbutton → `action_set_high_contrast`). **Point unique `App._apply_styles()`** (= `apply_ttk_styles(self, high_contrast=…)`) utilisé partout (startup + `action_set_ui_scale`) pour ne jamais perdre le mode en ré-appliquant les styles. Les couleurs peintes hors styles (tags de la liste d'arbres, dessin) ne changent pas → message « redémarrer pour un effet complet ».
- **Progression dans les onglets** : `App._refresh_tab_progress()` (appelé dans `_redraw_all`) préfixe les onglets de l'étape par un glyphe d'avancement — **même vocabulaire que les pastilles** (`○` à faire · `◐` en cours · `●` prêt). Identification (`●` si rayon>0 et essence saisie), Sondages (glyphe de complétude via `_arbre_etat`), Diagnostic (`●` si `_arbre_diag_fiable`). La **forme** porte l'info (lisible en daltonisme ; ttk n'autorise pas de couleur par onglet). Dégradations/Contreforts restent sans glyphe (étapes optionnelles — un `○` y suggérerait à tort un manque). `self.nb` mémorisé dans `_build_center`.
- **Saisie des sondages = grille 16 directions** (`pane_sondages.py`) : refonte ergonomique remplaçant la modale-par-mesure. Les 16 directions (rose des vents `_WIND_LABELS` : cardinales `N/NE/E…`, intermédiaires en combiné `N-NE/NE-E…`) sont pré-affichées ; l'opérateur tape la PRBS et descend (`Entrée`/`↓`/`↑` → ligne suivante via `_focus_entry`). **Sémantique** : case vide = direction non sondée (aucun `Sondage`) ; valeur (y compris 0) = sondage existant ; **effacer la valeur supprime le `Sondage`** (commentaire + compartimentation compris). Cette suppression étant destructrice et muette, si le sondage effacé portait un **commentaire** ou une **compartimentation** ≠ « non renseignée », elle est **signalée** en barre d'état et son undo est **poussé immédiatement** (pas au focus-out) pour que le « Ctrl+Z » annoncé fonctionne sans changer de focus. L'altéré (`R − sain`, clampé à `R`) est en lecture seule, recalculé en direct. La compartimentation (combobox) n'est active que si un sondage existe sur la ligne. **Unicité garantie par construction** (une ligne par grade — plus de validation d'unicité). Double-clic sur les libellés **Direction/Grade** ouvre `edit_sondage` (détail : commentaire, redirection de grade) ; l'`Entry` garde son double-clic natif. **Undo des éditions live** : snapshot capturé au focus-in (`host.capture_undo_snapshot`), empilé au focus-out seulement si la valeur a changé (`host.push_undo_snapshot`) — évite les undo parasites ; la compartimentation passe par `host.push_undo` (mutation discrète). Mutations notifiées via `host.on_sondages_changed` (dirty + redraw debouncé ; ne re-`refresh()` PAS la grille pour ne pas lutter contre la frappe). Sondages maintenus triés par grade (`sort` + `renumeroter_sondages`). Les libellés de la rose des vents 16 directions vivent dans `geometry.WIND_LABELS` (partagés avec la grille Contreforts). **Garde-fous rayon** : tant que le brin n'a pas de rayon (`R<=0`), un bandeau ambre en tête de grille (`_lbl_no_radius`, montré/caché par `refresh`) rappelle de saisir le rayon dans l'onglet Identification — sinon l'altéré n'est pas calculable (« — ») et le bois sain n'est pas borné. La PRBS est **plafonnée au rayon** dès la frappe (`_on_sain_write`, `min(sain, R)`) ; le focus-out **signale** ce plafonnement en barre d'état (`host.set_status`) au lieu de le subir silencieusement.
- **Saisie des contreforts = grille 16 directions** (`pane_contreforts.py`) : même pattern que la grille de sondages — l'unicité « un contrefort par grade central » borne le domaine à 16, donc lignes pré-affichées. **Sémantique alignée** : longueur vide = pas de contrefort ; valeur (y compris 0) = existant ; effacer = supprimer. Largeur (combobox des multiples de 25, défaut 75 gr à la création) et commentaire actifs seulement si un contrefort existe sur la ligne. Double-clic Direction/Grade → `edit_contrefort` (détail : largeur en cm). Même mécanique d'undo focus-in/out ; notification via `host.on_section_changed` (équivalent générique d'`on_sondages_changed` pour Dégradations/Contreforts). Contreforts maintenus triés par grade.
- **Saisie des dégradations = tableau éditable en place** (`pane_degradations.py`) : une dégradation est un **arc** début→fin (domaine non fixe) → pas de grille pré-affichée mais des **lignes dynamiques toutes éditables** (combobox début/fin readonly via `dialogs.grade_choices`/`find_grade_choice`/`parse_grade` rendus publics, largeur gr·cm en lecture seule, profondeur/commentaire en saisie live, bouton ✕). **« ＋ Ajouter » ne passe plus par la modale** : crée l'arc sur la première plage libre (50 gr, repli 25 gr) et pose le focus sur la profondeur. Non-chevauchement validé à la sélection début/fin (valeur fautive **rétablie** + `messagebox` ; texte partagé `dialogs.message_chevauchement`). Double-clic sur le n° → `edit_degradation` (détail : largeur en cm). **Piège dataclass** : les callbacks capturent l'objet `deg` par closure et le retrouvent par **identité** (`_index_de`, `is`) — jamais `in`/`remove`, dont le `__eq__` structurel confondrait deux arcs identiques.
- **Synthèse de mission** (tableau de hiérarchisation du risque) : `diagnostic.mission_synthesis_rows(chantier)` → `List[MissionSynthesisRow]` (fonction pure), **une ligne par arbre** (n° · essence · port · nb sondages · rayon · t/R moyen · classe globale · direction critique). Respecte la règle de fiabilité : `tR_moyen_pct`/`classe_globale` = `None` si `< 3` sondages (via `DiagnosticSnapshot.diagnostic_global`), `tR_min_pct`/`crit_grade` = `None` si aucune altération. Exports : `export.export_synthesis_csv` (séparateur `;`, UTF-8 BOM) et `export.export_synthesis_xlsx` (thème vert, cellule classe colorée, **autofiltre** pour trier par risque, en-tête gelé, ligne de bilan). Wrappers Tk dans `app_exports.export_synthesis_{csv,xlsx}_mission` ; actions `App.action_export_synthesis_{csv,xlsx}` ; entrées dans le menu **Fichier** (mission-level, à côté des fiches PDF / sondages CSV). « Non fiable » (1-2 sondages) ≠ « — » (rayon nul / 0 sondage) dans la colonne classe. **Colonnes Préconisation** : les 3 champs `urgence`/`echeance`/`preconisation` du genet sont repris en fin de ligne (`_replace` au niveau genet/tête de cépée seulement, vides sur les sous-lignes de brin). Le XLSX colore la cellule **Urgence** par niveau (`_URGENCE_FILL`).
- **Préconisation (expertise → décision)** : la classe de risque dit « quel danger », ces champs **genet** disent « quoi faire » — c'est le livrable. `Arbre.urgence` (∈ `model.URGENCE_NIVEAUX` : Immédiate / Court terme / Moyen terme / Surveillance / Sans objet ; `""` = non renseignée), `Arbre.echeance` (date `JJ/MM/AAAA` facultative), `Arbre.preconisation` (**texte libre**) — choix d'Edwin (AskUserQuestion : texte libre + échelle d'urgence + échéance optionnelle). Pas de migration (nouveaux champs à défaut vide, filtrés par `__dataclass_fields__` au load). **Saisie** : bloc « Préconisation » de l'onglet **Diagnostic** (`pane_diagnostic._build_preconisation`) — combobox urgence, échéance (entry normalisée + bouton 📅 `ask_date`), `tk.Text` multi-ligne. Édite le **genet** courant ; mutations via `host.on_preconisation_changed` (= `_mark_dirty` **seul**, pas de redraw — n'affecte ni dessin ni pastille). Undo : snapshot au focus-in, empilé au focus-out si changé (urgence = `push_undo` discret). `_refresh_preconisation` **ne recharge que si l'arbre a changé** (`_preco_loaded_id` = `id(arbre)`) → ne lutte pas contre la frappe sur un redraw. **Sorties** : colonnes synthèse mission (cf. ci-dessus) + bloc sur la **fiche PDF** (`fiche_pdf` : urgence colorée par niveau `_URGENCE_COLOR`, échéance, texte libre `_wrap_lines` borné 4 lignes ; placé après l'identité → le budget vertical du dessin s'ajuste).
- **Comparaison inter-missions (ré-inspection)** : `comparaison.open_comparison(parent, current, reference, *, cur_date, couleur_classe, export_cb)` — fenêtre **redimensionnable** à 3 sections côte à côte (**référence | courant | carte d'évolution**), tableau chiffré, verdict, et **export PNG + PDF**. Décisions métier (AskUserQuestion) : **par session** (`App._reference_chantier`, rien de persisté → pas de lien cassé) ; **lien explicite par arbre** (combobox, défaut = même n°) ; **vue dédiée** ; **section d'évolution** (progression surlignée) + **export PNG & PDF**.
  - **Cépée (multi-brin)** : la fenêtre affiche **un bloc de comparaison par brin** (3 dessins + tableau + verdict), empilés dans une zone **défilante** (mono-caule = un seul bloc, sans en-tête). Appariement **automatique par index/label** (a↔a, b↔b… — choix Edwin) : un brin courant **sans homologue** de référence (réf plus courte / brins ré-ordonnés) est comparé à `None` (colonne réf. vide, pas de couronne orange) — jamais d'appariement décalé silencieux. Calcul pur `diagnostic.comparaison_par_brin(ref, cur, annees)` → `[(label, cur_brin, ref_brin|None, ComparaisonDetail)]` (classe/t/R **au niveau brin** via `_brin_compare_summary`). Rendu brin : `comparaison_render.render_brin_section` (brin isolé via genet temporaire) + `render_evolution_section_brin(ref_b|None, cur_b)`. **Export par brin** : `render_comparison_pages(...)` → **une page A4 par brin** pour une cépée (page genet inchangée pour un mono-caule) ; `save_comparison_pdf` = **PDF multi-pages**, `save_comparison_png` = pages **empilées verticalement** (PNG mono-image). Composeur de page partagé `_compose_comparison_page` (genet ↔ brin). Le builder de la fenêtre (`_page_builder`) renvoie la **liste** de pages. **Ergonomie** : la fenêtre **respecte la case « Afficher sondages »** (param `show_sondages` propagé jusqu'aux dessins, fenêtre **et** export — sinon les flèches s'affichaient toujours), s'ouvre **grande et centrée** (95 % écran) avec le **bouton maximiser** disponible — elle n'est **pas** `transient` (un transient X11 = dialogue utilitaire, souvent sans bouton maximiser et `-zoomed` ignoré ; `state('zoomed')`/`-zoomed` tentés en best-effort par-dessus), et le `filedialog` d'export est **ancré sur la fenêtre** (`parent=dlg`, via `export_cb(fmt, builder, parent)`) pour ne pas passer dessous. **Molette** : défilement activé quand le pointeur est sur la zone (pattern `bind_all` Enter/`unbind_all` Leave, comme `pane_diagnostic`). **Choix des DEUX arbres dans la fenêtre** : deux comboboxes (arbre **courant** de la mission **+** arbre de **référence**) — avant, le courant était figé au lancement ; `default_arbre` = sélection initiale, référence par défaut = même n°. **Piège** : les `StringVar` des comboboxes sont gardées dans `state` (sinon, locales, elles sont GC à la sortie de la fonction → leur `__del__` désaffecte la variable Tcl → combobox vide).
  - **Calcul pur** (`diagnostic`) : `arbre_compare_summary` (réutilise la synthèse genet) ; `evolution_classe(ref, cur)` → `-1`/`0`/`+1`/`None` (`_GRAVITE_CLASSE`) ; `comparaison_detaillee(ref_arbre, cur_arbre, annees)` → `ComparaisonDetail` (cœur partagé `_comparaison_core` prenant des brins + résumés ; `ref_b=None` toléré). **Comparaison sur les 16 directions EXTRAPOLÉES** (`prbs_par_grade` : rayon − altération interne extrapolée − dégradation externe) — on exploite l'extrapolation au lieu de se limiter aux directions sondées. Métrique principale = **`perte_moy_par_dir`** (bois sain perdu moyen **par direction**, cm) ; **`taux_cm_an`** seulement si `annees ≥ _TAUX_ANNEES_MIN` (0.5) — sinon `None` (sur un intervalle court, `perte/annees` explose : 20 j → 155 cm/an aberrant, d'où le garde-fou). Aussi : PRBS moyenne réf/cur, compartimentation perdue active→absente (directions sondées seules), pire direction. `verdict_evolution(detail)` (classe + t/R + perte cm/direction + cm/an si dispo). `dialogs.annees_entre(date_a, date_b)` = durée (base 365.25 j) depuis les `date_releve`.
  - **Rendu PIL** (`comparaison_render`, sans Tk) : `render_evolution_section(ref_arbre, cur_arbre, size)` — **« section d'évolution »** sur la géométrie du tronc COURANT : couronne **orange** = bois sain **perdu depuis la référence** (entre l'ancien bord de cavité `R − PRBS_réf` et le nouveau `R − PRBS_courant`), cavité de référence au centre (`COLOR_ROT`), bois sain (`COLOR_WOOD`), écorce (`COLOR_BARK`). Contours **lissés** par `geometry.catmull_rom_closed` (helper `_poly`, même spline que le rendu des sections → pas d'aspect « cubique »). Choix d'Edwin (la heatmap abstraite, jugée peu lisible, a été remplacée). `render_comparison_page(...)` (page **A4 paysage** 1754×1240 : en-tête, 3 sections, tableau `metric_rows`, verdict) ; `save_comparison_png`/`save_comparison_pdf`. `metric_rows`/`verdict_evolution` partagés fenêtre ↔ page.
  - **App** : menu **Comparaison** dédié + **boutons** dans la barre du haut (la ré-inspection n'est plus cachée). `action_reinspection` (« Faire une comparaison ») charge une mission antérieure comme **base de travail** (`_install_chantier_ui`, mutualisé avec `_open_path`) **et** la fige comme référence (`deepcopy`) : on **redemande la date** (`ask_date`, aujourd'hui par défaut → la référence garde l'ancienne date), on **détache le fichier** (`current_file=None` → Enregistrer sous… forcé, jamais d'écrasement de la référence) ; `action_compare_arbre` (« Diagnostic de la comparaison ») → `open_comparison(self.chantier, ref, default_arbre=…, show_sondages=…)` ; `action_load_reference` (choix manuel) ; `_export_comparison(fmt, builder, parent)` (filedialog ancré sur `parent` + `notify_export`). **Croissance en diamètre** prise en compte : `ComparaisonDetail.rayon_ref/rayon_cur` (chaque PRBS/t/R rapporté à SON rayon) + ligne **« Diamètre du tronc »** du tableau (`metric_rows`). Aucun changement de format de fichier.
- **Checkbox « Afficher sondages »** vit **sous le canvas** (`App._build_right`), pas dans l'onglet Diagnostic — elle contrôle un état visuel toujours présent. Variable `App.var_show_sondages`. Elle gouverne aussi le **dessin des exports PDF** (`action_export_pdf_arbre`/`_mission` → `render_fiche_arbre(pdf, …, show_sondages=…)`) : pastilles masquées sur le dessin si décochée, **mais le tableau PRBS reste** (c'est la donnée). L'export PNG (`action_export_png`) la respectait déjà.
- **Titre du canvas** : `SectionCanvas._draw_titre` ne dessine que `display_name` (pas de sous-titre rayon/Ø/H/mèche — redondant avec l'onglet Identification). Aligné sur `pil_render._pil_draw_titre` (titre seul). Appelé en mono-brin ET en cépée (`_draw_cepee`).
- **Fiche d'expertise PDF = VECTORIELLE (fpdf2)** : `fiche_pdf.py` produit un PDF **natif** (texte sélectionnable/cherchable, net au zoom, ~3-4× plus léger). Approche **hybride** : le texte, le tableau PRBS, le diagnostic et la préconisation sont vectoriels ; le **dessin de section** (rose des vents) **reste rendu par Pillow** (`pil_render.render_arbre_to_pil_image`) et **collé comme image** (`pdf.image`) — le réécrire en vectoriel serait énorme et sans gain ; la **légende horizontale** est aussi rendue sur une petite image PIL et collée (fidélité). **API** : `pdf = _new_pdf()` puis `render_fiche_arbre(pdf, arbre, chantier, …)` **ajoute** la/les page(s) (une fiche + une page photos si `arbre.photos`), enfin `pdf.output(chemin)` — la **mission** réutilise **un seul** `pdf` en bouclant (concaténation native ; plus d'`append_images` Pillow). Le document travaille en **unité = 1 px @150 DPI** (`FPDF(unit=72/150, format=(1240,1754))` ⟹ A4 exact) → **coordonnées historiques conservées verbatim** ; seule la taille de police est convertie en points à la frontière (`_Page`, wrapper qui émule les ancres PIL `la`/`lm`/`rm`/`mm`/`mt`). **Polices** : DejaVu embarquées (`assets/fonts/`) enregistrées via `add_font` — l'Helvetica de base de fpdf2 est latin-1 (casserait accents + ✔/✘) ; symboles compartimentation source-unique `dialogs_shared`. **Pas de golden pixel** sur la fiche (les goldens `test_render` visent `comparaison_render`, resté raster) → smoke tests `FichePdfSmokeTests` (%PDF + nb pages) + les 2 tests de dessin redirigés sur `render_arbre_to_pil_image`. `comparaison_render.py` **reste raster** (hors périmètre).
- **Exports tableau XLSX ↔ HTML** : mise en page **propre à Pénétromètre** (plus de gabarit externe). Garder les deux **alignés** (même contenu : titre mission + identité arbre en toutes lettres ; 9 colonnes N° · Direction · Grade · Rayon · PRBS bois sain · Bois altéré · t/R coloré · Classe · Compart. ; ligne **Diagnostic** = t/R moyen + classe globale, masquée si < 3 sondées via `DiagnosticSnapshot.diagnostic_global` ; légende compartimentation ✔/✘/— ; légende des classes colorée). La colonne **PRBS = mesure brute**, le **t/R = ajusté** de la dégradation externe (comportement historique). Une modif du XLSX doit être reportée au HTML (et inversement) — cf. `tests/test_export.py::HtmlExportAlignementTests` (parité) et `::test_diagnostic_et_legendes_du_tableau` (mise en page XLSX).

## Commandes utiles

```bash
python penetrometre.py                      # Lancer l'app
pytest tests                                # suite de tests (unittest discover reste OK)
ruff check .                                # Lint
python -m mypy bareme.py geometry.py palette.py model.py diagnostic.py \
  persistence.py export.py pil_render.py fiche_pdf.py app_exports.py app_menu.py \
  app_recent.py app_settings.py ui_fonts.py app_arbres.py app_recovery.py app_export_actions.py app_fichier.py app_layout.py app_reglages.py \
  pane_identification.py pane_sondages.py pane_degradations.py \
  pane_contreforts.py pane_diagnostic.py dialogs.py section_canvas.py \
  comparaison.py comparaison_render.py undo.py tooltip.py aide_repliable.py \
  penetrometre.py photo_gallery.py \
  dialogs_settings.py dialogs_shared.py i18n.py bareme_store.py \
  template_store.py update_checker.py
```

> NB mypy : la liste ci-dessus passe **proprement (exit 0)** sous mypy
> ≥ 1.20. Le bruit « Cannot infer type of lambda » des callbacks Tk
> (`pane_sondages`, `pane_identification`) est neutralisé par module via
> `disable_error_code = misc` dans `mypy.ini` ; le faux positif du
> workaround bpo de `app_style` est réglé par `_fixed_map -> list[Any]`.
> Ne **pas** faire `mypy .` : il agrège les tests (hors périmètre typé).
> S'en tenir à la liste.

Golden-tests :

- PIL : `python -m tests.test_render --update`
- Tk : `xvfb-run -a python -m tests.test_section_canvas --update`

Build / empaquetage (distribution uniquement — le dev tourne sans build) :

- PyInstaller (référence) : `pyinstaller penetrometre.spec` → `dist/Penetrometre/`
  (installeurs Win/macOS/Linux produits par `.github/workflows/build.yml` sur
  tag `v*`).
- Nuitka (binaire compilé, option durcie) : `python build/build_nuitka.py` →
  `dist-nuitka/` (compilateur C requis ; réplique le spec).

Gestion des licences (usage interne — `private.key` requis, jamais commité) :

```bash
python gen_license.py issue "Nom du cabinet" "email@client.fr"   # licence 1 an (défaut)
python gen_license.py issue "Nom" "email" --expires 2028-01-01   # date personnalisée
python gen_license.py issue "Nom" "email" --no-expires           # illimitée
python gen_license.py verify "<clé>"                             # vérifier une clé
```

Le check de licence ne s'active que dans le **bundle PyInstaller** (`is_bundled()`).
En développement (`python penetrometre.py`), il est sauté automatiquement.
La clé publique est dans `license.py` (`_PUBLIC_KEY_B64`) ; la clé privée (`private.key`)
doit rester hors du repo git (déjà dans `.gitignore`).

## Quand tu modifies l'app

1. **Repérer le bon module** :
   - Barème métier → `bareme.py`
   - Géométrie pure → `geometry.py`
   - Modèle / mutateurs → `model.py` ; migration JSON → `persistence.py`
   - Diagnostic (calculs purs) → `diagnostic.py`
   - Rendu PNG section → `pil_render.py` ; fiche PDF A4 vectorielle (fpdf2) → `fiche_pdf.py`
   - Couleurs → `palette.py` ; exports tableau → `export.py`
   - Dialogues Tk → `dialogs.py` ; onglet UI → `pane_*.py`
   - Actions export → `app_exports.py` ; rendu Tk section → `section_canvas.py`
   - Liste d'arbres → `app_arbres.py` ; autosave/récup → `app_recovery.py`
   - Boutons/menus d'export (`action_export_*`) → `app_export_actions.py`
   - Cycle de vie fichier mission (new/open/save/save_as, récents, ré-inspection) → `app_fichier.py`
   - Construction de l'UI (`_build_*`, barre d'état, sash) → `app_layout.py`
   - Préférences/réglages + mises à jour (langue, barème, taille, contraste, logo) → `app_reglages.py`
   - Fichiers récents → `app_recent.py`
   - Orchestration App (câblage évènements, synchro, undo) → `penetrometre.py`
   - Vérification/chargement de licence → `license.py` ; dialogue d'activation → `dialogs_license.py`
   - Émission de clés clients (usage interne) → `gen_license.py`
2. **Géométrie partagée** : modifier `geometry.py` une fois, les deux renderers héritent. Pour le visuel spécifique (traits, polices, écorce) → modifier Tk **et** PIL.
3. **Modèle** : ajout de champ = OK. Renommage/suppression → migration dans `persistence.py`.
4. **Tests** : lancer la suite avant tout commit touchant modèle/géométrie/exports.
5. **Valider** : lancer l'app + sauvegarder/recharger un `.json`.

Pour les détails d'architecture, de rendu et les pièges, voir :

- `.claude/docs/architecture.md` — description détaillée de chaque module
- `.claude/docs/rendu-et-pieges.md` — pendants Tk↔PIL, pièges, ordre des couches
- `.claude/docs/cepees-plan.md` — **chantier cépées/formes** : plan
  d'implémentation par étape (0-3 faites, 4 à venir), décisions métier,
  garde-fous. À lire/mettre à jour avant de toucher au rendu multi-brins.
