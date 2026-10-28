"""
Rendu PIL de la comparaison inter-missions (ré-inspection) :

- `render_evolution_heatmap` : « carte de différence » — une rose des 16
  directions colorée par l'aggravation de l'altération (ΔPRBS) entre la
  campagne de référence et la campagne courante (rouge = bois sain perdu).
- `render_comparison_page` : page A4 paysage livrable (en-tête, les deux
  sections + la heatmap, tableau chiffré, verdict) — exportable en PNG et
  en PDF (cf. `app_exports`).

Module sans Tk (PIL pur). Les calculs viennent de `diagnostic_comparaison`
(`ComparaisonDetail`, `verdict_evolution`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional, Tuple

import angle_units
from diagnostic_comparaison import (
    comparaison_detaillee,
    comparaison_par_brin,
    evolution_globale,
    verdict_contraste,
    verdict_lignes,
)
from geometry import (
    GRADES,
    cavity_polygon,
    contour_polygon,
    degradation_externe_outline,
)
from i18n import _
from palette import (
    COLOR_BARK,
    COLOR_BRAND_ORANGE,
    COLOR_FIELD_BORDER,
    COLOR_INK,
    COLOR_MUTED,
    COLOR_RENDER_ACCENT,
    COLOR_ROT,
    COLOR_SIDE_PANEL,
    COLOR_WOOD,
)
from pil_render import (
    BULLET_RADIUS_PX,
    _draw_horizontal_legend_pil,
    _margin_top_titre,
    _pil_draw_cardinales,
    _pil_draw_cernes,
    _pil_draw_echelle_radiale,
    _pil_draw_sondages,
    _pil_draw_ticks,
    _pil_load_fonts,
    _titre_y,
    render_arbre_to_pil_image,
)

if TYPE_CHECKING:
    from pathlib import Path

    from PIL.Image import Image as PILImage

    from diagnostic_comparaison import ComparaisonDetail
    from model import Arbre, Brin, Chantier

# Grade → angle écran (radians, 0 à 3 h, sens horaire). 360/400 = 0.9 ; le
# Nord (grade 0) est en haut → −90°.
_GR_TO_DEG = 0.9
_ORANGE = (232, 128, 26)   # bois sain perdu depuis la référence
_ORANGE_HEX = "#{:02X}{:02X}{:02X}".format(*_ORANGE)
_VERT = (45, 122, 62)      # bois sain regagné (zone dégradée à la réf., plus maintenant)
_VERT_HEX = "#{:02X}{:02X}{:02X}".format(*_VERT)


def _peindre_evolution(img: "PILImage", ref_polys: List[Any],
                       cur_polys: List[Any]) -> None:
    """Peint sur `img` la différence entre deux ensembles de zones
    dégradées (polygones écran) : **orange** = dégradé maintenant mais pas à
    la référence (aggravation), **vert** = dégradé à la référence mais plus
    maintenant (amélioration), `COLOR_ROT` = dégradé aux deux campagnes.
    Par masques (et non par simple superposition) : seule façon de montrer
    à la fois ce qui s'ajoute et ce qui disparaît."""
    from PIL import Image as _Image
    from PIL import ImageChops, ImageDraw
    m_ref = _Image.new("L", img.size, 0)
    m_cur = _Image.new("L", img.size, 0)
    for mask, polys in ((m_ref, ref_polys), (m_cur, cur_polys)):
        dm = ImageDraw.Draw(mask)
        for pts in polys:
            dm.polygon(pts, fill=255)
    img.paste(_VERT, mask=ImageChops.subtract(m_ref, m_cur))
    img.paste(_ORANGE, mask=ImageChops.subtract(m_cur, m_ref))
    img.paste(COLOR_ROT, mask=ImageChops.multiply(m_ref, m_cur))


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
                                  size: int = 460, *,
                                  show_title: bool = False, titre: str = "",
                                  port: str = "", meche: float = 0.0,
                                  show_sondages: bool = False) -> "PILImage":
    """« Section d'évolution » d'**un brin** : sur la géométrie du brin
    COURANT, le bois sain **perdu depuis la référence** est surligné en
    orange. Contrairement à une lecture « tout depuis le centre », la perte
    est placée À SA VRAIE POSITION :

    - l'**altération interne** (cavité) creuse depuis le **centre** ;
    - la **dégradation externe** ronge depuis la **surface du bois** (sous
      l'écorce).

    Couches concentriques par direction (du bord vers le centre) : écorce →
    bande externe déjà dégradée au ref (`COLOR_ROT`) → bois perdu en externe
    depuis le ref (orange) → bois sain restant (`COLOR_WOOD`) → cavité interne
    nouvelle depuis le ref (orange) → cavité interne déjà présente au ref
    (`COLOR_ROT`). La section ressemble alors à la section réelle (l'encoche
    externe reste sur le pourtour, plus jamais aspirée vers le cœur).

    `ref_b=None` (brin sans homologue de référence) ⟹ aucune couronne orange
    (réf = courant) et une légende « pas de brin de référence ».

    Rendu avec **les mêmes primitives géométriques que la section réelle**
    (`pil_render`) : ellipse native pour un tronc circulaire, `contour_polygon`
    pour un ovale, `cavity_polygon` pour la cavité interne, et surtout
    `degradation_externe_outline` pour les dégradations externes — donc des
    **arcs exacts** (ne débordent jamais de leur secteur) et la **même
    qualité** de tracé que les autres dessins. La perte depuis la référence
    est obtenue par superposition : on peint l'état COURANT en orange (bois
    perdu), puis l'état de RÉFÉRENCE en `COLOR_ROT` par-dessus → l'orange ne
    subsiste que dans la zone creusée entre les deux campagnes.

    `show_title=True` ajoute un titre en tête et une **légende complète**
    en bas (même format que l'export PNG classique d'un arbre,
    `pil_render.render_arbre_to_pil_image` + `_draw_horizontal_legend_pil`) :
    Bois sain / Bois dégradé / Écorce / Sondage (ce dernier seulement si
    `show_sondages`) + un item « Aggravation » pour la couronne orange —
    nom court (légende d'un support visuel, pas une phrase explicative) ET
    distinct de « Bois dégradé » (le `COLOR_ROT` sombre = dégradation déjà
    là à la référence ; l'orange = ce qui s'est ajouté DEPUIS, cf. vocabulaire
    déjà en usage dans `diagnostic_comparaison.verdict_evolution` — les
    confondre sous un même mot comme « Bois perdu » les faisait lire comme
    la même chose). Utilisé par l'export PNG « rapport » (`render_evolution_pngs`).
    `port`/`meche` (genet-level) et `show_sondages` ne servent qu'à cette
    légende complète : ils positionnent aussi les pastilles de sondage sur
    le dessin lui-même, comme la section réelle."""
    from PIL import Image, ImageDraw

    from diagnostic import compute_alteration_par_grade

    img = Image.new("RGB", (size, size), "white")
    d = ImageDraw.Draw(img, "RGBA")          # mode RGBA, comme le rendu réel
    f_base = _pil_load_fonts()
    # Facteur d'échelle des constantes en pixels partagées avec
    # `pil_render` (police des cardinales/de l'échelle radiale, largeurs de
    # trait) — même formule que `render_arbre_to_pil_image` : sans lui, un
    # export haute résolution (2400 px, cf. `render_evolution_pngs`) garde
    # des lettres/tirets calibrés pour un aperçu ~460-532 px, minuscules et
    # se chevauchant avec la légende. La légende elle-même (`sf` plus bas)
    # reste dimensionnée directement en fraction de `size`, DÉJÀ
    # proportionnelle : elle utilise `f_base`, pas ce `f` mis à l'échelle.
    ds = max(1.0, size / 1200.0)

    def f(sz: int, variant: str = "sans") -> Any:
        return f_base(max(1, int(sz * ds)), variant)

    rot = cur_b.rotation_grades
    ep = max(0.0, cur_b.epaisseur_ecorce_cm)
    R_of = cur_b.rayon_a_grade               # callable grade→rayon (cm)
    cur_alt = compute_alteration_par_grade(cur_b)
    if ref_b is not None:
        ref_alt = compute_alteration_par_grade(ref_b)
        ref_degs = ref_b.degradations_externes
    else:
        # Pas d'homologue : réf = courant → l'état courant repeint en ROT
        # par-dessus l'orange ⟹ aucune bande orange (état courant seul).
        ref_alt = list(cur_alt)
        ref_degs = cur_b.degradations_externes

    # Cadrage identique à render_arbre_to_pil_image(show_title=False,
    # show_legend=False) pour que la section d'évolution ait exactement
    # le même grossissement que les sections réf/courant — SAUF avec
    # `show_title=True` (export PNG « rapport » autonome, pas de colonne
    # voisine à aligner) : une bande basse dédiée est alors réservée pour
    # la légende, comme `render_arbre_to_pil_image(show_legend=True)` — sans
    # elle, la légende empiète sur la lettre cardinale « S » (constaté à
    # haute résolution, où sa police — mise à l'échelle par `ds` — grandit
    # sans que son décalage au bord du tronc, un pixel-constant, ne suive).
    expansion = ep + max((c.longueur_cm for c in cur_b.contreforts), default=0.0)
    r_ext_max = max(R_of(g) for g in GRADES) + expansion
    margin_top = _margin_top_titre(size, ds) if show_title else 70
    base_bottom = max(80, int(size * 0.06))
    caption_h = max(70, int(size * 0.09)) if show_title else 0
    if show_title and ref_b is None:
        caption_h += int(size * 0.045)   # 2e ligne : note « sans référence »
    margin_bottom = base_bottom + caption_h
    margin_side = max(60, int(size * 0.055))
    radius_px_max = min((size - 2 * margin_side) / 2,
                        (size - margin_top - margin_bottom) / 2)
    cx = size / 2.0
    cy = margin_top + radius_px_max
    scale = radius_px_max / (r_ext_max if r_ext_max > 0 else 1.0)

    if show_title:
        d.text((size / 2, _titre_y(size)), titre,
               font=f(54, "serif_bold"), fill=COLOR_RENDER_ACCENT,
               anchor="mm")

    R = cur_b.rayon_tronc_cm   # grand axe (= rayon si circulaire)

    def r_ext_of(g: float) -> float:
        return R_of(g) + ep

    # --- Couches, du fond vers le premier plan ---
    # Écorce + bois sain : cercle = ellipse native (nette), ovale = contour
    # lissé — exactement comme `_pil_draw_bois_sain` / `_pil_draw_ecorce`.
    if cur_b.a_rayon_variable:
        if ep > 0:
            d.polygon(contour_polygon(lambda g: R_of(g) + ep, cx, cy, scale,
                                      rotation_grades=rot), fill=COLOR_BARK)
        d.polygon(contour_polygon(R_of, cx, cy, scale, rotation_grades=rot),
                  fill=COLOR_WOOD)
    else:
        if ep > 0:
            rext = (R + ep) * scale
            d.ellipse([cx - rext, cy - rext, cx + rext, cy + rext],
                      fill=COLOR_BARK)
        rw = R * scale
        d.ellipse([cx - rw, cy - rw, cx + rw, cy + rw], fill=COLOR_WOOD)

    # Cernes de graduation (même primitives que la section réelle).
    _pil_draw_cernes(d, cur_b, cx, cy, R, scale)

    # Dégradation externe : arcs EXACTS (`degradation_externe_outline`),
    # orange = approfondie depuis la réf., vert = résorbée depuis la réf.
    def _ext_polys(degs: List[Any]) -> List[Any]:
        polys = []
        for deg in degs:
            pts = degradation_externe_outline(
                deg, cur_b.contreforts, R_of, ep, cx, cy, scale,
                rotation_grades=rot)
            if pts:
                polys.append(pts)
        return polys

    _peindre_evolution(img, _ext_polys(ref_degs),
                       _ext_polys(cur_b.degradations_externes))

    # Cavité interne (`cavity_polygon` = primitive du rendu réel, Catmull-Rom
    # centrée) : orange = anneau creusé depuis la réf., vert = cavité
    # résorbée depuis la réf.
    _peindre_evolution(
        img,
        [cavity_polygon(ref_alt, cx, cy, scale, rotation_grades=rot)]
        if any(a > 0 for a in ref_alt) else [],
        [cavity_polygon(cur_alt, cx, cy, scale, rotation_grades=rot)]
        if any(a > 0 for a in cur_alt) else [])

    d.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], fill=(230, 230, 226))

    # Ticks 16 directions + cardinales N/E/S/O avec halos (même rendu que
    # la section réelle — remplace l'ancien texte nu sans halo).
    _pil_draw_ticks(d, cx, cy, r_ext_of, scale)
    _pil_draw_cardinales(d, f, cx, cy, r_ext_of, scale)

    if show_sondages:
        bullet_r = max(BULLET_RADIUS_PX, int(BULLET_RADIUS_PX * ds))
        _pil_draw_sondages(d, f, cur_b, port, meche, cx, cy, R, scale, bullet_r)

    # Échelle radiale (premier plan, comme la section réelle) : esquive une
    # flèche de sondage seulement si `show_sondages` (sinon plein Est).
    _pil_draw_echelle_radiale(d, f, cur_b, cx, cy, scale, ds,
                              show_sondages=show_sondages)

    if show_title:
        legend_y = size - caption_h + int(size * 0.012)
        extra_items = ((("Aggravation", _ORANGE_HEX),
                        ("Amélioration", _VERT_HEX))
                       if ref_b is not None else ())
        # `height` pilote la taille de police/pastille de la légende, PAS le
        # cadrage (qui reste `width=size`, le vrai canevas) : à `size` réel
        # (2400), les 5 items possibles (sain/dégradé/écorce/sondage/perdu)
        # débordent du canevas si la police suit `size` — même artifice que
        # `fiche_pdf` (légende dimensionnée sur une hauteur fixe, collée sur
        # une page plus large qu'elle).
        legend_font_h = int(size * 0.6)
        _draw_horizontal_legend_pil(d, cur_b, y_top=legend_y, width=size,
                                    height=legend_font_h, font_fn=f_base,
                                    show_sondage_item=show_sondages,
                                    show_classes=False, extra_items=extra_items)
        if ref_b is None:
            note_font = f_base(int(size * 0.022), "sans")
            d.text((size * 0.5, legend_y + int(size * 0.06)),
                   _("pas de brin de référence — état courant seul"),
                   font=note_font, fill=COLOR_MUTED, anchor="mm")
    else:
        # Légende d'origine, compacte, conservée pour les usages existants
        # (fenêtre de comparaison, cartes 3-colonnes) : ces vues affichent
        # déjà les dates en en-tête de colonne, pas besoin de la légende
        # complète ici, et le cadrage doit rester identique aux colonnes
        # voisines (cf. commentaire sur `margin_bottom` plus haut).
        # Légende en bas À GAUCHE, sur deux lignes : centrée, elle passait
        # sous la lettre cardinale « S » (police agrandie par le design
        # system) ; dans le coin elle reste lisible sans toucher au cadrage.
        sf = f_base(int(size * 0.030), "sans")
        line_h = int(size * 0.04)
        x0 = int(size * 0.02)
        if ref_b is None:
            lines = [_("pas de brin de référence"), _("— état courant seul")]
        else:
            lines = []
        entries = ([] if ref_b is None else
                   [(_ORANGE, "aggravation"), (_VERT, "amélioration")])
        n_lines = len(entries) or len(lines)
        cap_y = size - n_lines * line_h - 8
        for k, (col, libelle) in enumerate(entries):
            y0 = cap_y + k * line_h
            d.rectangle([x0, y0, x0 + 20, y0 + 16], fill=col,
                        outline=(150, 150, 146))
            d.text((x0 + 26, y0 + 8), libelle, font=sf, fill=COLOR_MUTED,
                   anchor="lm")
        for i, ln in enumerate(lines):
            d.text((x0, cap_y + 8 + i * line_h), ln, font=sf,
                   fill=COLOR_MUTED, anchor="lm")
    return img


