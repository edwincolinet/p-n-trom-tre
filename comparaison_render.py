"""
Rendu PIL de la comparaison inter-missions (ré-inspection) :

- `render_evolution_section_brin` : la « section d'évolution » (progression,
  recouvrement, écarts à vérifier, bois neuf) ;
- `render_evolution_pngs` : export PNG « rapport », un fichier par brin ;
- `metric_rows` / `verdict_couleur` : partagés avec l'onglet et le PDF
  (`fiche_evolution`).

Module sans Tk (PIL pur). Les calculs viennent de `diagnostic_comparaison`
(`ComparaisonDetail`, `verdict_evolution`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional, Tuple

import angle_units
from campagnes import cal_depuis
from diagnostic_comparaison import (
    comparaison_par_brin,
    directions_a_verifier,
    evolution_degradation,
)
from evolution import degradations_reference_recalees, hauteurs_incompatibles
from geometry import (
    GRADES,
    cal_outline,
    cavity_polygon,
    contour_polygon,
    degradation_externe_outline,
    ring_polygon_points,
)
from i18n import _
from palette import (
    COLOR_BARK,
    COLOR_MUTED,
    COLOR_NEW_WOOD,
    COLOR_RENDER_ACCENT,
    COLOR_ROT,
    COLOR_WOOD,
)
from pil_render import (
    BULLET_RADIUS_PX,
    _draw_horizontal_legend_pil,
    _margin_top_titre,
    _pil_draw_cardinales,
    _pil_draw_echelle_radiale,
    _pil_draw_sondages,
    _pil_draw_ticks,
    _pil_load_fonts,
    _titre_y,
    render_arbre_to_pil_image,
)

if TYPE_CHECKING:

    from PIL.Image import Image as PILImage

    from diagnostic_comparaison import ComparaisonDetail
    from model import Arbre, Brin

# Grade → angle écran (radians, 0 à 3 h, sens horaire). 360/400 = 0.9 ; le
# Nord (grade 0) est en haut → −90°.
_GR_TO_DEG = 0.9
_ORANGE = (232, 128, 26)   # bois sain perdu depuis la référence
_ORANGE_HEX = "#{:02X}{:02X}{:02X}".format(*_ORANGE)
_VERT = (45, 122, 62)      # dégradation externe recouverte par du bois neuf
_VERT_HEX = "#{:02X}{:02X}{:02X}".format(*_VERT)
_VIOLET = (110, 90, 170)   # cavité en recul : impossible en principe, à vérifier
_VIOLET_HEX = "#{:02X}{:02X}{:02X}".format(*_VIOLET)


def _peindre_evolution(img: "PILImage", ref_polys: List[Any],
                       cur_polys: List[Any],
                       couleur_recul: Tuple[int, int, int]) -> None:
    """Peint sur `img` la différence entre deux ensembles de zones
    dégradées (polygones écran) : **orange** = dégradé maintenant mais pas à
    la référence (progression), `couleur_recul` = dégradé à la référence mais
    plus maintenant, `COLOR_ROT` = dégradé aux deux campagnes.
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
    img.paste(couleur_recul, mask=ImageChops.subtract(m_ref, m_cur))
    img.paste(_ORANGE, mask=ImageChops.subtract(m_cur, m_ref))
    img.paste(COLOR_ROT, mask=ImageChops.multiply(m_ref, m_cur))


def render_evolution_section(ref_arbre: "Arbre", cur_arbre: "Arbre",
                             size: int = 460) -> "PILImage":
    """« Section d'évolution » au niveau **genet** (brin courant) — délègue
    à `render_evolution_section_brin`. Conservé pour le rendu mono-caule et
    l'export genet."""
    return render_evolution_section_brin(
        ref_arbre.brin_courant, cur_arbre.brin_courant, size,
        non_comparable=hauteurs_incompatibles(ref_arbre, cur_arbre) is not None)


