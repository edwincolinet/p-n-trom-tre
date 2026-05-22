"""
Exports stylés du tableau PRBS d'un arbre.

Deux formats au choix :
- `export_prbs_xlsx`  : fichier .xlsx avec mise en forme (en-têtes
  colorés, cellule t/R color-codée par classe, bordures, gel de lignes,
  largeurs ajustées). Nécessite openpyxl.
- `export_prbs_html`  : fichier .html autonome (CSS embarqué). Aucune
  dépendance — ouvrable dans n'importe quel navigateur, imprimable en
  PDF via le navigateur.

Le tableau exporté est calqué sur la fiche Excel d'origine du cabinet
Silvavenir (`docs/tableau souhaité.png`) :
- Une ligne d'en-tête « méta arbre » (N° arbre, Hauteur sondage,
  Diamètre sous écorce, Hauteur de l'arbre).
- L'en-tête des colonnes.
- UNE LIGNE PAR SONDAGE (Sondage, Zone sondée, Rayon, Bois sain, Bois
  altéré, Compartimentation ✓/✗, t/R coloré).
- Une ligne de légende ✓ = Compartimentation active, ✗ = absente.

Les fonctions reçoivent les objets `arbre` / `chantier` via des
`Protocol` structurels (`ArbreLike`, `ChantierLike`, `SondageLike`)
plutôt que par import direct depuis `model.py` : ça garde le module
autonome (utile pour le tester avec des stubs) tout en donnant à
mypy la surface attendue. Le dict `couleur_classe` (label → hex) et
la fonction `classer_prbs` sont injectés depuis l'UI (palette /
bareme), eux aussi par paramètre pour éviter une dépendance forte.
"""

from __future__ import annotations

import html as html_lib
from datetime import datetime
from typing import Any, Callable, List, Mapping, Protocol, Sequence, Tuple

from geometry import GRADES

try:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False


# ----------------------------------------------------------------------
# Protocols : surface attendue des objets métier passés en paramètre.
# Évite un import direct vers `model.py` (qui marcherait, mais qui
# rendrait `export.py` dépendant du modèle Silvavenir ; les protocols
# le rendent réutilisable avec n'importe quel objet qui exposerait la
# même surface, et donnent à mypy le contrat à vérifier côté caller).
# ----------------------------------------------------------------------

class SondageLike(Protocol):
    numero: int
    grade: int
    bois_altere_cm: float
    compartimentation: str
    commentaire: str

    @property
    def prbs_cm(self) -> float: ...


class ArbreLike(Protocol):
    rayon_tronc_cm: float
    port_arbre: str
    numero_arbre: str
    essence: str
    hauteur_sondage_cm: float
    diametre_sous_ecorce_cm: float
    hauteur_arbre_m: float

    # `sondages` est exposé en lecture seule via `@property` pour autoriser
    # la covariance : un `Arbre` concret avec `sondages: List[Sondage]`
    # satisfait alors le Protocol sans warning de variance (un attribut
    # mutable obligerait `Sondage` et `SondageLike` à être strictement
    # le même type).
    @property
    def sondages(self) -> Sequence[SondageLike]: ...

    def ratio_tR_par_grade(self) -> List[float]: ...


class ChantierLike(Protocol):
    nom: str
    adresse: str
    operateur: str
    date_releve: str


# Signature attendue de `classer_prbs` (cf. bareme.py). Injectée par
# l'appelant pour éviter d'importer bareme.py ici.
ClasserPrbs = Callable[[float, str], str]


# ----------------------------------------------------------------------
# Données : une ligne par sondage
# ----------------------------------------------------------------------

