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
ui_fonts.py            ← échelle des polices + typographie/espacements nommés (design system, pur)
icons.py               ← glyphes d'icônes du chrome Tk, monochromes (design system, pur)
photo_paths.py         ← résolution CONFINÉE des chemins de photos (jail mission + whitelist, pur)
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
license.py             ← licence offline Ed25519 : vérification, repère de date monotone, essai (pur)
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
model.py + palette.py + tooltip.py + aide_repliable.py + app_recent.py + app_settings.py + ui_fonts.py + icons.py + photo_paths.py
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
- **Diagnostic non fiable si < 3 sondages** → exports masquent t/R moyen + classe.
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
- **Licence : portée réaliste.** La vérification est locale et hors-ligne ;
  elle n'est pas inviolable et ne cherche pas à l'être. Ce qui est garanti :
  signature Ed25519 non forgeable, refus d'une licence utilisée **avant sa
  date d'émission** (date signée), et décisions de date prises sur
  `license.today_effectif()` — plancherée par un repère monotone
  (`state.json`) pour qu'un recul d'horloge ne ressuscite ni une licence
  expirée ni un essai consommé. L'essai est écrit en double
  (`trial.json` + `state.json`) et `essai_deja_consomme()` — et non
  `get_trial_info()` — décide d'afficher le bouton « Essai gratuit »
  (les deux valent `None` quand l'essai est **expiré**). Tous ces fichiers
  sont en 0600 sous un dossier 0700, **y compris sur les installations
  antérieures** au durcissement : `durcir_config_existante()`, appelée par
  `main()` à chaque démarrage, resserre le dossier et les 3 fichiers privés
  s'ils sont trop permissifs — sans quoi la `license.key` d'un client
  resterait en 0644 indéfiniment (on ne la réécrit qu'à la réactivation).
  Les autres fichiers (`bareme.json`, `recent.json`, le log) ne sont pas
  touchés : le 0700 du **dossier** interdit déjà la traversée.
  Émission : `--machine-id` est **requis**
  (`--any-machine` pour y renoncer explicitement) et la clé privée vit hors
  du dépôt (`~/.penetrometre-keys/`, `$PENETROMETRE_LICENSE_KEY`).
- **Journal = artefact de support** : il est explicitement destiné à être
  envoyé par le client. Pas d'email en clair (`license.masquer_email`), pas
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
- **Indicateurs d'état de la liste d'arbres** : `App._arbre_etat(arbre)` renvoie `(glyphe, risque, tag)` pour **deux colonnes distinctes** (`État` + `Risque`), qui lèvent l'ancienne ambiguïté où la **couleur de ligne** signifiait *complétude* pour `○/◐` mais *classe de risque* pour `●` (ttk.Treeview ne colore qu'une ligne entière, pas une cellule → un seul sens possible par couleur). Désormais :
  - **Colonne État = forme du glyphe = complétude** (lisible en daltonisme rouge-vert) : `○` `etat_vide` (0 sondage OU rayon=0), `◐` `etat_partiel` (1-2 sondages), `●` (≥3 sondages, fiable).
  - **Colonne Risque = mot** « Vert/Orange/Rouge » (= `gd.classe_globale`, qui EST déjà la chaîne) dès que fiable, `—` sinon → risque lisible **sans dépendre de la couleur**.
  - **Couleur de ligne (`tag`) = uniquement la classe de risque** : `etat_ok_vert`/`_orange`/`_rouge` (via `COULEUR_CLASSE`) pour les fiables ; **les incomplets `○/◐` sont en gris NEUTRE** (`etat_vide`/`etat_partiel` → `COLOR_MUTED`), plus en rouge/orange. La couleur ne signifie donc plus qu'une chose. Repli `etat_ok` (vert) si fiable mais classe indispo.
  Le seuil **fiable ≥ 3** est **aligné** sur la règle métier de fiabilité (« < 3 sondages → exports masqués »). NB : l'extrapolation géométrique de la cavité (`compute_alteration_par_grade`) reste active dès 2 sondages — découplé du seuil de fiabilité. Refresh ligne par ligne via `_refresh_current_arbre_etat()` appelé dans `_redraw_all` (après toute mutation, debounce). Footer `lbl_etat_footer` = **vue de triage macro** de la mission (`_update_etat_footer`, sans argument, recalculé sur **toute** la mission — jamais la sous-liste filtrée) : répartition `N rouge · N orange · N vert · N à finir (total)` (classes via `_arbre_etat`, « à finir » = incomplets `○/◐`). Répond au « puis-je quitter le site ? » sans ouvrir l'export de synthèse. Son **compagnon de triage** : le bouton « ⏭ Prochain arbre à finir » (sous le footer) + l'entrée menu Arbres → `action_next_a_finir` saute au prochain arbre non fiable en **bouclant** (parcours cyclique depuis le courant), **vide les filtres** si besoin pour rendre la cible visible. Les largeurs des 4 colonnes + la largeur par défaut du panneau gauche (`PanedWindow`) sont calibrées pour que `Risque` tienne malgré la scrollbar verticale ; le panneau reste élargissable à la souris.
- **Workaround bpo-36468 (ttk.Treeview)** : depuis Python 3.7, les `tag_configure(foreground=…)` sont ignorés à cause d'entrées par défaut dans `style.map`. `app_style._fixed_map` retire les entrées `("!disabled", "!selected", …)` pour que les tags prennent la main. Sans ça, les pastilles d'état resteraient blanches.
  **Contraste activé/désactivé d'une case à cocher (2026-08-20)** : sujet apparenté — le thème `clam` ne donne par défaut quasi aucune différence visuelle entre `Panel.TCheckbutton` activée-vide et désactivée (même contour, remplissage à peine différent), au point de passer pour un contrôle inerte. `s.map("Panel.TCheckbutton", indicatorbackground=[("disabled", COLOR_BG), ("!disabled", "white")], indicatorforeground=[("selected", COLOR_ACCENT)])` (`app_style.py`) tranche net : blanc franc activée, gris plat désactivée, coche à la couleur d'accent.
- **Filtre de la liste d'arbres** : cinq filtres **cumulés** (ET) dans `_arbre_matches_filter` — (1) champ 🔎 texte (`var_filter`), sous-chaîne insensible à la casse sur **n° OU essence** ; (2-5) quatre comboboxes derrière un panneau **« Filtres avancés ▸ » repliable** (même principe que `AideRepliable` — flèche ▸/▾, compteur `(n)` dans l'en-tête **visible même replié** pour qu'un filtre actif ne soit jamais oublié « hors de vue », cf. `_sync_filtres_avances`/`_count_filtres_avances_actifs`) : **Risque** (`var_risk_filter`, constantes `_RISK_FILTER_*` d'`app_arbres` : Tous / Vert / Orange / Rouge / Non fiable — « Non fiable » = colonne Risque à « — »), **Urgence** (`var_urgence_filter`, standards + personnalisés + « Non renseignée »), **Échéance** (`var_echeance_filter` : Toutes / dépassée / dans 30 j / dans 90 j / sans échéance) et **Sondages** (`var_complet_filter` : Tous / Complets ≥3 / Incomplets). `_refresh_tree_arbres` masque les lignes non concordantes **mais conserve les `iid = a{index}`** indexés sur la position réelle (cf. `_on_select_arbre`) — le filtre n'altère jamais le modèle. Le **footer reste sur toute la mission** (vue macro), pas sur la sous-liste. `Échap` dans le champ texte le vide. Les **cinq** filtres sont **remis à zéro** au chargement d'une mission (new/open) et à la **création d'un arbre** (`_clear_filter_if_set` — un arbre neuf est « Non fiable », il resterait masqué par un filtre risque actif). La **navigation clavier** (`_select_arbre_relative`) parcourt uniquement les arbres **visibles** quand un filtre est actif. **Réinitialisation** : `_reset_all_filters` (App), câblé à un **unique** bouton « ↺ Réinitialiser les filtres » **dans** le panneau Filtres avancés — un bandeau conditionnel séparé sous la liste (visible seulement quand le filtre masque ≥1 arbre) reste comme **message purement informatif** (« N arbre(s) masqué(s) par le filtre ») ; les deux portaient chacun un bouton jusqu'à ce qu'un doublon soit remonté (2026-08-20), le panneau étant le seul reachable même quand le filtre ne masque encore rien. **Action groupée** : sélection multiple dans la liste (Ctrl/Maj+clic) puis menu Arbres → « Urgence pour la sélection… » (`action_bulk_set_urgence`) applique un niveau d'urgence à tous les arbres sélectionnés en une fois.
  **Valeurs de combobox traduites vs invariantes** (piège corrigé 2026-08-20) : les sentinelles 100% UI (« Tous », « Toutes », « Non renseignée », les libellés d'échéance/complétude…) sont traduites via `_risk_filter_choices()`/`_echeance_filter_choices()`/`_complet_filter_choices()` (appelées à la construction du combobox, jamais au niveau module — la langue n'est connue qu'après `i18n.setup_language()`) ; les classes **Vert/Orange/Rouge** et les **niveaux d'urgence** restent volontairement en français partout (vocabulaire de domaine persisté/exporté tel quel, cf. « Compartimentation »). **`_(une_variable)` est invisible au test `test_i18n.py`** (le scanner AST ne lit que les littéraux `_("…")`, pas `_(CONSTANTE)`) : toute constante enveloppée ainsi doit être vérifiée **à la main** (le catalogue peut sembler complet — test vert — alors qu'une entrée manque et retombe silencieusement en français). Deux entrées manquantes de ce type (« Toutes », « Non renseignée ») ont échappé au test avant d'être repérées à l'usage.
- **Ajout d'arbre** : bouton « ＋ Ajouter » (`action_add_arbre`, `Ctrl+T`) = nouvel arbre, tous champs par défaut. N° via `_next_arbre_numero` (max numérique + 1). **« Hériter du précédent »** (variante qui recopiait l'identité/protocole — essence, port, mèche, écorce, hauteur de sondage — sans la géométrie mesurée, pour les alignements d'arbres identiques) a été retirée (2026-09-05) : jugée floue à l'usage (le tooltip promettait même, par erreur, de recopier Ø et hauteur d'arbre — jamais fait par le code) et trop proche en apparence d'`action_dup_arbre` (« Dupliquer »), qui clone lui tout l'arbre y compris ses mesures.
- **Navigation clavier entre arbres** : `Ctrl+PgDown`/`Ctrl+PgUp` → `action_next_arbre`/`action_prev_arbre` → `_select_arbre_relative(±1)` (bornée, sans boucle). Donne d'abord le focus clavier à la liste (`tree_arbres.focus_set()`) pour déclencher le `<FocusOut>` d'une case de grille en cours d'édition avant de basculer. Libre de conflit avec la navigation entre **onglets** : `nb.enable_traversal()` (appelé dans `_build_center`) lie `Ctrl+Tab`/`Ctrl+Maj+Tab` pour compléter le flux de saisie au clavier (rayon → onglet suivant → sondages…) — disjoint de `Ctrl+PgUp/PgDown` (arbres) et `Ctrl+Z/Y`. Documenté dans le popup `action_shortcuts`.
- **Menu contextuel clic droit** sur la liste d'arbres : Renommer/Dupliquer/Supprimer. `tk_popup` SANS `grab_release()` (anti-pattern qui annule le grab) + `bind("<FocusOut>")` sur le menu pour fermeture au clic externe.
- **Canvas interactif** : `section_canvas.SectionCanvas` accepte un `host` optionnel (l'App) ; `tag_bind("sondage_item"/"degradation_item"/"contrefort_item", "<Button-1>")` ouvre le dialogue d'édition correspondant. Curseur `hand2` au survol. Dispatch via tags `<type>_idx_<i>` pour retrouver l'objet métier.
- **Dialogues modaux** : `dialogs._make_modal(dlg, parent)` séquence `update_idletasks → transient → wait_visibility → grab_set → focus_set`. Appeler `grab_set` avant que le WM ait mappé la fenêtre fait apparaître le dialogue **vide** sur Linux/X11 (race entre grab et rendu). Tous les dialogues passent par ce helper, qui est appelé APRÈS la création des widgets. Chaque dialogue d'édition (Sondage/Dégradation/Contrefort) bind `<Return>`→Valider, `<Escape>`→Annuler, et pose le focus initial sur son 1er champ utile.
- **Saisie texte thémée** : `dialogs.ask_string(parent, title, prompt, initial, info=…)` remplace `simpledialog.askstring` (look système incohérent). Renvoie `None` si annulé, la chaîne (sans `strip`) si validé — `""` validé ≠ `None`. Utilisé par `action_rename_arbre`.
- **Barre d'état** : `App._build_statusbar()` (bas de fenêtre, packée `side="bottom"` AVANT le body). `App.notify_export(path, label)` y affiche le succès d'un export (non-modal) et active les boutons « Ouvrir le fichier / le dossier » (`App._open_in_system`). `app_exports._notify_export` route vers `notify_export` si l'hôte le fournit, sinon `messagebox` (contexte test). À gauche, un **bouton « 💾 Enregistrer » toujours visible** (texte seul
sans le préfixe emoji sur Windows, cf. `icons.py`) (= `action_save`) + un **indicateur d'état d'enregistrement persistant** (`lbl_save_state`) : `App._update_save_indicator()` (appelé par `_update_title`, donc à jour à chaque changement du dirty flag) montre `● Modifications non enregistrées` (ambre, bouton actif) / `✓ Enregistré` (vert, bouton désactivé) / `Mission non enregistrée` (gris, mission neuve sans fichier, bouton actif). Le `•` du titre ne suffisait pas (masquable par le WM) — c'est la réponse au « ai-je enregistré ? » de l'opérateur terrain.
- **Date du relevé** : deux saisies complémentaires. (1) **Clavier** : champ libre normalisé au format `JJ/MM/AAAA` au focus-out via le helper pur `dialogs.normaliser_date` (accepte séparateurs `/ - .`/espace, ordre français ou ISO, année 2 ou 4 chiffres ; valide via `datetime.date`, rejette 31/02). Handlers dédiés `App._date_focus_in`/`_date_focus_out` (les 3 autres champs méta gardent `_meta_focus_*`) : une saisie non interprétable **rétablit la valeur d'avant l'édition** + message de barre d'état (motif de revert comme le n° d'arbre). `normaliser_date("")` → `""` (date facultative), saisie illisible → `None`. (2) **Calendrier** : bouton « 📅 » (texte `_("Date")` sur Windows, cf. `icons.py`) → `dialogs.ask_date` (mini-calendrier **Tkinter pur**, aucune dépendance type `tkcalendar`/`babel` ; mois FR lundi-d'abord, nav ◀▶, jour sélectionné/aujourd'hui accentués, boutons Aujourd'hui/Effacer/Annuler). `App._pick_date` applique avec undo ; renvoie `""` si effacée, `None` si annulée (no-op). **`title`/`prompt`/`info` optionnels** (2026-09-05, même convention que `ask_string`) : `title` = barre de titre système (peu visible seule), `prompt` = en-tête explicite affiché dans le dialogue, `info` = note grise sous le titre — ajoutés après qu'une fenêtre de calendrier générique lors d'une ré-inspection ait laissé l'utilisateur deviner de quelle date il s'agissait. Les 3 autres appelants ne les passent pas → mise en page inchangée.
- **Infobulles** : `tooltip.Tooltip(widget, texte)` — bindings `add="+"` pour ne pas écraser ceux du widget. Sert à rappeler les accélérateurs (bouton « ＋ Ajouter » → Ctrl+T) et décrire le bandeau d'export (2 boutons + menu « Tableau »).
- **Aide repliable** : `aide_repliable.AideRepliable(parent, *paragraphes, titre="Aide", wraplength=…)` — bloc d'aide derrière un en-tête cliquable « ⓘ Aide ▸/▾ », **replié par défaut** (discret pour l'opérateur expérimenté, dépliable au clic à la 1ʳᵉ utilisation). Remplace les libellés `Muted.TLabel` ⓘ permanents (identification : couplage Ø↔rayon + invariance PRBS ; sondages : sémantique case vide/effacer ; canevas : clic = éditer/ajouter). Fonctionne en `grid` comme en `pack` (gère sa disposition interne ; le parent place le widget). État conservé tant que le widget vit — les panes ne sont construits qu'une fois, pas par arbre. S'appuie sur les styles `Panel.TFrame`/`Muted.TLabel`.
- **Canevas — ajout par clic** : un clic sur une direction libre du dessin ajoute un sondage à ce grade (`App.open_add_sondage`) ; un clic sur une direction déjà sondée l'édite. `SectionCanvas._on_click_background` convertit le pixel en grade (inverse de `geometry.polar_to_xy`), mémorise la géométrie du dernier rendu dans `self._geom`, et ignore les clics sur un élément interactif (garde par tags).
- **Raccourci export** : `Ctrl+E` → `App.action_export_pdf_arbre`. Bind dans `App.__init__` (comme Ctrl+Z/Y) via `_on_export_shortcut`, qui **ne déclenche pas** si un `Entry`/`Combobox` a le focus (Ctrl+E = « fin de ligne » dans les widgets Tk).
- **Menu Export = point d'entrée UNIQUE des exports (2026-09-05)** :
  avant, les 8 `action_export_*` étaient dispersées entre le menu
  Fichier (synthèse mission, toutes les fiches PDF, sondages CSV) et
  l'onglet Diagnostic (fiche PDF, PNG, tableau PRBS Excel/HTML) — deux
  chemins selon la portée (arbre vs mission), sans logique de rangement
  commune. `app_menu.py` les regroupe dans un menu **Export** dédié
  (barre de menu, entre Affichage et Aide), **organisées par format de
  fichier** (bloc PDF / PNG / XLSX / CSV / HTML séparés par des
  séparateurs, chaque bloc ouvert par un en-tête désactivé nommant le
  format) plutôt que par portée : chaque libellé précise lui-même s'il
  porte sur l'arbre courant ou sur la mission. Le menu Fichier ne garde
  que le cycle de vie du fichier (Nouveau/Ouvrir/Enregistrer/Récents/
  Sauvegardes/Quitter) ; l'onglet Diagnostic ne garde que le résumé/
  tableau PRBS/préconisation (ses boutons d'export en ont été retirés).
  **Impression directe supprimée** avec ce rangement (bouton « Imprimer »
  de l'onglet Diagnostic, entrée menu Fichier, raccourci Ctrl+P,
  `app_exports.print_pdf_arbre`) : elle faisait doublon avec la fiche
  PDF — imprimer un PDF exporté se fait depuis n'importe quel lecteur.
- **Fichiers récents** : `~/.penetrometre/recent.json` (8 entrées max). `App._push_recent_file(path)` appelé après chaque open/save. Sous-menu `Fichier → Ouvrir récent` reconstruit par `app_menu.refresh_recent_menu(app)`.
- **Adaptation petits écrans** : `App.__init__` clampe la geometry à 95 % de l'écran et fixe `minsize(1100, 680)` pour rester utilisable sur laptops 1366×768.
- **Disposition 3 colonnes redimensionnable** : le `body` est une `tk.PanedWindow` horizontale (`self._paned`) à 3 panneaux **à poignées** — liste d'arbres (`minsize=190`, `stretch="never"`), saisie/onglets (`minsize=400`, `stretch="never"`), dessin (`minsize=360`, `stretch="always"` → absorbe le redim. fenêtre). `tk.PanedWindow` (classique, pas `ttk`) pour le `minsize` par panneau. Répond à deux besoins : élargir le tableau de saisie au détriment du dessin (onglets Dégradations/Contreforts peu denses) et réallouer l'espace sur petit écran. `SectionCanvas` se redessine sur `<Configure>` → s'adapte à la largeur du panneau sans code spécifique. **Positions persistées** : `App._save_sash_positions` (sur `<ButtonRelease-1>` de la PanedWindow) → `SettingsStore.set_sash_positions` ; `App._restore_sash_positions` les ré-applique via `sash_place` **différé** (`after(150,…)`, sinon TclError tant que la PanedWindow n'est pas dimensionnée). `get_sash_positions()` tolérant → `[]` si jamais réglé / corrompu (défauts d'`add`).
- **Taille du texte (accessibilité)** : réglage `ui_scale` persisté dans `~/.penetrometre/settings.json` (`app_settings.SettingsStore`, pur, borné `[0.8, 1.6]`). **`tk scaling` est inopérant** sur plusieurs builds Tk/Linux (métriques de police indépendantes du facteur) — le seul levier fiable est de **multiplier le nombre de taille** de chaque police. Centralisé dans `ui_fonts` : facteur global de processus (`set_ui_scale`/`get_ui_scale`) + helper `font(family, size, *opts)` qui applique le facteur (identité à 1.0 → aucune régression ni golden-test par défaut). `App.__init__` fixe le facteur **avant** la création des widgets (`_apply_ui_scale` → `set_ui_scale`). Toutes les polices de la couche UI passent par `ui_fonts.font` : styles ttk (`app_style`, `_f`), et tuples explicites de `penetrometre`/`pane_sondages`/`pane_diagnostic`/`dialogs` (`ui_font`). `app_style` scale aussi le `rowheight` du Treeview. **Le dessin (`section_canvas`) n'est PAS scalé** (géométrie en pixels fixes, golden-testé). Menu **Affichage → Taille du texte** (radiobuttons Petit/Normal/Grand/Très grand → `action_set_ui_scale`) : persiste, met à jour le facteur, **ré-applique `apply_ttk_styles` à chaud** (effet immédiat sur la majorité de l'UI) ; les quelques widgets à police en tuple déjà réalisés ne se redimensionnent qu'au redémarrage (message de barre d'état).
- **Contraste élevé (accessibilité plein soleil)** : réglage booléen `high_contrast` persisté (`SettingsStore`). `apply_ttk_styles(root, *, high_contrast=False)` passe le texte courant en **noir pur** et le texte atténué (Muted/Sub, onglets inactifs) à un gris **bien plus sombre** (`#2C3631`) — **les accents verts et les fonds sont inchangés**, et **le dessin n'est pas concerné** (golden-testé). Identité au défaut → aucune régression. Menu **Affichage → Contraste élevé** (checkbutton → `action_set_high_contrast`). **Point unique `App._apply_styles()`** (= `apply_ttk_styles(self, high_contrast=…)`) utilisé partout (startup + `action_set_ui_scale`) pour ne jamais perdre le mode en ré-appliquant les styles. Les couleurs peintes hors styles (tags de la liste d'arbres, dessin) ne changent pas → message « redémarrer pour un effet complet ».
- **Progression dans les onglets** : `App._refresh_tab_progress()` (appelé dans `_redraw_all`) préfixe les onglets de l'étape par un glyphe d'avancement — **même vocabulaire que les pastilles** (`○` à faire · `◐` en cours · `●` prêt). Identification (`●` si rayon>0 et essence saisie), Sondages (glyphe de complétude via `_arbre_etat`), Diagnostic (`●` si `_arbre_diag_fiable`). La **forme** porte l'info (lisible en daltonisme ; ttk n'autorise pas de couleur par onglet). Dégradations/Contreforts restent sans glyphe (étapes optionnelles — un `○` y suggérerait à tort un manque). `self.nb` mémorisé dans `_build_center`.
- **Saisie des sondages = grille 16 directions** (`pane_sondages.py`) : refonte ergonomique remplaçant la modale-par-mesure. Les 16 directions (rose des vents `_WIND_LABELS` : cardinales `N/NE/E…`, intermédiaires en combiné `N-NE/NE-E…`) sont pré-affichées ; l'opérateur tape la PRBS et descend (`Entrée`/`↓`/`↑` → ligne suivante via `_focus_entry`). **Sémantique** : case « Bois sain » vide = direction non sondée (aucun `Sondage`) ; valeur (y compris 0) = sondage existant ; **quitter la case en la laissant vide supprime le `Sondage`** (commentaire + compartimentation compris — **le Ø local n'est PAS concerné**, il vit indépendamment de tout sondage, cf. ci-dessous). La suppression n'est décidée qu'**au focus-out**, pas à la frappe : vider la case sans en sortir (ex. pour retaper une valeur corrigée) ne supprime rien. Cette suppression étant destructrice et muette, si le sondage effacé portait un **commentaire** ou une **compartimentation** ≠ « non renseignée », elle est **signalée** en barre d'état (undo poussé au focus-out, comme le reste des éditions live). L'altéré (`rayon LOCAL − sain`, clampé au rayon local) est en lecture seule, recalculé en direct. La compartimentation (combobox) n'est active que si un sondage existe sur la ligne. **Colonne « Douteux (~) » (sondage incertain)** : case à cocher `Sondage.incertain` (angle de mèche, pression, accès difficile…), même activation conditionnelle que Compart./Commentaire — reste comptée dans le diagnostic mais préfixe la PRBS de « ~ » dans les exports (PDF/XLSX/CSV, source unique du préfixe : `fiche_pdf`/`export`). L'en-tête de colonne a été explicité en toutes lettres le 2026-09-05 (le seul « ~ » était trop cryptique — rien n'indiquait qu'une case à cocher s'y cachait) ; le symbole reste affiché entre parenthèses, lien visuel avec le préfixe des exports. Tooltip (rattaché par index de colonne, pas par comparaison du texte traduit) sur l'en-tête et sur chaque case + paragraphe dédié dans le bloc Aide (sinon totalement indécouvrable). **Onglet scrollable** (2026-09-05) : la grille 16 lignes + Ø local + le bloc Aide déplié pouvaient dépasser la hauteur disponible (petit écran, texte agrandi) sans aucun moyen d'atteindre le bas — le pane vit désormais dans un sous-`tk.Canvas` scrollable verticalement (molette comprise), même motif que `pane_diagnostic`. **Piège corrigé (2026-08-20)** : `ttk.Checkbutton(..., textvariable=var_inc, variable=var_inc, ...)` affichait la valeur du `BooleanVar` comme **libellé** de la case (« 0 »/« 1 » visible à côté du carré, cf. `textvariable` ≠ `variable`) — retiré, seul `variable` reste. Second piège, plus grave : `_on_sain_write` réactivait déjà `combo`/`com_entry` au premier caractère tapé dans « Bois sain », mais **pas** `chk_inc` — la case restait bloquée `disabled` pour un sondage fraîchement saisi tant qu'aucun `refresh()` complet n'intervenait (changement d'arbre), puisque la grille ne se re-`refresh()` volontairement pas à chaque frappe (cf. plus bas). Les deux widgets ont désormais le même réflexe d'activation dans `_on_sain_write`. **Unicité garantie par construction** (une ligne par grade — plus de validation d'unicité). Double-clic sur les libellés **Direction/Grade** ouvre `edit_sondage` (détail : commentaire, redirection de grade) ; l'`Entry` garde son double-clic natif. **Undo des éditions live** : snapshot capturé au focus-in (`host.capture_undo_snapshot`), empilé au focus-out seulement si la valeur a changé (`host.push_undo_snapshot`) — évite les undo parasites ; la compartimentation passe par `host.push_undo` (mutation discrète). Mutations notifiées via `host.on_sondages_changed` (dirty + redraw debouncé ; ne re-`refresh()` PAS la grille pour ne pas lutter contre la frappe). Sondages maintenus triés par grade (`sort` + `renumeroter_sondages`). Les libellés de la rose des vents 16 directions vivent dans `geometry.WIND_LABELS` (partagés avec la grille Contreforts). **Garde-fous rayon** : tant que le brin n'a pas de rayon général (`R<=0`), un bandeau ambre en tête de grille (`_lbl_no_radius`, montré/caché par `refresh`) rappelle de saisir le rayon dans l'onglet Identification — sinon l'altéré n'est pas calculable (« — ») et le bois sain n'est pas borné. La PRBS est **plafonnée au rayon LOCAL** dès la frappe (`_on_sain_write`, `min(sain, rayon_a_grade(g))`) ; le focus-out **signale** ce plafonnement en barre d'état (`host.set_status`) au lieu de le subir silencieusement. **Colonne « Ø local (cm) »** (entre Grade et Bois sain) : diamètre sous écorce optionnel mesuré à cette direction (cf. « Diamètre local par direction » ci-dessus), **toujours active** (indépendante de la présence d'un sondage sur la ligne — permet de modéliser un méplat entre deux sondages sans mesure PRBS supplémentaire), propre undo focus-in/out (`_on_diam_write`/`_on_diam_focus_in`/`_on_diam_focus_out`), navigation `Entrée`/`↓`/`↑` dédiée (`_focus_diam_entry`). Éditer le Ø local réaligne le bois altéré du sondage éventuellement présent sur CETTE ligne via `Brin.set_diametre_local` — **sans jamais retoucher sa PRBS**. Un Ø local **trop petit** QUAND un sondage existe sur la ligne (rayon local < bois sain déjà saisi, physiquement impossible) est **empêché** : la valeur appliquée est relevée au minimum valide (2 × bois sain) dès la frappe, l'affichage n'étant normalisé qu'au focus-out — même mécanique que le plafonnement de « Bois sain » au rayon, signalée en barre d'état si elle a joué. Sans sondage sur la ligne, aucune contrainte (rien à violer).
- **Saisie des contreforts = grille 16 directions** (`pane_contreforts.py`) : même pattern que la grille de sondages — l'unicité « un contrefort par grade central » borne le domaine à 16, donc lignes pré-affichées. **Sémantique alignée** : longueur vide = pas de contrefort ; valeur (y compris 0) = existant ; effacer = supprimer. Largeur (combobox des multiples de 25, défaut 75 gr à la création) et commentaire actifs seulement si un contrefort existe sur la ligne. Double-clic Direction/Grade → `edit_contrefort` (détail : largeur en cm). Même mécanique d'undo focus-in/out ; notification via `host.on_section_changed` (équivalent générique d'`on_sondages_changed` pour Dégradations/Contreforts). Contreforts maintenus triés par grade.
- **Saisie des dégradations = tableau éditable en place** (`pane_degradations.py`) : une dégradation est un **arc** début→fin (domaine non fixe) → pas de grille pré-affichée mais des **lignes dynamiques toutes éditables** (combobox début/fin readonly via `dialogs.grade_choices`/`find_grade_choice`/`parse_grade` rendus publics, largeur gr·cm en lecture seule, profondeur/commentaire en saisie live, bouton ✕). **« ＋ Ajouter » ne passe plus par la modale** : crée l'arc sur la première plage libre (50 gr, repli 25 gr) et pose le focus sur la profondeur. Non-chevauchement validé à la sélection début/fin (valeur fautive **rétablie** + `messagebox` ; texte partagé `dialogs.message_chevauchement`). Double-clic sur le n° → `edit_degradation` (détail : largeur en cm). **Piège dataclass** : les callbacks capturent l'objet `deg` par closure et le retrouvent par **identité** (`_index_de`, `is`) — jamais `in`/`remove`, dont le `__eq__` structurel confondrait deux arcs identiques.
- **Synthèse de mission** (tableau de hiérarchisation du risque) : `diagnostic.mission_synthesis_rows(chantier)` → `List[MissionSynthesisRow]` (fonction pure), **une ligne par arbre** (n° · essence · port · nb sondages · rayon · t/R moyen · classe globale · direction critique). Respecte la règle de fiabilité : `tR_moyen_pct`/`classe_globale` = `None` si `< 3` sondages (via `DiagnosticSnapshot.diagnostic_global`), `tR_min_pct`/`crit_grade` = `None` si aucune altération. Exports (`export_synthesis.py`) : `export_synthesis_csv` (séparateur `;`, UTF-8 BOM) et `export_synthesis_xlsx` (thème vert, cellule classe colorée, **autofiltre** pour trier par risque, en-tête gelé, ligne de bilan). Wrappers Tk dans `app_exports.export_synthesis_{csv,xlsx}_mission` ; actions `App.action_export_synthesis_{csv,xlsx}` ; entrées dans le menu **Fichier** (mission-level, à côté des fiches PDF / sondages CSV). « Non fiable » (1-2 sondages) ≠ « — » (rayon nul / 0 sondage) dans la colonne classe. **Colonnes Préconisation** : les 3 champs `urgence`/`echeance`/`preconisation` du genet sont repris en fin de ligne (`_replace` au niveau genet/tête de cépée seulement, vides sur les sous-lignes de brin). Le XLSX colore la cellule **Urgence** par niveau (`_URGENCE_FILL`).
- **Préconisation (expertise → décision)** : la classe de risque dit « quel danger », ces champs **genet** disent « quoi faire » — c'est le livrable. `Arbre.urgence` (∈ `model.URGENCE_NIVEAUX` : Immédiate / Court terme / Moyen terme / Surveillance / Sans objet ; `""` = non renseignée), `Arbre.echeance` (date `JJ/MM/AAAA` facultative), `Arbre.preconisation` (**texte libre**) — choix d'Edwin (AskUserQuestion : texte libre + échelle d'urgence + échéance optionnelle). Pas de migration (nouveaux champs à défaut vide, filtrés par `__dataclass_fields__` au load). **Saisie** : bloc « Préconisation » de l'onglet **Diagnostic** (`pane_diagnostic._build_preconisation`) — combobox urgence, échéance (entry normalisée + bouton 📅/`_("Date")` sur Windows `ask_date`), `tk.Text` multi-ligne. Édite le **genet** courant ; mutations via `host.on_preconisation_changed` (= `_mark_dirty` **seul**, pas de redraw — n'affecte ni dessin ni pastille). Undo : snapshot au focus-in, empilé au focus-out si changé (urgence = `push_undo` discret). `_refresh_preconisation` **ne recharge que si l'arbre a changé** (`_preco_loaded_id` = `id(arbre)`) → ne lutte pas contre la frappe sur un redraw. **Combobox urgence/suivi traduits mais valeur persistée toujours française** (`URGENCE_NIVEAUX`/`SUIVI_VALIDITES` sont du vocabulaire de domaine invariant, cf. barème) : l'affichage passe par `translate_values`, la lecture par `untranslate_value` — **piège corrigé (2026-08-20)** : le combobox écrivait la valeur **affichée** (donc traduite hors français) directement dans `a.urgence`/`a.suivi_validite` au lieu de la reconvertir, cassant silencieusement la correspondance avec `_URGENCE_COLOR`/les exports colorés dès que l'UI n'était pas en français (la préconisation restait enregistrée mais perdait sa classe de couleur, et ne matchait plus aucun niveau connu au rechargement). **Sorties** : colonnes synthèse mission (cf. ci-dessus) + bloc sur la **fiche PDF** (`fiche_pdf` : urgence colorée par niveau `_URGENCE_COLOR`, échéance, texte libre `_wrap_lines` borné 4 lignes ; placé après l'identité → le budget vertical du dessin s'ajuste).
- **Comparaison inter-missions (ré-inspection)** : `comparaison.open_comparison(parent, current, reference, *, cur_date, couleur_classe, on_save)` — fenêtre **redimensionnable** à 3 sections côte à côte (**référence | courant | carte d'évolution**), tableau chiffré, verdict. Décisions métier (AskUserQuestion) : **par session** (`App._reference_chantier`, rien de persisté → pas de lien cassé) ; **lien explicite par arbre** (combobox, défaut = même n°) ; **vue dédiée** ; **section d'évolution** (progression surlignée) + **export PNG & PDF**.
  - **Fenêtre intégrée au reste de l'app, MÊME bandeau que la fenêtre principale (2026-09-06)** : avant, la fenêtre portait ses propres boutons Export PDF/PNG + Fermer, coupant l'utilisateur du menu Export et de la barre d'état pendant qu'elle restait ouverte (repéré à l'usage — plus de bandeau, donc plus moyen d'Enregistrer ni de rouvrir un export juste produit). Un premier passage a déplacé l'export dans le menu Export de la fenêtre **principale** — mais celle-ci étant couverte par la comparaison (quasi plein écran, cf. plus bas), ce menu restait injoignable sans fermer la fenêtre (re-signalé aussitôt) ; un second passage lui a donné un menu propre réduit à **Export** (2 entrées) — toujours un sous-ensemble, sans Fichier/Comparaison/Arbres/Affichage/Aide. **Solution retenue** : la fenêtre réutilise **le même widget `tk.Menu`** que la fenêtre principale — `app_menu.build_menu` le mémorise sur `App._menubar`, `open_comparison` fait `dlg.config(menu=parent._menubar)` (un `tk.Menu` Tk peut être la barre de menu de plusieurs fenêtres à la fois) — plus besoin de sous-ensemble à entretenir en double, ni de quitter la fenêtre pour la moindre action du bandeau. L'entrée **Comparaison — fiche PDF…**/**… évolution (PNG)…** du menu Export (déjà présente, grisée hors comparaison active via `comparaison.is_comparison_active()`, relu par un `postcommand`) fonctionne donc telle quelle depuis cette fenêtre — `export_active_comparison(fmt)`/`get_comparison_window()` exposent l'état du module, `ExportActionsMixin.action_export_comparison_{pdf,png}` délèguent à `App._export_comparison` (`app_fichier.py`, inchangée dans son fonctionnement). Par ailleurs : (2) **le pied de fenêtre reprend le MÊME bandeau que la barre d'état principale** (2026-09-06) — un `tk.Menu` peut être partagé tel quel entre fenêtres (ci-dessus), mais un widget ordinaire (`ttk.Frame`) ne le peut pas : ce pied est donc une **reconstruction visuellement identique** (mêmes styles `Side.TFrame`/`Side.TLabel`/`Ghost.TButton`, même disposition), pas le même widget. Il porte le bouton **« 💾 Enregistrer »** (texte seul sur Windows, cf. `icons.py`) (`on_save` = `App.action_save`) — l'ancien bouton « Enregistrer » du bandeau supérieur de la fenêtre (à côté des sélecteurs d'arbres) a été **retiré**, jugé redondant une fois le pied de fenêtre équipé du sien — suivi de l'**indicateur d'enregistrement** (texte + couleur `● Modifications non enregistrées`/`✓ Enregistré`/`Mission non enregistrée`), dont le texte/couleur/activation vient de `dialogs_shared.save_state_label(dirty, has_file)` — **SOURCE UNIQUE** partagée avec `App._update_save_indicator`, pour que les deux bandeaux disent toujours la même chose sans dupliquer la logique ; recalculé à l'ouverture et après chaque clic sur Enregistrer (`_refresh_save_state`, lit `parent._dirty`/`parent.current_file` — `parent` est toujours l'App). (3) le pied de fenêtre reproduit aussi localement `App.notify_export` (`show_export_feedback(text, on_open_file, on_open_folder)` met à jour un label + 2 boutons « Ouvrir le fichier/dossier », stockés dans `state["_lbl_msg"/"_btn_open_file"/"_btn_open_folder"]`) — la barre d'état principale reste aussi mise à jour (`notify_export`) mais invisible tant que cette fenêtre couvre l'écran ; (4) plus de bouton Fermer : décorations système complètes (pas de `transient`, cf. plus bas), la croix suffit.
  - **Cépée (multi-brin)** : la fenêtre affiche **un bloc de comparaison par brin** (3 dessins + tableau + verdict), empilés dans une zone **défilante** (mono-caule = un seul bloc, sans en-tête). Appariement **automatique par index/label** (a↔a, b↔b… — choix Edwin) : un brin courant **sans homologue** de référence (réf plus courte / brins ré-ordonnés) est comparé à `None` (colonne réf. vide, pas de couronne orange) — jamais d'appariement décalé silencieux. Calcul pur `diagnostic_comparaison.comparaison_par_brin(ref, cur, annees)` → `[(label, cur_brin, ref_brin|None, ComparaisonDetail)]` (classe/t/R **au niveau brin** via `_brin_compare_summary`). Rendu brin : `comparaison_render.render_brin_section` (brin isolé via genet temporaire) + `render_evolution_section_brin(ref_b|None, cur_b)`. **Export par brin** : `render_comparison_pages(...)` → **une page A4 par brin** pour une cépée (page genet inchangée pour un mono-caule) ; `save_comparison_pdf` = **PDF multi-pages**, `save_comparison_png` = pages **empilées verticalement** (PNG mono-image). Composeur de page partagé `_compose_comparison_page` (genet ↔ brin). Le builder de la fenêtre (`_page_builder`) renvoie la **liste** de pages. **Ergonomie** : la fenêtre **partage la case « Afficher sondages »** avec la fenêtre principale (même `BooleanVar`, cf. « Checkbox « Afficher sondages » » plus haut — bascule instantanée dans les deux sens, plus besoin de changer de fenêtre ; propagée aux dessins, fenêtre **et** export — sinon les flèches s'affichaient toujours), s'ouvre **grande et centrée** (95 % écran) avec le **bouton maximiser** disponible — elle n'est **pas** `transient` (un transient X11 = dialogue utilitaire, souvent sans bouton maximiser et `-zoomed` ignoré ; `state('zoomed')`/`-zoomed` tentés en best-effort par-dessus), et le `filedialog` d'export est **ancré sur la fenêtre** (`parent=get_comparison_window() or self`) pour ne pas passer dessous. **Molette** : défilement activé quand le pointeur est sur la zone (pattern `bind_all` Enter/`unbind_all` Leave, comme `pane_diagnostic`). **Choix des DEUX arbres dans la fenêtre** : deux comboboxes (arbre **courant** de la mission **+** arbre de **référence**) — avant, le courant était figé au lancement ; `default_arbre` = sélection initiale, référence par défaut = même n°. **Piège** : les `StringVar` des comboboxes sont gardées dans `state` (sinon, locales, elles sont GC à la sortie de la fonction → leur `__del__` désaffecte la variable Tcl → combobox vide).
  - **Calcul pur** (`diagnostic`) : `arbre_compare_summary` (réutilise la synthèse genet) ; `evolution_classe(ref, cur)` → `-1`/`0`/`+1`/`None` (`_GRAVITE_CLASSE`) ; `comparaison_detaillee(ref_arbre, cur_arbre, annees)` → `ComparaisonDetail` (cœur partagé `_comparaison_core` prenant des brins + résumés ; `ref_b=None` toléré). **Comparaison sur les 16 directions EXTRAPOLÉES** (`prbs_par_grade` : rayon − altération interne extrapolée − dégradation externe) — on exploite l'extrapolation au lieu de se limiter aux directions sondées. Métrique principale = **`perte_moy_par_dir`** (bois sain perdu moyen **par direction**, cm) ; **`taux_cm_an`** seulement si `annees ≥ _TAUX_ANNEES_MIN` (0.5) — sinon `None` (sur un intervalle court, `perte/annees` explose : 20 j → 155 cm/an aberrant, d'où le garde-fou). Aussi : PRBS moyenne réf/cur, compartimentation perdue active→absente (directions sondées seules), pire direction. `verdict_evolution(detail)` (classe + t/R + perte cm/direction + cm/an si dispo). `dialogs.annees_entre(date_a, date_b)` = durée (base 365.25 j) depuis les `date_releve`.
  - **Rendu PIL** (`comparaison_render`, sans Tk) : `render_evolution_section(ref_arbre, cur_arbre, size)` — **« section d'évolution »** sur la géométrie du tronc COURANT : couronne **orange** = bois sain **perdu depuis la référence** (entre l'ancien bord de cavité `R − PRBS_réf` et le nouveau `R − PRBS_courant`), cavité de référence au centre (`COLOR_ROT`), bois sain (`COLOR_WOOD`), écorce (`COLOR_BARK`). Contours **lissés** par `geometry.catmull_rom_closed` (helper `_poly`, même spline que le rendu des sections → pas d'aspect « cubique »). Choix d'Edwin (la heatmap abstraite, jugée peu lisible, a été remplacée). `render_comparison_page(...)` (page **A4 paysage** 1754×1240 : en-tête, 3 sections, tableau `metric_rows`, verdict) ; `save_comparison_png`/`save_comparison_pdf`. `metric_rows`/`verdict_evolution` partagés fenêtre ↔ page.
  - **App** : menu **Comparaison** dédié dans la barre de menu (les deux
  boutons qui doublonnaient ce menu à côté du titre « Pénétromètre » ont été
  retirés le 2026-09-05 — jugés encombrants pour une action ponctuelle,
  déjà accessible par le menu). `action_reinspection` (« Faire une comparaison ») charge une mission antérieure comme **base de travail** (`_install_chantier_ui`, mutualisé avec `_open_path`) **et** la fige comme référence (`deepcopy`) : on **redemande la date** (`ask_date` avec `title`/`prompt`/`info` explicites depuis le 2026-09-05 — « Date du diagnostic actuel », rappel du nom et de la date de la mission de référence, pour lever l'ambiguïté d'un calendrier générique ; aujourd'hui par défaut → la référence garde l'ancienne date), on **détache le fichier** (`current_file=None` → Enregistrer sous… forcé, jamais d'écrasement de la référence) ; `action_compare_arbre` (« Diagnostic de la comparaison ») → `open_comparison(self.chantier, ref, default_arbre=…, on_save=…, on_export_pdf=…, on_export_png=…, show_sondages=…)` ; `action_load_reference` (choix manuel) ; `_export_comparison(fmt, builder, parent)` (filedialog ancré sur `parent` + `notify_export` + `comparaison.show_export_feedback`). **Croissance en diamètre** prise en compte : `ComparaisonDetail.rayon_ref/rayon_cur` (chaque PRBS/t/R rapporté à SON rayon) + ligne **« Diamètre du tronc »** du tableau (`metric_rows`). Aucun changement de format de fichier.
- **Checkbox « Afficher sondages »** vit **sous le canvas** (`App._build_right`), pas dans l'onglet Diagnostic — elle contrôle un état visuel toujours présent. Variable `App.var_show_sondages`. Elle gouverne aussi le **dessin des exports PDF** (`action_export_pdf_arbre`/`_mission` → `render_fiche_arbre(pdf, …, show_sondages=…)`) : pastilles masquées sur le dessin si décochée, **mais le tableau PRBS reste** (c'est la donnée). L'export PNG (`action_export_png`) la respectait déjà. **Bascule pilotée par `trace_add`, pas `command=`** (2026-09-06) : la fenêtre de comparaison (`comparaison.open_comparison`) pose sa **propre** case à cocher sur cette **MÊME** `BooleanVar` (un seul interpréteur Tcl pour toute l'app — même mécanique de partage que le bandeau, cf. ci-dessous) pour ne plus avoir à changer de fenêtre ; un `command=` sur le seul Checkbutton principal n'aurait réagi qu'à SES clics, pas à ceux de l'autre case sur la même variable, d'où le passage à une trace `"write"` (déclenchée quelle que soit l'origine du changement) qui redessine `App.section`. La fenêtre de comparaison pose sa propre trace pour redessiner ses blocs, retirée à la fermeture (`<Destroy>`) pour ne pas rappeler `_on_select` sur des widgets détruits à la bascule suivante.
- **Titre du canvas** : `SectionCanvas._draw_titre` ne dessine que `display_name` (pas de sous-titre rayon/Ø/H/mèche — redondant avec l'onglet Identification). Aligné sur `pil_render._pil_draw_titre` (titre seul). Appelé en mono-brin ET en cépée (`_draw_cepee`).
- **Fiche d'expertise PDF = VECTORIELLE (fpdf2)** : `fiche_pdf.py` produit un PDF **natif** (texte sélectionnable/cherchable, net au zoom, ~3-4× plus léger). Approche **hybride** : le texte, le tableau PRBS, le diagnostic et la préconisation sont vectoriels ; le **dessin de section** (rose des vents) **reste rendu par Pillow** (`pil_render.render_arbre_to_pil_image`) et **collé comme image** (`pdf.image`) — le réécrire en vectoriel serait énorme et sans gain ; la **légende horizontale** est aussi rendue sur une petite image PIL et collée (fidélité). **API** : `pdf = _new_pdf()` puis `render_fiche_arbre(pdf, arbre, chantier, …)` **ajoute** la/les page(s) (une fiche + une page photos si `arbre.photos`), enfin `pdf.output(chemin)` — la **mission** réutilise **un seul** `pdf` en bouclant (concaténation native ; plus d'`append_images` Pillow). **Tableau PRBS paginé (2026-08-20)** : une cépée à beaucoup de sondages (plusieurs brins × 16 directions) peut dépasser la hauteur d'une page A4 — le tableau se poursuit alors sur une page « (suite) » (`table_y_limit`, pied de page factorisé dans `_draw_footer` et rejoué identique sur chaque page) plutôt que de chevaucher le pied de page ; la section Diagnostic/Préconisation qui suit bascule elle aussi en haut d'une page neuve si la place restante est insuffisante. Cas mono-brin inchangé (toujours 1 page). Le document travaille en **unité = 1 px @150 DPI** (`FPDF(unit=72/150, format=(1240,1754))` ⟹ A4 exact) → **coordonnées historiques conservées verbatim** ; seule la taille de police est convertie en points à la frontière (`_Page`, wrapper qui émule les ancres PIL `la`/`lm`/`rm`/`mm`/`mt`). **Polices** : DejaVu embarquées (`assets/fonts/`) enregistrées via `add_font` — l'Helvetica de base de fpdf2 est latin-1 (casserait accents + ✓/✗) ; symboles compartimentation source-unique `dialogs_shared`. **Pas de golden pixel** sur la fiche (les goldens `test_render` visent `comparaison_render`, resté raster) → smoke tests `FichePdfSmokeTests` (%PDF + nb pages) + les 2 tests de dessin redirigés sur `render_arbre_to_pil_image`. `comparaison_render.py` **reste raster** (hors périmètre).
  **Répartition par classe = UNE seule lecture (2026-09-05)** : le bloc
  Diagnostic du mono-caule (`_draw_mono_diagnostic`) n'affiche plus, sous
  la barre colorée Vert/Orange/Rouge (déjà porteuse des pourcentages), la
  ligne texte redondante « Vert N/16 (X gr) • … » (mêmes proportions,
  exprimées en fractions) — un doublon d'information repéré à l'usage.
  **Page photos** (`_render_photos_page`) : le pied de page appelle
  désormais `_draw_footer` comme la page principale (barème + **nom du
  cabinet**) au lieu d'un pied de page ré-écrit à la main qui omettait le
  cabinet ; la légende sous chaque photo est « Photo N » (jamais le nom de
  fichier, cf. « Photos = entrée semi-fiable » plus haut).
- **Exports tableau XLSX ↔ HTML** : mise en page **propre à Pénétromètre** (plus de gabarit externe). Garder les deux **alignés** (même contenu : titre mission + identité arbre en toutes lettres ; 9 colonnes N° · Direction · Grade · Rayon · PRBS bois sain · Bois altéré · t/R coloré · Classe · Compart. ; ligne **Diagnostic** = t/R moyen + classe globale, masquée si < 3 sondées via `DiagnosticSnapshot.diagnostic_global` ; légende compartimentation ✓/✗/– ; légende des classes colorée). La colonne **PRBS = mesure brute**, le **t/R = ajusté** de la dégradation externe (comportement historique). Une modif du XLSX doit être reportée au HTML (et inversement) — cf. `tests/test_export.py::HtmlExportAlignementTests` (parité) et `::test_diagnostic_et_legendes_du_tableau` (mise en page XLSX).

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
  template_store.py update_checker.py photo_paths.py icons.py
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
`action_open_guide`), `LICENSE` et `PRIVACY.md` (à la racine du bundle,
ouverts par `penetrometre._open_doc` depuis les boutons « Licence (CLU) »/
« Confidentialité » de la fenêtre À propos). **Piège corrigé (2026-09-06)** :
`LICENSE`/`PRIVACY.md`/`docs/` étaient absents des deux specs — l'app
tournait normalement (`Path(__file__).parent / name` résout dans
l'environnement de dev), mais dans le binaire empaqueté ces boutons
affichaient « Fichier introuvable » (silencieux, pas de crash). Nuitka doit
rester le **miroir exact** des `datas` du spec PyInstaller — toute
modification de l'un doit être reportée sur l'autre.

Gestion des licences (usage interne). La clé privée vit **hors du dépôt**,
dans `~/.penetrometre-keys/private.key` (ou `$PENETROMETRE_LICENSE_KEY`) :

```bash
python3 gen_license.py machine-id                    # ID de CETTE machine (tests)
# --machine-id est REQUIS (l'ID vient du client, via sa fenêtre d'activation)
python3 gen_license.py issue "Cabinet" "a@b.fr" --machine-id a3b4c5d6e7f8
python3 gen_license.py issue "Cabinet" "a@b.fr" --machine-id a3b4c5d6e7f8 --expires 2028-01-01
python3 gen_license.py issue "Cabinet" "a@b.fr" --machine-id a3b4c5d6e7f8 --no-expires
python3 gen_license.py issue "Cabinet" "a@b.fr" --any-machine   # clé TRANSFÉRABLE (rare)
python3 gen_license.py verify "<clé>"                # support : pour qui / jusqu'à quand
```

Le check de licence ne s'active que dans un **binaire de production**
(`is_bundled()` : PyInstaller *ou* Nuitka). En développement
(`python3 penetrometre.py`), il est sauté automatiquement — la fenêtre
d'activation ne s'affiche donc **pas**, c'est normal.

La clé publique est dans `license.py` (`_PUBLIC_KEY_B64`) ; la clé privée ne
doit jamais entrer dans le dépôt. `keygen` refuse d'écrire dans un dépôt git,
`issue` avertit si la clé y traîne encore, et le hook `pre-push` bloque tout
fichier de clé suivi par git.

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
- `.claude/docs/design-system.md` — **design system du chrome Tk** :
  tokens couleur (`palette.py`), typographie/espacements (`ui_fonts.py`),
  icônes (`icons.py`). `COLOR_ACCENT` (chrome) est volontairement
  **distinct** de `COLOR_RENDER_ACCENT` (dessin/PDF/comparaison,
  golden-testés, jamais retouchés) et de `COULEUR_CLASSE` (diagnostic de
  risque) — ne jamais les confondre. Aucun emoji couleur dans le chrome :
  glyphes Unicode monochromes (`icons.py`) ou texte seul.
