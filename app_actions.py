"""
Actions « édition métier » de la fenêtre App : ajouter/éditer/supprimer
un sondage, une dégradation externe, un contrefort.

Chaque fonction prend `app` (la fenêtre Tk) en premier argument et
suit le même protocole :

1. récupère l'arbre courant (`app._current_arbre()`), bail-out si None ;
2. (édition/suppression) lit la sélection courante de la table Tk ;
3. ouvre le dialogue d'édition (cf. `dialogs.py`) ou supprime ;
4. en cas de succès : mute l'arbre, renumérote, rafraîchit la table et
   demande un redraw du dessin.

Aucune dépendance vers `penetrometre.py` (pas de cycle). Le contrat
attendu de `app` est formalisé par le `AppHost` (Protocol) ci-dessous —
c'est purement statique (aucun coût runtime), ça remplace le
« duck-typing » historique qui n'attrapait les fautes de frappe qu'à
l'exécution.

L'analogue de ce module pour les actions d'export est `app_exports.py`.
"""

from __future__ import annotations

from tkinter import ttk
from typing import Optional, Protocol

from dialogs import edit_contrefort, edit_degradation, edit_sondage
from model import Arbre, Contrefort, DegradationExterne, Sondage


class AppHost(Protocol):
    """Surface minimale de la fenêtre `App` consommée par ce module.

    `App` (dans `penetrometre.py`) satisfait ce Protocol par structure
    (PEP 544) — aucun héritage à déclarer côté `App`. Les types-checkers
    (Pyright/mypy) vérifient le contrat ; à l'exécution, c'est du duck-
    typing transparent.
    """
    tbl: ttk.Treeview
    tbl_de: ttk.Treeview
    tbl_cf: ttk.Treeview

    def _current_arbre(self) -> Optional[Arbre]: ...
    def _refresh_sondages_table(self) -> None: ...
    def _refresh_degradations_table(self) -> None: ...
    def _refresh_contreforts_table(self) -> None: ...
    def _debounced_redraw(self) -> None: ...


# ----------------------------------------------------------------------
# Sondages
# ----------------------------------------------------------------------

def add_sondage(app: AppHost) -> None:
    a = app._current_arbre()
    if not a:
        return
    s = Sondage(numero=len(a.sondages) + 1, grade=0,
                bois_sain_cm=a.rayon_tronc_cm, bois_altere_cm=0.0)
    if edit_sondage(app, a, s):
        a.sondages.append(s)
        a.renumeroter_sondages()
        app._refresh_sondages_table()
        app._debounced_redraw()


def edit_sondage_selected(app: AppHost) -> None:
    sel = app.tbl.selection()
    if not sel:
        return
    idx = int(sel[0][1:])
    a = app._current_arbre()
    if not a:
        return
    s = a.sondages[idx]
    if edit_sondage(app, a, s):
        app._refresh_sondages_table()
        app._debounced_redraw()


def del_sondage(app: AppHost) -> None:
    sel = app.tbl.selection()
    if not sel:
        return
    idx = int(sel[0][1:])
    a = app._current_arbre()
    if not a:
        return
    del a.sondages[idx]
    a.renumeroter_sondages()
    app._refresh_sondages_table()
    app._debounced_redraw()


# ----------------------------------------------------------------------
# Dégradations externes
# ----------------------------------------------------------------------

def add_degradation(app: AppHost) -> None:
    a = app._current_arbre()
    if not a:
        return
    deg = DegradationExterne(
        numero=len(a.degradations_externes) + 1,
        grade_debut=0, grade_fin=50, profondeur_cm=2.0)
    if edit_degradation(app, a, deg):
        a.degradations_externes.append(deg)
        a.renumeroter_degradations()
        app._refresh_degradations_table()
        app._debounced_redraw()


def edit_degradation_selected(app: AppHost) -> None:
    sel = app.tbl_de.selection()
    if not sel:
        return
    idx = int(sel[0][1:])
    a = app._current_arbre()
    if not a:
        return
    deg = a.degradations_externes[idx]
    if edit_degradation(app, a, deg):
        app._refresh_degradations_table()
        app._debounced_redraw()


def del_degradation(app: AppHost) -> None:
    sel = app.tbl_de.selection()
    if not sel:
        return
    idx = int(sel[0][1:])
    a = app._current_arbre()
    if not a:
        return
    del a.degradations_externes[idx]
    a.renumeroter_degradations()
    app._refresh_degradations_table()
    app._debounced_redraw()


# ----------------------------------------------------------------------
# Contreforts
# ----------------------------------------------------------------------

def add_contrefort(app: AppHost) -> None:
    a = app._current_arbre()
    if not a:
        return
    c = Contrefort(numero=len(a.contreforts) + 1,
                   grade_centre=0, largeur_grades=75, longueur_cm=10.0)
    if edit_contrefort(app, a, c):
        a.contreforts.append(c)
        a.renumeroter_contreforts()
        app._refresh_contreforts_table()
        app._debounced_redraw()


def edit_contrefort_selected(app: AppHost) -> None:
    sel = app.tbl_cf.selection()
    if not sel:
        return
    idx = int(sel[0][1:])
    a = app._current_arbre()
    if not a:
        return
    c = a.contreforts[idx]
    if edit_contrefort(app, a, c):
        app._refresh_contreforts_table()
        app._debounced_redraw()


def del_contrefort(app: AppHost) -> None:
    sel = app.tbl_cf.selection()
    if not sel:
        return
    idx = int(sel[0][1:])
    a = app._current_arbre()
    if not a:
        return
    del a.contreforts[idx]
    a.renumeroter_contreforts()
    app._refresh_contreforts_table()
    app._debounced_redraw()
