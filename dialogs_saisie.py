"""Boîtes de dialogue d'édition détaillée (Sondage, DégradationExterne,
Contrefort).

Extrait de `dialogs.py` (2026-08-25) : ces trois dialogues forment un
sous-domaine cohérent (édition d'une mesure ponctuelle d'un brin, avec
liens automatiques bois sain/altéré ou largeur gr/cm) sans dépendance
mutuelle. Ce qui reste dans `dialogs.py` : les primitives génériques
(`ask_string`/`ask_choice`/`ask_date`/`ProgressDialog`) que d'autres
modules (réglages, cycle de vie fichier…) utilisent sans rien connaître
du modèle métier Sondage/Dégradation/Contrefort.

Chaque fonction reçoit :

- `parent`  : la fenêtre Tk parente (utilisée pour `transient`,
              `grab_set` et la position du toplevel).
- `arbre`   : la `Section` courante — `Arbre` ou `Brin` (peut être
              `None`). Lecture seule, sert uniquement à connaître
              `rayon_a_grade`/`rayon_tronc_cm` pour les calculs de
              liens automatiques (bois sain ↔ altéré, largeur en cm
              ↔ largeur en grades). Les dialogues mutent **directement**
              l'objet métier passé en paramètre (Sondage / Dégradation /
              Contrefort) — pas de copie.
- `obj`     : l'objet métier à éditer (mutation en place).

Renvoie `True` si l'utilisateur a validé, `False` s'il a annulé ou
fermé la fenêtre.
"""

from __future__ import annotations

import math
import tkinter as tk
from tkinter import messagebox, ttk
from typing import List, Optional

from dialogs import Section, _make_modal, _numeric_entry
from dialogs_shared import (
    COMPART_NR_LABEL,
    ZONE_DEGRADEE_AIDE,
    _round_to_25,
    compart_choices,
    compart_from_label,
    compart_label,
    find_grade_choice,
    grade_choices,
    message_chevauchement,
    parse_grade,
    to_float,
    zone_degradee_choices,
    zone_degradee_label,
    zone_degradee_to_bool,
)
from geometry import DIRECTION_LABELS
from i18n import _
from model import (
    Contrefort,
    DegradationExterne,
    Sondage,
    degradations_chevauchements,
)
from palette import COLOR_MUTED, COLOR_PANEL
from ui_fonts import font as ui_font

# ---------------------------------------------------------------------
# Dialog : Sondage
# ---------------------------------------------------------------------

