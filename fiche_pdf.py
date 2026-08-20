"""
Fiche d'expertise PDF — layout d'une page A4 pour un arbre (VECTORIEL).

Depuis l'adoption de **fpdf2**, la fiche est un **PDF vectoriel** : tout le
texte, le tableau PRBS, le diagnostic et la préconisation sont des objets
PDF natifs (texte sélectionnable/cherchable, net à l'impression et au zoom,
fichier bien plus léger). Approche **hybride** :

- **Texte + tableau + mise en page** : vectoriel fpdf2.
- **Dessin de section** (rose des vents) : **reste rendu par Pillow**
  (`pil_render.render_arbre_to_pil_image`) et **collé comme image**
  (`pdf.image(pil_image, …)`). Le réécrire en vectoriel serait énorme et sans
  gain — hors périmètre.
- **Légende horizontale** : rendue sur une petite image PIL
  (`pil_render._draw_horizontal_legend_pil`) puis collée — fidélité maximale,
  sans réimplémenter la légende.
- **Photos** : chaque photo est une image collée, le reste (en-tête,
  légendes) est vectoriel.

Le document travaille en **unité = 1 px @150 DPI** (`FPDF(unit=72/150,
format=(1240, 1754))` ⟹ page A4 exacte). On garde donc **verbatim** le système
de coordonnées historique (marges, largeurs de colonnes, tailles de police en
« px ») ; seules les tailles de police sont converties en points à la
frontière de l'API fpdf2 (helper `_Page`).

API :

    pdf = _new_pdf()
    render_fiche_arbre(pdf, arbre, chantier, …)   # ajoute la/les page(s)
    pdf.output(chemin)

- **1 arbre**  : un `_new_pdf`, un `render_fiche_arbre`, un `output`.
- **Mission** : un `_new_pdf`, une boucle de `render_fiche_arbre`, un `output`
  (concaténation native — plus de `append_images` Pillow).

`fpdf2` est une dépendance runtime déclarée (`requirements.txt`).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Sequence, Tuple

try:
    from fpdf import FPDF
    HAS_FPDF = True
except ImportError:   # pragma: no cover - fpdf2 est une dépendance déclarée
    # Import paresseux : l'app doit **démarrer** même sans fpdf2 (l'export PDF
    # seul est indisponible). Même philosophie que Pillow (`pil_render.HAS_PIL`)
    # et openpyxl. `_new_pdf` lève alors un message clair.
    FPDF = None       # type: ignore[assignment,misc]
    HAS_FPDF = False

from bareme import classer_prbs, description_seuils_mission
from diagnostic import (
    degradation_externe_par_grade,
    genet_diagnostic,
    repartition_classes,
    repartition_classes_brin,
)
from dialogs_shared import compart_color, compart_glyph
from geometry import DIRECTION_LABELS, GRADES
from i18n import _
from palette import (
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_INK,
    COLOR_MUTED,
    COULEUR_CLASSE,
)
from photo_paths import resolve_photo
from pil_render import (
    _draw_horizontal_legend_pil,
    _pil_load_fonts,
    render_arbre_to_pil_image,
)

if TYPE_CHECKING:
    from model import Arbre, Chantier  # noqa: F401


# --- Constantes de page ---------------------------------------------------

# A4 portrait raisonné en px @150 DPI (comme l'ancien rendu raster) ; le
# document fpdf2 prend 1 unité = 1 px (voir `_new_pdf`).
W, H = 1240, 1754
# Points par unité-doc : 1 px @150 DPI = 72/150 pt. `set_font` attend des
# points → on multiplie la taille « px » par ce facteur.
_PX = 72.0 / 150.0

_FONT_DIR = Path(__file__).parent / "assets" / "fonts"

# Style logique (hérité de la factory PIL) → (famille fpdf2, style fpdf2).
_STYLE = {
    "sans":       ("DejaVu", ""),
    "sans_bold":  ("DejaVu", "B"),
    "serif_bold": ("DejaVuSerif", "B"),
}

# Fractions de l'em pour poser la ligne de base et imiter les ancres PIL.
# PIL « a »/« t » (haut) aligne le haut de l'ascendante sur y ; « m » centre
# la boîte verticale. Ligne de base = y + facteur × taille.
_ASC = 0.90    # ancre haut  (la, mt, …)
_MID = 0.35    # ancre milieu (lm, rm, mm)


# --- Polices --------------------------------------------------------------

# Fallbacks système par variante, au cas où `assets/fonts/` serait retiré.
_FONT_FALLBACK = {
    "DejaVuSans.ttf": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        "/Library/Fonts/Arial.ttf",
    ],
    "DejaVuSans-Bold.ttf": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
    ],
    "DejaVuSerif-Bold.ttf": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        r"C:\Windows\Fonts\georgiab.ttf",
        "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
    ],
}


def _font_file(name: str) -> str:
    """Chemin de la police `name` : embarquée en priorité, sinon système.

    DejaVu porte accents + ✓ (U+2713) + ✗ (U+2717) + – (U+2013) + Ø + ● →
    tout ce qu'utilise la fiche (Helvetica de base est latin-1 → casserait
    les accents et les glyphes de compartimentation)."""
    embedded = _FONT_DIR / name
    if embedded.exists():
        return str(embedded)
    for cand in _FONT_FALLBACK.get(name, []):
        if Path(cand).exists():
            return cand
    return str(embedded)  # laisse fpdf2 lever une erreur explicite


def _register_fonts(pdf: FPDF) -> None:
    pdf.add_font("DejaVu", "", _font_file("DejaVuSans.ttf"))
    pdf.add_font("DejaVu", "B", _font_file("DejaVuSans-Bold.ttf"))
    pdf.add_font("DejaVuSerif", "B", _font_file("DejaVuSerif-Bold.ttf"))


# --- Couleurs -------------------------------------------------------------

def _rgb(color: Any) -> Tuple[int, int, int]:
    """Convertit une couleur (`#RRGGBB`, `"white"`, ou triplet RGB) en RGB."""
    if isinstance(color, (tuple, list)):
        return (int(color[0]), int(color[1]), int(color[2]))
    if color == "white":
        return (255, 255, 255)
    if color == "black":
        return (0, 0, 0)
    h = str(color).lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _text_h(size: float) -> int:
    """Hauteur approx. d'une ligne de texte (px) pour dimensionner un badge.

    Utilisée **à la fois** au dessin et à l'estimation de hauteur → tant que
    les deux appellent ce helper, le budget vertical reste cohérent."""
    return int(size * 0.75)


# --- Couche de dessin vectoriel ------------------------------------------

class _Page:
    """Fine surface de dessin sur un `FPDF` déjà positionné sur une page.

    Reproduit les primitives PIL utilisées par l'ancienne fiche
    (`text`/`rect`/`line`/`polygon`/`image`) avec les mêmes coordonnées en
    « px @150 DPI » et une gestion d'ancre calquée sur PIL."""

    def __init__(self, pdf: FPDF) -> None:
        self.pdf = pdf

    def _set(self, size: float, style: str) -> None:
        fam, st = _STYLE[style]
        self.pdf.set_font(fam, st, size * _PX)

    def sw(self, s: str, size: float, style: str = "sans") -> float:
        """Largeur de `s` en px (unité-doc)."""
        self._set(size, style)
        return self.pdf.get_string_width(s)

    def text(self, x: float, y: float, s: str, size: float,
             style: str = "sans", color: Any = COLOR_INK,
             anchor: str = "la") -> None:
        if not s:
            return
        self._set(size, style)
        self.pdf.set_text_color(*_rgb(color))
        w = self.pdf.get_string_width(s)
        ah = anchor[0]
        av = anchor[1] if len(anchor) > 1 else "a"
        if ah == "m":
            x -= w / 2.0
        elif ah == "r":
            x -= w
        if av in ("a", "t"):
            by = y + _ASC * size
        elif av == "m":
            by = y + _MID * size
        else:  # "s" : ligne de base
            by = y
        self.pdf.text(x, by, s)

    def rect(self, x0: float, y0: float, x1: float, y1: float,
             color: Any) -> None:
        self.pdf.set_fill_color(*_rgb(color))
        self.pdf.rect(x0, y0, x1 - x0, y1 - y0, style="F")

    def line(self, x0: float, y0: float, x1: float, y1: float,
             color: Any, width: float = 1.0) -> None:
        self.pdf.set_draw_color(*_rgb(color))
        self.pdf.set_line_width(max(0.4, width))
        self.pdf.line(x0, y0, x1, y1)

    def polygon(self, points: Sequence[Tuple[float, float]],
                color: Any) -> None:
        self.pdf.set_fill_color(*_rgb(color))
        self.pdf.polygon([(float(px), float(py)) for px, py in points],
                         style="F")

    def image(self, pil_image: Any, x: float, y: float, w: float,
              h: float = 0.0) -> None:
        # h=0 ⟹ fpdf2 déduit la hauteur du ratio de l'image.
        self.pdf.image(pil_image, x=x, y=y, w=w, h=h)


