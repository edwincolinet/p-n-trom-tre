"""
Jeu de glyphes d'icônes de l'interface (design system).

Emoji couleur bannis du chrome Tk PAR DÉFAUT : leur rendu dépend de la
police système et de la plateforme (déjà constaté et documenté pour
`ttk.Treeview` dans `app_arbres.py` — d'où l'absence de 🔴🟠🟢 dans la
liste d'arbres). Ce module généralise cette règle à toute l'application :
uniquement des glyphes issus de blocs Unicode à support universel (formes
géométriques, flèches, ponctuation) — déjà éprouvés dans l'app avant ce
module (état de la liste d'arbres, filtres, compartimentation).

Pour les actions sans équivalent monochrome fiable (document, imprimante,
image, tableau, loupe), le choix du design system reste de NE PAS
chercher un glyphe de repli : le bouton reste texte seul (cf.
`.claude/docs/design-system.md`).

**Exception assumée (2026-09-05)** : le bouton « Enregistrer » (toujours
visible en barre d'état) et les boutons calendrier (📅, sélection de
date) sont des commandes à très forte fréquence d'usage sur le terrain —
le repli en texte seul (essayé dans une première version de ce design
system) s'est révélé moins lisible en scan rapide que l'emoji couleur
d'origine. Le risque de rendu plateforme-dépendant est jugé, pour ces
deux cas précis, moins coûteux que la perte de lisibilité. `ICON_CALENDAR`
ci-dessous porte cette exception ; le préfixe « 💾 » du bouton Enregistrer
vit directement dans la chaîne traduisible (`app_layout._("💾 Enregistrer")`),
comme avant.
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
# Bouton compact ouvrant le calendrier de sélection de date — cf.
# l'exception assumée en tête de module.
ICON_CALENDAR = "📅"