# Légende du « pts » de la ligne t/R minimal — partagée par la fenêtre Tk, la
# page PDF et (en version courte) la carte PNG. Le « pts » = points de
# pourcentage est correct mais jargonneux : un écart de 15 pts entre 45 % et
# 30 % n'est PAS une baisse de 15 % (c'est −33 % en relatif). On l'explicite.
PTS_LEGENDE = ("« pts » = points de pourcentage de t/R : l'écart direct entre "
               "les deux % (et non une variation relative).")


def _classe_aff(classe: Optional[str]) -> str:
    return classe if classe else "non publié"


def _pct_aff(v: Optional[float]) -> str:
    return f"{v:.1f} %" if v is not None else "—"


def metric_rows(detail: "ComparaisonDetail") -> List[Tuple[str, str, str, str]]:
    """Lignes du tableau chiffré : (libellé, référence, courant, évolution).
    Partagé par la fenêtre Tk et la page d'export."""
    rows: List[Tuple[str, str, str, str]] = []
    # Classe (t/R minimal)
    rows.append(("Classe (t/R minimal)", _classe_aff(detail.classe_ref),
                 _classe_aff(detail.classe_cur), ""))
    # Diamètre du tronc — un arbre croît en diamètre entre deux campagnes.
    # Le rendre explicite : chaque PRBS/t/R est déjà rapporté à SON rayon,
    # mais l'opérateur doit voir la croissance (et penser à la saisir).
    if detail.rayon_cur is not None or detail.rayon_ref is not None:
        diam_ref = (f"{2 * detail.rayon_ref:.1f} cm"
                    if detail.rayon_ref is not None else "—")
        diam_cur = (f"{2 * detail.rayon_cur:.1f} cm"
                    if detail.rayon_cur is not None else "—")
        evo_diam = ""
        if detail.rayon_ref is not None and detail.rayon_cur is not None:
            evo_diam = f"{2 * (detail.rayon_cur - detail.rayon_ref):+.1f} cm"
        rows.append(("Diamètre du tronc", diam_ref, diam_cur, evo_diam))
    # t/R minimal (point le plus faible — seul indicateur biomécanique)
    evo_tr = ""
    if detail.tR_min_ref is not None and detail.tR_min_cur is not None:
        dpts = detail.tR_min_cur - detail.tR_min_ref
        evo_tr = f"{dpts:+.1f} pts"
    rows.append(("t/R minimal", _pct_aff(detail.tR_min_ref),
                 _pct_aff(detail.tR_min_cur), evo_tr))
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
    # Part réellement mesurée de la comparaison (le reste est extrapolé).
    if detail.n_mesurees_2_dates is not None:
        rows.append(("Directions mesurées aux 2 dates", "—", "—",
                     f"{detail.n_mesurees_2_dates}/16"))
    # Compartimentation
    rows.append(("Compartimentation perdue (active→absente)", "—", "—",
                 f"{detail.compart_aggravees} direction(s)"))
    # Pire direction
    if detail.pire is not None:
        extrap = "" if detail.pire.mesuree_2_dates else " (extrapolée)"
        rows.append(("Direction la plus aggravée", "—", "—",
                     f"{detail.pire.direction} ({angle_units.fmt(detail.pire.grade)}) : "
                     f"{detail.pire.delta:+.2f} cm{extrap}"))
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


