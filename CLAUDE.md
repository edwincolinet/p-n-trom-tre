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
persistence.py         ← I/O JSON (save/load + migration ; v3 = brins)
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

- **Grades** : 0 à 375 par pas de 25 (16 directions). 0 = Nord, sens horaire.
  Afficher `100 gr` (pas de symbole °).
  **Unité d'affichage (option, 2026-10-20)** : Affichage → *Unité des angles*
  (Grades / Degrés), réglage de poste `SettingsStore.angle_unit`. **Le modèle,
  les fichiers et le diagnostic restent TOUJOURS en grades** (400 gr = 360°,
  25 gr = 22,5°) : l'option ne change que l'affichage, la saisie et les
  exports. Source unique `angle_units.py` (pur) : toute chaîne d'angle passe
  par `fmt`/`nombre`/`valeur`/`suffixe`/`titre_colonne` — **jamais de « gr » en
  dur** — et toute saisie par `angle_units.parse`/`depuis_unite` (retour en
  grades). `dialogs_shared.grade_choices`/`find_grade_choice`/`parse_grade`
  (libellés `100 gr — E` ou `90° — E`), `angle_head`/`largeur_head`/
  `largeur_label`/`largeur_grades_saisie` pour les champs. Bascule à chaud
  (`App.action_set_angle_unit`) via `refresh_unit()` des panes Sondages/
  Contreforts/Dégradations + `_redraw_all` (diagnostic) ; dialogues et exports
  lisent l'unité à l'ouverture/génération. Les exports (PDF, XLSX, HTML, CSV,
  synthèse, comparaison) suivent l'unité choisie. **Piège** : `_(variable)`
  est invisible au test d'i18n — les libellés d'unité sont des littéraux dans
  `angle_head`/`largeur_*`, mais l'en-tête d'export « Angle (°) » passe par
  `_(h)` (vérifié à la main : traduction ajoutée en EN/IT).
- **PRBS** = Paroi Résiduelle de Bois Sain (mesure physique invariante).
  Quand le rayon change, la PRBS reste, `bois_altéré` s'ajuste.
- **t/R** = PRBS / Rayon **local** (0–1). **Classe** = barème sur le t/R **minimal** des 16 dir. (biomécanique : la rupture part de la paroi la plus mince — **aucun t/R moyen** n'est calculé ni publié ; décision 2026-10-18, remplace l'ancienne règle « moyen »). `classe_globale` reste le nom du champ (cépée : pire brin fiable). Les seuils Vert/Orange/Rouge par défaut ont été calibrés pour une moyenne → à revalider.
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
  `.claude/docs/archives/cepees-plan.md`. **Brin courant (4a)** : `App._current_brin()` /
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
  contour fidèle via `contour_polygon`, **écorce comprise** si mesurée
  (anneau via `geometry.ring_polygon_points`, comme les renderers — sans ça
  deux brins qui se chevauchaient une fois l'écorce comptée semblaient avoir
  un écart, seul le bois était tracé ; le rayon de détection au clic/glisser
  compte aussi l'écorce), cadrage figé par `brins_layout` ; travail
  sur copie → Annuler = no-op). `App.edit_cepee_layout` applique (undo + redraw) ;
  bouton « Disposition… » de l'onglet Identification (activé si ≥ 2 brins). La
  **rotation** d'un brin (`rotation_grades`) est éditable à la **molette** dans
  cet éditeur et **appliquée au rendu** (Tk + PIL) : les helpers purs
  `contour_polygon` / `cavity_polygon` / `contrefort_zone_outline` /
  `degradation_externe_outline` / `diagnostic.sondage_render_data` prennent un
  `rotation_grades` (défaut 0.0) qui **décale l'angle de placement** tout en
  évaluant le rayon au grade LOCAL → la forme (rayon variable comprise), la
  cavité, les sondages, contreforts et dégradations pivotent ensemble ; la
  **boussole** (ticks/cardinales) reste au Nord du monde. Un **cercle étant
  invariant par rotation**, le cas circulaire garde sa primitive native
  (`create_oval`/`d.ellipse`) → goldens byte-identiques (`rotation_grades=0`
  ⟹ `g+0.0==g`). Le diagnostic (classes, t/R) est inchangé : la rotation est
  purement visuelle.
