"""
Onglet « Identification » : formulaire des caractéristiques de l'arbre.

Encapsule les 10 `StringVar`, le formulaire ttk, les notes d'aide, la
règle de cohérence Ø ↔ Rayon, et la synchro UI ↔ modèle. Auparavant
ces éléments étaient répartis dans `App._build_center`,
`App._sync_ui_to_model` et `App._load_arbre_to_ui`.

Contrat host (Protocol structural) :
- `_current_arbre()` : renvoie l'arbre courant (ou None).
- `on_identification_changed(rayon_adjusted)` : notifie l'App qu'un
  champ a changé. Quand `rayon_adjusted=True`, l'App doit aussi
  rafraîchir les tables Sondages/Dégradations/Contreforts (le rayon
  a entraîné un recalcul du bois altéré et de la profondeur des
  dégradations externes — cf. `Arbre.set_rayon`).

La règle « PRBS préservée, bois altéré recalculé » est portée par
`Arbre.set_rayon` (côté modèle, testée) — le pane se contente
d'appeler ce mutateur et de lire son retour.
"""

from __future__ import annotations

import logging
import tkinter as tk
from contextlib import contextmanager
from tkinter import ttk
from typing import Any, Dict, Optional, Protocol

from bareme import PORTS_ARBRE
from model import Arbre

_log = logging.getLogger("penetrometre")


class _IdentificationHost(Protocol):
    def _current_arbre(self) -> Optional[Arbre]: ...
    def on_identification_changed(self, *, rayon_adjusted: bool) -> None: ...
    def push_undo(self) -> None: ...


