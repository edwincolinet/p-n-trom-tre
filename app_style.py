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


def apply_ttk_styles(root: tk.Misc) -> None:
    """Configure le thème ttk pour `root` (typiquement la fenêtre App).

    Force le thème `clam` (look uniforme cross-OS, vs. natif Windows
    qui ignorerait certaines options). Si `clam` est absent, on retombe
    silencieusement sur le thème par défaut.

    Styles définis : conteneurs (TFrame en 3 variantes), textes
    (TLabel + Title/Sub/H/Muted/Panel/Side), boutons (TButton +
    Accent/Ghost), saisie (TEntry), onglets (TNotebook + Tab) et
    arborescences (Treeview + Side.Treeview).
    """
    s = ttk.Style(root)
    try:
        s.theme_use("clam")
    except tk.TclError:
        pass
    s.configure(".", background=COLOR_BG, foreground=COLOR_INK,
                font=("Helvetica", 10))
    s.configure("TFrame", background=COLOR_BG)
    s.configure("Panel.TFrame", background=COLOR_PANEL)
    s.configure("Side.TFrame", background=COLOR_SIDE_PANEL)
    s.configure("TLabel", background=COLOR_BG, foreground=COLOR_INK)
    s.configure("Panel.TLabel", background=COLOR_PANEL,
                foreground=COLOR_INK)
    s.configure("Side.TLabel", background=COLOR_SIDE_PANEL,
                foreground=COLOR_INK)
    s.configure("Title.TLabel", background=COLOR_BG,
                foreground=COLOR_ACCENT,
                font=("Georgia", 18, "bold"))
    s.configure("Sub.TLabel", background=COLOR_BG, foreground=COLOR_MUTED,
                font=("Helvetica", 10, "italic"))
    s.configure("H.TLabel", background=COLOR_PANEL,
                foreground=COLOR_ACCENT,
                font=("Georgia", 12, "bold"))
    s.configure("Muted.TLabel", background=COLOR_PANEL,
                foreground=COLOR_MUTED,
                font=("Helvetica", 9))
    s.configure("TButton", padding=6)
    s.configure("Accent.TButton", background=COLOR_ACCENT,
                foreground="white", padding=(12, 7),
                font=("Helvetica", 10, "bold"), borderwidth=0)
    s.map("Accent.TButton",
          background=[("active", COLOR_WOOD_DARK),
                      ("pressed", COLOR_WOOD_DARK)])
    # Variante Menubutton du bouton accent (bouton « ＋ Ajouter ▾ » de la
    # liste d'arbres) : le style TButton ne s'applique pas tel quel à un
    # Menubutton.
    s.configure("Accent.TMenubutton", background=COLOR_ACCENT,
                foreground="white", padding=(12, 7),
                font=("Helvetica", 10, "bold"), borderwidth=0)
    s.map("Accent.TMenubutton",
          background=[("active", COLOR_WOOD_DARK),
                      ("pressed", COLOR_WOOD_DARK)])
    s.configure("Ghost.TButton", background=COLOR_PANEL,
                foreground=COLOR_ACCENT, padding=(10, 6),
                font=("Helvetica", 10), borderwidth=1)
    s.map("Ghost.TButton",
          background=[("active", COLOR_ACCENT_SOFT)])
    # Menu déroulant d'export (`pane_diagnostic`) : même look que
    # Ghost.TButton mais sur un ttk.Menubutton (le style TButton ne
    # s'applique pas tel quel à un Menubutton).
    s.configure("Ghost.TMenubutton", background=COLOR_PANEL,
                foreground=COLOR_ACCENT, padding=(10, 6),
                font=("Helvetica", 10), borderwidth=1)
    s.map("Ghost.TMenubutton",
          background=[("active", COLOR_ACCENT_SOFT)])
    s.configure("TEntry", fieldbackground=COLOR_PANEL,
                foreground=COLOR_INK, padding=3)
    s.configure("TNotebook", background=COLOR_PANEL, borderwidth=0)
    s.configure("TNotebook.Tab", padding=(16, 9),
                font=("Helvetica", 10, "bold"),
                background="#E7E2D4", foreground=COLOR_MUTED)
    s.map("TNotebook.Tab",
          background=[("selected", COLOR_PANEL)],
          foreground=[("selected", COLOR_ACCENT)])
    s.configure("Treeview", background=COLOR_PANEL,
                fieldbackground=COLOR_PANEL, foreground=COLOR_INK,
                rowheight=26, borderwidth=0)
    s.configure("Treeview.Heading",
                background=COLOR_ACCENT, foreground="white",
                font=("Helvetica", 10, "bold"), borderwidth=0)
    s.map("Treeview",
          background=[("selected", COLOR_ACCENT_SOFT)],
          foreground=[("selected", COLOR_INK)])
    s.configure("Side.Treeview", background=COLOR_SIDE_PANEL,
                fieldbackground=COLOR_SIDE_PANEL, rowheight=28)
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
    def _fixed_map(style_name: str, option: str) -> list[tuple[str, ...]]:
        return [elm for elm in s.map(style_name, query_opt=option)
                if elm[:2] != ("!disabled", "!selected")]

    for tv_style in ("Treeview", "Side.Treeview"):
        s.map(tv_style,
              foreground=_fixed_map(tv_style, "foreground"),
              background=_fixed_map(tv_style, "background"))
