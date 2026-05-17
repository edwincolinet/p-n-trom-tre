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

import tkinter as tk
from contextlib import contextmanager
from tkinter import ttk
from typing import Optional, Protocol

from bareme import PORTS_ARBRE
from model import Arbre


class _IdentificationHost(Protocol):
    def _current_arbre(self) -> Optional[Arbre]: ...
    def on_identification_changed(self, *, rayon_adjusted: bool) -> None: ...


class IdentificationPane(ttk.Frame):
    """Form Tk autonome : possède ses vars, son build et sa synchro."""

    def __init__(self, master, host: _IdentificationHost, **kw) -> None:
        super().__init__(master, style="Panel.TFrame", padding=12, **kw)
        self._host = host
        # _suspend_sync = True pendant un `load_from_arbre()` ou un
        # ajustement de var_rayon depuis `_sync_to_model` — évite la
        # boucle infinie de trace_add → _sync_to_model → set_var → trace_add.
        self._suspend_sync = False

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
                w = ttk.Combobox(self, textvariable=var, values=choices,
                                  state="readonly", width=30)
            else:
                w = ttk.Entry(self, textvariable=var, width=32)
            w.grid(row=i, column=1, sticky="we", pady=5)
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

    def _sync_to_model(self) -> None:
        if self._suspend_sync:
            return
        a = self._host._current_arbre()
        if not a:
            return

        # Détecter lequel des deux champs Ø / rayon vient d'être modifié
        # pour répercuter automatiquement sur l'autre (sans boucle infinie).
        try:
            new_diam = float(self.var_diam.get() or 0)
        except ValueError:
            new_diam = a.diametre_sous_ecorce_cm
        try:
            new_rayon = float(self.var_rayon.get() or 0)
        except ValueError:
            new_rayon = a.rayon_tronc_cm

        diam_changed = abs(new_diam - a.diametre_sous_ecorce_cm) > 1e-9
        rayon_changed = abs(new_rayon - a.rayon_tronc_cm) > 1e-9

        try:
            a.numero_arbre = self.var_num.get()
            a.essence = self.var_essence.get()
            a.hauteur_sondage_cm = float(self.var_h_s.get() or 0)
            a.hauteur_arbre_m = float(self.var_h_arb.get() or 0)
            a.meche_cm = float(self.var_meche.get() or 0)
            a.epaisseur_ecorce_cm = max(0.0,
                float(self.var_ep_ecorce.get() or 0))
            a.port_arbre = self.var_port.get()
            a.commentaire = self.var_comm.get()

            # Règle de cohérence Ø / rayon :
            # - si l'utilisateur a édité le diamètre, on recalcule le rayon
            # - si l'utilisateur a édité le rayon, on laisse le diamètre tel quel
            #   (cas "j'ai mesuré directement sur le sondage")
            # La règle métier "PRBS préservée, bois altéré recalculé"
            # est portée par `Arbre.set_rayon` (modèle, testée).
            if diam_changed and not rayon_changed:
                a.diametre_sous_ecorce_cm = new_diam
                ajustement = a.set_rayon(new_diam / 2.0)
                with self._suspend_sync_block():
                    self.var_rayon.set(f"{a.rayon_tronc_cm:g}")
            else:
                a.diametre_sous_ecorce_cm = new_diam
                ajustement = a.set_rayon(new_rayon)
        except ValueError:
            return

        self._host.on_identification_changed(rayon_adjusted=ajustement)
