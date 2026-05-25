"""
Rendu PIL de la section transversale (PNG).

Ce module est le pendant non-Tk du `SectionCanvas` : il rend la même
section avec exactement la même géométrie (via les primitives partagées
de `geometry.py`), mais sur un `PIL.Image` exportable.

Contenu :
- `_pil_load_fonts`             — charge un jeu de polices avec
                                    fallback multi-OS.
- `render_arbre_to_pil_image`   — section transversale (PNG, ou base
                                    pour le dessin du PDF).
- `_draw_horizontal_legend_pil` — légende horizontale adaptative,
                                    consommée aussi par `fiche_pdf.py`.

Le layout de la fiche d'expertise PDF (page A4 complète : en-tête
mission, dessin, tableau PRBS, diagnostic) vit dans `fiche_pdf.py`
pour garder ce module focalisé sur le rendu de la section.

`HAS_PIL` est exposé : `False` quand Pillow n'est pas installé. Dans
ce cas, importer ce module reste possible mais appeler les fonctions de
rendu lèvera une exception au moment de la première utilisation de PIL
(les imports de `Image`/`ImageDraw` sont faits paresseusement dans
chaque fonction).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

from bareme import CLASSE_ORANGE, CLASSE_ROUGE, CLASSE_VERT
from diagnostic import (
    compute_alteration_par_grade,
    sondage_render_data,
)
from geometry import (
    adaptive_ruler_step_cm,
    cardinal_label_positions,
    cavity_polygon,
    cerne_radii_px,
    contrefort_zone_outline,
    contrefort_zones,
    degradation_externe_outline,
    ruler_graduation_positions,
    tick_endpoints,
)
from palette import (
    COLOR_ACCENT,
    COLOR_BARK,
    COLOR_BARK_LIGHT,
    COLOR_CERNE,
    COLOR_INK,
    COLOR_MUTED,
    COLOR_PANEL,
    COLOR_ROT,
    COLOR_SOND,
    COLOR_WOOD,
    COULEUR_CLASSE,
)

try:
    from PIL import Image  # noqa: F401  (re-exporté implicitement via TYPE_CHECKING)
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

if TYPE_CHECKING:
    from PIL import ImageDraw, ImageFont  # noqa: F401
    from PIL.Image import Image as PILImage  # noqa: F401

    from model import Arbre  # noqa: F401

# Type alias pour la factory de polices retournée par `_pil_load_fonts`.
# Signature côté appel : `f(size, variant="sans" | "sans_bold" | "serif_bold")`.
FontFn = Callable[..., Any]


# ----------------------------------------------------------------------
# Constantes de layout — pixels hors-scale, tunées pour le rendu PIL.
# Le rendu Tk a son propre jeu (cf. SectionCanvas.MARGIN_*, etc.) parce
# que le moteur de dessin diffère (hinting, épaisseurs).
# ----------------------------------------------------------------------

# Nombre de cernes de croissance dessinés à l'intérieur du tronc.
N_CERNES = 8

# Décalages des éléments hors-tronc (cardinales, ticks, pastilles).
# Stockés en px puis divisés par `scale` au point d'usage.
SONDAGE_INSET_PX = 18         # début de flèche / centre pastille
CARDINALES_OFFSET_PX = 45     # lettres N/NE/E/SE/S/SO/O/NO
TICK_LEN_PX = 12              # tirets de graduation des 16 grades
BULLET_RADIUS_PX = 22         # rayon de la pastille numérotée

# Échantillonnage du polygone d'altération (segments Catmull-Rom).
# Légèrement plus dense que côté Tk (28) pour absorber le hinting
# anti-aliasing PIL sur les courbes.
CAVITY_SAMPLES_PER_SEGMENT = 32


def _pil_load_fonts() -> FontFn:
    """Charge un jeu de polices cohérent, avec fallback sur le défaut PIL.

    Priorité 1 : polices embarquées dans `assets/fonts/` (DejaVu sous
    licence permissive). Garantit un rendu PDF/PNG identique sur toute
    machine, indépendamment des polices système installées.
    Priorité 2 : polices système connues (Linux/Windows/macOS), pour
    rester compatible avec une installation où `assets/fonts/` aurait
    été retiré.

    Appelé uniquement depuis les fonctions `render_*` qui importent
    `PIL.Image` en premier — si Pillow n'est pas installé, l'import
    aura déjà levé `ImportError` avant qu'on n'arrive ici.
    """
    from PIL import ImageFont
    embedded = Path(__file__).parent / "assets" / "fonts"
    # (variant, chemin) — premier trouvé pour chaque variant gagne.
    candidates: list[tuple[str, str]] = [
        # Polices embarquées (source unique, reproductible)
        ("serif_bold", str(embedded / "DejaVuSerif-Bold.ttf")),
        ("sans",       str(embedded / "DejaVuSans.ttf")),
        ("sans_bold",  str(embedded / "DejaVuSans-Bold.ttf")),
        # Fallback Linux (chemins debian/ubuntu)
        ("serif_bold", "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"),
        ("sans",       "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        ("sans_bold",  "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        # Fallback Windows
        ("serif_bold", r"C:\Windows\Fonts\georgiab.ttf"),
        ("sans",       r"C:\Windows\Fonts\arial.ttf"),
        ("sans_bold",  r"C:\Windows\Fonts\arialbd.ttf"),
        # Fallback macOS
        ("serif_bold", "/System/Library/Fonts/Supplemental/Georgia Bold.ttf"),
        ("sans",       "/Library/Fonts/Arial.ttf"),
    ]
    paths: Dict[str, Optional[str]] = {
        "serif_bold": None, "sans": None, "sans_bold": None}
    for variant, filepath in candidates:
        if paths[variant] is not None:
            continue
        try:
            ImageFont.truetype(filepath, 12)
            paths[variant] = filepath
        except Exception:
            continue

    def f(size: int, variant: str = "sans") -> Any:
        path = paths.get(variant) or paths.get("sans") or paths.get("serif_bold")
        try:
            return ImageFont.truetype(path, size) if path \
                else ImageFont.load_default()
        except Exception:
            return ImageFont.load_default()
    return f


def render_arbre_to_pil_image(arbre: "Arbre",
                              width: int = 1600, height: int = 1600,
                              show_sondages: bool = True,
                              show_title: bool = True,
                              show_legend: bool = False) -> "PILImage":
    """Rend la section transversale d'un arbre en image PIL (PNG/PDF).
    Logique identique à SectionCanvas.redraw() mais sans dépendance tk.

    Si `show_legend=True`, une légende adaptative est dessinée sous la
    règle graduée sur UNE LIGNE horizontale (Bois sain / Bois dégradé /
    Écorce / Sondage / Classes) ; une bande de hauteur est réservée en
    bas, ce qui repousse la section vers le haut.

    L'orchestration est ici, chaque couche est déléguée à un helper
    `_pil_draw_*` (symétrique à SectionCanvas._draw_*).
    """
    from PIL import Image, ImageDraw
    f = _pil_load_fonts()
    img = Image.new("RGB", (width, height), COLOR_PANEL)
    d = ImageDraw.Draw(img, "RGBA")

    if arbre.rayon_tronc_cm <= 0:
        _pil_draw_placeholder(d, f, width, height)
        return img

    R = arbre.rayon_tronc_cm
    ep = max(0.0, arbre.epaisseur_ecorce_cm)
    R_ext = R + ep
    # Marges adaptées à la taille (responsive) :
    # - haut : titre+méta+lettre N hors écorce (proportionnel)
    # - bas : pastille S à l'intérieur, règle graduée + label
    margin_top = max(130, int(height * 0.10)) if show_title else 70
    legend_bottom_h = max(60, int(height * 0.06)) if show_legend else 0
    margin_bottom = max(110, int(height * 0.09)) + legend_bottom_h
    margin_side = max(60, int(width * 0.055))
    available_v = height - margin_top - margin_bottom
    available_h = width - 2 * margin_side
    radius_px_max = min(available_h / 2, available_v / 2)
    cx = width / 2
    cy = margin_top + radius_px_max
    # `radius_px` = rayon en pixels du BOIS ; `radius_ext_px` = bois+écorce.
    # On réserve aussi l'espace des contreforts (longueur_cm au-delà de R+ep).
    expansion = ep + max((c.longueur_cm for c in arbre.contreforts),
                          default=0.0)
    scale = radius_px_max / (R + expansion)

    _pil_draw_bois_sain(d, cx, cy, R, scale)
    _pil_draw_cernes(d, cx, cy, R, scale)
    _pil_draw_cavite(d, arbre, cx, cy, scale)
    _pil_draw_ecorce(d, cx, cy, R, ep, R_ext, scale)
    _pil_draw_contreforts(d, arbre, cx, cy, R, ep, scale)
    # Dégradations EN DERNIER (cf. CLAUDE.md « Ordre global des couches »).
    _pil_draw_degradations(d, arbre, cx, cy, R, ep, scale)
    _pil_draw_ticks(d, cx, cy, R_ext, scale)
    _pil_draw_cardinales(d, f, cx, cy, R_ext, scale)
    if show_sondages:
        _pil_draw_sondages(d, f, arbre, cx, cy, R, scale)
    y_axis = _pil_draw_regle(d, f, cx, cy, R, ep, R_ext, scale, height)
    # Point central de la section
    d.ellipse([cx-5, cy-5, cx+5, cy+5], fill=COLOR_INK)
    if show_title:
        _pil_draw_titre(d, f, arbre, R, width, height)
    if show_legend:
        legend_y = y_axis + max(35, int(height * 0.028))
        _draw_horizontal_legend_pil(d, arbre, y_top=legend_y,
                                     width=width, height=height,
                                     font_fn=f,
                                     show_sondage_item=False,
                                     show_classes=False)
    return img


# ----------------------------------------------------------------------
# Helpers PIL — un par couche logique (symétrique à SectionCanvas._draw_*)
# ----------------------------------------------------------------------

# ----------------------------------------------------------------------
# Helpers de dessin — un par couche logique.
#
# **Pendants Tk ↔ PIL**. Chaque helper ci-dessous a un jumeau dans
# `section_canvas.SectionCanvas` (préfixé `_draw_`) qui dessine la même
# couche sur un `tk.Canvas`. La géométrie est partagée via
# `geometry.py` ; seuls subsistent ici les paramètres visuels propres
# à PIL (`ImageFont`, ellipse-outline-inside-bbox, polygones explicites
# pour les flèches, anti-aliasing). Toute modification d'une couche
# doit être répliquée dans les DEUX fichiers — cf. tableau dans
# CLAUDE.md « Pendants Tk ↔ PIL ».
#
#   _pil_draw_placeholder        ↔ SectionCanvas._draw_placeholder
#   _pil_draw_bois_sain          ↔ SectionCanvas._draw_bois_sain
#   _pil_draw_cernes             ↔ SectionCanvas._draw_cernes
#   _pil_draw_cavite             ↔ SectionCanvas._draw_cavite
#   _pil_draw_ecorce             ↔ SectionCanvas._draw_ecorce
#   _pil_draw_contreforts        ↔ SectionCanvas._draw_contreforts_canvas
#   _pil_draw_degradations       ↔ SectionCanvas._draw_degradation_externe_canvas
#   _pil_draw_ticks              ↔ SectionCanvas._draw_ticks
#   _pil_draw_cardinales         ↔ SectionCanvas._draw_cardinales
#   _pil_draw_sondages           ↔ SectionCanvas._draw_sondages
#   _pil_draw_regle              ↔ SectionCanvas._draw_regle
#   _pil_draw_titre              ↔ SectionCanvas._draw_titre
# ----------------------------------------------------------------------


def _pil_draw_placeholder(d: "ImageDraw.ImageDraw", f: FontFn,
                          width: int, height: int) -> None:
    d.text((width/2, height/2),
           "Rayon non renseigné", fill=COLOR_MUTED,
           font=f(28, "sans"), anchor="mm")


def _pil_draw_bois_sain(d: "ImageDraw.ImageDraw",
                        cx: float, cy: float,
                        R: float, scale: float) -> None:
    radius_px = R * scale
    d.ellipse([cx-radius_px, cy-radius_px, cx+radius_px, cy+radius_px],
              fill=COLOR_WOOD)


def _pil_draw_cernes(d: "ImageDraw.ImageDraw",
                     cx: float, cy: float,
                     R: float, scale: float) -> None:
    for rr in cerne_radii_px(R, scale, N_CERNES):
        d.ellipse([cx-rr, cy-rr, cx+rr, cy+rr],
                  outline=COLOR_CERNE, width=1)


def _pil_draw_cavite(d: "ImageDraw.ImageDraw", arbre: "Arbre",
                     cx: float, cy: float, scale: float) -> None:
    alt = compute_alteration_par_grade(arbre)
    if not any(a > 0 for a in alt):
        return
    smooth = cavity_polygon(alt, cx, cy, scale,
                              samples_per_segment=CAVITY_SAMPLES_PER_SEGMENT)
    d.polygon(smooth, fill=COLOR_ROT, outline=None)


def _pil_draw_ecorce(d: "ImageDraw.ImageDraw",
                     cx: float, cy: float,
                     R: float, ep: float, R_ext: float,
                     scale: float) -> None:
    # Note PIL : `d.ellipse(outline, width)` trace l'outline À L'INTÉRIEUR
    # du bounding box (pas centré sur la frontière comme Tkinter). Avec
    # bbox de rayon R_ext et width=ep_px, l'outline va de R_ext-ep à
    # R_ext, soit exactement [R, R_ext].
    radius_ext_px = R_ext * scale
    if ep > 0:
        ep_px = max(1.0, ep * scale)
        d.ellipse([cx-radius_ext_px, cy-radius_ext_px,
                   cx+radius_ext_px, cy+radius_ext_px],
                  outline=COLOR_BARK, width=int(round(ep_px)))
    else:
        radius_px = R * scale
        d.ellipse([cx-radius_px, cy-radius_px,
                   cx+radius_px, cy+radius_px],
                  outline=COLOR_BARK, width=4)


def _pil_draw_contreforts(d: "ImageDraw.ImageDraw", arbre: "Arbre",
                          cx: float, cy: float,
                          R: float, ep: float, scale: float) -> None:
    # Fusionnés par zones connectées : plusieurs contreforts qui se
    # touchent sont rendus comme une seule cloche unifiée (max des
    # hauteurs), ce qui évite l'encoche en V.
    for zone in contrefort_zones(arbre.contreforts):
        poly = contrefort_zone_outline(zone, arbre.contreforts, R, ep,
                                        cx, cy, scale)
        wood_outer = poly["wood_outer"]
        if ep > 0:
            d.polygon(poly["bark_outer"] + poly["bark_inner"],
                      fill=COLOR_BARK)
        d.polygon(wood_outer + poly["base"], fill=COLOR_WOOD)
        if ep == 0:
            d.line(wood_outer, fill=COLOR_BARK, width=4, joint="curve")


def _pil_draw_degradations(d: "ImageDraw.ImageDraw", arbre: "Arbre",
                           cx: float, cy: float,
                           R: float, ep: float, scale: float) -> None:
    # Le bord externe du polygone suit la surface réelle (R + ep + cloche).
    # Une dégradation qui passe sur un contrefort y mord à concurrence
    # de sa profondeur.
    for deg in arbre.degradations_externes:
        pts_arc = degradation_externe_outline(deg, arbre.contreforts,
                                               R, ep, cx, cy, scale)
        if pts_arc:
            d.polygon(pts_arc, fill=COLOR_ROT, outline=None)


def _pil_draw_ticks(d: "ImageDraw.ImageDraw",
                    cx: float, cy: float,
                    R_ext: float, scale: float) -> None:
    # 16 grades — tirets à l'extérieur de l'écorce.
    tick_len_cm = TICK_LEN_PX / scale
    for x1, y1, x2, y2, maj in tick_endpoints(
            cx, cy, scale, R_ext, tick_len_cm):
        d.line([x1, y1, x2, y2],
               fill=COLOR_BARK if maj else COLOR_BARK_LIGHT,
               width=3 if maj else 1)


def _pil_draw_cardinales(d: "ImageDraw.ImageDraw", f: FontFn,
                         cx: float, cy: float,
                         R_ext: float, scale: float) -> None:
    # Lettres cardinales à `CARDINALES_OFFSET_PX` hors écorce, halo blanc.
    offset_cm = CARDINALES_OFFSET_PX / scale
    for lx, ly, lbl in cardinal_label_positions(
            cx, cy, scale, R_ext, offset_cm):
        for dx in (-4, -3, 0, 3, 4):
            for dy in (-4, -3, 0, 3, 4):
                if dx or dy:
                    d.text((lx+dx, ly+dy), lbl, font=f(44, "serif_bold"),
                           fill="white", anchor="mm")
        d.text((lx, ly), lbl, font=f(44, "serif_bold"),
               fill=COLOR_INK, anchor="mm")


def _pil_draw_sondages(d: "ImageDraw.ImageDraw", f: FontFn, arbre: "Arbre",
                       cx: float, cy: float,
                       R: float, scale: float) -> None:
    inset_cm = SONDAGE_INSET_PX / scale
    items = sondage_render_data(arbre, cx, cy, R, scale, inset_cm,
                                COULEUR_CLASSE)
    r_b = BULLET_RADIUS_PX
    for item in items:
        x_ext, y_ext = item.arrow_start
        x_end, y_end = item.arrow_end
        d.line([x_ext, y_ext, x_end, y_end], fill=COLOR_SOND, width=4)
        ang = math.atan2(y_end - y_ext, x_end - x_ext)
        ah = 12
        d.polygon([
            (x_end, y_end),
            (x_end - ah * math.cos(ang - 0.5),
             y_end - ah * math.sin(ang - 0.5)),
            (x_end - ah * math.cos(ang + 0.5),
             y_end - ah * math.sin(ang + 0.5)),
        ], fill=COLOR_SOND)
        px, py = item.bullet_center
        d.ellipse([px - r_b - 2, py - r_b - 2, px + r_b + 2, py + r_b + 2],
                  fill="white")
        d.ellipse([px - r_b, py - r_b, px + r_b, py + r_b],
                  fill=item.classe_color, outline="white", width=2)
        d.text((px, py), str(item.numero), font=f(20, "sans_bold"),
               fill="white", anchor="mm")


def _pil_draw_regle(d: "ImageDraw.ImageDraw", f: FontFn,
                    cx: float, cy: float,
                    R: float, ep: float, R_ext: float, scale: float,
                    height: int) -> float:
    """Dessine la règle graduée sous la section et renvoie son ordonnée
    `y_axis`. Demi-règle : 0 AU CENTRE de l'arbre, graduation seulement
    vers la droite jusqu'à R (bord du bois). La portion bois est en
    trait noir fin ; la barre écorce (si ep > 0) prolonge la règle
    jusqu'à R+ep, sans label numérique.
    """
    radius_ext_px = R_ext * scale
    # Pas adaptatif : on veut ~50 px mini entre deux étiquettes pour la
    # police 18 pt de la fiche.
    step = adaptive_ruler_step_cm(scale, min_gap_px=60)
    y_axis = min(cy + radius_ext_px + 105, height - 60)
    wood_half_px = R * scale
    ext_half_px = R_ext * scale
    x_rw = cx + wood_half_px
    x_re = cx + ext_half_px

    # Trait bois (noir fin) du centre au bord droit
    d.line([cx, y_axis, x_rw, y_axis], fill=COLOR_INK, width=4)
    # Barre écorce (brun foncé épais) à l'extrémité droite
    if ep > 0:
        bar_h = 12
        d.rectangle([x_rw, y_axis - bar_h/2,
                     x_re, y_axis + bar_h/2], fill=COLOR_BARK)
    # Tiret à l'extrémité externe (R+ep)
    end_color = COLOR_BARK if ep > 0 else COLOR_INK
    d.line([x_re, y_axis-14, x_re, y_axis+14], fill=end_color, width=4)
    # Tiret central (origine 0) et transition bois/écorce (R)
    d.line([cx, y_axis-11, cx, y_axis+11], fill=COLOR_INK, width=4)
    if ep > 0:
        d.line([x_rw, y_axis-11, x_rw, y_axis+11], fill=COLOR_INK, width=4)
    # Graduations intermédiaires (bois) tous les `step` cm depuis 0
    # (centre) jusqu'à R (bord droit).
    if R > 0:
        for xg, label in ruler_graduation_positions(cx, scale, R, step):
            d.line([xg, y_axis-8, xg, y_axis+8], fill=COLOR_INK, width=2)
            d.text((xg, y_axis+32), label,
                   font=f(24, "sans_bold"), fill=COLOR_INK, anchor="mm")
        # Étiquettes des deux extrémités : 0 au centre, R au bord
        d.text((cx, y_axis+32), "0",
               font=f(24, "sans_bold"), fill=COLOR_INK, anchor="mm")
        d.text((x_rw, y_axis+32), f"{R:g}",
               font=f(24, "sans_bold"), fill=COLOR_INK, anchor="mm")
    # Label "cm" à droite
    d.text((x_re+35, y_axis), "cm",
           font=f(26, "sans_bold"), fill=COLOR_INK, anchor="lm")
    return y_axis


def _pil_draw_titre(d: "ImageDraw.ImageDraw", f: FontFn, arbre: "Arbre",
                    R: float, width: int, height: int) -> None:
    # Titre + méta — positions proportionnelles à la hauteur.
    title_y = max(48, int(height * 0.042))
    sub_y = title_y + 62
    d.text((width/2, title_y), arbre.display_name,
           font=f(54, "serif_bold"), fill=COLOR_ACCENT, anchor="mm")
    sub_parts = [f"Rayon {R:g} cm"]
    if arbre.diametre_sous_ecorce_cm:
        sub_parts.append(f"Ø sous écorce {arbre.diametre_sous_ecorce_cm:g} cm")
    if arbre.hauteur_arbre_m:
        sub_parts.append(f"H {arbre.hauteur_arbre_m:g} m")
    if arbre.meche_cm:
        sub_parts.append(f"Mèche {arbre.meche_cm:g} cm")
    d.text((width/2, sub_y), "   •   ".join(sub_parts),
           font=f(30, "sans"), fill=COLOR_MUTED, anchor="mm")


def _draw_horizontal_legend_pil(d: "ImageDraw.ImageDraw", arbre: "Arbre",
                                y_top: float, width: int, height: int,
                                font_fn: FontFn, *,
                                show_sondage_item: bool = True,
                                show_classes: bool = True) -> None:
    """Dessine la légende du dessin de section sur UNE LIGNE horizontale,
    centrée, sous la règle graduée.

    Légende adaptative : on n'affiche que les éléments effectivement
    présents sur le dessin (Bois dégradé seulement s'il y a des
    altérations ou dégradations externes ; Écorce seulement si une
    épaisseur > 0 a été renseignée ; etc.).

    `show_sondage_item` / `show_classes` permettent à l'appelant de
    réduire la légende : l'export PNG la veut minimaliste (bois sain /
    bois dégradé / écorce), la fiche PDF garde la flèche « Sondage »
    mais retire le bloc « Classe du sondage » (les pastilles colorées
    sont déjà explicitées par le tableau PRBS).
    """
    ep = max(0.0, arbre.epaisseur_ecorce_cm)
    has_decay = (
        bool(arbre.degradations_externes)
        or any(s.bois_altere_cm > 0 for s in arbre.sondages)
        or any(a > 0 for a in compute_alteration_par_grade(arbre))
    )
    has_bark = ep > 0
    has_sondages = bool(arbre.sondages)

    item_size = max(16, int(height * 0.024))
    swatch_w = max(26, int(height * 0.030))
    swatch_h = max(18, int(height * 0.024))
    r_p = max(10, int(height * 0.015))
    item_font = font_fn(item_size, "sans")
    bold_font = font_fn(item_size, "sans_bold")

    items = [("wood", "Bois sain")]
    if has_decay:
        items.append(("rot", "Bois dégradé"))
    if has_bark:
        items.append(("bark", "Écorce"))
    if has_sondages and show_sondage_item:
        items.append(("arrow", "Sondage"))

    classes = tuple(
        (label, COULEUR_CLASSE[label])
        for label in (CLASSE_VERT, CLASSE_ORANGE, CLASSE_ROUGE)
    ) if (has_sondages and show_classes) else ()
    classes_prefix = "Classe du sondage :"

    # Pré-calcul des largeurs pour centrer le bloc complet.
    def text_w(txt: str, font: Any) -> float:
        bbox = d.textbbox((0, 0), txt, font=font)
        return bbox[2] - bbox[0]

    item_widths = [swatch_w + 8 + text_w(label, item_font)
                   for _, label in items]
    classes_w: float = 0.0
    if classes:
        classes_w = text_w(classes_prefix, bold_font) + 12
        for label, _ in classes:
            classes_w += 2 * r_p + 6 + text_w(label, item_font) + 14
        classes_w -= 14  # pas de gap après le dernier

    gap = max(22, int(width * 0.018))
    total_w = sum(item_widths) + gap * max(0, len(items) - 1)
    if classes:
        total_w += gap + classes_w

    x_cur = max(20, (width - total_w) // 2)
    sw_top = y_top + (item_size - swatch_h) // 2 + 2  # alignement vertical

    for i, (kind, label) in enumerate(items):
        if kind == "wood":
            d.rectangle([x_cur, sw_top,
                         x_cur + swatch_w, sw_top + swatch_h],
                        fill=COLOR_WOOD, outline=COLOR_BARK, width=1)
        elif kind == "rot":
            d.rectangle([x_cur, sw_top,
                         x_cur + swatch_w, sw_top + swatch_h],
                        fill=COLOR_ROT)
        elif kind == "bark":
            d.rectangle([x_cur, sw_top,
                         x_cur + swatch_w, sw_top + swatch_h],
                        fill=COLOR_BARK)
        elif kind == "arrow":
            ay = sw_top + swatch_h / 2
            ax1 = x_cur + 2
            ax2 = x_cur + swatch_w - 4
            d.line([(ax1, ay), (ax2, ay)],
                   fill=COLOR_SOND, width=max(2, int(height * 0.0028)))
            ah = max(6, int(height * 0.008))
            d.polygon([(ax2 + ah, ay),
                       (ax2 - 1, ay - ah * 0.65),
                       (ax2 - 1, ay + ah * 0.65)], fill=COLOR_SOND)
        d.text((x_cur + swatch_w + 8, sw_top + swatch_h / 2), label,
               font=item_font, fill=COLOR_INK, anchor="lm")
        x_cur += item_widths[i] + gap

    if classes:
        d.text((x_cur, sw_top + swatch_h / 2), classes_prefix,
               font=bold_font, fill=COLOR_INK, anchor="lm")
        x_cur += text_w(classes_prefix, bold_font) + 12
        for label, hex_col in classes:
            cy_p = sw_top + swatch_h / 2
            d.ellipse([x_cur, cy_p - r_p,
                       x_cur + 2 * r_p, cy_p + r_p],
                      fill=hex_col, outline="white",
                      width=max(1, int(height * 0.0018)))
            x_cur += 2 * r_p + 6
            d.text((x_cur, cy_p), label, font=item_font,
                   fill=hex_col, anchor="lm")
            x_cur += text_w(label, item_font) + 14

