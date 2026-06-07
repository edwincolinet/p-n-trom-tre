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
from typing import Any, Dict, List, Optional, Protocol, Tuple

from aide_repliable import AideRepliable
from bareme import PORTS_ARBRE
from dialogs import ask_forme_tronc, to_float, validate_numeric
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
        # Groupes thématiques (LabelFrame) pour clarifier les unités :
        # un opérateur qui voit « Hauteur (m) » et « Rayon (cm) » côte à
        # côte peut se tromper d'ordre de grandeur. Les regrouper par
        # objet (Arbre / Tronc / Sondage) rend l'unité évidente.
        # Schéma : Arbre (n°, essence, hauteur en m, port) ; Tronc
        # (diam, rayon, écorce) ; Sondage (mèche, hauteur sondage) ;
        # Notes (commentaire libre).
        Row = Tuple[str, tk.StringVar, Optional[List[str]]]
        groupes: List[Tuple[str, List[Row]]] = [
            ("Arbre", [
                ("N° arbre",                  self.var_num, None),
                ("Essence",                   self.var_essence, None),
                ("Hauteur de l'arbre (m)",    self.var_h_arb, None),
                ("Port de l'arbre",           self.var_port, list(PORTS_ARBRE)),
            ]),
            ("Tronc", [
                ("Diamètre sous écorce (cm)", self.var_diam, None),
                ("Rayon du tronc (cm)",       self.var_rayon, None),
                ("Épaisseur de l'écorce (cm)", self.var_ep_ecorce, None),
            ]),
            ("Sondage", [
                ("Longueur de la mèche (cm)", self.var_meche, None),
                ("Hauteur du sondage (cm)",   self.var_h_s, None),
            ]),
            ("Notes", [
                ("Commentaire",               self.var_comm, None),
            ]),
        ]
        numeric_var_names = {str(self.var_diam), str(self.var_rayon),
                             str(self.var_meche), str(self.var_ep_ecorce),
                             str(self.var_h_s), str(self.var_h_arb)}
        self._tronc_box: Optional[ttk.LabelFrame] = None
        vcmd = (self.register(validate_numeric), "%P")
        for gi, (group_label, rows) in enumerate(groupes):
            box = ttk.LabelFrame(self, text=" " + group_label + " ",
                                  padding=(10, 6, 10, 10))
            box.grid(row=gi, column=0, sticky="we", pady=(0, 8))
            box.columnconfigure(1, weight=1)
            if group_label == "Tronc":
                self._tronc_box = box
            for i, (lbl, var, choices) in enumerate(rows):
                ttk.Label(box, text=lbl, style="Panel.TLabel").grid(
                    row=i, column=0, sticky="w", pady=4, padx=(0, 10))
                if choices:
                    widget: tk.Widget = ttk.Combobox(
                        box, textvariable=var, values=choices,
                        state="readonly", width=28)
                else:
                    widget = ttk.Entry(box, textvariable=var, width=30)
                    if str(var) in numeric_var_names:
                        widget.configure(validate="key",
                                         validatecommand=vcmd)
                widget.grid(row=i, column=1, sticky="we", pady=4)
                self._entry_widgets[str(var)] = widget
                var.trace_add("write", lambda *a: self._sync_to_model())

        for var in (self.var_diam, self.var_rayon):
            w = self._entry_widgets[str(var)]
            w.bind("<FocusIn>", lambda e: self._on_rayon_field_focus_in())
            w.bind("<FocusOut>", lambda e: self._on_rayon_field_focus_out())

        # Éditeur avancé de forme (section ovale) : volontairement hors du
        # formulaire courant pour ne pas alourdir la saisie du cas par
        # défaut (tronc circulaire). Bouton sous les champs du « Tronc ».
        if self._tronc_box is not None:
            self.btn_forme = ttk.Button(
                self._tronc_box, text="Forme du tronc (ovale)…",
                style="Ghost.TButton", command=self._open_forme_editor)
            self.btn_forme.grid(row=99, column=0,
                                columnspan=2, sticky="w", pady=(6, 0))

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

        AideRepliable(
            self,
            "Saisir le diamètre sous écorce calcule le rayon "
            "automatiquement (÷ 2). Le rayon reste modifiable "
            "indépendamment si besoin.",
            "Si vous corrigez le rayon après avoir saisi des sondages, la "
            "PRBS (bois sain) reste inchangée car elle correspond à la "
            "mesure physique du pénétromètre. Le bois altéré est recalculé "
            "automatiquement (= rayon − bois sain).",
            "Tronc ovale : le bouton « Forme du tronc (ovale)… » ouvre un "
            "éditeur dédié (petit axe + orientation du grand axe). Par "
            "défaut la section est circulaire ; en ellipse, « Rayon du "
            "tronc » est le demi-grand axe et le t/R de chaque direction "
            "est rapporté à son rayon local.",
        ).grid(row=len(groupes), column=0, sticky="we", pady=(6, 0))
        self.columnconfigure(0, weight=1)

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
        """Parse un champ numérique. Renvoie None si vide ou invalide.
        Accepte la virgule comme séparateur décimal (format FR)."""
        raw = var.get().strip()
        if not raw:
            self._mark_field(var, True)
            return None
        try:
            val = to_float(raw)
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

    def _open_forme_editor(self) -> None:
        """Ouvre l'éditeur avancé de forme (section ovale) et applique le
        résultat : push undo + `set_forme_ovale` (réaligne le bois altéré
        sur le rayon local, PRBS préservée). Annulation ⟹ aucun effet."""
        a = self._host._current_arbre()
        if not a:
            return
        # Flush d'une édition de rayon en cours avant d'ouvrir l'éditeur,
        # pour que le grand axe affiché soit à jour.
        self._commit_rayon()
        res = ask_forme_tronc(
            self.winfo_toplevel(),
            grand_axe_cm=a.rayon_tronc_cm,
            petit_axe_cm=a.rayon_petit_axe_cm,
            orientation_grade=a.orientation_grade)
        if res is None:
            return
        petit_v, orient_v = res
        if (abs(petit_v - a.rayon_petit_axe_cm) <= 1e-9
                and orient_v == a.orientation_grade):
            return
        self._host.push_undo()
        adjusted = a.set_forme_ovale(petit_v, orient_v)
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