def prbs_table_rows_par_sondage(arbre: ArbreLike,
                                 classer_prbs: ClasserPrbs
                                 ) -> List[dict]:
    """Construit la liste des entrées prêtes à être rendues, une par
    sondage, triées par numéro de sondage (ordre de saisie).

    `classer_prbs` est passée en paramètre pour éviter d'importer
    bareme.py ici (export.py reste autonome).

    Chaque entrée :
    - `numero` (int)
    - `grade` (int 0..375)
    - `rayon_cm` (float, identique pour toutes les lignes)
    - `prbs_cm` (float, PRBS brute mesurée par le sondage)
    - `bois_altere_cm` (float)
    - `compartimentation` (str: "active" | "absente" | "-")
    - `ratio_tR` (float, 0..1, ajusté de la dégradation externe →
      cohérent avec la pastille colorée sur le dessin)
    - `classe` (str: Vert/Orange/Rouge)
    - `commentaire` (str)
    """
    R = arbre.rayon_tronc_cm
    # `ratio_tR_par_grade()` retire la dégradation externe avant le
    # ratio → on prend la même valeur que celle affichée par la
    # pastille du sondage sur le dessin (cf. CLAUDE.md « Pastille du
    # sondage = PRBS ajustée »).
    ratios_par_grade = arbre.ratio_tR_par_grade()
    rows: List[dict] = []
    for s in sorted(arbre.sondages, key=lambda x: x.numero):
        try:
            idx = GRADES.index(s.grade)
            ratio = ratios_par_grade[idx]
        except ValueError:
            ratio = 0.0
        rows.append({
            "numero": s.numero,
            "grade": s.grade,
            "rayon_cm": R,
            "prbs_cm": s.prbs_cm,
            "bois_altere_cm": s.bois_altere_cm,
            "compartimentation": s.compartimentation or "-",
            "ratio_tR": ratio,
            "classe": classer_prbs(ratio, arbre.port_arbre),
            "commentaire": s.commentaire,
        })
    return rows


# ----------------------------------------------------------------------
# Helpers présentation
# ----------------------------------------------------------------------

# Glyphes & couleurs pour la colonne « Compartimentation »
_COMPART_GLYPH = {
    "active":  ("✓", "2D7A3E"),
    "absente": ("✗", "C0392B"),
}
_COMPART_NEUTRE = ("—", "6E7B73")


def _compart_visual(value: str) -> Tuple[str, str]:
    """(glyphe, couleur_hex_sans_diese) selon la valeur saisie."""
    return _COMPART_GLYPH.get((value or "").lower().strip(),
                              _COMPART_NEUTRE)


def _value_or_dash(value: Any, unit: str = "") -> str:
    """Formate une valeur métier en remplaçant le vide/0 par « — »."""
    if value in (None, "", 0, 0.0):
        return "—"
    if isinstance(value, (int, float)):
        return f"{value:g}{(' ' + unit) if unit else ''}"
    return str(value) + ((" " + unit) if unit else "")


def _meta_fields(arbre: ArbreLike) -> List[Tuple[str, str]]:
    """4 (label, valeur) de la ligne méta-arbre au-dessus du tableau.

    Calqué sur la fiche Excel d'origine : N° arbre / Hauteur sondage /
    Diamètre sondage sous écorce / Hauteur de l'arbre.
    """
    return [
        ("N° arbre", _value_or_dash(arbre.numero_arbre)),
        ("Hauteur sondage", _value_or_dash(arbre.hauteur_sondage_cm, "cm")),
        ("Diamètre sondage sous écorce",
         _value_or_dash(arbre.diametre_sous_ecorce_cm, "cm")),
        ("Hauteur", _value_or_dash(arbre.hauteur_arbre_m, "m")),
    ]


# ----------------------------------------------------------------------
# Export XLSX
# ----------------------------------------------------------------------

# En-têtes du tableau (ordre des colonnes), calqués sur la fiche Excel
# d'origine du cabinet Silvavenir.
_HEADERS = [
    "Sondage",
    "Zone sondée\n(Grades)",
    "Rayon du tronc\nsous écorce (cm)",
    "Épaisseur bois sain\n(cm)",
    "Épaisseur bois altéré\n(cm)",
    "Compartimentation",
    "Proportion de bois sain\nsur le rayon (%)",
]
_NCOLS = len(_HEADERS)

# Découpe en colonnes de la ligne méta (chaque méta couvre 1 ou 2
# colonnes du tableau, total = 7).
_META_SPANS = [1, 2, 2, 2]


