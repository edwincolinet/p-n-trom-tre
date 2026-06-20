"""
Onglet « Contreforts » : grille des 16 directions, saisie directe sans modale.

Même refonte ergonomique que l'onglet Sondages : la règle d'unicité
métier — un seul contrefort par grade central — borne le domaine à 16
contreforts possibles, naturellement indexés par direction. La grille
pré-affiche les 16 directions (rose des vents) ; l'opérateur tape la
longueur radiale et descend d'une ligne (Entrée / flèche bas).

Sémantique de la grille (alignée sur celle des sondages) :
- **Case « Longueur » vide** = pas de contrefort sur cette direction.
- **Une valeur saisie** (y compris 0) = contrefort existant.
- **Effacer la valeur** supprime le contrefort de cette direction.
- **Largeur** (combobox des multiples de 25) et **commentaire** ne sont
  actifs que si un contrefort existe sur la ligne.
- **Double-clic sur la direction/grade** ouvre le dialogue détaillé
  (`edit_contrefort`) pour la saisie de la largeur en cm.

L'unicité « un seul contrefort par grade central » est garantie par
construction (une ligne par grade) — plus de validation d'unicité.

Contrat host (Protocol structural) :
- `_current_brin()`          : brin (ramet) courant à éditer, ou None.
- `on_section_changed()`     : notifie l'App d'une mutation (dirty +
                               redraw debouncé ; ne re-refresh PAS la
                               grille, déjà à jour).
- `push_undo()`              : snapshot avant une mutation discrète.
- `capture_undo_snapshot()`  : snapshot de l'état courant (undo live).
- `push_undo_snapshot(snap)` : empile un snapshot pré-édition capturé.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Dict, Optional, Protocol

from aide_repliable import AideRepliable
from dialogs import edit_contrefort
from dialogs_shared import to_float, validate_numeric
from geometry import GRADES, WIND_LABELS
from i18n import _
from model import Brin, Contrefort
from palette import COLOR_ACCENT
from ui_fonts import font as ui_font

# Largeur angulaire d'un contrefort : multiples de 25, de 25 à 400 gr.
_LARGEUR_VALUES = [str(v) for v in range(25, 401, 25)]
# Largeur par défaut d'un contrefort créé depuis la grille (reprend le
# pré-réglage de l'ancien bouton « ＋ Ajouter contrefort »).
_LARGEUR_DEFAUT = 75


class _ContrefortsHost(Protocol):
    def _current_brin(self) -> Optional[Brin]: ...
    def on_section_changed(self) -> None: ...
    def push_undo(self) -> None: ...
    def capture_undo_snapshot(self) -> dict: ...
    def push_undo_snapshot(self, snap: dict) -> None: ...


class ContrefortsPane(ttk.Frame):
    """Pane Tk autonome : grille fixe de 16 directions, saisie directe."""

    def __init__(self, master: tk.Misc, host: _ContrefortsHost, **kw: Any) -> None:
        super().__init__(master, style="Panel.TFrame", padding=10, **kw)
        self._host = host
        self._suspend = False
        self._undo_snap: Optional[dict] = None
        self._focus_in_value = ""
        # Par grade : {"long", "larg", "com": StringVar ;
        #              "entry", "combo", "com_entry": widgets}.
        self._rows: Dict[int, Dict[str, Any]] = {}
        self._entries_order: list[ttk.Entry] = []
        self._build()

    def _build(self) -> None:
        # Écho du brin édité (cépée) — cf. SondagesPane. Vide en mono-caule.
        self._brin_title = ttk.Label(
            self, text="", style="Panel.TLabel", foreground=COLOR_ACCENT,
            font=ui_font("Helvetica", 11, "bold"))

        self._intro = ttk.Label(
            self,
            text=_("Un contrefort = empattement saillant à la base du tronc. "
                   "Saisissez la longueur radiale de chaque contrefort."),
            style="Muted.TLabel", wraplength=420, justify="left")
        self._intro.pack(anchor="w", pady=(0, 8))

        grid = ttk.Frame(self, style="Panel.TFrame")
        grid.pack(fill="both", expand=True)

        heads = ["Direction", "Grade", "Longueur (cm)", "Largeur (gr)",
                 "Commentaire"]
        for c, h in enumerate(heads):
            ttk.Label(grid, text=h, style="Panel.TLabel",
                      font=ui_font("Helvetica", 9, "bold")).grid(
                row=0, column=c, sticky="w", padx=6, pady=(0, 4))

        vcmd = (self.register(validate_numeric), "%P")
        for r, g in enumerate(GRADES, start=1):
            var_long = tk.StringVar()
            var_larg = tk.StringVar()
            var_com = tk.StringVar()

            lbl_dir = ttk.Label(grid, text=WIND_LABELS[g],
                                style="Panel.TLabel", width=6,
                                font=ui_font("Helvetica", 10, "bold"))
            lbl_dir.grid(row=r, column=0, sticky="w", padx=6, pady=1)
            lbl_gr = ttk.Label(grid, text=f"{g} gr", style="Muted.TLabel",
                               width=7)
            lbl_gr.grid(row=r, column=1, sticky="w", padx=6, pady=1)

            ent = ttk.Entry(grid, textvariable=var_long, width=10,
                            validate="key", validatecommand=vcmd,
                            justify="center")
            ent.grid(row=r, column=2, sticky="w", padx=6, pady=1)

            cmb = ttk.Combobox(grid, textvariable=var_larg,
                               values=_LARGEUR_VALUES, state="disabled",
                               width=8, justify="center")
            cmb.grid(row=r, column=3, sticky="w", padx=6, pady=1)

            com = ttk.Entry(grid, textvariable=var_com, width=18,
                            state="disabled")
            com.grid(row=r, column=4, sticky="we", padx=6, pady=1)

            self._rows[g] = {"long": var_long, "larg": var_larg,
                             "com": var_com, "entry": ent, "combo": cmb,
                             "com_entry": com}
            self._entries_order.append(ent)

            var_long.trace_add(
                "write", lambda *a, gr=g: self._on_long_write(gr))
            var_com.trace_add(
                "write", lambda *a, gr=g: self._on_com_write(gr))
            for w, field in ((ent, "long"), (com, "com")):
                w.bind("<FocusIn>",
                       lambda e, gr=g, f=field: self._on_focus_in(gr, f))
                w.bind("<FocusOut>",
                       lambda e, gr=g, f=field: self._on_focus_out(gr, f))
            # Navigation verticale rapide (saisie au kilomètre).
            row_idx = r - 1
            ent.bind("<Return>", lambda e, i=row_idx: self._focus_entry(i + 1))
            ent.bind("<Down>", lambda e, i=row_idx: self._focus_entry(i + 1))
            ent.bind("<Up>", lambda e, i=row_idx: self._focus_entry(i - 1))
            cmb.bind("<<ComboboxSelected>>",
                     lambda e, gr=g: self._on_larg_changed(gr))
            # Détail (largeur en cm) via double-clic sur les libellés non
            # éditables — comme la grille de sondages.
            for lbl in (lbl_dir, lbl_gr):
                lbl.bind("<Double-1>", lambda e, gr=g: self._open_dialog(gr))

        grid.columnconfigure(4, weight=1)

        AideRepliable(
            self,
            "Laissez vide une direction sans contrefort. Effacer la "
            "longueur supprime le contrefort. Double-cliquez la "
            "direction pour le détail (largeur en cm sur l'écorce).",
            wraplength=420,
        ).pack(anchor="w", pady=(8, 0))

    # --- Navigation ---------------------------------------------------

    def _focus_entry(self, i: int) -> str:
        """Place le focus sur la case de saisie de la ligne `i` (bornée)
        et sélectionne son contenu pour réécriture immédiate."""
        if 0 <= i < len(self._entries_order):
            e = self._entries_order[i]
            e.focus_set()
            e.select_range(0, "end")
        return "break"

    # --- Refresh ------------------------------------------------------

    def refresh(self) -> None:
        """Recharge la grille depuis le brin courant. Suspend la synchro
        pour ne pas re-muter le modèle pendant qu'on écrit les vars."""
        b = self._host._current_brin()
        # Écho du brin courant (cépée seulement → label non vide).
        label = b.label if b else ""
        if label:
            self._brin_title.configure(text=_("▸ Saisie du brin {label}").format(label=label))
            self._brin_title.pack(anchor="w", pady=(0, 6),
                                  before=self._intro)
        else:
            self._brin_title.pack_forget()
        by_grade: Dict[int, Contrefort] = {}
        if b:
            for cf in b.contreforts:
                by_grade[cf.grade_centre] = cf
        self._suspend = True
        try:
            for g, row in self._rows.items():
                c: Optional[Contrefort] = by_grade.get(g)
                if c is None:
                    row["long"].set("")
                    row["larg"].set("")
                    row["com"].set("")
                    row["combo"].configure(state="disabled")
                    row["com_entry"].configure(state="disabled")
                else:
                    row["long"].set(f"{c.longueur_cm:g}")
                    row["larg"].set(str(c.largeur_grades))
                    row["com"].set(c.commentaire)
                    row["combo"].configure(state="readonly")
                    row["com_entry"].configure(state="normal")
        finally:
            self._suspend = False

    # --- Modèle (helpers) ---------------------------------------------

    def _find_contrefort(self, b: Brin, g: int) -> Optional[Contrefort]:
        for c in b.contreforts:
            if c.grade_centre == g:
                return c
        return None

    def _get_or_create_contrefort(self, b: Brin, g: int) -> Contrefort:
        c = self._find_contrefort(b, g)
        if c is not None:
            return c
        c = Contrefort(numero=0, grade_centre=g,
                       largeur_grades=_LARGEUR_DEFAUT, longueur_cm=0.0)
        b.contreforts.append(c)
        b.contreforts.sort(key=lambda x: x.grade_centre)
        b.renumeroter_contreforts()
        return c

    def _remove_contrefort(self, b: Brin, g: int) -> None:
        before = len(b.contreforts)
        b.contreforts[:] = [c for c in b.contreforts if c.grade_centre != g]
        if len(b.contreforts) != before:
            b.renumeroter_contreforts()

    # --- Saisie live --------------------------------------------------

    def _on_long_write(self, g: int) -> None:
        if self._suspend:
            return
        b = self._host._current_brin()
        if not b:
            return
        row = self._rows[g]
        raw = row["long"].get().strip()

        if raw == "":
            self._remove_contrefort(b, g)
            self._suspend = True
            try:
                row["larg"].set("")
                row["com"].set("")
            finally:
                self._suspend = False
            row["combo"].configure(state="disabled")
            row["com_entry"].configure(state="disabled")
            self._host.on_section_changed()
            return

        try:
            longueur = to_float(raw)
        except ValueError:
            return

        c = self._get_or_create_contrefort(b, g)
        c.longueur_cm = max(0.0, longueur)
        self._suspend = True
        try:
            row["larg"].set(str(c.largeur_grades))
            row["com"].set(c.commentaire)
        finally:
            self._suspend = False
        if str(row["combo"].cget("state")) == "disabled":
            row["combo"].configure(state="readonly")
            row["com_entry"].configure(state="normal")
        self._host.on_section_changed()

    def _on_com_write(self, g: int) -> None:
        if self._suspend:
            return
        b = self._host._current_brin()
        if not b:
            return
        c = self._find_contrefort(b, g)
        if c is None:
            return
        c.commentaire = self._rows[g]["com"].get()
        self._host.on_section_changed()

    def _on_focus_in(self, g: int, field: str) -> None:
        # Snapshot pré-édition : empilé sur l'undo seulement si la valeur
        # change réellement d'ici le focus-out (cf. grille de sondages).
        self._undo_snap = self._host.capture_undo_snapshot()
        self._focus_in_value = self._rows[g][field].get()

    def _on_focus_out(self, g: int, field: str) -> None:
        b = self._host._current_brin()
        # Normalise l'affichage de la longueur à la valeur stockée
        # (format `:g`, clamp à 0 fait par le modèle).
        if field == "long" and b is not None:
            c = self._find_contrefort(b, g)
            if c is not None:
                self._suspend = True
                try:
                    self._rows[g]["long"].set(f"{c.longueur_cm:g}")
                finally:
                    self._suspend = False
        cur = self._rows[g][field].get()
        if self._undo_snap is not None and cur != self._focus_in_value:
            self._host.push_undo_snapshot(self._undo_snap)
        self._undo_snap = None

    def _on_larg_changed(self, g: int) -> None:
        b = self._host._current_brin()
        if not b:
            return
        c = self._find_contrefort(b, g)
        if c is None:
            # Pas de contrefort sur cette direction : la largeur n'a pas
            # de sens, on revient à la valeur neutre.
            self._suspend = True
            try:
                self._rows[g]["larg"].set("")
            finally:
                self._suspend = False
            return
        try:
            new = int(self._rows[g]["larg"].get())
        except ValueError:
            return
        if new == c.largeur_grades:
            return
        self._host.push_undo()
        c.largeur_grades = new
        self._host.on_section_changed()

    # --- Détail (dialogue) --------------------------------------------

    def _open_dialog(self, g: int) -> str:
        """Double-clic sur une ligne : ouvre `edit_contrefort` pour le
        détail (largeur en cm sur l'écorce). Crée le contrefort si la
        direction est encore vide."""
        b = self._host._current_brin()
        if not b:
            return "break"
        c = self._find_contrefort(b, g)
        created = c is None
        if c is None:
            c = Contrefort(numero=len(b.contreforts) + 1, grade_centre=g,
                           largeur_grades=_LARGEUR_DEFAUT, longueur_cm=10.0)
        snap = self._host.capture_undo_snapshot()
        if edit_contrefort(self, b, c):
            self._host.push_undo_snapshot(snap)
            if created:
                b.contreforts.append(c)
            b.contreforts.sort(key=lambda x: x.grade_centre)
            b.renumeroter_contreforts()
            self.refresh()
            self._host.on_section_changed()
        return "break"
