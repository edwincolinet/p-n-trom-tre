"""
Onglet « Sondages » : grille des 16 directions, saisie directe sans modale.

Refonte ergonomique : le geste dominant sur le terrain est de saisir les
16 PRBS d'un arbre à la chaîne. Plutôt qu'une boîte de dialogue par
mesure, l'onglet présente les **16 directions pré-affichées** (rose des
vents N → NNO) ; l'opérateur ne fait que taper la valeur de bois sain et
descendre d'une ligne (Entrée / flèche bas).

Sémantique de la grille :
- **Case « Bois sain » vide** = direction non sondée (aucun `Sondage`).
- **Une valeur saisie** (y compris 0) = sondage existant à cette direction.
- **Effacer la valeur** supprime le `Sondage` de cette direction.
- **Altéré** = rayon − bois sain (lecture seule, recalculé en direct).
- **Compartimentation** = liste déroulante, active uniquement quand un
  sondage existe sur la ligne.
- **Double-clic sur la direction/grade** ouvre le dialogue détaillé
  (`edit_sondage`) pour le commentaire ou changer la direction.

L'unicité « un seul sondage par direction » est garantie par construction
(une ligne par grade), donc plus aucune validation d'unicité nécessaire.

Contrat host (Protocol structural) :
- `_current_brin()`             : brin (ramet) courant à éditer, ou None.
                                  Mono-caule = `brins[0]` (inchangé) ;
                                  cépée = le brin du sélecteur.
- `on_sondages_changed()`       : notifie l'App d'une mutation (marque
                                  dirty + redraw debouncé + maj diag/état).
- `push_undo()`                 : snapshot avant une mutation discrète.
- `capture_undo_snapshot()`     : renvoie un snapshot de l'état courant
                                  (utilisé pour l'undo des éditions live).
- `push_undo_snapshot(snap)`    : empile un snapshot pré-édition capturé.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Dict, Optional, Protocol

from aide_repliable import AideRepliable
from dialogs import edit_sondage, to_float, validate_numeric
from geometry import GRADES
from model import Brin, Sondage
from ui_fonts import font as ui_font

# Rose des vents 16 directions — libellé affiché par ligne de la grille.
# (DIRECTION_LABELS ne nomme que les 8 cardinales/intercardinales ; ici on
#  complète les 8 intermédiaires pour que chaque ligne se lise seule.)
_WIND_LABELS: Dict[int, str] = {
    0: "N", 25: "N-NE", 50: "NE", 75: "NE-E",
    100: "E", 125: "E-SE", 150: "SE", 175: "SE-S",
    200: "S", 225: "S-SO", 250: "SO", 275: "SO-O",
    300: "O", 325: "O-NO", 350: "NO", 375: "NO-N",
}
_COMPART_VALUES = ["non renseignée", "active", "absente"]


class _SondagesHost(Protocol):
    def _current_brin(self) -> Optional[Brin]: ...
    def on_sondages_changed(self) -> None: ...
    def push_undo(self) -> None: ...
    def capture_undo_snapshot(self) -> dict: ...
    def push_undo_snapshot(self, snap: dict) -> None: ...


class SondagesPane(ttk.Frame):
    """Pane Tk autonome : grille fixe de 16 directions, saisie directe."""

    def __init__(self, master: tk.Misc, host: _SondagesHost, **kw: Any) -> None:
        super().__init__(master, style="Panel.TFrame", padding=10, **kw)
        self._host = host
        self._suspend = False
        self._undo_snap: Optional[dict] = None
        self._focus_in_value = ""
        # Par grade : {"sain", "alt", "comp": StringVar ; "entry", "combo"}.
        self._rows: Dict[int, Dict[str, Any]] = {}
        self._entries_order: list[ttk.Entry] = []
        self._build()

    def _build(self) -> None:
        ttk.Label(
            self,
            text="Tapez la PRBS (bois sain) de chaque direction, puis "
                 "Entrée (ou ↓) pour descendre. Le dessin et le diagnostic "
                 "se recalculent en direct.",
            style="Muted.TLabel", wraplength=420, justify="left"
        ).pack(anchor="w", pady=(0, 8))

        grid = ttk.Frame(self, style="Panel.TFrame")
        grid.pack(fill="both", expand=True)

        heads = ["Direction", "Grade", "Bois sain (cm)", "Altéré (cm)",
                 "Compart."]
        for c, h in enumerate(heads):
            ttk.Label(grid, text=h, style="Panel.TLabel",
                      font=ui_font("Helvetica", 9, "bold")).grid(
                row=0, column=c, sticky="w", padx=6, pady=(0, 4))

        vcmd = (self.register(validate_numeric), "%P")
        for r, g in enumerate(GRADES, start=1):
            var_sain = tk.StringVar()
            var_alt = tk.StringVar(value="—")
            var_comp = tk.StringVar(value="non renseignée")

            lbl_dir = ttk.Label(grid, text=_WIND_LABELS[g],
                                style="Panel.TLabel", width=6,
                                font=ui_font("Helvetica", 10, "bold"))
            lbl_dir.grid(row=r, column=0, sticky="w", padx=6, pady=1)
            lbl_gr = ttk.Label(grid, text=f"{g} gr", style="Muted.TLabel",
                               width=7)
            lbl_gr.grid(row=r, column=1, sticky="w", padx=6, pady=1)

            ent = ttk.Entry(grid, textvariable=var_sain, width=10,
                            validate="key", validatecommand=vcmd,
                            justify="center")
            ent.grid(row=r, column=2, sticky="w", padx=6, pady=1)

            ttk.Label(grid, textvariable=var_alt, style="Panel.TLabel",
                      width=9, anchor="center").grid(
                row=r, column=3, sticky="w", padx=6, pady=1)

            cmb = ttk.Combobox(grid, textvariable=var_comp,
                               values=_COMPART_VALUES, state="disabled",
                               width=14)
            cmb.grid(row=r, column=4, sticky="w", padx=6, pady=1)

            self._rows[g] = {"sain": var_sain, "alt": var_alt,
                             "comp": var_comp, "entry": ent, "combo": cmb}
            self._entries_order.append(ent)

            var_sain.trace_add(
                "write", lambda *a, gr=g: self._on_sain_write(gr))
            ent.bind("<FocusIn>", lambda e, gr=g: self._on_focus_in(gr))
            ent.bind("<FocusOut>", lambda e, gr=g: self._on_focus_out(gr))
            # Navigation verticale rapide (saisie au kilomètre).
            row_idx = r - 1
            ent.bind("<Return>", lambda e, i=row_idx: self._focus_entry(i + 1))
            ent.bind("<Down>", lambda e, i=row_idx: self._focus_entry(i + 1))
            ent.bind("<Up>", lambda e, i=row_idx: self._focus_entry(i - 1))
            cmb.bind("<<ComboboxSelected>>",
                     lambda e, gr=g: self._on_comp_changed(gr))
            # Détail (commentaire, redirection) via double-clic sur les
            # libellés non éditables — l'Entry garde le double-clic natif
            # (sélection de mot).
            for w in (lbl_dir, lbl_gr):
                w.bind("<Double-1>", lambda e, gr=g: self._open_dialog(gr))

        AideRepliable(
            self,
            "Laissez vide une direction non sondée. Effacer une valeur "
            "supprime le sondage. Double-cliquez la direction pour le "
            "détail (commentaire, redirection).",
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
        """Recharge la grille depuis l'arbre courant. Suspend la synchro
        pour ne pas re-muter le modèle pendant qu'on écrit les vars."""
        b = self._host._current_brin()
        R = b.rayon_tronc_cm if b else 0.0
        by_grade: Dict[int, Sondage] = {}
        if b:
            for sd in b.sondages:
                by_grade[sd.grade] = sd
        self._suspend = True
        try:
            for g, row in self._rows.items():
                s: Optional[Sondage] = by_grade.get(g)
                if s is None:
                    row["sain"].set("")
                    row["alt"].set("—")
                    row["comp"].set("non renseignée")
                    row["combo"].configure(state="disabled")
                else:
                    row["sain"].set(f"{s.bois_sain_cm:g}")
                    row["alt"].set(f"{s.bois_altere_cm:g}" if R > 0 else "—")
                    comp = (s.compartimentation
                            if s.compartimentation in _COMPART_VALUES
                            else "non renseignée")
                    row["comp"].set(comp)
                    row["combo"].configure(state="readonly")
        finally:
            self._suspend = False

    # --- Modèle (helpers) ---------------------------------------------

    def _find_sondage(self, b: Brin, g: int) -> Optional[Sondage]:
        for s in b.sondages:
            if s.grade == g:
                return s
        return None

    def _get_or_create_sondage(self, b: Brin, g: int) -> Sondage:
        s = self._find_sondage(b, g)
        if s is not None:
            return s
        s = Sondage(numero=0, grade=g, bois_sain_cm=0.0, bois_altere_cm=0.0)
        b.sondages.append(s)
        b.sondages.sort(key=lambda x: x.grade)
        b.renumeroter_sondages()
        return s

    def _remove_sondage(self, b: Brin, g: int) -> None:
        before = len(b.sondages)
        b.sondages[:] = [s for s in b.sondages if s.grade != g]
        if len(b.sondages) != before:
            b.renumeroter_sondages()

    # --- Saisie live --------------------------------------------------

    def _on_sain_write(self, g: int) -> None:
        if self._suspend:
            return
        b = self._host._current_brin()
        if not b:
            return
        row = self._rows[g]
        raw = row["sain"].get().strip()
        R = b.rayon_tronc_cm

        if raw == "":
            self._remove_sondage(b, g)
            row["alt"].set("—")
            row["comp"].set("non renseignée")
            row["combo"].configure(state="disabled")
            self._host.on_sondages_changed()
            return

        try:
            sain = to_float(raw)
        except ValueError:
            return
        sain = max(0.0, min(sain, R)) if R > 0 else max(0.0, sain)

        s = self._get_or_create_sondage(b, g)
        s.bois_sain_cm = sain
        s.bois_altere_cm = max(0.0, R - sain) if R > 0 else 0.0
        row["alt"].set(f"{s.bois_altere_cm:g}" if R > 0 else "—")
        if str(row["combo"].cget("state")) == "disabled":
            row["combo"].configure(state="readonly")
        self._host.on_sondages_changed()

    def _on_focus_in(self, g: int) -> None:
        # Snapshot pré-édition : empilé sur l'undo seulement si la valeur
        # change réellement d'ici le focus-out (évite les undo parasites
        # d'un simple aller-retour de focus).
        self._undo_snap = self._host.capture_undo_snapshot()
        self._focus_in_value = self._rows[g]["sain"].get()

    def _on_focus_out(self, g: int) -> None:
        b = self._host._current_brin()
        # Normalise l'affichage à la valeur réellement stockée (clamp à R,
        # mise au format `:g`) — ex. "99" sur R=20 redevient "20".
        if b is not None:
            s = self._find_sondage(b, g)
            if s is not None:
                self._suspend = True
                try:
                    self._rows[g]["sain"].set(f"{s.bois_sain_cm:g}")
                finally:
                    self._suspend = False
        cur = self._rows[g]["sain"].get()
        if self._undo_snap is not None and cur != self._focus_in_value:
            self._host.push_undo_snapshot(self._undo_snap)
        self._undo_snap = None

    def _on_comp_changed(self, g: int) -> None:
        b = self._host._current_brin()
        if not b:
            return
        s = self._find_sondage(b, g)
        if s is None:
            # Pas de sondage sur cette direction : la compartimentation n'a
            # pas de sens, on revient à la valeur neutre.
            self._suspend = True
            try:
                self._rows[g]["comp"].set("non renseignée")
            finally:
                self._suspend = False
            return
        new = self._rows[g]["comp"].get()
        if new == s.compartimentation:
            return
        self._host.push_undo()
        s.compartimentation = new
        self._host.on_sondages_changed()

    # --- Détail (dialogue) --------------------------------------------

    def _open_dialog(self, g: int) -> str:
        """Double-clic sur une ligne : ouvre `edit_sondage` pour le détail
        (commentaire, redirection vers un autre grade). Crée le sondage si
        la direction est encore vide."""
        b = self._host._current_brin()
        if not b:
            return "break"
        s = self._find_sondage(b, g)
        created = s is None
        if s is None:
            s = Sondage(numero=len(b.sondages) + 1, grade=g,
                        bois_sain_cm=b.rayon_tronc_cm, bois_altere_cm=0.0)
        snap = self._host.capture_undo_snapshot()
        if edit_sondage(self, b, s):
            self._host.push_undo_snapshot(snap)
            if created:
                b.sondages.append(s)
            b.sondages.sort(key=lambda x: x.grade)
            b.renumeroter_sondages()
            self.refresh()
            self._host.on_sondages_changed()
        return "break"
