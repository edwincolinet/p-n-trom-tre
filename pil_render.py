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
    f_base = _pil_load_fonts()
    # Facteur d'échelle pour les éléments en pixels (polices, pastilles).
    # Calibré sur 1200 px : à 1600 → 1.33×, à 2400 → 2.0×. Plafonné à
    # 1.0 minimum pour ne pas réduire les tailles sur les petits dessins
    # (ex. vignette PDF à ~600 px).
    _ds = max(1.0, min(width, height) / 1200.0)

    def f(size: int, variant: str = "sans") -> Any:
        return f_base(max(1, int(size * _ds)), variant)

    img = Image.new("RGB", (width, height), COLOR_PANEL)
    d = ImageDraw.Draw(img, "RGBA")

    if arbre.rayon_tronc_cm <= 0:
        _pil_draw_placeholder(d, f_base, width, height)
        return img

    R = arbre.rayon_tronc_cm
    ep = max(0.0, arbre.epaisseur_ecorce_cm)
    R_ext = R + ep
    # Marges adaptées à la taille (responsive) :
    # - haut : titre+méta+lettre N hors écorce (proportionnel)
    # - bas : pastille S à l'intérieur, règle graduée + label
    margin_top = max(100, int(height * 0.065)) if show_title else 70
    legend_bottom_h = max(70, int(height * 0.09)) if show_legend else 0
    margin_bottom = max(120, int(height * 0.11)) + legend_bottom_h
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
    bullet_r = max(BULLET_RADIUS_PX, int(BULLET_RADIUS_PX * _ds))
    if show_sondages:
        _pil_draw_sondages(d, f, arbre, cx, cy, R, scale, bullet_r)
    y_axis = _pil_draw_regle(d, f, cx, cy, R, ep, R_ext, scale, height,
                              _ds)
    dot_r = max(5, int(5 * _ds))
    d.ellipse([cx-dot_r, cy-dot_r, cx+dot_r, cy+dot_r], fill=COLOR_INK)
    if show_title:
        _pil_draw_titre(d, f, arbre, R, width, height)
    if show_legend:
        legend_y = y_axis + int(50 * _ds) + int(height * 0.018)
        _draw_horizontal_legend_pil(d, arbre, y_top=legend_y,
                                     width=width, height=height,
                                     font_fn=f_base,
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
                       R: float, scale: float,
                       bullet_radius: int = BULLET_RADIUS_PX) -> None:
    inset_cm = SONDAGE_INSET_PX / scale
    items = sondage_render_data(arbre, cx, cy, R, scale, inset_cm,
                                COULEUR_CLASSE)
    r_b = bullet_radius
    ds_ratio = r_b / BULLET_RADIUS_PX
    for item in items:
        x_ext, y_ext = item.arrow_start
        x_end, y_end = item.arrow_end
        lw = max(4, int(4 * ds_ratio))
        d.line([x_ext, y_ext, x_end, y_end], fill=COLOR_SOND, width=lw)
        ang = math.atan2(y_end - y_ext, x_end - x_ext)
        ah = max(12, int(12 * ds_ratio))
        d.polygon([
            (x_end, y_end),
            (x_end - ah * math.cos(ang - 0.5),
             y_end - ah * math.sin(ang - 0.5)),
            (x_end - ah * math.cos(ang + 0.5),
             y_end - ah * math.sin(ang + 0.5)),
        ], fill=COLOR_SOND)
        px, py = item.bullet_center
        halo = max(2, int(2 * ds_ratio))
        d.ellipse([px - r_b - halo, py - r_b - halo,
                   px + r_b + halo, py + r_b + halo],
                  fill="white")
        d.ellipse([px - r_b, py - r_b, px + r_b, py + r_b],
                  fill=item.classe_color, outline="white",
                  width=max(2, int(2 * ds_ratio)))
        d.text((px, py), str(item.numero), font=f(20, "sans_bold"),
               fill="white", anchor="mm")


