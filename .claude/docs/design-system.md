# Design system (chrome Tk)

Trois modules de tokens, en bas du graphe de dépendances (aucune dépendance
Tk), consommés par `app_style.py` et par tous les `pane_*.py`/`dialogs*.py` :

- `palette.py` — couleurs
- `ui_fonts.py` — typographie + espacements
- `icons.py` — glyphes d'icônes

Périmètre : le **chrome Tk interactif** (boutons, onglets, panneaux,
dialogues). Le **dessin de section** (`section_canvas.py`, `pil_render.py`,
`comparaison_render.py`, `fiche_pdf.py`) est golden-testé et volontairement
hors périmètre — cf. « Couleur d'accent des rendus » ci-dessous.

## Pourquoi

Avant ce design system, trois défauts s'étaient accumulés par correctifs
ponctuels successifs (jamais une décision centralisée) :

1. Le Treeview évitait déjà les emoji couleur (rendu imprévisible selon la
   police système), mais la barre d'export et le header en étaient pleins —
   exactement le risque que ce principe visait à éviter ailleurs.
2. `COLOR_ACCENT` (chrome UI) valait EXACTEMENT `COULEUR_CLASSE[Vert]`
   (arbre en bon état sanitaire) : le canal couleur le plus important de
   l'app (le diagnostic de risque) était dilué par son usage comme couleur
   de marque générique (boutons, onglets, titres).
3. Les tailles/graisses de police étaient fixées au cas par cas, sans
   échelle nommée — chaque ajout recopiait ou réinventait une variante
   proche (`("Helvetica", 11, "bold")` ici, `("Georgia", 12, "bold")` là,
   pour un rôle visuel quasi identique).

## Charte SILVAVENIR (2026-10-18)

