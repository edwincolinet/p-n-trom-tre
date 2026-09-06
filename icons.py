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

**Exception 📅/💾 abandonnée (2026-09-06)** : une version antérieure de ce
design system utilisait 📅 (calendrier) et le préfixe « 💾 » du bouton
Enregistrer, en pariant que leur reconnaissance immédiate compenserait le
risque de rendu plateforme-dépendant déjà identifié ci-dessus. Un test sur
Windows réel (pas seulement une inspection du code) a confirmé ce risque :
ces deux glyphes viennent du bloc « Miscellaneous Symbols and
Pictographs », qui impose une présentation **emoji couleur** — Segoe UI ne
les contient pas, Tk bascule alors sur Segoe UI Emoji, dont les glyphes
pleine couleur et surdimensionnés jurent avec le chrome plat du reste de
l'app. Ce n'est pas le cas des glyphes ci-dessus (formes géométriques,
flèches, ponctuation) : ces blocs sont **texte par défaut**, rendus par la
police système normale sans bascule de police, d'où leur rendu identique
et fiable sur les trois plateformes déjà avant ce correctif.
- Le préfixe « 💾 » est retiré : le bouton Enregistrer redevient texte
  seul (`_("Enregistrer")`, déjà traduit ailleurs dans l'app — même clé de
  catalogue réutilisée, cf. `app_layout._btn_save`/
  `comparaison.py` pied de fenêtre).
- `ICON_CALENDAR` passe à un glyphe **texte par défaut** du bloc Formes
  géométriques (même bloc qu'`ICON_STATE_*`/`ICON_EXPAND`/`ICON_COLLAPSE`,
  déjà éprouvé sur Windows) : `▦`, une grille évoquant une page de
  calendrier — moins immédiatement identifiable qu'un pictogramme couleur,
  mais chaque bouton qui le porte a déjà une infobulle explicite
  (« Choisir la date au calendrier »…) et le glyphe reste **distinct** des
  boutons « … » voisins (`pane_diagnostic` : « Gérer les niveaux
  d'urgence/durées personnalisés »), point qui aurait été perdu en
  repliant simplement sur « … ».
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
# le correctif en tête de module (glyphe texte-par-défaut, pas d'emoji).
ICON_CALENDAR = "▦"
