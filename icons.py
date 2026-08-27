"""
Jeu de glyphes d'icônes de l'interface (design system).

Emoji couleur bannis du chrome Tk : leur rendu dépend de la police système
et de la plateforme (déjà constaté et documenté pour `ttk.Treeview` dans
`app_arbres.py` — d'où l'absence de 🔴🟠🟢 dans la liste d'arbres). Ce
module généralise cette règle à toute l'application : uniquement des
glyphes issus de blocs Unicode à support universel (formes géométriques,
flèches, ponctuation) — déjà éprouvés dans l'app avant ce module (état de
la liste d'arbres, filtres, compartimentation).

Pour les actions sans équivalent monochrome fiable (document, imprimante,
image, tableau, disquette, loupe), le choix du design system est de NE
PAS chercher un glyphe de repli : le bouton reste texte seul (cf.
`.claude/docs/design-system.md`).
"""

from __future__ import annotations

ICON_ADD = "＋"
ICON_REMOVE = "－"
ICON_DELETE = "✕"
ICON_WARNING = "⚠"
ICON_RESET = "↺"
ICON_RESTART = "⟳"
ICON_NEXT = "⏭"
ICON_HINT_ARROW = "→"
ICON_EXPAND = "▸"
ICON_COLLAPSE = "▾"
ICON_STATE_EMPTY = "○"
ICON_STATE_PARTIAL = "◐"
ICON_STATE_FULL = "●"
ICON_CHECK = "✓"
ICON_CROSS = "✗"
# Bouton compact ouvrant un sélecteur (calendrier…) — convention courante
# (« Parcourir… », « Choisir… ») plutôt qu'un pictogramme.
ICON_PICKER = "…"
