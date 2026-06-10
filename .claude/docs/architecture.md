# Architecture détaillée des modules

## `bareme.py` — barème métier Silvavenir (stdlib uniquement)

- `classer_prbs(ratio_tR, port_arbre) -> str` — renvoie `Vert | Orange | Rouge`.
- `normaliser_port(value) -> str` — vérifie l'appartenance à `PORTS_ARBRE`.
- Constantes : `PORTS_ARBRE`, `PORTS_GROUPE_LIBRE`, `PORTS_GROUPE_STRICT`,
  `CLASSE_VERT`, `CLASSE_ORANGE`, `CLASSE_ROUGE`.
- Le port `délaissé` est dans `PORTS_GROUPE_LIBRE` (mêmes seuils que `libre`).

## `geometry.py` — fonctions pures (stdlib uniquement)

**Géométrie pure**
- `catmull_rom_closed` — spline fermée Catmull-Rom.
- `bell_max_at_grade(grade, contreforts)` — hauteur max de cloche cosinus².
- `contrefort_zones(contreforts)` — fusion des arcs qui se chevauchent.
- `ellipse_radius(a, b, orientation_grade, grade)` — rayon polaire d'une
  ellipse (demi-grand-axe `a`, demi-petit-axe `b`) dans une direction.
  Robuste aux axes nuls (jamais de division par zéro).

**Rayon scalaire ou par direction (`RadiusSpec`)** : `RadiusSpec = Union[float,
Callable[[float], float]]`. Les primitives de contour ci-dessous acceptent un
rayon **scalaire** (section circulaire — calcul strictement identique à l'ancien)
**ou une fonction `grade→rayon`** (section ovale, p. ex. `Brin.rayon_a_grade`).
Helper interne `_radius_at(R, grade)`.

**Primitives de rendu partagées Tk ↔ PIL** (points `(x, y)` en coord. écran) :
- `polar_to_xy`, `polar_idx_to_xy` — polaire → écran (grade 0 = Nord, horaire).
- `cavity_polygon(alteration_par_grade, cx, cy, scale)` — polygone lissé cavité.
- `contour_polygon(r_of, cx, cy, scale, n_samples=160)` — contour fermé
  échantillonné finement (cercle ou ellipse) ; sert au **remplissage** ovale
  (bois/écorce/cernes). Le cas circulaire garde la primitive native des
  renderers (`d.ellipse` / `create_oval`) → goldens byte-identiques.
- `contrefort_zone_outline(zone, contreforts, R, ep_cm, cx, cy, scale, R_inner=None)`
  — dict `{wood_outer, base, bark_outer?, bark_inner?}`. `R` (et `R_inner`) =
  `RadiusSpec`.
- `degradation_externe_outline(deg, contreforts, R, ep_cm, cx, cy, scale)` —
  `R` = `RadiusSpec`.
- `adaptive_ruler_step_cm(scale_px_per_cm, min_gap_px)` — pas de graduation.
- `tick_endpoints`, `cardinal_label_positions` (`R_ext` = `RadiusSpec`),
  `ruler_graduation_positions`.
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

- `Sondage` — `.prbs_cm` (alias), `.ratio_tR_brut(R)` (CSV uniquement).
- `DegradationExterne` — `.largeur_grades()`, `.couvre_grade(grade)`.
- `Contrefort` — `.grade_debut()`, `.grade_fin()`, `.largeur_cm(R)`.
- `Brin` (= ramet) — porte la **géométrie et les mesures propres à la tige** :
  `rayon_tronc_cm` (= demi-grand-axe si ovale), `rayon_petit_axe_cm`
  (0 = circulaire, sentinelle), `orientation_grade`, `diametre_sous_ecorce_cm`,
  `epaisseur_ecorce_cm`, `sondages`, `degradations_externes`, `contreforts`,
  position `pos_x_cm/pos_y_cm/rotation_grades` (réservée aux cépées, Étapes 2-4).
  Propriété `est_ovale` ; `rayon_a_grade(grade)` (rayon LOCAL — constant si
  circulaire, ellipse sinon) ; `extent_cm()` = rayon d'**encombrement** (rayon
  max + écorce + plus longue saillie de contrefort), pour le cadrage cépée.
  `label` (« a »/« b »/… ; "" si brin unique). Mutateurs : `set_rayon(new_R)` et
  `set_forme_ovale(petit_axe, orientation)` (tous deux → `_resync_sondages_local()`
  qui réaligne le bois altéré sur le rayon local **en préservant la PRBS**) ;
  `renumeroter_sondages/degradations/contreforts()`.
