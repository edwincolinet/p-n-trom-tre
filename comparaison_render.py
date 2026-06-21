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

from typing import TYPE_CHECKING, Any, List, Optional, Tuple

from diagnostic import (
    comparaison_detaillee,
    comparaison_par_brin,
    evolution_classe,
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
    COLOR_ACCENT,
    COLOR_BARK,
    COLOR_INK,
    COLOR_MUTED,
    COLOR_ROT,
    COLOR_WOOD,
)
from pil_render import (
    _pil_draw_cardinales,
    _pil_draw_cernes,
    _pil_draw_echelle_radiale,
    _pil_draw_ticks,
    _pil_load_fonts,
    render_arbre_to_pil_image,
)

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage

    from diagnostic import ComparaisonDetail
    from model import Arbre, Brin

# Grade → angle écran (radians, 0 à 3 h, sens horaire). 360/400 = 0.9 ; le
# Nord (grade 0) est en haut → −90°.
_GR_TO_DEG = 0.9
_ORANGE = (232, 128, 26)   # bois sain perdu depuis la référence


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
    subsiste que dans la zone creusée entre les deux campagnes."""
    from PIL import Image, ImageDraw

    from diagnostic import compute_alteration_par_grade

    img = Image.new("RGB", (size, size), "white")
    d = ImageDraw.Draw(img, "RGBA")          # mode RGBA, comme le rendu réel
    f = _pil_load_fonts()

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
    # le même grossissement que les sections réf/courant.
    expansion = ep + max((c.longueur_cm for c in cur_b.contreforts), default=0.0)
    r_ext_max = max(R_of(g) for g in GRADES) + expansion
    margin_top = 70
    margin_bottom = max(80, int(size * 0.06))
    margin_side = max(60, int(size * 0.055))
    radius_px_max = min((size - 2 * margin_side) / 2,
                        (size - margin_top - margin_bottom) / 2)
    cx = size / 2.0
    cy = margin_top + radius_px_max
    scale = radius_px_max / (r_ext_max if r_ext_max > 0 else 1.0)

    R = cur_b.rayon_tronc_cm   # grand axe (= rayon si circulaire)

    def r_ext_of(g: float) -> float:
        return R_of(g) + ep

    # --- Couches, du fond vers le premier plan ---
    # Écorce + bois sain : cercle = ellipse native (nette), ovale = contour
    # lissé — exactement comme `_pil_draw_bois_sain` / `_pil_draw_ecorce`.
    if cur_b.est_ovale:
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

    # Échelle radiale (premier plan, comme la section réelle). Pas de
    # sondages dans la section d'évolution → toujours plein Est.
    _pil_draw_echelle_radiale(d, f, cur_b, cx, cy, scale, 1.0,
                              show_sondages=False)

    sf = f(int(size * 0.030), "sans")
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
    d.rectangle([0, 0, W, 92], fill=COLOR_ACCENT)
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


# --- « Carte visuelle » de comparaison (export PNG) ----------------------
# Le PNG n'est plus une rasterisation de la feuille A4 (en-tête, tableau
# chiffré, verdict) : c'est une image resserrée, centrée sur les TROIS
# dessins (référence / courant / évolution) + le verdict. Pensée pour le
# partage rapide ou l'insertion dans un rapport, là où la fiche A4 (PDF)
# reste le livrable formel. Cf. choix produit (carte visuelle).
_CARD_MARGIN = 40
_CARD_GAP = 24
_CARD_SEC = _PAGE_SEC                                   # 532, dessins nets
_CARD_W = 2 * _CARD_MARGIN + 3 * _CARD_SEC + 2 * _CARD_GAP


def _verdict_rgb(detail: "ComparaisonDetail") -> Any:
    """Couleur du verdict selon l'évolution de classe (aggravation = rouge,
    amélioration = vert, stable = encre). Pendant PIL de `_verdict_color`
    (côté Tk) — gardé local pour que ce module reste sans dépendance UI."""
    evo = evolution_classe(detail.classe_ref, detail.classe_cur)
    if evo is None:
        return COLOR_MUTED
    if evo > 0:
        return "#C0392B"
    if evo < 0:
        return "#2D7A3E"
    return COLOR_INK


def _wrap_card(text: str, font: Any, max_w: float, draw: Any,
               max_lines: int = 3) -> List[str]:
    """Retour à la ligne par mots pour le verdict de la carte (borné)."""
    lines: List[str] = []
    cur = ""
    for word in (text or "").split():
        trial = (cur + " " + word).strip()
        if not cur or draw.textbbox((0, 0), trial, font=font)[2] <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines[:max_lines]


def _compose_comparison_card(titre: str, sous_titre: str, ref_label: str,
                             cur_label: str, ref_img: "PILImage",
                             cur_img: "PILImage", evo_img: "PILImage",
                             detail: "ComparaisonDetail") -> "PILImage":
    """Compose une carte visuelle : titre léger, 3 dessins côte à côte avec
    en-têtes de colonne, verdict coloré dessous. Pas de bandeau plein ni de
    tableau chiffré (≠ page A4). Hauteur ajustée au verdict (1 à 3 lignes)."""
    from PIL import Image, ImageDraw
    f = _pil_load_fonts()
    margin, gap, sec, W = _CARD_MARGIN, _CARD_GAP, _CARD_SEC, _CARD_W

    title_font = f(30, "serif_bold")
    sub_font = f(17, "sans")
    col_font = f(20, "sans_bold")
    verdict_font = f(21, "sans_bold")
    note_font = f(14, "sans")

    title_h, sub_h = 40, (26 if sous_titre else 0)
    gap_after_title, col_h, gap_after_img, line_h = 18, 34, 22, 30

    # Pré-mesure du verdict (wrap) pour dimensionner la hauteur de la carte.
    tmp = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    verdict = verdict_evolution(detail)
    vlines = _wrap_card(verdict, verdict_font, W - 2 * margin, tmp)
    verdict_h = max(1, len(vlines)) * line_h
    # Note « pts » seulement si le verdict en contient (t/R comparable).
    show_note = "pts" in verdict
    note_h = 28 if show_note else 0

    total_h = (margin + title_h + sub_h + gap_after_title + col_h + sec
               + gap_after_img + verdict_h + note_h + margin)

    card = Image.new("RGB", (W, total_h), "white")
    d = ImageDraw.Draw(card)

    # Filet d'accent vertical à gauche (rappel du langage visuel des fiches).
    d.rectangle([0, 0, 6, total_h], fill=COLOR_ACCENT)

    y = margin
    d.text((margin, y), titre, font=title_font, fill=COLOR_INK)
    y += title_h
    if sous_titre:
        d.text((margin, y), sous_titre, font=sub_font, fill=COLOR_MUTED)
        y += sub_h
    y += gap_after_title

    cols = ((_("Référence — {r}").format(r=ref_label), ref_img),
            (f"Courant — {cur_label}", cur_img),
            ("Évolution de l'altération", evo_img))
    y_img = y + col_h
    for i, (titre_col, img) in enumerate(cols):
        x = margin + i * (sec + gap)
        d.text((x + sec / 2, y), titre_col, font=col_font,
               fill=COLOR_INK, anchor="ma")
        card.paste(img, (x, y_img))
    y = y_img + sec + gap_after_img

    vcol = _verdict_rgb(detail)
    for line in vlines:
        d.text((margin, y), line, font=verdict_font, fill=vcol)
        y += line_h
    if show_note:
        y += 4
        d.text((margin, y), PTS_LEGENDE, font=note_font, fill=COLOR_MUTED)
    return card


def render_comparison_cards(mission_nom: str, ref_arbre: "Arbre",
                            cur_arbre: "Arbre", annees: Optional[float],
                            *, ref_label: str, cur_label: str,
                            show_sondages: bool = True) -> List["PILImage"]:
    """Cartes visuelles d'export PNG : **une carte par brin** pour une cépée,
    une carte **genet** pour un mono-caule. Même appariement et même choix de
    dessins que `render_comparison_pages`, mais composition resserrée (3
    dessins + verdict, sans tableau). Le sous-titre rappelle la mission."""
    sous_titre = f"Mission « {mission_nom or 'Mission'} »"
    if len(cur_arbre.brins) <= 1:
        detail = comparaison_detaillee(ref_arbre, cur_arbre, annees)
        ref_img = render_arbre_to_pil_image(
            ref_arbre, _CARD_SEC, _CARD_SEC, show_sondages=show_sondages,
            show_title=False, show_legend=False)
        cur_img = render_arbre_to_pil_image(
            cur_arbre, _CARD_SEC, _CARD_SEC, show_sondages=show_sondages,
            show_title=False, show_legend=False)
        evo_img = render_evolution_section(ref_arbre, cur_arbre, _CARD_SEC)
        return [_compose_comparison_card(
            f"Comparaison d'inspections — {cur_arbre.display_name}",
            sous_titre, ref_label, cur_label,
            ref_img, cur_img, evo_img, detail)]
    cards: List["PILImage"] = []
    for label, cur_b, ref_b, detail in comparaison_par_brin(
            ref_arbre, cur_arbre, annees):
        ref_img = (render_brin_section(ref_arbre, ref_b, _CARD_SEC,
                                       show_sondages=show_sondages)
                   if ref_b is not None
                   else _blank_section(_CARD_SEC, _("pas de brin de référence")))
        cur_img = render_brin_section(cur_arbre, cur_b, _CARD_SEC,
                                      show_sondages=show_sondages)
        evo_img = render_evolution_section_brin(ref_b, cur_b, _CARD_SEC)
        cards.append(_compose_comparison_card(
            f"Comparaison d'inspections — {cur_arbre.display_name} — Brin {label}",
            sous_titre, ref_label, cur_label,
            ref_img, cur_img, evo_img, detail))
    return cards


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