def _new_pdf() -> FPDF:
    """Crée un document A4 portrait en unité « px @150 DPI » et enregistre
    les polices DejaVu. À nourrir ensuite par `render_fiche_arbre`."""
    if not HAS_FPDF:
        raise ImportError(
            "fpdf2 est requis pour l'export PDF (pip install fpdf2)")
    pdf = FPDF(orientation="P", unit=_PX, format=(W, H))
    pdf.set_auto_page_break(False)
    pdf.set_margins(0, 0)
    pdf.set_margin(0)
    _register_fonts(pdf)
    pdf.set_title("Fiche d'expertise Pénétromètre")
    pdf.set_creator("Pénétromètre")
    return pdf


# --- Helpers texte (mesure via _Page) ------------------------------------

def _fit_text(pg: _Page, text: str, size: float, style: str,
              max_width: float) -> str:
    """Tronque `text` avec une ellipsis « … » si sa largeur dépasse
    `max_width`. Évite que les valeurs débordent de leur colonne."""
    if not text:
        return ""
    if pg.sw(text, size, style) <= max_width:
        return text
    ellipsis = "…"
    while text:
        text = text[:-1]
        if pg.sw(text + ellipsis, size, style) <= max_width:
            return text + ellipsis
    return ellipsis


def _wrap_lines(pg: _Page, text: str, size: float, style: str,
                max_width: float, max_lines: int = 4) -> List[str]:
    """Découpe `text` en lignes tenant dans `max_width` (retour à la ligne
    par mots), bornées à `max_lines` (dernière ligne tronquée « … » si le
    texte déborde). Pour la préconisation/suivi libres de la fiche PDF."""
    lines: List[str] = []
    cur = ""
    for word in (text or "").split():
        trial = (cur + " " + word).strip()
        if not cur or pg.sw(trial, size, style) <= max_width:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = _fit_text(pg, lines[-1] + " …", size, style, max_width)
    return lines