def edit_sondage(parent: tk.Misc, arbre: Optional[Section],
                  sondage: Sondage) -> bool:
    """Édite un sondage en place. Renvoie True si validé."""
    dlg = tk.Toplevel(parent)
    dlg.title(f"Sondage n° {sondage.numero}")
    dlg.configure(bg=COLOR_PANEL)
    dlg.resizable(False, False)
    # `transient` + `grab_set` posés APRÈS la création des widgets et
    # `wait_visibility` (cf. fin de fonction). Les appeler avant
    # provoquait un dialogue vide quand l'ouverture venait du canvas
    # interactif (clic sur pastille) sur Linux/X11.

    R = arbre.rayon_a_grade(sondage.grade) if arbre else 0.0

    v_grade = tk.StringVar()
    v_sain = tk.StringVar(value=f"{sondage.bois_sain_cm:g}")
    v_alt = tk.StringVar(value=f"{sondage.bois_altere_cm:g}")
    v_comp = tk.StringVar(value=compart_label(sondage.compartimentation))
    v_com = tk.StringVar(value=sondage.commentaire)
    v_inc = tk.BooleanVar(value=sondage.incertain)
    result = {"ok": False}
    syncing: List[bool] = [False]

    choices = grade_choices()
    v_grade.set(find_grade_choice(choices, sondage.grade))


    # Bandeau rappelant le rayon LOCAL (référence pour le calcul auto) — le
    # diamètre général, ajusté du Ø local de cette direction s'il est saisi
    # dans la grille (indépendant du sondage, non éditable ici).
    if R > 0:
        rappel = (f"Rayon local de cette direction : {R:g} cm\n"
                  f"Règle : Bois sain + Bois altéré = Rayon.\n"
                  f"Modifier l'un recalcule l'autre automatiquement.")
    else:
        rappel = ("⚠ Rayon du tronc non renseigné : le calcul auto "
                  "entre bois sain et bois altéré est désactivé.")
    ttk.Label(dlg, text=rappel, background=COLOR_PANEL,
              foreground=COLOR_MUTED, font=ui_font("Helvetica", 9, "italic"),
              wraplength=300, justify="left"
              ).grid(row=0, column=0, columnspan=2, sticky="we",
                     padx=10, pady=(10, 4))

    ttk.Label(dlg, text=_("Direction (grade)"), background=COLOR_PANEL
              ).grid(row=1, column=0, sticky="w", padx=10, pady=6)
    combo_grade = ttk.Combobox(dlg, textvariable=v_grade,
                               values=choices,
                               state="readonly", width=26)
    combo_grade.grid(row=1, column=1, sticky="we", padx=10, pady=6)

    ttk.Label(dlg, text=_("Épaisseur bois sain (cm)"),
              background=COLOR_PANEL
              ).grid(row=2, column=0, sticky="w", padx=10, pady=6)
    _numeric_entry(dlg, v_sain, width=12
                   ).grid(row=2, column=1, sticky="w", padx=10, pady=6)

    ttk.Label(dlg, text=_("Épaisseur bois altéré (cm)"),
              background=COLOR_PANEL
              ).grid(row=3, column=0, sticky="w", padx=10, pady=6)
    _numeric_entry(dlg, v_alt, width=12
                   ).grid(row=3, column=1, sticky="w", padx=10, pady=6)

    # --- Lien automatique bois sain <-> bois altéré -----------------
    def _on_sain_changed(*_: object) -> None:
        if syncing[0] or R <= 0:
            return
        try:
            v = to_float(v_sain.get())
        except ValueError:
            return
        v = max(0.0, min(v, R))
        syncing[0] = True
        v_alt.set(f"{R - v:g}")
        syncing[0] = False

    def _on_alt_changed(*_: object) -> None:
        if syncing[0] or R <= 0:
            return
        try:
            v = to_float(v_alt.get())
        except ValueError:
            return
        v = max(0.0, min(v, R))
        syncing[0] = True
        v_sain.set(f"{R - v:g}")
        syncing[0] = False

    v_sain.trace_add("write", _on_sain_changed)
    v_alt.trace_add("write", _on_alt_changed)

    # Migration silencieuse à l'ouverture du dialogue : ancien "-" → tiret long.
    if v_comp.get() == "-":
        v_comp.set(COMPART_NR_LABEL)
    ttk.Label(dlg, text=_("Compartimentation"), background=COLOR_PANEL
              ).grid(row=4, column=0, sticky="w", padx=10, pady=6)
    ttk.Combobox(dlg, textvariable=v_comp,
                 values=compart_choices(["active", "absente", "non renseignée"]),
                 state="readonly", width=18
                 ).grid(row=4, column=1, sticky="w", padx=10, pady=6)

    ttk.Label(dlg, text=_("Commentaire"), background=COLOR_PANEL
              ).grid(row=5, column=0, sticky="w", padx=10, pady=6)
    ttk.Entry(dlg, textvariable=v_com, width=28
              ).grid(row=5, column=1, sticky="we", padx=10, pady=6)
    ttk.Checkbutton(dlg, text=_("Sondage incertain (mesure douteuse)"),
                    variable=v_inc, style="Panel.TCheckbutton"
                    ).grid(row=6, column=0, columnspan=2,
                           sticky="w", padx=10, pady=(0, 4))

    def ok() -> None:
        try:
            new_grade = parse_grade(v_grade.get())
            if arbre is not None:
                for other in arbre.sondages:
                    if other is not sondage and other.grade == new_grade:
                        lbl = DIRECTION_LABELS.get(new_grade, "")
                        direction = f" ({lbl})" if lbl else ""
                        messagebox.showwarning(
                            _("Direction déjà sondée"),
                            f"Un sondage existe déjà au grade "
                            f"{new_grade} gr{direction}.\n\n"
                            "Chaque direction ne peut être sondée "
                            "qu'une seule fois.",
                            parent=dlg)
                        return
            sondage.grade = new_grade
            # Bois sain/altéré restent clampés sur `R`, le rayon local
            # affiché à l'ouverture du dialogue (le Ø local, indépendant du
            # sondage, s'édite dans la grille — pas ici).
            sain = to_float(v_sain.get())
            alt = to_float(v_alt.get())
            if R > 0:
                # Clamp et recoller à R pour éviter toute incohérence
                sain = max(0.0, min(sain, R))
                alt = max(0.0, min(alt, R))
                # si la somme ne fait pas R, on fait confiance à
                # l'altéré (dernière grandeur pertinente métier)
                if abs(sain + alt - R) > 1e-6:
                    sain = R - alt
            sondage.bois_sain_cm = sain
            sondage.bois_altere_cm = alt
            sondage.compartimentation = compart_from_label(v_comp.get())
            sondage.commentaire = v_com.get()
            sondage.incertain = v_inc.get()
            result["ok"] = True
            dlg.destroy()
        except ValueError as e:
            messagebox.showerror(_("Erreur de saisie"),
                                 f"Valeur invalide : {e}", parent=dlg)

    btns = ttk.Frame(dlg, style="Panel.TFrame")
    btns.grid(row=7, column=0, columnspan=2, pady=(10, 12))
    ttk.Button(btns, text=_("Annuler"), style="Ghost.TButton",
               command=dlg.destroy).pack(side="right", padx=6)
    ttk.Button(btns, text=_("Valider"), style="Accent.TButton",
               command=ok).pack(side="right")

    # Validation au clavier : Entrée valide, Échap annule — évite
    # d'attraper la souris à chaque sondage saisi.
    dlg.bind("<Return>", lambda e: ok())
    dlg.bind("<Escape>", lambda e: dlg.destroy())

    _make_modal(dlg, parent)
    combo_grade.focus_set()  # focus sur le 1er champ utile
    dlg.wait_window()
    return result["ok"]


