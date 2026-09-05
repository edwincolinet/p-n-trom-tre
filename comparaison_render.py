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

from diagnostic_comparaison import (
    comparaison_detaillee,
    comparaison_par_brin,
    verdict_evolution,
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
    COLOR_INK,
    COLOR_MUTED,
    COLOR_RENDER_ACCENT,
    COLOR_ROT,
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
    from PIL.Image import Image as PILImage

    from diagnostic_comparaison import ComparaisonDetail
    from model import Arbre, Brin

# Grade → angle écran (radians, 0 à 3 h, sens horaire). 360/400 = 0.9 ; le
# Nord (grade 0) est en haut → −90°.
_GR_TO_DEG = 0.9
_ORANGE = (232, 128, 26)   # bois sain perdu depuis la référence
_ORANGE_HEX = "#{:02X}{:02X}{:02X}".format(*_ORANGE)


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

    # Dégradation externe : profondeur COURANTE en orange, profondeur de
    # RÉFÉRENCE en ROT par-dessus → orange = bande approfondie depuis la réf.
    # Arcs EXACTS (`degradation_externe_outline`) : plus de débordement.
    for deg in cur_b.degradations_externes:
        pts = degradation_externe_outline(deg, cur_b.contreforts, R_of, ep,
                                          cx, cy, scale, rotation_grades=rot)
        if pts:
            d.polygon(pts, fill=_ORANGE)
    for deg in ref_degs:
        pts = degradation_externe_outline(deg, cur_b.contreforts, R_of, ep,
                                          cx, cy, scale, rotation_grades=rot)
        if pts:
            d.polygon(pts, fill=COLOR_ROT)

    # Cavité interne : courante en orange, référence en ROT par-dessus →
    # orange = anneau creusé depuis la réf. `cavity_polygon` = primitive du
    # rendu réel (Catmull-Rom centrée, pas de bord arc → lissage légitime).
    if any(a > 0 for a in cur_alt):
        d.polygon(cavity_polygon(cur_alt, cx, cy, scale, rotation_grades=rot),
                  fill=_ORANGE)
    if any(a > 0 for a in ref_alt):
        d.polygon(cavity_polygon(ref_alt, cx, cy, scale, rotation_grades=rot),
                  fill=COLOR_ROT)

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
        extra_items = (("Aggravation", _ORANGE_HEX),) if ref_b is not None else ()
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
        sf = f_base(int(size * 0.030), "sans")
        cap_y = size * 0.95
        if ref_b is None:
            d.text((size * 0.5, cap_y + 8),
                   _("pas de brin de référence — état courant seul"),
                   font=sf, fill=COLOR_MUTED, anchor="mm")
        else:
            d.rectangle([size * 0.14, cap_y, size * 0.14 + 20, cap_y + 16],
                        fill=_ORANGE, outline=(150, 150, 146))
            d.text((size * 0.14 + 26, cap_y + 8),
                   "= bois sain perdu depuis la référence",
                   font=sf, fill=COLOR_MUTED, anchor="lm")
    return img


# Légende du « pts » de la ligne t/R moyen — partagée par la fenêtre Tk, la
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
    # Classe globale
    rows.append(("Classe globale", _classe_aff(detail.classe_ref),
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
    d.rectangle([0, 0, W, 92], fill=COLOR_RENDER_ACCENT)
    d.text((margin, 20), titre, font=f(30, "serif_bold"), fill="white")
    d.text((margin, 62),
           f"Mission « {mission_nom or 'Mission'} »   •   "
           f"Référence : {ref_label}   →   Courant : {cur_label}",
           font=f(17, "sans"), fill="white")

    # Trois sections côte à côte (images déjà rendues).
    y_lbl = 116
    y_img = y_lbl + 34
    cols = ((_("Référence — {r}").format(r=ref_label), ref_img),
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
    d.rectangle([margin, y, W - margin, y + head_h], fill=COLOR_RENDER_ACCENT)
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

    # Note explicative du « pts » (sous le tableau).
    y += 8
    d.text((margin, y), PTS_LEGENDE, font=f(13, "sans"), fill=COLOR_MUTED)

    # Verdict.
    y += 28
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
                   else _blank_section(_PAGE_SEC, _("pas de brin de référence")))
        cur_img = render_brin_section(cur_arbre, cur_b, _PAGE_SEC,
                                      show_sondages=show_sondages)
        evo_img = render_evolution_section_brin(ref_b, cur_b, _PAGE_SEC)
        titre = (f"Comparaison d'inspections — "
                 f"{cur_arbre.display_name} — Brin {label}")
        pages.append(_compose_comparison_page(
            mission_nom, titre, ref_label, cur_label,
            ref_img, cur_img, evo_img, detail))
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