# Couleur du badge d'urgence (fond plein, texte blanc) selon le délai —
# gradient vert (peu urgent) → rouge (immédiat).
_URGENCE_COLOR = {
    "Immédiate": "#C0392B",
    "< 6 mois":  "#E67E22",
    "< 1 an":    "#B7950B",
    "< 2 ans":   "#2D7A3E",
}


def _estimate_preco_height(pg: _Page, arbre: "Arbre", txt_w: int,
                           has_intervention: bool, has_suivi: bool) -> int:
    """Hauteur (px) qu'occupera la colonne préconisation.

    Miroir **exact** des incréments de `y_preco` dans `render_fiche_arbre`,
    pour réserver la place dans le budget vertical (sinon un texte long
    déborde sur le pied de page, le dessin ne rétrécissant que pour le
    diagnostic). Toute modif des incréments de dessin doit être répercutée
    ici."""
    h = 36  # titre "Préconisation" (y_preco = y_section + 36)
    if has_intervention:
        h += 32 + 12   # bande "Intervention" (_preco_header)
        if arbre.urgence:
            h += _text_h(16) + 2 * 7 + 12   # badge
        if arbre.echeance:
            h += 26
        if arbre.preconisation:
            n = len(_wrap_lines(pg, arbre.preconisation, 16, "sans",
                                txt_w, max_lines=8))
            h += 2 + n * 22
        h += 14
    if has_suivi:
        h += 32 + 12   # bande "Suivi"
        if arbre.suivi_validite:
            h += 26
        if arbre.suivi_echeance:
            h += 26
        if arbre.suivi_texte:
            n = len(_wrap_lines(pg, arbre.suivi_texte, 16, "sans",
                                txt_w, max_lines=8))
            h += 2 + n * 22
        h += 6
    return h


def _draw_footer(pg: _Page, chantier: "Chantier", cabinet_name: str,
                 margin: int) -> None:
    """Filet + ligne barème + ligne Pénétromètre/date, en bas de la page
    courante. Factorisé pour être rejoué identique sur chaque page d'une
    fiche qui déborde sur plusieurs pages (table PRBS d'une grosse cépée,
    cf. `render_fiche_arbre`)."""
    pg.line(margin, H - 60, W - margin, H - 60, COLOR_MUTED, width=1)
    pg.text(W / 2, H - 44,
            _("Barème appliqué") + " — " + description_seuils_mission(chantier),
            12, "sans", COLOR_MUTED, anchor="mm")
    cab_suffix = f"   •   {cabinet_name}" if cabinet_name else ""
    pg.text(W / 2, H - 22,
            f"Pénétromètre{cab_suffix}   •   " + _("Édité le")
            + f" {datetime.now().strftime('%d/%m/%Y à %H:%M')}",
            14, "sans", COLOR_MUTED, anchor="mm")


