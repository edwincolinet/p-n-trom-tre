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
barème Silvavenir (Vert/Orange/Rouge), keyé par les constantes
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
COLOR_MUTED      = "#6E7B73"

# `COLOR_ACCENT` est la couleur de marque utilisée pour les boutons,
# titres et chrome UI. Elle vaut actuellement le même hex que
# `COULEUR_CLASSE[CLASSE_VERT]` ci-dessous : si Silvavenir décide un
# jour de différencier le vert chrome du vert classe, c'est ici qu'il
# faudra dissocier.
COLOR_ACCENT     = "#2D7A3E"
COLOR_ACCENT_SOFT= "#C9E4CE"


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
# traverse la couche d'écorce.
COLOR_ROT        = "#3E2510"   # brun très foncé : bois dégradé
COLOR_SOND       = "#1F3A8A"


# ----------------------------------------------------------------------
# Mapping classe Silvavenir → couleur hexa
# ----------------------------------------------------------------------
#
# Le barème (cf. `classer_prbs` dans bareme.py) renvoie un label
# (Vert / Orange / Rouge). La couleur associée est purement visuelle :
# elle vit ici, pas dans la logique métier. Les exports (XLSX, HTML)
# reçoivent ce dict en paramètre, ce qui leur évite d'importer
# l'application.

COULEUR_CLASSE = {
    CLASSE_VERT:   "#2D7A3E",
    CLASSE_ORANGE: "#E67E22",
    CLASSE_ROUGE:  "#C0392B",
}
