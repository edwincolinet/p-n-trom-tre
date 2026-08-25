"""Primitives Tk génériques (saisie texte/choix/date, progression) +
helper de modalité partagé.

Module séparé pour éviter que `penetrometre.py` ne reste un fichier
de 2 200+ lignes. Les dialogues d'édition détaillée des objets métier
(Sondage/DégradationExterne/Contrefort) vivent dans `dialogs_saisie.py`,
l'éditeur de disposition d'une cépée dans `dialogs_cepee.py` — extraits
d'ici le 2026-08-25, ce fichier ne gardant que les primitives sans
connaissance du modèle métier (utilisées aussi par les réglages, le
cycle de vie fichier…) et `_make_modal`, point de couplage commun aux
trois modules.

`Section = Union[Arbre, Brin]` reste défini ici (réexporté par
`dialogs_saisie`) : les dialogues d'édition ne lisent que de la
géométrie (`rayon_tronc_cm`) et la liste de mesures concernée —
présentes aussi bien sur un `Arbre` (relais de compat → brins[0]) que
sur un `Brin` natif. Accepter les deux permet d'éditer un brin précis
d'une cépée (le sélecteur de brin de l'Étape 4) sans passer par les
relais brins[0].
"""

from __future__ import annotations

import calendar
import tkinter as tk
from datetime import date
from functools import partial
from tkinter import ttk
from typing import List, Optional, Union

from dialogs_shared import (
    SUIVI_VALIDITES as SUIVI_VALIDITES,  # noqa: PLC0414 — re-exported
)
from dialogs_shared import (
    ZONE_BOIS_SEUL as ZONE_BOIS_SEUL,
)
from dialogs_shared import (
    ZONE_DEGRADEE_AIDE as ZONE_DEGRADEE_AIDE,
)
from dialogs_shared import (
    ZONE_DEGRADEE_CHOICES as ZONE_DEGRADEE_CHOICES,
)
from dialogs_shared import (
    ZONE_ECORCE_BOIS as ZONE_ECORCE_BOIS,
)
from dialogs_shared import (
    annees_entre as annees_entre,
)
from dialogs_shared import (
    find_grade_choice as find_grade_choice,  # noqa: PLC0414 — re-exported (tests)
)
from dialogs_shared import (
    normaliser_date,
    validate_numeric,
)
from dialogs_shared import (
    to_float as to_float,
)
from i18n import _
from model import Arbre, Brin
from palette import COLOR_MUTED, COLOR_PANEL
from ui_fonts import font as ui_font

Section = Union[Arbre, Brin]


def _numeric_entry(parent: tk.Misc, textvariable: tk.StringVar,
                    width: int) -> ttk.Entry:
    """Crée une ttk.Entry qui n'accepte à la frappe que des chiffres
    et un seul séparateur décimal."""
    vcmd = (parent.register(validate_numeric), "%P")
    return ttk.Entry(parent, textvariable=textvariable, width=width,
                     validate="key", validatecommand=vcmd)


def _make_modal(dlg: tk.Toplevel, parent: tk.Misc) -> None:
    """Pose `transient` + `grab_set` sur un Toplevel **après** que ses
    widgets soient visibles.

    Sans cet ordre, ouvrir un dialogue depuis un événement de clic
    (typiquement : `tag_bind` du canvas interactif) produisait une
    fenêtre vide sur Linux/X11 : le grab pris pendant que la fenêtre
    n'avait pas encore été mappée par le WM empêchait le rendu de ses
    enfants. La séquence canonique Tk : update_idletasks → transient →
    wait_visibility → grab_set → focus.
    """
    dlg.update_idletasks()
    try:
        dlg.transient(parent)  # type: ignore[call-overload]
    except tk.TclError:
        # parent n'est pas un Toplevel/Tk acceptable : on continue sans
        # transient, le dialogue restera modal via grab_set.
        pass
    try:
        dlg.wait_visibility()
    except tk.TclError:
        # fenêtre détruite avant d'être visible (cas limite tests).
        return
    dlg.grab_set()
    dlg.focus_set()


