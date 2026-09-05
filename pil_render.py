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
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

from bareme import CLASSE_ORANGE, CLASSE_ROUGE, CLASSE_VERT
from diagnostic import (
    compute_alteration_par_grade,
    sondage_render_data,
)
from geometry import (
    RadiusSpec,
    adaptive_ruler_step_cm,
    brins_layout,
    cardinal_label_positions,
    cavity_polygon,
    cerne_radii_px,
    contour_polygon,
    contrefort_zone_outline,
    contrefort_zones,
    degradation_externe_outline,
    radial_ruler_data,
    radial_ruler_grade,
    ring_polygon_points,
    tick_endpoints,
)
from palette import (
    COLOR_BARK,
    COLOR_BARK_LIGHT,
    COLOR_CERNE,
    COLOR_INK,
    COLOR_MUTED,
    COLOR_PANEL,
    COLOR_RENDER_ACCENT,
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

    from model import Arbre, Brin  # noqa: F401

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


def _titre_y(height: int) -> int:
    """Ordonnée (centre) du titre — partagée par `_pil_draw_titre` et le
    calcul de marge haute (`_margin_top_titre`)."""
    return max(48, int(height * 0.042))


def _margin_top_titre(height: int, ds: float) -> int:
    """Marge haute quand le titre est affiché.

    Empile : bas du titre (`_titre_y` + demi-police 54) + respiration +
    lettre N de la boussole (offset hors écorce + demi-lettre 44). Un
    simple pourcentage de la hauteur ne suffit pas : le titre et l'offset
    des cardinales ne croissent pas au même rythme qu'elle, et le « N »
    finissait sous le titre sur les grands exports (constaté à 2400²).
    """
    title_bottom = _titre_y(height) + int(27 * ds)
    return title_bottom + int(10 * ds) + CARDINALES_OFFSET_PX + int(22 * ds)


@lru_cache(maxsize=1)
def _pil_font_paths() -> Dict[str, Optional[str]]:
    """Chemin retenu pour chaque variante de police (sondé une seule fois).

    La détection ouvre jusqu'à 11 fichiers de police pour trouver le
    premier disponible par variante. C'est un coût de découverte, pas de
    rendu : il n'a aucune raison d'être payé à chaque image. Le cache est
    volontairement au niveau module — les polices installées ne changent
    pas pendant la vie du processus.
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
    return paths


@lru_cache(maxsize=64)
def _pil_font(size: int, variant: str) -> Any:
    """Objet police PIL pour `(taille, variante)`, **mémorisé**.

    Sans ce cache, chaque `d.text(...)` reconstruisait un `FreeTypeFont`
    — donc rouvrait le .ttf ET repartait d'un cache de glyphes vide. Le
    halo blanc des lettres cardinales tire 24 tracés par lettre : une
    seule fiche PDF déclenchait ~240 chargements de police, soit
    l'essentiel du temps d'export (profil : 1,4 s sur 2,9 s pour 20
    arbres).

    Réutiliser l'objet police ne change rien au rendu (même fichier,
    même taille, même moteur FreeType) : les golden-tests PIL le
    verrouillent.

    Non thread-safe au sens strict (les objets PIL partagent un cache de
    glyphes) : l'app ne rend jamais deux images en parallèle — l'export
    long tourne dans un worker unique, l'UI étant bloquée par sa fenêtre
    de progression.
    """
    from PIL import ImageFont
    paths = _pil_font_paths()
    path = paths.get(variant) or paths.get("sans") or paths.get("serif_bold")
    try:
        return ImageFont.truetype(path, size) if path \
            else ImageFont.load_default()
    except Exception:
        return ImageFont.load_default()


def _pil_load_fonts() -> FontFn:
    """Fabrique de polices `f(size, variant)` — API historique conservée.

    Priorité 1 : polices embarquées dans `assets/fonts/` (DejaVu sous
    licence permissive). Garantit un rendu PDF/PNG identique sur toute
    machine, indépendamment des polices système installées.
    Priorité 2 : polices système connues (Linux/Windows/macOS), pour
    rester compatible avec une installation où `assets/fonts/` aurait
    été retiré.

    N'est plus qu'un adaptateur vers `_pil_font` (mémorisé) : les
    appelants gardent leur signature, le coût disparaît.
    """
    def f(size: int, variant: str = "sans") -> Any:
        return _pil_font(size, variant)
    return f


def render_arbre_to_pil_image(arbre: "Arbre",
                              width: int = 1600, height: int = 1600,
                              show_sondages: bool = True,
                              show_title: bool = True,
                              show_legend: bool = False) -> "PILImage":
    """Rend la section transversale d'un arbre en image PIL (PNG/PDF).
    Logique identique à SectionCanvas.redraw() mais sans dépendance tk.

    Si `show_legend=True`, une légende adaptative est dessinée sous la
    section sur UNE LIGNE horizontale (Bois sain / Bois dégradé /
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

    # Cépée (≥ 2 brins, ou un brin décentré) : chemin de composition
    # multi-brins, dérivé tôt pour laisser le cas mono-brin centré (99 %)
    # strictement inchangé en dessous (goldens byte-identiques).
    brins = arbre.brins
    if not (len(brins) == 1 and brins[0].pos_x_cm == 0.0
            and brins[0].pos_y_cm == 0.0):
        _pil_draw_cepee(d, f, f_base, arbre, width, height, _ds,
                        show_sondages=show_sondages, show_title=show_title,
                        show_legend=show_legend)
        return img

    if arbre.rayon_tronc_cm <= 0:
        _pil_draw_placeholder(d, f_base, width, height)
        return img

    R = arbre.rayon_tronc_cm
    ep = max(0.0, arbre.epaisseur_ecorce_cm)
    # Marges adaptées à la taille (responsive) :
    # - haut : titre + lettre N hors écorce (empilés, cf. _margin_top_titre)
    # - bas : lettre S + halo (l'échelle est radiale, DANS la section —
    #   plus de règle horizontale sous le dessin)
    margin_top = _margin_top_titre(height, _ds) if show_title else 70
    legend_bottom_h = max(70, int(height * 0.09)) if show_legend else 0
    base_bottom = max(80, int(height * 0.06))
    margin_bottom = base_bottom + legend_bottom_h
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

    bullet_r = max(BULLET_RADIUS_PX, int(BULLET_RADIUS_PX * _ds))
    # Section elle-même (bois → pastilles + moelle + échelle radiale),
    # centrée en (cx, cy). Isolée dans `_pil_draw_brin` pour la composition
    # multi-brins (cépées) : un appel par brin à son propre centre. Les
    # décorations de repère (titre, légende) restent globales, ci-dessous.
    # `port`/`meche` sont genet-level (partagés par tous les brins) → passés
    # explicitement à la section.
    _pil_draw_brin(d, f, arbre.brin_courant, arbre.port_arbre, arbre.meche_cm,
                   cx, cy, R, ep, scale,
                   show_sondages=show_sondages, bullet_r=bullet_r, ds=_ds)
    if show_title:
        _pil_draw_titre(d, f, arbre, R, width, height)
    if show_legend:
        # Légende dans la bande TOUT EN BAS : la zone `base_bottom` reste
        # entre la section et la légende pour la lettre S (et son halo).
        legend_y = height - legend_bottom_h + int(height * 0.012)
        _draw_horizontal_legend_pil(d, arbre, y_top=legend_y,
                                     width=width, height=height,
                                     font_fn=f_base,
                                     show_sondage_item=False,
                                     show_classes=False)
    return img


def _pil_draw_brin(d: "ImageDraw.ImageDraw", f: FontFn, brin: "Brin",
                   port: str, meche: float,
                   cx: float, cy: float, R: float, ep: float, scale: float,
                   *, show_sondages: bool, bullet_r: int,
                   ds: float = 1.0, draw_cardinales: bool = True) -> None:
    """Dessine UNE section (bois → pastilles + moelle) centrée en (cx, cy).

    Regroupe toutes les couches **propres à un brin** dans l'ordre de
    superposition. Le repère partagé (titre, légende) reste à la
    charge de l'orchestrateur. Pour une cépée, l'orchestrateur appellera ce
    helper une fois par brin à son propre centre écran ; pour un genet
    mono-brin centré, le rendu est strictement identique à l'ancien.

    `port`/`meche` sont genet-level (sur l'`Arbre`, partagés par tous les
    brins) : passés explicitement pour positionner les sondages par brin.

    `draw_cardinales=False` omet les lettres N/E/S/O de CE brin : pour une
    cépée, la boussole est dessinée **une seule fois**, globalement (les
    brins partagent la même orientation). Les ticks restent par brin (ils
    marquent les 16 directions de sondage propres à chaque tige).
    """
    R_ext = R + ep
    # Fournisseur de rayon par direction : constant pour une section
    # circulaire (rendu identique à l'ancien), variable pour une ellipse.
    r_ext_of = (lambda g: brin.rayon_a_grade(g) + ep) if ep \
        else brin.rayon_a_grade
    _pil_draw_bois_sain(d, brin, cx, cy, R, scale)
    _pil_draw_cernes(d, brin, cx, cy, R, scale)
    _pil_draw_cavite(d, brin, cx, cy, scale)
    _pil_draw_ecorce(d, brin, cx, cy, R, ep, R_ext, scale)
    _pil_draw_contreforts(d, brin, cx, cy, ep, scale)
    # Dégradations EN DERNIER des couches de surface (cf. CLAUDE.md).
    _pil_draw_degradations(d, brin, cx, cy, ep, scale)
    _pil_draw_ticks(d, cx, cy, r_ext_of, scale)
    if draw_cardinales:
        _pil_draw_cardinales(d, f, cx, cy, r_ext_of, scale)
    if show_sondages:
        _pil_draw_sondages(d, f, brin, port, meche, cx, cy, R, scale, bullet_r)
    # Moelle (point central) du brin.
    dot_r = max(5, int(5 * ds))
    d.ellipse([cx-dot_r, cy-dot_r, cx+dot_r, cy+dot_r], fill=COLOR_INK)
    # Échelle radiale EN DERNIER : au premier plan pour rester lisible
    # par-dessus cavité, dégradations et flèches de sondage.
    _pil_draw_echelle_radiale(d, f, brin, cx, cy, scale, ds,
                              show_sondages=show_sondages)


def _pil_draw_brin_label(d: "ImageDraw.ImageDraw", f: FontFn, brin: "Brin",
                         cx: float, cy: float, R: float, scale: float,
                         ds: float) -> None:
    """Étiquette d'un brin (« a », « b », …) au-dessus de sa moelle, avec
    halo blanc pour rester lisible sur le bois. Rien si le brin n'a pas de
    label (brin unique d'un genet mono-caule)."""
    if not brin.label:
        return
    y = cy - max(6.0, R * scale * 0.45)
    size = max(22, int(30 * ds))
    for dx in (-3, 0, 3):
        for dy in (-3, 0, 3):
            if dx or dy:
                d.text((cx + dx, y + dy), brin.label,
                       font=f(size, "serif_bold"), fill="white", anchor="mm")
    d.text((cx, y), brin.label, font=f(size, "serif_bold"),
           fill=COLOR_RENDER_ACCENT, anchor="mm")


def _pil_draw_cepee(d: "ImageDraw.ImageDraw", f: FontFn, f_base: FontFn,
                    arbre: "Arbre", width: int, height: int, ds: float, *,
                    show_sondages: bool, show_title: bool,
                    show_legend: bool = False) -> None:
    """Compose une cépée : N brins positionnés dans un cadrage commun.

    Pendant multi-brins de la branche mono-brin de `render_arbre_to_pil_image`.
    Chaque brin est dessiné à son centre écran (via `geometry.brins_layout`)
    SANS sa boussole ; une seule boussole globale (orientation partagée) et
    le titre du genet sont ajoutés autour de la bounding box.

    Une cépée est large : `brins_layout` la cadre sur la largeur, ce qui
    laissait un grand vide vertical en bas. On **centre verticalement** les
    brins ; chaque brin porte sa propre **échelle radiale** (les brins ayant
    des rayons distincts, pas de règle commune) et, en export
    (`show_legend`), la **légende** occupe la bande basse.
    """
    drawable = [b for b in arbre.brins if b.rayon_tronc_cm > 0]
    if not drawable:
        _pil_draw_placeholder(d, f_base, width, height)
        return
    margin_top = _margin_top_titre(height, ds) if show_title else 70
    base_bottom = max(80, int(height * 0.06))
    margin_side = max(60, int(width * 0.055))
    # Réserver la place de la boussole globale (offset + demi-largeur d'une
    # lettre) pour qu'elle ne déborde pas du canvas sur les bords/coins.
    clear = CARDINALES_OFFSET_PX + int(32 * ds)
    margin_top = max(margin_top, clear)
    base_bottom = max(base_bottom, clear)
    margin_side = max(margin_side, clear)
    # Bande basse : légende (export seulement).
    legend_band = (max(70, int(height * 0.09))) if show_legend else 0
    margin_bottom = base_bottom + legend_band
    pe = [(b.pos_x_cm, b.pos_y_cm, b.extent_cm()) for b in drawable]
    scale, origin_x, origin_y = brins_layout(
        pe, width, height, margin_top, margin_bottom, margin_side)
    # Centrage vertical : `brins_layout` aligne le haut de la bbox sur
    # `margin_top` ; on redescend les brins pour les centrer dans la zone
    # disponible [margin_top, height - margin_bottom].
    y0_cm = min(py - e for _px, py, e in pe)
    y1_cm = max(py + e for _px, py, e in pe)
    bbox_h_px = (y1_cm - y0_cm) * scale
    avail_h_px = (height - margin_bottom) - margin_top
    origin_y += max(0.0, (avail_h_px - bbox_h_px) / 2.0)
    bullet_r = max(BULLET_RADIUS_PX, int(BULLET_RADIUS_PX * ds))
    port = arbre.port_arbre
    meche = arbre.meche_cm
    for b in drawable:
        cxb = origin_x + b.pos_x_cm * scale
        cyb = origin_y + b.pos_y_cm * scale
        epb = max(0.0, b.epaisseur_ecorce_cm)
        _pil_draw_brin(d, f, b, port, meche, cxb, cyb, b.rayon_tronc_cm, epb,
                       scale, show_sondages=show_sondages, bullet_r=bullet_r,
                       ds=ds, draw_cardinales=False)
        _pil_draw_brin_label(d, f, b, cxb, cyb, b.rayon_tronc_cm, scale, ds)
    # Boussole globale autour de la bounding box : orientation commune à
    # tous les brins. Placée sur le RECTANGLE de la bbox (N/S/E/O sur les
    # bords, diagonales aux coins) plutôt que sur un cercle — une cépée
    # large déborderait verticalement d'un cercle de rayon = demi-diagonale.
    x0 = min(px - e for px, _py, e in pe)
    x1 = max(px + e for px, _py, e in pe)
    y0 = min(py - e for _px, py, e in pe)
    y1 = max(py + e for _px, py, e in pe)
    x0s = origin_x + x0 * scale
    x1s = origin_x + x1 * scale
    y0s = origin_y + y0 * scale
    y1s = origin_y + y1 * scale
    cxg = (x0s + x1s) / 2.0
    cyg = (y0s + y1s) / 2.0
    off = CARDINALES_OFFSET_PX
    compass = (
        ("N", cxg, y0s - off), ("S", cxg, y1s + off),
        ("E", x1s + off, cyg), ("O", x0s - off, cyg),
        ("NE", x1s + off, y0s - off), ("NO", x0s - off, y0s - off),
        ("SE", x1s + off, y1s + off), ("SO", x0s - off, y1s + off),
    )
    for lbl, lx, ly in compass:
        for dx in (-4, -3, 0, 3, 4):
            for dy in (-4, -3, 0, 3, 4):
                if dx or dy:
                    d.text((lx + dx, ly + dy), lbl, font=f(44, "serif_bold"),
                           fill="white", anchor="mm")
        d.text((lx, ly), lbl, font=f(44, "serif_bold"),
               fill=COLOR_INK, anchor="mm")
    if show_title:
        _pil_draw_titre(d, f, arbre, drawable[0].rayon_tronc_cm, width, height)

    # Légende horizontale (export uniquement), dans la bande TOUT EN BAS :
    # la zone `base_bottom` reste entre les brins et la légende pour la
    # lettre S de la boussole globale.
    if show_legend:
        legend_y = height - legend_band + int(height * 0.012)
        _draw_horizontal_legend_pil(d, arbre, y_top=legend_y,
                                     width=width, height=height,
                                     font_fn=f_base,
                                     show_sondage_item=show_sondages,
                                     show_classes=False)


def _pil_draw_echelle_radiale(d: "ImageDraw.ImageDraw", f: FontFn,
                              brin: "Brin", cx: float, cy: float,
                              scale: float, ds: float, *,
                              show_sondages: bool) -> None:
    """Échelle radiale d'un brin : axe gradué du centre au bord du bois,
    prolongé d'un segment d'écorce, le long de l'axe Est (ou de la
    direction libre la plus proche si un sondage y est rendu, cf.
    `geometry.radial_ruler_grade`). Dessinée au premier plan avec un halo
    blanc pour rester lisible par-dessus cavité et dégradations.

    L'esquive n'opère que si les sondages sont AFFICHÉS (`show_sondages`) :
    masqués, il n'y a pas de flèche à éviter → échelle plein Est."""
    sond_grades = [s.grade for s in brin.sondages] if show_sondages else []
    gw = radial_ruler_grade(sond_grades, brin.rotation_grades)
    # La forme du brin est pivotée de `rotation_grades` : le rayon à la
    # direction MONDE `gw` est le rayon local à `gw - rotation`.
    R = brin.rayon_a_grade(gw - brin.rotation_grades)
    # Pour une direction dont le rayon local (mesuré à un sondage proche)
    # est bien plus petit que le rayon général, R peut être très petit →
    # étiquettes "0" et "N cm" quasi superposées. On bascule sur l'Est du
    # monde avec le rayon général dans ce cas.
    if brin.a_rayon_variable and R < brin.rayon_tronc_cm * 0.5:
        gw = float(brin.rotation_grades % 400)
        R = brin.rayon_tronc_cm
    ep = max(0.0, brin.epaisseur_ecorce_cm)
    step = adaptive_ruler_step_cm(scale, min_gap_px=int(60 * ds))
    data = radial_ruler_data(cx, cy, scale, R, ep, gw, step,
                             tick_len_px=int(16 * ds),
                             label_offset_px=int(50 * ds))
    if data is None:
        return
    lw = max(3, int(3 * ds))
    halo_w = lw + max(4, int(4 * ds))
    tick_w = max(2, int(2 * ds))
    (x0, y0), (xr, yr) = data.axis
    segments = [(x0, y0, xr, yr, COLOR_INK, lw)]
    if data.bark is not None:
        (bx0, by0), (bx1, by1) = data.bark
        segments.append((bx0, by0, bx1, by1, COLOR_BARK, lw))
    # Décide quels ticks intermédiaires affichent leur étiquette : "0" et
    # terminal toujours ; un intermédiaire seulement si son centre est à
    # ≥ 80 ds px du centre du terminal (évite les collisions de texte sans
    # supprimer les traits de graduation).
    n = len(data.ticks)
    term_lx = data.ticks[-1][4] if data.ticks else 0.0
    min_lbl_gap = int(80 * ds)
    def _show_label(i: int, lx: float) -> bool:
        return i == 0 or i == n - 1 or abs(term_lx - lx) >= min_lbl_gap
    # Passe 1 : halo blanc sous tous les traits (axe + écorce + tirets).
    for x1, y1, x2, y2, _col, _w in segments:
        d.line([x1, y1, x2, y2], fill="white", width=halo_w)
    for x1, y1, x2, y2, _lx, _ly, _lbl in data.ticks:
        d.line([x1, y1, x2, y2], fill="white", width=tick_w + 4)
    # Passe 2 : encre.
    for x1, y1, x2, y2, col, w in segments:
        d.line([x1, y1, x2, y2], fill=col, width=w)
    for i, (x1, y1, x2, y2, lx, ly, lbl) in enumerate(data.ticks):
        d.line([x1, y1, x2, y2], fill=COLOR_INK, width=tick_w)
        if not _show_label(i, lx):
            continue  # trait dessiné, étiquette omise (trop proche du terminal)
        for ox in (-3, 0, 3):
            for oy in (-3, 0, 3):
                if ox or oy:
                    d.text((lx + ox, ly + oy), lbl, font=f(28, "sans_bold"),
                           fill="white", anchor="mm")
        d.text((lx, ly), lbl, font=f(28, "sans_bold"),
               fill=COLOR_INK, anchor="mm")


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
#   _pil_draw_echelle_radiale    ↔ SectionCanvas._draw_echelle_radiale
#   _pil_draw_titre              ↔ SectionCanvas._draw_titre
# ----------------------------------------------------------------------


def _pil_draw_placeholder(d: "ImageDraw.ImageDraw", f: FontFn,
                          width: int, height: int) -> None:
    d.text((width/2, height/2),
           "Rayon non renseigné", fill=COLOR_MUTED,
           font=f(28, "sans"), anchor="mm")


def _pil_draw_bois_sain(d: "ImageDraw.ImageDraw", brin: "Brin",
                        cx: float, cy: float,
                        R: float, scale: float) -> None:
    if brin.a_rayon_variable:
        d.polygon(contour_polygon(brin.rayon_a_grade, cx, cy, scale,
                                  rotation_grades=brin.rotation_grades),
                  fill=COLOR_WOOD)
        return
    # Section circulaire : un cercle est invariant par rotation → primitive
    # native (rendu byte-identique, goldens stables).
    radius_px = R * scale
    d.ellipse([cx-radius_px, cy-radius_px, cx+radius_px, cy+radius_px],
              fill=COLOR_WOOD)


def _pil_draw_cernes(d: "ImageDraw.ImageDraw", brin: "Brin",
                     cx: float, cy: float,
                     R: float, scale: float) -> None:
    if brin.a_rayon_variable:
        # Cernes = contours homothétiques (k/(N+1) du rayon local).
        for k in range(1, N_CERNES + 1):
            frac = k / (N_CERNES + 1)

            def r_cerne(g: float, frac: float = frac) -> float:
                return brin.rayon_a_grade(g) * frac

            d.polygon(contour_polygon(r_cerne, cx, cy, scale,
                                      rotation_grades=brin.rotation_grades),
                      outline=COLOR_CERNE, width=1)
        return
    for rr in cerne_radii_px(R, scale, N_CERNES):
        d.ellipse([cx-rr, cy-rr, cx+rr, cy+rr],
                  outline=COLOR_CERNE, width=1)


def _pil_draw_cavite(d: "ImageDraw.ImageDraw", brin: "Brin",
                     cx: float, cy: float, scale: float) -> None:
    alt = compute_alteration_par_grade(brin)
    if not any(a > 0 for a in alt):
        return
    smooth = cavity_polygon(alt, cx, cy, scale,
                              samples_per_segment=CAVITY_SAMPLES_PER_SEGMENT,
                              rotation_grades=brin.rotation_grades)
    d.polygon(smooth, fill=COLOR_ROT, outline=None)


def _pil_draw_ecorce(d: "ImageDraw.ImageDraw", brin: "Brin",
                     cx: float, cy: float,
                     R: float, ep: float, R_ext: float,
                     scale: float) -> None:
    if brin.a_rayon_variable:
        rot = brin.rotation_grades
        inner = contour_polygon(brin.rayon_a_grade, cx, cy, scale,
                                rotation_grades=rot)
        if ep > 0:
            def r_outer(g: float) -> float:
                return brin.rayon_a_grade(g) + ep

            outer = contour_polygon(r_outer, cx, cy, scale,
                                    rotation_grades=rot)
            # Anneau d'écorce : contour externe + contour interne inversé,
            # technique du trou de serrure (cf. `geometry.ring_polygon_points`
            # — un pont aller-retour au MÊME angle, sinon fin artefact non
            # rempli à la jointure).
            d.polygon(ring_polygon_points(outer, inner), fill=COLOR_BARK)
        else:
            d.line(inner + [inner[0]], fill=COLOR_BARK, width=4, joint="curve")
        return
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


def _pil_draw_contreforts(d: "ImageDraw.ImageDraw", brin: "Brin",
                          cx: float, cy: float,
                          ep: float, scale: float) -> None:
    # Fusionnés par zones connectées : plusieurs contreforts qui se
    # touchent sont rendus comme une seule cloche unifiée (max des
    # hauteurs), ce qui évite l'encoche en V. La base des cloches suit le
    # rayon LOCAL (constant si circulaire, ellipse sinon).
    for zone in contrefort_zones(brin.contreforts):
        poly = contrefort_zone_outline(zone, brin.contreforts,
                                        brin.rayon_a_grade, ep,
                                        cx, cy, scale,
                                        rotation_grades=brin.rotation_grades)
        wood_outer = poly["wood_outer"]
        if ep > 0:
            d.polygon(poly["bark_outer"] + poly["bark_inner"],
                      fill=COLOR_BARK)
        d.polygon(wood_outer + poly["base"], fill=COLOR_WOOD)
        if ep == 0:
            d.line(wood_outer, fill=COLOR_BARK, width=4, joint="curve")


def _pil_draw_degradations(d: "ImageDraw.ImageDraw", brin: "Brin",
                           cx: float, cy: float,
                           ep: float, scale: float) -> None:
    # Le bord externe du polygone suit la surface réelle (rayon local +
    # ep + cloche). Une dégradation qui passe sur un contrefort y mord à
    # concurrence de sa profondeur.
    for deg in brin.degradations_externes:
        pts_arc = degradation_externe_outline(deg, brin.contreforts,
                                               brin.rayon_a_grade, ep,
                                               cx, cy, scale,
                                               rotation_grades=brin.rotation_grades)
        if pts_arc:
            d.polygon(pts_arc, fill=COLOR_ROT, outline=None)


def _pil_draw_ticks(d: "ImageDraw.ImageDraw",
                    cx: float, cy: float,
                    R_ext: "RadiusSpec", scale: float) -> None:
    # 16 grades — tirets à l'extérieur de l'écorce.
    tick_len_cm = TICK_LEN_PX / scale
    for x1, y1, x2, y2, maj in tick_endpoints(
            cx, cy, scale, R_ext, tick_len_cm):
        d.line([x1, y1, x2, y2],
               fill=COLOR_BARK if maj else COLOR_BARK_LIGHT,
               width=3 if maj else 1)


def _pil_draw_cardinales(d: "ImageDraw.ImageDraw", f: FontFn,
                         cx: float, cy: float,
                         R_ext: "RadiusSpec", scale: float) -> None:
    # Lettres cardinales à `CARDINALES_OFFSET_PX` hors écorce, halo blanc.
    offset_cm = CARDINALES_OFFSET_PX / scale
    # Police résolue UNE fois : le halo tire 24 tracés par lettre, la
    # rechercher à chaque itération était le point chaud du rendu.
    font = f(44, "serif_bold")
    for lx, ly, lbl in cardinal_label_positions(
            cx, cy, scale, R_ext, offset_cm):
        for dx in (-4, -3, 0, 3, 4):
            for dy in (-4, -3, 0, 3, 4):
                if dx or dy:
                    d.text((lx+dx, ly+dy), lbl, font=font,
                           fill="white", anchor="mm")
        d.text((lx, ly), lbl, font=font, fill=COLOR_INK, anchor="mm")


def _pil_draw_sondages(d: "ImageDraw.ImageDraw", f: FontFn, brin: "Brin",
                       port: str, meche: float,
                       cx: float, cy: float,
                       R: float, scale: float,
                       bullet_radius: int = BULLET_RADIUS_PX) -> None:
    inset_cm = SONDAGE_INSET_PX / scale
    items = sondage_render_data(brin, port, meche, cx, cy, R, scale, inset_cm,
                                COULEUR_CLASSE,
                                rotation_grades=brin.rotation_grades)
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


def _pil_draw_titre(d: "ImageDraw.ImageDraw", f: FontFn, arbre: "Arbre",
                    R: float, width: int, height: int) -> None:
    title_y = _titre_y(height)
    d.text((width/2, title_y), arbre.display_name,
           font=f(54, "serif_bold"), fill=COLOR_RENDER_ACCENT, anchor="mm")


def _draw_horizontal_legend_pil(d: "ImageDraw.ImageDraw", arbre: "Arbre | Brin",
                                y_top: float, width: int, height: int,
                                font_fn: FontFn, *,
                                show_sondage_item: bool = True,
                                show_classes: bool = True,
                                extra_items: "tuple[tuple[str, str], ...]" = (),
                                ) -> None:
    """Dessine la légende du dessin de section sur UNE LIGNE horizontale,
    centrée, sous la section.

    Légende adaptative : on n'affiche que les éléments effectivement
    présents sur le dessin (Bois dégradé seulement s'il y a des
    altérations ou dégradations externes ; Écorce seulement si une
    épaisseur > 0 a été renseignée ; etc.). `arbre` peut être un `Brin`
    (mêmes attributs pertinents que sur l'`Arbre`, cf. `Section` dans
    `diagnostic.py`) — utile pour légender le dessin d'un seul brin.

    `show_sondage_item` / `show_classes` permettent à l'appelant de
    réduire la légende : l'export PNG la veut minimaliste (bois sain /
    bois dégradé / écorce), la fiche PDF garde la flèche « Sondage »
    mais retire le bloc « Classe du sondage » (les pastilles colorées
    sont déjà explicitées par le tableau PRBS).

    `extra_items` ajoute des entrées à pastille pleine (label, couleur hex)
    APRÈS les items standards et AVANT le bloc classes — utilisé par
    `comparaison_render` pour l'item « Bois perdu » (couronne orange de la
    section d'évolution), sans dupliquer l'algorithme de centrage/layout.
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
    for label, hex_col in extra_items:
        items.append((f"solid:{hex_col}", label))

    classes = tuple(
        (label, COULEUR_CLASSE[label])
        for label in (CLASSE_VERT, CLASSE_ORANGE, CLASSE_ROUGE)
    ) if (has_sondages and show_classes) else ()
    classes_prefix = "Classe du sondage :"

    # Pré-calcul des largeurs pour centrer le bloc complet.
    def text_w(txt: str, font: Any) -> float:
        bbox = d.textbbox((0, 0), txt, font=font)
        return float(bbox[2] - bbox[0])

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
        elif kind.startswith("solid:"):
            d.rectangle([x_cur, sw_top,
                         x_cur + swatch_w, sw_top + swatch_h],
                        fill=kind[len("solid:"):])
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