def export_prbs_xlsx(arbre: ArbreLike, chantier: ChantierLike, path: str,
                     couleur_classe: Mapping[str, str],
                     classer_prbs: ClasserPrbs) -> None:
    """Écrit le tableau PRBS dans `path` (.xlsx). `couleur_classe` est
    le dict label → hex injecté depuis la couche UI."""
    if not HAS_OPENPYXL:
        raise RuntimeError(
            "openpyxl n'est pas installé. Lancer "
            "`pip install -r requirements.txt`.")

    wb = Workbook()
    ws = wb.active
    ws.title = "PRBS"

    BORDER = Border(
        left=Side(style="thin", color="999999"),
        right=Side(style="thin", color="999999"),
        top=Side(style="thin", color="999999"),
        bottom=Side(style="thin", color="999999"),
    )
    HEADER_FILL = PatternFill("solid", fgColor="EFEFEF")
    HEADER_FONT = Font(name="Calibri", size=11, bold=True, color="1A2E22")
    META_FONT = Font(name="Calibri", size=11, color="1A2E22")
    TITLE_FONT = Font(name="Calibri", size=16, bold=True, color="2D7A3E")
    SUBTITLE_FONT = Font(name="Calibri", size=10, color="6E7B73")
    ROW_FONT = Font(name="Calibri", size=11, color="1A2E22")
    LEGEND_FONT = Font(name="Calibri", size=10, italic=True,
                       color="6E7B73")

    LEFT = Alignment(horizontal="left", vertical="center",
                     wrap_text=True, indent=1)
    CENTER = Alignment(horizontal="center", vertical="center",
                       wrap_text=True)

    last = _NCOLS

    # --- Titre + sous-titre mission ---
    row = 1
    ws.cell(row=row, column=1,
            value=f"Pénétromètre — {chantier.nom or 'Mission'}").font = \
        TITLE_FONT
    ws.merge_cells(start_row=row, start_column=1,
                   end_row=row, end_column=last)
    row += 1
    subtitle_parts = []
    if chantier.adresse:
        subtitle_parts.append(chantier.adresse)
    if chantier.operateur:
        subtitle_parts.append(f"Opérateur : {chantier.operateur}")
    subtitle_parts.append(f"Relevé du {chantier.date_releve or '—'}")
    if arbre.essence:
        subtitle_parts.append(f"Essence : {arbre.essence}")
    if arbre.port_arbre:
        subtitle_parts.append(f"Port : {arbre.port_arbre}")
    ws.cell(row=row, column=1,
            value=" • ".join(subtitle_parts)).font = SUBTITLE_FONT
    ws.merge_cells(start_row=row, start_column=1,
                   end_row=row, end_column=last)
    row += 2  # ligne vide

    # --- Ligne méta arbre (4 cellules réparties sur 7 colonnes) ---
    meta_row = row
    col = 1
    for (label, value), span in zip(_meta_fields(arbre), _META_SPANS):
        c = ws.cell(row=meta_row, column=col,
                    value=f"{label} :  {value}")
        c.font = META_FONT
        c.alignment = LEFT
        c.border = BORDER
        if span > 1:
            ws.merge_cells(start_row=meta_row, start_column=col,
                           end_row=meta_row, end_column=col + span - 1)
            # Bordure visible sur toutes les cellules fusionnées
            for k in range(span):
                ws.cell(row=meta_row, column=col + k).border = BORDER
        col += span
    ws.row_dimensions[meta_row].height = 26
    row += 1

    # --- En-tête tableau ---
    header_row = row
    for i, h in enumerate(_HEADERS, start=1):
        c = ws.cell(row=header_row, column=i, value=h)
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
        c.alignment = CENTER
        c.border = BORDER
    ws.row_dimensions[header_row].height = 44
    row += 1

    # --- Une ligne par sondage ---
    rows_data = prbs_table_rows_par_sondage(arbre, classer_prbs)
    if not rows_data:
        c_empty = ws.cell(row=row, column=1,
                          value="Aucun sondage enregistré.")
        c_empty.font = Font(name="Calibri", size=10, italic=True,
                            color="6E7B73")
        c_empty.alignment = LEFT
        c_empty.border = BORDER
        ws.merge_cells(start_row=row, start_column=1,
                       end_row=row, end_column=last)
        for k in range(last):
            ws.cell(row=row, column=k + 1).border = BORDER
        row += 1
    classe_col = _NCOLS  # colonne t/R = fond coloré par classe
    compart_col = 6      # colonne Compartimentation = glyphe coloré
    for r in rows_data:
        values = [
            r["numero"],
            r["grade"],
            round(r["rayon_cm"], 2),
            round(r["prbs_cm"], 2),
            round(r["bois_altere_cm"], 2),
            None,                          # rempli ci-dessous
            round(100 * r["ratio_tR"], 1),
        ]
        classe_hex = couleur_classe.get(r["classe"], "CCCCCC").lstrip("#")
        glyph, glyph_hex = _compart_visual(r["compartimentation"])
        for i, v in enumerate(values, start=1):
            c = ws.cell(row=row, column=i)
            c.border = BORDER
            c.font = ROW_FONT
            c.alignment = CENTER
            if i == compart_col:
                c.value = glyph
                c.font = Font(name="Calibri", size=14, bold=True,
                              color=glyph_hex)
            elif i == classe_col:
                c.value = v
                c.fill = PatternFill("solid", fgColor=classe_hex)
                c.font = Font(name="Calibri", size=11, bold=True,
                              color="FFFFFF")
            else:
                c.value = v
        ws.row_dimensions[row].height = 24
        row += 1

    # --- Ligne légende sous le tableau ---
    row += 1
    legend_row = row
    # Légende : | "Légende :" | ✓ | "Compartimentation active" | ✗ |
    # "Pas de compartimentation" | (rien) | (rien) |
    legend_cells = [
        ("Légende :", LEGEND_FONT, None),
        ("✓", Font(name="Calibri", size=14, bold=True,
                    color=_COMPART_GLYPH["active"][1]), None),
        ("Compartimentation active", LEGEND_FONT, None),
        ("✗", Font(name="Calibri", size=14, bold=True,
                    color=_COMPART_GLYPH["absente"][1]), None),
        ("Pas de compartimentation", LEGEND_FONT, None),
    ]
    for i, (value, font, _) in enumerate(legend_cells, start=1):
        c = ws.cell(row=legend_row, column=i, value=value)
        c.font = font
        c.alignment = CENTER if value in ("✓", "✗") else LEFT
        c.border = BORDER
    # Bordures sur les colonnes 6-7 même si vides
    for k in (6, 7):
        ws.cell(row=legend_row, column=k).border = BORDER
    ws.row_dimensions[legend_row].height = 24
    row += 2

    # --- Pied : édition + signature ---
    ws.cell(row=row, column=1,
            value=f"Édité le {datetime.now().strftime('%d/%m/%Y à %H:%M')} "
                  "— Pénétromètre, Silvavenir Foresterie urbaine").font = \
        Font(name="Calibri", size=9, italic=True, color="6E7B73")
    ws.merge_cells(start_row=row, start_column=1,
                   end_row=row, end_column=last)

    # --- Largeurs de colonnes ---
    # NB : on n'utilise PAS `ws.cell(row=1, column=i).column_letter` ici,
    # car la ligne 1 contient une cellule fusionnée et toutes les
    # cellules au-delà de A1 sont des `MergedCell` qui n'ont pas
    # `column_letter`. `get_column_letter` est la bonne API.
    widths = [11, 14, 16, 16, 16, 18, 18]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # Gel : tout l'en-tête (titre + méta + en-tête tableau)
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)

    wb.save(path)


