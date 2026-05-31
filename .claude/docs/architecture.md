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

**Primitives de rendu partagées Tk ↔ PIL** (points `(x, y)` en coord. écran) :
- `polar_to_xy`, `polar_idx_to_xy` — polaire → écran (grade 0 = Nord, horaire).
- `cavity_polygon(alteration_par_grade, cx, cy, scale)` — polygone lissé cavité.
- `contrefort_zone_outline(zone, contreforts, R, ep_cm, cx, cy, scale)` —
  dict `{wood_outer, base, bark_outer?, bark_inner?}`.
- `degradation_externe_outline(deg, contreforts, R, ep_cm, cx, cy, scale)`.
- `adaptive_ruler_step_cm(scale_px_per_cm, min_gap_px)` — pas de graduation.
- `tick_endpoints`, `cardinal_label_positions`, `ruler_graduation_positions`.

## `model.py` — dataclasses + mutateurs de cohérence

- `Sondage` — `.prbs_cm` (alias), `.ratio_tR_brut(R)` (CSV uniquement).
- `DegradationExterne` — `.largeur_grades()`, `.couvre_grade(grade)`.
- `Contrefort` — `.grade_debut()`, `.grade_fin()`, `.largeur_cm(R)`.
- `Arbre` — mutateurs : `set_rayon(new_R)` (PRBS invariante, bois altéré ajusté),
  `renumeroter_sondages/degradations/contreforts()`. Prop : `display_name`.
- `Chantier` — nom, adresse, opérateur, date, arbres.

## `diagnostic.py` — calculs purs sur Arbre

Toutes les fonctions sont **pures** (pas de mutation, pas de cache sur l'arbre).

- `compute_alteration_par_grade(arbre)` — extrapolation pondérée linéaire.
- `degradation_externe_par_grade(arbre)` — profondeur max par direction.
- `prbs_par_grade(arbre)`, `ratio_tR_par_grade(arbre)` — composent les deux.
- `repartition_classes(arbre)` → `DiagnosticSnapshot` (self-contained :
  répartition, ratios, direction critique, t/R moyen, classe globale,
  `diagnostic_fiable`, `extrapolation_text`).
  - `snap.diagnostic_global` → `Optional[Tuple[float, str]]` — point
    d'entrée unique ; renvoie `None` (t/R moyen + classe masqués) tant
    que `diagnostic_fiable` est faux, c.-à-d. **< 3 directions sondées**
    (seuil métier, découplé du minimum d'extrapolation de la cavité = 2).
  - `snap.par_classe(cls)` — accès indexé par label.
- `extrapolation_summary(arbre)` / `extrapolation_summary_text(arbre)`.
- `diagnostic_summary_lines(arbre)` — résumé textuel (onglet Diag + fiche PDF).

Convention : classe globale = t/R **moyen** (confirmé Silvavenir mai 2026).

## `persistence.py` — I/O JSON des missions

- `FORMAT_VERSION = 2` — versionne le format.
- `chantier_to_dict` / `chantier_from_dict` — sérialisation symétrique.
- `save_chantier` / `load_chantier` — wrappers fichier UTF-8.
  **Écriture atomique** : write dans `.tmp` puis `os.replace` — le fichier
  original survit en cas de crash (disque plein, coupure de courant).
- Migration ascendante : anciens libellés de port (v3.1 → v3.2).
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
`DiagnosticPane` est scrollable (Canvas interne) et expose les 5 exports
individuels (PNG / fiche PDF / XLSX / HTML / CSV mission) en haut du
pane — le menu Fichier ne conserve que les 2 exports globaux (PDF
mission, CSV mission). La checkbox « Afficher sondages » a été déplacée
hors de ce pane et vit désormais sous le canvas (`App._build_right`).

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

## `fiche_pdf.py` — layout fiche PDF A4

- `render_fiche_arbre_to_pdf_page(arbre, chantier)` — page 1240×1754 px (150 DPI).
- Assemble : en-tête + logo, identité arbre, dessin section (via `pil_render`),
  légende, tableau PRBS, diagnostic (t/R moyen+min, barre répartition, classe).
- Dimensionnement adaptatif : au-delà de 8/12 sondages, police et hauteur
  de ligne se resserrent pour rester sur 1 page.

## `section_canvas.py` — rendu Tk de la section

`SectionCanvas(tk.Canvas)` : `redraw()` orchestre les `_draw_*` (ordre =
superposition). Pendant Tk de `pil_render` — géométrie partagée, visuels
spécifiques (polices, outline+width, smooth, flèches).

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

- `prbs_table_rows_par_sondage(arbre, classer_prbs)` — données pures.
- `export_prbs_xlsx(…)` — Excel stylé (openpyxl). En-têtes et méta sur
  fond vert Silvavenir, alternance de lignes, largeurs auto-fit,
  compartimentation ✓/✗, t/R coloré par classe.
- `export_prbs_html(…)` — HTML autonome imprimable, même thème vert.
- Injection de `couleur_classe` + `classer_prbs` pour éviter cycles.

## `dialogs.py` — boîtes de dialogue Tk

`edit_sondage`, `edit_degradation`, `edit_contrefort` : reçoivent
`(parent, arbre, obj)`, mutent en place, renvoient `True/False`. Chacun
bind `<Return>`→Valider, `<Escape>`→Annuler, et pose le focus initial
sur son 1er champ utile (la combobox Direction/Orientation).

`ask_string(parent, title, prompt, initial, info=…)` : dialogue de
saisie texte thémé (look ttk Silvavenir) qui remplace
`simpledialog.askstring`. Renvoie `None` si annulé, la chaîne (sans
`strip`) si validé — `""` validé ≠ `None`. Utilisé par
`App.action_rename_arbre`.

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
décrire les 5 boutons d'export du pane Diagnostic.

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
