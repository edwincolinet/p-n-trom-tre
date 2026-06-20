"""
Onglet « Dégradations externes » : tableau éditable en place, sans modale.

Contrairement aux sondages et contreforts (domaine fixe de 16 directions,
grille pré-affichée), une dégradation est un **arc** (début → fin) :
nombre variable, non indexé par direction. Le tableau garde donc « une
ligne = une dégradation », mais toutes les cellules s'éditent
directement — combobox de grades pour début/fin, saisie libre pour la
profondeur et le commentaire, bouton ✕ pour supprimer. La modale
(`edit_degradation`) ne sert plus qu'au détail (double-clic sur le n° :
saisie de la largeur en cm).

- **« ＋ Ajouter »** crée la ligne sur le premier arc libre, sans
  dialogue, et pose le focus sur sa profondeur.
- Le **non-chevauchement** est validé à la sélection début/fin : une
  valeur qui créerait un chevauchement est refusée et rétablie
  (`model.degradations_chevauchements`, partagé avec le dialogue).
- La **largeur** (gr + cm) est recalculée en lecture seule.

Contrat host (Protocol structural) :
- `_current_brin()`          : brin (ramet) courant à éditer, ou None.
- `on_section_changed()`     : notifie l'App d'une mutation (dirty +
                               redraw debouncé ; ne re-refresh PAS le
                               tableau, déjà à jour).
- `push_undo()`              : snapshot avant une mutation discrète.
- `capture_undo_snapshot()`  : snapshot de l'état courant (undo live).
- `push_undo_snapshot(snap)` : empile un snapshot pré-édition capturé.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Dict, Optional, Protocol

from aide_repliable import AideRepliable
from diagnostic import FUSION_WARN_TEXT, degradation_ecretee
from dialogs import edit_degradation
from dialogs_shared import (
    ZONE_DEGRADEE_AIDE,
    ZONE_DEGRADEE_CHOICES,
    find_grade_choice,
    grade_choices,
    message_chevauchement,
    parse_grade,
    to_float,
    validate_numeric,
    zone_degradee_label,
    zone_degradee_to_bool,
)
from geometry import GRADES
from i18n import _
from model import Brin, DegradationExterne, degradations_chevauchements
from palette import COLOR_ACCENT, COLOR_WARN
from tooltip import Tooltip
from ui_fonts import font as ui_font


class _DegradationsHost(Protocol):
    def _current_brin(self) -> Optional[Brin]: ...
    def on_section_changed(self) -> None: ...
    def push_undo(self) -> None: ...
    def capture_undo_snapshot(self) -> dict: ...
    def push_undo_snapshot(self, snap: dict) -> None: ...


class DegradationsPane(ttk.Frame):
    """Pane Tk autonome : tableau de lignes éditables, une par arc."""

    def __init__(self, master: tk.Misc, host: _DegradationsHost, **kw: Any) -> None:
        super().__init__(master, style="Panel.TFrame", padding=10, **kw)
        self._host = host
        self._suspend = False
        self._undo_snap: Optional[dict] = None
        self._focus_in_value = ""
        self._grade_choices = grade_choices()
        # Vars de chaque ligne, dans l'ordre du tableau (cf. _build_row).
        self._row_refs: list[Dict[str, Any]] = []
        self._build()

    def _build(self) -> None:
        # Écho du brin édité (cépée) — cf. SondagesPane. Vide en mono-caule.
        self._brin_title = ttk.Label(
            self, text="", style="Panel.TLabel", foreground=COLOR_ACCENT,
            font=ui_font("Helvetica", 11, "bold"))

        self._intro = ttk.Label(
            self,
            text=_("Une dégradation externe = arc continu sur l'écorce "
                 "(début → fin) consommant du bois sain en profondeur. "
                 "Éditez directement dans le tableau."),
            style="Muted.TLabel", wraplength=420, justify="left")
        self._intro.pack(anchor="w", pady=(0, 8))

        # Conteneur des lignes, reconstruit par `refresh()` (nombre de
        # dégradations variable).
        self._rows_frame = ttk.Frame(self, style="Panel.TFrame")
        self._rows_frame.pack(fill="both", expand=True)

        # Rappel discret du sens de la colonne « Zone dégradée » : créé non
        # packé, montré par `refresh()` dès qu'une ligne existe (inutile sur
        # une liste vide). Remplace le tooltip de l'ancienne case nue.
        self._lbl_zone_aide = ttk.Label(
            self, text=ZONE_DEGRADEE_AIDE, style="Muted.TLabel",
            wraplength=420, justify="left")

        # Bandeau du garde-fou fusion : créé non packé, montré/caché par
        # `refresh_fusion_warnings` quand une ligne porte un ⚠.
        self._lbl_fusion = ttk.Label(
            self, text=FUSION_WARN_TEXT, style="Panel.TLabel",
            foreground=COLOR_WARN, wraplength=420, justify="left")

        self._toolbar = ttk.Frame(self, style="Panel.TFrame")
        self._toolbar.pack(fill="x", pady=(10, 0))
        ttk.Button(self._toolbar, text=_("＋ Ajouter dégradation"),
                   style="Accent.TButton",
                   command=self._on_add).pack(side="left")

        AideRepliable(
            self,
            "« ＋ Ajouter » crée l'arc sur la première plage libre : "
            "ajustez ensuite début/fin dans la ligne. Les arcs ne "
            "peuvent pas se chevaucher (mitoyens bout-à-bout autorisés). "
            "Double-cliquez le n° pour le détail (largeur en cm).",
            wraplength=420,
        ).pack(anchor="w", pady=(8, 0))

    # --- Refresh ------------------------------------------------------

    def refresh(self) -> None:
        """Reconstruit les lignes du tableau depuis le brin courant."""
        for w in self._rows_frame.winfo_children():
            w.destroy()
        self._row_refs = []
        b = self._host._current_brin()
        # Écho du brin courant (cépée seulement) — avant les retours
        # anticipés : on est peut-être sur le brin b sans dégradation encore.
        label = b.label if b else ""
        if label:
            self._brin_title.configure(text=_("▸ Saisie du brin {label}").format(label=label))
            self._brin_title.pack(anchor="w", pady=(0, 6),
                                  before=self._intro)
        else:
            self._brin_title.pack_forget()
        if not b:
            self._lbl_zone_aide.pack_forget()
            return
        if not b.degradations_externes:
            ttk.Label(self._rows_frame,
                      text=_("Aucune dégradation externe relevée."),
                      style="Muted.TLabel").grid(row=0, column=0,
                                                 sticky="w", padx=6)
            self._lbl_zone_aide.pack_forget()
            return

        heads = [_("N°"), _("Début"), _("Fin"), _("Largeur"), _("Profondeur (cm)"),
                 _("Zone dégradée"), _("Commentaire"), ""]
        for c, h in enumerate(heads):
            ttk.Label(self._rows_frame, text=h, style="Panel.TLabel",
                      font=ui_font("Helvetica", 9, "bold")).grid(
                row=0, column=c, sticky="w", padx=6, pady=(0, 4))

        vcmd = (self.register(validate_numeric), "%P")
        for r, deg in enumerate(b.degradations_externes, start=1):
            self._build_row(r, deg, vcmd)
        self._rows_frame.columnconfigure(6, weight=1)
        self._lbl_zone_aide.pack(anchor="w", pady=(8, 0),
                                 before=self._toolbar)
        self.refresh_fusion_warnings()

    def refresh_fusion_warnings(self) -> None:
        """Garde-fou non bloquant : pose « ⚠ » sur les lignes dont la
        profondeur, cumulée à l'altération centrale, dépasse le rayon sur
        une direction couverte (cf. `diagnostic.degradation_ecretee`).

        Ne touche que des labels en lecture seule : appelable pendant la
        frappe — câblée sur `App._redraw_all` (debouncé) pour suivre
        aussi les éditions faites dans la grille de sondages."""
        b = self._host._current_brin()
        if not b:
            return
        any_ecrete = False
        for row in self._row_refs:
            ecrete = degradation_ecretee(b, row["deg"])
            any_ecrete = any_ecrete or ecrete
            row["warn"].set("⚠" if ecrete else "")
        # Bandeau explicatif au-dessus de la barre d'outils (le ⚠ de
        # ligne ne dit pas quoi corriger).
        if any_ecrete:
            self._lbl_fusion.pack(anchor="w", pady=(8, 0),
                                  before=self._toolbar)
        else:
            self._lbl_fusion.pack_forget()

    def _build_row(self, r: int, deg: DegradationExterne,
                   vcmd: Any) -> None:
        """Construit la ligne `r` (1-based) pour la dégradation `deg`.

        Les callbacks capturent `deg` (l'objet) et leurs vars par
        closure : pas d'indices à invalider quand le tableau est
        reconstruit."""
        f = self._rows_frame
        var_deb = tk.StringVar(
            value=find_grade_choice(self._grade_choices, deg.grade_debut))
        var_fin = tk.StringVar(
            value=find_grade_choice(self._grade_choices, deg.grade_fin))
        var_larg = tk.StringVar()
        var_prof = tk.StringVar(value=f"{deg.profondeur_cm:g}")
        var_ecorce = tk.StringVar(value=zone_degradee_label(deg.comprend_ecorce))
        var_com = tk.StringVar(value=deg.commentaire)
        row: Dict[str, Any] = {"deb": var_deb, "fin": var_fin,
                               "larg": var_larg, "prof": var_prof,
                               "ecorce": var_ecorce,
                               "com": var_com, "warn": tk.StringVar(),
                               "deg": deg}
        # Référence gardée dans l'ordre des lignes : les callbacks
        # passent par les closures, mais `refresh_fusion_warnings` et les
        # tests ont besoin d'un accès indexé (avec l'objet `deg` associé).
        self._row_refs.append(row)
        self._set_largeur_label(row, deg)

        lbl_num = ttk.Label(f, text=str(deg.numero), style="Panel.TLabel",
                            width=3, font=ui_font("Helvetica", 10, "bold"))
        lbl_num.grid(row=r, column=0, sticky="w", padx=6, pady=1)
        lbl_num.bind("<Double-1>", lambda e: self._open_detail(deg))

        cmb_deb = ttk.Combobox(f, textvariable=var_deb,
                               values=self._grade_choices,
                               state="readonly", width=11)
        cmb_deb.grid(row=r, column=1, sticky="w", padx=6, pady=1)
        cmb_fin = ttk.Combobox(f, textvariable=var_fin,
                               values=self._grade_choices,
                               state="readonly", width=11)
        cmb_fin.grid(row=r, column=2, sticky="w", padx=6, pady=1)
        for cmb in (cmb_deb, cmb_fin):
            cmb.bind("<<ComboboxSelected>>",
                     lambda e: self._on_arc_changed(deg, row))

        ttk.Label(f, textvariable=var_larg, style="Muted.TLabel",
                  width=14).grid(row=r, column=3, sticky="w",
                                 padx=6, pady=1)

        ent_prof = ttk.Entry(f, textvariable=var_prof, width=8,
                             validate="key", validatecommand=vcmd,
                             justify="center")
        ent_prof.grid(row=r, column=4, sticky="w", padx=6, pady=1)
        var_prof.trace_add(
            "write", lambda *a: self._on_prof_write(deg, row))

        # « Zone dégradée » : « Écorce + bois » = la dégradation comprend
        # l'écorce (part de la surface extérieure ; l'écorce dégradée n'est
        # pas du bois sain → déduite, défaut). « Bois seul » = commence sous
        # l'écorce (écorce intacte, toute la profondeur est du bois). Le
        # texte explicite remplace l'ancienne case nue, illisible sur le
        # terrain ; le sens détaillé reste dans le rappel sous le tableau.
        cmb_ec = ttk.Combobox(f, textvariable=var_ecorce,
                              values=list(ZONE_DEGRADEE_CHOICES),
                              state="readonly", width=12)
        cmb_ec.grid(row=r, column=5, sticky="w", padx=6, pady=1)
        cmb_ec.bind("<<ComboboxSelected>>",
                    lambda e: self._on_ecorce_toggle(deg, row))

        ent_com = ttk.Entry(f, textvariable=var_com, width=18)
        ent_com.grid(row=r, column=6, sticky="we", padx=6, pady=1)
        var_com.trace_add(
            "write", lambda *a: self._on_com_write(deg, row))

        for w, field in ((ent_prof, "prof"), (ent_com, "com")):
            w.bind("<FocusIn>",
                   lambda e, rw=row, fl=field: self._on_focus_in(rw, fl))
            w.bind("<FocusOut>",
                   lambda e, d=deg, rw=row, fl=field:
                   self._on_focus_out(d, rw, fl))

        ttk.Button(f, text="✕", style="Ghost.TButton", width=2,
                   command=lambda: self._on_del(deg)
                   ).grid(row=r, column=7, sticky="w", padx=(6, 0), pady=1)

        # Garde-fou fusion : « ⚠ » quand cette dégradation, cumulée à
        # l'altération centrale, dépasse le rayon sur une direction
        # qu'elle couvre (PRBS écrêtée à 0). Texte posé/retiré par
        # `refresh_fusion_warnings`.
        lbl_warn = ttk.Label(f, textvariable=row["warn"],
                             style="Panel.TLabel", width=2,
                             foreground=COLOR_WARN,
                             font=ui_font("Helvetica", 10, "bold"))
        lbl_warn.grid(row=r, column=8, sticky="w", pady=1)
        Tooltip(lbl_warn,
                "Profondeur + altération centrale > rayon sur au moins "
                "une direction couverte : les deux zones dégradées se "
                "rejoignent, la PRBS y est écrêtée à 0.\n"
                "Vérifiez la profondeur saisie (ou le bois sain du "
                "sondage concerné).")

    @staticmethod
    def _index_de(b: Brin, deg: DegradationExterne) -> Optional[int]:
        """Index de `deg` dans le brin, par IDENTITÉ (`is`) — les
        dataclasses ont un `__eq__` structurel : deux arcs aux champs
        identiques se confondraient avec `in`/`remove`."""
        for i, d in enumerate(b.degradations_externes):
            if d is deg:
                return i
        return None

    def _set_largeur_label(self, row: Dict[str, Any],
                           deg: DegradationExterne) -> None:
        b = self._host._current_brin()
        R = b.rayon_tronc_cm if b else 0.0
        txt = f"{deg.largeur_grades()} gr"
        if R > 0:
            txt += f" · {deg.largeur_cm(R):.1f} cm"
        row["larg"].set(txt)

    # --- Saisie live --------------------------------------------------

    def _on_arc_changed(self, deg: DegradationExterne,
                        row: Dict[str, Any]) -> None:
        """Début ou fin modifié : valide le non-chevauchement, applique
        ou rétablit."""
        if self._suspend:
            return
        b = self._host._current_brin()
        if not b or self._index_de(b, deg) is None:
            return
        new_debut = parse_grade(row["deb"].get())
        new_fin = parse_grade(row["fin"].get())
        if new_debut == deg.grade_debut and new_fin == deg.grade_fin:
            return
        conflits = degradations_chevauchements(
            b.degradations_externes, deg, new_debut, new_fin)
        if conflits:
            # Rétablit les valeurs du modèle avant d'avertir : la ligne
            # reste toujours cohérente avec l'état réel.
            self._suspend = True
            try:
                row["deb"].set(find_grade_choice(self._grade_choices,
                                                 deg.grade_debut))
                row["fin"].set(find_grade_choice(self._grade_choices,
                                                 deg.grade_fin))
            finally:
                self._suspend = False
            other, shared = conflits[0]
            messagebox.showwarning("Chevauchement de dégradations",
                                   message_chevauchement(other, shared),
                                   parent=self)
            return
        self._host.push_undo()
        deg.grade_debut = new_debut
        deg.grade_fin = new_fin
        self._set_largeur_label(row, deg)
        self._host.on_section_changed()

    def _on_prof_write(self, deg: DegradationExterne,
                       row: Dict[str, Any]) -> None:
        if self._suspend:
            return
        b = self._host._current_brin()
        if not b or self._index_de(b, deg) is None:
            return
        try:
            prof = to_float(row["prof"].get())
        except ValueError:
            # Saisie incomplète (vide, ",") : on attend la suite — la
            # ligne existe indépendamment de sa profondeur, contrairement
            # à la grille de sondages où vider la case supprime.
            return
        deg.profondeur_cm = max(0.0, prof)
        self._host.on_section_changed()

    def _on_ecorce_toggle(self, deg: DegradationExterne,
                          row: Dict[str, Any]) -> None:
        """Change la zone dégradée (« Écorce + bois » ↔ « Bois seul » =
        `comprend_ecorce`). Mutation discrète → undo immédiat, comme le
        début/fin de l'arc. Change aussi le dessin (rayon de départ de la
        zone dégradée)."""
        if self._suspend:
            return
        b = self._host._current_brin()
        if not b or self._index_de(b, deg) is None:
            return
        new_val = zone_degradee_to_bool(row["ecorce"].get())
        if new_val == deg.comprend_ecorce:
            return
        self._host.push_undo()
        deg.comprend_ecorce = new_val
        self._host.on_section_changed()

    def _on_com_write(self, deg: DegradationExterne,
                      row: Dict[str, Any]) -> None:
        if self._suspend:
            return
        b = self._host._current_brin()
        if not b or self._index_de(b, deg) is None:
            return
        deg.commentaire = row["com"].get()
        self._host.on_section_changed()

    def _on_focus_in(self, row: Dict[str, Any], field: str) -> None:
        # Snapshot pré-édition : empilé sur l'undo seulement si la valeur
        # change réellement d'ici le focus-out (cf. grille de sondages).
        self._undo_snap = self._host.capture_undo_snapshot()
        self._focus_in_value = row[field].get()

    def _on_focus_out(self, deg: DegradationExterne,
                      row: Dict[str, Any], field: str) -> None:
        b = self._host._current_brin()
        # Normalise l'affichage de la profondeur à la valeur stockée
        # (format `:g`, clamp à 0 fait par le modèle).
        if (field == "prof" and b is not None
                and self._index_de(b, deg) is not None):
            self._suspend = True
            try:
                row["prof"].set(f"{deg.profondeur_cm:g}")
            finally:
                self._suspend = False
        cur = row[field].get()
        if self._undo_snap is not None and cur != self._focus_in_value:
            self._host.push_undo_snapshot(self._undo_snap)
        self._undo_snap = None

    # --- Actions ------------------------------------------------------

    def _arc_libre(self, b: Brin) -> Optional[tuple[int, int]]:
        """Premier arc (début, fin) ne chevauchant aucune dégradation
        existante : largeur 50 gr d'abord, repli à 25 gr."""
        for largeur in (50, 25):
            for g in GRADES:
                fin = (g + largeur) % 400
                if not degradations_chevauchements(
                        b.degradations_externes, None, g, fin):
                    return g, fin
        return None

    def _on_add(self) -> None:
        b = self._host._current_brin()
        if not b:
            return
        arc = self._arc_libre(b)
        if arc is None:
            messagebox.showwarning(
                "Plus de place",
                "Toutes les directions sont déjà couvertes par des "
                "dégradations : supprimez ou rétrécissez un arc "
                "existant.", parent=self)
            return
        self._host.push_undo()
        deg = DegradationExterne(
            numero=len(b.degradations_externes) + 1,
            grade_debut=arc[0], grade_fin=arc[1], profondeur_cm=2.0)
        b.degradations_externes.append(deg)
        b.renumeroter_degradations()
        self.refresh()
        self._host.on_section_changed()
        # Focus sur la profondeur de la nouvelle ligne (la valeur à
        # mesurer), prête à réécrire.
        entries = [w for w in self._rows_frame.grid_slaves(
            row=len(b.degradations_externes), column=4)
            if isinstance(w, ttk.Entry)]
        if entries:
            entries[0].focus_set()
            entries[0].select_range(0, "end")

    def _on_del(self, deg: DegradationExterne) -> None:
        b = self._host._current_brin()
        if not b:
            return
        idx = self._index_de(b, deg)
        if idx is None:
            return
        self._host.push_undo()
        del b.degradations_externes[idx]
        b.renumeroter_degradations()
        self.refresh()
        self._host.on_section_changed()

    # --- Détail (dialogue) --------------------------------------------

    def _open_detail(self, deg: DegradationExterne) -> None:
        """Double-clic sur le n° : ouvre `edit_degradation` pour le
        détail (largeur en cm sur l'écorce)."""
        b = self._host._current_brin()
        if not b or self._index_de(b, deg) is None:
            return
        snap = self._host.capture_undo_snapshot()
        if edit_degradation(self.winfo_toplevel(), b, deg):
            self._host.push_undo_snapshot(snap)
            self.refresh()
            self._host.on_section_changed()
