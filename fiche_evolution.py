"""PDF d'évolution (ré-inspection), vectoriel, dans le style de la fiche
d'examen : mêmes en-tête, identité, polices et pied de page que `fiche_pdf`.

Par brin (un seul pour un mono-caule) :

- page 1 : dessins « référence » et « actuel », grand dessin d'évolution,
  verdict sur la dégradation et état t/R à chaque date ;
- page 2 : chiffres, détail par direction, plaies recouvertes.

Une dernière page reprend les photos de la comparaison s'il y en a. Textes
et tableaux sont vectoriels ; les dessins de section restent rendus par
Pillow et collés en image (même approche hybride que la fiche).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Optional, Sequence, Tuple

import angle_units
from comparaison_render import (
    PTS_LEGENDE,
    metric_rows,
    render_brin_section,
    render_evolution_section_brin,
    verdict_couleur,
)
from diagnostic import plaies_recouvertes
from diagnostic_comparaison import (
    ComparaisonDetail,
    comparaison_par_brin,
    verdict_lignes,
)
from evolution import EPS_CM, DirectionDelta
from fiche_pdf import (
    H,
    W,
    _draw_en_tete,
    _draw_footer,
    _fit_text,
    _new_pdf,
    _Page,
    _wrap_lines,
)
from i18n import _
from palette import (
    COLOR_BRAND_ORANGE,
    COLOR_INK,
    COLOR_MUTED,
    COLOR_RENDER_ACCENT,
    COLOR_SIDE_PANEL,
)
from photo_paths import resolve_photo

if TYPE_CHECKING:
    from fpdf import FPDF

    from model import Arbre, Chantier

PHOTOS_COMPARAISON_MAX = 4

_TITRE = "Évolution de l'altération — Pénétromètre"
_MARGE = 60
_BAS = H - 76          # limite au-dessus du pied de page


class _Contexte:
    """Ce qui se répète sur chaque page."""

    def __init__(self, pdf: "FPDF", arbre: "Arbre", chantier: "Chantier",
                 logo_path: Optional[str], cabinet_name: str) -> None:
        self.pdf = pdf
        self.arbre = arbre
        self.chantier = chantier
        self.logo_path = logo_path
        self.cabinet_name = cabinet_name

    def nouvelle_page(self, sous_titre: str) -> "Tuple[_Page, float]":
        self.pdf.add_page()
        pg = _Page(self.pdf)
        y = _draw_en_tete(pg, self.chantier, self.logo_path, _MARGE, _MARGE,
                          titre=_TITRE)
        pg.text(_MARGE, y, self.arbre.display_name, 35, "serif_bold",
                COLOR_INK)
        y += 48
        pg.text(_MARGE, y, _fit_text(pg, sous_titre, 18, "sans",
                                     W - 2 * _MARGE), 18, "sans", COLOR_MUTED)
        y += 36
        _draw_footer(pg, self.arbre, self.chantier, self.cabinet_name, _MARGE)
        return pg, y


def _texte(pg: _Page, y: float, texte: str, taille: float,
           style: str = "sans", couleur: Any = COLOR_INK,
           max_lignes: int = 4) -> float:
    for ligne in _wrap_lines(pg, texte, taille, style, W - 2 * _MARGE,
                             max_lines=max_lignes):
        pg.text(_MARGE, y, ligne, taille, style, couleur)
        y += taille * 1.4
    return y


def _titre_section(pg: _Page, y: float, texte: str) -> float:
    pg.text(_MARGE, y, texte, 22, "serif_bold", COLOR_RENDER_ACCENT)
    return y + 36


def _tableau(pg: _Page, y: float, entetes: Sequence[str],
             lignes: "Sequence[Sequence[str]]",
             parts: Sequence[float], row_h: int = 32) -> float:
    """Tableau pleine largeur ; `parts` = largeurs relatives."""
    largeur = W - 2 * _MARGE
    xs = [float(_MARGE)]
    for part in parts:
        xs.append(xs[-1] + largeur * part / sum(parts))
    pg.rect(_MARGE, y, W - _MARGE, y + 36, COLOR_RENDER_ACCENT)
    for i, entete in enumerate(entetes):
        pg.text(xs[i] + 10, y + 18, entete, 16, "sans_bold", "white",
                anchor="lm")
    y += 36
    for n, ligne in enumerate(lignes):
        if n % 2 == 1:
            pg.rect(_MARGE, y, W - _MARGE, y + row_h, COLOR_SIDE_PANEL)
        for i, valeur in enumerate(ligne):
            pg.text(xs[i] + 10, y + row_h / 2, _fit_text(
                pg, valeur, 15, "sans", xs[i + 1] - xs[i] - 18),
                15, "sans", COLOR_INK, anchor="lm")
        y += row_h
    return y


def _etat(classe: Optional[str], tr: Optional[float]) -> str:
    if classe is None or tr is None:
        return "non publié"
    return f"{classe} — t/R minimal {tr:.1f} %"


def _cavite(d: DirectionDelta) -> str:
    if d.progression > EPS_CM:
        return f"▲ progression {d.progression:+.1f} cm"
    if d.anomalie:
        return "? à vérifier"
    if d.recouverte:
        return "✓ recouverte"
    if d.non_resondee:
        return "non re-sondée"
    return "="


def _page_dessins(ctx: _Contexte, sous_titre: str, ref_img: Any,
                  cur_img: Any, evo_img: Any, detail: ComparaisonDetail,
                  ref_label: str, cur_label: str) -> None:
    pg, y = ctx.nouvelle_page(sous_titre)
    cote, ecart = 540, W - 2 * _MARGE - 2 * 540
    for i, (titre, img) in enumerate(((f"Référence — {ref_label}", ref_img),
                                      (f"Actuel — {cur_label}", cur_img))):
        x = _MARGE + i * (cote + ecart)
        pg.text(x + cote / 2, y, titre, 18, "sans_bold", COLOR_INK,
                anchor="mt")
        if img is None:
            pg.text(x + cote / 2, y + 28 + cote / 2,
                    _("pas de brin de référence"), 18, "sans", COLOR_MUTED,
                    anchor="mm")
        else:
            pg.image(img, x, y + 28, cote, cote)
    y += 28 + cote + 6
    grand = 580
    pg.text(W / 2, y, "Évolution", 18, "sans_bold", COLOR_INK, anchor="mt")
    pg.image(evo_img, (W - grand) / 2, y + 28, grand, grand)
    y += 28 + grand + 8

    titre, precisions = verdict_lignes(detail)
    y = _texte(pg, y, titre, 22, "sans_bold",
               verdict_couleur(detail) or COLOR_INK, max_lignes=2)
    y = _texte(pg, y + 4, precisions, 15, max_lignes=4)
    y += 8
    pg.text(_MARGE, y, f"{ref_label} : "
            f"{_etat(detail.classe_ref, detail.tR_min_ref)}",
            16, "sans_bold", COLOR_INK)
    pg.text(W / 2, y, f"{cur_label} : "
            f"{_etat(detail.classe_cur, detail.tR_min_cur)}",
            16, "sans_bold", COLOR_INK)


def _page_chiffres(ctx: _Contexte, sous_titre: str, cur_arbre: "Arbre",
                   cur_brin: Any, detail: ComparaisonDetail,
                   ref_label: str, cur_label: str) -> None:
    pg, y = ctx.nouvelle_page(sous_titre)
    y = _titre_section(pg, y, "Chiffres")
    y = _tableau(pg, y, ("Indicateur", ref_label, cur_label, "Évolution"),
                 metric_rows(detail), (4.2, 1.6, 1.6, 3.2))
    y = _texte(pg, y + 8, PTS_LEGENDE, 13, couleur=COLOR_MUTED) + 16

    directions = [d for d in detail.directions
                  if d.evaluee or d.non_resondee]
    if directions and not detail.hauteurs_incompatibles:
        y = _titre_section(pg, y, "Par direction")
        y = _tableau(
            pg, y, ("Direction", "Bois sain réf.", "Bois sain actuel",
                    "Croissance", "Cavité"),
            [(f"{d.direction} ({angle_units.fmt(d.grade)})",
              f"{d.prbs_ref:.1f} cm", f"{d.prbs_cur:.1f} cm",
              f"{d.croissance:+.1f} cm", _cavite(d)) for d in directions],
            (2.4, 1.8, 1.8, 1.6, 3.0), row_h=30) + 20

    plaies = plaies_recouvertes(cur_arbre, cur_brin)
    if plaies and y < _BAS - 80:
        y = _titre_section(pg, y, "Plaies recouvertes par un cal")
        for plaie in plaies:
            if y > _BAS - 24:
                break
            y = _texte(pg, y, plaie, 16, max_lignes=1)
    if y < _BAS - 40:
        _texte(pg, y + 8, "La progression est mesurée depuis le centre du "
               "tronc, en supposant une croissance centrée.", 13,
               couleur=COLOR_MUTED)


def _charger_photos(refs: List[str],
                    mission_dir: Optional[Path]) -> List[Any]:
    """Photos utilisables d'une colonne. Même confinement que la fiche ; un
    fichier refusé, absent ou illisible est ignoré."""
    from PIL import Image, ImageOps

    out: List[Any] = []
    for ref in refs:
        if len(out) >= PHOTOS_COMPARAISON_MAX:
            break
        chemin = resolve_photo(ref, mission_dir).path
        if chemin is None:
            continue
        try:
            with Image.open(chemin) as im:
                out.append(ImageOps.exif_transpose(im).convert("RGB"))
        except Exception:
            continue
    return out


def _page_photos(ctx: _Contexte, ref_label: str, cur_label: str,
                 colonnes: "Sequence[List[Any]]") -> None:
    """Photos de la référence à gauche, actuelles à droite. Légendes
    « Photo N », jamais un nom de fichier."""
    pg, y = ctx.nouvelle_page(_("Évolution photographique"))
    ecart = 40
    largeur = (W - 2 * _MARGE - ecart) / 2
    hauteur = (_BAS - y - 36) / PHOTOS_COMPARAISON_MAX
    for i, (titre, photos) in enumerate(zip(
            (f"Référence — {ref_label}", f"Actuel — {cur_label}"), colonnes)):
        x = _MARGE + i * (largeur + ecart)
        pg.text(x, y, titre, 18, "sans_bold", COLOR_INK)
        if not photos:
            pg.text(x, y + 36, _("Aucune photo"), 16, "sans", COLOR_MUTED)
        for n, photo in enumerate(photos):
            haut = y + 36 + n * hauteur
            boite_h = hauteur - 30
            ratio = min(largeur / photo.width, boite_h / photo.height)
            w, h = photo.width * ratio, photo.height * ratio
            pg.image(photo, x + (largeur - w) / 2, haut, w, h)
            pg.text(x + largeur / 2, haut + boite_h + 6, f"Photo {n + 1}",
                    14, "sans", COLOR_MUTED, anchor="mt")
    pg.line(W / 2, y, W / 2, _BAS, COLOR_BRAND_ORANGE, width=2)


def construire_pdf_evolution(
        ref_arbre: "Arbre", cur_arbre: "Arbre", annees: Optional[float], *,
        ref_label: str, cur_label: str, chantier: "Chantier",
        show_sondages: bool = True, show_cernes: bool = True,
        logo_path: Optional[str] = None, cabinet_name: str = "",
        mission_dir: Optional[Path] = None) -> "FPDF":
    """Document PDF complet, à écrire avec `.output(chemin)`.

    `chantier` fournit l'en-tête (adresse, client, date, opérateur) et le
    barème cité en pied de page. Les photos sont celles de
    `cur_arbre.photos_comparaison_ref/_cur`."""
    pdf = _new_pdf()
    ctx = _Contexte(pdf, cur_arbre, chantier, logo_path, cabinet_name)
    paires = comparaison_par_brin(ref_arbre, cur_arbre, annees)
    plusieurs = max(len(ref_arbre.brins), len(cur_arbre.brins)) > 1
    cote = 1100
    for label, cur_b, ref_b, detail in paires:
        sous_titre = f"Relevé du {cur_label} comparé à celui du {ref_label}"
        if plusieurs:
            sous_titre = f"Brin {label}   •   {sous_titre}"
        ref_img = (render_brin_section(ref_arbre, ref_b, cote,
                                       show_sondages=show_sondages,
                                       show_cernes=show_cernes)
                   if ref_b is not None else None)
        cur_img = render_brin_section(cur_arbre, cur_b, cote,
                                      show_sondages=show_sondages,
                                      show_cernes=show_cernes)
        evo_img = render_evolution_section_brin(
            ref_b, cur_b, cote,
            non_comparable=detail.hauteurs_incompatibles is not None)
        _page_dessins(ctx, sous_titre, ref_img, cur_img, evo_img, detail,
                      ref_label, cur_label)
        _page_chiffres(ctx, sous_titre, cur_arbre, cur_b, detail,
                       ref_label, cur_label)
    colonnes = (_charger_photos(cur_arbre.photos_comparaison_ref, mission_dir),
                _charger_photos(cur_arbre.photos_comparaison_cur, mission_dir))
    if any(colonnes):
        _page_photos(ctx, ref_label, cur_label, colonnes)
    return pdf