- **Diamètre local par direction** : un tronc n'est jamais parfaitement
  cylindrique. `Brin.diametres_locaux: Dict[int, float]` (grade → diamètre
  cm) porte les diamètres mesurés à certaines des 16 directions — **INDÉPENDANT
  de tout sondage** : une direction peut avoir un diamètre local sans PRBS
  mesurée là (p. ex. un méplat repéré au pied à coulisse entre deux sondages,
  sans multiplier les mesures au résistographe — sinon les directions
  intermédiaires retombent sur le diamètre général et le contour « vague »
  au lieu de suivre le méplat réel). Une direction absente de la table
  retombe sur le diamètre général du brin (`Brin.rayon_tronc_cm`, onglet
  Identification). Source unique : `Brin.rayon_a_grade(grade)` — lecture
  exacte de la table des 16 rayons locaux (`Brin._rayon_locaux`) aux grades
  canoniques (sondages, dégradations, contreforts, diagnostic) ; entre deux
  directions mesurées voisines, **interpolation lissée par cosinus**
  (`(1-cos(π·t))/2`) — raccord à dérivée nulle à chaque direction mesurée
  (pas d'angle vif, contour moins « facetté » qu'une interpolation linéaire
  pure) tout en restant **strictement bornée** entre les deux valeurs
  voisines (jamais de dépassement, contrairement à une spline type
  Catmull-Rom) — pour le contour dessiné, échantillonné à des grades
  quelconques (`geometry.contour_polygon`). D'où le t/R local ci-dessus.
  `Brin.a_rayon_variable` (True si un rayon local diffère du général)
  pilote, comme l'ancien `est_ovale`, le choix entre la primitive cercle
  native et `contour_polygon` dans les deux renderers. Saisie **en ligne**
  dans la grille Sondages (colonne « Ø local (cm) », optionnelle, **toujours
  active** — pas de dépendance à un sondage sur la ligne) via
  `Brin.set_diametre_local(grade, diametre_cm)` (réaligne le bois altéré du
  sondage éventuellement présent à cette direction, **sans jamais retoucher
  sa PRBS** ; borne la profondeur des dégradations co-localisées) — pas
  d'éditeur séparé (a remplacé le tronc ovale à 2 axes,
  `rayon_petit_axe_cm`/`orientation_grade`/`ask_forme_tronc`, strictement
  moins expressif : jusqu'à 16 points mesurés au lieu de 2). Fichiers
  antérieurs à cette fonctionnalité : la forme ovale n'est pas migrée, ils
  repassent en section circulaire au chargement (clés JSON orphelines
  silencieusement ignorées) ; un diamètre local qui vivait encore sur le
  `Sondage` (version transitoire du 2026-08-19) est migré vers
  `Brin.diametres_locaux` au chargement (`persistence._brin_from_dict`).
- **Diagnostic non fiable si < 3 sondages** → exports masquent t/R minimal + classe.
  **Couverture angulaire (2026-10-28)** : avec ≥ 3 sondages mais un secteur > 180° (200 gr) sans aucun sondage, la classe reste publiée et un **avertissement non bloquant** s'affiche (`diagnostic.couverture_insuffisante` / `couverture_avertissement` ; onglet Diagnostic, fiche PDF, tableau PRBS, colonne « Couverture sondages » de la synthèse).