def _fit_pil(font: Any, text: str, max_w: float) -> str:
    """Tronque `text` (avec « … ») pour tenir dans `max_w` pixels."""
    if font.getlength(text) <= max_w:
        return text
    while text and font.getlength(text + "…") > max_w:
        text = text[:-1]
    return text + "…"


_HEADER_TOP, _HEADER_H = 30, 116


def _draw_page_header(page: "PILImage", d: Any, f: Any,
                      chantier: "Optional[Chantier]",
                      logo_path: "Optional[str]") -> None:
    """Bandeau d'en-tête commun aux pages du PDF de comparaison."""
    from pathlib import Path

    from PIL import Image
    margin, W = _PAGE_MARGIN, _PAGE_W
    # En-tête : même bandeau que la fiche d'examen (vert, filet orange de
    # marque, logo du cabinet à droite) — seul le titre dit « comparaison ».
    top, header_h = _HEADER_TOP, _HEADER_H
    d.rectangle([margin, top, W - margin, top + header_h],
                fill=COLOR_RENDER_ACCENT)
    d.rectangle([margin, top + header_h, W - margin, top + header_h + 4],
                fill=COLOR_BRAND_ORANGE)
    logo_w = 0
    try:
        if logo_path and Path(logo_path).exists():
            logo = Image.open(logo_path).convert("RGBA")
            target_h = header_h - 24
            lw = int(logo.width * target_h / logo.height)
            lx, ly = W - margin - lw - 12, top + 12
            bg = Image.new("RGB", logo.size, "white")
            bg.paste(logo, (0, 0), logo)
            d.rectangle([lx, ly, lx + lw, ly + target_h], fill="white")
            page.paste(bg.resize((lw, target_h)), (lx, ly))
            logo_w = lw + 24
    except Exception:
        pass
    text_w = W - 2 * margin - logo_w - 40
    d.text((margin + 20, top + 22),
           "Fiche d'examen approfondis — Pénétromètre — Comparaison",
           font=f(30, "serif_bold"), fill="white")
    if chantier is not None:
        f19, f17 = f(19, "sans"), f(17, "sans")
        ligne2 = "   •   ".join(t for t in (
            chantier.adresse,
            f"{_('Client')} : {chantier.client}" if chantier.client else ""
        ) if t)
        d.text((margin + 20, top + 64), _fit_pil(f19, ligne2, text_w),
               font=f19, fill="white")
        d.text((margin + 20, top + 92),
               _fit_pil(f17, f"{chantier.date_releve}   •   {_('Opérateur')}"
                        f" : {chantier.operateur}", text_w),
               font=f17, fill="white")



