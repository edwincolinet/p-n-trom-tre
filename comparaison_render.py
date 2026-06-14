"""
Rendu PIL de la comparaison inter-missions (ré-inspection) :

- `render_evolution_heatmap` : « carte de différence » — une rose des 16
  directions colorée par l'aggravation de l'altération (ΔPRBS) entre la
  campagne de référence et la campagne courante (rouge = bois sain perdu).
- `render_comparison_page` : page A4 paysage livrable (en-tête, les deux
  sections + la heatmap, tableau chiffré, verdict) — exportable en PNG et
  en PDF (cf. `app_exports`).

Module sans Tk (PIL pur). Les calculs viennent de `diagnostic`
(`ComparaisonDetail`, `verdict_evolution`).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, List, Optional, Tuple

from diagnostic import verdict_evolution
from geometry import GRADES
from palette import COLOR_ACCENT, COLOR_INK, COLOR_MUTED
from pil_render import _pil_load_fonts, render_arbre_to_pil_image

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage

    from diagnostic import ComparaisonDetail
    from model import Arbre

# Grade → angle PIL (degrés, 0 à 3 h, sens horaire). 360/400 = 0.9 ; le
# Nord (grade 0) est en haut → −90°.
_GR_TO_DEG = 0.9
_NEUTRE = (238, 232, 216)
_ROUGE = (176, 30, 20)
_VERT = (45, 122, 62)
_VIDE = (224, 224, 220)


def _lerp(c0: Tuple[int, int, int], c1: Tuple[int, int, int],
          t: float) -> Tuple[int, int, int]:
    return (int(round(c0[0] + (c1[0] - c0[0]) * t)),
            int(round(c0[1] + (c1[1] - c0[1]) * t)),
            int(round(c0[2] + (c1[2] - c0[2]) * t)))


def _heat_color(delta: float, max_abs: float) -> Tuple[int, int, int]:
    """Couleur d'un secteur selon ΔPRBS : rouge (perte de bois sain),
    neutre (stable), vert (gain, rare). Intensité normalisée sur `max_abs`."""
    if max_abs <= 0:
        return _NEUTRE
    t = max(-1.0, min(1.0, delta / max_abs))
    return _lerp(_NEUTRE, _ROUGE, -t) if t < 0 else _lerp(_NEUTRE, _VERT, t)


def render_evolution_heatmap(detail: "ComparaisonDetail",
                             size: int = 460) -> "PILImage":
    """Rose des 16 directions colorée par l'évolution de l'altération."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (size, size), "white")
    d = ImageDraw.Draw(img)
    f = _pil_load_fonts()
    cx, cy = size / 2.0, size * 0.40
    R = size * 0.31
    by_grade = {dd.grade: dd for dd in detail.directions}
    max_abs = max((abs(dd.delta) for dd in detail.directions), default=0.0)

    for g in GRADES:
        a0 = (g - 12.5) * _GR_TO_DEG - 90
        a1 = (g + 12.5) * _GR_TO_DEG - 90
        dd = by_grade.get(g)
        fill = _VIDE if dd is None else _heat_color(dd.delta, max_abs)
        outline = (200, 200, 196) if dd is None else (110, 110, 106)
        d.pieslice([cx - R, cy - R, cx + R, cy + R], a0, a1,
                   fill=fill, outline=outline)
    d.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=(60, 60, 56))

    for g, lbl in ((0, "N"), (100, "E"), (200, "S"), (300, "O")):
        ang = math.radians(g * _GR_TO_DEG - 90)
        lx = cx + (R + 20) * math.cos(ang)
        ly = cy + (R + 20) * math.sin(ang)
        d.text((lx, ly), lbl, font=f(int(size * 0.046), "serif_bold"),
               fill=COLOR_INK, anchor="mm")

    # Échelle de couleur (barre dégradé rouge → neutre) sous la rose.
    bar_y = size * 0.86
    bx0, bx1 = size * 0.16, size * 0.84
    steps = 60
    for i in range(steps):
        t = i / (steps - 1)
        col = _lerp(_ROUGE, _NEUTRE, t)
        x = bx0 + (bx1 - bx0) * t
        d.rectangle([x, bar_y, x + (bx1 - bx0) / steps + 1, bar_y + 12],
                    fill=col)
    sf = f(int(size * 0.030), "sans")
    perte = f"−{max_abs:.1f} cm" if max_abs > 0 else "perte"
    d.text((bx0, bar_y + 16), perte, font=sf, fill=COLOR_MUTED, anchor="lt")
    d.text((bx1, bar_y + 16), "stable", font=sf, fill=COLOR_MUTED, anchor="rt")
    d.text((cx, bar_y - 6), "Bois sain perdu par direction",
           font=sf, fill=COLOR_MUTED, anchor="mb")
    return img


def _classe_aff(classe: Optional[str]) -> str:
    return classe if classe else "non publié"


def _pct_aff(v: Optional[float]) -> str:
    return f"{v:.1f} %" if v is not None else "—"


