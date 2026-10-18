"""Synthèse de mission (tableau de hiérarchisation du risque).

Extrait de `export.py` (2026-08-25) : une ligne par arbre plutôt qu'une
ligne par sondage — sous-domaine distinct de l'export PRBS par arbre,
qui ne partage avec lui que deux helpers réutilisés tels quels
(`ChantierLike`, `_defuse` — la neutralisation d'injection de formule
tableur, cf. leur définition dans `export.py`, vaut pour tout champ
texte libre de mission, pas seulement le tableau PRBS).

Source des données : `diagnostic.mission_synthesis_rows(chantier)` —
calculé par l'appelant et passé en paramètre (`Sequence[MissionSynthesisRow]`),
pour garder ce module purement « formatage » et testable avec des
stubs. Le masquage des champs non fiables (< 3 sondages) est déjà
appliqué en amont (champs `None`) ; ici on ne fait que présenter.
"""

from __future__ import annotations

import csv
from typing import TYPE_CHECKING, Mapping, Sequence

from export import ChantierLike, _defuse
from i18n import _

if TYPE_CHECKING:
    from diagnostic import MissionSynthesisRow  # noqa: F401

try:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False


_SYNTH_HEADERS = ["N°", "Essence", "Port", "Sondages", "Rayon (cm)",
                  "Classe (t/R minimal)", "Direction critique",
                  "t/R minimal (%)", "Urgence", "Échéance", "Préconisation",
                  "Validité suivi", "Échéance suivi", "Commentaire suivi"]

# Cellule « Urgence » : NEUTRE (fond Sous-couche, encre). Charte SILVAVENIR :
# le délai est une donnée d'échéance, pas un niveau de risque — seule la
# colonne Classe porte la gravité (couleur).
_URGENCE_NEUTRE = ("F4F2EC", "404040")


def _synth_classe_text(row: "MissionSynthesisRow") -> str:
    """Texte de la colonne « Classe (t/R minimal) ». Distingue les 3 cas :
    classe publiée (Vert/Orange/Rouge), arbre sondé mais non fiable
    (1-2 sondages → « Non fiable »), ou non renseigné (« — »)."""
    if row.classe_globale is not None:
        return row.classe_globale
    if row.n_sondees > 0 and row.rayon_cm > 0:
        return _("Non fiable")
    return "—"


def _synth_crit_text(row: "MissionSynthesisRow") -> str:
    if row.crit_grade is None:
        return "—"
    if row.crit_dir:
        return f"{row.crit_dir} ({row.crit_grade} gr)"
    return f"{row.crit_grade} gr"


def _synth_pct_text(v: object) -> str:
    return f"{v:.1f}" if isinstance(v, (int, float)) else "—"


def _synth_or_dash(s: str) -> str:
    """Texte d'un champ de préconisation, « — » si vide (ou sous-ligne de
    brin où la préconisation n'est pas répétée)."""
    return s if s else "—"


def export_synthesis_csv(rows: "Sequence[MissionSynthesisRow]",
                         path: str, bareme_desc: str = "") -> None:
    """Synthèse mission en CSV (séparateur `;`, UTF-8 BOM compatible
    Excel). Une ligne par arbre.

    `bareme_desc` : seuils ayant produit les classes, écrits en ligne de
    commentaire avant l'en-tête — sans quoi le fichier ne permet pas de
    reproduire ses propres classes."""
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        if bareme_desc:
            w.writerow([f"# Barème appliqué : {bareme_desc}"])
        w.writerow([_(h) for h in _SYNTH_HEADERS])
        for r in rows:
            # Sous-ligne de brin (cépée) : N° décalé « ↳ brin a », identité
            # genet laissée vide (déjà sur la ligne de tête).
            if r.brin_label:
                num: object = f"↳ brin {r.brin_label}"
                ess, port = "", ""
            else:
                num, ess, port = r.numero, r.essence, r.port
            w.writerow([_defuse(v) for v in [
                num, ess, port, r.n_sondees,
                f"{r.rayon_cm:g}",
                _synth_classe_text(r),
                _synth_crit_text(r),
                _synth_pct_text(r.tR_min_pct),
                _synth_or_dash(r.urgence),
                _synth_or_dash(r.echeance),
                _synth_or_dash(r.preconisation),
                _synth_or_dash(r.suivi_validite),
                _synth_or_dash(r.suivi_echeance),
                _synth_or_dash(r.suivi_texte),
            ]])