# ---------------------------------------------------------------------
# Dialog : Dégradation externe
# ---------------------------------------------------------------------

def edit_degradation(parent: tk.Misc, arbre: Optional[Section],
                      deg: DegradationExterne) -> bool:
    """Édite une dégradation externe en place. Renvoie True si validé.

    Saisie : direction de début, et (au choix) direction de fin OU
    largeur en grades OU largeur en cm sur l'écorce — les trois sont
    liées automatiquement. Profondeur radiale en cm, commentaire.
    """
    dlg = tk.Toplevel(parent)
    dlg.title(_("Dégradation externe n° {n}").format(n=deg.numero))
    dlg.configure(bg=COLOR_PANEL)
    dlg.resizable(False, False)
    # transient + grab_set : cf. note dans edit_sondage.

    R = arbre.rayon_tronc_cm if arbre else 0.0

    v_debut = tk.StringVar()
    v_fin = tk.StringVar()
    v_largeur_gr = tk.StringVar(value=str(deg.largeur_grades()))
    v_largeur_cm = tk.StringVar(value=f"{deg.largeur_cm(R):.1f}")
    v_prof = tk.StringVar(value=f"{deg.profondeur_cm:g}")
    v_ecorce = tk.StringVar(value=zone_degradee_label(deg.comprend_ecorce))
    v_com = tk.StringVar(value=deg.commentaire)
    result = {"ok": False}
    syncing: List[bool] = [False]

    choices = grade_choices()
    v_debut.set(find_grade_choice(choices, deg.grade_debut))
    v_fin.set(find_grade_choice(choices, deg.grade_fin))


    ttk.Label(dlg, text=_("Direction de début (grade)"),
              background=COLOR_PANEL).grid(row=0, column=0,
                                           sticky="w", padx=10, pady=6)
    combo_debut = ttk.Combobox(dlg, textvariable=v_debut,
                               values=choices,
                               state="readonly", width=24)
    combo_debut.grid(row=0, column=1, sticky="we", padx=10, pady=6)

    ttk.Label(dlg, text=_("Direction de fin (grade, sens horaire)"),
              background=COLOR_PANEL).grid(row=1, column=0,
                                           sticky="w", padx=10, pady=6)
    ttk.Combobox(dlg, textvariable=v_fin, values=choices,
                 state="readonly", width=24
                 ).grid(row=1, column=1, sticky="we", padx=10, pady=6)

    ttk.Label(dlg, text=_("— ou —"), background=COLOR_PANEL,
              foreground=COLOR_MUTED, font=ui_font("Helvetica", 9, "italic")
              ).grid(row=2, column=0, columnspan=2, pady=(2, 2))

    ttk.Label(dlg, text=_("Largeur en grades"),
              background=COLOR_PANEL).grid(row=3, column=0,
                                           sticky="w", padx=10, pady=6)
    _numeric_entry(dlg, v_largeur_gr, width=12
                   ).grid(row=3, column=1, sticky="w", padx=10, pady=6)

    ttk.Label(dlg, text=_("Largeur en cm (sur l'écorce)"),
              background=COLOR_PANEL).grid(row=4, column=0,
                                           sticky="w", padx=10, pady=6)
    _numeric_entry(dlg, v_largeur_cm, width=12
                   ).grid(row=4, column=1, sticky="w", padx=10, pady=6)

    ttk.Label(dlg, text=_("Profondeur radiale (cm)"),
              background=COLOR_PANEL).grid(row=5, column=0,
                                           sticky="w", padx=10, pady=6)
    _numeric_entry(dlg, v_prof, width=12
                   ).grid(row=5, column=1, sticky="w", padx=10, pady=6)

    ttk.Label(dlg, text=_("Zone dégradée"),
              background=COLOR_PANEL).grid(row=6, column=0,
                                           sticky="w", padx=10, pady=6)
    ttk.Combobox(dlg, textvariable=v_ecorce,
                 values=list(zone_degradee_choices()),
                 state="readonly", width=24
                 ).grid(row=6, column=1, sticky="we", padx=10, pady=6)
    ttk.Label(dlg, text=_(ZONE_DEGRADEE_AIDE), background=COLOR_PANEL,
              foreground=COLOR_MUTED, wraplength=300, justify="left",
              font=ui_font("Helvetica", 9)
              ).grid(row=7, column=0, columnspan=2,
                     sticky="w", padx=10, pady=(0, 6))

    ttk.Label(dlg, text=_("Commentaire"), background=COLOR_PANEL
              ).grid(row=8, column=0, sticky="w", padx=10, pady=6)
    ttk.Entry(dlg, textvariable=v_com, width=28
              ).grid(row=8, column=1, sticky="we", padx=10, pady=6)

    # --- Liens auto entre fin / largeur_gr / largeur_cm -------------
    def _on_fin(*_: object) -> None:
        if syncing[0]:
            return
        try:
            d = parse_grade(v_debut.get())
            f = parse_grade(v_fin.get())
            largeur = (f - d) % 400
            if largeur == 0:
                largeur = 25
            syncing[0] = True
            v_largeur_gr.set(str(largeur))
            if R > 0:
                v_largeur_cm.set(
                    f"{R * largeur * math.pi / 200:.1f}")
            syncing[0] = False
        except (ValueError, IndexError):
            pass

    def _on_largeur_gr(*_: object) -> None:
        if syncing[0]:
            return
        try:
            raw = to_float(v_largeur_gr.get()) or 25
            gr = _round_to_25(int(raw))
            if gr == 0:
                gr = 25
            d = parse_grade(v_debut.get())
            f = (d + gr) % 400
            syncing[0] = True
            v_fin.set(find_grade_choice(choices, f))
            if R > 0:
                v_largeur_cm.set(
                    f"{R * gr * math.pi / 200:.1f}")
            syncing[0] = False
        except (ValueError, IndexError):
            pass

    def _on_largeur_cm(*_: object) -> None:
        if syncing[0] or R <= 0:
            return
        try:
            cm = to_float(v_largeur_cm.get())
            gr = _round_to_25(int(cm * 200 / (R * math.pi)))
            if gr == 0:
                gr = 25
            d = parse_grade(v_debut.get())
            f = (d + gr) % 400
            syncing[0] = True
            v_largeur_gr.set(str(gr))
            v_fin.set(find_grade_choice(choices, f))
            syncing[0] = False
        except (ValueError, IndexError, ZeroDivisionError):
            pass

    v_debut.trace_add("write", _on_fin)
    v_fin.trace_add("write", _on_fin)
    v_largeur_gr.trace_add("write", _on_largeur_gr)
    v_largeur_cm.trace_add("write", _on_largeur_cm)

    def ok() -> None:
        try:
            new_debut = parse_grade(v_debut.get())
            new_fin = parse_grade(v_fin.get())
            if arbre is not None:
                conflits = degradations_chevauchements(
                    arbre.degradations_externes, deg, new_debut, new_fin)
                if conflits:
                    other, shared = conflits[0]
                    messagebox.showwarning(
                        _("Chevauchement de dégradations"),
                        message_chevauchement(other, shared),
                        parent=dlg)
                    return
            deg.grade_debut = new_debut
            deg.grade_fin = new_fin
            deg.profondeur_cm = max(0.0, to_float(v_prof.get()))
            deg.comprend_ecorce = zone_degradee_to_bool(v_ecorce.get())
            deg.commentaire = v_com.get()
            result["ok"] = True
            dlg.destroy()
        except (ValueError, IndexError) as e:
            messagebox.showerror(_("Erreur de saisie"),
                                 f"Valeur invalide : {e}", parent=dlg)

    btns = ttk.Frame(dlg, style="Panel.TFrame")
    btns.grid(row=9, column=0, columnspan=2, pady=(10, 12))
    ttk.Button(btns, text=_("Annuler"), style="Ghost.TButton",
               command=dlg.destroy).pack(side="right", padx=6)
    ttk.Button(btns, text=_("Valider"), style="Accent.TButton",
               command=ok).pack(side="right")

    # Entrée valide, Échap annule (cf. edit_sondage).
    dlg.bind("<Return>", lambda e: ok())
    dlg.bind("<Escape>", lambda e: dlg.destroy())

    _make_modal(dlg, parent)
    combo_debut.focus_set()  # focus sur le 1er champ utile
    dlg.wait_window()
    return result["ok"]


