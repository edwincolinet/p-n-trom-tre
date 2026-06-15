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

from diagnostic import (
    comparaison_detaillee,
    comparaison_par_brin,
    prbs_par_grade,
    rayon_par_grade,
    verdict_evolution,
)
from geometry import GRADES, catmull_rom_closed
from palette import (
    COLOR_ACCENT,
    COLOR_BARK,
    COLOR_INK,
    COLOR_MUTED,
    COLOR_ROT,
    COLOR_WOOD,
)
from pil_render import _pil_load_fonts, render_arbre_to_pil_image

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage

    from diagnostic import ComparaisonDetail
    from model import Arbre, Brin

# Grade → angle écran (radians, 0 à 3 h, sens horaire). 360/400 = 0.9 ; le
# Nord (grade 0) est en haut → −90°.
_GR_TO_DEG = 0.9
_ORANGE = (232, 128, 26)   # bois sain perdu depuis la référence


def _poly(cx: float, cy: float, scale: float,
          radii: list) -> list:
    """Contour **lissé** (spline Catmull-Rom fermée, comme le rendu des
    sections) passant par les 16 directions (grade 0 = Nord, sens horaire)
    aux rayons `radii` (cm) — évite l'aspect « cubique » du 16-gon."""
    pts = []
    for i, g in enumerate(GRADES):
        ang = math.radians(g * _GR_TO_DEG - 90)
        r = max(0.0, radii[i]) * scale
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return catmull_rom_closed(pts, samples_per_segment=12)


def render_evolution_section(ref_arbre: "Arbre", cur_arbre: "Arbre",
                             size: int = 460) -> "PILImage":
    """« Section d'évolution » au niveau **genet** (brin courant) — délègue
    à `render_evolution_section_brin`. Conservé pour le rendu mono-caule et
    l'export genet."""
    return render_evolution_section_brin(
        ref_arbre.brin_courant, cur_arbre.brin_courant, size)


def render_brin_section(src: "Arbre", brin: "Brin", size: int = 460,
                        *, show_sondages: bool = True) -> "PILImage":
    """Rend la section d'**un seul brin** (ramet) d'une cépée, centrée,
    comme un mono-caule. Astuce : on emballe le brin dans un genet temporaire
    (identité reprise pour la couleur des sondages = port), puis on réutilise
    `render_arbre_to_pil_image`. Évite un renderer brin-isolé dédié.
    `show_sondages` suit la case « Afficher sondages » sous le canevas."""
    from model import Arbre
    tmp = Arbre(numero_arbre=src.numero_arbre, essence=src.essence,
                port_arbre=src.port_arbre, meche_cm=src.meche_cm)
    tmp.brins = [brin]
    return render_arbre_to_pil_image(
        tmp, size, size, show_sondages=show_sondages, show_title=False,
        show_legend=False)


