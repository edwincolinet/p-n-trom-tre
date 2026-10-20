"""Éditeur de disposition d'une cépée (placement des brins à la souris).

Extrait de `dialogs.py` (2026-08-25) : `ask_cepee_layout` est un éditeur
canvas autonome, sans dépendance vers les dialogues d'édition
Sondage/Dégradation/Contrefort — seul point commun avec `dialogs.py` :
le helper `_make_modal`.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, List, Optional, Tuple

import angle_units
from dialogs import _make_modal
from geometry import brins_layout, contour_polygon, ring_polygon_points
from i18n import _
from model import Arbre, Brin
from palette import (
    COLOR_ACCENT,
    COLOR_ACCENT_SOFT,
    COLOR_BARK,
    COLOR_BG,
    COLOR_INK,
    COLOR_MUTED,
    COLOR_PANEL,
    COLOR_WOOD,
)
from ui_fonts import font_small_italic, font_subheading


def ask_cepee_layout(parent: tk.Misc,
                     arbre: Arbre
                     ) -> Optional[List[Tuple[float, float, int]]]:
    """Éditeur de disposition d'une cépée : place et oriente les brins.

    Affiche tous les brins du genet (contour fidèle — cercle ou rayon
    variable par direction, **écorce comprise** si mesurée) dans un canvas
    — sans l'anneau d'écorce, deux brins dont le bois seul ne se touche pas
    peuvent en réalité se chevaucher une fois l'écorce comptée, ce qui
    trompait l'opérateur pendant le placement. On **glisse** un brin pour fixer
    sa position `(pos_x_cm, pos_y_cm)` dans le plan du genet ; la **molette** (au-dessus
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
            ep = max(0.0, b.epaisseur_ecorce_cm)
            inner = contour_polygon(b.rayon_a_grade, cx, cy, scale,
                                    rotation_grades=rotations[i])
            anchor = (i == 0)
            fill = COLOR_ACCENT_SOFT if anchor else COLOR_WOOD
            outline = COLOR_ACCENT if i == state["drag"] else COLOR_INK
            if ep > 0:
                # Anneau d'écorce dessiné AUSSI ici : sans lui, deux brins
                # dont l'écorce mesurée se touche/chevauche apparaissaient
                # avec un écart (seul le bois était tracé) — trompeur pour
                # juger le chevauchement pendant le placement.
                def r_outer(g: float, b: "Brin" = b) -> float:
                    return b.rayon_a_grade(g) + ep
                outer = contour_polygon(r_outer, cx, cy, scale,
                                        rotation_grades=rotations[i])
                ring = ring_polygon_points(outer, inner)
                cv.create_polygon(*[c for p in ring for c in p],
                                  fill=COLOR_BARK, outline=outline, width=2)
                cv.create_polygon(*[c for p in inner for c in p],
                                  fill=fill, outline="")
            else:
                cv.create_polygon(*[c for p in inner for c in p],
                                  fill=fill, outline=outline, width=2)
            label = b.label or chr(ord("a") + i)
            rot_txt = f" · {angle_units.fmt(rotations[i])}" if rotations[i] else ""
            txt = (f"{label} · ancre{rot_txt}" if anchor
                   else f"{label}{rot_txt}")
            cv.create_text(cx, cy, text=txt, fill=COLOR_INK,
                           font=font_subheading())

    def brin_at(px: float, py: float) -> Optional[int]:
        # Brins dessinés dans l'ordre ; on teste du dernier au premier pour
        # attraper celui « au-dessus » en cas de chevauchement.
        for i in reversed(range(len(brins))):
            cx, cy = to_px(positions[i][0], positions[i][1])
            b = brins[i]
            rr = max(b.rayon_tronc_cm + max(0.0, b.epaisseur_ecorce_cm),
                     1.0) * scale
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
        text=_("Glissez un brin pour le positionner")
             + " ; molette au-dessus d'un brin pour le faire pivoter "
             f"(pas de {angle_units.fmt(25)}).",
        background=COLOR_PANEL, foreground=COLOR_MUTED,
        font=font_small_italic(),
        wraplength=int(W), justify="left").grid(
        row=1, column=0, sticky="w", padx=12, pady=(0, 6))

    def ok() -> None:
        result["val"] = [(round(positions[i][0], 3), round(positions[i][1], 3),
                          rotations[i]) for i in range(len(brins))]
        dlg.destroy()

    btns = ttk.Frame(dlg, style="Panel.TFrame")
    btns.grid(row=2, column=0, sticky="e", padx=12, pady=(2, 12))
    ttk.Button(btns, text=_("Annuler"), style="Ghost.TButton",
               command=dlg.destroy).pack(side="right", padx=6)
    ttk.Button(btns, text=_("Valider"), style="Accent.TButton",
               command=ok).pack(side="right")

    dlg.bind("<Return>", lambda e: ok())
    dlg.bind("<Escape>", lambda e: dlg.destroy())

    redraw()
    _make_modal(dlg, parent)
    dlg.wait_window()
    return result["val"]