Source : dossier `design system SILVAVENIR/` (bundle HTML hors ligne, v1.0
sept. 2026 — logo, couleurs, échelle diagnostic, typographie, composants).
Le chrome, la fiche PDF, les exports XLSX/HTML et la comparaison en
reprennent les tokens ; le produit s'appelle désormais **« Pénétromètre
Silvavenir »** (l'éditeur/auteur reste Edwin Colinet).

## Couleurs (`palette.py`)

- **Marque** : `COLOR_BRAND_ORANGE` `#F58101` (titres ≥ 20 px, filets, action
  principale), `COLOR_BRAND_ORANGE_DARK` `#E36C0A` (survol, orange lisible
  en petit corps), `COLOR_BRAND_FOREST` `#385623` (sous-titres, actions
  secondaires), `COLOR_BRAND_LEAF` `#40A838` (logo — marque, **jamais** un
  état), `COLOR_BRAND_DEEP` `#24331B`, `COLOR_BRAND_SAND` `#FCE3C0`.
- **Neutres** : fond `COLOR_BG` `#FAF9F5` (Papier), `COLOR_SIDE_PANEL`
  `#F4F2EC` (Sous-couche), `COLOR_RULE` `#E3E1DA` (filets), corps
  `COLOR_INK` `#404040` (jamais de noir pur), `COLOR_INK_STRONG` `#262625`,
  secondaire `COLOR_MUTED` `#595959`.
- `COLOR_ACCENT` = accent du **chrome interactif** (onglets actifs,
  sélections, cases cochées, titres de section, texte des boutons
  secondaires) = vert forêt. **Plus identique** à `COULEUR_CLASSE[Vert]`
  (`#2D7A3E`) : la charte interdit d'employer le vert de marque comme
  couleur d'état, ce qui lève la collision bouton actif ↔ arbre en bon état.
- Action principale (`Accent.TButton`/`Accent.TMenubutton`) = **orange de
  marque**, survol orange foncé, **une seule par écran** (charte).
  Secondaire (`Ghost.*`) = contour + texte vert forêt. Focus d'un champ =
  liseré orange. En-tête de la fenêtre = bandeau blanc + filet orange 3 px
  (`Brand.*` dans `app_style`).
- `COLOR_RENDER_ACCENT` = accent des **rendus** (dessin de section, fiche
  PDF, comparaison) = vert forêt ; figé indépendamment de `COLOR_ACCENT`.
  Les bandeaux de la fiche PDF et de la comparaison portent en plus un
  filet orange de marque. **Ne jamais remplacer par `COLOR_ACCENT`** dans
  `section_canvas.py`/`pil_render.py`/`comparaison_render.py`/`fiche_pdf.py`.
- `COULEUR_CLASSE` (Vert/Orange/Rouge) reste réservée au **diagnostic de
  risque** et **n'a PAS été alignée** sur l'échelle de la charte (vert
  `#4C8B2B` / jaune `#F2B705` / rouge `#C62828`) : décision d'Edwin
  (2026-10-18), pour ne pas migrer le libellé « Orange » persisté. Écart
  assumé ; à rouvrir si la charte devait être appliquée strictement.
- Exports XLSX/HTML : en-têtes forêt, titre orange, texte `#404040`, lignes
  alternées `#F4F2EC`, polices Century Gothic (titres) / Segoe UI (corps).
  Les glyphes de compartimentation (état) gardent leurs couleurs.

## Typographie (`ui_fonts.py`)

**Familles de la charte** : titres Jost / Century Gothic, corps Source Sans 3 /
Segoe UI. `ui_fonts.resolve_brand_fonts(root)` (appelé dans
`App._apply_ui_scale` et à l'ouverture du dialogue d'activation) choisit la
première famille **installée** ; les noms historiques « Helvetica » (corps)
et « Georgia » (titres) passés à `ui_fonts.font()` sont des **rôles**
traduits vers ces familles. Sans Jost/Century Gothic, les titres retombent
sur la famille du corps (jamais un serif). Les polices ne sont **pas
installables par l'app** côté Tk (impossible de charger un .ttf sans
l'installer) ; en revanche **Jost 700, Source Sans 3 (400, 600, italique)**
sont **embarquées** dans `assets/fonts/` (instances statiques tirées des
variables Google Fonts, licence OFL — `OFL-*.txt`) et utilisées par la fiche
PDF (`fiche_pdf._STYLE`) et tous les rendus PIL (`pil_render._pil_font_paths`,
rôles `serif_bold`→Jost, `sans`/`sans_bold`→Source Sans 3 / demi-gras). Ni ⚠
ni les glyphes d'emoji ne sont dans ces polices : les rendus PDF/PIL
utilisent ▲. DejaVu reste embarquée en dernier recours.
**Pastilles d'urgence NEUTRES** (fiche PDF, XLSX synthèse) : la charte
interdit de colorer le délai (« seule la couleur de synthèse porte la
gravité »). **n°** toujours suivi d'une espace insécable (« n° 272 »). Le dessin
de section (`section_canvas`) garde ses polices en dur (golden-testé).

Fonctions (pas des constantes — l'échelle utilisateur `_scale` n'est fixée
qu'au démarrage, après l'import des modules) : `font_title()`,
`font_subtitle()`, `font_heading()`, `font_subheading()`, `font_body()`,
`font_body_bold()`, `font_small()`, `font_small_bold()`,
`font_small_italic()`. Chaque appelant doit préférer le token le plus
proche de son besoin ; un besoin réellement isolé (taille sans autre
occurrence dans la base) reste un `font(...)` direct plutôt qu'un token à
usage unique — cf. les 3 tailles one-off de l'écran de bienvenue
(`app_layout.py`) ou les légendes de vignettes photo à 7 pt
(`photo_gallery.py`).

Espacements nommés (`SPACE_XS/S/M/L/XL` = 4/6/10/14/18) : disponibles pour
le code déjà touché par une évolution, **pas un retrofit systématique**
des `padx=`/`pady=` existants (surface trop large pour un gain
proportionné dans une UI hand-tuned au pixel).

## Cases à cocher (`app_style.Panel.TCheckbutton`)

Style **unique** pour toutes les cases à cocher de l'app (dialogues,
grille Sondages, panneau du dessin — un seul `ttk.Checkbutton` réel,
`style="TCheckbutton"`, subsistait hors de ce style avant le 2026-09-05 ;
son fond gris tranchait sur le panneau blanc qui l'entoure, cf. piège
ci-dessous). Repéré à l'usage comme peu lisible : indicateur natif du
thème `clam` minuscule (~10px) et état coché à peine distinct de l'état
vide (une coche verte discrète sur fond blanc inchangé). Corrigé par :

- `indicatorsize=16` (contre ~10px natif) — cible plus grande, plus facile
  à repérer et à cliquer.
- **Inversion de contraste à l'état coché** plutôt qu'une simple coche
  colorée sur fond inchangé : `indicatorbackground` plein `COLOR_ACCENT` +
  `indicatorforeground` blanc. `disabled` reste prioritaire sur `selected`
  dans les deux `map` (listé en premier — ttk retient la première
  correspondance) : une case cochée-désactivée reste grise sur fond gris,
  jamais verte.

**Piège** : une case à cocher posée sur un panneau blanc (`Panel.TFrame`)
avec le style de base `TCheckbutton` hérite du fond `COLOR_BG` (crème) de
la règle `.` — un rectangle visiblement décalé apparaît derrière son
libellé. Toujours utiliser `style="Panel.TCheckbutton"`, jamais le style
de base, dès qu'une case à cocher est posée sur un panneau.

## Icônes (`icons.py`)

Glyphes Unicode monochromes **par défaut** (formes géométriques, flèches,
ponctuation) — pas d'emoji couleur, dont le rendu dépend de la police
système et de la plateforme.