def ask_string(parent: tk.Misc, title: str, prompt: str,
               initial: str = "", *, info: str = "") -> Optional[str]:
    """Dialogue de saisie texte thémé (look ttk Pénétromètre).

    Remplace `tkinter.simpledialog.askstring`, dont l'apparence système
    détonne avec le reste de l'app. Renvoie la chaîne saisie (sans
    `strip`) si l'utilisateur valide, ou `None` s'il annule / ferme —
    même contrat que `askstring`, donc une chaîne vide validée ("") se
    distingue d'une annulation (`None`).

    `info` : note grise optionnelle sous le champ (exemples, contraintes).
    """
    dlg = tk.Toplevel(parent)
    dlg.title(title)
    dlg.configure(bg=COLOR_PANEL)
    dlg.resizable(False, False)
    dlg.columnconfigure(0, weight=1)
    result: dict[str, Optional[str]] = {"val": None}
    var = tk.StringVar(value=initial)

    ttk.Label(dlg, text=prompt, background=COLOR_PANEL, justify="left",
              wraplength=320).grid(row=0, column=0, sticky="w",
                                   padx=12, pady=(12, 6))
    entry = ttk.Entry(dlg, textvariable=var, width=34)
    entry.grid(row=1, column=0, sticky="we", padx=12, pady=(0, 6))
    entry.select_range(0, "end")
    if info:
        ttk.Label(dlg, text=info, background=COLOR_PANEL,
                  foreground=COLOR_MUTED,
                  font=ui_font("Helvetica", 9, "italic"),
                  wraplength=320, justify="left"
                  ).grid(row=2, column=0, sticky="w", padx=12, pady=(0, 6))

    def ok() -> None:
        result["val"] = var.get()
        dlg.destroy()

    btns = ttk.Frame(dlg, style="Panel.TFrame")
    btns.grid(row=3, column=0, sticky="e", padx=12, pady=(8, 12))
    ttk.Button(btns, text=_("Annuler"), style="Ghost.TButton",
               command=dlg.destroy).pack(side="right", padx=6)
    ttk.Button(btns, text=_("Valider"), style="Accent.TButton",
               command=ok).pack(side="right")

    dlg.bind("<Return>", lambda e: ok())
    dlg.bind("<Escape>", lambda e: dlg.destroy())

    _make_modal(dlg, parent)
    entry.focus_set()
    dlg.wait_window()
    return result["val"]


def ask_choice(parent: tk.Misc, title: str, prompt: str,
               choices: "List[str]", initial: str = ""
               ) -> Optional[str]:
    """Dialogue de choix unique thémé (combobox readonly), même contrat
    que `ask_string` : renvoie la valeur choisie si validé, `None` si
    annulé/fermé (une chaîne vide validée, p. ex. « non renseignée »,
    se distingue donc bien d'une annulation).

    Sert aux actions groupées (p. ex. urgence appliquée à plusieurs
    arbres sélectionnés) — un seul dialogue, pas un `askstring` brut.
    """
    dlg = tk.Toplevel(parent)
    dlg.title(title)
    dlg.configure(bg=COLOR_PANEL)
    dlg.resizable(False, False)
    dlg.columnconfigure(0, weight=1)
    result: dict[str, Optional[str]] = {"val": None}
    var = tk.StringVar(value=initial if initial in choices else
                       (choices[0] if choices else ""))

    ttk.Label(dlg, text=prompt, background=COLOR_PANEL, justify="left",
              wraplength=320).grid(row=0, column=0, sticky="w",
                                   padx=12, pady=(12, 6))
    cmb = ttk.Combobox(dlg, textvariable=var, values=choices,
                       state="readonly", width=32)
    cmb.grid(row=1, column=0, sticky="we", padx=12, pady=(0, 6))

    def ok() -> None:
        result["val"] = var.get()
        dlg.destroy()

    btns = ttk.Frame(dlg, style="Panel.TFrame")
    btns.grid(row=2, column=0, sticky="e", padx=12, pady=(8, 12))
    ttk.Button(btns, text=_("Annuler"), style="Ghost.TButton",
               command=dlg.destroy).pack(side="right", padx=6)
    ttk.Button(btns, text=_("Valider"), style="Accent.TButton",
               command=ok).pack(side="right")

    dlg.bind("<Return>", lambda e: ok())
    dlg.bind("<Escape>", lambda e: dlg.destroy())

    _make_modal(dlg, parent)
    cmb.focus_set()
    dlg.wait_window()
    return result["val"]


# ---------------------------------------------------------------------
# Dialog : sélecteur de date (calendrier Tkinter pur, sans dépendance)
# ---------------------------------------------------------------------

_MOIS_FR = ("janvier", "février", "mars", "avril", "mai", "juin",
            "juillet", "août", "septembre", "octobre", "novembre",
            "décembre")
_JOURS_FR = ("Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim")


