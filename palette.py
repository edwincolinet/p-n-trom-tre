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

COLOR_BG         = "#F7F3EA"   # fond général
COLOR_PANEL      = "#FFFFFF"   # panneaux blancs
COLOR_SIDE_PANEL = "#EAE5D8"   # bandeau latéral (liste des arbres)
COLOR_INK        = "#1A2E22"
# Texte secondaire (libellés d'aide ⓘ, sous-titres, labels d'échelle du
# dessin). Assombri de #6E7B73 à #55605A pour repasser au-dessus du
# seuil de contraste WCAG AA (≈6.5:1 sur blanc, ≈5.8:1 sur le fond
# beige) : l'ancienne teinte (~4.0-4.4:1) rendait le texte d'aide en
# 9 px peu lisible sur un laptop de terrain en plein jour. Couleur
# partagée Tk ↔ PIL → les exports PNG/PDF en bénéficient aussi.
COLOR_MUTED      = "#55605A"

# `COLOR_ACCENT` est la couleur de marque du CHROME Tk interactif
# (boutons, titres de fenêtre, onglets actifs, sélections). Bleu cobalt
# volontairement DISTINCT de `COULEUR_CLASSE[CLASSE_VERT]` (contraste vs
# blanc = 5.17:1, AA — mieux que l'ancien vert à 5.30:1 tout en restant
# net) : avant ce design system, `COLOR_ACCENT` valait EXACTEMENT le même
# hex que la classe de risque « Vert » — un arbre en bon état et un
# bouton actif partageaient le même signal visuel, ce qui diluait le sens
# du vert dans les pastilles de risque (le canal le plus important de
# l'app). Un premier essai en bleu pétrole désaturé (#1E5F6B) a été jugé
# trop terne (« gris », « triste ») — ce cobalt franc corrige le tir tout
# en gardant le contraste. cf. `COLOR_RENDER_ACCENT` ci-dessous pour la
# couleur (inchangée) des rendus golden-testés.
COLOR_ACCENT     = "#2563EB"
COLOR_ACCENT_SOFT= "#CBDAFA"

# Couleur d'accent des RENDUS golden-testés (dessin de section Tk/PIL,
# fiche PDF, comparaison inter-missions) — figée à l'ANCIENNE valeur de
# `COLOR_ACCENT` (avant ce design system) pour ne jamais faire dévier un
# pixel des golden-tests (`tests/test_render.py`,
# `tests/test_section_canvas.py`) au passage du chrome UI à sa nouvelle
# teinte. Un heureux side-effect : ces documents (destinés au client)
# restent dans le vert historique de l'app, cohérent avec le vocabulaire
# visuel Vert/Orange/Rouge du diagnostic qu'ils exposent — voir
# `.claude/docs/design-system.md`. Ne JAMAIS remplacer par `COLOR_ACCENT`
# dans `section_canvas.py`/`pil_render.py`/`comparaison_render.py`/
# `fiche_pdf.py`.
COLOR_RENDER_ACCENT = "#2D7A3E"

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