def render_brin_section(src: "Arbre", brin: "Brin", size: int = 460,
                        *, show_sondages: bool = True,
                        show_cernes: bool = True) -> "PILImage":
    """Rend la section d'**un seul brin** (ramet) d'une cépée, centrée,
    comme un mono-caule. Astuce : on emballe le brin dans un genet temporaire
    (identité reprise pour la couleur des sondages = port), puis on réutilise
    `render_arbre_to_pil_image`. Évite un renderer brin-isolé dédié.
    `show_sondages` suit la case « Afficher sondages » sous le canevas."""
    from model import Arbre
    tmp = Arbre(numero_arbre=src.numero_arbre, essence=src.essence,
                port_arbre=src.port_arbre, meche_cm=src.meche_cm)
    tmp.brins = [brin]
    tmp.campagnes = src.campagnes          # pour situer les plaies sous cal
    return render_arbre_to_pil_image(
        tmp, size, size, show_sondages=show_sondages, show_title=False,
        show_legend=False, show_cernes=show_cernes)


def render_evolution_section_brin(ref_b: Optional["Brin"], cur_b: "Brin",
                                  size: int = 460, *,
                                  show_title: bool = False, titre: str = "",
                                  port: str = "", meche: float = 0.0,
                                  show_sondages: bool = False,
                                  non_comparable: bool = False
                                  ) -> "PILImage":
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

    `non_comparable=True` (hauteurs de sondage différentes) : aucune zone
    d'évolution n'est peinte, seul l'état courant est montré.

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

    img = Image.new("RGB", (size, size), "white")
    d = ImageDraw.Draw(img, "RGBA")          # mode RGBA, comme le rendu réel
    f_base = _pil_load_fonts()
    # Facteur d'échelle des constantes en pixels partagées avec
    # `pil_render` (police des cardinales/de l'échelle radiale, largeurs de
    # trait) — même formule que `render_arbre_to_pil_image` : sans lui, un
    # export haute résolution (2400 px, cf. `render_evolution_pngs`) garde
    # des lettres/tirets calibrés pour un aperçu ~460-532 px, minuscules et
    # se chevauchant avec la légende. La légende elle-même reste
    # dimensionnée directement en fraction de `size`, DÉJÀ proportionnelle :
    # elle utilise `f_base`, pas ce `f` mis à l'échelle.
    ds = max(1.0, size / 1200.0)

    def f(sz: int, variant: str = "sans") -> Any:
        return f_base(max(1, int(sz * ds)), variant)

    cx, cy, scale, caption_h = _evo_cadrage(
        cur_b, size, ds, show_title=show_title,
        sans_ref=ref_b is None or non_comparable)
    if non_comparable:
        ref_b = None

    if show_title:
        d.text((size / 2, _titre_y(size)), titre,
               font=f(54, "serif_bold"), fill=COLOR_RENDER_ACCENT,
               anchor="mm")

    _evo_couches(img, d, f, ref_b, cur_b, cx, cy, scale, ds, port=port,
                 meche=meche, show_sondages=show_sondages)

    if show_title:
        _evo_legende_complete(d, f_base, cur_b, size, caption_h,
                              avec_ref=ref_b is not None,
                              show_sondages=show_sondages,
                              non_comparable=non_comparable)
    else:
        _evo_legende_compacte(d, f_base, size, avec_ref=ref_b is not None,
                              non_comparable=non_comparable)
    return img


def _evo_cadrage(cur_b: "Brin", size: int, ds: float, *, show_title: bool,
                 sans_ref: bool) -> Tuple[float, float, float, int]:
    """Cadrage `(cx, cy, scale, caption_h)` de la section d'évolution.

    Identique à `render_arbre_to_pil_image(show_title=False,
    show_legend=False)` pour que la section d'évolution ait exactement le
    même grossissement que les sections réf/courant — SAUF avec
    `show_title=True` (export PNG « rapport » autonome, pas de colonne
    voisine à aligner) : une bande basse dédiée (`caption_h`) est alors
    réservée pour la légende, comme `render_arbre_to_pil_image(
    show_legend=True)` — sans elle, la légende empiète sur la lettre
    cardinale « S » (constaté à haute résolution, où sa police — mise à
    l'échelle par `ds` — grandit sans que son décalage au bord du tronc, un
    pixel-constant, ne suive)."""
    ep = cur_b.ep_max_cm
    R_of = cur_b.rayon_a_grade
    expansion = ep + max((c.longueur_cm for c in cur_b.contreforts), default=0.0)
    r_ext_max = max(R_of(g) for g in GRADES) + expansion
    margin_top = _margin_top_titre(size, ds) if show_title else 70
    base_bottom = max(80, int(size * 0.06))
    caption_h = max(70, int(size * 0.09)) if show_title else 0
    if show_title and sans_ref:
        caption_h += int(size * 0.045)   # 2e ligne : note « sans référence »
    margin_bottom = base_bottom + caption_h
    margin_side = max(60, int(size * 0.055))
    radius_px_max = min((size - 2 * margin_side) / 2,
                        (size - margin_top - margin_bottom) / 2)
    cx = size / 2.0
    cy = margin_top + radius_px_max
    scale = radius_px_max / (r_ext_max if r_ext_max > 0 else 1.0)
    return cx, cy, scale, caption_h