def ask_date(parent: tk.Misc, initial: str = "") -> Optional[str]:
    """Sélecteur de date par mini-calendrier, en **Tkinter pur** (pas de
    dépendance type `tkcalendar`/`babel` — cf. règle « pas de dépendance
    sans bonne raison »). Complément clavier : la saisie libre du champ
    reste normalisée par `normaliser_date`.

    Renvoie « JJ/MM/AAAA » si une date est choisie, `""` si l'utilisateur
    efface la date, `None` s'il annule / ferme. `initial` est accepté
    librement (normalisé pour la position de départ).
    """
    today = date.today()
    norm = normaliser_date(initial)
    if norm:
        d, m, y = (int(x) for x in norm.split("/"))
        selected = date(y, m, d)
    else:
        selected = None
    cursor = selected or today
    state = {"year": cursor.year, "month": cursor.month}
    result: dict[str, Optional[str]] = {"val": None}

    dlg = tk.Toplevel(parent)
    dlg.title("Choisir une date")
    dlg.configure(bg=COLOR_PANEL)
    dlg.resizable(False, False)

    header = ttk.Frame(dlg, style="Panel.TFrame")
    header.grid(row=0, column=0, padx=10, pady=(10, 2), sticky="we")
    lbl_title = ttk.Label(header, style="Panel.TLabel", anchor="center",
                          font=ui_font("Helvetica", 11, "bold"))

    grid_frame = ttk.Frame(dlg, style="Panel.TFrame")
    grid_frame.grid(row=1, column=0, padx=10, pady=2)

    def choose(d: date) -> None:
        result["val"] = f"{d.day:02d}/{d.month:02d}/{d.year:04d}"
        dlg.destroy()

    def clear() -> None:
        result["val"] = ""
        dlg.destroy()

    def render() -> None:
        lbl_title.configure(
            text=f"{_MOIS_FR[state['month'] - 1]} {state['year']}")
        for w in grid_frame.winfo_children():
            w.destroy()
        for c, j in enumerate(_JOURS_FR):
            ttk.Label(grid_frame, text=j, style="Muted.TLabel",
                      width=4, anchor="center").grid(row=0, column=c,
                                                     padx=1, pady=1)
        weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(
            state["year"], state["month"])
        for r, week in enumerate(weeks, start=1):
            for c, day in enumerate(week):
                if day == 0:
                    continue
                d = date(state["year"], state["month"], day)
                # Jour sélectionné : accentué ; aujourd'hui (si différent) :
                # repère doux ; reste : bouton neutre.
                if selected is not None and d == selected:
                    style = "Accent.TButton"
                elif d == today:
                    style = "Accent.TButton"
                else:
                    style = "Ghost.TButton"
                ttk.Button(grid_frame, text=str(day), width=4,
                           style=style,
                           command=partial(choose, d)).grid(
                    row=r, column=c, padx=1, pady=1)

    def shift(delta: int) -> None:
        m0 = state["month"] - 1 + delta
        state["year"] += m0 // 12
        state["month"] = m0 % 12 + 1
        render()

    ttk.Button(header, text="«", width=3, style="Ghost.TButton",
               command=lambda: shift(-12)).grid(row=0, column=0)
    ttk.Button(header, text="◀", width=3, style="Ghost.TButton",
               command=lambda: shift(-1)).grid(row=0, column=1)
    lbl_title.grid(row=0, column=2, sticky="we")
    ttk.Button(header, text="▶", width=3, style="Ghost.TButton",
               command=lambda: shift(1)).grid(row=0, column=3)
    ttk.Button(header, text="»", width=3, style="Ghost.TButton",
               command=lambda: shift(12)).grid(row=0, column=4)
    header.columnconfigure(2, weight=1)

    footer = ttk.Frame(dlg, style="Panel.TFrame")
    footer.grid(row=2, column=0, padx=10, pady=(4, 10), sticky="we")
    ttk.Button(footer, text=_("Aujourd'hui"), style="Ghost.TButton",
               command=lambda: choose(today)).pack(side="left")
    ttk.Button(footer, text=_("Effacer"), style="Ghost.TButton",
               command=clear).pack(side="left", padx=6)
    ttk.Button(footer, text=_("Annuler"), style="Ghost.TButton",
               command=dlg.destroy).pack(side="right")

    render()
    dlg.bind("<Escape>", lambda e: dlg.destroy())
    _make_modal(dlg, parent)
    dlg.wait_window()
    return result["val"]


# ---------------------------------------------------------------------------
# Progression d'une tâche longue (export mission)
# ---------------------------------------------------------------------------

