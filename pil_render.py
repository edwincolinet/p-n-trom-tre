"""
Rendu PIL : dessin de la section transversale (PNG) et fiche
d'expertise A4 (PDF).

Ce module est le pendant non-Tk du `SectionCanvas` : il rend la même
section avec exactement la même géométrie (via les primitives partagées
de `geometry.py`), mais sur un `PIL.Image` exportable.

Contenu :
- `_pil_load_fonts`             — charge un jeu de polices avec
                                    fallback multi-OS.
- `render_arbre_to_pil_image`   — section transversale (PNG, ou base
                                    pour le dessin du PDF).
- `_draw_horizontal_legend_pil` — légende horizontale adaptative.
- `_fit_text`                   — troncature ellipsis pour respecter
                                    une largeur de colonne donnée.
- `render_fiche_arbre_to_pdf_page` — page A4 complète (en-tête mission,
                                    dessin, tableau PRBS ajustée,
                                    diagnostic).

`HAS_PIL` est exposé : `False` quand Pillow n'est pas installé. Dans
ce cas, importer ce module reste possible mais appeler les fonctions de
rendu lèvera une exception au moment de la première utilisation de PIL
(les imports de `Image`/`ImageDraw` sont faits paresseusement dans
chaque fonction).
"""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from geometry import (
    CLASSE_ORANGE,
    CLASSE_ROUGE,
    CLASSE_VERT,
    DIRECTION_LABELS,
    GRADES,
    cavity_polygon,
    classer_prbs,
    contrefort_zone_outline,
    contrefort_zones,
    degradation_externe_outline,
    polar_idx_to_xy,
    polar_to_xy,
)
from palette import (
    COLOR_ACCENT,
    COLOR_BARK,
    COLOR_BARK_LIGHT,
    COLOR_BG,
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
    from PIL.Image import Image as PILImage  # noqa: F401
    from model import Arbre, Chantier  # noqa: F401


def _pil_load_fonts():
    """Charge un jeu de polices cohérent, avec fallback sur le défaut PIL."""
    if not HAS_PIL:
        return None
    from PIL import ImageFont
    candidates = [
        # Linux
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        # Windows
        r"C:\Windows\Fonts\georgiab.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
        # macOS
        "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
        "/Library/Fonts/Arial.ttf",
    ]
    paths = {"serif_bold": None, "sans": None, "sans_bold": None}
    for c in candidates:
        try:
            ImageFont.truetype(c, 12)
            name = c.lower()
            if paths["serif_bold"] is None and ("serifb" in name or "georgiab" in name):
                paths["serif_bold"] = c
            elif paths["sans_bold"] is None and "bold" in name and "serif" not in name:
                paths["sans_bold"] = c
            elif paths["sans"] is None and "serif" not in name:
                paths["sans"] = c
        except Exception:
            continue
    def f(size, variant="sans"):
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

    Si `show_legend=True`, une légende adaptative est dessinée à gauche
    du tronc (Bois sain / Bois dégradé / Écorce / Sondage / Classes) ;
    la section circulaire est alors décalée vers la droite pour ménager
    une bande dédiée à la légende.
    """
    from PIL import Image, ImageDraw
    f = _pil_load_fonts()
    img = Image.new("RGB", (width, height), COLOR_PANEL)
    d = ImageDraw.Draw(img, "RGBA")

    if arbre.rayon_tronc_cm <= 0:
        d.text((width/2, height/2),
               "Rayon non renseigné", fill=COLOR_MUTED,
               font=f(28, "sans"), anchor="mm")
        return img

    R = arbre.rayon_tronc_cm
    # Marges adaptées à la taille (responsive) :
    # - haut : titre+méta+lettre N hors écorce (proportionnel)
    # - bas : pastille S à l'intérieur, règle graduée + label
    if show_title:
        margin_top = max(140, int(height * 0.13))
    else:
        margin_top = 70   # juste pour que la lettre N tienne au-dessus
    # Si la légende doit être affichée, on la pose en bas (sous la règle
    # graduée), sur une seule ligne horizontale. On réserve donc une
    # bande de hauteur en bas, ce qui repousse la section vers le haut.
    legend_bottom_h = max(70, int(height * 0.085)) if show_legend else 0
    margin_bottom = max(160, int(height * 0.16)) + legend_bottom_h
    margin_side = max(80, int(width * 0.08))
    available_v = height - margin_top - margin_bottom
    available_h = width - 2 * margin_side
    radius_px_max = min(available_h / 2, available_v / 2)
    cx = width / 2
    cy = margin_top + radius_px_max
    # Réserver l'espace pour l'écorce + les contreforts. L'écorce ajoute
    # `epaisseur_ecorce_cm` vers l'extérieur, et les contreforts encore
    # `longueur_cm` au-delà.
    # `radius_px` reste le rayon en pixels du BOIS (tronc sous écorce) ;
    # `radius_ext_px` est le rayon externe (bois + écorce).
    ep = max(0.0, arbre.epaisseur_ecorce_cm)
    R_ext = R + ep
    expansion = ep + max((c.longueur_cm for c in arbre.contreforts),
                          default=0.0)
    R_eff = R + expansion
    scale = radius_px_max / R_eff
    radius_px = R * scale
    radius_ext_px = R_ext * scale

    # Helpers locaux : on délègue aux primitives de geometry.py mais on
    # capture (cx, cy, scale) pour rester lisible côté call-sites.
    def polar(r_cm, idx):
        return polar_idx_to_xy(cx, cy, scale, r_cm, idx)

    def polar_grade(r_cm, grade):
        return polar_to_xy(cx, cy, scale, r_cm, grade)

    # Disque bois sain
    d.ellipse([cx-radius_px, cy-radius_px, cx+radius_px, cy+radius_px],
              fill=COLOR_WOOD)

    # Cernes de croissance — par-dessus le bois, en brun très foncé fin.
    # Ils seront partiellement effacés par la cavité qui suit, ce qui les
    # rend visibles uniquement dans le bois sain.
    for k in range(1, 9):
        rr = radius_px * k / 9
        d.ellipse([cx-rr, cy-rr, cx+rr, cy+rr],
                  outline=COLOR_CERNE, width=1)

    # Cavité altération (spline) — couleur uniforme, pas de contour
    arbre.recompute_alteration_from_sondages()
    alt = arbre.alteration_par_grade
    if any(a > 0 for a in alt):
        smooth = cavity_polygon(alt, cx, cy, scale, samples_per_segment=32)
        d.polygon(smooth, fill=COLOR_ROT, outline=None)

    # Écorce. Si une épaisseur est renseignée, on dessine un anneau
    # brun épais entre R et R+ep ; sinon trait fin classique au bord
    # du bois.
    # Note PIL : `d.ellipse(outline, width)` trace l'outline À
    # L'INTÉRIEUR du bounding box (pas centré sur la frontière
    # comme Tkinter). Avec bbox de rayon R_ext et width=ep_px,
    # l'outline va de R_ext-ep à R_ext, soit exactement [R, R_ext].
    if ep > 0:
        ep_px = max(1.0, ep * scale)
        d.ellipse([cx-radius_ext_px, cy-radius_ext_px,
                   cx+radius_ext_px, cy+radius_ext_px],
                  outline=COLOR_BARK, width=int(round(ep_px)))
    else:
        d.ellipse([cx-radius_px, cy-radius_px,
                   cx+radius_px, cy+radius_px],
                  outline=COLOR_BARK, width=4)

    # Contreforts (empattements à la base du tronc) — fusionnés par
    # zones connectées via `contrefort_zone_outline`. Plusieurs
    # contreforts qui se touchent sont rendus comme une seule cloche
    # unifiée (max des hauteurs), ce qui évite l'encoche en V.
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

    # Dégradations externes — dessinées EN DERNIER pour qu'elles
    # creusent l'écorce ET les contreforts dans leur secteur.
    # Le bord externe du polygone suit la surface réelle de l'arbre
    # (R + ep + cloche), donc une dégradation qui passe sur un
    # contrefort y mord à concurrence de sa profondeur.
    for deg in arbre.degradations_externes:
        pts_arc = degradation_externe_outline(deg, arbre.contreforts,
                                               R, ep, cx, cy, scale)
        if pts_arc:
            d.polygon(pts_arc, fill=COLOR_ROT, outline=None)

    # Ticks 16 grades — à l'extérieur de l'écorce
    for i, g in enumerate(GRADES):
        x1, y1 = polar(R_ext, i)
        x2, y2 = polar(R_ext + 12/scale, i)
        maj = (g % 50 == 0)
        d.line([x1, y1, x2, y2],
               fill=COLOR_BARK if maj else COLOR_BARK_LIGHT,
               width=3 if maj else 1)

    # Lettres cardinales — à 35 px hors écorce, halo blanc
    for i, g in enumerate(GRADES):
        lbl = DIRECTION_LABELS.get(g, "")
        if not lbl:
            continue
        lx, ly = polar(R_ext + 45/scale, i)
        for dx in (-4, -3, 0, 3, 4):
            for dy in (-4, -3, 0, 3, 4):
                if dx or dy:
                    d.text((lx+dx, ly+dy), lbl, font=f(36, "serif_bold"),
                           fill="white", anchor="mm")
        d.text((lx, ly), lbl, font=f(36, "serif_bold"),
               fill=COLOR_INK, anchor="mm")

    # Sondages (optionnel) — pastilles à l'INTÉRIEUR du tronc, juste sous
    # l'écorce. Cela libère tout l'extérieur pour les lettres cardinales.
    if show_sondages:
        port = arbre.port_arbre
        meche = arbre.meche_cm if arbre.meche_cm > 0 else float("inf")
        # Profondeur de dégradation externe par direction : la pastille
        # est classée sur la PRBS AJUSTÉE (PRBS - dégrad. externe
        # couvrant le grade) pour rester cohérente avec le tableau
        # Diagnostic et la fiche PDF.
        deg_ext_par_grade = arbre.degradation_externe_par_grade()
        for s in arbre.sondages:
            if s.grade not in GRADES:
                continue
            i = GRADES.index(s.grade)
            penetration = min(s.bois_sain_cm + s.bois_altere_cm, meche)
            penetration = max(0.0, min(penetration, R))
            end_radius = R - penetration
            prbs_adj = max(0.0, s.prbs_cm - deg_ext_par_grade[i])
            ratio_adj = prbs_adj / R if R > 0 else 0.0
            col_class = COULEUR_CLASSE[classer_prbs(ratio_adj, port)]
            # Flèche : depuis 18 px sous l'écorce vers la fin de pénétration
            x_ext, y_ext = polar(R - 18/scale, i)
            x_end, y_end = polar(end_radius, i)
            d.line([x_ext, y_ext, x_end, y_end], fill=COLOR_SOND, width=4)
            ang = math.atan2(y_end-y_ext, x_end-x_ext)
            ah = 12
            d.polygon([
                (x_end, y_end),
                (x_end - ah*math.cos(ang-0.5), y_end - ah*math.sin(ang-0.5)),
                (x_end - ah*math.cos(ang+0.5), y_end - ah*math.sin(ang+0.5)),
            ], fill=COLOR_SOND)
            # Pastille à 18 px à l'INTÉRIEUR de l'écorce
            px, py = polar(R - 18/scale, i)
            r_b = 22
            d.ellipse([px-r_b-2, py-r_b-2, px+r_b+2, py+r_b+2],
                      fill="white")
            d.ellipse([px-r_b, py-r_b, px+r_b, py+r_b],
                      fill=col_class, outline="white", width=2)
            d.text((px, py), str(s.numero), font=f(20, "sans_bold"),
                   fill="white", anchor="mm")

    # RÈGLE GRADUÉE — placée SOUS la section, hors de l'écorce.
    # Étendue jusqu'au rayon externe (R + ep). La portion bois
    # ([-R, +R]) est en trait noir fin ; les portions écorce
    # ([-R_ext, -R] et [+R, +R_ext]) sont des barres brun foncé
    # épaisses qui évoquent l'écorce.
    step = 5 if R >= 15 else (2 if R >= 6 else 1)
    y_axis = cy + radius_ext_px + 105
    y_axis = min(y_axis, height - 60)
    wood_half_px = R * scale
    ext_half_px = R_ext * scale
    x_lw, x_rw = cx - wood_half_px, cx + wood_half_px
    x_le, x_re = cx - ext_half_px, cx + ext_half_px

    # Trait bois (noir fin) au centre
    d.line([x_lw, y_axis, x_rw, y_axis], fill=COLOR_INK, width=3)
    # Barres écorce (brun foncé épais) aux extrémités
    if ep > 0:
        bar_h = 10
        d.rectangle([x_le, y_axis - bar_h/2,
                     x_lw, y_axis + bar_h/2], fill=COLOR_BARK)
        d.rectangle([x_rw, y_axis - bar_h/2,
                     x_re, y_axis + bar_h/2], fill=COLOR_BARK)
    # Tirets aux extrémités externes (R+ep)
    end_color = COLOR_BARK if ep > 0 else COLOR_INK
    d.line([x_le, y_axis-12, x_le, y_axis+12], fill=end_color, width=3)
    d.line([x_re, y_axis-12, x_re, y_axis+12], fill=end_color, width=3)
    # Tirets à la transition bois/écorce (R)
    if ep > 0:
        d.line([x_lw, y_axis-9, x_lw, y_axis+9], fill=COLOR_INK, width=3)
        d.line([x_rw, y_axis-9, x_rw, y_axis+9], fill=COLOR_INK, width=3)
    # Graduations intermédiaires (bois) tous les `step` cm,
    # exclues à la valeur R (déjà marquée par le tiret de transition).
    for r in range(step, int(R), step):
        rr = r * scale
        for sign in (-1, 1):
            xg = cx + sign * rr
            d.line([xg, y_axis-7, xg, y_axis+7], fill=COLOR_INK, width=2)
            d.text((xg, y_axis+28), f"{r}",
                   font=f(18, "sans_bold"), fill=COLOR_INK, anchor="mm")
    # Étiquette à R (bord bois/écorce) en gras
    if R > 0:
        label_R = f"{R:g}"
        for xg in (x_lw, x_rw):
            d.text((xg, y_axis+28), label_R,
                   font=f(18, "sans_bold"), fill=COLOR_INK, anchor="mm")
    # Étiquette à R+ep (extrémité externe) en gras brun.
    # Si l'écart bois/écorce est trop serré (ep_px < 45 px en PIL),
    # on décale d'une ligne en dessous pour ne pas chevaucher R.
    if ep > 0:
        label_ext = f"{R + ep:g}"
        ext_y = y_axis + (52 if ep * scale < 45 else 28)
        for xg in (x_le, x_re):
            d.text((xg, ext_y), label_ext,
                   font=f(18, "sans_bold"), fill=COLOR_BARK, anchor="mm")
    # Repère "0" au centre
    d.text((cx, y_axis+28), "0",
           font=f(18, "sans_bold"), fill=COLOR_INK, anchor="mm")
    # Label "cm" à droite
    d.text((x_re+35, y_axis), "cm",
           font=f(20, "sans_bold"), fill=COLOR_INK, anchor="lm")
    # Point central de la section
    d.ellipse([cx-5, cy-5, cx+5, cy+5], fill=COLOR_INK)

    # Titre — positions proportionnelles à la hauteur (si show_title)
    if show_title:
        title_y = max(45, int(height * 0.045))
        sub_y = title_y + 52
        d.text((width/2, title_y), arbre.display_name,
               font=f(44, "serif_bold"), fill=COLOR_ACCENT, anchor="mm")
        sub_parts = [f"Rayon {R:g} cm"]
        if arbre.diametre_sous_ecorce_cm:
            sub_parts.append(f"Ø sous écorce {arbre.diametre_sous_ecorce_cm:g} cm")
        if arbre.hauteur_arbre_m:
            sub_parts.append(f"H {arbre.hauteur_arbre_m:g} m")
        if arbre.meche_cm:
            sub_parts.append(f"Mèche {arbre.meche_cm:g} cm")
        d.text((width/2, sub_y), "   •   ".join(sub_parts),
               font=f(24, "sans"), fill=COLOR_MUTED, anchor="mm")

    # Légende horizontale (uniquement si demandée), placée sous la
    # règle graduée. Elle occupe la bande inférieure réservée par
    # `legend_bottom_h` plus haut.
    if show_legend:
        legend_y = y_axis + max(50, int(height * 0.045))
        _draw_horizontal_legend_pil(d, arbre, y_top=legend_y,
                                     width=width, height=height,
                                     font_fn=f)

    return img


def _draw_horizontal_legend_pil(d, arbre, y_top, width, height,
                                font_fn) -> None:
    """Dessine la légende du dessin de section sur UNE LIGNE horizontale,
    centrée, sous la règle graduée.

    Légende adaptative : on n'affiche que les éléments effectivement
    présents sur le dessin (Bois dégradé seulement s'il y a des
    altérations ou dégradations externes ; Écorce seulement si une
    épaisseur > 0 a été renseignée ; etc.). Les classes du sondage
    (Vert/Orange/Rouge) sont toujours affichées si l'arbre a au moins
    un sondage — elles documentent la signification des pastilles
    colorées sur le dessin.
    """
    ep = max(0.0, arbre.epaisseur_ecorce_cm)
    has_decay = (
        bool(arbre.degradations_externes)
        or any(s.bois_altere_cm > 0 for s in arbre.sondages)
        or any(a > 0 for a in arbre.alteration_par_grade)
    )
    has_bark = ep > 0
    has_sondages = bool(arbre.sondages)

    item_size = max(13, int(height * 0.018))
    swatch_w = max(20, int(height * 0.024))
    swatch_h = max(14, int(height * 0.018))
    r_p = max(8, int(height * 0.012))
    item_font = font_fn(item_size, "sans")
    bold_font = font_fn(item_size, "sans_bold")

    items = [("wood", "Bois sain")]
    if has_decay:
        items.append(("rot", "Bois dégradé"))
    if has_bark:
        items.append(("bark", "Écorce"))
    if has_sondages:
        items.append(("arrow", "Sondage"))

    classes = tuple(
        (label, COULEUR_CLASSE[label])
        for label in (CLASSE_VERT, CLASSE_ORANGE, CLASSE_ROUGE)
    ) if has_sondages else ()
    classes_prefix = "Classe du sondage :"

    # Pré-calcul des largeurs pour centrer le bloc complet.
    def text_w(txt, font):
        bbox = d.textbbox((0, 0), txt, font=font)
        return bbox[2] - bbox[0]

    item_widths = [swatch_w + 8 + text_w(label, item_font)
                   for _, label in items]
    classes_w = 0
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


def _fit_text(text: str, font, max_width: float, draw) -> str:
    """Tronque `text` avec une ellipsis « … » si sa largeur dépasse
    `max_width`. Évite que les valeurs débordent de leur colonne."""
    if not text:
        return ""
    bbox = draw.textbbox((0, 0), text, font=font)
    if bbox[2] - bbox[0] <= max_width:
        return text
    ellipsis = "…"
    while text:
        text = text[:-1]
        bbox = draw.textbbox((0, 0), text + ellipsis, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return text + ellipsis
    return ellipsis


def render_fiche_arbre_to_pdf_page(arbre: "Arbre",
                                   chantier: "Chantier") -> "PILImage":
    """Construit une page A4 portrait 150 DPI (1240 × 1754 px environ)
    avec : en-tête chantier, dessin, tableau PRBS, diagnostic.

    Les tailles de police, largeurs de colonnes et marges sont calibrées
    pour rester lisibles à l'impression (≈ 12 pt minimum au tirage A4).
    """
    from PIL import Image, ImageDraw
    f = _pil_load_fonts()

    # A4 portrait à 150 DPI
    W, H = 1240, 1754
    page = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(page)

    margin = 60
    y = margin

    # --- En-tête mission avec logo Silvavenir ---
    header_h = 116
    d.rectangle([margin, y, W-margin, y+header_h], fill=COLOR_ACCENT)
    # Logo à droite
    logo_w = 0
    try:
        logo_path = Path(__file__).parent / "silvavenir_logo.jpg"
        if logo_path.exists():
            logo = Image.open(logo_path).convert("RGBA")
            target_h = header_h - 24
            ratio = target_h / logo.height
            logo = logo.resize(
                (int(logo.width * ratio), target_h),
                Image.LANCZOS)
            # Fond blanc derrière le logo pour le détacher du vert
            logo_bg = Image.new("RGB", logo.size, "white")
            logo_bg.paste(logo, (0, 0), logo if logo.mode == "RGBA" else None)
            page.paste(logo_bg,
                       (W - margin - logo.width - 12, y + 12))
            logo_w = logo.width + 24
    except Exception:
        pass

    # Largeur disponible pour le texte d'en-tête (sans empiéter sur le logo)
    header_text_w = W - margin*2 - logo_w - 20
    title_txt = "Fiche d'expertise — Pénétromètre"
    d.text((margin+20, y+22), title_txt,
           font=f(30, "serif_bold"), fill="white")
    mission_txt = _fit_text(
        f"Mission : {chantier.nom}   •   {chantier.adresse}",
        f(19, "sans"), header_text_w, d)
    d.text((margin+20, y+64), mission_txt,
           font=f(19, "sans"), fill="white")
    d.text((margin+20, y+92),
           f"{chantier.date_releve}   •   Opérateur : {chantier.operateur}",
           font=f(17, "sans"), fill="white")
    y += header_h + 18

    # --- Identité de l'arbre ---
    d.text((margin, y), arbre.display_name,
           font=f(35, "serif_bold"), fill=COLOR_INK)
    y += 50
    R = arbre.rayon_tronc_cm
    ligne = (f"Rayon : {R:g} cm   •   "
             f"Ø sous écorce : {arbre.diametre_sous_ecorce_cm:g} cm   •   "
             f"Hauteur : {arbre.hauteur_arbre_m:g} m   •   "
             f"Port : {arbre.port_arbre}")
    ligne = _fit_text(ligne, f(18, "sans"), W - 2*margin, d)
    d.text((margin, y), ligne, font=f(18, "sans"), fill=COLOR_MUTED)
    y += 32
    if arbre.commentaire:
        comm = _fit_text(f"Commentaire : {arbre.commentaire}",
                          f(17, "sans"), W - 2*margin, d)
        d.text((margin, y), comm, font=f(17, "sans"), fill=COLOR_INK)
        y += 30

    # --- Dessin ---
    # Taille adaptative : on estime la hauteur que vont occuper le
    # tableau PRBS et le diagnostic, puis on alloue le reste au dessin
    # (entre 480 et 900 px). Évite que la page déborde quand l'arbre a
    # beaucoup de sondages, sans rapetisser inutilement le dessin quand
    # il en a peu.
    n_sond = len(arbre.sondages) if R > 0 else 0
    # Hauteur de ligne adaptative : on resserre les lignes du tableau
    # quand l'arbre a beaucoup de sondages, pour éviter de déborder de la
    # page. La police reste lisible (15 pt minimum).
    if n_sond > 12:
        row_h = 32
        row_font_size = 15
    elif n_sond > 8:
        row_h = 35
        row_font_size = 16
    else:
        row_h = 38
        row_font_size = 17
    est_table_h = (36 + 44 + n_sond * row_h + 18) if n_sond > 0 else 0
    est_diag_h = 360  # majorant : t/R + bar + détail + classe globale
    # La légende horizontale est dessinée APRÈS le dessin du tronc, sur
    # la pleine largeur de la page (pas dans l'image du tronc qui est
    # plus étroite). On réserve une bande pour elle dans le calcul.
    est_legend_h = 56
    footer_reserve = 60
    used_so_far = y - margin   # depuis le haut de la page utile
    remaining = (H - margin - footer_reserve) - used_so_far \
                - est_table_h - est_diag_h - est_legend_h - 22
    drawing_h = max(420, min(900, remaining))
    drawing_w = drawing_h
    # Le dessin lui-même est rendu sans légende ; la légende est tracée
    # ci-dessous, en dehors du dessin, pour profiter de toute la largeur.
    drawing = render_arbre_to_pil_image(arbre, drawing_w, drawing_h,
                                        show_sondages=True,
                                        show_title=False,
                                        show_legend=False)
    x_draw = (W - drawing_w) // 2
    page.paste(drawing, (x_draw, y))
    y += drawing_h + 6
    # Légende horizontale, centrée, sur la pleine largeur utile. Calibrée
    # pour donner des polices ≈ 16 pt et des pastilles bien lisibles.
    if R > 0:
        _draw_horizontal_legend_pil(d, arbre, y_top=y,
                                     width=W, height=900, font_fn=f)
        y += est_legend_h

    # --- Tableau PRBS ajustée par sondage ---
    if R > 0 and arbre.sondages:
        d.text((margin, y), "Paroi Résiduelle de Bois Sain par sondage",
               font=f(22, "serif_bold"), fill=COLOR_ACCENT)
        y += 36
        deg_ext_par_grade = arbre.degradation_externe_par_grade()
        # Largeurs de colonnes redistribuées : Direction et PRBS plus
        # généreuses (où les valeurs sont les plus longues), Compart.
        # rétrécie (souvent juste « - » ou « active »).
        # Total = 70 + 220 + 270 + 130 + 160 + 270 = 1120 = W - 2*margin.
        col_widths = [70, 220, 270, 130, 160, 270]
        cols_x = [margin]
        for w in col_widths:
            cols_x.append(cols_x[-1] + w)
        # cols_x = [60, 130, 350, 620, 750, 910, 1180]
        headers = ["N°", "Direction", "PRBS ajustée (cm)", "t/R (%)",
                   "Classe", "Compart."]
        # Alignement : N° et nombres à droite ; texte à gauche.
        right_align = {0, 3}            # N°, t/R (%)
        right_align_data = {0, 3}       # idem pour les valeurs
        header_h_row = 44
        d.rectangle([cols_x[0], y, cols_x[-1], y+header_h_row],
                    fill=COLOR_ACCENT)
        for i, h in enumerate(headers):
            if i in right_align:
                d.text((cols_x[i+1]-12, y+header_h_row/2), h,
                       font=f(17, "sans_bold"), fill="white",
                       anchor="rm")
            else:
                d.text((cols_x[i]+12, y+header_h_row/2), h,
                       font=f(17, "sans_bold"), fill="white",
                       anchor="lm")
        y += header_h_row
        for k, s in enumerate(arbre.sondages):
            dir_lbl = DIRECTION_LABELS.get(s.grade, "")
            direction = f"{dir_lbl} ({s.grade} gr)" if dir_lbl \
                else f"{s.grade} gr"
            idx_g = GRADES.index(s.grade) if s.grade in GRADES else 0
            deg_ext = deg_ext_par_grade[idx_g]
            prbs_adj = max(0.0, s.prbs_cm - deg_ext)
            ratio = prbs_adj / R
            classe = classer_prbs(ratio, arbre.port_arbre)
            col_c = COULEUR_CLASSE[classe]
            if k % 2 == 0:
                d.rectangle([cols_x[0], y, cols_x[-1], y+row_h],
                            fill=COLOR_BG)
            if deg_ext > 0:
                prbs_txt = f"{prbs_adj:g}  (–{deg_ext:g} ext.)"
            else:
                prbs_txt = f"{prbs_adj:g}"
            vals = [str(s.numero), direction, prbs_txt,
                    f"{100*ratio:.1f}", classe, s.compartimentation]
            for i, v in enumerate(vals):
                col = col_c if i == 4 else COLOR_INK
                wt = "sans_bold" if i == 4 else "sans"
                font_v = f(row_font_size, wt)
                col_w = col_widths[i] - 24  # padding 12 de chaque côté
                txt = _fit_text(v, font_v, col_w, d)
                if i in right_align_data:
                    d.text((cols_x[i+1]-12, y+row_h/2), txt,
                           font=font_v, fill=col, anchor="rm")
                else:
                    d.text((cols_x[i]+12, y+row_h/2), txt,
                           font=font_v, fill=col, anchor="lm")
            y += row_h
        y += 18

    # --- Diagnostic global enrichi (répartition par classe) ---
    d.text((margin, y), "Diagnostic",
           font=f(22, "serif_bold"), fill=COLOR_ACCENT)
    y += 36
    rep = arbre.repartition_classes()
    ratios = arbre.ratio_tR_par_grade()
    if R > 0 and not all(r >= 0.999 for r in ratios):
        d.text((margin, y),
               f"t/R moyen sur le pourtour : {100*rep['tR_moyen']:.1f} %",
               font=f(18, "sans_bold"), fill=COLOR_INK)
        y += 28
        d.text((margin, y),
               f"t/R minimal : {100*rep['tR_min']:.1f} %  "
               f"(grade {rep['tR_min_grade']} gr — {rep['tR_min_dir']})",
               font=f(18, "sans"), fill=COLOR_INK)
        y += 32
        d.text((margin, y),
               "Répartition sur le pourtour (16 directions) :",
               font=f(18, "sans_bold"), fill=COLOR_INK)
        y += 30
        # Barre horizontale empilée Vert/Orange/Rouge — plus haute pour
        # que le pourcentage soit lisible même sur des segments étroits.
        bar_w = W - 2*margin
        bar_h = 36
        x_cur = margin
        # Petites étiquettes hors-barre pour les segments trop étroits
        # pour porter leur texte à l'intérieur.
        outside_labels = []
        for cls in ("Vert", "Orange", "Rouge"):
            seg_pct = rep[cls]["pct"]
            seg_w = bar_w * seg_pct / 100.0
            if seg_w > 0:
                col = COULEUR_CLASSE[cls]
                d.rectangle([x_cur, y, x_cur + seg_w, y + bar_h],
                            fill=col)
                if seg_w > 95:
                    d.text((x_cur + seg_w/2, y + bar_h/2),
                           f"{cls} {seg_pct:.0f} %",
                           font=f(15, "sans_bold"), fill="white",
                           anchor="mm")
                else:
                    outside_labels.append((cls, seg_pct, col,
                                            x_cur + seg_w/2))
                x_cur += seg_w
        y += bar_h + 4
        # Étiquettes externes (au-dessous de la barre, en couleur du
        # segment), avec petit triangle indicateur au-dessus.
        for cls, pct, col, x_center in outside_labels:
            d.polygon([(x_center, y),
                       (x_center - 6, y + 8),
                       (x_center + 6, y + 8)], fill=col)
            d.text((x_center, y + 12), f"{cls} {pct:.0f} %",
                   font=f(15, "sans_bold"), fill=col, anchor="mt")
        if outside_labels:
            y += 36
        else:
            y += 8
        # Détail textuel — sur UNE seule ligne pour économiser l'espace.
        # On n'affiche que les classes non vides, séparées par " • ", et
        # chaque libellé est rendu dans la couleur de sa classe.
        chunks = []
        for cls in ("Vert", "Orange", "Rouge"):
            n = rep[cls]["n"]
            if n > 0:
                grades = rep[cls]["grades"]
                col = COULEUR_CLASSE[cls]
                chunks.append(
                    (f"{cls} {n}/16 ({grades} gr)", col))
        if chunks:
            font_chunk = f(17, "sans")
            font_sep = f(17, "sans")
            sep = "   •   "
            sep_w = d.textbbox((0, 0), sep, font=font_sep)[2]
            x_chunk = margin
            for i, (txt, col) in enumerate(chunks):
                if i > 0:
                    d.text((x_chunk, y), sep,
                           font=font_sep, fill=COLOR_MUTED)
                    x_chunk += sep_w
                d.text((x_chunk, y), txt, font=font_chunk, fill=col)
                bbox = d.textbbox((0, 0), txt, font=font_chunk)
                x_chunk += bbox[2] - bbox[0]
            y += 28
        y += 10
        # Gros marqueur coloré pour la classe globale (basée sur t/R moyen).
        # Boîte plus large et plus haute pour rester proportionnée aux
        # autres éléments de la page.
        classe_g = rep["classe_globale"]
        col_g = COULEUR_CLASSE[classe_g]
        box_w, box_h = 460, 60
        d.rectangle([margin, y, margin+box_w, y+box_h], fill=col_g)
        d.text((margin+box_w/2, y+box_h/2),
               f"Classe globale : {classe_g}",
               font=f(24, "sans_bold"), fill="white", anchor="mm")
        y += box_h + 8
    else:
        d.text((margin, y), "Aucune altération saisie.",
               font=f(18, "sans"), fill=COLOR_INK)

    # --- Pied de page ---
    d.line([margin, H-46, W-margin, H-46], fill=COLOR_MUTED, width=1)
    d.text((W/2, H-24),
           f"Pénétromètre — Silvavenir, Foresterie urbaine   •   "
           f"Édité le {datetime.now().strftime('%d/%m/%Y à %H:%M')}",
           font=f(14, "sans"), fill=COLOR_MUTED, anchor="mm")

    return page