# ----------------------------------------------------------------------
# Export HTML
# ----------------------------------------------------------------------

_HTML_CSS = """
* { box-sizing: border-box; }
body {
    font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
    color: #1A2E22;
    background: #F7F3EA;
    margin: 0;
    padding: 28px 36px;
}
h1 { font-size: 22px; color: #2D7A3E; margin: 0 0 4px 0; }
.meta-mission { color: #6E7B73; font-size: 13px; margin-bottom: 18px; }
table {
    border-collapse: collapse; width: 100%; margin-top: 6px;
    background: #FFFFFF; font-size: 13px;
    border: 1px solid #999999;
}
table th, table td {
    border: 1px solid #999999;
    padding: 6px 10px;
}
.meta-cell {
    background: #FFFFFF;
    font-weight: 600;
    text-align: left;
}
.meta-cell .meta-label { color: #6E7B73; font-weight: 600; }
.meta-cell .meta-value { color: #1A2E22; font-weight: 700;
                          margin-left: 4px; }
thead th {
    background: #EFEFEF; color: #1A2E22;
    text-align: center; font-weight: 700; font-size: 12px;
    line-height: 1.2;
}
tbody td { text-align: center; font-variant-numeric: tabular-nums; }
td.tR {
    font-weight: 700; color: white;
    text-shadow: 0 1px 1px rgba(0,0,0,0.2);
}
td.compart-active { color: #2D7A3E; font-size: 18px; font-weight: 700; }
td.compart-absente { color: #C0392B; font-size: 18px; font-weight: 700; }
td.compart-neutre { color: #6E7B73; }
.legend-cell { background: #FFFFFF; text-align: center; }
.legend-label { font-style: italic; color: #6E7B73; text-align: left; }
.empty-row td { color: #6E7B73; font-style: italic; text-align: left; }
footer {
    margin-top: 28px; color: #6E7B73; font-size: 11px;
    font-style: italic;
}
@media print {
    body { background: white; padding: 12mm; }
    table { box-shadow: none; }
    thead { display: table-header-group; }
}
"""


