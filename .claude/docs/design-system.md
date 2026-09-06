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

## Couleurs (`palette.py`)

- `COLOR_ACCENT` = couleur de marque du **chrome interactif uniquement**
  (boutons, titres de fenêtre, onglets actifs, sélections). Vert
  historique `#2D7A3E` — IDENTIQUE à `COULEUR_CLASSE[CLASSE_VERT]`.
  Plusieurs teintes distinctes ont été essayées pendant ce design system
  pour lever la collision de sens (bouton actif ↔ arbre en bon état) : un
  bleu pétrole désaturé (`#1E5F6B`, AAA mais jugé trop terne — « gris »,
  « triste »), un cobalt franc (`#2563EB`, AA mais « le bleu pose
  problème »), un violet améthyste (`#6B3FA0`, AAA mais non plus retenu à
  l'usage). Aucune n'a convaincu : préférence assumée pour le vert
  d'origine malgré le compromis de sens.
- `COLOR_RENDER_ACCENT` = couleur d'accent des **rendus golden-testés**
  (dessin de section, fiche PDF, comparaison inter-missions). Même valeur
  que `COLOR_ACCENT` (`#2D7A3E`) — figée indépendamment pour que le chrome
  UI puisse un jour reprendre une teinte distincte sans faire dévier un
  pixel des golden-tests. **Ne jamais remplacer par `COLOR_ACCENT`** dans
  `section_canvas.py`/`pil_render.py`/`comparaison_render.py`/
  `fiche_pdf.py` — cela romprait leurs goldens.
- `COULEUR_CLASSE` (Vert/Orange/Rouge) reste réservée à l'affichage du
  **diagnostic de risque d'un arbre** (pastille, cellule, légende). Ne
  jamais la réutiliser comme couleur de chrome générique.

## Typographie (`ui_fonts.py`)

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