- `Arbre` (= genet) — identité partagée (`numero_arbre`, `essence`,
  `hauteur_sondage_cm`, `hauteur_arbre_m`, `port_arbre`, `meche_cm`,
  `commentaire`) + `brins: List[Brin]` (≥ 1). **Propriétés-relais et méthodes-relais**
  (`rayon_tronc_cm`, `sondages`, `set_rayon`, `set_forme_ovale`, `rayon_a_grade`,
  …) délèguent au **brin courant** (`brins[0]`) pour que le code écrit avant les
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
- `degradation_externe_par_grade(section)` — profondeur max par direction.
- `rayon_par_grade(section)` — 16 rayons extérieurs (constant = `rayon_tronc_cm`
  si circulaire, ellipse sinon via `section.rayon_a_grade`).
- `prbs_par_grade(section)`, `ratio_tR_par_grade(section)` — composent les
  trois ; dénominateur t/R = **rayon LOCAL** de chaque direction (apport ovale).
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

Convention : classe globale d'un **brin** = t/R **moyen** (confirmé Silvavenir
mai 2026) ; classe globale d'un **genet** = **pire classe** parmi ses brins
fiables (jamais une moyenne inter-brins — repères polaires distincts).

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
La **forme ovale** n'est PAS en ligne (pour ne pas alourdir le cas
circulaire courant) : un bouton « Forme du tronc (ovale)… » dans le groupe
Tronc ouvre l'éditeur avancé `dialogs.ask_forme_tronc` ; `_open_forme_editor`
applique le résultat via `push_undo` + `set_forme_ovale`. Sous ce bouton,
les actions **« ＋ Brin » / « − Brin »** (`App.add_brin` / `remove_last_brin`,
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
`DiagnosticPane` est scrollable (Canvas interne) et expose les 5 exports
individuels (PNG / fiche PDF / XLSX / HTML / CSV mission) en haut du
pane — le menu Fichier ne conserve que les 2 exports globaux (PDF
mission, CSV mission). La checkbox « Afficher sondages » a été déplacée
hors de ce pane et vit désormais sous le canvas (`App._build_right`). Pour
une **cépée**, le résumé passe par `genet_summary_lines` (un bloc par brin +
classe globale) et le tableau PRBS itère tous les brins (N° préfixé « a1 »).

## `app_exports.py` — actions d'export Tk

Adaptateur : vérifie prérequis, gère `filedialog`, entoure d'un try/except
avec logging. Thin wrappers depuis `App.action_export_*`.

- `export_pdf_mission` : PDF multi-pages (Pillow `save_all`) regroupant
  toutes les fiches arbres d'une mission.

## `app_menu.py` — barre de menu Tk

`build_menu(app)` attache la barre de menu et bind les raccourcis
globaux. Trois cascades :

- **Fichier** : Nouvelle (Ctrl+N), Ouvrir (Ctrl+O), **Ouvrir récent**
  (sous-menu populé par `refresh_recent_menu(app)` depuis
  `app.get_recent_files()`), Enregistrer (Ctrl+S), Enregistrer sous,
  exports PDF/CSV mission, Quitter.
- **Arbres** : Ajouter (Ctrl+T), Dupliquer, Renommer, Supprimer.
- **Aide** : Raccourcis clavier, Ouvrir le fichier de log, À propos.

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
- **Section ovale** : chaque couche de contour (bois/cernes/écorce) **branche
  sur `brin.est_ovale`** — circulaire → primitive native `d.ellipse` (rendu
  inchangé, goldens stables) ; ovale → polygone via `contour_polygon`. Les
  contreforts/dégradations/ticks/cardinales reçoivent `brin.rayon_a_grade`
  (constant si circulaire → byte-identique). La règle horizontale utilise le
  rayon de l'axe E-O (`rayon_a_grade(100)`).
- **Cépée** : `_pil_draw_brin(d, f, brin, port, meche, cx, cy, R, ep, scale, …)`
  dessine UNE section centrée (toutes les couches per-brin) ; l'orchestrateur
  dérive tôt vers `_pil_draw_cepee` dès que `len(brins) > 1` ou un brin décentré
  (le mono-brin centré garde le chemin verbatim → goldens intacts). `_pil_draw_cepee`
  compose les brins via `geometry.brins_layout`, ajoute un label par brin
  (`_pil_draw_brin_label`) et **une seule boussole globale** sur le rectangle de
  la bbox (les ticks restent par brin). Fixture golden `cepee`.

## `fiche_pdf.py` — layout fiche PDF A4

- `render_fiche_arbre_to_pdf_page(arbre, chantier)` — page 1240×1754 px (150 DPI).
- Assemble : en-tête + logo, identité arbre, dessin section (via `pil_render`),
  légende, tableau PRBS, diagnostic (t/R moyen+min, barre répartition, classe).
- Dimensionnement adaptatif : au-delà de 8/12 sondages, police et hauteur
  de ligne se resserrent pour rester sur 1 page.
- **Cépée** : tableau PRBS itère tous les brins (N° préfixé « a1 ») ; le bloc
  diagnostic est routé — mono-caule = `_draw_mono_diagnostic` (verbatim, barre
  + encadré classe), cépée = `_draw_cepee_diagnostic` (encadré « Classe globale
  (pire brin) » + une ligne de synthèse par brin).

## `section_canvas.py` — rendu Tk de la section

`SectionCanvas(tk.Canvas)` : `redraw()` orchestre les `_draw_*` (ordre =
superposition). Pendant Tk de `pil_render` — géométrie partagée, visuels
spécifiques (polices, outline+width, smooth, flèches). Même gestion de la
**section ovale** que PIL (branche `est_ovale` : `create_oval` natif si
circulaire, `contour_polygon` via `create_polygon` si ellipse ;
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
- `export_prbs_xlsx(…)` — Excel stylé (openpyxl). En-têtes et méta sur
  fond vert Silvavenir, alternance de lignes, largeurs auto-fit,
  compartimentation ✓/✗/— (glyphe coloré), t/R coloré par classe.
  Sous le tableau : légende des 3 glyphes (collée, sans ligne vide) puis
  légende des classes « Classe verte/orange/rouge » (texte coloré).
  Calqué cellule pour cellule sur la fiche de référence du cabinet
  (`Communication/export excel attendu.xlsx`) — verrouillé par
  `test_legendes_calquees_sur_la_fiche_du_cabinet`.
- `export_prbs_html(…)` — HTML autonome imprimable, même thème vert.
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
saisie texte thémé (look ttk Silvavenir) qui remplace
`simpledialog.askstring`. Renvoie `None` si annulé, la chaîne (sans
`strip`) si validé — `""` validé ≠ `None`. Utilisé par
`App.action_rename_arbre`.

`ask_forme_tronc(parent, *, grand_axe_cm, petit_axe_cm, orientation_grade)` :
**éditeur avancé de la forme de section** (tronc ovale). Affiche le grand axe
(= rayon du tronc) en référence et édite demi-petit-axe + orientation. Renvoie
`(petit_axe_cm, orientation_grade)` si validé, `None` si annulé ; petit axe
vide/0 ⟹ section circulaire. Volontairement séparé du formulaire pour ne pas
alourdir le cas circulaire courant ; appelé par `IdentificationPane`.

`ask_cepee_layout(parent, arbre) -> Optional[List[Tuple[float, float]]]` :
**éditeur de disposition d'une cépée** (Étape 4b). Canvas qui dessine chaque
brin (contour fidèle via `geometry.contour_polygon` — cercle ou ellipse
orientée), cadrage **figé à l'ouverture** par `geometry.brins_layout` (le dessin
ne saute pas pendant le glissement). Glisser-déposer un brin fixe sa position
`(pos_x_cm, pos_y_cm)` ; le brin « a » est l'**ancre** (fixe, en (0,0)).
Travaille sur une copie → renvoie les positions par brin si validé, `None` si
annulé (Annuler = no-op). Appliqué par `App.edit_cepee_layout` (push_undo +
redraw) ; déclenché par le bouton « Disposition… » de `IdentificationPane`.

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

- `UndoStack` (dataclass) : pile de snapshots `Dict[str, Any]` (dicts
  JSON via `chantier_to_dict`), curseur, profondeur max 50.
- `push(snapshot)` — sauvegarde avant mutation, tronque le futur.
- `undo(current)` → dict à restaurer (ou `None`).
- `redo()` → dict à restaurer (ou `None`).
- `clear()` — vidée sur new/open.
- `can_undo` / `can_redo` — propriétés booléennes.

Intégré dans `App` via `push_undo()` (appelé par les panes avant
chaque mutation discrète). Bindings : Ctrl+Z (undo), Ctrl+Y ou
Ctrl+Shift+Z (redo).

## `penetrometre.py` — application Tk + main

`App(tk.Tk)` — fenêtre principale, layout 3 colonnes, instanciation des
panes, callbacks communs. Porte :

- **Dirty flag** (`_dirty`) : tracké sur toute mutation, reset au
  save/open/new. Titre dynamique avec `•` si modifié.
- **WM_DELETE_WINDOW** : confirme la fermeture si dirty.
- **Undo/redo** : `push_undo()` + `_perform_undo/redo()` via
  `UndoStack` + `chantier_to_dict`/`chantier_from_dict`.
- **Meta mission** : push undo sur FocusOut (pas à chaque frappe).
- **Géométrie de fenêtre adaptative** : `minsize(1100, 680)` + clamp
  à 95 % de l'écran via `winfo_screenwidth/height` au démarrage.
- **Liste d'arbres** : colonne État cliquable (Nom, Essence, État).
  Indicateurs : `_arbre_etat(a) -> (glyphe, tag)` — `etat_vide` (rouge,
  rayon=0 OU 0 sondage), `etat_partiel` (orange, 1-2 sondages),
  `etat_ok` (vert, ≥3 sondages). Le seuil vert ≥3 est **aligné** sur la
  règle de fiabilité du diagnostic global (`DiagnosticSnapshot`). Refresh
  granulaire via `_refresh_current_arbre_etat()` appelé dans
  `_redraw_all`. Footer `lbl_etat_footer` = compteur d'arbres `etat_ok`.
- **Menu contextuel clic droit** : `_tree_arbres_ctx_menu` avec
  Renommer/Dupliquer/Supprimer. `tk_popup` SANS `grab_release()` +
  `<FocusOut>` pour fermeture au clic externe.
- **Fichiers récents** : `_load_recent_files()` / `_save_recent_files()`
  / `_push_recent_file(path)` / `_remove_recent_file(path)` + action
  `action_open_recent(path)`. Persistance dans
  `~/.penetrometre/recent.json` (8 max). Sous-menu rebuilt via
  `app_menu.refresh_recent_menu()`.
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
- **Aide** : `action_about`, `action_shortcuts` (popup raccourcis),
  `action_open_log` (ouvre `~/.penetrometre/penetrometre.log` avec
  l'éditeur par défaut, cross-platform via `os.startfile`/`open`/
  `xdg-open`).
