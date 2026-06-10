"""Boîtes de dialogue Tk d'édition des objets métier (Sondage,
DégradationExterne, Contrefort).

Module séparé pour éviter que `penetrometre.py` ne reste un fichier
de 2 200+ lignes. Chaque fonction reçoit :

- `parent`  : la fenêtre Tk parente (utilisée pour `transient`,
              `grab_set` et la position du toplevel).
- `arbre`   : l'`Arbre` courant (peut être `None`). Lecture seule, sert
              uniquement à connaître `rayon_tronc_cm` pour les calculs
              de liens automatiques (bois sain ↔ altéré, largeur en cm
              ↔ largeur en grades). Les dialogues mutent **directement**
              l'objet métier passé en paramètre (Sondage / Dégradation /
              Contrefort) — pas de copie.
- `obj`     : l'objet métier à éditer (mutation en place).

Renvoie `True` si l'utilisateur a validé, `False` s'il a annulé ou
fermé la fenêtre.

Aucune dépendance vers `penetrometre.py` (ce qui empêche le cycle
d'import). Les dataclasses sont reçues en duck-typing, mais on importe
quand même `Sondage`, `DegradationExterne`, `Contrefort` pour le typage.
"""

from __future__ import annotations

import math
import tkinter as tk
from tkinter import messagebox, ttk
from typing import List, Optional, Tuple, Union

from geometry import DIRECTION_LABELS, GRADES
from model import Arbre, Brin, Contrefort, DegradationExterne, Sondage
from palette import COLOR_MUTED, COLOR_PANEL
from ui_fonts import font as ui_font

# Les dialogues d'édition (sondage/dégradation/contrefort) ne lisent que de la
# géométrie (`rayon_tronc_cm`) et la liste de mesures concernée — présentes
# aussi bien sur un `Arbre` (relais de compat → brins[0]) que sur un `Brin`
# natif. Accepter les deux permet d'éditer un brin précis d'une cépée (le
# sélecteur de brin de l'Étape 4) sans passer par les relais brins[0].
Section = Union[Arbre, Brin]


def _grade_choices() -> list[str]:
    """Libellés des 16 directions, format `"100 gr — E"`."""
    out = []
    for g in GRADES:
        lbl = DIRECTION_LABELS.get(g, "")
        out.append(f"{g} gr" + (f" — {lbl}" if lbl else ""))
    return out


def _find_grade_choice(choices: list[str], grade_value: int) -> str:
    """Renvoie l'entrée de `choices` qui commence par `<grade_value> gr`."""
    for c in choices:
        if c.startswith(f"{grade_value} gr"):
            return c
    return choices[0]


def _parse_grade(s: str) -> int:
    """Extrait le grade entier d'une chaîne `"100 gr — E"` (tolère
    aussi l'ancien format `"100° — E"`)."""
    return int(s.replace("°", " ").split(" ")[0].strip())


def _round_to_25(v: int, *, min_v: int = 0, max_v: int = 375,
                  wrap: bool = True) -> int:
    """Arrondit à 25 près. `wrap=True` ramène modulo 400 (pour les
    grades), `wrap=False` clamp dans `[min_v, max_v]` (pour les
    largeurs de contrefort)."""
    v = round(v / 25) * 25
    if wrap:
        return v % 400
    return max(min_v, min(max_v, v))


def validate_numeric(proposed: str) -> bool:
    """Validateur Tk (validate="key") pour les champs numériques
    positifs. Accepte : vide, chiffres, et au plus un séparateur
    décimal (`.` ou `,`). Refuse tout autre caractère à la frappe.

    Public car réutilisé par les onglets (`pane_identification`)."""
    if proposed == "":
        return True
    if proposed.count(",") + proposed.count(".") > 1:
        return False
    test = proposed.replace(",", ".", 1)
    try:
        float(test)
    except ValueError:
        return False
    return True


