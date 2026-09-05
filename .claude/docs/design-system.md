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

**Exception assumée (2026-09-05) : `ICON_CALENDAR` 📅.** Une première
version de ce design system remplaçait le bouton calendrier par `…`
(convention « Choisir… ») pour rester dans le principe « pas d'emoji
couleur ». À l'usage, ce repli s'est révélé moins lisible qu'une icône —
un `…` ne se distingue pas au premier coup d'œil d'un état « en attente »
ou d'un simple bouton tronqué, alors que 📅 identifie la fonction
instantanément. Même diagnostic pour le préfixe « 💾 » du bouton
**Enregistrer**, toujours visible en barre d'état (`app_layout._btn_save`,
chaîne `_("💾 Enregistrer")`) : c'est la commande la plus fréquente de
l'app, elle doit rester repérable au scan rapide sur le terrain. Le risque
de rendu plateforme-dépendant (déjà documenté ci-dessus) est jugé, pour
ces deux commandes à très forte fréquence d'usage, moins coûteux que la
perte de lisibilité constatée.

**Pas de glyphe de repli** reste la règle pour les AUTRES actions sans
équivalent monochrome fiable (document, imprimante, image, tableau,
loupe) : ces boutons sont **texte seul** (« Fiche PDF (arbre courant) »,
« Imprimer », « PNG du dessin », « Exporter le tableau »…). Choix
délibéré, pas un renoncement : chercher un dingbat Unicode obscur pour
ces actions échangerait un risque de rendu (emoji couleur) contre un
autre (glyphe absent de la police système/plateforme, notamment Segoe UI
sur Windows) sans réel gain de clarté par rapport à un libellé texte — à
la différence de 📅/💾 ci-dessus, dont la reconnaissance immédiate justifie
le compromis.

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
