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

**Exception 📅/💾 : Windows seulement (2026-09-05 → 2026-09-06).** Une
version antérieure de ce design system utilisait 📅 (calendrier) et le
préfixe « 💾 » du bouton Enregistrer PARTOUT, en pariant que leur
reconnaissance immédiate compenserait le risque de rendu
plateforme-dépendant déjà identifié ci-dessus. Un test réel a confirmé ce
risque **sur Windows seulement** : ces deux glyphes viennent du bloc
« Miscellaneous Symbols and Pictographs », qui impose une présentation
**emoji couleur** — Segoe UI ne les contient pas, Tk bascule alors sur
Segoe UI Emoji, dont les glyphes pleine couleur et surdimensionnés jurent
avec le chrome plat du reste de l'app. **Sur Linux/macOS le rendu
d'origine convient** (confirmé à l'usage) — pas de raison de le changer
là où il fonctionne. D'où un repli **`sys.platform == "win32"`
uniquement**, pas un abandon général.

Un premier repli Windows (`ICON_CALENDAR = "▦"`, Formes géométriques,
texte-par-défaut) a lui-même été abandonné : un diagnostic CI sur
`windows-latest` a montré que `▦` n'est même pas représentable dans
l'encodage Windows par défaut (`cp1252` — `UnicodeEncodeError: 'charmap'
codec can't encode character '▦'`), signe que son support dans les
polices Windows de base est bien moins garanti que celui
d'`ICON_STATE_*`/`ICON_EXPAND`/`ICON_COLLAPSE` (Latin-1/WGL4, couverts
par `cp1252`). Un second repli en texte simple (`_("Date")`) a bien
fonctionné (zéro risque de police) mais restait moins satisfaisant qu'une
vraie icône. **Correctif final (2026-09-06) : `chrome_icons.py`** — sur
Windows, les boutons calendrier/Enregistrer affichent une **icône bitmap**
(dessinée par PIL, mise en cache en `PhotoImage`) plutôt qu'un glyphe
Unicode : une image ne dépend d'AUCUNE police installée, donc rendu
garanti identique quelle que soit la machine Windows. `ICON_CALENDAR`
(ce module) et le préfixe « 💾 » restent inchangés partout ailleurs
(Linux/macOS, rendu confirmé correct à l'usage).
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
# Bouton compact ouvrant le calendrier de sélection de date. Sur Windows,
# remplacé par une icône bitmap (`chrome_icons.calendar_icon`, cf.
# l'exception en tête de module) — cette constante ne sert donc QUE
# hors Windows.
ICON_CALENDAR = "📅"