class ProgressDialog:
    """Fenêtre modale de progression, avec bouton **Annuler**.

    Pensée pour les exports qui parcourent toute la mission : à ~60 ms
    par fiche, une mission de 300 arbres bloquait la fenêtre une
    vingtaine de secondes, sans rien afficher — l'OS finissait par la
    déclarer « ne répond pas ». Le travail part donc dans un thread et
    cette fenêtre en montre l'avancement.

    **À piloter depuis le thread Tk uniquement** — l'appelant découpe
    son travail en tranches et se replanifie par `after` (cf.
    `app_exports.export_pdf_mission`). Ce n'est pas une commodité : deux
    tentatives par thread worker ont échoué, et il faut savoir pourquoi
    avant d'y revenir.

    1. Poster la progression par `parent.after(0, …)` depuis le worker
       appelle `Tcl_CreateCommand` hors du thread de l'interpréteur →
       « RuntimeError: main thread is not in main loop ». Dans un thread
       daemon, l'exception disparaît sans trace : l'export ne se termine
       jamais, en silence.
    2. Même en ne faisant transiter que des données (file + sondage
       côté Tk), le worker reste exposé : le **ramasse-miettes** peut se
       déclencher dans CE thread et y exécuter le `__del__` d'un objet
       Tk devenu inaccessible (`tkinter.Variable.__del__` appelle
       `globalunsetvar`). Tcl détecte l'accès hors thread et **abandonne
       le processus** (`Fatal Python error: Aborted`) — observé en test,
       pendant que fpdf2 chargeait ses polices.

    Le découpage coopératif évite les deux : aucun thread, donc aucun
    appel Tcl hors thread, et l'UI reste vivante parce qu'elle reprend
    la main entre deux tranches.
    """

    def __init__(self, parent: tk.Misc, titre: str, total: int,
                 message: str = "") -> None:
        self._parent = parent
        self._total = max(1, total)
        self._annule = False
        self._ferme = False

        self.dlg = tk.Toplevel(parent)
        self.dlg.title(titre)
        self.dlg.resizable(False, False)
        # Fermer la fenêtre = annuler (jamais « laisser tourner en fond
        # sans retour » : l'utilisateur croirait l'export terminé).
        self.dlg.protocol("WM_DELETE_WINDOW", self.annuler)

        frm = ttk.Frame(self.dlg, padding=20)
        frm.pack(fill="both", expand=True)

        # Typés Optional : `fermer()` les remet à None (cf. commentaire là-bas).
        self._var_txt: "Optional[tk.StringVar]" = tk.StringVar(value=message)
        ttk.Label(frm, textvariable=self._var_txt).pack(anchor="w")

        self._bar: "Optional[ttk.Progressbar]" = ttk.Progressbar(
            frm, mode="determinate", length=380, maximum=self._total)
        self._bar.pack(fill="x", pady=(10, 4))

        self._var_compte: "Optional[tk.StringVar]" = tk.StringVar(
            value=f"0 / {self._total}")
        ttk.Label(frm, textvariable=self._var_compte,
                  style="Muted.TLabel").pack(anchor="w")

        ttk.Button(frm, text=_("Annuler"),
                   command=self.annuler).pack(anchor="e", pady=(12, 0))

        _make_modal(self.dlg, parent)

    def demande_annulation(self) -> bool:
        """Vrai si l'utilisateur a cliqué Annuler (ou fermé la fenêtre)."""
        return self._annule

    def avancer(self, n: int, message: str = "") -> None:
        """Affiche `n` unités traitées sur `total`.

        `update()` force le repaint ET le traitement des événements en
        attente : c'est ce qui rend le bouton Annuler cliquable pendant
        la boucle d'export, alors qu'on n'a jamais quitté le thread Tk.
        """
        if self._ferme or self._bar is None or self._var_compte is None:
            return
        try:
            self._bar["value"] = n
            self._var_compte.set(f"{n} / {self._total}")
            if message and self._var_txt is not None:
                self._var_txt.set(message)
            self.dlg.update()
        except tk.TclError:
            pass                       # fenêtre détruite entre-temps

    def annuler(self) -> None:
        self._annule = True
        if self._var_txt is not None:
            self._var_txt.set(_("Annulation en cours…"))

    def fermer(self) -> None:
        if self._ferme:
            return
        self._ferme = True
        try:
            self.dlg.grab_release()
            self.dlg.destroy()
        except tk.TclError:
            pass
        # Libère les `StringVar` : si l'objet ProgressDialog survit à la
        # destruction de la racine Tk (une référence gardée par
        # l'appelant, par exemple), leur `__del__` tenterait de parler à
        # un interpréteur Tcl mort — « main thread is not in main loop »
        # au moment du GC. `_maj` ne les touche plus une fois `_ferme`.
        self._var_txt = None
        self._var_compte = None
        self._bar = None