def render_evolution_section_brin(ref_b: Optional["Brin"], cur_b: "Brin",
                                  size: int = 460) -> "PILImage":
    """« Section d'évolution » d'**un brin** : sur la géométrie du brin
    COURANT, la couronne de bois sain **perdu depuis la référence** est
    surlignée en orange — entre l'ancien bord de cavité (R − PRBS_réf) et le
    nouveau (R − PRBS_courant). Au centre : la cavité déjà altérée à la
    référence.

    `ref_b=None` (brin sans homologue de référence) ⟹ pas de couronne orange
    (PRBS_réf = PRBS_courant) et une légende « pas de brin de référence ».

    Tout est exprimé sur le rayon LOCAL courant (`rayon_par_grade`) et les
    PRBS **extrapolées** sur 16 directions, donc complet même sur les
    directions non sondées. Schématique (16-gon), pas les cernes."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (size, size), "white")
    d = ImageDraw.Draw(img)
    f = _pil_load_fonts()

    R = rayon_par_grade(cur_b)                 # rayon local courant, 16 dir.
    ep = max(0.0, cur_b.epaisseur_ecorce_cm)
    prbs_c = prbs_par_grade(cur_b)
    # Pas d'homologue de référence → on prend la PRBS courante (aucune
    # couronne orange : rien à comparer, on montre l'état courant seul).
    prbs_r = prbs_par_grade(ref_b) if ref_b is not None else list(prbs_c)
    outer = [R[i] + ep for i in range(16)]
    cur_cav = [R[i] - prbs_c[i] for i in range(16)]   # nouvelle cavité
    ref_cav = [R[i] - prbs_r[i] for i in range(16)]   # ancienne cavité

    rmax = max(outer) if outer else 1.0
    cx, cy = size / 2.0, size * 0.45
    scale = (size * 0.40) / (rmax if rmax > 0 else 1.0)

    d.polygon(_poly(cx, cy, scale, outer), fill=COLOR_BARK)        # écorce
    d.polygon(_poly(cx, cy, scale, R), fill=COLOR_WOOD)           # bois sain
    d.polygon(_poly(cx, cy, scale, cur_cav), fill=_ORANGE)        # bois perdu
    d.polygon(_poly(cx, cy, scale, ref_cav), fill=COLOR_ROT)      # cavité réf.
    d.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], fill=(230, 230, 226))

    for g, lbl in ((0, "N"), (100, "E"), (200, "S"), (300, "O")):
        ang = math.radians(g * _GR_TO_DEG - 90)
        lx = cx + (rmax * scale + 18) * math.cos(ang)
        ly = cy + (rmax * scale + 18) * math.sin(ang)
        d.text((lx, ly), lbl, font=f(int(size * 0.046), "serif_bold"),
               fill=COLOR_INK, anchor="mm")

    sf = f(int(size * 0.030), "sans")
    cap_y = size * 0.95
    if ref_b is None:
        d.text((size * 0.5, cap_y + 8),
               "pas de brin de référence — état courant seul",
               font=sf, fill=COLOR_MUTED, anchor="mm")
    else:
        d.rectangle([size * 0.14, cap_y, size * 0.14 + 20, cap_y + 16],
                    fill=_ORANGE, outline=(150, 150, 146))
        d.text((size * 0.14 + 26, cap_y + 8),
               "= bois sain perdu depuis la référence",
               font=sf, fill=COLOR_MUTED, anchor="lm")
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
    # PRBS moyenne extrapolée (16 directions)
    evo_prbs = ""
    if detail.perte_moy_par_dir is not None:
        evo_prbs = f"{-detail.perte_moy_par_dir:+.2f} cm"
    rows.append(("PRBS moyenne (16 directions)",
                 f"{detail.prbs_moy_ref:.2f} cm" if detail.prbs_moy_ref is not None else "—",
                 f"{detail.prbs_moy_cur:.2f} cm" if detail.prbs_moy_cur is not None else "—",
                 evo_prbs))
    # Perte moyenne de bois sain PAR DIRECTION (cm) — la mesure de référence.
    if detail.perte_moy_par_dir is not None:
        rows.append(("Perte moyenne de bois sain", "—", "—",
                     f"{detail.perte_moy_par_dir:.2f} cm / direction"))
    # Taux annualisé (uniquement si l'intervalle est suffisant).
    if detail.taux_cm_an is not None:
        rows.append(("Taux annualisé", "—", "—",
                     f"{detail.taux_cm_an:.2f} cm/an"))
    elif detail.annees is not None:
        rows.append(("Taux annualisé", "—", "—",
                     "intervalle trop court (< 6 mois)"))
    else:
        rows.append(("Taux annualisé", "—", "—", "missions non datées"))
    # Compartimentation
    rows.append(("Compartimentation perdue (active→absente)", "—", "—",
                 f"{detail.compart_aggravees} direction(s)"))
    # Pire direction
    if detail.pire is not None:
        rows.append(("Direction la plus aggravée", "—", "—",
                     f"{detail.pire.direction} ({detail.pire.grade} gr) : "
                     f"{detail.pire.delta:+.2f} cm"))
    return rows


# Géométrie de la page A4 paysage (150 DPI). `_PAGE_SEC` = côté des trois
# dessins côte à côte — exposé pour rendre les images à la bonne taille
# AVANT composition (la composition ne fait que les coller).
_PAGE_W, _PAGE_H = 1754, 1240
_PAGE_MARGIN = 54
_PAGE_GAP = 24
_PAGE_SEC = (_PAGE_W - 2 * _PAGE_MARGIN - 2 * _PAGE_GAP) // 3   # 532


def _blank_section(size: int, text: str) -> "PILImage":
    """Vignette blanche à texte centré (ex. brin courant sans homologue de
    référence) — occupe proprement la colonne « Référence » manquante."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (size, size), "white")
    d = ImageDraw.Draw(img)
    f = _pil_load_fonts()
    d.text((size / 2, size / 2), text, font=f(int(size * 0.035), "sans"),
           fill=COLOR_MUTED, anchor="mm")
    return img


