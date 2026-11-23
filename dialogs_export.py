"""
Dialogue de choix d'un export : portée (arbre courant / toute la mission)
puis format de fichier, pour UN type d'export du registre
(`export_registry`). Un seul dialogue pour tous les types — il ne montre
que ce qui est réellement à choisir (pas de bloc « portée » s'il n'y en a
qu'une). Le dernier choix fait pour chaque type est mémorisé pour la
session : `Entrée` suffit pour refaire le même export.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Dict, Optional, Tuple

from dialogs import _make_modal
from export_registry import ExportType
from i18n import _
from palette import COLOR_PANEL

# Mémoire de session : type d'export → (portée, format) du dernier choix.
_DERNIER_CHOIX: Dict[str, Tuple[str, str]] = {}


def ask_export_choice(parent: tk.Misc, etype: ExportType
                      ) -> Optional[Tuple[str, str]]:
    """Demande portée + format pour `etype`. Renvoie `(clé_portée,
    clé_format)` si validé, `None` si annulé."""
    scope0, fmt0 = _DERNIER_CHOIX.get(etype.key, etype.default_choice())
    if etype.format(scope0, fmt0) is None:
        scope0, fmt0 = etype.default_choice()

    dlg = tk.Toplevel(parent)
    dlg.title(_("Exporter — {type}").format(type=etype.label))
    dlg.configure(bg=COLOR_PANEL)
    dlg.resizable(False, False)
    result: Dict[str, Optional[Tuple[str, str]]] = {"val": None}
    var_scope = tk.StringVar(value=scope0)
    var_fmt = tk.StringVar(value=fmt0)

    row = 0
    if len(etype.scopes) > 1:
        ttk.Label(dlg, text=_("Que faut-il exporter ?"),
                  background=COLOR_PANEL).grid(
            row=row, column=0, sticky="w", padx=14, pady=(14, 4))
        row += 1
        for sc in etype.scopes:
            ttk.Radiobutton(
                dlg, text=sc.label, value=sc.key, variable=var_scope,
                command=lambda: rebuild_formats(keep=True),
            ).grid(row=row, column=0, sticky="w", padx=26, pady=1)
            row += 1

    ttk.Label(dlg, text=_("Format du fichier"),
              background=COLOR_PANEL).grid(
        row=row, column=0, sticky="w", padx=14, pady=(12, 4))
    row += 1
    fmt_frame = ttk.Frame(dlg, style="Panel.TFrame")
    fmt_frame.grid(row=row, column=0, sticky="we", padx=26)
    row += 1

    def rebuild_formats(keep: bool = False) -> None:
        for w in fmt_frame.winfo_children():
            w.destroy()
        sc = etype.scope(var_scope.get()) or etype.scopes[0]
        keys = [f.key for f in sc.formats]
        if not (keep and var_fmt.get() in keys):
            var_fmt.set(keys[0])
        for f in sc.formats:
            ttk.Radiobutton(fmt_frame, text=f.label, value=f.key,
                            variable=var_fmt).pack(anchor="w", pady=1)

    rebuild_formats(keep=True)

    def ok() -> None:
        choice = (var_scope.get(), var_fmt.get())
        _DERNIER_CHOIX[etype.key] = choice
        result["val"] = choice
        dlg.destroy()

    btns = ttk.Frame(dlg, style="Panel.TFrame")
    btns.grid(row=row, column=0, sticky="e", padx=14, pady=(14, 12))
    ttk.Button(btns, text=_("Annuler"), style="Ghost.TButton",
               command=dlg.destroy).pack(side="right", padx=6)
    ttk.Button(btns, text=_("Exporter"), style="Accent.TButton",
               command=ok).pack(side="right")

    dlg.bind("<Return>", lambda e: ok())
    dlg.bind("<Escape>", lambda e: dlg.destroy())
    _make_modal(dlg, parent)
    dlg.wait_window()
    return result["val"]