def _draw_page_footer(d: Any, f: Any, chantier: "Optional[Chantier]",
                      port: str, cabinet_name: str) -> None:
    """Pied de page commun (cf. `fiche_pdf._draw_footer`)."""
    from datetime import datetime

    from bareme import description_seuils_arbre
    margin, W = _PAGE_MARGIN, _PAGE_W
    if chantier is not None:
        fy = _PAGE_H - 60
        d.line([margin, fy, W - margin, fy], fill=COLOR_MUTED, width=1)
        d.text((W / 2, fy + 16),
               _("Barème appliqué") + " — "
               + description_seuils_arbre(chantier, port),
               font=f(12, "sans"), fill=COLOR_MUTED, anchor="mm")
        cab = f"{cabinet_name}   •   " if cabinet_name else ""
        d.text((W / 2, fy + 38),
               cab + _("Édité le")
               + f" {datetime.now().strftime('%d/%m/%Y à %H:%M')}",
               font=f(14, "sans"), fill=COLOR_MUTED, anchor="mm")


def _compose_comparison_page(mission_nom: str, titre: str, ref_label: str,
                             cur_label: str, ref_img: "PILImage",
                             cur_img: "PILImage", evo_img: "PILImage",
                             detail: "ComparaisonDetail", *,
                             chantier: "Optional[Chantier]" = None,
                             port: str = "",
                             logo_path: "Optional[str]" = None,
                             cabinet_name: str = "") -> "PILImage":
    """Compose une page A4 paysage (en-tête identique à la fiche d'examen,
    3 dessins déjà rendus à `_PAGE_SEC`, tableau chiffré, verdict, pied de
    page). Partagé par la page **genet** et les pages **par brin**.

    `titre` = ligne d'identité de l'arbre (« Arbre 12 », « Arbre 12 — Brin
    a »). Sans `chantier` (anciens appelants/tests), l'en-tête se limite au
    bandeau et le pied de page est omis."""
    from PIL import Image, ImageDraw

    f = _pil_load_fonts()
    W, margin, gap, sec = _PAGE_W, _PAGE_MARGIN, _PAGE_GAP, _PAGE_SEC
    page = Image.new("RGB", (W, _PAGE_H), "white")
    d = ImageDraw.Draw(page)

    _draw_page_header(page, d, f, chantier, logo_path)

    # Identité de l'arbre (comme sous le bandeau de la fiche).
    y_id = _HEADER_TOP + _HEADER_H + 18
    d.text((margin, y_id), titre, font=f(35, "serif_bold"), fill=COLOR_INK)

    # Trois sections côte à côte (images déjà rendues).
    y_lbl = y_id + 56
    y_img = y_lbl + 30
    cols = ((_("Référence — {r}").format(r=ref_label), ref_img),
            (f"Courant — {cur_label}", cur_img),
            ("Évolution de l'altération", evo_img))
    for i, (titre_col, img) in enumerate(cols):
        x = margin + i * (sec + gap)
        d.text((x, y_lbl), titre_col, font=f(18, "sans_bold"), fill=COLOR_INK)
        page.paste(img, (x, y_img))

    # Tableau chiffré.
    y = y_img + sec + 18
    y_table = y
    rows = metric_rows(detail)
    col_x = [margin, margin + 520, margin + 520 + 250,
             margin + 520 + 250 + 250]
    headers = ("Indicateur", "Référence", "Courant", "Évolution")
    head_h = 34
    d.rectangle([margin, y, W - margin, y + head_h], fill=COLOR_RENDER_ACCENT)
    for cx0, h in zip(col_x, headers):
        d.text((cx0 + 10, y + head_h / 2), h, font=f(16, "sans_bold"),
               fill="white", anchor="lm")
    y += head_h
    # Tableau plus dense quand il a beaucoup de lignes (sinon le verdict, qui
    # peut tenir sur 2 lignes de détail, mordrait sur le pied de page).
    row_h = 30 if len(rows) <= 7 else 26
    for k, row in enumerate(rows):
        if k % 2 == 1:
            d.rectangle([margin, y, W - margin, y + row_h], fill=COLOR_SIDE_PANEL)
        for cx0, val in zip(col_x, row):
            d.text((cx0 + 10, y + row_h / 2), val, font=f(15, "sans"),
                   fill=COLOR_INK, anchor="lm")
        y += row_h
    d.rectangle([margin, y_table, W - margin, y], outline=COLOR_FIELD_BORDER)

    # Note explicative du « pts » (sous le tableau).
    y += 8
    d.text((margin, y), PTS_LEGENDE, font=f(13, "sans"), fill=COLOR_MUTED)

    # Verdict.
    y += 26
    titre, precisions = verdict_lignes(detail)
    d.text((margin, y), titre, font=f(22, "sans_bold"),
           fill=_verdict_fill(detail))
    f_det = f(15, "sans")
    ligne = ""
    y_det = y + 34
    for mot in precisions.split(" "):
        essai = f"{ligne} {mot}" if ligne else mot
        if ligne and f_det.getlength(essai) > W - 2 * margin:
            d.text((margin, y_det), ligne, font=f_det, fill=COLOR_INK)
            y_det += 22
            ligne = mot
        else:
            ligne = essai
    if ligne:
        d.text((margin, y_det), ligne, font=f_det, fill=COLOR_INK)

    _draw_page_footer(d, f, chantier, port, cabinet_name)
    return page


