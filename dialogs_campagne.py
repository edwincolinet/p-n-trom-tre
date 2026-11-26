"""Dialogue d'appariement des arbres lors de l'import d'un relevé antérieur."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import List, Optional, Sequence

from dialogs import _make_modal
from i18n import _
from model import Arbre
from palette import COLOR_PANEL


def libelle_arbre(a: Arbre) -> str:
    return f"n° {a.numero_arbre or '?'} — {a.essence or '?'}"


def ask_appariement(parent: tk.Misc, courants: Sequence[Arbre],
                    anciens: Sequence[Arbre],
                    proposition: Sequence[Optional[int]]
                    ) -> Optional[List[Optional[int]]]:
    """Fait valider, pour chaque arbre de la mission, l'arbre de l'ancienne
    mission qui lui correspond. Renvoie un index (ou `None`) par arbre
    courant, ou `None` si l'expert annule."""
    dlg = tk.Toplevel(parent)
    dlg.title(_("Importer un relevé antérieur"))
    dlg.configure(bg=COLOR_PANEL)
    result: List[Optional[List[Optional[int]]]] = [None]

    ttk.Label(dlg, text=_("Vérifiez la correspondance des arbres. Seuls les "
                          "arbres appariés reçoivent le relevé."),
              style="Panel.TLabel", wraplength=480, justify="left"
              ).pack(anchor="w", padx=12, pady=(12, 8))

    zone = ttk.Frame(dlg, style="Panel.TFrame")
    zone.pack(fill="both", expand=True, padx=12)
    canvas = tk.Canvas(zone, bg=COLOR_PANEL, highlightthickness=0,
                       width=500, height=min(360, 32 * len(courants) + 8))
    vsb = ttk.Scrollbar(zone, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=vsb.set)
    vsb.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    inner = ttk.Frame(canvas, style="Panel.TFrame")
    canvas.create_window((0, 0), window=inner, anchor="nw")
    inner.bind("<Configure>",
               lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))

    choix = [_("(aucun)")] + [libelle_arbre(a) for a in anciens]
    combos: List[ttk.Combobox] = []
    for r, (arbre, i_ancien) in enumerate(zip(courants, proposition)):
        ttk.Label(inner, text=libelle_arbre(arbre), style="Panel.TLabel"
                  ).grid(row=r, column=0, sticky="w", padx=(0, 12), pady=3)
        cmb = ttk.Combobox(inner, values=choix, state="readonly", width=32)
        cmb.current(0 if i_ancien is None else i_ancien + 1)
        cmb.grid(row=r, column=1, sticky="w", pady=3)
        combos.append(cmb)

    def _valider(_e: object = None) -> None:
        choisis = [c.current() - 1 if c.current() > 0 else None
                   for c in combos]
        pris = [i for i in choisis if i is not None]
        if len(set(pris)) != len(pris):
            messagebox.showwarning(
                _("Importer un relevé antérieur"),
                _("Un même arbre de l'ancienne mission est choisi deux fois."),
                parent=dlg)
            return
        result[0] = choisis
        dlg.destroy()

    pied = ttk.Frame(dlg, style="Panel.TFrame", padding=12)
    pied.pack(fill="x")
    ttk.Button(pied, text=_("Importer"), command=_valider).pack(side="right")
    ttk.Button(pied, text=_("Annuler"), command=dlg.destroy
               ).pack(side="right", padx=(0, 8))
    dlg.bind("<Return>", _valider)
    dlg.bind("<Escape>", lambda _e: dlg.destroy())

    _make_modal(dlg, parent)
    if combos:
        combos[0].focus_set()
    dlg.wait_window()
    return result[0]