def _compose_comparison_page(mission_nom: str, titre: str, ref_label: str,
                             cur_label: str, ref_img: "PILImage",
                             cur_img: "PILImage", evo_img: "PILImage",
                             detail: "ComparaisonDetail") -> "PILImage":
    """Compose une page A4 paysage (en-tête, 3 dessins déjà rendus à
    `_PAGE_SEC`, tableau chiffré, verdict). Partagé par la page **genet**
    et les pages **par brin**."""
    from PIL import Image, ImageDraw
    f = _pil_load_fonts()
    W, margin, gap, sec = _PAGE_W, _PAGE_MARGIN, _PAGE_GAP, _PAGE_SEC
    page = Image.new("RGB", (W, _PAGE_H), "white")
    d = ImageDraw.Draw(page)

    # En-tête vert.
    d.rectangle([0, 0, W, 92], fill=COLOR_ACCENT)
    d.text((margin, 20), titre, font=f(30, "serif_bold"), fill="white")
    d.text((margin, 62),
           f"Mission « {mission_nom or 'Mission'} »   •   "
           f"Référence : {ref_label}   →   Courant : {cur_label}",
           font=f(17, "sans"), fill="white")

    # Trois sections côte à côte (images déjà rendues).
    y_lbl = 116
    y_img = y_lbl + 34
    cols = ((f"Référence — {ref_label}", ref_img),
            (f"Courant — {cur_label}", cur_img),
            ("Évolution de l'altération", evo_img))
    for i, (titre_col, img) in enumerate(cols):
        x = margin + i * (sec + gap)
        d.text((x, y_lbl), titre_col, font=f(18, "sans_bold"), fill=COLOR_INK)
        page.paste(img, (x, y_img))

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
    d.rectangle([margin, y_img + sec + 24, W - margin, y], outline="#BBBBBB")

    # Verdict.
    y += 18
    d.text((margin, y), verdict_evolution(detail),
           font=f(18, "sans_bold"), fill=COLOR_INK)
    return page


def render_comparison_page(mission_nom: str, ref_arbre: "Arbre",
                           cur_arbre: "Arbre", detail: "ComparaisonDetail",
                           *, ref_label: str, cur_label: str,
                           show_sondages: bool = True) -> "PILImage":
    """Page A4 paysage **genet** (dessins de l'arbre entier + évolution du
    brin courant). Sortie inchangée — utilisée pour un mono-caule."""
    ref_img = render_arbre_to_pil_image(
        ref_arbre, _PAGE_SEC, _PAGE_SEC, show_sondages=show_sondages,
        show_title=False, show_legend=False)
    cur_img = render_arbre_to_pil_image(
        cur_arbre, _PAGE_SEC, _PAGE_SEC, show_sondages=show_sondages,
        show_title=False, show_legend=False)
    evo_img = render_evolution_section(ref_arbre, cur_arbre, _PAGE_SEC)
    return _compose_comparison_page(
        mission_nom, f"Comparaison d'inspections — {cur_arbre.display_name}",
        ref_label, cur_label, ref_img, cur_img, evo_img, detail)


def render_comparison_pages(mission_nom: str, ref_arbre: "Arbre",
                            cur_arbre: "Arbre", annees: Optional[float],
                            *, ref_label: str, cur_label: str,
                            show_sondages: bool = True) -> List["PILImage"]:
    """Pages d'export de la comparaison : **une page par brin** pour une
    cépée (dessins du brin isolé + évolution brin-level + tableau/verdict du
    brin), une **page genet** pour un mono-caule (vue d'ensemble, inchangée).
    Le brin courant sans homologue de référence reçoit une colonne
    « Référence » vide (jamais d'appariement décalé). `show_sondages` suit la
    case « Afficher sondages » sous le canevas."""
    if len(cur_arbre.brins) <= 1:
        detail = comparaison_detaillee(ref_arbre, cur_arbre, annees)
        return [render_comparison_page(
            mission_nom, ref_arbre, cur_arbre, detail,
            ref_label=ref_label, cur_label=cur_label,
            show_sondages=show_sondages)]
    pages: List["PILImage"] = []
    for label, cur_b, ref_b, detail in comparaison_par_brin(
            ref_arbre, cur_arbre, annees):
        ref_img = (render_brin_section(ref_arbre, ref_b, _PAGE_SEC,
                                       show_sondages=show_sondages)
                   if ref_b is not None
                   else _blank_section(_PAGE_SEC, "pas de brin de référence"))
        cur_img = render_brin_section(cur_arbre, cur_b, _PAGE_SEC,
                                      show_sondages=show_sondages)
        evo_img = render_evolution_section_brin(ref_b, cur_b, _PAGE_SEC)
        titre = (f"Comparaison d'inspections — "
                 f"{cur_arbre.display_name} — Brin {label}")
        pages.append(_compose_comparison_page(
            mission_nom, titre, ref_label, cur_label,
            ref_img, cur_img, evo_img, detail))
    return pages


def save_comparison_png(pages: List["PILImage"], path: str) -> None:
    """Enregistre en PNG. Une page → telle quelle ; plusieurs (cépée) →
    empilées verticalement en une seule image (le PNG est mono-image)."""
    if len(pages) == 1:
        pages[0].save(path, "PNG")
        return
    from PIL import Image
    w = max(p.width for p in pages)
    h = sum(p.height for p in pages)
    stacked = Image.new("RGB", (w, h), "white")
    y = 0
    for p in pages:
        stacked.paste(p, (0, y))
        y += p.height
    stacked.save(path, "PNG")


def save_comparison_pdf(pages: List["PILImage"], path: str) -> None:
    """Enregistre en PDF — **multi-pages** pour une cépée (une page/brin)."""
    imgs = [p.convert("RGB") for p in pages]
    imgs[0].save(path, "PDF", resolution=150.0,
                 save_all=True, append_images=imgs[1:])