def _pil_draw_regle(d: "ImageDraw.ImageDraw", f: FontFn,
                    cx: float, cy: float,
                    R: float, ep: float, R_ext: float, scale: float,
                    height: int, _ds: float = 1.0) -> float:
    """Règle graduée symétrique centrée sous la section (-R à +R).

    Renvoie l'ordonnée de la règle pour le placement de la légende.
    """
    radius_ext_px = R_ext * scale
    step = adaptive_ruler_step_cm(scale, min_gap_px=int(60 * _ds))
    y_bar = min(cy + radius_ext_px + int(80 * _ds),
                height - int(100 * _ds))
    half_px = R * scale
    ext_half_px = R_ext * scale
    x_left = cx - half_px
    x_right = cx + half_px

    lw = max(3, int(3 * _ds))
    tick_h = int(14 * _ds)
    tick_s = int(8 * _ds)
    label_off = int(28 * _ds)

    # Trait principal de -R à +R
    d.line([x_left, y_bar, x_right, y_bar], fill=COLOR_INK, width=lw + 1)
    # Barres d'écorce aux deux extrémités + tiret et label au bout
    if ep > 0:
        bar_h = int(12 * _ds)
        x_ext_r = cx + ext_half_px
        x_ext_l = cx - ext_half_px
        d.rectangle([x_right, y_bar - bar_h / 2,
                     x_ext_r, y_bar + bar_h / 2], fill=COLOR_BARK)
        d.rectangle([x_ext_l, y_bar - bar_h / 2,
                     x_left, y_bar + bar_h / 2], fill=COLOR_BARK)
        d.line([x_ext_r, y_bar - tick_h, x_ext_r, y_bar + tick_h],
               fill=COLOR_BARK, width=lw + 1)
        d.line([x_ext_l, y_bar - tick_h, x_ext_l, y_bar + tick_h],
               fill=COLOR_BARK, width=lw + 1)
    # Tirets aux extrémités bois (R) et au centre (0)
    d.line([x_left, y_bar - tick_h, x_left, y_bar + tick_h],
           fill=COLOR_INK, width=lw + 1)
    d.line([x_right, y_bar - tick_h, x_right, y_bar + tick_h],
           fill=COLOR_INK, width=lw + 1)
    d.line([cx, y_bar - tick_h, cx, y_bar + tick_h],
           fill=COLOR_INK, width=lw + 1)
    if R > 0:
        # Graduations côté droit (avec labels)
        for xg, label in ruler_graduation_positions(cx, scale, R, step):
            d.line([xg, y_bar - tick_s, xg, y_bar + tick_s],
                   fill=COLOR_INK, width=max(2, int(2 * _ds)))
            d.text((xg, y_bar + label_off), label,
                   font=f(36, "sans_bold"), fill=COLOR_INK, anchor="mm")
            # Miroir côté gauche (même graduation, même label)
            x_mirror = cx - (xg - cx)
            d.line([x_mirror, y_bar - tick_s, x_mirror, y_bar + tick_s],
                   fill=COLOR_INK, width=max(2, int(2 * _ds)))
            d.text((x_mirror, y_bar + label_off), label,
                   font=f(36, "sans_bold"), fill=COLOR_INK, anchor="mm")
        d.text((cx, y_bar + label_off), "0",
               font=f(36, "sans_bold"), fill=COLOR_INK, anchor="mm")
        d.text((x_right, y_bar + label_off), f"{R:g}",
               font=f(36, "sans_bold"), fill=COLOR_INK, anchor="mm")
        d.text((x_left, y_bar + label_off), f"{R:g}",
               font=f(36, "sans_bold"), fill=COLOR_INK, anchor="mm")
    d.text((cx + ext_half_px + int(20 * _ds), y_bar), "cm",
           font=f(38, "sans_bold"), fill=COLOR_INK, anchor="lm")
    return y_bar


def _pil_draw_titre(d: "ImageDraw.ImageDraw", f: FontFn, arbre: "Arbre",
                    R: float, width: int, height: int) -> None:
    title_y = max(48, int(height * 0.042))
    d.text((width/2, title_y), arbre.display_name,
           font=f(54, "serif_bold"), fill=COLOR_ACCENT, anchor="mm")


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

    item_size = max(20, int(height * 0.038))
    swatch_w = max(32, int(height * 0.042))
    swatch_h = max(24, int(height * 0.035))
    r_p = max(14, int(height * 0.020))
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