def metric_rows(detail: "ComparaisonDetail") -> List[Tuple[str, str, str, str]]:
    """Lignes du tableau chiffré : (libellé, référence, courant, évolution).
    Partagé par la fenêtre Tk et la page d'export."""
    rows: List[Tuple[str, str, str, str]] = []
    # Classe globale
    rows.append(("Classe globale", _classe_aff(detail.classe_ref),
                 _classe_aff(detail.classe_cur), ""))
    # t/R moyen
    evo_tr = ""
    if detail.tR_moy_ref is not None and detail.tR_moy_cur is not None:
        dpts = detail.tR_moy_cur - detail.tR_moy_ref
        evo_tr = f"{dpts:+.1f} pts"
    rows.append(("t/R moyen", _pct_aff(detail.tR_moy_ref),
                 _pct_aff(detail.tR_moy_cur), evo_tr))
    # PRBS moyenne (directions communes)
    evo_prbs = ""
    if detail.delta_prbs_moy is not None:
        evo_prbs = f"{detail.delta_prbs_moy:+.2f} cm"
    rows.append(("PRBS moyenne (dir. communes)",
                 f"{detail.prbs_moy_ref:.2f} cm" if detail.prbs_moy_ref is not None else "—",
                 f"{detail.prbs_moy_cur:.2f} cm" if detail.prbs_moy_cur is not None else "—",
                 evo_prbs))
    # Taux de perte cm/an
    if detail.taux_cm_an is not None:
        rows.append(("Perte de bois sain", "—", "—",
                     f"{detail.taux_cm_an:.2f} cm/an"))
    else:
        rows.append(("Perte de bois sain", "—", "—",
                     "n/a (missions non datées)"))
    # Compartimentation
    rows.append(("Compartimentation perdue (active→absente)", "—", "—",
                 f"{detail.compart_aggravees} direction(s)"))
    # Pire direction
    if detail.pire is not None:
        rows.append(("Direction la plus aggravée", "—", "—",
                     f"{detail.pire.direction} ({detail.pire.grade} gr) : "
                     f"{detail.pire.delta:+.2f} cm"))
    return rows


def render_comparison_page(mission_nom: str, ref_arbre: "Arbre",
                           cur_arbre: "Arbre", detail: "ComparaisonDetail",
                           *, ref_label: str, cur_label: str) -> "PILImage":
    """Page A4 paysage (1754×1240 @150 DPI) : en-tête, les deux sections +
    la heatmap d'évolution, tableau chiffré, verdict. Exportable PNG/PDF."""
    from PIL import Image, ImageDraw
    f = _pil_load_fonts()
    W, H = 1754, 1240
    page = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(page)
    margin = 54

    # En-tête vert.
    d.rectangle([0, 0, W, 92], fill=COLOR_ACCENT)
    d.text((margin, 20),
           f"Comparaison d'inspections — {cur_arbre.display_name}",
           font=f(30, "serif_bold"), fill="white")
    d.text((margin, 62),
           f"Mission « {mission_nom or 'Mission'} »   •   "
           f"Référence : {ref_label}   →   Courant : {cur_label}",
           font=f(17, "sans"), fill="white")

    # Trois sections côte à côte.
    gap = 24
    sec = (W - 2 * margin - 2 * gap) // 3       # ≈ 540
    y_lbl = 116
    y_img = y_lbl + 34
    titres = [(f"Référence — {ref_label}", ref_arbre),
              (f"Courant — {cur_label}", cur_arbre)]
    for i, (titre, arbre) in enumerate(titres):
        x = margin + i * (sec + gap)
        d.text((x, y_lbl), titre, font=f(18, "sans_bold"), fill=COLOR_INK)
        thumb = render_arbre_to_pil_image(
            arbre, sec, sec, show_sondages=True, show_title=False,
            show_legend=False)
        page.paste(thumb, (x, y_img))
    # Heatmap.
    x = margin + 2 * (sec + gap)
    d.text((x, y_lbl), "Évolution de l'altération",
           font=f(18, "sans_bold"), fill=COLOR_INK)
    heat = render_evolution_heatmap(detail, sec)
    page.paste(heat, (x, y_img))

    # Tableau chiffré.
    y = y_img + sec + 24
    rows = metric_rows(detail)
    col_x = [margin, margin + 520, margin + 520 + 250,
             margin + 520 + 250 + 250]
    headers = ("Indicateur", "Référence", "Courant", "Évolution")
    head_h = 38
    d.rectangle([margin, y, W - margin, y + head_h], fill=COLOR_ACCENT)
    for cx0, h in zip(col_x, headers):
        d.text((cx0 + 10, y + head_h / 2), h, font=f(16, "sans_bold"),
               fill="white", anchor="lm")
    y += head_h
    row_h = 34
    for k, row in enumerate(rows):
        if k % 2 == 1:
            d.rectangle([margin, y, W - margin, y + row_h], fill="#F2F2F2")
        for cx0, val in zip(col_x, row):
            d.text((cx0 + 10, y + row_h / 2), val, font=f(15, "sans"),
                   fill=COLOR_INK, anchor="lm")
        y += row_h
    d.rectangle([margin, y_img + sec + 24, W - margin, y],
                outline="#BBBBBB")

    # Verdict.
    y += 18
    d.text((margin, y), verdict_evolution(detail),
           font=f(18, "sans_bold"), fill=COLOR_INK)
    return page


def save_comparison_png(page: "PILImage", path: str) -> None:
    page.save(path, "PNG")


def save_comparison_pdf(page: "PILImage", path: str) -> None:
    page.convert("RGB").save(path, "PDF", resolution=150.0)
