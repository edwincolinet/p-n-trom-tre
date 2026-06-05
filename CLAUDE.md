# Pénétromètre — Projet Silvavenir

Application desktop d'expertise arboricole (mesure de cavités dans les
troncs au pénétromètre). Utilisé en interne par le cabinet Silvavenir.

## Stack

- **Python 3.9+** (3.12 recommandé), **Tkinter** (UI stdlib), **Pillow** (PNG/PDF)
- Aucun framework, aucun build system — lancement par double-clic.
- Dépendance optionnelle : openpyxl (export XLSX).

## Structure

```text
penetrometre.py        ← App Tk + main (~670 l.)
section_canvas.py      ← SectionCanvas (rendu Tk section, ~410 l.)
pane_identification.py ← onglet Identification
pane_sondages.py       ← onglet Sondages
pane_degradations.py   ← onglet Dégradations externes
pane_contreforts.py    ← onglet Contreforts
pane_diagnostic.py     ← onglet Diagnostic (exports + résumé)
app_exports.py         ← actions d'export (adaptateur Tk)
app_menu.py            ← barre de menu Tk
app_style.py           ← thème ttk
dialogs.py             ← dialogues Tk (Sondage, Dégradation, Contrefort)
model.py               ← dataclasses + mutateurs + __post_init__ validation
diagnostic.py          ← fonctions pures de diagnostic + sondage_render_data
persistence.py         ← I/O JSON (save/load + migration)
geometry.py            ← briques géométriques pures (spline, polaire, cernes)
bareme.py              ← barème métier (classer_prbs, ports)
pil_render.py          ← rendu PNG de la section transversale
fiche_pdf.py           ← layout fiche expertise PDF (page A4)
palette.py             ← couleurs partagées Tk ↔ PIL
export.py              ← exports XLSX/HTML tableau PRBS + synthèse mission (XLSX/CSV)
undo.py                ← pile undo/redo (Ctrl+Z / Ctrl+Y, 50 snapshots)
tooltip.py             ← infobulle Tk légère (survol), n'importe quel widget
tests/                 ← 176 tests (intégration, golden PIL + Tk, undo, persistence)
```

**Graphe de dépendances** (chaque module importe uniquement vers le bas) :

```text
geometry.py + bareme.py   (stdlib)
   ↑
model.py + palette.py + tooltip.py
   ↑
diagnostic.py
   ↑
export.py + pil_render.py + persistence.py + dialogs.py
   ↑
fiche_pdf.py
   ↑
section_canvas.py + pane_*.py + app_exports.py + app_menu.py + app_style.py
   ↑
penetrometre.py  (Tk + main) ← undo.py
```

## Conventions métier

- **Grades** : 0 à 375 par pas de 25 (16 directions). 0 = Nord, sens horaire.
  Afficher `100 gr` (pas de symbole °).
- **PRBS** = Paroi Résiduelle de Bois Sain (mesure physique invariante).
  Quand le rayon change, la PRBS reste, `bois_altéré` s'ajuste.
