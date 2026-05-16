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

Aucune dépendance vers `penetrometre.py` (pas de cycle). Les fonctions
sont volontairement « duck-typées » sur `app` : elles n'accèdent qu'à
`app._current_arbre()`, `app._refresh_*`, `app._debounced_redraw`, et
aux trois tables Tk (`tbl`, `tbl_de`, `tbl_cf`).

L'analogue de ce module pour les actions d'export est `app_exports.py`.
"""

from __future__ import annotations

from dialogs import edit_contrefort, edit_degradation, edit_sondage
from model import Contrefort, DegradationExterne, Sondage


# ----------------------------------------------------------------------
# Sondages
# ----------------------------------------------------------------------

def add_sondage(app) -> None:
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


def edit_sondage_selected(app) -> None:
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


def del_sondage(app) -> None:
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

def add_degradation(app) -> None:
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


def edit_degradation_selected(app) -> None:
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


def del_degradation(app) -> None:
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

def add_contrefort(app) -> None:
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


def edit_contrefort_selected(app) -> None:
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


def del_contrefort(app) -> None:
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