def verdict_couleur(detail: "ComparaisonDetail") -> Optional[str]:
    """Couleur du verdict (source unique fenêtre ↔ export) : rouge =
    aggravation, ambre = évolution contrastée, vert = amélioration,
    `None` = stable / non comparable (à la charge de l'appelant)."""
    evo = evolution_globale(detail)
    if evo is None:
        return None
    if verdict_contraste(detail):
        return "#B7791F"
    if evo > 0:
        return "#C0392B"
    if evo < 0:
        return "#2D7A3E"
    return None


def _verdict_fill(detail: "ComparaisonDetail") -> str:
    return verdict_couleur(detail) or COLOR_INK


def render_comparison_page(mission_nom: str, ref_arbre: "Arbre",
                           cur_arbre: "Arbre", detail: "ComparaisonDetail",
                           *, ref_label: str, cur_label: str,
                           show_sondages: bool = True,
                           chantier: "Optional[Chantier]" = None,
                           logo_path: "Optional[str]" = None,
                           cabinet_name: str = "") -> "PILImage":
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
        mission_nom, cur_arbre.display_name,
        ref_label, cur_label, ref_img, cur_img, evo_img, detail,
        chantier=chantier, port=cur_arbre.port_arbre,
        logo_path=logo_path, cabinet_name=cabinet_name)