- **t/R** = PRBS / Rayon (0–1). **Classe globale** = barème sur t/R **moyen** 16 dir.
- **Diagnostic non fiable si < 3 sondages** → exports masquent t/R moyen + classe.
- **Dégradations externes** consomment du bois sain : `PRBS_ajustée = sain − profondeur_deg`.
- **Pastille sondage = PRBS ajustée** (jamais brute).
- **Contreforts** = cloche cosinus², fusion si adjacents (`contrefort_zones`).
- **Écorce** = purement visuel (n'intervient pas dans diagnostic). R_ext = R + ep.
- **COLOR_BARK ≠ COLOR_ROT** : ne jamais unifier (contraste dégradation/écorce).
- **Unicité** : un seul sondage par direction, pas de dégradations qui se
  chevauchent (arcs mitoyens bout-à-bout autorisés), un seul contrefort par
  grade central. Validé dans `dialogs.py` au clic Valider.

## Conventions de code

- Pas de dépendance sans bonne raison. Compat Python 3.9+.
- Tout en français (UI + docstrings).
- Pas de `print` — logger applicatif (`~/.penetrometre/penetrometre.log`).
- Exports : `log.exception(...)` avant `messagebox.showerror`.
- Compat fichier bidirectionnelle : ajout champ = OK (default) ; renommage/suppression = migration explicite dans `persistence.chantier_from_dict`.
- Écriture atomique : `save_chantier` écrit dans un `.tmp` puis `os.replace` — le fichier original survit en cas de crash.
- **Autosave anti-crash** (`persistence.save_recovery`/`load_recovery`/`clear_recovery`, câblage dans `App`) : tick `after` toutes les 60 s (`_AUTOSAVE_INTERVAL_MS`) qui n'écrit `~/.penetrometre/recovery/autosave.json` **que si `_dirty`**. Le fichier enveloppe `chantier_to_dict` + métadonnées (`saved_at`, `original_file`). **Invariant clé** : l'autosave est effacé dès qu'on atteint un état propre (`action_save`, `action_new`, `_open_path`) **et à la fermeture normale** (`_on_close`, même en abandonnant des modifs) — donc sa seule présence au démarrage ⟺ crash précédent avec travail non enregistré. `_check_recovery_on_startup` (programmé via `after(200, …)` pour s'afficher sur une UI déjà mappée) propose la reprise ; `_restore_recovery` recharge l'UI, repointe `current_file` sur l'original s'il existe encore, et remet `_dirty=True`. Écriture atomique (`.tmp` + `os.replace`) comme `save_chantier`.
- **Champs numériques UI** : filtrage à la frappe via `dialogs.validate_numeric` (validateur Tk `validate="key"`) — seuls chiffres + un séparateur décimal `.`/`,` acceptés. Parsing via `dialogs.to_float` (accepte `2,5` et `2.5`). Branché sur les 3 dialogues (Sondage/Dégradation/Contrefort) + les 6 champs numériques de `pane_identification`. `_parse_float("")` renvoie `None` (pas `0.0`). `set_rayon` n'est appelé qu'au focus-out (jamais pendant la frappe) pour éviter la destruction irréversible des PRBS par valeurs intermédiaires.
- **N° d'arbre** : doit contenir au moins un chiffre (« 1 », « 42 », « 12 bis » OK ; « bis » seul refusé). Règle appliquée dans `pane_identification._revert_num_if_invalid` (revert au focus-out) et `App.action_rename_arbre` (boucle de retry pré-remplie).
- **Compartimentation** : valeurs `"active"`, `"absente"`, `"non renseignée"` (anciennement `"-"`, migré silencieusement au load via `persistence.chantier_from_dict`).
- **Indicateurs d'état de la liste d'arbres** : `App._arbre_etat(arbre)` renvoie `(glyphe, tag)`. Tags : `etat_vide` (0 sondage OU rayon=0, **rouge**), `etat_partiel` (1-2 sondages, **orange ambre**), `etat_ok` (≥3 sondages, **vert**). Le seuil **vert ≥ 3** est **aligné** sur la règle métier de fiabilité (« < 3 sondages → exports masqués ») : la pastille verte signale exactement les arbres au diagnostic global publiable. NB : l'extrapolation géométrique de la cavité (`compute_alteration_par_grade`) reste active dès 2 sondages — c'est son minimum mathématique, découplé du seuil de fiabilité. Refresh ligne par ligne via `_refresh_current_arbre_etat()` appelé dans `_redraw_all` (donc après toute mutation via debounce). Footer `lbl_etat_footer` = compteur d'arbres `etat_ok`.
- **Workaround bpo-36468 (ttk.Treeview)** : depuis Python 3.7, les `tag_configure(foreground=…)` sont ignorés à cause d'entrées par défaut dans `style.map`. `app_style._fixed_map` retire les entrées `("!disabled", "!selected", …)` pour que les tags prennent la main. Sans ça, les pastilles d'état resteraient blanches.
- **Ajout d'arbre en série** : le bouton « ＋ Ajouter » est un `Menubutton` (`Accent.TMenubutton`) à 2 entrées. **« Arbre vierge »** (`action_add_arbre`, `Ctrl+T`) = tous champs par défaut. **« Hériter du précédent »** (`action_add_arbre_inherit`) reprend les champs d'identité/protocole de l'arbre courant (essence, port, mèche, épaisseur d'écorce, hauteur de sondage) mais **PAS** la géométrie mesurée (rayon/diamètre/hauteur d'arbre laissés à défaut, à re-mesurer) ni les sondages/dégradations/contreforts — pensé pour les alignements d'arbres identiques. N° via `_next_arbre_numero` (max numérique + 1).
- **Navigation clavier entre arbres** : `Ctrl+PgDown`/`Ctrl+PgUp` → `action_next_arbre`/`action_prev_arbre` → `_select_arbre_relative(±1)` (bornée, sans boucle). Donne d'abord le focus clavier à la liste (`tree_arbres.focus_set()`) pour déclencher le `<FocusOut>` d'une case de grille en cours d'édition avant de basculer. Libre de conflit : `ttk.Notebook` ne lie que `Ctrl+Tab`.
- **Menu contextuel clic droit** sur la liste d'arbres : Renommer/Dupliquer/Supprimer. `tk_popup` SANS `grab_release()` (anti-pattern qui annule le grab) + `bind("<FocusOut>")` sur le menu pour fermeture au clic externe.
- **Canvas interactif** : `section_canvas.SectionCanvas` accepte un `host` optionnel (l'App) ; `tag_bind("sondage_item"/"degradation_item"/"contrefort_item", "<Button-1>")` ouvre le dialogue d'édition correspondant. Curseur `hand2` au survol. Dispatch via tags `<type>_idx_<i>` pour retrouver l'objet métier.
- **Dialogues modaux** : `dialogs._make_modal(dlg, parent)` séquence `update_idletasks → transient → wait_visibility → grab_set → focus_set`. Appeler `grab_set` avant que le WM ait mappé la fenêtre fait apparaître le dialogue **vide** sur Linux/X11 (race entre grab et rendu). Tous les dialogues passent par ce helper, qui est appelé APRÈS la création des widgets. Chaque dialogue d'édition (Sondage/Dégradation/Contrefort) bind `<Return>`→Valider, `<Escape>`→Annuler, et pose le focus initial sur son 1er champ utile.
- **Saisie texte thémée** : `dialogs.ask_string(parent, title, prompt, initial, info=…)` remplace `simpledialog.askstring` (look système incohérent). Renvoie `None` si annulé, la chaîne (sans `strip`) si validé — `""` validé ≠ `None`. Utilisé par `action_rename_arbre`.
- **Barre d'état** : `App._build_statusbar()` (bas de fenêtre, packée `side="bottom"` AVANT le body). `App.notify_export(path, label)` y affiche le succès d'un export (non-modal) et active les boutons « Ouvrir le fichier / le dossier » (`App._open_in_system`). `app_exports._notify_export` route vers `notify_export` si l'hôte le fournit, sinon `messagebox` (contexte test).
- **Infobulles** : `tooltip.Tooltip(widget, texte)` — bindings `add="+"` pour ne pas écraser ceux du widget. Sert à rappeler les accélérateurs (bouton « ＋ Ajouter » → Ctrl+T) et décrire le bandeau d'export (2 boutons + menu « Tableau »).
- **Canevas — ajout par clic** : un clic sur une direction libre du dessin ajoute un sondage à ce grade (`App.open_add_sondage`) ; un clic sur une direction déjà sondée l'édite. `SectionCanvas._on_click_background` convertit le pixel en grade (inverse de `geometry.polar_to_xy`), mémorise la géométrie du dernier rendu dans `self._geom`, et ignore les clics sur un élément interactif (garde par tags).
- **Raccourci export** : `Ctrl+E` → `App.action_export_pdf_arbre`. Bind dans `App.__init__` (comme Ctrl+Z/Y) via `_on_export_shortcut`, qui **ne déclenche pas** si un `Entry`/`Combobox` a le focus (Ctrl+E = « fin de ligne » dans les widgets Tk).
- **Fichiers récents** : `~/.penetrometre/recent.json` (8 entrées max). `App._push_recent_file(path)` appelé après chaque open/save. Sous-menu `Fichier → Ouvrir récent` reconstruit par `app_menu.refresh_recent_menu(app)`.
- **Adaptation petits écrans** : `App.__init__` clampe la geometry à 95 % de l'écran et fixe `minsize(1100, 680)` pour rester utilisable sur laptops 1366×768.
- **Saisie des sondages = grille 16 directions** (`pane_sondages.py`) : refonte ergonomique remplaçant la modale-par-mesure. Les 16 directions (rose des vents `_WIND_LABELS` : cardinales `N/NE/E…`, intermédiaires en combiné `N-NE/NE-E…`) sont pré-affichées ; l'opérateur tape la PRBS et descend (`Entrée`/`↓`/`↑` → ligne suivante via `_focus_entry`). **Sémantique** : case vide = direction non sondée (aucun `Sondage`) ; valeur (y compris 0) = sondage existant ; **effacer la valeur supprime le `Sondage`**. L'altéré (`R − sain`, clampé à `R`) est en lecture seule, recalculé en direct. La compartimentation (combobox) n'est active que si un sondage existe sur la ligne. **Unicité garantie par construction** (une ligne par grade — plus de validation d'unicité). Double-clic sur les libellés **Direction/Grade** ouvre `edit_sondage` (détail : commentaire, redirection de grade) ; l'`Entry` garde son double-clic natif. **Undo des éditions live** : snapshot capturé au focus-in (`host.capture_undo_snapshot`), empilé au focus-out seulement si la valeur a changé (`host.push_undo_snapshot`) — évite les undo parasites ; la compartimentation passe par `host.push_undo` (mutation discrète). Mutations notifiées via `host.on_sondages_changed` (dirty + redraw debouncé ; ne re-`refresh()` PAS la grille pour ne pas lutter contre la frappe). Sondages maintenus triés par grade (`sort` + `renumeroter_sondages`).
- **Synthèse de mission** (tableau de hiérarchisation du risque) : `diagnostic.mission_synthesis_rows(chantier)` → `List[MissionSynthesisRow]` (fonction pure), **une ligne par arbre** (n° · essence · port · nb sondages · rayon · t/R moyen · classe globale · direction critique). Respecte la règle de fiabilité : `tR_moyen_pct`/`classe_globale` = `None` si `< 3` sondages (via `DiagnosticSnapshot.diagnostic_global`), `tR_min_pct`/`crit_grade` = `None` si aucune altération. Exports : `export.export_synthesis_csv` (séparateur `;`, UTF-8 BOM) et `export.export_synthesis_xlsx` (thème vert, cellule classe colorée, **autofiltre** pour trier par risque, en-tête gelé, ligne de bilan). Wrappers Tk dans `app_exports.export_synthesis_{csv,xlsx}_mission` ; actions `App.action_export_synthesis_{csv,xlsx}` ; entrées dans le menu **Fichier** (mission-level, à côté des fiches PDF / sondages CSV). « Non fiable » (1-2 sondages) ≠ « — » (rayon nul / 0 sondage) dans la colonne classe.
- **Checkbox « Afficher sondages »** vit **sous le canvas** (`App._build_right`), pas dans l'onglet Diagnostic — elle contrôle un état visuel toujours présent. Variable `App.var_show_sondages`.

## Commandes utiles

```bash
python penetrometre.py                      # Lancer l'app
python -m unittest discover tests           # 174 tests
ruff check .                                # Lint
python -m mypy bareme.py geometry.py palette.py model.py diagnostic.py \
  persistence.py export.py pil_render.py fiche_pdf.py app_exports.py app_menu.py \
  pane_identification.py pane_sondages.py pane_degradations.py \
  pane_contreforts.py pane_diagnostic.py dialogs.py section_canvas.py \
  undo.py tooltip.py penetrometre.py
```

Golden-tests :
- PIL : `python -m tests.test_render --update`
- Tk : `xvfb-run -a python -m tests.test_section_canvas --update`

## Quand tu modifies l'app

1. **Repérer le bon module** :
   - Barème métier → `bareme.py`
   - Géométrie pure → `geometry.py`
   - Modèle / mutateurs → `model.py` ; migration JSON → `persistence.py`
   - Diagnostic (calculs purs) → `diagnostic.py`
   - Rendu PNG section → `pil_render.py` ; layout PDF A4 → `fiche_pdf.py`
   - Couleurs → `palette.py` ; exports tableau → `export.py`
   - Dialogues Tk → `dialogs.py` ; onglet UI → `pane_*.py`
   - Actions export → `app_exports.py` ; rendu Tk section → `section_canvas.py`
   - Orchestration App → `penetrometre.py`
2. **Géométrie partagée** : modifier `geometry.py` une fois, les deux renderers héritent. Pour le visuel spécifique (traits, polices, écorce) → modifier Tk **et** PIL.
3. **Modèle** : ajout de champ = OK. Renommage/suppression → migration dans `persistence.py`.
4. **Tests** : lancer la suite avant tout commit touchant modèle/géométrie/exports.
5. **Valider** : lancer l'app + sauvegarder/recharger un `.json`.

Pour les détails d'architecture, de rendu et les pièges, voir :
- `.claude/docs/architecture.md` — description détaillée de chaque module
- `.claude/docs/rendu-et-pieges.md` — pendants Tk↔PIL, pièges, ordre des couches