def export_synthesis_xlsx(rows: "Sequence[MissionSynthesisRow]",
                          chantier: ChantierLike, path: str,
                          couleur_classe: Mapping[str, str],
                          bareme_desc: str = "") -> None:
    """Synthèse mission en .xlsx thémé Pénétromètre Silvavenir : une ligne par arbre,
    cellule « Classe (t/R minimal) » colorée, autofiltre (tri par n'importe
    quelle colonne — p.ex. trier par classe = priorités d'intervention),
    en-tête gelé, ligne de bilan en pied."""
    if not HAS_OPENPYXL:
        raise RuntimeError(
            "openpyxl n'est pas installé. Lancer "
            "`pip install -r requirements.txt`.")

    wb = Workbook()
    ws = wb.active
    ws.title = _("Synthèse")

    BORDER = Border(
        left=Side(style="thin", color="D9D7CF"),
        right=Side(style="thin", color="D9D7CF"),
        top=Side(style="thin", color="D9D7CF"),
        bottom=Side(style="thin", color="D9D7CF"),
    )
    HEADER_FILL = PatternFill("solid", fgColor="385623")
    HEADER_FONT = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    TITLE_FONT = Font(name="Century Gothic", size=14, bold=True,
                      color="F58101")
    SUBTITLE_FONT = Font(name="Segoe UI", size=10, color="595959")
    ROW_FONT = Font(name="Segoe UI", size=11, color="404040")
    ALT_ROW_FILL = PatternFill("solid", fgColor="F4F2EC")
    MUTED_FILL = PatternFill("solid", fgColor="E0E0E0")
    FOOTER_FONT = Font(name="Segoe UI", size=10, italic=True, color="595959")
    CENTER = Alignment(horizontal="center", vertical="center",
                       wrap_text=True)
    LEFT = Alignment(horizontal="left", vertical="center", wrap_text=True)

    last = len(_SYNTH_HEADERS)

    # --- Titre + sous-titre mission ---
    ws.cell(row=1, column=1,
            value=_defuse(_(
                "Pénétromètre Silvavenir — Synthèse mission « {nom} »"
            ).format(nom=chantier.nom or _("Mission")))
            ).font = TITLE_FONT
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=last)
    subtitle_parts = []
    if chantier.client:
        subtitle_parts.append(_("Client") + f" : {chantier.client}")
    if chantier.adresse:
        subtitle_parts.append(chantier.adresse)
    if chantier.operateur:
        subtitle_parts.append(_("Opérateur") + f" : {chantier.operateur}")
    subtitle_parts.append(_("Relevé du") + f" {chantier.date_releve or '—'}")
    ws.cell(row=2, column=1,
            value=_defuse(" • ".join(subtitle_parts))).font = SUBTITLE_FONT
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=last)

    # --- En-tête tableau ---
    header_row = 4
    for i, h in enumerate(_SYNTH_HEADERS, start=1):
        c = ws.cell(row=header_row, column=i, value=_(h))
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
        c.alignment = CENTER
        c.border = BORDER
    ws.row_dimensions[header_row].height = 30

    # --- Une ligne par arbre ---
    classe_col = 6  # colonne « Classe (t/R minimal) » → fond coloré
    r_idx = header_row
    for k, row in enumerate(rows):
        r_idx += 1
        classe_txt = _synth_classe_text(row)
        # Sous-ligne de brin (cépée) : N° décalé, identité genet vide.
        if row.brin_label:
            num: object = f"↳ brin {row.brin_label}"
            ess, prt = "", ""
        else:
            num, ess, prt = row.numero, row.essence, row.port
        values = [
            num, ess, prt, row.n_sondees,
            f"{row.rayon_cm:g}",
            classe_txt,
            _synth_crit_text(row),
            _synth_pct_text(row.tR_min_pct),
            _synth_or_dash(row.urgence),
            _synth_or_dash(row.echeance),
            _synth_or_dash(row.preconisation),
            _synth_or_dash(row.suivi_validite),
            _synth_or_dash(row.suivi_echeance),
            _synth_or_dash(row.suivi_texte),
        ]
        values = [_defuse(v) for v in values]
        urgence_col = 10
        preco_col = 12
        suivi_texte_col = 15
        use_alt = k % 2 == 1
        for i, v in enumerate(values, start=1):
            c = ws.cell(row=r_idx, column=i, value=v)
            c.border = BORDER
            c.font = ROW_FONT
            c.alignment = LEFT if i in (2, preco_col, suivi_texte_col) else CENTER
            if i == classe_col:
                hexa = couleur_classe.get(classe_txt, "").lstrip("#")
                if hexa:
                    c.fill = PatternFill("solid", fgColor=hexa)
                    c.font = Font(name="Segoe UI", size=11, bold=True,
                                  color="FFFFFF")
                else:
                    c.fill = MUTED_FILL
            elif i == urgence_col and row.urgence:
                fill_hex, font_hex = _URGENCE_NEUTRE
                c.fill = PatternFill("solid", fgColor=fill_hex)
                c.font = Font(name="Segoe UI", size=11, bold=True,
                              color=font_hex)
            elif use_alt:
                c.fill = ALT_ROW_FILL
        ws.row_dimensions[r_idx].height = 22

    last_data_row = r_idx if rows else header_row

    # Autofiltre + gel de l'en-tête (tri par classe = hiérarchisation).
    ws.auto_filter.ref = (f"{get_column_letter(1)}{header_row}:"
                          f"{get_column_letter(last)}{last_data_row}")
    ws.freeze_panes = f"A{header_row + 1}"

    # --- Ligne de bilan (ne compte que les genets, pas les sous-lignes
    # de brin d'une cépée). ---
    genets = [r for r in rows if not r.brin_label]
    n_total = len(genets)
    n_fiable = sum(1 for r in genets if r.fiable)
    n_v = sum(1 for r in genets if r.classe_globale == "Vert")
    n_o = sum(1 for r in genets if r.classe_globale == "Orange")
    n_r = sum(1 for r in genets if r.classe_globale == "Rouge")
    footer_row = last_data_row + 2
    ws.cell(row=footer_row, column=1,
            value=(f"{n_total} arbre(s)  •  {n_fiable} diagnostic(s) fiable(s)"
                   f"  •  Vert : {n_v}   Orange : {n_o}   Rouge : {n_r}")
            ).font = FOOTER_FONT
    ws.merge_cells(start_row=footer_row, start_column=1,
                   end_row=footer_row, end_column=last)

    # --- Barème appliqué : la colonne « Classe (t/R minimal) » n'est
    # interprétable qu'avec ses seuils (réglage de poste). ---
    if bareme_desc:
        bareme_row = footer_row + 1
        ws.cell(row=bareme_row, column=1,
                value=f"Barème appliqué : {bareme_desc}").font = FOOTER_FONT
        ws.merge_cells(start_row=bareme_row, start_column=1,
                       end_row=bareme_row, end_column=last)

    # --- Largeurs de colonnes ---
    widths = [6, 18, 13, 10, 11, 15, 20, 14, 20, 12, 40, 14, 12, 40]
    for i, wdt in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = wdt

    wb.save(path)