def _evo_couches(img: "PILImage", d: Any, f: Any, ref_b: Optional["Brin"],
                 cur_b: "Brin", cx: float, cy: float, scale: float,
                 ds: float, *, port: str, meche: float,
                 show_sondages: bool) -> None:
    """Peint les couches de la section d'évolution, du fond vers le premier
    plan : écorce + bois sain, cernes, dégradations externes (diff réf →
    courant), cavité interne (diff), repères (ticks, cardinales), sondages,
    échelle radiale."""
    from diagnostic import compute_alteration_par_grade

    rot = cur_b.rotation_grades
    ep = cur_b.ep_max_cm                      # plus forte épaisseur d'écorce
    ep_spec = cur_b.ep_a_grade if cur_b.a_ecorce_variable else ep
    R_of = cur_b.rayon_a_grade               # callable grade→rayon (cm)
    cur_alt = compute_alteration_par_grade(cur_b)
    if ref_b is not None:
        # Une direction non sondée aux deux dates ne constate rien : on y
        # reprend la valeur courante pour ne rien colorer.
        communs = ({s.grade for s in ref_b.sondages if not s.a_confirmer}
                   & {s.grade for s in cur_b.sondages if not s.a_confirmer})
        alt = compute_alteration_par_grade(ref_b)
        ref_alt = [alt[i] if g in communs else cur_alt[i]
                   for i, g in enumerate(GRADES)]
        ref_degs = degradations_reference_recalees(ref_b, cur_b)
    else:
        # Pas d'homologue : réf = courant → l'état courant repeint en ROT
        # par-dessus l'orange ⟹ aucune bande orange (état courant seul).
        ref_alt = list(cur_alt)
        ref_degs = cur_b.degradations_externes

    R = cur_b.rayon_tronc_cm   # grand axe (= rayon si circulaire)

    def r_ext_of(g: float) -> float:
        return cur_b.rayon_ext_a_grade(g)

    # Écorce + bois sain : cercle = ellipse native (nette), ovale = contour
    # lissé — exactement comme `_pil_draw_bois_sain` / `_pil_draw_ecorce`.
    if cur_b.a_rayon_variable or cur_b.a_ecorce_variable:
        if ep > 0:
            d.polygon(contour_polygon(cur_b.rayon_ext_a_grade, cx, cy, scale,
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

    # Bois formé depuis la référence (anneau plus clair). Les cernes de
    # graduation sont volontairement absents : ils brouillent la lecture.
    if ref_b is not None and R > ref_b.rayon_tronc_cm:
        d.polygon(ring_polygon_points(
            contour_polygon(R_of, cx, cy, scale, rotation_grades=rot),
            contour_polygon(ref_b.rayon_a_grade, cx, cy, scale,
                            rotation_grades=rot)), fill=COLOR_NEW_WOOD)

    # Dégradation externe : arcs EXACTS (`degradation_externe_outline`),
    # orange = approfondie depuis la réf., vert = résorbée depuis la réf.
    def _ext_polys(degs: List[Any], profondeurs_cal: List[float]
                   ) -> List[Any]:
        polys = []
        for deg, cal in zip(degs, profondeurs_cal):
            pts = degradation_externe_outline(
                deg, cur_b.contreforts, R_of, ep_spec, cx, cy, scale,
                rotation_grades=rot, cal_cm=cal)
            if pts:
                polys.append(pts)
        return polys

    # Plaie recouverte : placée sous le bois formé depuis la référence.
    cal_cur = [(cal_depuis(ref_b, cur_b, d) or 0.0) if ref_b is not None
               else 0.0 for d in cur_b.degradations_externes]
    croissance = (max(0.0, cur_b.rayon_tronc_cm - ref_b.rayon_tronc_cm)
                  if ref_b is not None else 0.0)
    cal_ref = [croissance if d.recouverte else 0.0 for d in ref_degs]
    _peindre_evolution(img, _ext_polys(ref_degs, cal_ref),
                       _ext_polys(cur_b.degradations_externes, cal_cur), _VERT)

    for deg, cal in zip(cur_b.degradations_externes, cal_cur):
        if deg.recouverte:
            bourrelet = cal_outline(
                deg, cur_b.contreforts, R_of, ep_spec, cx, cy, scale,
                rotation_grades=rot, cal_cm=cal)
            if bourrelet:
                d.polygon(bourrelet, fill=_VERT, outline=COLOR_BARK)

    # Cavité interne (`cavity_polygon` = primitive du rendu réel, Catmull-Rom
    # centrée) : orange = anneau creusé depuis la réf., vert = cavité
    # résorbée depuis la réf.
    _peindre_evolution(
        img,
        [cavity_polygon(ref_alt, cx, cy, scale, rotation_grades=rot)]
        if any(a > 0 for a in ref_alt) else [],
        [cavity_polygon(cur_alt, cx, cy, scale, rotation_grades=rot)]
        if any(a > 0 for a in cur_alt) else [], _VIOLET)

    # Contour de l'ancienne cavité, en tireté.
    if ref_b is not None and any(a > 0 for a in ref_alt):
        bord = cavity_polygon(ref_alt, cx, cy, scale, rotation_grades=rot)
        bord.append(bord[0])
        for i in range(0, len(bord) - 1, 4):
            d.line(bord[i:i + 3], fill=(255, 255, 255),
                   width=max(2, int(2 * ds)))

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


def _evo_legende_complete(d: Any, f_base: Any, cur_b: "Brin", size: int,
                          caption_h: int, *, avec_ref: bool,
                          show_sondages: bool,
                          non_comparable: bool) -> None:
    """Légende complète de l'export PNG « rapport » (`show_title=True`) :
    Bois sain / dégradé / écorce / sondage + « Progression » (orange),
    « Recouvrement » (vert) et « À vérifier » (violet) ; note si pas de
    référence exploitable."""
    legend_y = size - caption_h + int(size * 0.012)
    extra_items = ((("Progression", _ORANGE_HEX),
                    ("Recouvrement", _VERT_HEX),
                    ("À vérifier", _VIOLET_HEX))
                   if avec_ref else ())
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
    if not avec_ref:
        note_font = f_base(int(size * 0.022), "sans")
        d.text((size * 0.5, legend_y + int(size * 0.06)),
               _("hauteurs de sondage différentes — état courant seul")
               if non_comparable
               else _("pas de brin de référence — état courant seul"),
               font=note_font, fill=COLOR_MUTED, anchor="mm")


def _evo_legende_compacte(d: Any, f_base: Any, size: int, *,
                          avec_ref: bool, non_comparable: bool) -> None:
    """Légende d'origine, compacte, conservée pour les usages existants
    (dessin de l'onglet Évolution, page PDF à 3 colonnes) : ces vues
    affichent déjà les dates autour du dessin, pas besoin de la légende complète ici,
    et le cadrage doit rester identique aux colonnes voisines. En bas À
    GAUCHE : centrée, elle passait sous la lettre cardinale « S » ; dans le
    coin elle reste lisible sans toucher au cadrage."""
    sf = f_base(int(size * 0.030), "sans")
    line_h = int(size * 0.04)
    x0 = int(size * 0.02)
    if avec_ref:
        lines: List[str] = []
        entries = [(_ORANGE, "progression"), (_VERT, "recouvrement"),
                   (_VIOLET, "à vérifier")]
    elif non_comparable:
        lines = [_("hauteurs différentes"), _("— état courant seul")]
        entries = []
    else:
        lines = [_("pas de brin de référence"), _("— état courant seul")]
        entries = []
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
    refus = detail.hauteurs_incompatibles
    if (refus is None and detail.tR_min_ref is not None
            and detail.tR_min_cur is not None):
        # Même arrondi que le verdict : écart des valeurs AFFICHÉES.
        dpts = round(detail.tR_min_cur, 1) - round(detail.tR_min_ref, 1)
        evo_tr = f"{dpts:+.1f} pts"
    rows.append(("t/R minimal", _pct_aff(detail.tR_min_ref),
                 _pct_aff(detail.tR_min_cur), evo_tr))
    if refus is not None:
        rows.append(("Hauteur de sondage", f"{refus[0]:g} cm",
                     f"{refus[1]:g} cm", "différente : non comparable"))
        return rows
    # Avancée moyenne de la dégradation (directions évaluées, hors croissance).
    if detail.progression_moy is not None:
        rows.append(("Progression moyenne de la dégradation", "—", "—",
                     f"{detail.progression_moy:.2f} cm / direction"))
    # Taux annualisé (uniquement si l'intervalle est suffisant).
    if detail.taux_cm_an is not None:
        rows.append(("Taux annualisé", "—", "—",
                     f"{detail.taux_cm_an:.2f} cm/an"))
    elif detail.annees is None:
        rows.append(("Taux annualisé", "—", "—", "missions non datées"))
    elif detail.progression_moy is not None:
        rows.append(("Taux annualisé", "—", "—",
                     "intervalle trop court (< 6 mois)"))
    # Part réellement mesurée de la comparaison (le reste est extrapolé).
    if detail.n_mesurees_2_dates is not None:
        rows.append(("Directions sondées aux 2 dates", "—", "—",
                     f"{detail.n_mesurees_2_dates}/16"))
    # Compartimentation
    rows.append(("Compartimentation perdue (active→absente)", "—", "—",
                 f"{detail.compart_aggravees} direction(s)"))
    # Pire direction
    if detail.pire is not None:
        rows.append(("Direction la plus aggravée", "—", "—",
                     f"{detail.pire.direction} ({angle_units.fmt(detail.pire.grade)}) : "
                     f"{detail.pire.progression:+.2f} cm"))
    return rows


def verdict_couleur(detail: "ComparaisonDetail") -> Optional[str]:
    """Couleur du verdict (source unique fenêtre ↔ export) : rouge =
    progression, ambre = écarts à vérifier, vert = recouvrement,
    `None` = pas de progression / pas de conclusion (à la charge de
    l'appelant)."""
    evo = evolution_degradation(detail)
    if evo == 1:
        return "#C0392B"
    if directions_a_verifier(detail):
        return "#B7791F"
    if evo == -1:
        return "#2D7A3E"
    return None


# --- Export PNG « rapport » (section d'évolution seule) ------------------
# Le PNG n'est plus la carte 3-colonnes (référence / courant / évolution +
# verdict) : trop dense pour être insérée telle quelle dans un rapport
# d'expertise (texte + trois dessins). Il reprend désormais EXACTEMENT le
# format de l'export PNG classique d'un arbre (titre + un seul dessin +
# légende, cf. `pil_render.render_arbre_to_pil_image`), mais le dessin est
# la « section d'évolution » (zones orange = dégradation en progression depuis la
# référence). Le livrable formel complet est le PDF
# (`fiche_evolution`).
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
    constructeur garde la même signature que celui du PDF. `show_sondages` reprend la case « Afficher
    sondages » : pastilles sur le dessin + item « Sondage » de la légende.

    Renvoie `[(label, image)]` — `label=""` pour le mono-caule (fichier
    unique) ; `label="a"/"b"/…` pour chaque brin d'une cépée, pour que
    `save_evolution_pngs` écrive **un fichier PNG par brin** (une cépée
    stockée dans une seule image empilée verticalement n'est pas
    directement insérable dans un rapport)."""
    if max(len(ref_arbre.brins), len(cur_arbre.brins)) <= 1:
        img = render_evolution_section_brin(
            ref_arbre.brin_courant, cur_arbre.brin_courant,
            _EVOLUTION_PNG_SIZE, show_title=True,
            titre=cur_arbre.display_name,
            port=cur_arbre.port_arbre, meche=cur_arbre.meche_cm,
            show_sondages=show_sondages,
            non_comparable=hauteurs_incompatibles(
                ref_arbre, cur_arbre) is not None)
        return [("", img)]
    imgs: List[Tuple[str, "PILImage"]] = []
    for label, cur_b, ref_b, detail in comparaison_par_brin(
            ref_arbre, cur_arbre, annees):
        imgs.append((label, render_evolution_section_brin(
            ref_b, cur_b, _EVOLUTION_PNG_SIZE, show_title=True,
            titre=f"{cur_arbre.display_name} — Brin {label}",
            port=cur_arbre.port_arbre, meche=cur_arbre.meche_cm,
            show_sondages=show_sondages,
            non_comparable=detail.hauteurs_incompatibles is not None)))
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