# ---------------------------------------------------------------------
# Dialog : Contrefort
# ---------------------------------------------------------------------

def edit_contrefort(parent: tk.Misc, arbre: Optional[Section],
                     cf: Contrefort) -> bool:
    """Édite un contrefort en place. Renvoie True si validé.

    Saisie : orientation (grade central), largeur en grades (multiple
    de 25) ou en cm sur l'écorce, longueur radiale, commentaire.
    """
    dlg = tk.Toplevel(parent)
    dlg.title(f"Contrefort n° {cf.numero}")
    dlg.configure(bg=COLOR_PANEL)
    dlg.resizable(False, False)
    # transient + grab_set : cf. note dans edit_sondage.

    R = arbre.rayon_tronc_cm if arbre else 0.0

    v_centre = tk.StringVar()
    v_largeur_gr = tk.StringVar(value=str(cf.largeur_grades))
    v_largeur_cm = tk.StringVar(value=f"{cf.largeur_cm(R):.1f}")
    v_long = tk.StringVar(value=f"{cf.longueur_cm:g}")
    v_com = tk.StringVar(value=cf.commentaire)
    result = {"ok": False}
    syncing: List[bool] = [False]

    choices = grade_choices()
    v_centre.set(find_grade_choice(choices, cf.grade_centre))


    ttk.Label(dlg, text=_("Orientation (grade central)"),
              background=COLOR_PANEL).grid(row=0, column=0,
                                           sticky="w", padx=10, pady=6)
    combo_centre = ttk.Combobox(dlg, textvariable=v_centre,
                                values=choices,
                                state="readonly", width=24)
    combo_centre.grid(row=0, column=1, sticky="we", padx=10, pady=6)

    ttk.Label(dlg, text=_("Largeur en grades (multiple de 25)"),
              background=COLOR_PANEL).grid(row=1, column=0,
                                           sticky="w", padx=10, pady=6)
    _numeric_entry(dlg, v_largeur_gr, width=12
                   ).grid(row=1, column=1, sticky="w", padx=10, pady=6)

    ttk.Label(dlg, text=_("Largeur en cm (sur l'écorce)"),
              background=COLOR_PANEL).grid(row=2, column=0,
                                           sticky="w", padx=10, pady=6)
    _numeric_entry(dlg, v_largeur_cm, width=12
                   ).grid(row=2, column=1, sticky="w", padx=10, pady=6)

    ttk.Label(dlg, text=_("Longueur radiale (cm, vers l'extérieur)"),
              background=COLOR_PANEL).grid(row=3, column=0,
                                           sticky="w", padx=10, pady=6)
    _numeric_entry(dlg, v_long, width=12
                   ).grid(row=3, column=1, sticky="w", padx=10, pady=6)

    ttk.Label(dlg, text=_("Commentaire"), background=COLOR_PANEL
              ).grid(row=4, column=0, sticky="w", padx=10, pady=6)
    ttk.Entry(dlg, textvariable=v_com, width=28
              ).grid(row=4, column=1, sticky="we", padx=10, pady=6)

    # Liens auto entre largeur_gr et largeur_cm
    def _on_largeur_gr(*_: object) -> None:
        if syncing[0]:
            return
        try:
            raw = to_float(v_largeur_gr.get()) or 25
            gr = _round_to_25(int(raw),
                                min_v=25, max_v=400, wrap=False)
            syncing[0] = True
            if R > 0:
                v_largeur_cm.set(f"{R * gr * math.pi / 200:.1f}")
            syncing[0] = False
        except (ValueError, IndexError):
            pass

    def _on_largeur_cm(*_: object) -> None:
        if syncing[0] or R <= 0:
            return
        try:
            cm = to_float(v_largeur_cm.get())
            gr = _round_to_25(int(cm * 200 / (R * math.pi)),
                                min_v=25, max_v=400, wrap=False)
            syncing[0] = True
            v_largeur_gr.set(str(gr))
            syncing[0] = False
        except (ValueError, IndexError, ZeroDivisionError):
            pass

    v_largeur_gr.trace_add("write", _on_largeur_gr)
    v_largeur_cm.trace_add("write", _on_largeur_cm)

    def ok() -> None:
        try:
            new_centre = parse_grade(v_centre.get()) % 400
            if arbre is not None:
                for other in arbre.contreforts:
                    if other is not cf and other.grade_centre == new_centre:
                        lbl = DIRECTION_LABELS.get(new_centre, "")
                        direction = f" ({lbl})" if lbl else ""
                        messagebox.showwarning(
                            _("Contrefort en double"),
                            f"Un contrefort existe déjà au grade "
                            f"{new_centre} gr{direction}.",
                            parent=dlg)
                        return
            cf.grade_centre = new_centre
            cf.largeur_grades = _round_to_25(
                int(to_float(v_largeur_gr.get()) or 25),
                min_v=25, max_v=400, wrap=False)
            cf.longueur_cm = max(0.0, to_float(v_long.get()))
            cf.commentaire = v_com.get()
            result["ok"] = True
            dlg.destroy()
        except (ValueError, IndexError) as e:
            messagebox.showerror(_("Erreur de saisie"),
                                 f"Valeur invalide : {e}", parent=dlg)

    btns = ttk.Frame(dlg, style="Panel.TFrame")
    btns.grid(row=5, column=0, columnspan=2, pady=(10, 12))
    ttk.Button(btns, text=_("Annuler"), style="Ghost.TButton",
               command=dlg.destroy).pack(side="right", padx=6)
    ttk.Button(btns, text=_("Valider"), style="Accent.TButton",
               command=ok).pack(side="right")

    # Entrée valide, Échap annule (cf. edit_sondage).
    dlg.bind("<Return>", lambda e: ok())
    dlg.bind("<Escape>", lambda e: dlg.destroy())

    _make_modal(dlg, parent)
    combo_centre.focus_set()  # focus sur le 1er champ utile
    dlg.wait_window()
    return result["ok"]