- **Dégradations externes** consomment du bois sain : `PRBS_ajustée = sain −
  profondeur_bois_deg`. **L'écorce n'est jamais du bois sain** (le rayon est
  déjà sous écorce) — invariant. Le champ `DegradationExterne.comprend_ecorce:
  bool = True` décrit la **géométrie** de la dégradation. Saisi via le
  sélecteur **« Zone dégradée »** (combobox *readonly* « Écorce + bois »
  [True, défaut] / « Bois seul » [False]) de la grille **et** du dialogue
  `edit_degradation` — libellés et helpers source-unique dans `dialogs`
  (`ZONE_DEGRADEE_CHOICES` reste la forme française canonique, comparée
  telle quelle ; `zone_degradee_label`/`zone_degradee_choices()` traduisent
  à l'affichage via `_()`, `zone_degradee_to_bool` reconvertit — même piège
  que les filtres avancés : ces trois helpers passent une **variable** à
  `_()`, invisible au test `test_i18n.py`, vérifié à la main),
  rappel `ZONE_DEGRADEE_AIDE` sous la grille. A remplacé une case à cocher
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
- **Barème configurable par groupes de ports** : les seuils Vert/Orange/Rouge
  sont un réglage de **poste** (`~/.penetrometre/bareme.json`), organisé en
  **groupes de ports librement composés par l'expert** — `bareme.GroupeBareme`
  (`nom`, `ports: Tuple[str,...]`, `seuil_vert`, `seuil_orange`), `_groupes`
  (état module, remplace un ancien binôme figé « libre »/« strict »). Un
  **port individuel** n'est qu'un groupe à un seul port : aucune distinction
  de code entre « régler port par port » et « regrouper des ports » — c'est
  la même mécanique. `GROUPES_DEFAUT` (2 groupes, mêmes seuils qu'avant cette
  fonctionnalité) reste la **valeur par défaut** de tout nouveau poste et du
  bouton « Restaurer » de l'éditeur. `classer_prbs(ratio, port)` cherche le
  groupe courant contenant ce port (`groupe_pour_port`) ; si aucun (config
  altérée à la main) retombe sur le groupe de `GROUPES_DEFAUT` couvrant ce
  port — jamais de crash, jamais un classement arbitraire silencieux.
  **Éditeur** (`Affichage → Barème…`, `dialogs_settings.ask_bareme_settings`) :
  une ligne éditable par groupe (nom, seuils Vert/Orange, suppression) +
  un **tableau d'assignation port → groupe** (une `tk.StringVar` par port,
  partagée par ses `Radiobutton` dans chaque colonne-groupe) — l'exclusivité
  Tk native **garantit par construction** qu'un port appartient à exactement
  un groupe, jamais par validation a posteriori (même philosophie que la
  grille Sondages). Supprimer un groupe réaffecte ses ports au groupe
  précédent (jamais d'orphelin) ; un dernier groupe ne peut pas être
  supprimé. Seule validation a posteriori : chaque groupe a ≥ 1 port et
  `0 < orange < vert ≤ 1`.
  **Traçabilité** (inchangée dans son principe) : deux opérateurs aux
  réglages différents classent les mêmes mesures différemment. Les groupes
  **en vigueur à l'enregistrement** sont écrits dans la mission
  (`Chantier.bareme_seuils`, forme brute JSON — liste de
  `{"nom":.., "ports":[...], "vert":.., "orange":..}`, un par groupe ; champ
  **duck-typé**, `model.py` ne dépend pas de `bareme.py`) et **cités dans
  chaque livrable** : pied de la fiche PDF, bannière des exports XLSX/HTML,
  ligne `# Barème appliqué` en tête des CSV. Source unique des libellés :
  `bareme.description_seuils` / `description_seuils_mission`. Frontière
  JSON : `groupes_vers_brut`/`seuils_depuis_brut` (ce dernier **migre
  silencieusement** l'ancien format à 2 groupes fixes — postes et missions
  antérieurs à cette fonctionnalité — et comble tout port manquant d'une
  config incomplète par un groupe de secours). **Ouvrir une mission
  n'applique JAMAIS son barème** (ce serait reconfigurer le poste en douce) :
  l'écart est seulement signalé en barre d'état par
  `App._avertir_bareme_different`. Liste vide = mission antérieure à cette
  trace ⟹ « inconnu », pas de migration.
- **Unicité** : un seul sondage par direction, pas de dégradations qui se
  chevauchent (arcs mitoyens bout-à-bout autorisés), un seul contrefort par
  grade central. Sondages et contreforts : **garantie par construction**
  (grilles 16 directions, une ligne par grade). Dégradations : helper pur
  `model.degradations_chevauchements` (exclut les grades-frontières
  mitoyens), partagé entre `dialogs.edit_degradation` (clic Valider) et la
  saisie en place de `pane_degradations` (valeur fautive rétablie).

## Conventions de code

- Pas de dépendance sans bonne raison. Compat Python 3.10+.
- **Photos = entrée semi-fiable** : un `.json` de mission circule entre
  confrères. `Arbre.photos` contient des chemins libres que l'app ouvre et
  embarque dans le PDF. Toute résolution passe donc par
  `photo_paths.resolve_photo` (pur) : extension dans `PHOTO_SUFFIXES`,
  chemin relatif **confiné** au dossier de la mission (`..` et symlinks
  sortants neutralisés), chemin absolu toléré pour compat mais signalé
  (`hors_mission`). En complément, `photo_gallery._view_photo` vérifie que
  le fichier est **réellement décodable comme image** avant de le passer à
  la visionneuse système — sans quoi un `.desktop` renommé `.png` serait
  exécuté par `xdg-open`. Le motif de refus est affiché sur la vignette
  (un garde-fou silencieux passerait pour un bug). **Dans la fiche PDF**
  (`fiche_pdf._render_photos_page`), la légende sous chaque photo est
  « Photo 1 », « Photo 2 »… — **jamais** le nom de fichier : celui-ci est
  un chemin libre non maîtrisé (récupéré ailleurs, mal nommé) qui se
  retrouverait sinon imprimé tel quel dans un document remis au client.
- **Threads et Tk : ne pas mélanger.** Les tâches longues (export PDF de
  mission) se découpent en tranches sur la boucle Tk — jamais dans un
  thread worker. Deux raisons vérifiées en test : `after()` appelé depuis
  un thread lève « main thread is not in main loop » (avalé sans trace par
  un thread daemon), et le **GC** peut s'exécuter dans le worker et y
  finaliser un objet Tk, ce qui fait **abandonner le processus**
  (`Fatal Python error: Aborted`). Cf. `dialogs.ProgressDialog` (progression
  + Annuler, `update()` entre les tranches) et
  `app_exports.export_pdf_mission`. La seule exception tolérée est
  `update_checker`, qui ne touche aucun widget.
- **Polices PIL mémorisées** : `pil_render._pil_font(size, variant)` est sous
  `lru_cache`. Sans ça, chaque `d.text(...)` reconstruisait un `FreeTypeFont`
  (réouverture du .ttf + cache de glyphes vide) — le halo des lettres
  cardinales tire 24 tracés par lettre, ce qui représentait l'essentiel du
  temps d'export PDF (÷2 après correction). Réutiliser l'objet police ne
  change rien au rendu : les golden-tests PIL le verrouillent.
- **Redraw débouncé partout** : `SectionCanvas` regroupe ses `<Configure>`
  (80 ms, `_RESIZE_DEBOUNCE_MS`) comme `App._debounced_redraw`. Un glissement
  de poignée de la `PanedWindow` émet un `<Configure>` par pixel ; seule la
  dernière taille compte.
- **Journal = artefact de support** : il est explicitement destiné à être
  envoyé par le client. Pas d'email en clair, pas
  de chemin complet de mission (nom de fichier seul).
- Tout en français (UI + docstrings).
- Pas de `print` — logger applicatif (`~/.penetrometre/penetrometre.log`).
- Exports : `log.exception(...)` avant `messagebox.showerror`.
- Compat fichier bidirectionnelle : ajout champ = OK (default) ; renommage/suppression = migration explicite dans `persistence.chantier_from_dict`. **Format v3** : la géométrie/mesures sont passées d'`arbre` à `arbre.brins[i]` ; un fichier v≤2 (champs à plat) est migré en un genet à **brin unique** (cf. `_brin_from_dict`).
- **Rendu de forme (cercle vs rayon variable)** : les primitives partagées de `geometry` (`contrefort_zone_outline`, `degradation_externe_outline`, `tick_endpoints`, `cardinal_label_positions`) acceptent un rayon `RadiusSpec` = **scalaire OU fonction `grade→rayon`** ; `contour_polygon` échantillonne le contour à rayon variable (interpolé entre les directions mesurées, cf. `Brin.rayon_a_grade`). Les renderers passent `arbre.rayon_a_grade` (constant si circulaire). **Cas circulaire = chemin primitif natif** (`d.ellipse` / `create_oval`) conservé sous une branche `if a_rayon_variable` → rendu **byte-identique**, goldens intacts (seule la fixture `ovale` s'ajoute). Toute évolution du contour doit garder cette branche pour ne pas casser les goldens circulaires.
- **Piège corrigé (2026-08-19) — anneau d'écorce à rayon variable** : peindre un anneau (écorce, bande de contrefort…) comme UN SEUL polygone simple « contour externe + contour interne inversé » (`outer + inner[::-1]`) referme la forme via **deux ponts à des angles légèrement différents** (dernier échantillon ~397.5 gr / premier échantillon 0 gr, écart = pas d'échantillonnage) au lieu du même angle aller-retour ⟹ un fin coin non rempli apparaît à la jointure (rectangle blanc visible au Nord dans l'écorce, `_draw_ecorce`/`_pil_draw_ecorce`, dès que `a_rayon_variable`). Corrigé par `geometry.ring_polygon_points(outer, inner)` : reboucle explicitement `outer` sur lui-même avant le pont vers `inner[0]` → les deux ponts sont l'aller-retour du MÊME segment, largeur nulle. **Tout nouvel anneau construit par cette technique doit passer par ce helper**, jamais par `outer + inner[::-1]` à la main.
- Écriture atomique : `save_chantier` écrit dans un `.tmp` puis `os.replace` — le fichier original survit en cas de crash.
- **Sauvegardes glissantes** (`persistence.write_backup`/`list_backups`/`_prune_backups`, purs) : à chaque `action_save` réussi, une **copie horodatée** `stem_AAAAMMJJ-HHMMSS.json` est déposée dans `~/.penetrometre/backups/` et les anciennes purgées (on garde `BACKUP_KEEP_DEFAULT=12` par mission, identifiée par `stem`+`suffix`). **Best-effort** : un échec est loggé et **n'interrompt jamais** l'enregistrement réel (`write_backup` renvoie `None`). Complémentaire de l'autosave : l'autosave protège du **crash**, le backup de l'**écrasement/corruption** (une mission = une journée de relevés). Accès via **Fichier → Ouvrir le dossier des sauvegardes…** (`App.action_open_backups_folder`). `list_backups` trie du plus récent au plus ancien (nom horodaté ⟹ ordre lexicographique = chronologique).
- **Autosave anti-crash** (`persistence.save_recovery`/`load_recovery`/`clear_recovery`, câblage dans `App`) : tick `after` toutes les 60 s (`_AUTOSAVE_INTERVAL_MS`) qui n'écrit `~/.penetrometre/recovery/autosave.json` **que si `_dirty`**. Le fichier enveloppe `chantier_to_dict` + métadonnées (`saved_at`, `original_file`). **Invariant clé** : l'autosave est effacé dès qu'on atteint un état propre (`action_save`, `action_new`, `_open_path`) **et à la fermeture normale** (`_on_close`, même en abandonnant des modifs) — donc sa seule présence au démarrage ⟺ crash précédent avec travail non enregistré. `_check_recovery_on_startup` (programmé via `after(200, …)` pour s'afficher sur une UI déjà mappée) propose la reprise ; `_restore_recovery` recharge l'UI, repointe `current_file` sur l'original s'il existe encore, et remet `_dirty=True`. Écriture atomique (`.tmp` + `os.replace`) comme `save_chantier`.
- **Champs numériques UI** : filtrage à la frappe via `dialogs.validate_numeric` (validateur Tk `validate="key"`) — seuls chiffres + un séparateur décimal `.`/`,` acceptés. Parsing via `dialogs.to_float` (accepte `2,5` et `2.5`). Branché sur les 3 dialogues (Sondage/Dégradation/Contrefort) + les 6 champs numériques de `pane_identification`. `_parse_float("")` renvoie `None` (pas `0.0`). `set_rayon` n'est appelé qu'au focus-out (jamais pendant la frappe) pour éviter la destruction irréversible des PRBS par valeurs intermédiaires.
- **N° d'arbre** : doit contenir au moins un chiffre (« 1 », « 42 », « 12 bis » OK ; « bis » seul refusé). Règle appliquée dans `pane_identification._revert_num_if_invalid` (revert au focus-out) et `App.action_rename_arbre` (boucle de retry pré-remplie).
- **Compartimentation** : valeurs `"active"`, `"absente"`, `"non renseignée"` (anciennement `"-"`, migré silencieusement au load via `persistence.chantier_from_dict`). **Symboles source-unique** dans `dialogs_shared` (`COMPART_GLYPH`/`COMPART_COLOR` + `compart_glyph`/`compart_color`/`compart_visual`) : **✓** active (vert `#2D7A3E`) · **✗** absente (rouge `#C0392B`) · **–** non renseignée (gris muted `#55605A`). Le **même** glyphe est affiché à la **saisie** (combobox « ✓ active » via `compart_label`/`compart_from_label`, qui préfixe/retire le glyphe) **et** dans **tous les exports** (cellule XLSX/HTML/PDF, symbole seul + légende). Coche/croix **fines** U+2713/U+2717 + tiret fin U+2013 (présentes dans DejaVu → rendu PDF garanti) — restylées « traits légers » (esprit épuré) depuis les « ballot » épais U+2714/U+2718 ; **pour rehabiller les symboles, ne changer que `dialogs_shared`** (tout en découle : légendes XLSX/HTML branchées sur `compart_glyph`, cellules via `compart_visual`). `export.py` et `fiche_pdf.py` importent ces helpers (openpyxl : `.lstrip("#")` sur la couleur).
- **Liste d'arbres (état / risque)** : colonne **État** = forme du glyphe (`○` vide · `◐` partiel · `●` fiable ≥ 3 sondages) ; colonne **Risque** = mot Vert/Orange/Rouge (`—` si non fiable) ; **couleur de ligne = uniquement la classe de risque** (incomplets en gris neutre). Source : `App._arbre_etat`. Footer de triage `_update_etat_footer` (toute la mission, jamais la sous-liste filtrée) + bouton « ⏭ Prochain arbre à finir ».
- **Workaround bpo-36468 (ttk.Treeview)** : depuis Python 3.7, les `tag_configure(foreground=…)` sont ignorés à cause d'entrées par défaut dans `style.map`. `app_style._fixed_map` retire les entrées `("!disabled", "!selected", …)` pour que les tags prennent la main. Sans ça, les pastilles d'état resteraient blanches.
  **Contraste activé/désactivé d'une case à cocher (2026-08-20)** : sujet apparenté — le thème `clam` ne donne par défaut quasi aucune différence visuelle entre `Panel.TCheckbutton` activée-vide et désactivée (même contour, remplissage à peine différent), au point de passer pour un contrôle inerte. `s.map("Panel.TCheckbutton", indicatorbackground=[("disabled", COLOR_BG), ("!disabled", "white")], indicatorforeground=[("selected", COLOR_ACCENT)])` (`app_style.py`) tranche net : blanc franc activée, gris plat désactivée, coche à la couleur d'accent.
- **Filtre de la liste d'arbres** : cinq filtres cumulés (ET) dans `_arbre_matches_filter` (texte n°/essence + Risque/Urgence/Échéance/Sondages dans un panneau repliable). Ils ne font que **masquer des lignes** : les `iid = a{index}` restent indexés sur la position réelle, le modèle n'est jamais altéré, le footer reste sur toute la mission. Remis à zéro au chargement d'une mission et à la création d'un arbre. **Piège i18n** : `_(une_variable)` est invisible au test `test_i18n.py` → vérifier à la main les constantes ainsi traduites ; Vert/Orange/Rouge et les niveaux d'urgence restent en français partout (vocabulaire de domaine).
- **Ajout d'arbre** : bouton « ＋ Ajouter » (`action_add_arbre`, `Ctrl+T`) = nouvel arbre, tous champs par défaut. N° via `_next_arbre_numero` (max numérique + 1). **« Hériter du précédent »** (variante qui recopiait l'identité/protocole — essence, port, mèche, écorce, hauteur de sondage — sans la géométrie mesurée, pour les alignements d'arbres identiques) a été retirée (2026-09-05) : jugée floue à l'usage (le tooltip promettait même, par erreur, de recopier Ø et hauteur d'arbre — jamais fait par le code) et trop proche en apparence d'`action_dup_arbre` (« Dupliquer »), qui clone lui tout l'arbre y compris ses mesures.
- **Navigation clavier entre arbres** : `Ctrl+PgDown`/`Ctrl+PgUp` → `action_next_arbre`/`action_prev_arbre` → `_select_arbre_relative(±1)` (bornée, sans boucle). Donne d'abord le focus clavier à la liste (`tree_arbres.focus_set()`) pour déclencher le `<FocusOut>` d'une case de grille en cours d'édition avant de basculer. Libre de conflit avec la navigation entre **onglets** : `nb.enable_traversal()` (appelé dans `_build_center`) lie `Ctrl+Tab`/`Ctrl+Maj+Tab` pour compléter le flux de saisie au clavier (rayon → onglet suivant → sondages…) — disjoint de `Ctrl+PgUp/PgDown` (arbres) et `Ctrl+Z/Y`. Documenté dans le popup `action_shortcuts`.
- **Menu contextuel clic droit** sur la liste d'arbres : Renommer/Dupliquer/Supprimer. `tk_popup` SANS `grab_release()` (anti-pattern qui annule le grab) + `bind("<FocusOut>")` sur le menu pour fermeture au clic externe.
- **Canvas interactif** : `section_canvas.SectionCanvas` accepte un `host` optionnel (l'App) ; `tag_bind("sondage_item"/"degradation_item"/"contrefort_item", "<Button-1>")` ouvre le dialogue d'édition correspondant. Curseur `hand2` au survol. Dispatch via tags `<type>_idx_<i>` pour retrouver l'objet métier.
- **Dialogues modaux** : `dialogs._make_modal(dlg, parent)` séquence `update_idletasks → transient → wait_visibility → grab_set → focus_set`. Appeler `grab_set` avant que le WM ait mappé la fenêtre fait apparaître le dialogue **vide** sur Linux/X11 (race entre grab et rendu). Tous les dialogues passent par ce helper, qui est appelé APRÈS la création des widgets. Chaque dialogue d'édition (Sondage/Dégradation/Contrefort) bind `<Return>`→Valider, `<Escape>`→Annuler, et pose le focus initial sur son 1er champ utile.
- **Saisie texte thémée** : `dialogs.ask_string(parent, title, prompt, initial, info=…)` remplace `simpledialog.askstring` (look système incohérent). Renvoie `None` si annulé, la chaîne (sans `strip`) si validé — `""` validé ≠ `None`. Utilisé par `action_rename_arbre`.
- **Barre d'état** : `App._build_statusbar()` — bouton « Enregistrer » toujours visible + indicateur persistant (`lbl_save_state`, source unique `dialogs_shared.save_state_label`) ; `notify_export(path, label)` signale le succès d'un export sans modale.
- **Date du relevé** : saisie clavier normalisée `JJ/MM/AAAA` (`dialogs.normaliser_date`, valeur d'avant rétablie si illisible, date facultative = `""`) ou calendrier Tk pur (`dialogs.ask_date`, `title`/`prompt`/`info` optionnels).
- **Infobulles** : `tooltip.Tooltip(widget, texte)` — bindings `add="+"` pour ne pas écraser ceux du widget. Sert à rappeler les accélérateurs (bouton « ＋ Ajouter » → Ctrl+T) et décrire le bandeau d'export (2 boutons + menu « Tableau »).
- **Aide repliable** : `aide_repliable.AideRepliable(parent, *paragraphes, titre="Aide", wraplength=…)` — bloc d'aide derrière un en-tête cliquable « ⓘ Aide ▸/▾ », **replié par défaut** (discret pour l'opérateur expérimenté, dépliable au clic à la 1ʳᵉ utilisation). Remplace les libellés `Muted.TLabel` ⓘ permanents (identification : couplage Ø↔rayon + invariance PRBS ; sondages : sémantique case vide/effacer ; canevas : clic = éditer/ajouter). Fonctionne en `grid` comme en `pack` (gère sa disposition interne ; le parent place le widget). État conservé tant que le widget vit — les panes ne sont construits qu'une fois, pas par arbre. S'appuie sur les styles `Panel.TFrame`/`Muted.TLabel`.
- **Canevas — ajout par clic** : un clic sur une direction libre du dessin ajoute un sondage à ce grade (`App.open_add_sondage`) ; un clic sur une direction déjà sondée l'édite. `SectionCanvas._on_click_background` convertit le pixel en grade (inverse de `geometry.polar_to_xy`), mémorise la géométrie du dernier rendu dans `self._geom`, et ignore les clics sur un élément interactif (garde par tags).
- **Raccourci export** : `Ctrl+E` → `App.action_export_pdf_arbre`. Bind dans `App.__init__` (comme Ctrl+Z/Y) via `_on_export_shortcut`, qui **ne déclenche pas** si un `Entry`/`Combobox` a le focus (Ctrl+E = « fin de ligne » dans les widgets Tk).
- **Menu Export = point d'entrée unique des exports**, organisé par format (PDF / PNG / XLSX / CSV / HTML). Le menu Fichier ne garde que le cycle de vie du fichier ; l'impression directe a été supprimée (imprimer un PDF exporté depuis un lecteur).
- **Fichiers récents** : `~/.penetrometre/recent.json` (8 entrées max). `App._push_recent_file(path)` appelé après chaque open/save. Sous-menu `Fichier → Ouvrir récent` reconstruit par `app_menu.refresh_recent_menu(app)`.
- **Adaptation petits écrans** : `App.__init__` clampe la geometry à 95 % de l'écran et fixe `minsize(1100, 680)` pour rester utilisable sur laptops 1366×768.
- **Disposition 3 colonnes** : `tk.PanedWindow` horizontale (`_paned`, la classique pour le `minsize` par panneau) ; positions persistées (`_save_sash_positions` / `_restore_sash_positions`, `sash_place` **différé** sinon `TclError`).
- **Accessibilité** : `ui_scale` [0.8, 1.6] et `high_contrast` sont des réglages de poste (`SettingsStore`). `tk scaling` est inopérant : le levier est de multiplier la taille de chaque police via `ui_fonts.font` (le **dessin n'est PAS scalé** — goldens). Le contraste élevé ne touche ni les accents, ni les fonds, ni le dessin. Point unique `App._apply_styles()` pour ne jamais perdre le mode.
- **Progression dans les onglets** : `App._refresh_tab_progress()` (appelé dans `_redraw_all`) préfixe les onglets de l'étape par un glyphe d'avancement — **même vocabulaire que les pastilles** (`○` à faire · `◐` en cours · `●` prêt). Identification (`●` si rayon>0 et essence saisie), Sondages (glyphe de complétude via `_arbre_etat`), Diagnostic (`●` si `_arbre_diag_fiable`). La **forme** porte l'info (lisible en daltonisme ; ttk n'autorise pas de couleur par onglet). Dégradations/Contreforts restent sans glyphe (étapes optionnelles — un `○` y suggérerait à tort un manque). `self.nb` mémorisé dans `_build_center`.
- **Saisie = grilles 16 directions (sondages, contreforts) et tableau en place (dégradations)** : case vide = absent, valeur (y compris 0) = présent, effacer = supprimer **au focus-out** (jamais à la frappe) ; unicité garantie par construction ; undo capturé au focus-in et empilé au focus-out si changé ; mutations notifiées sans `refresh()` de la grille pendant la frappe ; PRBS plafonnée au rayon **local** ; « Ø local » indépendant de tout sondage ; les callbacks de dégradation retrouvent l'objet par **identité** (`is`), jamais `in`/`remove`.
- **Synthèse de mission** : `diagnostic.mission_synthesis_rows(chantier)` (pur), une ligne par arbre (+ sous-lignes de brin), classe masquée si < 3 sondages (« Non fiable » ≠ « — »). Exports CSV/XLSX dans `export_synthesis.py` (colonnes repérées par leur en-tête).
- **Préconisation** : champs **genet** `urgence` (∈ `URGENCE_NIVEAUX`), `echeance`, `preconisation` (+ suivi), saisis dans l'onglet Diagnostic. **Valeur persistée toujours française** : affichage via `translate_values`, lecture via `untranslate_value` (piège corrigé 2026-08-20).
- **Comparaison inter-missions (ré-inspection)** : fenêtre `comparaison.open_comparison` (référence | courant | évolution), un bloc par brin pour une cépée, export PDF/PNG. Calcul pur dans `diagnostic_comparaison`, rendu PIL dans `comparaison_render`. Les 16 directions sont comparées sur la PRBS **extrapolée**, avec le nombre de directions **réellement mesurées aux deux dates** ; verdict à deux niveaux (titre + détail) qui tient compte de toutes les directions (un t/R minimal stable ne masque pas une perte ailleurs) ; section d'évolution orange (aggravation) / vert (amélioration). Réutilise le `tk.Menu` de la fenêtre principale ; case « Afficher sondages » partagée.
- **Case « Afficher sondages »** (`App.var_show_sondages`, sous le canvas) : gouverne aussi le dessin des exports PDF/PNG (le tableau PRBS reste). Bascule pilotée par `trace_add("write")`, car la fenêtre de comparaison pose sa propre case sur la **même** variable.
- **Titre du canvas** : `SectionCanvas._draw_titre` ne dessine que `display_name` (pas de sous-titre rayon/Ø/H/mèche — redondant avec l'onglet Identification). Aligné sur `pil_render._pil_draw_titre` (titre seul). Appelé en mono-brin ET en cépée (`_draw_cepee`).
- **Fiche d'examen approfondis PDF = vectorielle (fpdf2)** (`fiche_pdf.py`) : approche hybride — texte, tableau PRBS, diagnostic et préconisation en vectoriel ; dessin de section et légende rendus par Pillow et collés en image. API : `pdf = _new_pdf()` puis `render_fiche_arbre(pdf, …)` ajoute la/les page(s) (une mission réutilise un seul `pdf`). Document en **unité = 1 px @150 DPI** (coordonnées historiques conservées) ; polices Jost + Source Sans 3 (`assets/fonts/`), DejaVu en dernier recours ; **ni ⚠ ni emoji** (▲ à la place). Tableau PRBS paginé. Pas de golden pixel sur la fiche (smoke tests). `comparaison_render.py` reste raster.
- **Exports tableau XLSX ↔ HTML** : mise en page **propre au Pénétromètre Silvavenir** (plus de gabarit externe). Garder les deux **alignés** (même contenu : titre mission + identité arbre en toutes lettres ; 9 colonnes N° · Direction · Grade · Rayon · PRBS bois sain · Bois altéré · t/R coloré · Classe · Compart. ; ligne **Diagnostic** = t/R minimal + classe, masquée si < 3 sondées via `DiagnosticSnapshot.diagnostic_global` ; légende compartimentation ✓/✗/– ; légende des classes colorée). La colonne **PRBS = mesure brute**, le **t/R = ajusté** de la dégradation externe (comportement historique). Une modif du XLSX doit être reportée au HTML (et inversement) — cf. `tests/test_export.py::HtmlExportAlignementTests` (parité) et `::test_diagnostic_et_legendes_du_tableau` (mise en page XLSX).

## Commandes utiles

```bash
python3 penetrometre.py                      # Lancer l'app
pytest tests                                # suite de tests (unittest discover reste OK)
ruff check .                                # Lint
python3 -m mypy bareme.py geometry.py palette.py model.py diagnostic.py \
  persistence.py export.py export_synthesis.py diagnostic_comparaison.py pil_render.py fiche_pdf.py app_exports.py app_menu.py \
  app_recent.py app_settings.py ui_fonts.py app_arbres.py app_recovery.py app_export_actions.py app_fichier.py app_layout.py app_reglages.py \
  pane_identification.py pane_sondages.py pane_degradations.py \
  pane_contreforts.py pane_diagnostic.py dialogs.py dialogs_cepee.py dialogs_saisie.py section_canvas.py \
  comparaison.py comparaison_render.py undo.py tooltip.py aide_repliable.py \
  penetrometre.py photo_gallery.py \
  dialogs_settings.py dialogs_shared.py i18n.py bareme_store.py \
  template_store.py update_checker.py photo_paths.py icons.py chrome_icons.py
```

> NB mypy : la liste ci-dessus passe **proprement (exit 0)** sous mypy
> ≥ 1.20. Le bruit « Cannot infer type of lambda » des callbacks Tk
> (`pane_sondages`, `pane_identification`) est neutralisé par module via
> `disable_error_code = misc` dans `mypy.ini` ; le faux positif du
> workaround bpo de `app_style` est réglé par `_fixed_map -> list[Any]`.
> Ne **pas** faire `mypy .` : il agrège les tests (hors périmètre typé).
> S'en tenir à la liste.

Golden-tests :

- PIL : `python3 -m tests.test_render --update`
- Tk : `xvfb-run -a python3 -m tests.test_section_canvas --update`

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