# Nombre max. de photos reprises par colonne dans le PDF (grille 2 × 2).
PHOTOS_COMPARAISON_MAX = 4


def _charger_photos(refs: List[str], mission_dir: "Optional[Path]"
                    ) -> List["PILImage"]:
    """Photos utilisables d'une colonne (`PHOTOS_COMPARAISON_MAX` au plus).

    Même confinement que la fiche (`photo_paths.resolve_photo`) ; un fichier
    refusé, introuvable ou non décodable comme image est **ignoré** (jamais
    de crash d'export pour une photo déplacée)."""
    from PIL import Image, ImageOps

    from photo_paths import resolve_photo
    out: List["PILImage"] = []
    for ref in refs:
        if len(out) >= PHOTOS_COMPARAISON_MAX:
            break
        path = resolve_photo(ref, mission_dir).path
        if path is None:
            continue
        try:
            with Image.open(path) as im:
                out.append(ImageOps.exif_transpose(im).convert("RGB"))
        except Exception:
            continue
    return out


def _compose_photos_page(nom_arbre: str, ref_label: str, cur_label: str,
                         ref_photos: List["PILImage"],
                         cur_photos: List["PILImage"], *,
                         chantier: "Optional[Chantier]", port: str,
                         logo_path: "Optional[str]",
                         cabinet_name: str) -> "PILImage":
    """Page A4 paysage « évolution photographique » : photos de la
    référence (gauche) et de l'état actuel (droite), séparées par un trait
    vertical, avec l'en-tête de la page photos de la fiche classique et le
    pied de page des pages de comparaison. Légendes « Photo N » — jamais un nom de
    fichier (cf. CLAUDE.md, photos = entrée semi-fiable)."""
    from PIL import Image, ImageDraw
    f = _pil_load_fonts()
    W, margin, gap = _PAGE_W, _PAGE_MARGIN, 56
    page = Image.new("RGB", (W, _PAGE_H), "white")
    d = ImageDraw.Draw(page)
    # En-tête identique à la page photos de la fiche classique
    # (`fiche_pdf._render_photos_page`) : bandeau vert de 80 px, filet
    # orange de marque, « Photos — Arbre n° X » en serif gras blanc.
    top, header_h = _HEADER_TOP, 80
    d.rectangle([margin, top, W - margin, top + header_h],
                fill=COLOR_RENDER_ACCENT)
    d.rectangle([margin, top + header_h, W - margin, top + header_h + 4],
                fill=COLOR_BRAND_ORANGE)
    d.text((margin + 20, top + header_h // 2),
           _("Photos") + f"   —   {nom_arbre}",
           font=f(28, "serif_bold"), fill="white", anchor="lm")

    col_w = (W - 2 * margin - gap) // 2
    y_lbl = top + header_h + 28
    y0 = y_lbl + 32
    y_max = _PAGE_H - 60 - 16
    avail_h = y_max - y0
    cap_h = 26
    cols = ((_("Référence — {r}").format(r=ref_label), ref_photos),
            (f"Courant — {cur_label}", cur_photos))
    for i, (titre_col, photos) in enumerate(cols):
        x = margin + i * (col_w + gap)
        d.text((x, y_lbl), titre_col, font=f(18, "sans_bold"), fill=COLOR_INK)
        if not photos:
            d.text((x, y0 + 8), _("Aucune photo"), font=f(16, "sans"),
                   fill=COLOR_MUTED)
            continue
        n = len(photos)
        n_cols, n_rows = (1, 1) if n == 1 else (1, 2) if n == 2 else (2, 2)
        cell_w = (col_w - (n_cols - 1) * 16) // n_cols
        cell_h = (avail_h - (n_rows - 1) * 16) // n_rows
        for k, im in enumerate(photos):
            r, c = divmod(k, n_cols)
            cx = x + c * (cell_w + 16)
            cy = y0 + r * (cell_h + 16)
            box_w, box_h = cell_w, cell_h - cap_h
            im = im.copy()
            im.thumbnail((box_w, box_h))
            page.paste(im, (cx + (box_w - im.width) // 2,
                            cy + (box_h - im.height) // 2))
            d.text((cx + cell_w / 2, cy + box_h + cap_h / 2 + 2),
                   f"Photo {k + 1}", font=f(14, "sans"), fill=COLOR_MUTED,
                   anchor="mm")
    # Séparation physique référence | actuel : trait vertical au milieu de
    # la gouttière, sur toute la hauteur de la zone photos.
    sep_x = margin + col_w + gap // 2
    d.line([sep_x, y_lbl, sep_x, y_max], fill=COLOR_FIELD_BORDER, width=3)
    _draw_page_footer(d, f, chantier, port, cabinet_name)
    return page


def render_comparison_pages(mission_nom: str, ref_arbre: "Arbre",
                            cur_arbre: "Arbre", annees: Optional[float],
                            *, ref_label: str, cur_label: str,
                            show_sondages: bool = True,
                            chantier: "Optional[Chantier]" = None,
                            logo_path: "Optional[str]" = None,
                            cabinet_name: str = "",
                            mission_dir: "Optional[Path]" = None
                            ) -> List["PILImage"]:
    """Pages d'export de la comparaison : **une page par brin** pour une
    cépée (dessins du brin isolé + évolution brin-level + tableau/verdict du
    brin), une **page genet** pour un mono-caule (vue d'ensemble, inchangée).
    Le brin courant sans homologue de référence reçoit une colonne
    « Référence » vide (jamais d'appariement décalé). `show_sondages` suit la
    case « Afficher sondages » sous le canevas.

    Si l'arbre courant porte des **photos de comparaison** (référence /
    actuel, `Arbre.photos_comparaison_*`, résolues depuis `mission_dir`),
    une page « évolution photographique » est ajoutée à la fin."""
    pages = _pages_sondages(
        mission_nom, ref_arbre, cur_arbre, annees, ref_label=ref_label,
        cur_label=cur_label, show_sondages=show_sondages, chantier=chantier,
        logo_path=logo_path, cabinet_name=cabinet_name)
    ref_ph = _charger_photos(cur_arbre.photos_comparaison_ref, mission_dir)
    cur_ph = _charger_photos(cur_arbre.photos_comparaison_cur, mission_dir)
    if ref_ph or cur_ph:
        pages.append(_compose_photos_page(
            cur_arbre.display_name, ref_label, cur_label, ref_ph, cur_ph, chantier=chantier,
            port=cur_arbre.port_arbre, logo_path=logo_path,
            cabinet_name=cabinet_name))
    return pages


def _pages_sondages(mission_nom: str, ref_arbre: "Arbre", cur_arbre: "Arbre",
                    annees: Optional[float], *, ref_label: str,
                    cur_label: str, show_sondages: bool,
                    chantier: "Optional[Chantier]",
                    logo_path: "Optional[str]",
                    cabinet_name: str) -> List["PILImage"]:
    """Pages de comparaison chiffrée (genet ou une par brin)."""
    if len(cur_arbre.brins) <= 1:
        detail = comparaison_detaillee(ref_arbre, cur_arbre, annees)
        return [render_comparison_page(
            mission_nom, ref_arbre, cur_arbre, detail,
            ref_label=ref_label, cur_label=cur_label,
            show_sondages=show_sondages, chantier=chantier,
            logo_path=logo_path, cabinet_name=cabinet_name)]
    pages: List["PILImage"] = []
    for label, cur_b, ref_b, detail in comparaison_par_brin(
            ref_arbre, cur_arbre, annees):
        ref_img = (render_brin_section(ref_arbre, ref_b, _PAGE_SEC,
                                       show_sondages=show_sondages)
                   if ref_b is not None
                   else _blank_section(_PAGE_SEC, _("pas de brin de référence")))
        cur_img = render_brin_section(cur_arbre, cur_b, _PAGE_SEC,
                                      show_sondages=show_sondages)
        evo_img = render_evolution_section_brin(ref_b, cur_b, _PAGE_SEC)
        titre = f"{cur_arbre.display_name} — Brin {label}"
        pages.append(_compose_comparison_page(
            mission_nom, titre, ref_label, cur_label,
            ref_img, cur_img, evo_img, detail, chantier=chantier,
            port=cur_arbre.port_arbre, logo_path=logo_path,
            cabinet_name=cabinet_name))
    return pages


# --- Export PNG « rapport » (section d'évolution seule) ------------------
# Le PNG n'est plus la carte 3-colonnes (référence / courant / évolution +
# verdict) : trop dense pour être insérée telle quelle dans un rapport
# d'expertise (texte + trois dessins). Il reprend désormais EXACTEMENT le
# format de l'export PNG classique d'un arbre (titre + un seul dessin +
# légende, cf. `pil_render.render_arbre_to_pil_image`), mais le dessin est
# la « section d'évolution » (couronne orange = bois sain perdu depuis la
# référence). La feuille A4 complète (3 dessins + tableau + verdict) reste
# le format du PDF (`render_comparison_pages`), inchangé — c'est le
# livrable formel, pas destiné à être recadré dans un rapport tiers.
_EVOLUTION_PNG_SIZE = 2400   # même résolution que l'export PNG classique


def render_evolution_pngs(mission_nom: str, ref_arbre: "Arbre",
                          cur_arbre: "Arbre", annees: Optional[float],
                          *, ref_label: str, cur_label: str,
                          show_sondages: bool = True
                          ) -> List[Tuple[str, "PILImage"]]:
    """Export PNG « rapport » : **une image par brin** pour une cépée, une
    image **genet** pour un mono-caule — chacune au format de l'export PNG
    classique (titre + section d'évolution + légende complète). `mission_nom`
    ne pèse pas sur ce rendu (pas de mission affichée) ; `ref_label`/
    `cur_label` non plus (la légende ne date plus l'image, cf.
    `render_evolution_section_brin`) — les deux sont conservés pour que ce
    constructeur reste interchangeable avec `render_comparison_pages` dans
    `comparaison._page_builder`. `show_sondages` reprend la case « Afficher
    sondages » : pastilles sur le dessin + item « Sondage » de la légende.

    Renvoie `[(label, image)]` — `label=""` pour le mono-caule (fichier
    unique) ; `label="a"/"b"/…` pour chaque brin d'une cépée, pour que
    `save_evolution_pngs` écrive **un fichier PNG par brin** (une cépée
    stockée dans une seule image empilée verticalement n'est pas
    directement insérable dans un rapport)."""
    if len(cur_arbre.brins) <= 1:
        img = render_evolution_section_brin(
            ref_arbre.brin_courant, cur_arbre.brin_courant,
            _EVOLUTION_PNG_SIZE, show_title=True,
            titre=cur_arbre.display_name,
            port=cur_arbre.port_arbre, meche=cur_arbre.meche_cm,
            show_sondages=show_sondages)
        return [("", img)]
    imgs: List[Tuple[str, "PILImage"]] = []
    for label, cur_b, ref_b, _detail in comparaison_par_brin(
            ref_arbre, cur_arbre, annees):
        imgs.append((label, render_evolution_section_brin(
            ref_b, cur_b, _EVOLUTION_PNG_SIZE, show_title=True,
            titre=f"{cur_arbre.display_name} — Brin {label}",
            port=cur_arbre.port_arbre, meche=cur_arbre.meche_cm,
            show_sondages=show_sondages)))
    return imgs


def save_evolution_pngs(pages: List[Tuple[str, "PILImage"]],
                        path: str) -> List[str]:
    """Enregistre l'export PNG « rapport » (`render_evolution_pngs`) :
    **un fichier par brin** pour une cépée (suffixe `_brin_<label>` avant
    l'extension du chemin choisi, dans le même dossier), le chemin choisi
    tel quel pour un mono-caule (`label=""`, page unique) — contrairement
    aux autres exports comparaison, jamais empilé en une seule image.
    Renvoie les chemins effectivement écrits (le premier sert de repère
    pour `App.notify_export`)."""
    if len(pages) == 1 and pages[0][0] == "":
        pages[0][1].save(path, "PNG")
        return [path]
    import os
    stem, ext = os.path.splitext(path)
    ext = ext or ".png"
    written = []
    for label, img in pages:
        p = f"{stem}_brin_{label}{ext}"
        img.save(p, "PNG")
        written.append(p)
    return written


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
