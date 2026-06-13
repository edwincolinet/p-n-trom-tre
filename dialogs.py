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
from typing import Any, List, Optional, Tuple, Union

from geometry import DIRECTION_LABELS, GRADES, brins_layout, contour_polygon
from model import (
    Arbre,
    Brin,
    Contrefort,
    DegradationExterne,
    Sondage,
    degradations_chevauchements,
)
from palette import COLOR_ACCENT, COLOR_ACCENT_SOFT, COLOR_BG, COLOR_INK, COLOR_MUTED, COLOR_PANEL, COLOR_WOOD
from ui_fonts import font as ui_font

# Les dialogues d'édition (sondage/dégradation/contrefort) ne lisent que de la
# géométrie (`rayon_tronc_cm`) et la liste de mesures concernée — présentes
# aussi bien sur un `Arbre` (relais de compat → brins[0]) que sur un `Brin`
# natif. Accepter les deux permet d'éditer un brin précis d'une cépée (le
# sélecteur de brin de l'Étape 4) sans passer par les relais brins[0].
Section = Union[Arbre, Brin]


def grade_choices() -> list[str]:
    """Libellés des 16 directions, format `"100 gr — E"`.

    Public (avec `find_grade_choice` / `parse_grade`) car réutilisé par
    les combobox de saisie en place de `pane_degradations`."""
    out = []
    for g in GRADES:
        lbl = DIRECTION_LABELS.get(g, "")
        out.append(f"{g} gr" + (f" — {lbl}" if lbl else ""))
    return out


def find_grade_choice(choices: list[str], grade_value: int) -> str:
    """Renvoie l'entrée de `choices` qui commence par `<grade_value> gr`."""
    for c in choices:
        if c.startswith(f"{grade_value} gr"):
            return c
    return choices[0]


def parse_grade(s: str) -> int:
    """Extrait le grade entier d'une chaîne `"100 gr — E"` (tolère
    aussi l'ancien format `"100° — E"`)."""
    return int(s.replace("°", " ").split(" ")[0].strip())


def message_chevauchement(other: DegradationExterne,
                          shared: List[int]) -> str:
    """Texte d'avertissement quand un arc candidat chevauche `other`
    (cf. `model.degradations_chevauchements`). Partagé entre le dialogue
    `edit_degradation` et la saisie en place de `pane_degradations`."""
    labels = ", ".join(f"{g} gr" for g in shared[:4])
    if len(shared) > 4:
        labels += ", …"
    return (f"La dégradation n°{other.numero} ({other.grade_debut} gr → "
            f"{other.grade_fin} gr) couvre déjà les directions "
            f"{labels}.\n\nLes arcs ne doivent pas se chevaucher.")


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
# Dialog : Disposition d'une cépée (placement des brins à la souris)
# ---------------------------------------------------------------------