- État/complétude : `ICON_STATE_EMPTY` ○ / `ICON_STATE_PARTIAL` ◐ /
  `ICON_STATE_FULL` ●
- Structure : `ICON_ADD` ＋ / `ICON_REMOVE` － / `ICON_DELETE` ✕ /
  `ICON_EXPAND` ▸ / `ICON_COLLAPSE` ▾
- Signalétique : `ICON_WARNING` ⚠ / `ICON_CHECK` ✓ / `ICON_CROSS` ✗
- Navigation : `ICON_RESET` ↺ / `ICON_RESTART` ⟳ / `ICON_NEXT` ⏭ /
  `ICON_HINT_ARROW` →
- Calendrier : `ICON_CALENDAR` 📅 (icône bitmap sur Windows — cf.
  l'exception ci-dessous), bouton compact ouvrant `dialogs.ask_date`

**Exception 📅/💾 : Windows seulement, résolue en bitmap (`chrome_icons.py`,
2026-09-05 → 2026-09-06).** Historique de la dérive, dans l'ordre :
1. Une première version remplaçait le bouton calendrier par `…`
   (convention « Choisir… ») pour rester dans le principe « pas d'emoji
   couleur » ; jugé moins lisible sur inspection du code.
2. Retour à l'emoji couleur 📅 (et au préfixe « 💾 » du bouton
   **Enregistrer**, `app_layout._btn_save`) **partout**, pariant que leur
   reconnaissance immédiate valait le risque de rendu plateforme-dépendant
   déjà documenté ci-dessus. **Un test Windows réel a confirmé ce risque,
   mais SEULEMENT sur Windows** (Linux confirmé correct à l'usage) : 📅/💾
   viennent du bloc « Miscellaneous Symbols and Pictographs », à
   présentation **emoji obligatoire** — Segoe UI ne les contient pas, Tk
   bascule sur Segoe UI Emoji, rendu couleur surdimensionné.
3. Repli glyphe conditionné à `sys.platform == "win32"`
   (`ICON_CALENDAR = "▦"`, Formes géométriques, texte par défaut comme les
   glyphes listés plus haut) — lui-même abandonné : un diagnostic CI sur
   `windows-latest` a montré que `▦` n'est même pas représentable dans
   l'encodage Windows par défaut (`cp1252`), signe que sa police n'est pas
   universellement disponible sur Windows contrairement aux glyphes
   `ICON_STATE_*`/`ICON_EXPAND`/`ICON_COLLAPSE` (Latin-1/WGL4).
4. Repli texte (`_("Date")` à la place d'un glyphe) — fonctionnel (zéro
   risque de police) mais jugé insatisfaisant : pas une « icône ».
5. **Correctif final retenu : `chrome_icons.py`**, une **icône bitmap**
   dessinée par PIL (déjà une dépendance du projet) et mise en cache en
   `PhotoImage` — une image ne dépend d'AUCUNE police installée, rendu
   garanti identique sur toute machine Windows. Utilisé UNIQUEMENT sur
   Windows (`if sys.platform == "win32": ttk.Button(..., image=
   chrome_icons.calendar_icon()/save_icon(), ...)`, sinon la branche
   `else` garde `ICON_CALENDAR`/le préfixe « 💾 » d'origine) — Linux/macOS
   ne sont pas concernés, leur rendu convenait déjà.

**Pas de glyphe de repli** reste la règle pour les actions sans équivalent
monochrome fiable (document, imprimante, image, tableau, loupe) : ces
boutons sont **texte seul** (« Fiche PDF (arbre courant) », « PNG du
dessin », « Tableau PRBS — Excel (XLSX)… »…) — 📅/💾 restent la seule
paire à bénéficier d'un traitement dédié (icône bitmap), réservé à
Windows, car ce sont les deux seules commandes jugées assez fréquentes
sur le terrain pour justifier cet investissement.

**Piège i18n** : un glyphe qui préfixe une chaîne traduisible
(`_("⚠ Renseignez le rayon…")`, `_("▸ Saisie du brin {label}")`) fait
partie intégrante de l'entrée du catalogue — ne PAS l'extraire vers une
constante `icons.py` interpolée (`_("{icon} …").format(icon=ICON_WARNING)`)
sans nécessité : ça change la forme de la chaîne source et retombe dans le
piège déjà documenté dans CLAUDE.md (`_(une_variable)` invisible au
scanner AST de `tests/test_i18n.py`). Les constantes `icons.py` servent
les glyphes **hors** chaîne traduisible (`text="✕"`, `text=ICON_CALENDAR`).
Toute chaîne traduisible modifiée doit avoir son entrée mise à jour dans
`translations/en.py` **et** `translations/it.py` (clés alignées entre les
deux, cf. `tests/test_i18n.py`).
