"""
Thème ttk de l'application Pénétromètre.

Module séparé pour deux raisons :

1. **Allègement de `penetrometre.py`** : la configuration ttk
   (~60 lignes de `ttk.Style.configure(...)`) est purement déclarative
   et n'a rien à faire dans le corps de la classe `App`.

2. **Réutilisabilité** : si demain un second outil (par exemple un
   visualiseur de logs) partage le look Silvavenir, il appellera
   `apply_ttk_styles(root)` sur sa propre fenêtre.

La fonction utilise les couleurs centralisées dans `palette.py`.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from palette import (
    COLOR_ACCENT,
    COLOR_ACCENT_SOFT,
    COLOR_BG,
    COLOR_INK,
    COLOR_MUTED,
    COLOR_PANEL,
    COLOR_SIDE_PANEL,
    COLOR_WOOD_DARK,
)
from ui_fonts import font as _f
from ui_fonts import get_ui_scale


def apply_ttk_styles(root: tk.Misc, *, high_contrast: bool = False) -> None:
    """Configure le thème ttk pour `root` (typiquement la fenêtre App).

    Force le thème `clam` (look uniforme cross-OS, vs. natif Windows
    qui ignorerait certaines options). Si `clam` est absent, on retombe
    silencieusement sur le thème par défaut.

    Styles définis : conteneurs (TFrame en 3 variantes), textes
    (TLabel + Title/Sub/H/Muted/Panel/Side), boutons (TButton +
    Accent/Ghost), saisie (TEntry), onglets (TNotebook + Tab) et
    arborescences (Treeview + Side.Treeview).

    `high_contrast` (accessibilité — laptops de terrain en plein soleil) :
    passe le texte courant en **noir pur** et le texte « atténué »
    (Muted/Sub, onglets inactifs) à un gris **bien plus sombre**, sans
    toucher les accents verts ni les fonds (le dessin n'est pas concerné —
    il est golden-testé). Identité au défaut (`False`) → aucun changement.
    """
    # Texte principal / atténué : assombris en mode contraste élevé.
    ink = "#000000" if high_contrast else COLOR_INK
    muted = "#2C3631" if high_contrast else COLOR_MUTED
    s = ttk.Style(root)
    try:
        s.theme_use("clam")
    except tk.TclError:
        pass
    s.configure(".", background=COLOR_BG, foreground=ink,
                font=_f("Helvetica", 10))
    s.configure("TFrame", background=COLOR_BG)
    s.configure("Panel.TFrame", background=COLOR_PANEL)
    s.configure("Side.TFrame", background=COLOR_SIDE_PANEL)
    s.configure("TLabel", background=COLOR_BG, foreground=ink)
    s.configure("Panel.TLabel", background=COLOR_PANEL,
                foreground=ink)
    s.configure("Side.TLabel", background=COLOR_SIDE_PANEL,
                foreground=ink)
    s.configure("Title.TLabel", background=COLOR_BG,
                foreground=COLOR_ACCENT,
                font=_f("Georgia", 18, "bold"))
    s.configure("Sub.TLabel", background=COLOR_BG, foreground=muted,
                font=_f("Helvetica", 10, "italic"))
    s.configure("H.TLabel", background=COLOR_PANEL,
                foreground=COLOR_ACCENT,
                font=_f("Georgia", 12, "bold"))
    s.configure("Muted.TLabel", background=COLOR_PANEL,
                foreground=muted,
                font=_f("Helvetica", 9))
    s.configure("TButton", padding=6)
    s.configure("Accent.TButton", background=COLOR_ACCENT,
                foreground="white", padding=(12, 7),
                font=_f("Helvetica", 10, "bold"), borderwidth=0)
    s.map("Accent.TButton",
          background=[("active", COLOR_WOOD_DARK),
                      ("pressed", COLOR_WOOD_DARK)])
    # Variante Menubutton du bouton accent (bouton « ＋ Ajouter ▾ » de la
    # liste d'arbres) : le style TButton ne s'applique pas tel quel à un
    # Menubutton.
    s.configure("Accent.TMenubutton", background=COLOR_ACCENT,
                foreground="white", padding=(12, 7),
                font=_f("Helvetica", 10, "bold"), borderwidth=0)
    s.map("Accent.TMenubutton",
          background=[("active", COLOR_WOOD_DARK),
                      ("pressed", COLOR_WOOD_DARK)])
    s.configure("Ghost.TButton", background=COLOR_PANEL,
                foreground=COLOR_ACCENT, padding=(10, 6),
                font=_f("Helvetica", 10), borderwidth=1)
    s.map("Ghost.TButton",
          background=[("active", COLOR_ACCENT_SOFT)])
    # Menu déroulant d'export (`pane_diagnostic`) : même look que
    # Ghost.TButton mais sur un ttk.Menubutton (le style TButton ne
    # s'applique pas tel quel à un Menubutton).
    s.configure("Ghost.TMenubutton", background=COLOR_PANEL,
                foreground=COLOR_ACCENT, padding=(10, 6),
                font=_f("Helvetica", 10), borderwidth=1)
    s.map("Ghost.TMenubutton",
          background=[("active", COLOR_ACCENT_SOFT)])
    # Sélecteur de brin (cépées) : barre et boutons-onglets.
    _brin_bg = "#EBF5EE"   # très légère teinte verte (distinct du fond blanc)
    s.configure("BrinBar.TFrame", background=_brin_bg)
    s.configure("BrinBar.TLabel",
                background=_brin_bg, foreground=muted,
                font=_f("Helvetica", 9))
    # Brin.Toolbutton hérite du layout Toolbutton (pas d'indicateur radio) ;
    # selected = fond accent vert ; active = fond accent doux ; normal = blanc.
    s.configure("Brin.Toolbutton",
                background=COLOR_PANEL, foreground=ink,
                padding=(12, 5),
                font=_f("Helvetica", 10, "bold"))
    s.map("Brin.Toolbutton",
          background=[("selected", COLOR_ACCENT),
                      ("pressed",  COLOR_ACCENT),
                      ("active",   COLOR_ACCENT_SOFT)],
          foreground=[("selected", "white"),
                      ("pressed",  "white"),
                      ("active",   COLOR_ACCENT)])
    s.configure("TEntry", fieldbackground=COLOR_PANEL,
                foreground=ink, padding=3)
    # Cases à cocher posées sur un fond panneau (dialogues) : sans ça le
    # libellé hériterait du fond COLOR_BG et trancherait sur le panneau.
    s.configure("Panel.TCheckbutton", background=COLOR_PANEL,
                foreground=ink)
    s.map("Panel.TCheckbutton", background=[("active", COLOR_PANEL)])
    s.configure("TNotebook", background=COLOR_PANEL, borderwidth=0)
    s.configure("TNotebook.Tab", padding=(16, 9),
                font=_f("Helvetica", 10, "bold"),
                background="#E7E2D4", foreground=muted)
    s.map("TNotebook.Tab",
          background=[("selected", COLOR_PANEL)],
          foreground=[("selected", COLOR_ACCENT)])
    s.configure("Treeview", background=COLOR_PANEL,
                fieldbackground=COLOR_PANEL, foreground=ink,
                rowheight=round(26 * get_ui_scale()), borderwidth=0)
    s.configure("Treeview.Heading",
                background=COLOR_ACCENT, foreground="white",
                font=_f("Helvetica", 10, "bold"), borderwidth=0)
    s.map("Treeview",
          background=[("selected", COLOR_ACCENT_SOFT)],
          foreground=[("selected", ink)])
    s.configure("Side.Treeview", background=COLOR_SIDE_PANEL,
                fieldbackground=COLOR_SIDE_PANEL,
                rowheight=round(28 * get_ui_scale()))
    # Pas de `foreground=white` sur la sélection : on veut que les
    # tags d'état (rouge/orange/vert posés par `tree_arbres.tag_configure`)
    # restent visibles même sur l'arbre courant (= ligne sélectionnée).
    # Le fond vert accent suffit à signaler la sélection.
    s.map("Side.Treeview",
          background=[("selected", COLOR_ACCENT_SOFT)])

    # ------------------------------------------------------------------
    # Workaround bpo-36468 — depuis Python 3.7, `ttk.Treeview` ignore
    # silencieusement le `foreground` posé par `tag_configure` à cause
    # d'entrées par défaut dans le mapping de style qui priment sur le
    # tag. Sans ce patch, les tags d'état (`etat_vide`, `etat_partiel`,
    # `etat_ok` et ses variantes de classe `etat_ok_{vert,orange,rouge}`)
    # sont sans effet et la pastille reste blanche/grise.
    # On retire les entrées `("!disabled", "!selected", …)` du mapping
    # background/foreground pour que les tags prennent enfin la main.
    # Réf. https://bugs.python.org/issue36468
    # ------------------------------------------------------------------
    # Retour `list[Any]` : `Style.map(query_opt=…)` renvoie des
    # state-specs hétérogènes (tuples d'états + valeur) que les stubs
    # tkinter typent en `Any` ; forcer `list[tuple[str, ...]]` créait un
    # faux positif (la liste est ré-injectée telle quelle dans `map()`).
    def _fixed_map(style_name: str, option: str) -> list[Any]:
        return [elm for elm in s.map(style_name, query_opt=option)
                if elm[:2] != ("!disabled", "!selected")]

    for tv_style in ("Treeview", "Side.Treeview"):
        s.map(tv_style,
              foreground=_fixed_map(tv_style, "foreground"),
              background=_fixed_map(tv_style, "background"))
