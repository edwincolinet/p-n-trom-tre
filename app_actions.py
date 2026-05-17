"""
Actions « édition métier » de la fenêtre App pour les Sondages.

Chaque fonction prend `app` (la fenêtre Tk) en premier argument et
suit le même protocole :

1. récupère l'arbre courant (`app._current_arbre()`), bail-out si None ;
2. (édition/suppression) lit la sélection courante de la table Tk ;
3. ouvre le dialogue d'édition (cf. `dialogs.py`) ou supprime ;
4. en cas de succès : mute l'arbre, renumérote, rafraîchit la table et
   demande un redraw du dessin.

Aucune dépendance vers `penetrometre.py` (pas de cycle). Le contrat
attendu de `app` est formalisé par le `AppHost` (Protocol) ci-dessous.

Note : les actions Dégradations et Contreforts ne sont plus ici — elles
vivent dans `pane_degradations.DegradationsPane` et
`pane_contreforts.ContrefortsPane` respectivement. Ce module sera à son
tour absorbé dans un futur `SondagesPane`.

L'analogue de ce module pour les actions d'export est `app_exports.py`.
"""

from __future__ import annotations

from tkinter import ttk
from typing import Optional, Protocol

from dialogs import edit_sondage
from model import Arbre, Sondage


class AppHost(Protocol):
    """Surface minimale de la fenêtre `App` consommée par ce module.

    `App` (dans `penetrometre.py`) satisfait ce Protocol par structure
    (PEP 544) — aucun héritage à déclarer côté `App`. Les types-checkers
    (Pyright/mypy) vérifient le contrat ; à l'exécution, c'est du duck-
    typing transparent.
    """
    tbl: ttk.Treeview

    def _current_arbre(self) -> Optional[Arbre]: ...
    def _refresh_sondages_table(self) -> None: ...
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


# Note : les actions Dégradations et Contreforts vivent dans leurs
# panes respectifs (pane_degradations.py et pane_contreforts.py),
# avec le reste de l'onglet (table, boutons, refresh).
