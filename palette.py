"""
Palette de couleurs partagée entre la couche UI Tk (`penetrometre.py`)
et le rendu PIL (`pil_render.py`).

Centraliser les couleurs ici a deux objectifs :

1. **Cohérence visuelle Tk ↔ PIL.** Le dessin de la section circulaire
   est rendu deux fois (Canvas Tk pour l'aperçu en direct, PIL pour
   les exports PNG/PDF). Avec une seule source de vérité, ces deux
   moteurs ne peuvent plus diverger sur la couleur d'une plaie ou de
   l'écorce.

2. **Casser le cycle d'import.** Sans ce module, `pil_render.py` aurait
   besoin d'importer la palette de `penetrometre.py`, qui importe à
   son tour `pil_render.py` pour les fonctions d'export. Ce module
   intermédiaire (sans dépendance Tk ni PIL) résout le problème.

Convention : les `COLOR_*` sont des composants visuels neutres
(panneaux, encre, écorce, bois, cernes, dégradation, sondage).
`COULEUR_CLASSE` est un dict label → hex pour les trois classes du
barème (Vert/Orange/Rouge), keyé par les constantes
`CLASSE_*` de `geometry.py`.
"""

from __future__ import annotations

from bareme import CLASSE_ORANGE, CLASSE_ROUGE, CLASSE_VERT

# ----------------------------------------------------------------------
# Palette UI (panneaux, texte, accents)
# ----------------------------------------------------------------------

# --- Charte SILVAVENIR (dossier « design system SILVAVENIR », v1.0 sept. 2026)
#
# Marque : orange #F58101 (titres ≥ 20 px, filets, action principale) ;
# orange foncé #E36C0A (orange lisible en petit corps, survols, liens) ;
# vert forêt #385623 (sous-titres, actions secondaires, texte sur clair) ;
# vert feuille #40A838 (couleur du logo — marque, JAMAIS un état) ;
# vert profond #24331B (fonds pleins, bandeaux) ; sable #FCE3C0 (surlignages).
COLOR_BRAND_ORANGE      = "#F58101"
COLOR_BRAND_ORANGE_DARK = "#E36C0A"
COLOR_BRAND_FOREST      = "#385623"
COLOR_BRAND_LEAF        = "#40A838"
COLOR_BRAND_DEEP        = "#24331B"
COLOR_BRAND_SAND        = "#FCE3C0"

COLOR_BG         = "#FAF9F5"   # fond général (« Papier »)
COLOR_PANEL      = "#FFFFFF"   # panneaux blancs
COLOR_SIDE_PANEL = "#F4F2EC"   # bandeau latéral (« Sous-couche »)
COLOR_RULE       = "#E3E1DA"   # filets
COLOR_FIELD_BORDER = "#D9D7CF" # bordure de champ de saisie
COLOR_INK        = "#404040"   # corps de texte — jamais de noir pur
COLOR_INK_STRONG = "#262625"   # encre forte (titres, valeurs saisies)
# Texte secondaire (libellés d'aide ⓘ, sous-titres, labels d'échelle du
# dessin) : gris secondaire de la charte (#595959, ≈7:1 sur blanc,
# ≈6.6:1 sur le fond Papier — au-dessus du seuil WCAG AA, lisible en plein
# jour sur un laptop de terrain). Couleur partagée Tk ↔ PIL.
COLOR_MUTED      = "#595959"
# Gris titre 3 de la charte : texte des contrôles désactivés, légendes.
COLOR_DISABLED   = "#7F7F7F"

# `COLOR_ACCENT` est la couleur d'accent du CHROME Tk interactif
# (onglets actifs, sélections, cases cochées, titres de section) : le
# **vert forêt** de la charte. Distinct de `COULEUR_CLASSE[CLASSE_VERT]`
# (classe de risque « Vert ») — c'était le compromis assumé avant la
# charte, où le vert d'accent EST le vert « bon état » ; la charte
# interdit d'ailleurs d'employer le vert de marque comme couleur d'état.
# L'action principale (bouton `Accent.TButton`) est, elle, en orange de
# marque (`COLOR_BRAND_ORANGE`).
COLOR_ACCENT     = COLOR_BRAND_FOREST
COLOR_ACCENT_SOFT= "#F1F5EC"   # survol / sélection doux (vert très pâle)

# Couleur d'accent des RENDUS (dessin de section Tk/PIL, fiche PDF,
# comparaison inter-missions) : vert forêt de la charte. Figée
# indépendamment de `COLOR_ACCENT` pour que le chrome puisse évoluer sans
# faire dévier les golden-tests. Ne JAMAIS remplacer par `COLOR_ACCENT`
# dans `section_canvas.py`/`pil_render.py`/`comparaison_render.py`/
# `fiche_pdf.py`.
COLOR_RENDER_ACCENT = COLOR_BRAND_FOREST

# Avertissement non bloquant (garde-fou de saisie : fusion écrêtée des
# dégradations, données à vérifier). Même ambre saturé que la pastille
# « état partiel » de la liste d'arbres — déjà choisi pour se distinguer
# nettement du rouge bordeaux des classes.
COLOR_WARN       = "#D97706"


# ----------------------------------------------------------------------
# Palette du dessin de section (bois, écorce, cernes, dégradation)
# ----------------------------------------------------------------------

COLOR_BARK       = "#5C3A1E"   # brun écorce (intact)
COLOR_BARK_LIGHT = "#8B6244"
COLOR_WOOD       = "#F0DC9E"   # beige doré (bois ancien jaunissant)
COLOR_WOOD_DARK  = "#C9B486"   # variante foncée (états :hover des boutons)
COLOR_CERNE      = "#2A1F10"   # cernes : brun très foncé presque noir
# COLOR_ROT distinct de COLOR_BARK : la dégradation (cavité interne et
# dégradation externe) doit se voir comme un brun NETTEMENT plus foncé
# que l'écorce intacte, pour que la « plaie » soit lisible quand elle
# traverse la couche d'écorce. On vise un contraste fort en restant sur
# une teinte chaude (pas du gris) — l'œil doit lire « plaie profonde »
# vs « écorce intacte ».
COLOR_ROT        = "#140804"   # quasi-noir chaud : bois dégradé
COLOR_SOND       = "#1F3A8A"


# ----------------------------------------------------------------------
# Mapping classe → couleur hexa
# ----------------------------------------------------------------------
#
# Le barème (cf. `classer_prbs` dans bareme.py) renvoie un label
# (Vert / Orange / Rouge). La couleur associée est purement visuelle :
# elle vit ici, pas dans la logique métier. Les exports (XLSX, HTML)
# reçoivent ce dict en paramètre, ce qui leur évite d'importer
# l'application.
#
# RÈGLE : ces couleurs sont réservées à l'affichage du DIAGNOSTIC DE
# RISQUE d'un arbre (pastille de liste, cellule de tableau, légende).
# Ne jamais les réutiliser comme couleur de chrome générique (bouton,
# onglet, sélection, focus) — ce mélange est précisément ce que ce
# design system corrige pour `COLOR_ACCENT` ci-dessus.

COULEUR_CLASSE = {
    CLASSE_VERT:   "#2D7A3E",
    CLASSE_ORANGE: "#E67E22",
    CLASSE_ROUGE:  "#C0392B",
}
