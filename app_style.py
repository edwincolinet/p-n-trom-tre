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
    s.configure("Ghost.TButton", background=COLOR_PANEL,
                foreground=COLOR_ACCENT, padding=(10, 6),
                font=("Helvetica", 10), borderwidth=1)
    s.map("Ghost.TButton",
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
    s.map("Side.Treeview",
          background=[("selected", COLOR_ACCENT)],
          foreground=[("selected", "white")])
