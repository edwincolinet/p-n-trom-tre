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


class IdentificationPane(ttk.Frame):
    """Form Tk autonome : possède ses vars, son build et sa synchro."""

    _COLOR_FIELD_OK = "#FFFFFF"
    _COLOR_FIELD_ERR = "#FDDEDE"

    def __init__(self, master: tk.Misc, host: _IdentificationHost, **kw: Any) -> None:
        super().__init__(master, style="Panel.TFrame", padding=12, **kw)
        self._host = host
        self._suspend_sync = False
        self._entry_widgets: Dict[str, tk.Widget] = {}

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

    def _parse_float(self, var: tk.StringVar) -> Optional[float]:
        """Parse un champ numérique. Renvoie None si invalide."""
        raw = var.get().strip()
        if not raw:
            self._mark_field(var, True)
            return 0.0
        try:
            val = float(raw)
            self._mark_field(var, True)
            return val
        except ValueError:
            self._mark_field(var, False)
            return None

    def _sync_to_model(self) -> None:
        if self._suspend_sync:
            return
        a = self._host._current_arbre()
        if not a:
            return

        try:
            new_diam = self._parse_float(self.var_diam)
            new_rayon = self._parse_float(self.var_rayon)

            if new_diam is None or new_rayon is None:
                return

            diam_changed = abs(new_diam - a.diametre_sous_ecorce_cm) > 1e-9
            rayon_changed = abs(new_rayon - a.rayon_tronc_cm) > 1e-9

            a.numero_arbre = self.var_num.get()
            a.essence = self.var_essence.get()

            h_s = self._parse_float(self.var_h_s)
            h_arb = self._parse_float(self.var_h_arb)
            meche = self._parse_float(self.var_meche)
            ep = self._parse_float(self.var_ep_ecorce)

            if any(v is None for v in (h_s, h_arb, meche, ep)):
                return

            assert h_s is not None and h_arb is not None
            assert meche is not None and ep is not None
            a.hauteur_sondage_cm = h_s
            a.hauteur_arbre_m = h_arb
            a.meche_cm = meche
            a.epaisseur_ecorce_cm = max(0.0, ep)
            a.port_arbre = self.var_port.get()
            a.commentaire = self.var_comm.get()

            if diam_changed and not rayon_changed:
                a.diametre_sous_ecorce_cm = new_diam
                ajustement = a.set_rayon(new_diam / 2.0)
                with self._suspend_sync_block():
                    self.var_rayon.set(f"{a.rayon_tronc_cm:g}")
            else:
                a.diametre_sous_ecorce_cm = new_diam
                ajustement = a.set_rayon(new_rayon)
        except Exception:
            _log.exception("Erreur inattendue dans _sync_to_model")
            return

        self._host.on_identification_changed(rayon_adjusted=ajustement)
