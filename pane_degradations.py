"""
Onglet « Dégradations externes » : table + boutons add/edit/del.

Pendant de `pane_contreforts.ContrefortsPane`, même pattern : le pane
possède sa table, ses boutons, son refresh et ses actions. La fenêtre
`App` instancie le pane et appelle `refresh()` quand l'arbre change.

Contrat host (Protocol structural) :
- `_current_arbre()` : renvoie l'arbre courant ou None.
- `_debounced_redraw()` : déclenche un redraw du dessin de section.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Optional, Protocol

from dialogs import edit_degradation
from model import Arbre, DegradationExterne


class _DegradationsHost(Protocol):
    def _current_arbre(self) -> Optional[Arbre]: ...
    def _debounced_redraw(self) -> None: ...


class DegradationsPane(ttk.Frame):
    """Pane Tk autonome : possède sa table, ses boutons et ses actions."""

    def __init__(self, master: tk.Misc, host: _DegradationsHost, **kw: Any) -> None:
        super().__init__(master, style="Panel.TFrame", padding=10, **kw)
        self._host = host
        self._build()

    def _build(self) -> None:
        ttk.Label(
            self,
            text="Une dégradation externe = un arc continu sur l'écorce, "
                 "défini par un grade de début, un grade de fin (sens "
                 "horaire) et une profondeur radiale en cm.",
            style="Muted.TLabel", wraplength=400, justify="left"
        ).pack(anchor="w", pady=(0, 8))

        tbl_frame = ttk.Frame(self, style="Panel.TFrame")
        tbl_frame.pack(fill="both", expand=True)

        cols = ("n", "debut", "fin", "largeur_gr", "largeur_cm",
                "profondeur", "comm")
        self.tbl = ttk.Treeview(tbl_frame, columns=cols,
                                 show="headings", height=10)
        heads = [("n", "N°", 35),
                 ("debut", "Début (gr)", 75),
                 ("fin", "Fin (gr)", 75),
                 ("largeur_gr", "Largeur (gr)", 85),
                 ("largeur_cm", "Largeur (cm)", 85),
                 ("profondeur", "Profondeur (cm)", 105),
                 ("comm", "Commentaire", 100)]
        for k, lbl, w in heads:
            self.tbl.heading(k, text=lbl)
            self.tbl.column(k, width=w, anchor="center")
        self.tbl.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(tbl_frame, orient="vertical",
                            command=self.tbl.yview)
        sb.pack(side="right", fill="y")
        self.tbl.configure(yscrollcommand=sb.set)
        self.tbl.bind("<Double-1>", lambda e: self._on_edit())

        tb = ttk.Frame(self, style="Panel.TFrame")
        tb.pack(fill="x", pady=(10, 0))
        ttk.Button(tb, text="＋ Ajouter dégradation",
                   style="Accent.TButton",
                   command=self._on_add).pack(side="left")
        ttk.Button(tb, text="Éditer", style="Ghost.TButton",
                   command=self._on_edit).pack(side="left", padx=(6, 0))
        ttk.Button(tb, text="Supprimer", style="Ghost.TButton",
                   command=self._on_del).pack(side="left", padx=(6, 0))

    def refresh(self) -> None:
        """Recharge le contenu de la table depuis l'arbre courant."""
        self.tbl.delete(*self.tbl.get_children())
        a = self._host._current_arbre()
        if not a:
            return
        R = a.rayon_tronc_cm
        for i, deg in enumerate(a.degradations_externes):
            self.tbl.insert(
                "", "end", iid=f"d{i}",
                values=(deg.numero,
                        f"{deg.grade_debut}",
                        f"{deg.grade_fin}",
                        f"{deg.largeur_grades()}",
                        f"{deg.largeur_cm(R):.1f}",
                        f"{deg.profondeur_cm:g}",
                        deg.commentaire))

    def _selected_index(self) -> Optional[int]:
        sel = self.tbl.selection()
        if not sel:
            return None
        return int(sel[0][1:])

    def _on_add(self) -> None:
        a = self._host._current_arbre()
        if not a:
            return
        deg = DegradationExterne(
            numero=len(a.degradations_externes) + 1,
            grade_debut=0, grade_fin=50, profondeur_cm=2.0)
        if edit_degradation(self, a, deg):
            a.degradations_externes.append(deg)
            a.renumeroter_degradations()
            self.refresh()
            self._host._debounced_redraw()

    def _on_edit(self) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        a = self._host._current_arbre()
        if not a:
            return
        deg = a.degradations_externes[idx]
        if edit_degradation(self, a, deg):
            self.refresh()
            self._host._debounced_redraw()

    def _on_del(self) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        a = self._host._current_arbre()
        if not a:
            return
        del a.degradations_externes[idx]
        a.renumeroter_degradations()
        self.refresh()
        self._host._debounced_redraw()