def ask_cepee_layout(parent: tk.Misc,
                     arbre: Arbre
                     ) -> Optional[List[Tuple[float, float, int]]]:
    """Éditeur de disposition d'une cépée : place et oriente les brins.

    Affiche tous les brins du genet (contour fidèle — cercle ou ellipse
    orientée) dans un canvas. On **glisse** un brin pour fixer sa position
    `(pos_x_cm, pos_y_cm)` dans le plan du genet ; la **molette** (au-dessus
    d'un brin) le fait **pivoter** par pas de 25 gr (`rotation_grades`). Le
    1er brin (« a ») est l'**ancre** du repère (origine en (0, 0)) : sa
    position reste fixe (il peut quand même pivoter), les autres se placent
    autour de lui (cf. décision du plan cépées).

    Travaille sur une **copie** → « Annuler » n'a aucun effet. Renvoie la liste
    `[(pos_x_cm, pos_y_cm, rotation_grades), ...]` (un triplet par brin, dans
    l'ordre des brins) si validé, `None` si annulé.

    L'échelle et l'origine du dessin sont figées à l'ouverture (calculées sur
    les positions initiales, avec une marge généreuse) : le dessin ne « saute »
    pas pendant le glissement.
    """
    brins = arbre.brins
    positions: List[List[float]] = [[b.pos_x_cm, b.pos_y_cm] for b in brins]
    rotations: List[int] = [int(b.rotation_grades) % 400 for b in brins]
    extents = [max(1.0, b.extent_cm()) for b in brins]

    dlg = tk.Toplevel(parent)
    dlg.title("Disposition de la cépée")
    dlg.configure(bg=COLOR_PANEL)
    dlg.resizable(False, False)
    dlg.columnconfigure(0, weight=1)
    result: dict[str, Optional[List[Tuple[float, float, int]]]] = {"val": None}

    W = H = 440.0
    MARGIN = 70.0  # marge large → headroom pour glisser hors de la bbox initiale
    scale, origin_x, origin_y = brins_layout(
        [(positions[i][0], positions[i][1], extents[i])
         for i in range(len(brins))],
        W, H, MARGIN, MARGIN, MARGIN)

    cv = tk.Canvas(dlg, width=int(W), height=int(H), bg=COLOR_BG,
                   highlightthickness=0, cursor="hand2")
    cv.grid(row=0, column=0, padx=12, pady=(12, 6))

    state: dict[str, Any] = {"drag": None, "gx": 0.0, "gy": 0.0}

    def to_px(x: float, y: float) -> Tuple[float, float]:
        return origin_x + x * scale, origin_y + y * scale

    def to_cm(px: float, py: float) -> Tuple[float, float]:
        return (px - origin_x) / scale, (py - origin_y) / scale

    def redraw() -> None:
        cv.delete("all")
        for i, b in enumerate(brins):
            cx, cy = to_px(positions[i][0], positions[i][1])
            pts = contour_polygon(b.rayon_a_grade, cx, cy, scale,
                                  rotation_grades=rotations[i])
            flat = [c for p in pts for c in p]
            anchor = (i == 0)
            fill = COLOR_ACCENT_SOFT if anchor else COLOR_WOOD
            outline = COLOR_ACCENT if i == state["drag"] else COLOR_INK
            cv.create_polygon(*flat, fill=fill, outline=outline, width=2)
            label = b.label or chr(ord("a") + i)
            rot_txt = f" · {rotations[i]} gr" if rotations[i] else ""
            txt = (f"{label} · ancre{rot_txt}" if anchor
                   else f"{label}{rot_txt}")
            cv.create_text(cx, cy, text=txt, fill=COLOR_INK,
                           font=ui_font("Helvetica", 11, "bold"))

    def brin_at(px: float, py: float) -> Optional[int]:
        # Brins dessinés dans l'ordre ; on teste du dernier au premier pour
        # attraper celui « au-dessus » en cas de chevauchement.
        for i in reversed(range(len(brins))):
            cx, cy = to_px(positions[i][0], positions[i][1])
            rr = max(brins[i].rayon_tronc_cm, 1.0) * scale
            if (px - cx) ** 2 + (py - cy) ** 2 <= rr * rr:
                return i
        return None

    def on_press(e: "tk.Event[tk.Misc]") -> None:
        i = brin_at(e.x, e.y)
        if i is None or i == 0:  # rien, ou l'ancre (non déplaçable)
            return
        mx, my = to_cm(e.x, e.y)
        state["drag"] = i
        state["gx"] = mx - positions[i][0]
        state["gy"] = my - positions[i][1]
        redraw()

    def on_motion(e: "tk.Event[tk.Misc]") -> None:
        i = state["drag"]
        if i is None:
            return
        mx, my = to_cm(e.x, e.y)
        positions[i][0] = mx - state["gx"]
        positions[i][1] = my - state["gy"]
        redraw()

    def on_release(_e: "tk.Event[tk.Misc]") -> None:
        state["drag"] = None
        redraw()

    def on_wheel(e: "tk.Event[tk.Misc]") -> None:
        # Molette au-dessus d'un brin : rotation de ±25 gr. Sous Linux/X11
        # Tk émet <Button-4> (haut) / <Button-5> (bas) ; ailleurs <MouseWheel>
        # avec e.delta. On ramène à un pas signé.
        i = brin_at(e.x, e.y)
        if i is None:
            return
        if getattr(e, "num", 0) == 4 or getattr(e, "delta", 0) > 0:
            step = 25
        elif getattr(e, "num", 0) == 5 or getattr(e, "delta", 0) < 0:
            step = -25
        else:
            return
        rotations[i] = (rotations[i] + step) % 400
        redraw()

    cv.bind("<Button-1>", on_press)
    cv.bind("<B1-Motion>", on_motion)
    cv.bind("<ButtonRelease-1>", on_release)
    cv.bind("<MouseWheel>", on_wheel)      # Windows / macOS
    cv.bind("<Button-4>", on_wheel)        # Linux/X11 molette haut
    cv.bind("<Button-5>", on_wheel)        # Linux/X11 molette bas

    ttk.Label(
        dlg,
        text="Glissez un brin pour le positionner ; molette au-dessus d'un "
             "brin pour le faire pivoter (pas de 25 gr). Le brin « a » est "
             "l'ancre du repère (position fixe ; il peut pivoter).",
        background=COLOR_PANEL, foreground=COLOR_MUTED,
        font=ui_font("Helvetica", 9, "italic"),
        wraplength=int(W), justify="left").grid(
        row=1, column=0, sticky="w", padx=12, pady=(0, 6))

    def ok() -> None:
        result["val"] = [(round(positions[i][0], 3), round(positions[i][1], 3),
                          rotations[i]) for i in range(len(brins))]
        dlg.destroy()

    btns = ttk.Frame(dlg, style="Panel.TFrame")
    btns.grid(row=2, column=0, sticky="e", padx=12, pady=(2, 12))
    ttk.Button(btns, text="Annuler", style="Ghost.TButton",
               command=dlg.destroy).pack(side="right", padx=6)
    ttk.Button(btns, text="Valider", style="Accent.TButton",
               command=ok).pack(side="right")

    dlg.bind("<Return>", lambda e: ok())
    dlg.bind("<Escape>", lambda e: dlg.destroy())

    redraw()
    _make_modal(dlg, parent)
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

    choices = grade_choices()
    v_grade.set(find_grade_choice(choices, sondage.grade))


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
                               values=choices,
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
            new_grade = parse_grade(v_grade.get())
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
    v_ecorce = tk.BooleanVar(value=deg.comprend_ecorce)
    v_com = tk.StringVar(value=deg.commentaire)
    result = {"ok": False}
    syncing: List[bool] = [False]

    choices = grade_choices()
    v_debut.set(find_grade_choice(choices, deg.grade_debut))
    v_fin.set(find_grade_choice(choices, deg.grade_fin))


    ttk.Label(dlg, text="Direction de début (grade)",
              background=COLOR_PANEL).grid(row=0, column=0,
                                           sticky="w", padx=10, pady=6)
    combo_debut = ttk.Combobox(dlg, textvariable=v_debut,
                               values=choices,
                               state="readonly", width=24)
    combo_debut.grid(row=0, column=1, sticky="we", padx=10, pady=6)

    ttk.Label(dlg, text="Direction de fin (grade, sens horaire)",
              background=COLOR_PANEL).grid(row=1, column=0,
                                           sticky="w", padx=10, pady=6)
    ttk.Combobox(dlg, textvariable=v_fin, values=choices,
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

    ttk.Label(dlg, text="Profondeur radiale (cm)",
              background=COLOR_PANEL).grid(row=5, column=0,
                                           sticky="w", padx=10, pady=6)
    _numeric_entry(dlg, v_prof, width=12
                   ).grid(row=5, column=1, sticky="w", padx=10, pady=6)

    ttk.Checkbutton(
        dlg, variable=v_ecorce,
        text="La dégradation comprend l'écorce (sinon : commence sous l'écorce)",
        style="Panel.TCheckbutton"
    ).grid(row=6, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 6))

    ttk.Label(dlg, text="Commentaire", background=COLOR_PANEL
              ).grid(row=7, column=0, sticky="w", padx=10, pady=6)
    ttk.Entry(dlg, textvariable=v_com, width=28
              ).grid(row=7, column=1, sticky="we", padx=10, pady=6)

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
                        "Chevauchement de dégradations",
                        message_chevauchement(other, shared),
                        parent=dlg)
                    return
            deg.grade_debut = new_debut
            deg.grade_fin = new_fin
            deg.profondeur_cm = max(0.0, to_float(v_prof.get()))
            deg.comprend_ecorce = bool(v_ecorce.get())
            deg.commentaire = v_com.get()
            result["ok"] = True
            dlg.destroy()
        except (ValueError, IndexError) as e:
            messagebox.showerror("Erreur de saisie",
                                 f"Valeur invalide : {e}", parent=dlg)

    btns = ttk.Frame(dlg, style="Panel.TFrame")
    btns.grid(row=8, column=0, columnspan=2, pady=(10, 12))
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

    choices = grade_choices()
    v_centre.set(find_grade_choice(choices, cf.grade_centre))


    ttk.Label(dlg, text="Orientation (grade central)",
              background=COLOR_PANEL).grid(row=0, column=0,
                                           sticky="w", padx=10, pady=6)
    combo_centre = ttk.Combobox(dlg, textvariable=v_centre,
                                values=choices,
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
            new_centre = parse_grade(v_centre.get()) % 400
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
