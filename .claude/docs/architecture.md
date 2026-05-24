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
  - `snap.diagnostic_global` → `Optional[Tuple[float, str]]` — point d'entrée unique.
  - `snap.par_classe(cls)` — accès indexé par label.
- `extrapolation_summary(arbre)` / `extrapolation_summary_text(arbre)`.
- `diagnostic_summary_lines(arbre)` — résumé textuel (onglet Diag + fiche PDF).

Convention : classe globale = t/R **moyen** (confirmé Silvavenir mai 2026).

## `persistence.py` — I/O JSON des missions

- `FORMAT_VERSION = 2` — versionne le format.
- `chantier_to_dict` / `chantier_from_dict` — sérialisation symétrique.
- `save_chantier` / `load_chantier` — wrappers fichier UTF-8.
- Migration ascendante : anciens libellés de port (v3.1 → v3.2).
- Migration descendante : filtre par `__dataclass_fields__` + WARNING logged.

## `pane_*.py` — onglets Tk autonomes

Chaque pane : hérite `ttk.Frame`, possède ses widgets, expose `refresh()`,
déclare un `Protocol` host (`_*Host`). Tables Treeview incluent leur propre
cycle add/edit/del via `dialogs.py`. `IdentificationPane` gère la synchro
Ø ↔ R. `DiagnosticPane` est scrollable (Canvas interne).

## `app_exports.py` — actions d'export Tk

Adaptateur : vérifie prérequis, gère `filedialog`, entoure d'un try/except
avec logging. Thin wrappers depuis `App.action_export_*`.

## `pil_render.py` — rendu PNG de la section

- `render_arbre_to_pil_image(arbre, …)` — orchestrateur ~70 l. enchaînant
  les `_pil_draw_*`.
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

## `export.py` — exports tableau PRBS (XLSX/HTML)

- `prbs_table_rows_par_sondage(arbre, classer_prbs)` — données pures.
- `export_prbs_xlsx(…)` — Excel stylé (openpyxl). Colonne Compartimentation
  (✓/✗), t/R coloré par classe.
- `export_prbs_html(…)` — HTML autonome imprimable.
- Injection de `couleur_classe` + `classer_prbs` pour éviter cycles.

## `dialogs.py` — boîtes de dialogue Tk

`edit_sondage`, `edit_degradation`, `edit_contrefort` : reçoivent
`(parent, arbre, obj)`, mutent en place, renvoient `True/False`.