class IdentificationPane(ttk.Frame):
    """Form Tk autonome : possède ses vars, son build et sa synchro."""

    _COLOR_FIELD_OK = "#FFFFFF"
    _COLOR_FIELD_ERR = "#FDDEDE"

    def __init__(self, master: tk.Misc, host: _IdentificationHost, **kw: Any) -> None:
        super().__init__(master, style="Panel.TFrame", padding=12, **kw)
        self._host = host
        self._suspend_sync = False
        self._entry_widgets: Dict[str, tk.Widget] = {}
        self._rayon_at_focus_in: Optional[float] = None
        self._diam_at_focus_in: Optional[float] = None
        self._numeric_snapshots: Dict[str, str] = {}

        self.var_num = tk.StringVar()
        self.var_essence = tk.StringVar()
        self.var_h_s = tk.StringVar()
        self.var_diam = tk.StringVar()
        self.var_h_arb = tk.StringVar()
        self.var_port = tk.StringVar(value="libre")
        self.var_rayon = tk.StringVar(value="20")
        self.var_meche = tk.StringVar(value="40")
        self.var_ep_ecorce = tk.StringVar(value="0")
        self.var_comm = tk.StringVar()

        self._build()

    def _build(self) -> None:
        rows = [
            ("N° arbre",                  self.var_num, None),
            ("Essence",                   self.var_essence, None),
            ("Diamètre sous écorce (cm)", self.var_diam, None),
            ("Rayon du tronc (cm)",       self.var_rayon, None),
            ("Longueur de la mèche (cm)", self.var_meche, None),
            ("Épaisseur de l'écorce (cm)", self.var_ep_ecorce, None),
            ("Hauteur du sondage (cm)",   self.var_h_s, None),
            ("Hauteur de l'arbre (m)",    self.var_h_arb, None),
            ("Port de l'arbre",           self.var_port, list(PORTS_ARBRE)),
            ("Commentaire",               self.var_comm, None),
        ]
        for i, (lbl, var, choices) in enumerate(rows):
            ttk.Label(self, text=lbl, style="Panel.TLabel").grid(
                row=i, column=0, sticky="w", pady=5, padx=(0, 10))
            if choices:
                widget: tk.Widget = ttk.Combobox(
                    self, textvariable=var, values=choices,
                    state="readonly", width=30)
            else:
                widget = ttk.Entry(self, textvariable=var, width=32)
            widget.grid(row=i, column=1, sticky="we", pady=5)
            self._entry_widgets[str(var)] = widget
            var.trace_add("write", lambda *a: self._sync_to_model())

        for var in (self.var_diam, self.var_rayon):
            w = self._entry_widgets[str(var)]
            w.bind("<FocusIn>", lambda e: self._on_rayon_field_focus_in())
            w.bind("<FocusOut>", lambda e: self._on_rayon_field_focus_out())

        for var in (self.var_meche, self.var_ep_ecorce,
                    self.var_h_s, self.var_h_arb):
            key = str(var)
            w = self._entry_widgets[key]
            w.bind("<FocusIn>", lambda e, k=key, v=var: self._numeric_snapshots.__setitem__(k, v.get()))
            w.bind("<FocusOut>", lambda e, k=key, v=var: self._revert_if_invalid(v, k))

        num_key = str(self.var_num)
        num_w = self._entry_widgets[num_key]
        num_w.bind("<FocusIn>", lambda e: self._numeric_snapshots.__setitem__(num_key, self.var_num.get()))
        num_w.bind("<FocusOut>", lambda e: self._revert_num_if_invalid())

        ttk.Label(self,
                  text="ⓘ Saisir le diamètre sous écorce calcule le rayon "
                       "automatiquement (÷ 2). Le rayon reste modifiable "
                       "indépendamment si besoin.",
                  style="Muted.TLabel", wraplength=380, justify="left"
                  ).grid(row=len(rows), column=0, columnspan=2,
                         sticky="we", pady=(10, 0))
        ttk.Label(self,
                  text="ⓘ Si vous corrigez le rayon après avoir saisi des "
                       "sondages, la PRBS (bois sain) reste inchangée car "
                       "elle correspond à la mesure physique du "
                       "pénétromètre. Le bois altéré est recalculé "
                       "automatiquement (= rayon − bois sain).",
                  style="Muted.TLabel", wraplength=380, justify="left"
                  ).grid(row=len(rows)+1, column=0, columnspan=2,
                         sticky="we", pady=(6, 0))
        self.columnconfigure(1, weight=1)

    @contextmanager
    def _suspend_sync_block(self):
        prev = self._suspend_sync
        self._suspend_sync = True
        try:
            yield
        finally:
            self._suspend_sync = prev

    def load_from_arbre(self) -> None:
        """Recharge les vars depuis l'arbre courant du host (avec
        synchro suspendue pour ne pas boucler)."""
        self._commit_rayon()
        a = self._host._current_arbre()
        if not a:
            return
        with self._suspend_sync_block():
            self.var_num.set(a.numero_arbre)
            self.var_essence.set(a.essence)
            self.var_rayon.set(f"{a.rayon_tronc_cm:g}")
            self.var_h_s.set(f"{a.hauteur_sondage_cm:g}"
                              if a.hauteur_sondage_cm else "")
            self.var_diam.set(f"{a.diametre_sous_ecorce_cm:g}"
                               if a.diametre_sous_ecorce_cm else "")
            self.var_h_arb.set(f"{a.hauteur_arbre_m:g}"
                                if a.hauteur_arbre_m else "")
            self.var_meche.set(f"{a.meche_cm:g}" if a.meche_cm else "40")
            self.var_ep_ecorce.set(f"{a.epaisseur_ecorce_cm:g}"
                                    if a.epaisseur_ecorce_cm else "0")
            self.var_port.set(a.port_arbre)
            self.var_comm.set(a.commentaire)

    def _mark_field(self, var: tk.StringVar, valid: bool) -> None:
        w = self._entry_widgets.get(str(var))
        if w and isinstance(w, ttk.Entry):
            style_name = "TEntry" if valid else "Error.TEntry"
            try:
                s = ttk.Style(w)
                if not s.lookup("Error.TEntry", "fieldbackground"):
                    s.configure("Error.TEntry",
                                fieldbackground=self._COLOR_FIELD_ERR)
                w.configure(style=style_name)
            except tk.TclError:
                pass

    def _revert_if_invalid(self, var: tk.StringVar, key: str) -> None:
        """Au focus-out d'un champ numérique secondaire, revert à la
        valeur d'avant le focus-in si le contenu est non numérique."""
        raw = var.get().strip()
        if raw and self._parse_float(var) is None:
            prev = self._numeric_snapshots.get(key, "")
            with self._suspend_sync_block():
                var.set(prev)
            self._mark_field(var, True)

    def _revert_num_if_invalid(self) -> None:
        """Au focus-out du N° arbre, revert si la valeur ne contient
        aucun chiffre (accepte '1', '42', '1 bis' mais rejette 'ouyg')."""
        raw = self.var_num.get().strip()
        if raw and not any(c.isdigit() for c in raw):
            key = str(self.var_num)
            prev = self._numeric_snapshots.get(key, "1")
            with self._suspend_sync_block():
                self.var_num.set(prev)
            self._mark_field(self.var_num, True)

    def _parse_float(self, var: tk.StringVar) -> Optional[float]:
        """Parse un champ numérique. Renvoie None si vide ou invalide."""
        raw = var.get().strip()
        if not raw:
            self._mark_field(var, True)
            return None
        try:
            val = float(raw)
            self._mark_field(var, True)
            return val
        except ValueError:
            self._mark_field(var, False)
            return None

    def _on_rayon_field_focus_in(self) -> None:
        a = self._host._current_arbre()
        if a:
            self._rayon_at_focus_in = a.rayon_tronc_cm
            self._diam_at_focus_in = a.diametre_sous_ecorce_cm

    def _on_rayon_field_focus_out(self) -> None:
        self._commit_rayon()

    def _commit_rayon(self) -> None:
        """Finalise un changement de rayon : push undo + set_rayon
        (ajustement des sondages). Appelé sur focus-out des champs
        Diamètre/Rayon et avant un changement d'arbre.

        Si le champ est invalide au moment du focus-out (texte non
        numérique, champ vide), on REVERT le rayon et le diamètre à
        leur valeur d'avant l'édition — les valeurs intermédiaires
        (ex. "8" en route vers "80") ne doivent pas être commitées."""
        a = self._host._current_arbre()
        if not a or self._rayon_at_focus_in is None:
            return
        old_R = self._rayon_at_focus_in
        old_D = self._diam_at_focus_in
        self._rayon_at_focus_in = None
        self._diam_at_focus_in = None

        cur_diam = self._parse_float(self.var_diam)
        cur_rayon = self._parse_float(self.var_rayon)
        if cur_diam is None or cur_rayon is None:
            a.rayon_tronc_cm = old_R
            a.diametre_sous_ecorce_cm = old_D if old_D is not None else old_R * 2
            with self._suspend_sync_block():
                self.var_rayon.set(f"{a.rayon_tronc_cm:g}")
                self.var_diam.set(f"{a.diametre_sous_ecorce_cm:g}")
            self._host.on_identification_changed(rayon_adjusted=False)
            return

        new_R = a.rayon_tronc_cm
        if abs(new_R - old_R) <= 1e-9:
            return
        a.rayon_tronc_cm = old_R
        self._host.push_undo()
        adjusted = a.set_rayon(new_R)
        self._host.on_identification_changed(rayon_adjusted=adjusted)

    def _sync_to_model(self) -> None:
        if self._suspend_sync:
            return
        a = self._host._current_arbre()
        if not a:
            return

        try:
            a.numero_arbre = self.var_num.get()
            a.essence = self.var_essence.get()
            a.port_arbre = self.var_port.get()
            a.commentaire = self.var_comm.get()

            h_s = self._parse_float(self.var_h_s)
            h_arb = self._parse_float(self.var_h_arb)
            meche = self._parse_float(self.var_meche)
            ep = self._parse_float(self.var_ep_ecorce)

            if h_s is not None:
                a.hauteur_sondage_cm = h_s
            if h_arb is not None:
                a.hauteur_arbre_m = h_arb
            if meche is not None:
                a.meche_cm = meche
            if ep is not None:
                a.epaisseur_ecorce_cm = max(0.0, ep)

            new_diam = self._parse_float(self.var_diam)
            new_rayon = self._parse_float(self.var_rayon)

            if new_diam is not None and new_rayon is not None:
                diam_changed = abs(new_diam - a.diametre_sous_ecorce_cm) > 1e-9
                rayon_changed = abs(new_rayon - a.rayon_tronc_cm) > 1e-9
                a.diametre_sous_ecorce_cm = new_diam
                if diam_changed and not rayon_changed:
                    a.rayon_tronc_cm = max(0.0, new_diam / 2.0)
                    with self._suspend_sync_block():
                        self.var_rayon.set(f"{a.rayon_tronc_cm:g}")
                elif rayon_changed and not diam_changed:
                    a.rayon_tronc_cm = max(0.0, new_rayon)
                    a.diametre_sous_ecorce_cm = new_rayon * 2.0
                    with self._suspend_sync_block():
                        self.var_diam.set(f"{a.diametre_sous_ecorce_cm:g}")
                else:
                    a.rayon_tronc_cm = max(0.0, new_rayon)
            elif new_diam is not None:
                a.diametre_sous_ecorce_cm = new_diam
            elif new_rayon is not None:
                a.rayon_tronc_cm = max(0.0, new_rayon)
        except Exception:
            _log.exception("Erreur inattendue dans _sync_to_model")
            return

        self._host.on_identification_changed(rayon_adjusted=False)
