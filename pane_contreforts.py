"""
Onglet « Contreforts » : table des contreforts + boutons add/edit/del.

Encapsule la table Tk, la construction du widget, son refresh depuis
un `Arbre`, et les trois actions add/edit/del. La fenêtre `App` n'a
plus à connaître le détail des widgets — elle instancie le pane et
appelle `refresh()` quand l'arbre courant change.

Contrat host (Protocol structural) :
- `_current_arbre()` : renvoie l'arbre courant ou None.
- `_debounced_redraw()` : déclenche un redraw du dessin de section.

Réunit en un seul module la construction du widget, le refresh depuis
l'arbre et les trois actions add/edit/del — autrefois éparpillés dans
`App._build_layout`, `App._refresh_contreforts_table` et l'ancien
`app_actions.py` (supprimé après l'extraction des trois panes).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Optional, Protocol

from dialogs import edit_contrefort
from geometry import DIRECTION_LABELS
from model import Arbre, Contrefort


class _ContrefortsHost(Protocol):
    def _current_arbre(self) -> Optional[Arbre]: ...
    def _debounced_redraw(self) -> None: ...
    def push_undo(self) -> None: ...


class ContrefortsPane(ttk.Frame):
    """Pane Tk autonome : possède sa table, ses boutons et ses actions."""

    def __init__(self, master: tk.Misc, host: _ContrefortsHost, **kw: Any) -> None:
        super().__init__(master, style="Panel.TFrame", padding=10, **kw)
        self._host = host
        self._build()

    def _build(self) -> None:
        ttk.Label(
            self,
            text="Un contrefort = empattement saillant à la base du "
                 "tronc, défini par une orientation (grade central), "
                 "une largeur en grades et une longueur radiale en cm "
                 "vers l'extérieur. Élément descriptif (n'impacte pas "
                 "le diagnostic).",
            style="Muted.TLabel", wraplength=420, justify="left"
        ).pack(anchor="w", pady=(0, 8))

        tbl_frame = ttk.Frame(self, style="Panel.TFrame")
        tbl_frame.pack(fill="both", expand=True)

        cols = ("n", "centre", "largeur_gr", "largeur_cm",
                "longueur", "comm")
        self.tbl = ttk.Treeview(tbl_frame, columns=cols,
                                 show="headings", height=10)
        heads = [("n", "N°", 35),
                 ("centre", "Orientation (gr)", 120),
                 ("largeur_gr", "Largeur (gr)", 90),
                 ("largeur_cm", "Largeur (cm)", 90),
                 ("longueur", "Longueur (cm)", 100),
                 ("comm", "Commentaire", 120)]
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
        ttk.Button(tb, text="＋ Ajouter contrefort",
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
        for i, c in enumerate(a.contreforts):
            lbl = DIRECTION_LABELS.get(c.grade_centre, "")
            centre_txt = f"{c.grade_centre}" + (f" — {lbl}" if lbl else "")
            self.tbl.insert(
                "", "end", iid=f"c{i}",
                values=(c.numero,
                        centre_txt,
                        f"{c.largeur_grades}",
                        f"{c.largeur_cm(R):.1f}",
                        f"{c.longueur_cm:g}",
                        c.commentaire))

    def _selected_index(self) -> Optional[int]:
        sel = self.tbl.selection()
        if not sel:
            return None
        return int(sel[0][1:])

    def _on_add(self) -> None:
        a = self._host._current_arbre()
        if not a:
            return
        c = Contrefort(numero=len(a.contreforts) + 1,
                       grade_centre=0, largeur_grades=75, longueur_cm=10.0)
        if edit_contrefort(self, a, c):
            self._host.push_undo()
            a.contreforts.append(c)
            a.renumeroter_contreforts()
            self.refresh()
            self._host._debounced_redraw()

    def _on_edit(self) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        a = self._host._current_arbre()
        if not a:
            return
        c = a.contreforts[idx]
        if edit_contrefort(self, a, c):
            self._host.push_undo()
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
        del a.contreforts[idx]
        a.renumeroter_contreforts()
        self.refresh()
        self._host._debounced_redraw()
