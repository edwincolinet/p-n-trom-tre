"""
Fiche d'expertise PDF — layout d'une page A4 pour un arbre.

Pendant « page A4 » de `pil_render.render_arbre_to_pil_image` : assemble
sur une page portrait 150 DPI l'en-tête mission + logo cabinet,
l'identité de l'arbre, le dessin de section, la légende horizontale,
le tableau PRBS ajustée et le diagnostic enrichi (t/R moyen + min,
barre de répartition, classe globale).

Ce module est dédié au LAYOUT — il n'introduit aucune géométrie nouvelle
et ne dessine pas la section transversale lui-même. Il compose des
briques existantes :
- `pil_render.render_arbre_to_pil_image` pour le dessin du tronc ;
- `pil_render._draw_horizontal_legend_pil` pour la légende ;
- `pil_render._pil_load_fonts` pour la factory de polices ;
- les calculs métier (`Arbre.repartition_classes`,
  `Arbre.degradation_externe_par_grade`, `classer_prbs`) pour le tableau
  et le diagnostic.

`render_fiche_arbre_to_pdf_page` renvoie une `PIL.Image`. La conversion
en fichier PDF (`page.save(p, "PDF", resolution=150.0)`) reste à la
charge de l'appelant (`app_exports.export_pdf_arbre`).

Si Pillow n'est pas installé, importer ce module reste possible ; le
premier appel à `render_fiche_arbre_to_pdf_page` lèvera `ImportError`.
L'appelant doit tester `pil_render.HAS_PIL` avant.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bareme import classer_prbs
from diagnostic import (
    degradation_externe_par_grade,
    genet_diagnostic,
    repartition_classes,
    repartition_classes_brin,
)
from geometry import DIRECTION_LABELS, GRADES
from i18n import _
from palette import (
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_INK,
    COLOR_MUTED,
    COULEUR_CLASSE,
)
from pil_render import (
    _draw_horizontal_legend_pil,
    _pil_load_fonts,
    render_arbre_to_pil_image,
)

if TYPE_CHECKING:
    from PIL import ImageDraw  # noqa: F401
    from PIL.Image import Image as PILImage  # noqa: F401

    from model import Arbre, Chantier  # noqa: F401


def _fit_text(text: str, font: Any, max_width: float,
              draw: "ImageDraw.ImageDraw") -> str:
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


def _wrap_lines(text: str, font: Any, max_width: float,
                draw: "ImageDraw.ImageDraw", max_lines: int = 4) -> list:
    """Découpe `text` en lignes tenant dans `max_width` (retour à la ligne
    par mots), bornées à `max_lines` (dernière ligne tronquée « … » si le
    texte déborde). Pour la préconisation libre de la fiche PDF."""
    lines: list = []
    cur = ""
    for word in (text or "").split():
        trial = (cur + " " + word).strip()
        if not cur or draw.textbbox((0, 0), trial, font=font)[2] <= max_width:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = _fit_text(lines[-1] + " …", font, max_width, draw)
    return lines


# Couleur du badge d'urgence (fond plein, texte blanc) selon le délai —
# gradient vert (peu urgent) → rouge (immédiat).
_URGENCE_COLOR = {
    "Immédiate": "#C0392B",
    "< 6 mois":  "#E67E22",
    "< 1 an":    "#B7950B",
    "< 2 ans":   "#2D7A3E",
}


def _estimate_preco_height(d: "ImageDraw.ImageDraw", f: Any, arbre: "Arbre",
                           txt_w: int, has_intervention: bool,
                           has_suivi: bool) -> int:
    """Hauteur (px) qu'occupera la colonne préconisation.

    Miroir **exact** des incréments de `y_preco` dans le dessin
    (`render_fiche_arbre_to_pdf_page`), pour réserver la place dans le
    budget vertical : sans ça, un suivi (ou une intervention) long déborde
    sur le pied de page, le dessin ne rétrécissant que pour le diagnostic.
    Toute modif des incréments de dessin doit être répercutée ici."""
    h = 36  # titre "Préconisation" (y_preco = y_section + 36)
    if has_intervention:
        h += 32 + 12   # bande "Intervention" (_preco_header)
        if arbre.urgence:
            bb = d.textbbox((0, 0), arbre.urgence, font=f(16, "sans_bold"))
            h += int(bb[3] - bb[1]) + 2 * 7 + 12   # badge
        if arbre.echeance:
            h += 26
        if arbre.preconisation:
            n = len(_wrap_lines(arbre.preconisation, f(16, "sans"),
                                txt_w, d, max_lines=8))
            h += 2 + n * 22
        h += 14
    if has_suivi:
        h += 32 + 12   # bande "Suivi"
        if arbre.suivi_validite:
            h += 26
        if arbre.suivi_texte:
            n = len(_wrap_lines(arbre.suivi_texte, f(16, "sans"),
                                txt_w, d, max_lines=8))
            h += 2 + n * 22
        h += 6
    return h


def render_fiche_arbre_to_pdf_page(arbre: "Arbre",
                                   chantier: "Chantier",
                                   show_sondages: bool = True,
                                   logo_path: "str | None" = None,
                                   cabinet_name: str = "") -> "PILImage":
    """Construit une page A4 portrait 150 DPI (1240 × 1754 px environ)
    avec : en-tête chantier, dessin, tableau PRBS, diagnostic.

    Les tailles de police, largeurs de colonnes et marges sont calibrées
    pour rester lisibles à l'impression (≈ 12 pt minimum au tirage A4).

    `show_sondages` reflète la case « Afficher l'emplacement des sondages
    sur le dessin » : à `False`, les pastilles/flèches sont omises **du
    dessin** (le tableau PRBS reste, lui, toujours présent — c'est la donnée).
    """
    from PIL import Image, ImageDraw
    f = _pil_load_fonts()

    # A4 portrait à 150 DPI
    W, H = 1240, 1754
    page = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(page)

    margin = 60
    y = margin

    # --- En-tête mission avec logo cabinet ---
    header_h = 116
    d.rectangle([margin, y, W-margin, y+header_h], fill=COLOR_ACCENT)
    # Logo à droite
    logo_w = 0
    try:
        _logo_path = Path(logo_path) if logo_path else None
        if _logo_path and _logo_path.exists():
            logo = Image.open(_logo_path).convert("RGBA")
            target_h = header_h - 24
            ratio = target_h / logo.height
            logo = logo.resize(
                (int(logo.width * ratio), target_h),
                Image.Resampling.LANCZOS)
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
    _lbl_client = _("Client")
    _lbl_ref = _("Réf.")
    mission_txt = _fit_text(
        (_("Mission") + f" : {chantier.nom}"
         + (f"   •   {chantier.adresse}" if chantier.adresse else "")
         + (f"   •   {_lbl_client} : {chantier.client}" if chantier.client else "")
         + (f"   •   {_lbl_ref} : {chantier.reference}" if chantier.reference else "")),
        f(19, "sans"), header_text_w, d)
    d.text((margin+20, y+64), mission_txt,
           font=f(19, "sans"), fill="white")
    d.text((margin+20, y+92),
           f"{chantier.date_releve}   •   " + _("Opérateur") + f" : {chantier.operateur}",
           font=f(17, "sans"), fill="white")
    y += header_h + 18

    # --- Identité de l'arbre ---
    d.text((margin, y), arbre.display_name,
           font=f(35, "serif_bold"), fill=COLOR_INK)
    y += 50
    R = arbre.rayon_tronc_cm
    ligne = (f"Rayon : {R:g} cm   •   "
             + _("Ø sous écorce") + f" : {arbre.diametre_sous_ecorce_cm:g} cm   •   "
             + f"Hauteur : {arbre.hauteur_arbre_m:g} m   •   "
             + f"Port : {arbre.port_arbre}")
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
    # tableau PRBS, le diagnostic et la préconisation (en pied), puis on
    # alloue le reste au dessin (entre 480 et 900 px).
    multi_brins = len(arbre.brins) > 1
    # Cépée = même prédicat de routage que les renderers (≥ 2 brins, ou un
    # brin décentré) : le dessin part alors en composition multi-brins.
    is_cepee = not (len(arbre.brins) == 1
                    and arbre.brins[0].pos_x_cm == 0.0
                    and arbre.brins[0].pos_y_cm == 0.0)
    # Total des sondages sur tous les brins (cépée) pour dimensionner la
    # hauteur du tableau et du dessin.
    n_sond = sum(len(b.sondages) for b in arbre.brins
                 if b.rayon_tronc_cm > 0)
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
    if multi_brins:
        # Cépée : encadré classe globale (76) + titre du détail (32) +
        # une ligne par brin (28) + marge. Bien plus compact que le bloc
        # mono-brin — le majorant 360 rapetissait le dessin pour rien.
        est_diag_h = 76 + 32 + 28 * len(arbre.brins) + 24
    else:
        est_diag_h = 360  # majorant : t/R + bar + détail + classe globale
    # La légende horizontale est dessinée APRÈS le dessin du tronc, sur
    # la pleine largeur de la page (pas dans l'image du tronc qui est
    # plus étroite). On réserve une bande pour elle dans le calcul.
    est_legend_h = 56
    footer_reserve = 60
    # has_intervention/has_suivi : utilisés plus bas pour le layout côte à côte.
    has_intervention = bool(arbre.urgence or arbre.echeance or arbre.preconisation)
    has_suivi = bool(arbre.suivi_validite or arbre.suivi_texte)
    # La préconisation (colonne droite) partage la bande verticale du
    # diagnostic ; on réserve donc le MAX des deux hauteurs, sinon une
    # préconisation plus haute que le diagnostic déborde sur le pied de page
    # (le dessin ne rétrécissant que pour le diagnostic). La géométrie de la
    # colonne droite est dérivée à l'identique du dessin (cf. plus bas).
    if has_intervention or has_suivi:
        _preco_left = (margin + 680) + 20
        _preco_txt_w = (W - margin) - 12 - (_preco_left + 12)
        est_preco_h = _estimate_preco_height(
            d, f, arbre, _preco_txt_w, has_intervention, has_suivi)
    else:
        est_preco_h = 0
    est_section_h = max(est_diag_h, est_preco_h)
    used_so_far = y - margin   # depuis le haut de la page utile
    remaining = (H - margin - footer_reserve) - used_so_far \
                - est_table_h - est_section_h - est_legend_h - 22
    # Plancher modeste (340) : il ne s'active que sur une page chargée
    # (beaucoup de sondages / longue préconisation), cas où l'on VEUT que
    # le dessin rétrécisse pour honorer le budget vertical et éviter de
    # rogner le texte. Sur une page normale, `remaining` dépasse le plancher.
    drawing_h = max(340, min(900, remaining))
    if is_cepee:
        # Une cépée est LARGE (brins côte à côte, cadrée sur la largeur) :
        # dans le carré historique chaque brin devenait minuscule. Pleine
        # largeur utile de la page ; la hauteur est en plus bornée par le
        # ratio cm réel de la cépée (+ marges internes du rendu : boussole,
        # bandes) pour ne pas créer de grandes bandes blanches — la
        # composition centre verticalement les brins.
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
    # Le dessin lui-même est rendu sans légende ; la légende est tracée
    # ci-dessous, en dehors du dessin, pour profiter de toute la largeur.
    drawing = render_arbre_to_pil_image(arbre, drawing_w, drawing_h,
                                        show_sondages=show_sondages,
                                        show_title=False,
                                        show_legend=False)
    x_draw = (W - drawing_w) // 2
    page.paste(drawing, (x_draw, y))
    y += drawing_h + 6
    # Légende horizontale, centrée, sur la pleine largeur utile. Calibrée
    # pour donner des polices ≈ 16 pt et des pastilles bien lisibles.
    if R > 0:
        # `show_sondage_item` suit la case « Afficher les sondages » : si
        # les pastilles sont masquées sur le dessin, l'item « Sondage » de
        # la légende disparaît aussi (sinon incohérence légende ↔ dessin).
        _draw_horizontal_legend_pil(d, arbre, y_top=y,
                                     width=W, height=900, font_fn=f,
                                     show_sondage_item=show_sondages,
                                     show_classes=False)
        y += est_legend_h

    # --- Tableau PRBS ajustée par sondage (par brin pour une cépée) ---
    if n_sond > 0:
        titre_tbl = ("Paroi Résiduelle de Bois Sain par sondage et par brin"
                     if multi_brins
                     else "Paroi Résiduelle de Bois Sain par sondage")
        d.text((margin, y), titre_tbl,
               font=f(22, "serif_bold"), fill=COLOR_ACCENT)
        y += 36
        # Largeurs de colonnes redistribuées : Direction et PRBS plus
        # généreuses (où les valeurs sont les plus longues), Compart.
        # rétrécie (souvent juste « - » ou « active »).
        # Total = 70 + 220 + 270 + 130 + 160 + 270 = 1120 = W - 2*margin.
        col_widths = [70, 220, 270, 130, 160, 270]
        cols_x = [margin]
        for w in col_widths:
            cols_x.append(cols_x[-1] + w)
        # cols_x = [60, 130, 350, 620, 750, 910, 1180]
        headers = [_("N°"), _("Direction"), _("PRBS (cm)"), _("t/R (%)"),
                   _("Classe"), _("Compart.")]
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
        # Itère tous les brins ; le N° est préfixé par le label en cépée
        # (« a1 », « b2 »). Chaque brin a son propre rayon et ses propres
        # dégradations externes (port partagé au niveau genet).
        k = 0
        for b in arbre.brins:
            R_b = b.rayon_tronc_cm
            if R_b <= 0:
                continue
            deg_ext_par_grade = degradation_externe_par_grade(b)
            for s in b.sondages:
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
                    d.rectangle([cols_x[0], y, cols_x[-1], y+row_h],
                                fill=COLOR_BG)
                k += 1
                prbs_txt = f"{prbs_adj:g}"
                _pfx = "~" if getattr(s, "incertain", False) else ""
                num_txt = (_pfx + (f"{b.label}{s.numero}" if multi_brins and b.label
                           else str(s.numero)))
                vals = [num_txt, direction, prbs_txt,
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

    # --- Diagnostic (col. gauche) + Préconisation (col. droite) côte à côte ---
    # Si une préconisation est saisie, la page se partage en deux colonnes :
    # diagnostic à gauche (680 px), trait de séparation, préconisation à droite
    # (400 px). Sans préconisation, le diagnostic occupe toute la largeur.
    has_preco = has_intervention or has_suivi
    col_diag_left = margin
    col_diag_right = (margin + 680) if has_preco else (W - margin)
    col_preco_left = col_diag_right + 20
    col_preco_right = W - margin

    y_section = y                 # y commun aux deux colonnes
    d.text((col_diag_left, y_section), _("Diagnostic"),
           font=f(22, "serif_bold"), fill=COLOR_ACCENT)
    y_diag = y_section + 36
    if multi_brins:
        y_diag = int(_draw_cepee_diagnostic(
            d, f, arbre, col_diag_left, col_diag_right, y_diag))
    else:
        y_diag = int(_draw_mono_diagnostic(
            d, f, arbre, col_diag_left, col_diag_right, R, y_diag))

    y_preco = y_section
    if has_preco:
        pad = 12                       # padding interne sous les bandes
        txt_x = col_preco_left + pad
        txt_w = col_preco_right - pad - txt_x

        # Titre aligné sur "Diagnostic" (même police, même baseline)
        d.text((col_preco_left, y_preco), _("Préconisation"),
               font=f(22, "serif_bold"), fill=COLOR_ACCENT)
        y_preco = y_section + 36

        # Filet de sécurité : ligne basse que le rendu ne franchit JAMAIS,
        # calée 8 px au-dessus du filet de pied de page (tracé à H-46).
        # Le budget vertical réserve déjà max(diagnostic, préconisation) et
        # rétrécit le dessin, mais un cas pathologique (beaucoup de sondages
        # ET deux textes longs) ne tient pas sur une A4 : on tronque alors le
        # texte (« … ») plutôt que de déborder sur le pied de page.
        y_limit = (H - 46) - 8

        def _preco_header(title: str, y0: int) -> int:
            """Sous-titre = bande verte pleine largeur, texte blanc — même
            langage visuel que les en-têtes de tableau du reste de la page."""
            bar_h = 32
            d.rectangle([col_preco_left, y0, col_preco_right, y0 + bar_h],
                        fill=COLOR_ACCENT)
            d.text((col_preco_left + pad, y0 + bar_h / 2), title,
                   font=f(16, "sans_bold"), fill="white", anchor="lm")
            return y0 + bar_h + 12

        def _draw_preco_text(text: str, y0: int) -> int:
            """Dessine `text` en lignes 16 pt sans jamais dépasser `y_limit`
            (tronque avec « … » si la place manque)."""
            avail = int((y_limit - y0) // 22)
            if avail < 1:
                return y0
            for line in _wrap_lines(text, f(16, "sans"), txt_w, d,
                                    max_lines=min(8, avail)):
                d.text((txt_x, y0), line, font=f(16, "sans"), fill=COLOR_INK)
                y0 += 22
            return y0

        # On ne pose une bande d'en-tête que si au moins une ligne de
        # contenu peut suivre (sinon une bande verte vide en bas de page).
        if has_intervention and y_preco + 32 + 24 <= y_limit:
            y_preco = _preco_header("Intervention", y_preco)

            if arbre.urgence and y_preco + 46 <= y_limit:
                # Ligne "Urgence : [badge coloré]" (symétrie avec "Échéance :")
                lbl = "Urgence : "
                lbl_w = d.textbbox((0, 0), lbl, font=f(16, "sans"))[2]
                urg_color = _URGENCE_COLOR.get(arbre.urgence, COLOR_INK)
                fnt = f(16, "sans_bold")
                bb = d.textbbox((0, 0), arbre.urgence, font=fnt)
                uw, uh = bb[2] - bb[0], bb[3] - bb[1]
                bx, by = 12, 7
                d.text((txt_x, y_preco + by), lbl,
                       font=f(16, "sans"), fill=COLOR_MUTED)
                badge_x = txt_x + lbl_w
                d.rectangle([badge_x, y_preco,
                             badge_x + uw + 2 * bx, y_preco + uh + 2 * by],
                            fill=urg_color)
                d.text((badge_x + bx, y_preco + by), arbre.urgence,
                       font=fnt, fill="white")
                y_preco += int(uh) + 2 * by + 12

            if arbre.echeance and y_preco + 26 <= y_limit:
                lbl = "Échéance : "
                lbl_w = d.textbbox((0, 0), lbl, font=f(16, "sans"))[2]
                d.text((txt_x, y_preco), lbl, font=f(16, "sans"), fill=COLOR_MUTED)
                d.text((txt_x + lbl_w, y_preco), arbre.echeance,
                       font=f(16, "sans_bold"), fill=COLOR_INK)
                y_preco += 26

            if arbre.preconisation:
                y_preco = _draw_preco_text(arbre.preconisation, y_preco + 2)
            y_preco += 14

        if has_suivi and y_preco + 32 + 24 <= y_limit:
            y_preco = _preco_header("Suivi", y_preco)

            if arbre.suivi_validite and y_preco + 26 <= y_limit:
                lbl = "Validité : "
                lbl_w = d.textbbox((0, 0), lbl, font=f(16, "sans"))[2]
                d.text((txt_x, y_preco), lbl, font=f(16, "sans"), fill=COLOR_MUTED)
                d.text((txt_x + lbl_w, y_preco), arbre.suivi_validite,
                       font=f(16, "sans_bold"), fill=COLOR_INK)
                y_preco += 26

            if arbre.suivi_texte:
                y_preco = _draw_preco_text(arbre.suivi_texte, y_preco + 2)
            y_preco += 6

    y = max(y_diag, y_preco) + 10

    # --- Photos ---
    photos_valides = [p for p in (arbre.photos or []) if Path(p).exists()]
    if photos_valides and y + 60 < H - 80:
        try:
            from PIL import Image as _PILImage
            d.text((margin, y), _("Photos"), font=f(18, "sans_bold"),
                   fill=COLOR_INK)
            y += 30
            thumb_h = 180
            thumb_gap = 12
            per_row = max(1, (W - 2*margin + thumb_gap) // (thumb_h + thumb_gap))
            for idx, photo_path in enumerate(photos_valides):
                col = idx % per_row
                row = idx // per_row
                xp = margin + col * (thumb_h + thumb_gap)
                yp = y + row * (thumb_h + thumb_gap + 20)
                if yp + thumb_h > H - 80:
                    break
                try:
                    img = _PILImage.open(photo_path).convert("RGB")
                    iw, ih = img.size
                    scale = min(thumb_h / ih, thumb_h / iw)
                    img = img.resize((int(iw*scale), int(ih*scale)),
                                     _PILImage.LANCZOS)
                    page.paste(img, (int(xp), int(yp)))
                    # Nom de fichier sous la vignette
                    fname_lbl = Path(photo_path).name[:28]
                    d.text((xp, yp + img.height + 2), fname_lbl,
                           font=f(11, "sans"), fill=COLOR_MUTED)
                except Exception:
                    pass
        except ImportError:
            pass

    # --- Pied de page ---
    d.line([margin, H-46, W-margin, H-46], fill=COLOR_MUTED, width=1)
    cab_suffix = f"   •   {cabinet_name}" if cabinet_name else ""
    d.text((W/2, H-24),
           f"Pénétromètre{cab_suffix}   •   "
           + _("Édité le") + f" {datetime.now().strftime('%d/%m/%Y à %H:%M')}",
           font=f(14, "sans"), fill=COLOR_MUTED, anchor="mm")
    return page


def _draw_mono_diagnostic(d: "ImageDraw.ImageDraw", f: Any, arbre: "Arbre",
                          x_left: int, x_right: int, R: float, y: float) -> float:
    """Bloc diagnostic d'un genet mono-caule.

    `x_left`/`x_right` délimitent la colonne allouée (permet le rendu côte
    à côte avec la préconisation). Renvoie l'ordonnée après le bloc.
    """
    snap = repartition_classes(arbre)
    diag = snap.diagnostic_global
    if R > 0 and not all(r >= 0.999 for r in snap.ratios):
        if diag is not None:
            tR_moyen_diag, _cls_tmp = diag
            d.text((x_left, y),
                   _("t/R moyen sur le pourtour") + f" : {100*tR_moyen_diag:.1f} %",
                   font=f(18, "sans_bold"), fill=COLOR_INK)
            y += 28
        d.text((x_left, y),
               _("t/R minimal") + f" : {100*snap.tR_min:.1f} %  "
               f"(grade {snap.tR_min_grade} gr — {snap.tR_min_dir})",
               font=f(18, "sans"), fill=COLOR_INK)
        y += 28
        if snap.extrapolation_text:
            d.text((x_left, y), snap.extrapolation_text,
                   font=f(16, "sans"), fill=COLOR_MUTED)
            y += 28
        else:
            y += 4
        if diag is None:
            d.text((x_left, y),
                   "⚠ Diagnostic global indisponible : il faut au moins",
                   font=f(18, "sans_bold"), fill=(176, 0, 32))
            y += 26
            d.text((x_left, y),
                   "2 directions sondées pour extrapoler le pourtour.",
                   font=f(18, "sans_bold"), fill=(176, 0, 32))
            y += 30
        else:
            d.text((x_left, y),
                   "Répartition sur le pourtour (16 directions) :",
                   font=f(18, "sans_bold"), fill=COLOR_INK)
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
            chunks = []
            for cls in ("Vert", "Orange", "Rouge"):
                r = snap.par_classe(cls)
                if r.n > 0:
                    col = COULEUR_CLASSE[cls]
                    chunks.append(
                        (f"{cls} {r.n}/16 ({r.grades} gr)", col))
            if chunks:
                font_chunk = f(17, "sans")
                font_sep = f(17, "sans")
                sep = "   •   "
                sep_w = d.textbbox((0, 0), sep, font=font_sep)[2]
                x_chunk: float = x_left
                for i, (txt, col) in enumerate(chunks):
                    if i > 0:
                        d.text((x_chunk, y), sep,
                               font=font_sep, fill=COLOR_MUTED)
                        x_chunk += sep_w
                    d.text((x_chunk, y), txt,
                           font=font_chunk, fill=col)
                    bbox = d.textbbox((0, 0), txt, font=font_chunk)
                    x_chunk += bbox[2] - bbox[0]
                y += 28
            y += 10
            _tR_tmp, classe_g = diag
            col_g = COULEUR_CLASSE[classe_g]
            box_w, box_h = 460, 60
            d.rectangle([x_left, y, x_left+box_w, y+box_h], fill=col_g)
            d.text((x_left+box_w/2, y+box_h/2),
                   _("Classe globale") + f" : {classe_g}",
                   font=f(24, "sans_bold"), fill="white", anchor="mm")
            y += box_h + 8
    else:
        d.text((x_left, y), _("Aucune altération saisie."),
               font=f(18, "sans"), fill=COLOR_INK)
        y += 28
    return y


def _draw_cepee_diagnostic(d: "ImageDraw.ImageDraw", f: Any, arbre: "Arbre",
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
        d.rectangle([x_left, y, x_left+box_w, y+box_h], fill=col_g)
        d.text((x_left+box_w/2, y+box_h/2),
               _("Classe globale (pire brin)") + f" : {gd.classe_globale}",
               font=f(22, "sans_bold"), fill="white", anchor="mm")
        y += box_h + 16
    else:
        d.text((x_left, y),
               "⚠ Classe globale indisponible : aucun brin avec au moins "
               "3 directions sondées.",
               font=f(18, "sans_bold"), fill=(176, 0, 32))
        y += 36
    d.text((x_left, y), "Détail par brin :",
           font=f(18, "sans_bold"), fill=COLOR_INK)
    y += 32
    for b in arbre.brins:
        lbl = b.label or "?"
        prefix = f"Brin {lbl} :  "
        d.text((x_left, y), prefix, font=f(17, "sans_bold"), fill=COLOR_INK)
        px = x_left + d.textbbox((0, 0), prefix, font=f(17, "sans_bold"))[2]
        if b.rayon_tronc_cm <= 0:
            d.text((px, y), "rayon non renseigné.",
                   font=f(17, "sans"), fill=COLOR_MUTED)
            y += 28
            continue
        snap = repartition_classes_brin(b, port)
        diag = snap.diagnostic_global
        if diag is not None:
            tR_moyen_b, classe_b = diag
            txt = (f"{classe_b}   •   t/R moyen {100*tR_moyen_b:.1f} %"
                   f"   •   t/R min {100*snap.tR_min:.1f} %")
            d.text((px, y), txt, font=f(17, "sans"),
                   fill=COULEUR_CLASSE[classe_b])
        else:
            d.text((px, y),
                   _("non fiable ({n}/16 directions sondées).").format(n=snap.n_sondees),
                   font=f(17, "sans"), fill=COLOR_MUTED)
        y += 28
    return y