def to_float(s: str) -> float:
    """Convertit la saisie utilisateur en float, en acceptant la
    virgule comme séparateur décimal (format français). Chaîne vide
    → 0.0. Public car réutilisé par `pane_identification`."""
    s = (s or "").strip().replace(",", ".")
    if not s:
        return 0.0
    return float(s)


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
    """Dialogue de saisie texte thémé (look ttk Silvavenir).

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
    ttk.Button(btns, text="Annuler", style="Ghost.TButton",
               command=dlg.destroy).pack(side="right", padx=6)
    ttk.Button(btns, text="Valider", style="Accent.TButton",
               command=ok).pack(side="right")

    dlg.bind("<Return>", lambda e: ok())
    dlg.bind("<Escape>", lambda e: dlg.destroy())

    _make_modal(dlg, parent)
    entry.focus_set()
    dlg.wait_window()
    return result["val"]


# ---------------------------------------------------------------------
# Dialog : Forme du tronc (éditeur avancé — section ovale)
# ---------------------------------------------------------------------

def ask_forme_tronc(parent: tk.Misc, *, grand_axe_cm: float,
                    petit_axe_cm: float, orientation_grade: int
                    ) -> Optional[Tuple[float, int]]:
    """Éditeur avancé de la forme de la section du tronc.

    Volontairement séparé du formulaire Identification pour ne pas alourdir
    la saisie courante (cas par défaut = section circulaire). Permet de
    définir une section **ovale** (ellipse) : demi-petit-axe + orientation
    du grand axe. Le grand axe (= rayon du tronc) est affiché en référence
    et reste piloté par le formulaire — on ne l'édite pas ici pour garder
    une source de vérité unique.

    Renvoie `(petit_axe_cm, orientation_grade)` si validé, `None` si annulé.
    Petit axe vide ou 0 ⟹ section circulaire. (Pensé comme point d'entrée
    du futur éditeur de cépées / brins.)
    """
    dlg = tk.Toplevel(parent)
    dlg.title("Forme du tronc")
    dlg.configure(bg=COLOR_PANEL)
    dlg.resizable(False, False)
    dlg.columnconfigure(0, weight=1)
    result: dict[str, Optional[Tuple[float, int]]] = {"val": None}

    v_petit = tk.StringVar(value=f"{petit_axe_cm:g}" if petit_axe_cm else "")
    v_orient = tk.StringVar(
        value=f"{orientation_grade:g}" if petit_axe_cm else "")
    vcmd = (dlg.register(validate_numeric), "%P")

    ttk.Label(dlg, text=f"Grand axe (rayon du tronc) : {grand_axe_cm:g} cm",
              background=COLOR_PANEL, justify="left").grid(
        row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(12, 8))

    form = ttk.Frame(dlg, style="Panel.TFrame")
    form.grid(row=1, column=0, sticky="we", padx=12)
    form.columnconfigure(1, weight=1)
    ttk.Label(form, text="Petit axe — rayon (cm)",
              style="Panel.TLabel").grid(row=0, column=0, sticky="w",
                                         pady=4, padx=(0, 10))
    e_petit = ttk.Entry(form, textvariable=v_petit, width=14,
                        validate="key", validatecommand=vcmd)
    e_petit.grid(row=0, column=1, sticky="we", pady=4)
    ttk.Label(form, text="Orientation grand axe (gr)",
              style="Panel.TLabel").grid(row=1, column=0, sticky="w",
                                         pady=4, padx=(0, 10))
    ttk.Entry(form, textvariable=v_orient, width=14,
              validate="key", validatecommand=vcmd).grid(
        row=1, column=1, sticky="we", pady=4)

    ttk.Label(dlg,
              text="Laissez le petit axe vide pour une section circulaire.\n"
                   "Sinon : ellipse de demi-grand-axe = rayon du tronc,\n"
                   "orientée selon l'orientation (0 gr = Nord-Sud).",
              background=COLOR_PANEL, foreground=COLOR_MUTED,
              font=ui_font("Helvetica", 9, "italic"),
              justify="left").grid(row=2, column=0, sticky="w",
                                   padx=12, pady=(8, 6))

    def ok() -> None:
        rp = v_petit.get().strip()
        ro = v_orient.get().strip()
        petit = to_float(rp) if rp else 0.0
        orient = to_float(ro) if ro else 0.0
        result["val"] = (max(0.0, petit), int(round(orient)) % 400)
        dlg.destroy()

    btns = ttk.Frame(dlg, style="Panel.TFrame")
    btns.grid(row=3, column=0, sticky="e", padx=12, pady=(8, 12))
    ttk.Button(btns, text="Annuler", style="Ghost.TButton",
               command=dlg.destroy).pack(side="right", padx=6)
    ttk.Button(btns, text="Valider", style="Accent.TButton",
               command=ok).pack(side="right")

    dlg.bind("<Return>", lambda e: ok())
    dlg.bind("<Escape>", lambda e: dlg.destroy())

    _make_modal(dlg, parent)
    e_petit.focus_set()
    dlg.wait_window()
    return result["val"]


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

    R = arbre.rayon_tronc_cm if arbre else 0.0

    v_grade = tk.StringVar()
    v_sain = tk.StringVar(value=f"{sondage.bois_sain_cm:g}")
    v_alt = tk.StringVar(value=f"{sondage.bois_altere_cm:g}")
    v_comp = tk.StringVar(value=sondage.compartimentation)
    v_com = tk.StringVar(value=sondage.commentaire)
    result = {"ok": False}
    syncing: List[bool] = [False]

    grade_choices = _grade_choices()
    v_grade.set(_find_grade_choice(grade_choices, sondage.grade))


    # Bandeau rappelant le rayon (référence pour le calcul auto)
    if R > 0:
        rappel = (f"Rayon du tronc de cet arbre : {R:g} cm\n"
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

    ttk.Label(dlg, text="Direction (grade)", background=COLOR_PANEL
              ).grid(row=1, column=0, sticky="w", padx=10, pady=6)
    combo_grade = ttk.Combobox(dlg, textvariable=v_grade,
                               values=grade_choices,
                               state="readonly", width=26)
    combo_grade.grid(row=1, column=1, sticky="we", padx=10, pady=6)

    ttk.Label(dlg, text="Épaisseur bois sain (cm)",
              background=COLOR_PANEL
              ).grid(row=2, column=0, sticky="w", padx=10, pady=6)
    _numeric_entry(dlg, v_sain, width=12
                   ).grid(row=2, column=1, sticky="w", padx=10, pady=6)

    ttk.Label(dlg, text="Épaisseur bois altéré (cm)",
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

    # Migration silencieuse à l'ouverture du dialogue : ancien "-" → libellé lisible.
    if v_comp.get() == "-":
        v_comp.set("non renseignée")
    ttk.Label(dlg, text="Compartimentation", background=COLOR_PANEL
              ).grid(row=4, column=0, sticky="w", padx=10, pady=6)
    ttk.Combobox(dlg, textvariable=v_comp,
                 values=["active", "absente", "non renseignée"],
                 state="readonly", width=18
                 ).grid(row=4, column=1, sticky="w", padx=10, pady=6)

    ttk.Label(dlg, text="Commentaire", background=COLOR_PANEL
              ).grid(row=5, column=0, sticky="w", padx=10, pady=6)
    ttk.Entry(dlg, textvariable=v_com, width=28
              ).grid(row=5, column=1, sticky="we", padx=10, pady=6)

    def ok() -> None:
        try:
            new_grade = _parse_grade(v_grade.get())
            if arbre is not None:
                for other in arbre.sondages:
                    if other is not sondage and other.grade == new_grade:
                        lbl = DIRECTION_LABELS.get(new_grade, "")
                        direction = f" ({lbl})" if lbl else ""
                        messagebox.showwarning(
                            "Direction déjà sondée",
                            f"Un sondage existe déjà au grade "
                            f"{new_grade} gr{direction}.\n\n"
                            "Chaque direction ne peut être sondée "
                            "qu'une seule fois.",
                            parent=dlg)
                        return
            sondage.grade = new_grade
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
            sondage.compartimentation = v_comp.get()
            sondage.commentaire = v_com.get()
            result["ok"] = True
            dlg.destroy()
        except ValueError as e:
            messagebox.showerror("Erreur de saisie",
                                 f"Valeur invalide : {e}", parent=dlg)

    btns = ttk.Frame(dlg, style="Panel.TFrame")
    btns.grid(row=6, column=0, columnspan=2, pady=(10, 12))
    ttk.Button(btns, text="Annuler", style="Ghost.TButton",
               command=dlg.destroy).pack(side="right", padx=6)
    ttk.Button(btns, text="Valider", style="Accent.TButton",
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
    dlg.title(f"Dégradation externe n° {deg.numero}")
    dlg.configure(bg=COLOR_PANEL)
    dlg.resizable(False, False)
    # transient + grab_set : cf. note dans edit_sondage.

    R = arbre.rayon_tronc_cm if arbre else 0.0

    v_debut = tk.StringVar()
    v_fin = tk.StringVar()
    v_largeur_gr = tk.StringVar(value=str(deg.largeur_grades()))
    v_largeur_cm = tk.StringVar(value=f"{deg.largeur_cm(R):.1f}")
    v_prof = tk.StringVar(value=f"{deg.profondeur_cm:g}")
    v_com = tk.StringVar(value=deg.commentaire)
    result = {"ok": False}
    syncing: List[bool] = [False]

    grade_choices = _grade_choices()
    v_debut.set(_find_grade_choice(grade_choices, deg.grade_debut))
    v_fin.set(_find_grade_choice(grade_choices, deg.grade_fin))


    ttk.Label(dlg, text="Direction de début (grade)",
              background=COLOR_PANEL).grid(row=0, column=0,
                                           sticky="w", padx=10, pady=6)
    combo_debut = ttk.Combobox(dlg, textvariable=v_debut,
                               values=grade_choices,
                               state="readonly", width=24)
    combo_debut.grid(row=0, column=1, sticky="we", padx=10, pady=6)

    ttk.Label(dlg, text="Direction de fin (grade, sens horaire)",
              background=COLOR_PANEL).grid(row=1, column=0,
                                           sticky="w", padx=10, pady=6)
    ttk.Combobox(dlg, textvariable=v_fin, values=grade_choices,
                 state="readonly", width=24
                 ).grid(row=1, column=1, sticky="we", padx=10, pady=6)

    ttk.Label(dlg, text="— ou —", background=COLOR_PANEL,
              foreground=COLOR_MUTED, font=ui_font("Helvetica", 9, "italic")
              ).grid(row=2, column=0, columnspan=2, pady=(2, 2))

    ttk.Label(dlg, text="Largeur en grades",
              background=COLOR_PANEL).grid(row=3, column=0,
                                           sticky="w", padx=10, pady=6)
    _numeric_entry(dlg, v_largeur_gr, width=12
                   ).grid(row=3, column=1, sticky="w", padx=10, pady=6)

    ttk.Label(dlg, text="Largeur en cm (sur l'écorce)",
              background=COLOR_PANEL).grid(row=4, column=0,
                                           sticky="w", padx=10, pady=6)
    _numeric_entry(dlg, v_largeur_cm, width=12
                   ).grid(row=4, column=1, sticky="w", padx=10, pady=6)

    ttk.Label(dlg, text="Profondeur (cm, depuis l'écorce)",
              background=COLOR_PANEL).grid(row=5, column=0,
                                           sticky="w", padx=10, pady=6)
    _numeric_entry(dlg, v_prof, width=12
                   ).grid(row=5, column=1, sticky="w", padx=10, pady=6)

    ttk.Label(dlg, text="Commentaire", background=COLOR_PANEL
              ).grid(row=6, column=0, sticky="w", padx=10, pady=6)
    ttk.Entry(dlg, textvariable=v_com, width=28
              ).grid(row=6, column=1, sticky="we", padx=10, pady=6)

    # --- Liens auto entre fin / largeur_gr / largeur_cm -------------
    def _on_fin(*_: object) -> None:
        if syncing[0]:
            return
        try:
            d = _parse_grade(v_debut.get())
            f = _parse_grade(v_fin.get())
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
            d = _parse_grade(v_debut.get())
            f = (d + gr) % 400
            syncing[0] = True
            v_fin.set(_find_grade_choice(grade_choices, f))
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
            d = _parse_grade(v_debut.get())
            f = (d + gr) % 400
            syncing[0] = True
            v_largeur_gr.set(str(gr))
            v_fin.set(_find_grade_choice(grade_choices, f))
            syncing[0] = False
        except (ValueError, IndexError, ZeroDivisionError):
            pass

    v_debut.trace_add("write", _on_fin)
    v_fin.trace_add("write", _on_fin)
    v_largeur_gr.trace_add("write", _on_largeur_gr)
    v_largeur_cm.trace_add("write", _on_largeur_cm)

    def ok() -> None:
        try:
            new_debut = _parse_grade(v_debut.get())
            new_fin = _parse_grade(v_fin.get())
            if arbre is not None:
                candidate = DegradationExterne(
                    grade_debut=new_debut, grade_fin=new_fin)
                for other in arbre.degradations_externes:
                    if other is not deg:
                        shared = [g for g in GRADES
                                  if candidate.couvre_grade(g)
                                  and other.couvre_grade(g)
                                  and not (g == new_debut
                                           and g == other.grade_fin)
                                  and not (g == new_fin
                                           and g == other.grade_debut)]
                        if shared:
                            labels = ", ".join(
                                f"{g} gr" for g in shared[:4])
                            if len(shared) > 4:
                                labels += ", …"
                            messagebox.showwarning(
                                "Chevauchement de dégradations",
                                f"La dégradation n°{other.numero} "
                                f"({other.grade_debut} gr → "
                                f"{other.grade_fin} gr) couvre "
                                f"déjà les directions {labels}.\n\n"
                                f"Les arcs ne doivent pas se "
                                f"chevaucher.",
                                parent=dlg)
                            return
            deg.grade_debut = new_debut
            deg.grade_fin = new_fin
            deg.profondeur_cm = max(0.0, to_float(v_prof.get()))
            deg.commentaire = v_com.get()
            result["ok"] = True
            dlg.destroy()
        except (ValueError, IndexError) as e:
            messagebox.showerror("Erreur de saisie",
                                 f"Valeur invalide : {e}", parent=dlg)

    btns = ttk.Frame(dlg, style="Panel.TFrame")
    btns.grid(row=7, column=0, columnspan=2, pady=(10, 12))
    ttk.Button(btns, text="Annuler", style="Ghost.TButton",
               command=dlg.destroy).pack(side="right", padx=6)
    ttk.Button(btns, text="Valider", style="Accent.TButton",
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

    grade_choices = _grade_choices()
    v_centre.set(_find_grade_choice(grade_choices, cf.grade_centre))


    ttk.Label(dlg, text="Orientation (grade central)",
              background=COLOR_PANEL).grid(row=0, column=0,
                                           sticky="w", padx=10, pady=6)
    combo_centre = ttk.Combobox(dlg, textvariable=v_centre,
                                values=grade_choices,
                                state="readonly", width=24)
    combo_centre.grid(row=0, column=1, sticky="we", padx=10, pady=6)

    ttk.Label(dlg, text="Largeur en grades (multiple de 25)",
              background=COLOR_PANEL).grid(row=1, column=0,
                                           sticky="w", padx=10, pady=6)
    _numeric_entry(dlg, v_largeur_gr, width=12
                   ).grid(row=1, column=1, sticky="w", padx=10, pady=6)

    ttk.Label(dlg, text="Largeur en cm (sur l'écorce)",
              background=COLOR_PANEL).grid(row=2, column=0,
                                           sticky="w", padx=10, pady=6)
    _numeric_entry(dlg, v_largeur_cm, width=12
                   ).grid(row=2, column=1, sticky="w", padx=10, pady=6)

    ttk.Label(dlg, text="Longueur radiale (cm, vers l'extérieur)",
              background=COLOR_PANEL).grid(row=3, column=0,
                                           sticky="w", padx=10, pady=6)
    _numeric_entry(dlg, v_long, width=12
                   ).grid(row=3, column=1, sticky="w", padx=10, pady=6)

    ttk.Label(dlg, text="Commentaire", background=COLOR_PANEL
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
            new_centre = _parse_grade(v_centre.get()) % 400
            if arbre is not None:
                for other in arbre.contreforts:
                    if other is not cf and other.grade_centre == new_centre:
                        lbl = DIRECTION_LABELS.get(new_centre, "")
                        direction = f" ({lbl})" if lbl else ""
                        messagebox.showwarning(
                            "Contrefort en double",
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
            messagebox.showerror("Erreur de saisie",
                                 f"Valeur invalide : {e}", parent=dlg)

    btns = ttk.Frame(dlg, style="Panel.TFrame")
    btns.grid(row=5, column=0, columnspan=2, pady=(10, 12))
    ttk.Button(btns, text="Annuler", style="Ghost.TButton",
               command=dlg.destroy).pack(side="right", padx=6)
    ttk.Button(btns, text="Valider", style="Accent.TButton",
               command=ok).pack(side="right")

    # Entrée valide, Échap annule (cf. edit_sondage).
    dlg.bind("<Return>", lambda e: ok())
    dlg.bind("<Escape>", lambda e: dlg.destroy())

    _make_modal(dlg, parent)
    combo_centre.focus_set()  # focus sur le 1er champ utile
    dlg.wait_window()
    return result["ok"]
