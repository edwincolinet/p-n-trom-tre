"""
Fiche d'expertise PDF — layout d'une page A4 pour un arbre.

Pendant « page A4 » de `pil_render.render_arbre_to_pil_image` : assemble
sur une page portrait 150 DPI l'en-tête mission + logo Silvavenir,
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
from diagnostic import degradation_externe_par_grade, repartition_classes
from geometry import DIRECTION_LABELS, GRADES
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
        logo_path = Path(__file__).parent / "assets" / "silvavenir_logo.jpg"
        if logo_path.exists():
            logo = Image.open(logo_path).convert("RGBA")
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
                                     width=W, height=900, font_fn=f,
                                     show_classes=False)
        y += est_legend_h

    # --- Tableau PRBS ajustée par sondage ---
    if R > 0 and arbre.sondages:
        d.text((margin, y), "Paroi Résiduelle de Bois Sain par sondage",
               font=f(22, "serif_bold"), fill=COLOR_ACCENT)
        y += 36
        deg_ext_par_grade = degradation_externe_par_grade(arbre)
        # Largeurs de colonnes redistribuées : Direction et PRBS plus
        # généreuses (où les valeurs sont les plus longues), Compart.
        # rétrécie (souvent juste « - » ou « active »).
        # Total = 70 + 220 + 270 + 130 + 160 + 270 = 1120 = W - 2*margin.
        col_widths = [70, 220, 270, 130, 160, 270]
        cols_x = [margin]
        for w in col_widths:
            cols_x.append(cols_x[-1] + w)
        # cols_x = [60, 130, 350, 620, 750, 910, 1180]
        headers = ["N°", "Direction", "PRBS (cm)", "t/R (%)",
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
    # `repartition_classes` renvoie un DiagnosticSnapshot self-contained
    # (ratios + extrapolation_text inclus) : pas besoin de rappeler
    # `ratio_tR_par_grade` / `extrapolation_summary_text` ici (chacun
    # repasse par la chaîne compute_alteration_par_grade).
    snap = repartition_classes(arbre)
    # Propriété diagnostic_global : encapsule la règle « publiable
    # seulement si >= 3 sondages ». Tous les exports passent par là.
    diag = snap.diagnostic_global
    if R > 0 and not all(r >= 0.999 for r in snap.ratios):
        # t/R moyen et classe globale ne sont écrits que si le
        # diagnostic est fiable (>= 3 sondages). Sinon on affiche
        # l'avertissement et on saute la barre / l'encadré final.
        if diag is not None:
            tR_moyen_diag, _ = diag
            d.text((margin, y),
                   f"t/R moyen sur le pourtour : "
                   f"{100*tR_moyen_diag:.1f} %",
                   font=f(18, "sans_bold"), fill=COLOR_INK)
            y += 28
        d.text((margin, y),
               f"t/R minimal : {100*snap.tR_min:.1f} %  "
               f"(grade {snap.tR_min_grade} gr — {snap.tR_min_dir})",
               font=f(18, "sans"), fill=COLOR_INK)
        y += 28
        if snap.extrapolation_text:
            d.text((margin, y), snap.extrapolation_text,
                   font=f(16, "sans"), fill=COLOR_MUTED)
            y += 28
        else:
            y += 4
        if diag is None:
            # Avertissement en rouge sombre, en lieu et place de la
            # barre de répartition et de l'encadré classe globale.
            d.text((margin, y),
                   "⚠ Diagnostic global indisponible : il faut au moins",
                   font=f(18, "sans_bold"), fill=(176, 0, 32))
            y += 26
            d.text((margin, y),
                   "2 directions sondées pour extrapoler le pourtour.",
                   font=f(18, "sans_bold"), fill=(176, 0, 32))
            y += 30
        else:
            d.text((margin, y),
                   "Répartition sur le pourtour (16 directions) :",
                   font=f(18, "sans_bold"), fill=COLOR_INK)
            y += 30
            # Barre horizontale empilée Vert/Orange/Rouge — plus haute
            # pour que le pourcentage soit lisible même sur des segments
            # étroits.
            bar_w = W - 2*margin
            bar_h = 36
            x_cur: float = margin
            # Petites étiquettes hors-barre pour les segments trop étroits
            # pour porter leur texte à l'intérieur.
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
            # Détail textuel — sur UNE seule ligne pour économiser
            # l'espace. On n'affiche que les classes non vides, séparées
            # par " • ", et chaque libellé est rendu dans la couleur de
            # sa classe.
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
                x_chunk: float = margin
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
            # Gros marqueur coloré pour la classe globale (basée sur
            # t/R moyen). Boîte plus large et plus haute pour rester
            # proportionnée aux autres éléments de la page. On est
            # dans le `else` d'un `if diag is None` ; donc diag est
            # non-None.
            _, classe_g = diag
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
