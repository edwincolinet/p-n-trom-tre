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
  (boutons, titres de fenêtre, onglets actifs, sélections). Bleu cobalt
  `#2563EB` (contraste vs blanc = 5.17:1, AA), volontairement **distinct**
  de `COULEUR_CLASSE[CLASSE_VERT]`. Un premier essai en bleu pétrole
  désaturé (`#1E5F6B`) a été jugé trop terne à l'usage — retenu pour son
  contraste (AAA) mais rejeté visuellement (« gris », « triste »).
- `COLOR_RENDER_ACCENT` = couleur d'accent des **rendus golden-testés**
  (dessin de section, fiche PDF, comparaison inter-missions). Figée à
  l'ANCIENNE valeur de `COLOR_ACCENT` (`#2D7A3E`) pour ne jamais faire
  dévier un pixel des golden-tests. Effet de bord positif : les documents
  envoyés au client restent dans le vert historique de l'app, cohérent
  avec le vocabulaire visuel Vert/Orange/Rouge du diagnostic qu'ils
  exposent. **Ne jamais remplacer par `COLOR_ACCENT`** dans
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

Glyphes Unicode monochromes uniquement (formes géométriques, flèches,
ponctuation) — jamais d'emoji couleur, dont le rendu dépend de la police
système et de la plateforme.

- État/complétude : `ICON_STATE_EMPTY` ○ / `ICON_STATE_PARTIAL` ◐ /
  `ICON_STATE_FULL` ●
- Structure : `ICON_ADD` ＋ / `ICON_REMOVE` － / `ICON_DELETE` ✕ /
  `ICON_EXPAND` ▸ / `ICON_COLLAPSE` ▾
- Signalétique : `ICON_WARNING` ⚠ / `ICON_CHECK` ✓ / `ICON_CROSS` ✗
- Navigation : `ICON_RESET` ↺ / `ICON_RESTART` ⟳ / `ICON_NEXT` ⏭ /
  `ICON_HINT_ARROW` →
- `ICON_PICKER` … : bouton compact ouvrant un sélecteur (calendrier…),
  convention déjà en usage avant ce module (boutons « Gérer les niveaux
  personnalisés » de `pane_diagnostic.py`).

**Pas de glyphe de repli** pour les actions sans équivalent monochrome
fiable (document, imprimante, image, tableau, disquette, loupe) : ces
boutons sont **texte seul** (« Fiche PDF (arbre courant) », « Imprimer »,
« PNG du dessin », « Exporter le tableau », « Enregistrer »…). C'est un
choix délibéré, pas un renoncement : chercher un dingbat Unicode obscur
pour ces actions échangerait un risque de rendu (emoji couleur) contre un
autre (glyphe absent de la police système/plateforme, notamment Segoe UI
sur Windows) sans réel gain de clarté par rapport à un libellé texte.

**Piège i18n** : un glyphe qui préfixe une chaîne traduisible
(`_("⚠ Renseignez le rayon…")`, `_("▸ Saisie du brin {label}")`) fait
partie intégrante de l'entrée du catalogue — ne PAS l'extraire vers une
constante `icons.py` interpolée (`_("{icon} …").format(icon=ICON_WARNING)`)
sans nécessité : ça change la forme de la chaîne source et retombe dans le
piège déjà documenté dans CLAUDE.md (`_(une_variable)` invisible au
scanner AST de `tests/test_i18n.py`). Les constantes `icons.py` servent
les glyphes **hors** chaîne traduisible (`text="✕"`, `text=ICON_PICKER`).
Toute chaîne traduisible modifiée doit avoir son entrée mise à jour dans
`translations/en.py` **et** `translations/it.py` (clés alignées entre les
deux, cf. `tests/test_i18n.py`).