def _h(s: object) -> str:
    """Échappe pour HTML."""
    return html_lib.escape(str(s), quote=True)


def export_prbs_html(arbre: ArbreLike, chantier: ChantierLike, path: str,
                     couleur_classe: Mapping[str, str],
                     classer_prbs: ClasserPrbs) -> None:
    """Écrit le tableau PRBS dans `path` (.html). Aucun fichier externe :
    le CSS est embarqué."""
    rows_data = prbs_table_rows_par_sondage(arbre, classer_prbs)
    title = (f"Pénétromètre — {chantier.nom or 'Mission'} — "
             f"{arbre.numero_arbre or ''}")

    # En-tête mission
    meta_chunks = []
    if chantier.adresse:
        meta_chunks.append(_h(chantier.adresse))
    if chantier.operateur:
        meta_chunks.append(f"Opérateur : {_h(chantier.operateur)}")
    meta_chunks.append(f"Relevé du {_h(chantier.date_releve or '—')}")
    if arbre.essence:
        meta_chunks.append(f"Essence : {_h(arbre.essence)}")
    if arbre.port_arbre:
        meta_chunks.append(f"Port : {_h(arbre.port_arbre)}")
    meta_html = " • ".join(meta_chunks)

    # Ligne méta arbre (4 cellules, colspans 1/2/2/2)
    meta_cells_html = "".join(
        f'<td class="meta-cell" colspan="{span}">'
        f'<span class="meta-label">{_h(label)} :</span>'
        f'<span class="meta-value">{_h(value)}</span>'
        f'</td>'
        for (label, value), span in zip(_meta_fields(arbre), _META_SPANS))

    headers_html = "".join(
        f'<th>{_h(h).replace(chr(10), "<br>")}</th>' for h in _HEADERS)

    # Données
    if not rows_data:
        body_html = (
            f'<tr class="empty-row"><td colspan="{_NCOLS}">'
            'Aucun sondage enregistré.</td></tr>')
    else:
        body_rows = []
        for r in rows_data:
            classe_color = couleur_classe.get(r["classe"], "#CCCCCC")
            comp = (r["compartimentation"] or "").lower().strip()
            if comp == "active":
                comp_html = '<td class="compart-active">✓</td>'
            elif comp == "absente":
                comp_html = '<td class="compart-absente">✗</td>'
            else:
                comp_html = '<td class="compart-neutre">—</td>'
            body_rows.append(
                "<tr>"
                f'<td>{r["numero"]}</td>'
                f'<td>{r["grade"]}</td>'
                f'<td>{round(r["rayon_cm"], 2):g}</td>'
                f'<td>{round(r["prbs_cm"], 2):g}</td>'
                f'<td>{round(r["bois_altere_cm"], 2):g}</td>'
                f'{comp_html}'
                f'<td class="tR" style="background:{classe_color}">'
                f'{100*r["ratio_tR"]:.1f}</td>'
                "</tr>"
            )
        body_html = "\n".join(body_rows)

    # Légende sous le tableau (mêmes colonnes que le tableau)
    legend_html = (
        '<tr>'
        '<td class="legend-label">Légende :</td>'
        '<td class="legend-cell compart-active">✓</td>'
        '<td class="legend-cell legend-label" colspan="2">'
        'Compartimentation active</td>'
        '<td class="legend-cell compart-absente">✗</td>'
        '<td class="legend-cell legend-label" colspan="2">'
        'Pas de compartimentation</td>'
        '</tr>'
    )

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>{_h(title)}</title>
<style>{_HTML_CSS}</style>
</head>
<body>
<h1>{_h('Pénétromètre — ' + (chantier.nom or 'Mission'))}</h1>
<div class="meta-mission">{meta_html}</div>

<table>
<thead>
<tr>{meta_cells_html}</tr>
<tr>{headers_html}</tr>
</thead>
<tbody>
{body_html}
{legend_html}
</tbody>
</table>

<footer>
Édité le {datetime.now().strftime('%d/%m/%Y à %H:%M')} — Pénétromètre, Silvavenir Foresterie urbaine.
</footer>
</body>
</html>
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
