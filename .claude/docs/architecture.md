# Architecture détaillée des modules

Ce document détaille les **modules du cœur** (géométrie, modèle, diagnostic,
persistance, rendu, exports, dialogues, canevas). La **couche App** (`App`
+ ses 6 mixins + helpers + accessibilité + ré-inspection) est **cartographiée
en bref en fin de document** (purpose + surface publique) avec renvoi à
**CLAUDE.md** pour le détail — on évite d'y dupliquer la prose volatile.
**En cas de doute, CLAUDE.md fait foi pour la couche App.**

## `bareme.py` — barème métier Pénétromètre (stdlib uniquement)

- `classer_prbs(ratio_tR, port_arbre) -> str` — renvoie `Vert | Orange | Rouge`
  selon le **groupe de barème courant** contenant ce port
  (`groupe_pour_port`) ; repli sur le groupe de `GROUPES_DEFAUT` couvrant ce
  port si aucun groupe courant ne le contient.
- `normaliser_port(value) -> str` — vérifie l'appartenance à `PORTS_ARBRE`.
- `GroupeBareme` (dataclass : `nom`, `ports: Tuple[str,...]`, `seuil_vert`,
  `seuil_orange`) — un groupe de ports partageant les mêmes seuils t/R ; un
  port individuel n'est qu'un groupe à un seul port. `get_groupes()`/
  `set_groupes()` (état module) ; `GROUPES_DEFAUT` = partition par défaut
  (2 groupes, cf. `PORTS_GROUPE_LIBRE`/`PORTS_GROUPE_STRICT` ci-dessous) ;
  `groupes_vers_brut`/`seuils_depuis_brut` = frontière JSON (ce dernier migre
  l'ancien format à 2 groupes fixes et comble les ports manquants d'une
  config incomplète). Cf. CLAUDE.md « Barème configurable par groupes de
  ports » pour le détail (dont l'éditeur `dialogs_settings.ask_bareme_settings`).
- Constantes : `PORTS_ARBRE`, `PORTS_GROUPE_LIBRE`, `PORTS_GROUPE_STRICT`
  (définissent `GROUPES_DEFAUT`), `CLASSE_VERT`, `CLASSE_ORANGE`, `CLASSE_ROUGE`.
- Le port `délaissé` est dans `PORTS_GROUPE_LIBRE` (mêmes seuils que `libre`)
  **par défaut** — reconfigurable par l'expert.

## `geometry.py` — fonctions pures (stdlib uniquement)

**Géométrie pure**
- `catmull_rom_closed` — spline fermée Catmull-Rom.
- `bell_max_at_grade(grade, contreforts)` — hauteur max de cloche cosinus².
- `contrefort_zones(contreforts)` — fusion des arcs qui se chevauchent.

**Rayon scalaire ou par direction (`RadiusSpec`)** : `RadiusSpec = Union[float,
Callable[[float], float]]`. Les primitives de contour ci-dessous acceptent un
rayon **scalaire** (section circulaire — calcul strictement identique à l'ancien)
**ou une fonction `grade→rayon`** (rayon variable par direction, p. ex.
`Brin.rayon_a_grade` — diamètre local par sondage, interpolé en LISSANT
(cosinus, borné, sans angle vif) entre les directions mesurées voisines).
Helper interne `_radius_at(R, grade)`.

**Primitives de rendu partagées Tk ↔ PIL** (points `(x, y)` en coord. écran) :
- `polar_to_xy`, `polar_idx_to_xy` — polaire → écran (grade 0 = Nord, horaire).
- `cavity_polygon(alteration_par_grade, cx, cy, scale, …, rotation_grades=0.0)`
  — polygone lissé cavité.
- `contour_polygon(r_of, cx, cy, scale, n_samples=160, rotation_grades=0.0)` —
  contour fermé échantillonné finement (cercle ou rayon variable) ; sert au
  **remplissage** à rayon variable (bois/écorce/cernes). Le cas circulaire
  garde la primitive native des renderers (`d.ellipse` / `create_oval`) →
  goldens byte-identiques.
- `ring_polygon_points(outer, inner)` — point unique fermé d'un anneau
  (écorce à rayon variable) par la technique du trou de serrure, SANS le
  piège de `outer + inner[::-1]` à la main (deux ponts à des angles
  différents ⟹ fin coin non rempli à la jointure, cf. CLAUDE.md « Piège
  corrigé — anneau d'écorce à rayon variable »). Utilisé par
  `_draw_ecorce`/`_pil_draw_ecorce` et `dialogs.ask_cepee_layout`.
- `contrefort_zone_outline(zone, contreforts, R, ep_cm, cx, cy, scale, R_inner=None, rotation_grades=0.0)`
  — dict `{wood_outer, base, bark_outer?, bark_inner?}`. `R` (et `R_inner`) =
  `RadiusSpec`.
- `degradation_externe_outline(deg, contreforts, R, ep_cm, cx, cy, scale, rotation_grades=0.0)`
  — `R` = `RadiusSpec`. Suit toujours la cloche des contreforts ; départ
  `R+bell+ep` (deg comprend l'écorce, `deg.comprend_ecorce` défaut True) ou
  `R+bell` (sous l'écorce), + recouvrement anti-couture `_BARK_SEAM_PX`.

**`rotation_grades` (cépée)** : commun aux 4 helpers ci-dessus (+
`diagnostic.sondage_render_data`). Décale l'**angle de placement** des points
(`polar_to_xy(..., g + rotation_grades)`) tout en évaluant le rayon/cloche au
grade **local** `g` → la forme (rayon variable comprise) et les mesures du
brin pivotent ensemble. Défaut 0.0 ⟹ `g + 0.0 == g`, rendu byte-identique
(cavité/sondages gardent en plus le chemin `polar_idx_to_xy` exact quand
`rotation_grades` falsy). Les ticks/cardinales (boussole monde) n'ont PAS de
rotation. Un cercle étant invariant par rotation, seul le chemin à rayon
variable est pivoté côté contour.
- `adaptive_ruler_step_cm(scale_px_per_cm, min_gap_px)` — pas de graduation.
- `radial_ruler_grade(sondage_grades, rotation_grades)` — grade MONDE de
  l'échelle radiale d'un brin : Est (100) par défaut, direction libre la plus
  proche si un sondage y est rendu (alternance 125, 75, 150, 50, …) ; retombe
  sur 100 si les 16 directions sont sondées. Les renderers ne passent les
  grades de sondage QUE si les sondages sont affichés (`show_sondages`).
- `radial_ruler_data(cx, cy, scale, R, ep, grade, step_cm, tick_len_px,
  label_offset_px)` → `RadialRulerData(axis, bark, ticks)` — géométrie px de
  l'échelle radiale centre→bois (+ segment écorce), tirets perpendiculaires
  étiquetés : « 0 », multiples du pas (repli médian si aucun ne tient),
  terminal « R+ep cm » au bout de l'écorce. `None` si `R <= 0`.
- `tick_endpoints`, `cardinal_label_positions` (`R_ext` = `RadiusSpec`).
- `brins_layout(positions_extents, width, height, margin_top, margin_bottom,
  margin_side)` → `(scale, origin_x, origin_y)` — **cadrage d'une cépée** :
  bounding box cm de N brins (`(pos_x, pos_y, extent_cm)`) → facteur px/cm
  commun + position écran de l'origine (cœur du brin[0]). Top-aligné, centré
  horizontalement. Le mono-brin garde son cadrage dédié (à l'ULP près) → la
  fonction n'est appelée que pour une vraie cépée.

## `model.py` — dataclasses + mutateurs de cohérence

Vocabulaire (écologie des plantes clonales) : `Arbre` = **genet** (individu
inventorié) ; `Brin` = **ramet** (tige physique autonome). Un arbre mono-caule
= un genet à brin unique ; une **cépée** = plusieurs brins. Voir CLAUDE.md
« Genet / brin » et la mémoire `project_cepees-formes`.

- `Sondage` — `.prbs_cm` (alias), `.ratio_tR_brut(R)` (CSV uniquement). Ne
  porte PAS de diamètre local (cf. `Brin.diametres_locaux` ci-dessous — un
  diamètre local est indépendant de tout sondage).
- `DegradationExterne` — `.largeur_grades()`, `.couvre_grade(grade)`,
  `.profondeur_bois_cm(ep)` (profondeur consommant du bois ; déduit l'écorce si
  `comprend_ecorce`), champ `comprend_ecorce: bool = True`.
- `Contrefort` — `.grade_debut()`, `.grade_fin()`, `.largeur_cm(R)`.
- `Brin` (= ramet) — porte la **géométrie et les mesures propres à la tige** :
  `rayon_tronc_cm` (rayon général), `diametre_sous_ecorce_cm`,
  `epaisseur_ecorce_cm`, `sondages`, `degradations_externes`, `contreforts`,
  `diametres_locaux: Dict[int, float]` (grade → diamètre cm, **indépendant de
  tout sondage** — permet un point de forme sans PRBS mesurée là, p. ex. un
  méplat entre deux sondages), position `pos_x_cm/pos_y_cm` +
  `rotation_grades` (cépées) : tous trois édités par l'éditeur de disposition
  (`dialogs.ask_cepee_layout`) ; `rotation_grades` est appliqué au rendu
  (cf. § geometry `rotation_grades`).
  Propriété `a_rayon_variable` (un rayon local diffère du général) ;
  `rayon_a_grade(grade)` (rayon LOCAL — exact aux 16 grades canoniques via
  `_rayon_locaux()`, interpolé en LISSANT par cosinus entre voisins mesurés
  sinon — borné, sans angle vif) ; `extent_cm()` = rayon d'**encombrement**
  (rayon local max + écorce + plus longue saillie de contrefort), pour le
  cadrage cépée. `label` (« a »/« b »/… ; "" si brin unique). Mutateurs :
  `set_rayon(new_R)` et `set_diametre_local(grade, diametre_cm)` — ce
  dernier réaligne le bois altéré du sondage éventuellement présent à cette
  direction **sans jamais retoucher sa PRBS** (contrairement à `set_rayon`,
  qui reclampe la PRBS de tous les sondages via `_resync_sondages_local()`) ;
  `renumeroter_sondages/degradations/contreforts()`.
- `Arbre` (= genet) — identité partagée (`numero_arbre`, `essence`,
  `hauteur_sondage_cm`, `hauteur_arbre_m`, `port_arbre`, `meche_cm`,
  `commentaire`) + `brins: List[Brin]` (≥ 1). **Propriétés-relais et méthodes-relais**
  (`rayon_tronc_cm`, `sondages`, `diametres_locaux`, `set_rayon`,
  `set_diametre_local`, `rayon_a_grade`, …) délèguent au **brin courant** (`brins[0]`) pour que le code écrit avant les
  cépées (≈140 accès) tourne inchangé. Constructeur **rétro-compatible** : les
  kwargs de géométrie/mesures sont routés vers `brins[0]`. Prop : `display_name`,
  `brin_courant`. **Gestion de cépée** : `ajouter_brin()` (nouveau brin héritant
  la forme du brin le plus à l'Est, placé à l'Est sans recouvrement, PAS les
  mesures), `supprimer_brin(i)` (≥ 1 garanti), `_relabel_brins()` (a/b/c… ou ""
  si mono-caule). *Les relais `brins[0]` sont une couche de compat (« Étape 0 »).
  L'Étape 4a a commencé à les retirer côté UI : les onglets de saisie ciblent
  désormais le brin courant explicite (`App._current_brin()`). Les relais restent
  pour les nombreux autres appelants (rendu, exports, diagnostic mono-brin).*
- `Chantier` — nom, adresse, opérateur, date, arbres.

## `diagnostic.py` — calculs purs par section + agrégation genet

Toutes les fonctions sont **pures** (pas de mutation, pas de cache sur l'arbre).
Type `Section = Union[Arbre, Brin]` : la chaîne de calcul opère sur une
**section** (un `Brin` natif, ou un `Arbre` mono-brin via shims), le `port`
genet-level étant passé explicitement quand il intervient.

- `compute_alteration_par_grade(section)` — extrapolation pondérée linéaire
  (lit `bois_altere_cm`, **indépendant du rayon**).
- `degradation_externe_par_grade(section)` — profondeur **consommant du bois**
  max par direction (déduit l'écorce des dégradations qui la comprennent).
- `rayon_par_grade(section)` — 16 rayons extérieurs (constant = `rayon_tronc_cm`
  si circulaire, rayon local sinon via `section.rayon_a_grade`).
- `prbs_par_grade(section)`, `ratio_tR_par_grade(section)` — composent les
  trois ; dénominateur t/R = **rayon LOCAL** de chaque direction (apport du
  diamètre local par sondage).
  `sondage_render_data(section, port, meche, …)` calcule pastille + t/R au rayon
  local du grade sondé.
- `repartition_classes_brin(section, port)` → `DiagnosticSnapshot` (self-contained :
  répartition, ratios, direction critique, t/R moyen, classe globale,
  `diagnostic_fiable`, `extrapolation_text`). `repartition_classes(arbre)`
  **délègue** au brin courant (compat mono-brin).
  - `snap.diagnostic_global` → `Optional[Tuple[float, str]]` — point
    d'entrée unique ; renvoie `None` (t/R moyen + classe masqués) tant
    que `diagnostic_fiable` est faux, c.-à-d. **< 3 directions sondées**
    (seuil métier, découplé du minimum d'extrapolation de la cavité = 2).
  - `snap.par_classe(cls)` — accès indexé par label.
- **Agrégation cépée** : `genet_diagnostic(arbre)` → `GenetDiagnostic(brins:
  List[BrinDiagnostic], classe_globale, fiable)`. `classe_globale` = **pire
  classe parmi les brins FIABLES** (rayon + ≥3 sondages) via `pire_classe()`
  (ordre Rouge > Orange > Vert) ; `None` si aucun brin fiable. `fiable` = au
  moins un brin fiable. Un brin non fiable est rapporté (`BrinDiagnostic`) mais
  n'entre PAS dans la classe globale (décision : **fiabilité par brin**).
- `extrapolation_summary(section)` / `extrapolation_summary_text(section)`.
- `diagnostic_summary_lines(arbre)` (brin courant) et `genet_summary_lines(arbre)`
  (mono = idem ; cépée = en-tête classe globale + un bloc par brin), via le cœur
  `_section_summary_lines(section, port, titre)`.
- `mission_synthesis_rows(chantier)` → une ligne genet par arbre mono-caule ;
  une cépée = **ligne de tête** (classe globale = pire brin) + une **sous-ligne
  par brin** (`MissionSynthesisRow.brin_label`).

Convention : classe globale d'un **brin** = t/R **moyen** (confirmé Edwin
Colinet mai 2026) ; classe globale d'un **genet** = **pire classe** parmi ses
brins fiables (jamais une moyenne inter-brins — repères polaires distincts).

## `persistence.py` — I/O JSON des missions

- `FORMAT_VERSION = 3` — versionne le format. v3 = introduction des **brins** :
  la géométrie/mesures qui vivaient sur `arbre` passent dans `arbre.brins[i]`.
- `chantier_to_dict` / `chantier_from_dict` — sérialisation symétrique. Helper
  `_brin_from_dict(bd)` reconstruit un `Brin` ; il sert pour les **deux** formats :
  v3+ (`bd` = `arbre["brins"][i]`) **et** v≤2 (`bd` = l'arbre lui-même, dont la
  géométrie/mesures à plat sont migrées en un **brin unique** centré).
- `save_chantier` / `load_chantier` — wrappers fichier UTF-8.
  **Écriture atomique** : write dans `.tmp` puis `os.replace` — le fichier
  original survit en cas de crash (disque plein, coupure de courant).
- Migration ascendante : anciens libellés de port (v3.1 → v3.2) ; v≤2 → brins.
- Migration descendante : filtre par `__dataclass_fields__` + WARNING logged.

## `pane_*.py` — onglets Tk autonomes

Chaque pane : hérite `ttk.Frame`, possède ses widgets, expose `refresh()`,
déclare un `Protocol` host (`_*Host`). Tables Treeview incluent leur propre
cycle add/edit/del via `dialogs.py`. `IdentificationPane` gère la synchro
bidirectionnelle Ø ↔ R, le **filtrage des champs numériques à la frappe**
via `dialogs.validate_numeric` (Diamètre, Rayon, Mèche, Épaisseur écorce,
Hauteur sondage, Hauteur arbre — accepte virgule ou point décimal), le
revert au focus-out en filet de sécurité, et le `_commit_rayon` différé
(set_rayon uniquement au focus-out, pas pendant la frappe — protège les
PRBS des valeurs intermédiaires). Form groupé en 4 `ttk.LabelFrame`
(Arbre / Tronc / Sondage / Notes) pour clarifier les unités (m vs cm).
Le **diamètre local par sondage** (rayon variable par direction) se saisit
**en ligne** dans la grille Sondages (colonne « Ø local (cm) », pas dans
l'onglet Identification — a remplacé l'ancien éditeur avancé de tronc ovale).
Sous les champs Tronc, les actions **« ＋ Brin » / « − Brin »** (`App.add_brin` / `remove_last_brin`,
via `Arbre.ajouter_brin` / `supprimer_brin`) construisent une cépée + un
compteur de brins (« − Brin » désactivé en mono-caule), et **« Disposition… »**
ouvre l'éditeur de placement des brins à la souris (`dialogs.ask_cepee_layout`,
activé si ≥ 2 brins).

**Saisie par brin (Étape 4a)** : la géométrie de l'onglet Identification
(rayon/diamètre/écorce/forme) et les onglets **Sondages / Dégradations /
Contreforts** éditent le **brin courant** (`App._current_brin()`), pas
forcément `brins[0]` ; l'identité (n°, essence, port, hauteurs, mèche) reste
au niveau **genet**. Le brin courant est choisi par une barre « Brin a/b/c »
au-dessus des onglets (`App._refresh_brin_selector` / `set_current_brin`,
masquée en mono-caule) ; il est remis à 0 à chaque changement d'arbre.
Avant de basculer de brin, `IdentificationPane.flush()` commite un rayon en
cours d'édition (sinon il s'appliquerait au mauvais brin).
`DiagnosticPane` est scrollable (Canvas interne) : résumé, tableau PRBS,
préconisation — **plus d'exports depuis le 2026-09-05** (déplacés vers
le menu **Export** de la barre de menu, cf. `app_menu.py` ci-dessous).
La checkbox « Afficher sondages » a été déplacée hors de ce pane et vit
désormais sous le canvas (`App._build_right`). Pour une **cépée**, le
résumé passe par `genet_summary_lines` (un bloc par brin + classe
globale) et le tableau PRBS itère tous les brins (N° préfixé « a1 »).

## `app_exports.py` — actions d'export Tk

Adaptateur : vérifie prérequis, gère `filedialog`, entoure d'un try/except
avec logging. Thin wrappers depuis `App.action_export_*`.

- `export_pdf_mission` : PDF multi-pages (Pillow `save_all`) regroupant
  toutes les fiches arbres d'une mission.

## `app_menu.py` — barre de menu Tk

`build_menu(app)` attache la barre de menu et bind les raccourcis
globaux. Six cascades :

- **Fichier** : Nouvelle (Ctrl+N), Ouvrir (Ctrl+O), **Ouvrir récent**
  (sous-menu populé par `refresh_recent_menu(app)` depuis
  `app.get_recent_files()`), Enregistrer (Ctrl+S), Enregistrer sous ;
  ouvrir le dossier des sauvegardes ; Quitter. **Ne contient plus les
  exports** (2026-09-05, déplacés vers le menu **Export**, ci-dessous)
  ni l'impression (supprimée, doublon de l'export PDF).
- **Export** (2026-09-05, entre Affichage et Aide) : point d'entrée
  unique des 8 `action_export_*` — avant, dispersées entre ce menu
  (exports mission) et l'onglet Diagnostic (exports arbre). Organisé
  **par format de fichier** plutôt que par portée : un bloc PDF, un PNG,
  un XLSX, un CSV, un HTML, séparés par des séparateurs et ouverts par
  un en-tête désactivé nommant le format ; chaque libellé précise
  lui-même s'il porte sur l'arbre courant ou sur la mission — choix
  produit d'Edwin. Le bouton « Imprimer » (impression directe,
  `app_exports.print_pdf_arbre`) a été supprimé avec ce rangement
  (doublon avec l'export PDF), avec son ancienne entrée du menu Fichier
  et son raccourci Ctrl+P.
- **Arbres** : Ajouter (Ctrl+T), Ajouter en héritant du précédent ;
  Arbre suivant (Ctrl+PgDn) / précédent (Ctrl+PgUp) ; Dupliquer,
  Renommer, Supprimer.
- **Affichage** : Taille du texte (Petit/Normal/Grand/Très grand,
  radiobuttons) ; Contraste élevé (checkbutton).
- **Comparaison** : Faire une comparaison (ré-inspection), Choisir la
  mission de référence, Diagnostic de la comparaison.
- **Aide** : Guide de démarrage, Raccourcis clavier, separator, Contacter
  le support, Ouvrir le fichier de log, separator, Vérifier les mises à
  jour / Vérification automatique, separator, Redémarrer, À propos.

`refresh_recent_menu(app)` est exposée pour être réappelée par l'App
après chaque ouverture/enregistrement ; elle vide et reconstruit le
sous-menu Récents depuis `app.get_recent_files()`. Le menu est exposé
sur l'App via `setattr(app, "_recent_menu", recent_menu)`.

## `app_style.py` — thème ttk

`apply_ttk_styles(root)` configure les styles ttk de l'app. Inclut le
**workaround bpo-36468** (`_fixed_map`) qui retire les entrées
`("!disabled", "!selected", …)` du `style.map` de `Treeview` et
`Side.Treeview` pour que `tag_configure(foreground=…)` reprenne enfin
la main. Sans ce patch, les tags d'état de la liste d'arbres seraient
silencieusement ignorés. Le style `Side.Treeview` ne force PAS
`foreground=white` sur la sélection — ainsi la couleur d'état reste
visible sur l'arbre courant (fond vert pâle `COLOR_ACCENT_SOFT`).

## `pil_render.py` — rendu PNG de la section

- `render_arbre_to_pil_image(arbre, …)` — orchestrateur enchaînant
  les `_pil_draw_*`. Facteur d'échelle `_ds = max(1.0, min(w,h)/1200)`
  pour que les polices, pastilles et traits de la règle grossissent
  automatiquement avec la résolution (ex. 2400×2400 pour le PNG export)
  sans affecter les petits dessins (vignette PDF ~600 px, `_ds = 1.0`).
- Helpers exposés : `_pil_load_fonts()`, `_draw_horizontal_legend_pil()`.
- `HAS_PIL` : False si Pillow absent.
- **Rayon variable** : chaque couche de contour (bois/cernes/écorce) **branche
  sur `brin.a_rayon_variable`** — circulaire → primitive native `d.ellipse`
  (rendu inchangé, goldens stables) ; rayon variable → polygone via
  `contour_polygon`. Les contreforts/dégradations/ticks/cardinales reçoivent
  `brin.rayon_a_grade` (constant si circulaire → byte-identique).
- **Échelle radiale** : `_pil_draw_echelle_radiale` (appelée en DERNIER dans
  `_pil_draw_brin` → premier plan, halo blanc) — axe gradué centre→bois +
  segment écorce le long de `radial_ruler_grade` (Est, esquive des sondages).
  Une échelle **par brin** (mono-brin compris). Pendant Tk :
  `SectionCanvas._draw_echelle_radiale`.
- **Cépée** : `_pil_draw_brin(d, f, brin, port, meche, cx, cy, R, ep, scale, …)`
  dessine UNE section centrée (toutes les couches per-brin) ; l'orchestrateur
  dérive tôt vers `_pil_draw_cepee` dès que `len(brins) > 1` ou un brin décentré
  (le mono-brin centré garde le chemin verbatim → goldens intacts). `_pil_draw_cepee`
  compose les brins via `geometry.brins_layout`, ajoute un label par brin
  (`_pil_draw_brin_label`) et **une seule boussole globale** sur le rectangle de
  la bbox (les ticks restent par brin). Une cépée étant large (cadrée sur la
  largeur), les brins sont **centrés verticalement** ; chaque brin porte son
  **échelle radiale**, et la bande basse reçoit la **légende** en export
  (`show_legend`). Pendant Tk : `SectionCanvas._draw_cepee` (même centrage,
  sans légende). Fixtures golden `cepee`, `cepee_rotation`.

## `fiche_pdf.py` — fiche PDF A4 VECTORIELLE (fpdf2)

- **PDF vectoriel** (fpdf2) : texte sélectionnable/cherchable, net au zoom,
  fichier ~3-4× plus léger que l'ancien rendu raster. **Hybride** : texte +
  tableau + diagnostic + préconisation en vectoriel ; le **dessin de section**
  (`pil_render.render_arbre_to_pil_image`) et la **légende horizontale**
  (`_draw_horizontal_legend_pil`) **restent raster** et sont **collés** via
  `pdf.image` — les réécrire en vectoriel serait énorme et sans gain.
- **API** : `_new_pdf()` crée le document (A4, unité = 1 px @150 DPI via
  `FPDF(unit=72/150, format=(1240,1754))` ⟹ **coordonnées historiques
  conservées verbatim** ; polices DejaVu embarquées enregistrées par
  `add_font` — l'Helvetica de base est latin-1). `render_fiche_arbre(pdf,
  arbre, chantier, *, show_sondages=True, …)` **ajoute** la/les page(s)
  (fiche + page photos si `arbre.photos`). Un arbre : `_new_pdf` +
  `render_fiche_arbre` + `pdf.output(p)`. Mission : **un seul** `pdf`, boucle,
  `output` (concaténation native — plus d'`append_images`).
- `_Page` = fine surface de dessin sur le `FPDF` (text/rect/line/polygon/image)
  qui **émule les ancres PIL** (`la`/`lm`/`rm`/`mm`/`mt` → décalage horizontal
  via `get_string_width`, ligne de base via fractions de l'em `_ASC`/`_MID`) et
  convertit les tailles de police « px » en points (`× 72/150`).
- `show_sondages` (= case « Afficher les sondages » sous le canevas, propagée
  par `app_exports.export_pdf_arbre`/`_mission`) masque les pastilles **sur le
  dessin** ET l'item « Sondage » de la légende (`show_sondage_item`) — le
  **tableau PRBS reste** (c'est la donnée).
- Assemble : en-tête + logo, identité arbre, dessin section (collé, via
  `pil_render`), légende (bande PIL collée), tableau PRBS, diagnostic
  (t/R moyen+min, barre répartition, classe), préconisation/suivi, pied.
  **Barre répartition = UNE lecture (2026-09-05)** : `_draw_mono_diagnostic`
  n'affiche plus, sous la barre colorée, la ligne fractionnaire « Vert N/16
  (X gr) • … » — même information que les pourcentages déjà sur la barre,
  jugée redondante.
- **Page photos** (`_render_photos_page`) : pied de page = `_draw_footer`
  comme la page principale (barème + **cabinet**, était ré-écrit à la main
  sans le cabinet) ; légende sous chaque photo = « Photo N » — **jamais**
  le nom de fichier (chemin libre non maîtrisé, cf. « Photos = entrée
  semi-fiable » de `CLAUDE.md`).
- **Pas de golden pixel** (les goldens `test_render` visent `comparaison_render`,
  resté raster) : couverts par `FichePdfSmokeTests` (`%PDF` + nb pages) ; les 2
  tests de dessin (`FichePdfSondagesTests`, `FichePdfCepeeLayoutTests`) sont
  redirigés sur `render_arbre_to_pil_image` (l'info qu'ils vérifient vit dans
  le dessin, resté PIL).
- Dimensionnement adaptatif : au-delà de 8/12 sondages, police et hauteur
  de ligne se resserrent pour rester sur 1 page.
- **Cépée** : tableau PRBS itère tous les brins (N° préfixé « a1 ») ; le bloc
  diagnostic est routé — mono-caule = `_draw_mono_diagnostic` (verbatim, barre
  + encadré classe), cépée = `_draw_cepee_diagnostic` (encadré « Classe globale
  (pire brin) » + une ligne de synthèse par brin). **Dessin pleine largeur** :
  le carré historique (calibré section ronde) rendait chaque brin minuscule —
  pour une cépée (même prédicat de routage que les renderers), `drawing_w` =
  largeur utile de la page et la hauteur est bornée par le ratio cm réel de la
  cépée (+ ~200 px de marges internes) pour éviter les bandes blanches ;
  `est_diag_h` est aussi estimé au réel (encadré + 28 px/brin, pas le majorant
  mono 360). Verrouillé par `FichePdfCepeeLayoutTests`.

## `section_canvas.py` — rendu Tk de la section

`SectionCanvas(tk.Canvas)` : `redraw()` orchestre les `_draw_*` (ordre =
superposition). Pendant Tk de `pil_render` — géométrie partagée, visuels
spécifiques (polices, outline+width, smooth, flèches). Même gestion de la
**rayon variable** que PIL (branche `a_rayon_variable` : `create_oval` natif
si circulaire, `contour_polygon` via `create_polygon` sinon ;
`rayon_a_grade` passé aux helpers de contour). **Cépée** : `_draw_brin(brin,
port, meche, …)` pour une section ; `redraw` dérive vers `_draw_cepee` dès
qu'il y a plusieurs brins / un brin décentré (mono-brin centré = verbatim,
golden `section_canvas_cepee`). `_draw_cepee` : `brins_layout` + label par brin
+ boussole globale ; l'interaction (clic-pour-éditer) reste mono-brin
(`_geom=None` en cépée — l'édition multi-brins viendra à l'Étape 4).

**Canvas interactif** : accepte un `host: _CanvasHost` optionnel. Quand
fourni, chaque pastille de sondage, arc de dégradation externe et zone
de contrefort est dessiné avec des tags `<type>_item` + `<type>_idx_<i>`.
`tag_bind("<Button-1>")` retrouve l'index via `_picked_index()` et appelle
`host.open_edit_*(obj)` — qui ouvre le dialogue d'édition, push undo et
rafraîchit la table correspondante. Pour les contreforts, les zones
fusionnées (cf. `geometry.contrefort_zones`) sont taggées avec l'index
du premier CF de la zone (cas mono-CF = 99 % des usages ; pour les
multi-CF, l'édition des autres reste accessible via l'onglet Contreforts).
Le clic est différé via `after_idle` pour laisser la boucle Tk finaliser
le clic avant la création du Toplevel modal (sinon race avec le focus du
Canvas). Curseur `hand2` au survol des items cliquables.

**Ajout par clic sur le fond** : un binding `<Button-1>` au niveau widget
(`_on_click_background`) convertit le pixel cliqué en grade (inverse de
`geometry.polar_to_xy`, via la géométrie du dernier rendu mémorisée dans
`self._geom`). Sur une direction libre → `host.open_add_sondage(grade)` ;
sur une direction déjà sondée → édition. Garde par tags : si le clic
porte sur un item interactif, le handler dédié s'en charge et le fond
est ignoré. Clic au-delà de l'anneau des cardinales → ignoré.

## `export.py` — exports tableau PRBS (XLSX/HTML)

- `prbs_table_rows_par_sondage(arbre, classer_prbs)` — données pures ; itère
  les **brins** (protocoles `BrinLike` + `brins` sur `ArbreLike`), N° de sondage
  préfixé par le label du brin en cépée (« a1 »), entier simple en mono.
- Synthèse mission (`export_synthesis_csv/xlsx`) : les sous-lignes de brin
  (`MissionSynthesisRow.brin_label`) s'affichent « ↳ brin a », identité genet
  laissée vide ; le bilan ne compte que les genets.
- `export_prbs_xlsx(…)` — Excel stylé (openpyxl). Mise en page propre à
  Pénétromètre (terminologie interne, plus de gabarit externe) : titre mission
  + identité de l'arbre en toutes lettres (bannières fusionnées), puis les
  9 colonnes N° · Direction · Grade · Rayon · PRBS · Bois altéré · t/R
  (coloré par classe) · Classe (texte coloré) · Compart. (glyphe coloré),
  alternance de lignes, en-tête gelé. Sous le tableau : une ligne
  **Diagnostic** (t/R moyen + classe globale, alignée sur la fiche PDF,
  masquée si < 3 sondées via `DiagnosticSnapshot.diagnostic_global`), une
  légende compartimentation ✓/✗/– puis une légende des classes colorée.
  Verrouillé par `test_diagnostic_et_legendes_du_tableau`.
- `export_prbs_html(…)` — HTML autonome imprimable, même thème vert.
  **À garder aligné sur le XLSX** : mêmes colonnes (dont Direction/Classe),
  même ligne Diagnostic, légende compartimentation à 3 entrées (✓/✗/–) ET
  légende des classes colorée (`.classe-legend`). Verrouillé par
  `HtmlExportAlignementTests` — toute modif du XLSX doit être reportée ici.
- Injection de `couleur_classe` + `classer_prbs` pour éviter cycles.

## `dialogs.py` — boîtes de dialogue Tk

`edit_sondage`, `edit_degradation`, `edit_contrefort` : reçoivent
`(parent, section, obj)`, mutent en place, renvoient `True/False`. Chacun
bind `<Return>`→Valider, `<Escape>`→Annuler, et pose le focus initial
sur son 1er champ utile (la combobox Direction/Orientation). Le paramètre
`section` est typé `Section = Union[Arbre, Brin]` (ils ne lisent que
`rayon_tronc_cm` + la liste de mesures, présentes sur les deux) → ils
peuvent éditer un brin précis d'une cépée.

`ask_string(parent, title, prompt, initial, info=…)` : dialogue de
saisie texte thémé (look ttk Pénétromètre) qui remplace
`simpledialog.askstring`. Renvoie `None` si annulé, la chaîne (sans
`strip`) si validé — `""` validé ≠ `None`. Utilisé par
`App.action_rename_arbre`.

Le diamètre local par direction (rayon variable, `Brin.diametres_locaux`,
cf. `model.py` ci-dessus) n'a pas de dialogue dédié : saisi en ligne dans la
grille Sondages (colonne « Ø local (cm) », toujours active — indépendante
d'un sondage sur la ligne).

`ask_cepee_layout(parent, arbre) -> Optional[List[Tuple[float, float, int]]]` :
**éditeur de disposition d'une cépée** (Étape 4b/4c). Canvas qui dessine chaque
brin (contour fidèle via `geometry.contour_polygon` — cercle ou rayon
variable par direction, **écorce comprise** si mesurée via
`geometry.ring_polygon_points` — sans elle deux brins qui se chevauchent une
fois l'écorce comptée semblaient avoir un écart ; le rayon de détection au
clic/glisser compte aussi l'écorce ; **rotation incluse**), cadrage **figé
à l'ouverture** par `geometry.brins_layout` (le dessin ne saute pas pendant le glissement).
Glisser-déposer un brin fixe sa position `(pos_x_cm, pos_y_cm)` ; la **molette**
au-dessus d'un brin le fait pivoter par pas de 25 gr (`rotation_grades`). Le
brin « a » est l'**ancre** (position fixe en (0,0) ; il peut pivoter). Travaille
sur une copie → renvoie un **triplet** `(pos_x, pos_y, rotation_grades)` par
brin si validé, `None` si annulé (Annuler = no-op). Appliqué par
`App.edit_cepee_layout` (push_undo + redraw) ; déclenché par le bouton
« Disposition… » de `IdentificationPane`.

Helpers publics réutilisés par `pane_identification` :

- `validate_numeric(proposed) -> bool` — validateur Tk (`validate="key"`)
  acceptant chiffres + au plus un séparateur décimal (`,` ou `.`).
- `to_float(s) -> float` — parse `"2,5"` ou `"2.5"` → `2.5` ; `""` → `0.0`.

Tous les champs numériques des 3 dialogues filtrent la frappe via ces
helpers (Entry créée par le helper privé `_numeric_entry`).

Helper privé `_make_modal(dlg, parent)` : séquence canonique
`update_idletasks → transient → wait_visibility → grab_set → focus_set`
appelée APRÈS la création des widgets. Sans cet ordre, les dialogues
ouverts depuis un événement de clic (ex. canvas interactif) apparaissent
**vides** sur Linux/X11 — le grab pris avant que le WM ait mappé la
fenêtre empêche le rendu des enfants.

Validations à la confirmation :

- Sondage : interdit deux sondages sur le même grade.
- Dégradation : interdit les arcs qui se chevauchent (arcs mitoyens
  bout-à-bout autorisés — détection via `couvre_grade` sur les 16 grades).
- Contrefort : interdit deux contreforts sur le même grade central.

## `tooltip.py` — infobulle Tk légère

`Tooltip(widget, text, delay_ms=500)` : attache une infobulle de survol
à n'importe quel widget (petit `Toplevel` sans bordure via
`overrideredirect`, affiché après un court délai, masqué à la sortie ou
au clic). Bindings posés avec `add="+"` pour ne pas écraser ceux du
widget (ex. curseur `hand2`). Importe uniquement `palette`. Utilisé
pour rappeler les accélérateurs (bouton « ＋ Ajouter » → Ctrl+T) et
décrire le bandeau d'export du pane Diagnostic (boutons Fiche PDF / PNG
et menu déroulant « Exporter le tableau » → XLSX / HTML / CSV).

## `undo.py` — pile undo/redo

- `UndoStack` (dataclass) : pile de snapshots `Any` (typée Any pour
  accueillir deux formats), curseur, profondeur max 50. `_live_tip:
  Optional[Any]` retient le snapshot capturé au focus-in sans encore
  l'empiler (seul le focus-out l'empile si la valeur a changé).
- `push(snapshot)` — sauvegarde avant mutation, tronque le futur ;
  remet `_live_tip = None`.
- `set_live_tip(tip)` — idempotent : ne pose le tip que s'il est `None`
  (focus-in suivant ignoré si déjà posé).
- `peek_top()` → snapshot au sommet sans déplacer le curseur.
- `undo(current)` → snapshot à restaurer (ou `None`).
- `redo()` → snapshot à restaurer (ou `None`).
- `clear()` — vidée sur new/open ; remet `_live_tip = None`.
- `can_undo` / `can_redo` — propriétés booléennes.

**Deux formats de snapshot** dans `App._restore_snapshot(snapshot)` :
- `{"_type":"arbre","_idx":int,"_arbre":Arbre}` — snapshot **scopé au brin
  courant** (O(1 arbre)), construit par `capture_undo_snapshot()` quand un
  arbre courant existe. Restauration : remplace l'arbre à `_idx`, rafraîchit
  la liste + l'UI si nécessaire.
- `dict` JSON complet (`chantier_to_dict`) — snapshot global (fallback si
  aucun arbre courant). Restauration : rechargement complet.

Intégré dans `App` via `push_undo()` / `capture_undo_snapshot()` /
`push_undo_snapshot()` (appelés par les panes avant / au focus-in / au
focus-out). Bindings : Ctrl+Z (undo), Ctrl+Y ou Ctrl+Shift+Z (redo).

## `penetrometre.py` — application Tk + main

`App(ArbreListMixin, RecoveryMixin, ExportActionsMixin, FichierMixin,
LayoutMixin, ReglagesMixin, tk.Tk)` — fenêtre principale, layout 3 colonnes
(`PanedWindow`), instanciation des panes, callbacks communs. La logique d'`App`
est **répartie en 6 mixins par responsabilité** dont le détail vit dans CLAUDE.md
(« App = orchestration + 6 mixins + 1 helper ») — on ne le duplique pas ici
pour ne pas le désynchroniser. Ce qui reste **dans `penetrometre.py`** :

- **Dirty flag** (`_dirty`) : tracké sur toute mutation, reset au
  save/open/new. Titre dynamique avec `•` si modifié.
- **WM_DELETE_WINDOW** : confirme la fermeture si dirty.
- **Undo/redo** : `push_undo()` + `_perform_undo/redo()` via
  `UndoStack` + `chantier_to_dict`/`chantier_from_dict`.
- **Meta mission** : push undo sur FocusOut (pas à chaque frappe).
- **Géométrie de fenêtre adaptative** : `minsize(1100, 680)` + clamp
  à 95 % de l'écran via `winfo_screenwidth/height` au démarrage.
- **Déporté en mixins** (détail dans CLAUDE.md) : la **liste d'arbres**
  (deux colonnes **État** + **Risque** ; `_arbre_etat(a) -> (glyphe, risque,
  tag)` — État = forme = complétude `○/◐/●`, Risque = mot Vert/Orange/Rouge
  ou « — », incomplets en **gris neutre** ; filtres texte + classe ; menu
  contextuel) → `app_arbres.ArbreListMixin` ; l'**autosave/récupération** →
  `app_recovery.RecoveryMixin` ; le **cycle de vie fichier mission**
  (new/open/save/save_as, `_open_path`, récents, ré-inspection) →
  `app_fichier.FichierMixin` ; les **exports** (`action_export_*`) →
  `app_export_actions.ExportActionsMixin`. L'historique des récents est
  persisté par `app_recent.RecentFilesStore` (`self._recent.push/remove/get`
  — il n'y a plus de `_*_recent_files` sur `App`).
- **Callbacks canvas interactif** : `open_edit_sondage(s)`,
  `open_edit_degradation(d)`, `open_edit_contrefort(c)` — appelés par
  `SectionCanvas` au clic sur un item, ouvrent le dialogue puis push
  undo, refresh table et redraw. `open_add_sondage(grade)` — appelé au
  clic sur une direction libre du dessin (cf. `section_canvas`).
- **Barre d'état** : `_build_statusbar()` (bas de fenêtre).
  `notify_export(path, label)` affiche le succès d'un export (non-modal,
  appelé par `app_exports._notify_export`) et active les boutons
  « Ouvrir le fichier / le dossier » → `_open_in_system(path)`
  (cross-platform). `set_status(text)` met à jour le message.
- **Raccourci export** : `Ctrl+E` → `action_export_pdf_arbre`, bind dans
  `__init__` via `_on_export_shortcut` qui ne déclenche pas si un
  `Entry`/`Combobox` a le focus (Ctrl+E = « fin de ligne » dans Tk).
- **Aide** : `action_about`, `action_shortcuts` (popup raccourcis,
  inclut Ctrl+Tab entre onglets via `nb.enable_traversal()`),
  `action_open_log` (ouvre `~/.penetrometre/penetrometre.log` avec
  l'éditeur par défaut, cross-platform via `os.startfile`/`open`/
  `xdg-open`).

## Couche App — mixins et helpers (carte)

`App` délègue par **responsabilité** à 6 mixins + 1 helper (couplage
**assumé** : sauf `ExportActionsMixin`, les mixins lisent et mutent l'état
d'`App`). Détail et justification dans CLAUDE.md (« App = orchestration +
6 mixins + 1 helper ») ; carte synthétique :

- **`app_arbres.ArbreListMixin`** — panneau gauche « Arbres de la
  mission » : filtre texte + classe de risque + filtre échéance/complétude,
  `Treeview`, pastilles d'état (`_arbre_etat` → colonnes État + Risque),
  cache `_etat_cache` (keyed by `id(arbre)` pour éviter les doublons de
  `genet_diagnostic()`), footer de **triage**
  (`_update_etat_footer` : `N rouge · N orange · N vert · N à finir`),
  navigation clavier, CRUD (ajouter vierge / hériter, dupliquer, renommer,
  supprimer).
- **`app_recovery.RecoveryMixin`** — autosave anti-crash (tick 60 s tant
  que `_dirty`) + récupération au démarrage. Fournit `_RECOVERY_PATH`.
- **`app_export_actions.ExportActionsMixin`** — les `action_export_*`
  (PNG, fiche PDF, PDF mission, CSV, synthèse XLSX/CSV, PRBS XLSX/HTML) ;
  pur dispatcher en lecture seule vers `app_exports` (seul mixin découplé).
- **`app_fichier.FichierMixin`** — cycle de vie du fichier mission
  (new/open/save/save_as, `_open_path`, récents) + **ré-inspection**
  (`action_load_reference`/`_compare_arbre`/`_export_comparison`). Fournit
  `_BACKUP_PATH` (sauvegardes glissantes).
- **`app_layout.LayoutMixin`** — construction de l'UI (`_build_layout` /
  `_build_left` / `_build_center` / `_build_right` / `_build_statusbar` + sash,
  `_trial_banner`). Quasi-pur builder : crée et assigne la plupart des
  attributs UI d'`App` (`tree_arbres`, `nb`, `section`, `var_*`, les 5 panes…).
- **`app_reglages.ReglagesMixin`** — préférences + mises à jour
  (`action_set_language` / `_set_ui_scale` / `_set_high_contrast` /
  `_bareme_settings` / `_cabinet_settings`, `_apply_ui_scale` /
  `_apply_styles` / `_apply_bareme` au démarrage, cycle vérification de
  version + bannière, `action_restart`).
- **`app_recent.RecentFilesStore`** (composition, pur) — historique des
  fichiers récents (JSON, 8 max, déduplication, callback `on_change`).

## Modules annexes

- **`license.py`** (pur) — vérification/chargement/sauvegarde de licence
  offline Ed25519 (`_PUBLIC_KEY_B64`). `LicenseData` + `TrialInfo` (essai
  30 jours). `get_machine_id()` = SHA-256[:12] de l'ID platform
  (`/etc/machine-id` Linux, `ioreg` macOS, registre Windows). `is_bundled()`
  : True en binaire de production **PyInstaller** (`sys.frozen`) **OU Nuitka**
  (`__compiled__` dans les globals) — les contrôles de licence ne s'activent
  qu'en bundle, jamais en dev. `get_trial_info()` / `start_trial()` / `save_license()`.
- **`dialogs_license.py`** — fenêtre d'activation bloquante au démarrage
  (si bundle sans licence). Retourne `Optional[Union[LicenseData, TrialInfo]]`.
  Affiche l'identifiant machine + bouton Copier ; bouton « Essai 30 jours »
  (caché si essai déjà démarré) ; contact `e.colinet@silvavenir.fr`.
- **`gen_license.py`** — outil interne d'émission de clés (non distribué).
  Sous-commandes : `issue` (name + email + expiration optionnelle +
  `--machine-id ID12`), `verify`, `machine-id`. Non committé avec `private.key`.
- **`i18n.py`** — internationalisation : `_("…")` wrapper autour de
  `gettext`. Catalogues dans `translations/` (`en.py`, `it.py`, `fr.py`).
  Sélecteur de langue persisté dans `settings.json`
  (`app_reglages.action_set_language`, redémarre l'app).
- **`bareme_store.py`** — barème t/R configurable. Charge `~/.penetrometre/
  bareme.json` si présent, sinon défauts codés. Exposé via
  `dialogs_settings.py` (dialog **Réglages → Barème…**).
- **`dialogs_settings.py`** — dialogs de préférences avancées (barème t/R,
  nom du cabinet, logo).
- **`dialogs_shared.py`** — helpers **purs** partagés entre dialogues et panes
  (validateurs numériques, choix de grades, dates). Porte la **source unique
  des symboles de compartimentation** : `COMPART_GLYPH`/`COMPART_COLOR` +
  `compart_glyph`/`compart_color`/`compart_visual` (**✓** active / **✗** absente
  / **—** non renseignée) — le même glyphe est affiché à la **saisie**
  (`compart_label`/`compart_from_label` préfixent/retirent le glyphe du
  combobox) **et** dans **tous les exports** (XLSX/HTML via `export.py`, PDF via
  `fiche_pdf.py`).
- **`update_checker.py`** — vérification des mises à jour via l'API GitHub
  Releases (timeout 2 s, best-effort). Activé au démarrage et via
  **Aide → Vérifier les mises à jour**.
- **`template_store.py`** — modèles de mission réutilisables : sauvegarde /
  chargement d'un `Chantier` sans arbres comme gabarit (méta, opérateur,
  barème). Dialog **Fichier → Nouveau depuis un modèle…**.
- **`photo_gallery.py`** — galerie photos par arbre (onglet Identification) :
  ajout/suppression de photos depuis le dossier compagnon `<mission>_photos/`
  undo-able ; intégrées optionnellement dans la fiche PDF (page dédiée).
- **Empaquetage** (`build/`) — distribution uniquement, hors app : PyInstaller
  (`penetrometre.spec` + `build/*.sh`/`installer.iss`, installeurs via
  `.github/workflows/build.yml` sur tag `v*`) et Nuitka (`build/build_nuitka.py`,
  binaire compilé — réplique le spec). `build/build_icons.py` génère les icônes.

## Accessibilité & réglages

- **`app_settings.SettingsStore`** (pur) — réglages UI persistés en JSON :
  `ui_scale` (borné [0.8, 1.6]), `high_contrast`, positions des poignées
  (`sash`). Tolérant aux valeurs absentes/corrompues.
- **`ui_fonts`** (pur) — échelle du texte : facteur global de processus
  (`set_ui_scale`/`get_ui_scale`) + helper `font(family, size, *opts)`.
  `tk scaling` étant inopérant sur plusieurs builds Tk/Linux, on agit sur
  le **nombre de taille** des polices. Identité à 1.0 → aucune régression.
- **`aide_repliable.AideRepliable`** — bloc d'aide repliable (en-tête
  « ⓘ Aide ▸/▾ »), **replié par défaut** ; fonctionne en `grid` comme en
  `pack`.
- **`palette.py`** — couleurs partagées **Tk ↔ PIL** (bois, écorce,
  cavité, `COULEUR_CLASSE`, `COLOR_WARN`, `COLOR_ACCENT`…). Invariant :
  `COLOR_BARK ≠ COLOR_ROT` (contraste dégradation/écorce).

## Ré-inspection inter-missions

- **`comparaison.py`** — fenêtre Tk `open_comparison(...)` redimensionnable :
  3 sections côte à côte (référence | courant | **section d'évolution**),
  tableau chiffré, verdict, export PNG + PDF. Référence chargée **par
  session** (rien de persisté). Décisions métier dans CLAUDE.md.
- **`comparaison_render.py`** (PIL pur, sans Tk) — `render_evolution_section`
  (couronne **orange** = bois sain perdu depuis la référence, contours
  lissés Catmull-Rom), `render_comparison_page` (A4 paysage),
  `save_comparison_{png,pdf}`, `metric_rows`/`verdict_evolution` partagés
  fenêtre ↔ page.
