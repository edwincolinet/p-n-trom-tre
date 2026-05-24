"""
Onglet « Sondages » : table + boutons add/edit/del.

Pendant de `pane_contreforts` / `pane_degradations`. Le pane possède
sa table, ses boutons, son refresh et ses actions.

Contrat host (Protocol structural) :
- `_current_arbre()` : renvoie l'arbre courant ou None.
- `_debounced_redraw()` : déclenche un redraw du dessin de section.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Optional, Protocol

from dialogs import edit_sondage
from geometry import DIRECTION_LABELS, GRADES
from model import Arbre, Sondage


class _SondagesHost(Protocol):
    def _current_arbre(self) -> Optional[Arbre]: ...
    def _debounced_redraw(self) -> None: ...
    def push_undo(self) -> None: ...


class SondagesPane(ttk.Frame):
    """Pane Tk autonome : possède sa table, ses boutons et ses actions."""

    def __init__(self, master: tk.Misc, host: _SondagesHost, **kw: Any) -> None:
        super().__init__(master, style="Panel.TFrame", padding=10, **kw)
        self._host = host
        self._build()

    def _build(self) -> None:
        ttk.Label(
            self,
            text="Chaque ligne = un sondage. Le dessin et les épaisseurs "
                 "d'altération par direction sont recalculés automatiquement.",
            style="Muted.TLabel", wraplength=400, justify="left"
        ).pack(anchor="w", pady=(0, 8))

        tbl_frame = ttk.Frame(self, style="Panel.TFrame")
        tbl_frame.pack(fill="both", expand=True)
        cols = ("n", "grade", "dir", "sain", "altere", "comp")
        self.tbl = ttk.Treeview(tbl_frame, columns=cols, show="headings",
                                 height=12)
        heads = [("n", "N°", 40), ("grade", "Grade (gr)", 80),
                 ("dir", "Direction", 80),
                 ("sain", "Bois sain (cm)", 100),
                 ("altere", "Altéré (cm)", 95),
                 ("comp", "Compart.", 85)]
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
        ttk.Button(tb, text="＋ Ajouter sondage", style="Accent.TButton",
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
        for i, s in enumerate(a.sondages):
            direction = DIRECTION_LABELS.get(s.grade, "")
            if not direction and s.grade in GRADES:
                idx = GRADES.index(s.grade)
                for delta in (1, -1, 2, -2):
                    g2 = GRADES[(idx + delta) % 16]
                    if DIRECTION_LABELS.get(g2):
                        direction = f"~{DIRECTION_LABELS[g2]}"
                        break
            self.tbl.insert("", "end", iid=f"s{i}",
                             values=(s.numero, f"{s.grade}", direction,
                                     f"{s.bois_sain_cm:g}",
                                     f"{s.bois_altere_cm:g}",
                                     s.compartimentation))

    def _selected_index(self) -> Optional[int]:
        sel = self.tbl.selection()
        if not sel:
            return None
        return int(sel[0][1:])

    def _on_add(self) -> None:
        a = self._host._current_arbre()
        if not a:
            return
        s = Sondage(numero=len(a.sondages) + 1, grade=0,
                    bois_sain_cm=a.rayon_tronc_cm, bois_altere_cm=0.0)
        if edit_sondage(self, a, s):
            self._host.push_undo()
            a.sondages.append(s)
            a.renumeroter_sondages()
            self.refresh()
            self._host._debounced_redraw()

    def _on_edit(self) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        a = self._host._current_arbre()
        if not a:
            return
        s = a.sondages[idx]
        self._host.push_undo()
        if edit_sondage(self, a, s):
            self.refresh()
            self._host._debounced_redraw()

    def _on_del(self) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        a = self._host._current_arbre()
        if not a:
            return
        self._host.push_undo()
        del a.sondages[idx]
        a.renumeroter_sondages()
        self.refresh()
        self._host._debounced_redraw()