def render_fiche_arbre(pdf: FPDF,
                       arbre: "Arbre",
                       chantier: "Chantier",
                       *,
                       show_sondages: bool = True,
                       logo_path: "str | None" = None,
                       cabinet_name: str = "",
                       mission_file: "Path | None" = None) -> None:
    """Ajoute au document `pdf` la/les page(s) de l'arbre.

    Une page « fiche » (en-tête mission, dessin, tableau PRBS, diagnostic,
    préconisation) ; plus une page « photos » si des photos sont associées.

    Les tailles de police, largeurs de colonnes et marges sont calibrées
    pour rester lisibles à l'impression A4.

    `show_sondages` reflète la case « Afficher l'emplacement des sondages
    sur le dessin » : à `False`, les pastilles/flèches sont omises **du
    dessin** (le tableau PRBS reste, lui, toujours présent — c'est la donnée).
    """
    from PIL import Image, ImageDraw

    f = _pil_load_fonts()     # pour le dessin de section + la légende (PIL)

    pdf.add_page()
    pg = _Page(pdf)

    margin = 60
    y = margin

    # --- En-tête mission avec logo cabinet ---
    header_h = 116
    pg.rect(margin, y, W - margin, y + header_h, COLOR_ACCENT)
    # Logo à droite (fond blanc pour le détacher du vert)
    logo_w = 0
    try:
        _logo_path = Path(logo_path) if logo_path else None
        if _logo_path and _logo_path.exists():
            logo = Image.open(_logo_path).convert("RGBA")
            target_h = header_h - 24
            ratio = target_h / logo.height
            lw = int(logo.width * ratio)
            lx = W - margin - lw - 12
            ly = y + 12
            logo_bg = Image.new("RGB", logo.size, "white")
            logo_bg.paste(logo, (0, 0), logo)
            pg.rect(lx, ly, lx + lw, ly + target_h, "white")
            pg.image(logo_bg, lx, ly, lw, target_h)
            logo_w = lw + 24
    except Exception:
        pass

    header_text_w = W - margin * 2 - logo_w - 20
    pg.text(margin + 20, y + 22, "Fiche d'expertise — Pénétromètre",
            30, "serif_bold", "white")
    _lbl_client = _("Client")
    mission_txt = _fit_text(
        pg,
        (_("Mission") + f" : {chantier.nom}"
         + (f"   •   {chantier.adresse}" if chantier.adresse else "")
         + (f"   •   {_lbl_client} : {chantier.client}" if chantier.client else "")),
        19, "sans", header_text_w)
    pg.text(margin + 20, y + 64, mission_txt, 19, "sans", "white")
    pg.text(margin + 20, y + 92,
            f"{chantier.date_releve}   •   " + _("Opérateur")
            + f" : {chantier.operateur}",
            17, "sans", "white")
    y += header_h + 18

    # --- Identité de l'arbre ---
    pg.text(margin, y, arbre.display_name, 35, "serif_bold", COLOR_INK)
    y += 50
    R = arbre.rayon_tronc_cm
    ligne = (f"Rayon : {R:g} cm   •   "
             + _("Ø sous écorce") + f" : {arbre.diametre_sous_ecorce_cm:g} cm   •   "
             + f"Hauteur : {arbre.hauteur_arbre_m:g} m   •   "
             + f"Port : {arbre.port_arbre}")
    ligne = _fit_text(pg, ligne, 18, "sans", W - 2 * margin)
    pg.text(margin, y, ligne, 18, "sans", COLOR_MUTED)
    y += 32
    if arbre.commentaire:
        comm = _fit_text(pg, f"Commentaire : {arbre.commentaire}",
                         17, "sans", W - 2 * margin)
        pg.text(margin, y, comm, 17, "sans", COLOR_INK)
        y += 30

    # --- Dessin (adaptatif : le reste de la page réserve sa place) ---
    multi_brins = len(arbre.brins) > 1
    # Cépée = même prédicat de routage que les renderers.
    is_cepee = not (len(arbre.brins) == 1
                    and arbre.brins[0].pos_x_cm == 0.0
                    and arbre.brins[0].pos_y_cm == 0.0)
    n_sond = sum(len(b.sondages) for b in arbre.brins
                 if b.rayon_tronc_cm > 0)
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
    if multi_brins:
        est_diag_h = 76 + 32 + 28 * len(arbre.brins) + 24
    else:
        est_diag_h = 360  # majorant : t/R + bar + détail + classe globale
    est_legend_h = 56
    # Pied de page : filet (H-60) + ligne barème (H-44) + ligne
    # Pénétromètre/date (H-22). Doit rester cohérent avec le bloc « Pied de
    # page » plus bas, sinon le contenu déborde sur le pied.
    footer_reserve = 76
    has_intervention = bool(arbre.urgence or arbre.echeance or arbre.preconisation)
    has_suivi = bool(arbre.suivi_validite or arbre.suivi_echeance
                     or arbre.suivi_texte)
    if has_intervention or has_suivi:
        _preco_left = (margin + 680) + 20
        _preco_txt_w = (W - margin) - 12 - (_preco_left + 12)
        est_preco_h = _estimate_preco_height(
            pg, arbre, _preco_txt_w, has_intervention, has_suivi)
    else:
        est_preco_h = 0
    est_section_h = max(est_diag_h, est_preco_h)
    used_so_far = y - margin
    remaining = (H - margin - footer_reserve) - used_so_far \
        - est_table_h - est_section_h - est_legend_h - 22
    drawing_h = max(340, min(900, remaining))
    if is_cepee:
        drawing_w = W - 2 * margin
        drawable = [b for b in arbre.brins if b.rayon_tronc_cm > 0]
        if drawable:
            w_cm = (max(b.pos_x_cm + b.extent_cm() for b in drawable)
                    - min(b.pos_x_cm - b.extent_cm() for b in drawable))
            h_cm = (max(b.pos_y_cm + b.extent_cm() for b in drawable)
                    - min(b.pos_y_cm - b.extent_cm() for b in drawable))
            if w_cm > 0:
                fitted = int(drawing_w * h_cm / w_cm) + 200
                drawing_h = max(420, min(drawing_h, fitted))
    else:
        drawing_w = drawing_h
    drawing = render_arbre_to_pil_image(arbre, drawing_w, drawing_h,
                                        show_sondages=show_sondages,
                                        show_title=False,
                                        show_legend=False)
    x_draw = (W - drawing_w) // 2
    pg.image(drawing, x_draw, y, drawing_w, drawing_h)
    y += drawing_h + 6

    # Légende horizontale : rendue sur une bande PIL puis collée (fidélité).
    if R > 0:
        strip_h = est_legend_h + 20
        strip = Image.new("RGB", (W, strip_h), "white")
        ds = ImageDraw.Draw(strip)
        _draw_horizontal_legend_pil(ds, arbre, y_top=0,
                                    width=W, height=900, font_fn=f,
                                    show_sondage_item=show_sondages,
                                    show_classes=False)
        pg.image(strip, 0, y, W, strip_h)
        y += est_legend_h

    # --- Tableau PRBS ajustée par sondage (par brin pour une cépée) ---
    # Ligne basse que le tableau ne franchit JAMAIS (mêmes 8 px de marge
    # que `y_limit` de la préconisation, au-dessus du filet de pied de page
    # tracé à H-60) : une cépée à beaucoup de sondages (plusieurs brins ×
    # 16 directions) ne tient pas toujours sur une seule page — le tableau
    # se poursuit alors sur une page suivante plutôt que de chevaucher le
    # pied de page (cf. `_draw_footer`, rejoué identique sur chaque page).
    table_y_limit = (H - 60) - 8
    if n_sond > 0:
        titre_tbl = ("Paroi Résiduelle de Bois Sain par sondage et par brin"
                     if multi_brins
                     else "Paroi Résiduelle de Bois Sain par sondage")
        pg.text(margin, y, titre_tbl, 22, "serif_bold", COLOR_ACCENT)
        y += 36
        # Total = 70 + 220 + 270 + 130 + 160 + 270 = 1120 = W - 2*margin.
        col_widths = [70, 220, 270, 130, 160, 270]
        cols_x = [margin]
        for w in col_widths:
            cols_x.append(cols_x[-1] + w)
        headers = [_("N°"), _("Direction"), _("PRBS (cm)"), _("t/R (%)"),
                   _("Classe"), _("Compart.")]
        right_align = {0, 3}            # N°, t/R (%)
        right_align_data = {0, 3}
        header_h_row = 44

        def _draw_table_head(y0: float) -> float:
            pg.rect(cols_x[0], y0, cols_x[-1], y0 + header_h_row, COLOR_ACCENT)
            for i, h in enumerate(headers):
                if i in right_align:
                    pg.text(cols_x[i + 1] - 12, y0 + header_h_row / 2, h,
                            17, "sans_bold", "white", anchor="rm")
                else:
                    pg.text(cols_x[i] + 12, y0 + header_h_row / 2, h,
                            17, "sans_bold", "white", anchor="lm")
            return y0 + header_h_row

        y = int(_draw_table_head(y))
        k = 0
        for b in arbre.brins:
            R_b = b.rayon_tronc_cm
            if R_b <= 0:
                continue
            deg_ext_par_grade = degradation_externe_par_grade(b)
            for s in b.sondages:
                if y + row_h > table_y_limit:
                    _draw_footer(pg, chantier, cabinet_name, margin)
                    pdf.add_page()
                    pg = _Page(pdf)
                    y = margin
                    pg.text(margin, y, titre_tbl + " " + _("(suite)"),
                            22, "serif_bold", COLOR_ACCENT)
                    y += 36
                    y = int(_draw_table_head(y))
                    k = 0
                dir_lbl = DIRECTION_LABELS.get(s.grade, "")
                direction = f"{dir_lbl} ({s.grade} gr)" if dir_lbl \
                    else f"{s.grade} gr"
                idx_g = GRADES.index(s.grade) if s.grade in GRADES else 0
                deg_ext = deg_ext_par_grade[idx_g]
                prbs_adj = max(0.0, s.prbs_cm - deg_ext)
                ratio = prbs_adj / R_b
                classe = classer_prbs(ratio, arbre.port_arbre)
                col_c = COULEUR_CLASSE[classe]
                if k % 2 == 0:
                    pg.rect(cols_x[0], y, cols_x[-1], y + row_h, COLOR_BG)
                k += 1
                prbs_txt = f"{prbs_adj:g}"
                _pfx = "~" if getattr(s, "incertain", False) else ""
                num_txt = (_pfx + (f"{b.label}{s.numero}" if multi_brins and b.label
                           else str(s.numero)))
                # Colonne Compart. = glyphe coloré ✓/✗/– (source unique).
                vals = [num_txt, direction, prbs_txt, f"{100 * ratio:.1f}",
                        classe, compart_glyph(s.compartimentation)]
                for i, v in enumerate(vals):
                    if i == 4:
                        col, wt = col_c, "sans_bold"
                    elif i == 5:
                        col = compart_color(s.compartimentation)
                        wt = "sans_bold"
                    else:
                        col, wt = COLOR_INK, "sans"
                    col_w = col_widths[i] - 24  # padding 12 de chaque côté
                    txt = _fit_text(pg, v, row_font_size, wt, col_w)
                    if i in right_align_data:
                        pg.text(cols_x[i + 1] - 12, y + row_h / 2, txt,
                                row_font_size, wt, col, anchor="rm")
                    elif i == 5:
                        pg.text((cols_x[i] + cols_x[i + 1]) / 2, y + row_h / 2,
                                txt, row_font_size, wt, col, anchor="mm")
                    else:
                        pg.text(cols_x[i] + 12, y + row_h / 2, txt,
                                row_font_size, wt, col, anchor="lm")
                y += row_h
        y += 18

    # Le tableau (paginé ci-dessus si besoin) peut finir juste au-dessus du
    # pied de page, sans plus assez de place pour le Diagnostic/la
    # Préconisation : les reporter en haut d'une page neuve plutôt que les
    # laisser chevaucher le pied de page (même logique que la pagination
    # du tableau).
    if y + est_section_h > table_y_limit:
        _draw_footer(pg, chantier, cabinet_name, margin)
        pdf.add_page()
        pg = _Page(pdf)
        y = margin

    # --- Diagnostic (col. gauche) + Préconisation (col. droite) ---
    has_preco = has_intervention or has_suivi
    col_diag_left = margin
    col_diag_right = (margin + 680) if has_preco else (W - margin)
    col_preco_left = col_diag_right + 20
    col_preco_right = W - margin

    y_section = y
    pg.text(col_diag_left, y_section, _("Diagnostic"),
            22, "serif_bold", COLOR_ACCENT)
    y_diag = y_section + 36
    if multi_brins:
        y_diag = int(_draw_cepee_diagnostic(
            pg, arbre, col_diag_left, col_diag_right, y_diag))
    else:
        y_diag = int(_draw_mono_diagnostic(
            pg, arbre, col_diag_left, col_diag_right, R, y_diag))

    y_preco = y_section
    if has_preco:
        pad = 12
        txt_x = col_preco_left + pad
        txt_w = col_preco_right - pad - txt_x

        pg.text(col_preco_left, y_preco, _("Préconisation"),
                22, "serif_bold", COLOR_ACCENT)
        y_preco = y_section + 36

        # Ligne basse que le rendu ne franchit JAMAIS (8 px au-dessus du
        # filet de pied de page, tracé à H-60 depuis l'ajout de la ligne
        # « Barème appliqué »).
        y_limit = (H - 60) - 8

        def _preco_header(title: str, y0: int) -> int:
            bar_h = 32
            pg.rect(col_preco_left, y0, col_preco_right, y0 + bar_h,
                    COLOR_ACCENT)
            pg.text(col_preco_left + pad, y0 + bar_h / 2, title,
                    16, "sans_bold", "white", anchor="lm")
            return y0 + bar_h + 12

        def _draw_preco_text(text: str, y0: int) -> int:
            avail = int((y_limit - y0) // 22)
            if avail < 1:
                return y0
            for line in _wrap_lines(pg, text, 16, "sans", txt_w,
                                    max_lines=min(8, avail)):
                pg.text(txt_x, y0, line, 16, "sans", COLOR_INK)
                y0 += 22
            return y0

        if has_intervention and y_preco + 32 + 24 <= y_limit:
            y_preco = _preco_header(_("Intervention"), y_preco)

            if arbre.urgence and y_preco + 46 <= y_limit:
                lbl = _("Urgence :") + " "
                lbl_w = pg.sw(lbl, 16, "sans")
                urg_color = _URGENCE_COLOR.get(arbre.urgence, COLOR_INK)
                uw = pg.sw(arbre.urgence, 16, "sans_bold")
                uh = _text_h(16)
                bx, by = 12, 7
                pg.text(txt_x, y_preco + by, lbl, 16, "sans", COLOR_MUTED)
                badge_x = txt_x + lbl_w
                pg.rect(badge_x, y_preco,
                        badge_x + uw + 2 * bx, y_preco + uh + 2 * by,
                        urg_color)
                pg.text(badge_x + bx, y_preco + by, arbre.urgence,
                        16, "sans_bold", "white")
                y_preco += int(uh) + 2 * by + 12

            if arbre.echeance and y_preco + 26 <= y_limit:
                lbl = _("Échéance :") + " "
                lbl_w = pg.sw(lbl, 16, "sans")
                pg.text(txt_x, y_preco, lbl, 16, "sans", COLOR_MUTED)
                pg.text(txt_x + lbl_w, y_preco, arbre.echeance,
                        16, "sans_bold", COLOR_INK)
                y_preco += 26

            if arbre.preconisation:
                y_preco = _draw_preco_text(arbre.preconisation, y_preco + 2)
            y_preco += 14

        if has_suivi and y_preco + 32 + 24 <= y_limit:
            y_preco = _preco_header(_("Suivi"), y_preco)

            if arbre.suivi_validite and y_preco + 26 <= y_limit:
                lbl = _("Validité :") + " "
                lbl_w = pg.sw(lbl, 16, "sans")
                pg.text(txt_x, y_preco, lbl, 16, "sans", COLOR_MUTED)
                pg.text(txt_x + lbl_w, y_preco, arbre.suivi_validite,
                        16, "sans_bold", COLOR_INK)
                y_preco += 26

            if arbre.suivi_echeance and y_preco + 26 <= y_limit:
                lbl = _("Prochaine visite :") + " "
                lbl_w = pg.sw(lbl, 16, "sans")
                pg.text(txt_x, y_preco, lbl, 16, "sans", COLOR_MUTED)
                pg.text(txt_x + lbl_w, y_preco, arbre.suivi_echeance,
                        16, "sans_bold", COLOR_INK)
                y_preco += 26

            if arbre.suivi_texte:
                y_preco = _draw_preco_text(arbre.suivi_texte, y_preco + 2)
            y_preco += 6

    y = max(y_diag, y_preco) + 10

    # --- Pied de page ---
    # Barème effectivement appliqué : sans cette ligne, la classe
    # Vert/Orange/Rouge du document n'est pas reproductible (les seuils
    # sont un réglage de poste). Cf. `bareme.description_seuils`.
    _draw_footer(pg, chantier, cabinet_name, margin)

    # --- Page photos (si photos associées) ---
    # Confinement identique à la galerie (cf. `photo_paths`) : une
    # référence hostile dans un `.json` reçu d'un tiers ne doit pas
    # pouvoir faire embarquer un fichier arbitraire du poste dans le PDF
    # remis au client.
    mission_dir = mission_file.parent if mission_file is not None else None
    photos_valides = [r for p in (arbre.photos or [])
                      if (r := resolve_photo(p, mission_dir).path) is not None]
    if photos_valides:
        _render_photos_page(pdf, photos_valides, arbre, chantier, margin)


def _draw_mono_diagnostic(pg: _Page, arbre: "Arbre",
                          x_left: int, x_right: int, R: float,
                          y: float) -> float:
    """Bloc diagnostic d'un genet mono-caule.

    `x_left`/`x_right` délimitent la colonne allouée (rendu côte à côte avec
    la préconisation). Renvoie l'ordonnée après le bloc.
    """
    snap = repartition_classes(arbre)
    diag = snap.diagnostic_global
    if R > 0 and not all(r >= 0.999 for r in snap.ratios):
        if diag is not None:
            tR_moyen_diag, _cls_tmp = diag
            pg.text(x_left, y,
                    _("t/R moyen sur le pourtour") + f" : {100 * tR_moyen_diag:.1f} %",
                    18, "sans_bold", COLOR_INK)
            y += 28
        pg.text(x_left, y,
                _("t/R minimal") + f" : {100 * snap.tR_min:.1f} %  "
                f"(grade {snap.tR_min_grade} gr — {snap.tR_min_dir})",
                18, "sans", COLOR_INK)
        y += 28
        if snap.extrapolation_text:
            pg.text(x_left, y, snap.extrapolation_text, 16, "sans", COLOR_MUTED)
            y += 28
        else:
            y += 4
        if diag is None:
            pg.text(x_left, y,
                    "⚠ Diagnostic global indisponible : il faut au moins",
                    18, "sans_bold", (176, 0, 32))
            y += 26
            pg.text(x_left, y,
                    "2 directions sondées pour extrapoler le pourtour.",
                    18, "sans_bold", (176, 0, 32))
            y += 30
        else:
            pg.text(x_left, y,
                    "Répartition sur le pourtour (16 directions) :",
                    18, "sans_bold", COLOR_INK)
            y += 30
            bar_w = x_right - x_left
            bar_h = 36
            x_cur: float = x_left
            outside_labels = []
            for cls in ("Vert", "Orange", "Rouge"):
                seg_pct = snap.par_classe(cls).pct
                seg_w = bar_w * seg_pct / 100.0
                if seg_w > 0:
                    col = COULEUR_CLASSE[cls]
                    pg.rect(x_cur, y, x_cur + seg_w, y + bar_h, col)
                    if seg_w > 95:
                        pg.text(x_cur + seg_w / 2, y + bar_h / 2,
                                f"{cls} {seg_pct:.0f} %",
                                15, "sans_bold", "white", anchor="mm")
                    else:
                        outside_labels.append((cls, seg_pct, col,
                                                x_cur + seg_w / 2))
                    x_cur += seg_w
            y += bar_h + 4
            if outside_labels:
                label_size = 15
                texts = [f"{cls} {pct:.0f} %" for cls, pct, _c, _x
                         in outside_labels]
                cols = [col for _cls, _pct, col, _x in outside_labels]
                anchors = [x_center for _cls, _pct, _col, x_center
                           in outside_labels]
                widths = [pg.sw(t, label_size, "sans_bold") for t in texts]
                label_xs = list(anchors)
                # Écarte les étiquettes qui se chevaucheraient (segments
                # étroits voisins) en les repoussant vers la droite, puis
                # ramène l'ensemble dans la largeur de la barre.
                gap = 8.0
                for i in range(1, len(label_xs)):
                    min_x = (label_xs[i - 1] + widths[i - 1] / 2
                              + widths[i] / 2 + gap)
                    if label_xs[i] < min_x:
                        label_xs[i] = min_x
                overflow = label_xs[-1] + widths[-1] / 2 - x_right
                if overflow > 0:
                    label_xs = [lx - overflow for lx in label_xs]
                underflow = x_left - (label_xs[0] - widths[0] / 2)
                if underflow > 0:
                    label_xs = [lx + underflow for lx in label_xs]
                for ax, lx, txt, col in zip(anchors, label_xs, texts, cols):
                    pg.polygon([(ax, y), (ax - 6, y + 8), (ax + 6, y + 8)],
                               col)
                    if abs(lx - ax) > 2:
                        pg.line(ax, y + 8, lx, y + 18, col)
                    pg.text(lx, y + 22, txt, label_size,
                            "sans_bold", col, anchor="mt")
                y += 46
            else:
                y += 8
            chunks = []
            for cls in ("Vert", "Orange", "Rouge"):
                r = snap.par_classe(cls)
                if r.n > 0:
                    col = COULEUR_CLASSE[cls]
                    chunks.append((f"{cls} {r.n}/16 ({r.grades} gr)", col))
            if chunks:
                sep = "   •   "
                sep_w = pg.sw(sep, 17, "sans")
                x_chunk: float = x_left
                for i, (txt, col) in enumerate(chunks):
                    if i > 0:
                        pg.text(x_chunk, y, sep, 17, "sans", COLOR_MUTED)
                        x_chunk += sep_w
                    pg.text(x_chunk, y, txt, 17, "sans", col)
                    x_chunk += pg.sw(txt, 17, "sans")
                y += 28
            y += 10
            _tR_tmp, classe_g = diag
            col_g = COULEUR_CLASSE[classe_g]
            box_w, box_h = 460, 60
            pg.rect(x_left, y, x_left + box_w, y + box_h, col_g)
            pg.text(x_left + box_w / 2, y + box_h / 2,
                    _("Classe globale") + f" : {classe_g}",
                    24, "sans_bold", "white", anchor="mm")
            y += box_h + 8
    else:
        pg.text(x_left, y, _("Aucune altération saisie."),
                18, "sans", COLOR_INK)
        y += 28
    return y


def _draw_cepee_diagnostic(pg: _Page, arbre: "Arbre",
                           x_left: int, x_right: int, y: float) -> float:
    """Bloc diagnostic d'une cépée.

    `x_left`/`x_right` délimitent la colonne allouée. Renvoie l'ordonnée
    après le bloc.
    """
    gd = genet_diagnostic(arbre)
    port = arbre.port_arbre
    if gd.classe_globale is not None:
        col_g = COULEUR_CLASSE[gd.classe_globale]
        box_w, box_h = 560, 60
        pg.rect(x_left, y, x_left + box_w, y + box_h, col_g)
        pg.text(x_left + box_w / 2, y + box_h / 2,
                _("Classe globale (pire brin)") + f" : {gd.classe_globale}",
                22, "sans_bold", "white", anchor="mm")
        y += box_h + 16
    else:
        pg.text(x_left, y,
                "⚠ Classe globale indisponible : aucun brin avec au moins "
                "3 directions sondées.",
                18, "sans_bold", (176, 0, 32))
        y += 36
    pg.text(x_left, y, "Détail par brin :", 18, "sans_bold", COLOR_INK)
    y += 32
    for b in arbre.brins:
        lbl = b.label or "?"
        prefix = f"Brin {lbl} :  "
        pg.text(x_left, y, prefix, 17, "sans_bold", COLOR_INK)
        px = x_left + pg.sw(prefix, 17, "sans_bold")
        if b.rayon_tronc_cm <= 0:
            pg.text(px, y, "rayon non renseigné.", 17, "sans", COLOR_MUTED)
            y += 28
            continue
        snap = repartition_classes_brin(b, port)
        diag = snap.diagnostic_global
        if diag is not None:
            tR_moyen_b, classe_b = diag
            txt = (f"{classe_b}   •   t/R moyen {100 * tR_moyen_b:.1f} %"
                   f"   •   t/R min {100 * snap.tR_min:.1f} %")
            pg.text(px, y, txt, 17, "sans", COULEUR_CLASSE[classe_b])
        else:
            pg.text(px, y,
                    _("non fiable ({n}/16 directions sondées).").format(
                        n=snap.n_sondees),
                    17, "sans", COLOR_MUTED)
        y += 28
    return y


def _render_photos_page(pdf: FPDF, photos: "List[Path]", arbre: "Arbre",
                        chantier: "Chantier", margin: int) -> None:
    """Ajoute une page de grille de photos (jusqu'à 6 photos en 2 × 3).

    En-tête vert « Photos — Arbre N°X », grille 2 colonnes avec légende (nom
    de fichier), pied de page identique à la fiche principale. Les photos
    sont des images collées ; l'en-tête et les légendes sont vectoriels.
    """
    from PIL import Image

    pdf.add_page()
    pg = _Page(pdf)

    y = margin

    header_h = 80
    pg.rect(margin, y, W - margin, y + header_h, COLOR_ACCENT)
    pg.text(margin + 20, y + header_h // 2,
            _("Photos") + f"   —   {arbre.display_name}",
            28, "serif_bold", "white", anchor="lm")
    pg.text(W - margin - 20, y + header_h // 2,
            _("Mission") + f" : {chantier.nom}",
            17, "sans", "white", anchor="rm")
    y += header_h + 24

    n_cols = 2
    gap = 20
    col_w = (W - 2 * margin - (n_cols - 1) * gap) // n_cols
    caption_h = 28
    footer_reserve = 46 + 32

    n_photos = min(len(photos), 6)
    n_rows = max(1, (n_photos + n_cols - 1) // n_cols)
    available_h = H - y - footer_reserve
    row_total_h = (available_h - (n_rows - 1) * gap) // n_rows
    photo_h = row_total_h - caption_h - 8

    for idx in range(n_photos):
        photo_path = photos[idx]
        col = idx % n_cols
        row = idx // n_cols
        x0 = margin + col * (col_w + gap)
        y0 = y + row * (row_total_h + gap)

        pg.rect(x0, y0, x0 + col_w, y0 + photo_h, "#F0F0F0")

        try:
            img = Image.open(photo_path).convert("RGB")
            img_ratio = img.width / img.height
            cell_ratio = col_w / photo_h
            if img_ratio > cell_ratio:
                new_w = col_w
                new_h = int(col_w / img_ratio)
            else:
                new_h = photo_h
                new_w = int(photo_h * img_ratio)
            px = x0 + (col_w - new_w) // 2
            py = y0 + (photo_h - new_h) // 2
            pg.image(img, px, py, new_w, new_h)
        except Exception:
            pg.text(x0 + col_w // 2, y0 + photo_h // 2, "⚠ Photo illisible",
                    16, "sans", COLOR_MUTED, anchor="mm")

        caption = _fit_text(pg, photo_path.name, 15, "sans", col_w)
        pg.text(x0 + col_w // 2, y0 + photo_h + 6, caption,
                15, "sans", COLOR_MUTED, anchor="mt")

    pg.line(margin, H - 46, W - margin, H - 46, COLOR_MUTED, width=1)
    pg.text(W / 2, H - 24,
            "Pénétromètre   •   " + _("Édité le")
            + f" {datetime.now().strftime('%d/%m/%Y à %H:%M')}",
            14, "sans", COLOR_MUTED, anchor="mm")
