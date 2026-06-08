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

import csv
import html as html_lib
from datetime import datetime
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    List,
    Mapping,
    Protocol,
    Sequence,
    Tuple,
    cast,
)

from diagnostic import ratio_tR_par_grade as _diag_ratio_tR_par_grade
from geometry import GRADES

if TYPE_CHECKING:
    from diagnostic import MissionSynthesisRow  # noqa: F401
    from model import Arbre  # noqa: F401  (forward-ref pour `cast()`)

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


class BrinLike(Protocol):
    """Surface d'un brin (ramet) pour le tableau PRBS par brin."""
    rayon_tronc_cm: float
    label: str

    @property
    def sondages(self) -> Sequence[SondageLike]: ...


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

    # Brins (ramets) du genet : ≥ 1. Le tableau PRBS itère les brins pour
    # une cépée (N° de sondage préfixé par le label « a1 », « b2 »).
    @property
    def brins(self) -> Sequence[BrinLike]: ...

    # `ratio_tR_par_grade` n'est plus une méthode d'`Arbre` (extraite
    # dans `diagnostic.py` sous forme de fonction pure). Le Protocol
    # local n'expose plus que les champs accédés directement par
    # `export.py` ; la fonction passe par `_diag_ratio_tR_par_grade`
    # avec un `cast()` au point d'appel pour bridger ArbreLike → Arbre.


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
    - `compartimentation` (str: "active" | "absente" | "non renseignée")
    - `ratio_tR` (float, 0..1, ajusté de la dégradation externe →
      cohérent avec la pastille colorée sur le dessin)
    - `classe` (str: Vert/Orange/Rouge)
    - `commentaire` (str)
    """
    # Itère les brins (ramets) : une cépée a un tableau combiné où le N° de
    # sondage est préfixé par le label du brin (« a1 », « b2 »). Un genet
    # mono-caule (ou un stub sans `brins`) garde un N° simple. Chaque brin a
    # son propre rayon et ses propres dégradations externes ; le port est
    # genet-level.
    brins = list(getattr(arbre, "brins", []) or [])
    multi = len(brins) > 1
    rows: List[dict] = []
    if not brins:
        # Stub ArbreLike sans `brins` : comportement mono historique.
        rows.extend(_brin_table_rows(arbre, arbre.rayon_tronc_cm,
                                     arbre.port_arbre, "", False,
                                     classer_prbs))
        return rows
    for b in brins:
        if b.rayon_tronc_cm <= 0:
            continue
        rows.extend(_brin_table_rows(b, b.rayon_tronc_cm, arbre.port_arbre,
                                     b.label, multi, classer_prbs))
    return rows


def _brin_table_rows(section: Any, R: float, port: str, label: str,
                     multi: bool, classer_prbs: ClasserPrbs) -> List[dict]:
    """Lignes PRBS d'UNE section (brin). `multi` préfixe le N° par le label.

    `diagnostic.ratio_tR_par_grade` retire la dégradation externe avant le
    ratio → même valeur que la pastille du sondage sur le dessin
    (cf. CLAUDE.md « Pastille du sondage = PRBS ajustée »). Le `cast` bridge
    structurellement vers la surface `Section` du module diagnostic."""
    ratios_par_grade = _diag_ratio_tR_par_grade(cast("Arbre", section))
    rows: List[dict] = []
    for s in sorted(section.sondages, key=lambda x: x.numero):
        try:
            idx = GRADES.index(s.grade)
            ratio = ratios_par_grade[idx]
        except ValueError:
            ratio = 0.0
        rows.append({
            "numero": s.numero,
            # Mono : entier (cellule XLSX numérique, inchangé). Cépée :
            # chaîne préfixée par le label du brin (« a1 »).
            "sondage_id": f"{label}{s.numero}" if multi and label
            else s.numero,
            "grade": s.grade,
            "rayon_cm": R,
            "prbs_cm": s.prbs_cm,
            "bois_altere_cm": s.bois_altere_cm,
            "compartimentation": s.compartimentation or "non renseignée",
            "ratio_tR": ratio,
            "classe": classer_prbs(ratio, port),
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

# Libellés (féminins) de la légende des classes, sous le pied de page —
# explique le code couleur de la colonne « Proportion de bois sain ».
# Keyé par les labels de classe de `bareme` (Vert/Orange/Rouge), tels
# qu'ils arrivent dans `couleur_classe`. Fallback générique si un label
# inattendu apparaît.
_CLASSE_LEGENDE = {
    "Vert": "Classe verte",
    "Orange": "Classe orange",
    "Rouge": "Classe rouge",
}


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
    HEADER_FILL = PatternFill("solid", fgColor="2D7A3E")
    HEADER_FONT = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    META_FILL = PatternFill("solid", fgColor="2D7A3E")
    META_FONT = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    TITLE_FONT = Font(name="Calibri", size=16, bold=True, color="2D7A3E")
    SUBTITLE_FONT = Font(name="Calibri", size=10, color="6E7B73")
    ROW_FONT = Font(name="Calibri", size=11, color="1A2E22")
    ALT_ROW_FILL = PatternFill("solid", fgColor="F2F2F2")
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
        c.fill = META_FILL
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
    for row_idx, r in enumerate(rows_data):
        values = [
            r["sondage_id"],
            r["grade"],
            round(r["rayon_cm"], 2),
            round(r["prbs_cm"], 2),
            round(r["bois_altere_cm"], 2),
            None,                          # rempli ci-dessous
            round(100 * r["ratio_tR"], 1),
        ]
        classe_hex = couleur_classe.get(r["classe"], "CCCCCC").lstrip("#")
        glyph, glyph_hex = _compart_visual(r["compartimentation"])
        use_alt = row_idx % 2 == 1
        for i, v in enumerate(values, start=1):
            c = ws.cell(row=row, column=i)
            c.border = BORDER
            c.font = ROW_FONT
            c.alignment = CENTER
            if use_alt:
                c.fill = ALT_ROW_FILL
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

    # --- Ligne légende sous le tableau (collée au tableau, sans ligne
    # vide intercalée — calquée sur la fiche Excel d'origine du cabinet).
    # Les 7 colonnes : | "Légende :" | ✓ | "Compartimentation active" |
    # ✗ | "Pas de compartimentation" | — | "Non renseignée/pas
    # d'altération" |. Les glyphes (✓/✗/—) sont centrés et colorés comme
    # dans la colonne Compartimentation du tableau ; le reste est aligné
    # à gauche.
    legend_row = row
    GLYPH_CELLS = ("✓", "✗", "—")
    legend_cells = [
        ("Légende :", LEGEND_FONT),
        ("✓", Font(name="Calibri", size=14, bold=True,
                   color=_COMPART_GLYPH["active"][1])),
        ("Compartimentation active", LEGEND_FONT),
        ("✗", Font(name="Calibri", size=14, bold=True,
                   color=_COMPART_GLYPH["absente"][1])),
        ("Pas de compartimentation", LEGEND_FONT),
        ("—", Font(name="Calibri", size=14, bold=True,
                   color=_COMPART_NEUTRE[1])),
        ("Non renseignée/pas d'altération", LEGEND_FONT),
    ]
    for i, (value, font) in enumerate(legend_cells, start=1):
        c = ws.cell(row=legend_row, column=i, value=value)
        c.font = font
        c.alignment = CENTER if value in GLYPH_CELLS else LEFT
        c.border = BORDER
    ws.row_dimensions[legend_row].height = 24
    row += 2

    # --- Pied : édition + signature ---
    ws.cell(row=row, column=1,
            value=f"Édité le {datetime.now().strftime('%d/%m/%Y à %H:%M')} "
                  "— Pénétromètre, Silvavenir Foresterie urbaine").font = \
        Font(name="Calibri", size=9, italic=True, color="6E7B73")
    ws.merge_cells(start_row=row, start_column=1,
                   end_row=row, end_column=last)

    # --- Légende des classes (code couleur de la colonne proportion) ---
    # Calquée sur la fiche d'origine : sous le pied, après deux lignes
    # vides, une ligne par classe en colonne D, texte coloré de la
    # couleur de la classe.
    row += 3  # pied + 2 lignes vides
    for class_key, hex_ in couleur_classe.items():
        label = _CLASSE_LEGENDE.get(class_key, f"Classe {class_key}")
        c = ws.cell(row=row, column=4, value=label)
        c.font = Font(name="Calibri", size=11,
                      color=hex_.lstrip("#"))
        row += 1

    # --- Largeurs de colonnes auto-fit ---
    min_widths = [10, 12, 14, 14, 14, 16, 16]
    for col_idx in range(1, _NCOLS + 1):
        max_len = min_widths[col_idx - 1]
        for cell_row in ws.iter_rows(min_row=header_row,
                                     max_row=ws.max_row,
                                     min_col=col_idx,
                                     max_col=col_idx):
            for cell in cell_row:
                if cell.value is not None and not isinstance(
                        cell, type(ws.merged_cells)):
                    txt = str(cell.value)
                    for line in txt.split("\n"):
                        max_len = max(max_len, len(line) + 3)
        ws.column_dimensions[get_column_letter(col_idx)].width = min(
            max_len, 30)

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
    background: #2D7A3E;
    font-weight: 600;
    text-align: left;
}
.meta-cell .meta-label { color: rgba(255,255,255,0.85); font-weight: 600; }
.meta-cell .meta-value { color: #FFFFFF; font-weight: 700;
                          margin-left: 4px; }
thead th {
    background: #2D7A3E; color: #FFFFFF;
    text-align: center; font-weight: 700; font-size: 12px;
    line-height: 1.2;
}
tbody td { text-align: center; font-variant-numeric: tabular-nums; }
tbody tr:nth-child(even) td { background: #F2F2F2; }
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
                f'<td>{r["sondage_id"]}</td>'
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


# ----------------------------------------------------------------------
# Synthèse de mission : une ligne par arbre (tableau de hiérarchisation)
# ----------------------------------------------------------------------
#
# Source des données : `diagnostic.mission_synthesis_rows(chantier)` —
# calculé par l'appelant et passé en paramètre (List[MissionSynthesisRow]),
# pour garder `export.py` purement « formatage » et testable avec des
# stubs. Le masquage des champs non fiables (< 3 sondages) est déjà
# appliqué en amont (champs `None`) ; ici on ne fait que présenter.

_SYNTH_HEADERS = ["N°", "Essence", "Port", "Sondages", "Rayon (cm)",
                  "t/R moyen (%)", "Classe globale", "Direction critique",
                  "t/R critique (%)"]


def _synth_classe_text(row: "MissionSynthesisRow") -> str:
    """Texte de la colonne « Classe globale ». Distingue les 3 cas :
    classe publiée (Vert/Orange/Rouge), arbre sondé mais non fiable
    (1-2 sondages → « Non fiable »), ou non renseigné (« — »)."""
    if row.classe_globale is not None:
        return row.classe_globale
    if row.n_sondees > 0 and row.rayon_cm > 0:
        return "Non fiable"
    return "—"


def _synth_crit_text(row: "MissionSynthesisRow") -> str:
    if row.crit_grade is None:
        return "—"
    if row.crit_dir:
        return f"{row.crit_dir} ({row.crit_grade} gr)"
    return f"{row.crit_grade} gr"


def _synth_pct_text(v: object) -> str:
    return f"{v:.1f}" if isinstance(v, (int, float)) else "—"


def export_synthesis_csv(rows: "Sequence[MissionSynthesisRow]",
                         path: str) -> None:
    """Synthèse mission en CSV (séparateur `;`, UTF-8 BOM compatible
    Excel). Une ligne par arbre."""
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(_SYNTH_HEADERS)
        for r in rows:
            # Sous-ligne de brin (cépée) : N° décalé « ↳ brin a », identité
            # genet laissée vide (déjà sur la ligne de tête).
            if r.brin_label:
                num: object = f"↳ brin {r.brin_label}"
                ess, port = "", ""
            else:
                num, ess, port = r.numero, r.essence, r.port
            w.writerow([
                num, ess, port, r.n_sondees,
                f"{r.rayon_cm:g}",
                _synth_pct_text(r.tR_moyen_pct),
                _synth_classe_text(r),
                _synth_crit_text(r),
                _synth_pct_text(r.tR_min_pct),
            ])


def export_synthesis_xlsx(rows: "Sequence[MissionSynthesisRow]",
                          chantier: ChantierLike, path: str,
                          couleur_classe: Mapping[str, str]) -> None:
    """Synthèse mission en .xlsx thémé Silvavenir : une ligne par arbre,
    cellule « Classe globale » colorée, autofiltre (tri par n'importe
    quelle colonne — p.ex. trier par classe = priorités d'intervention),
    en-tête gelé, ligne de bilan en pied."""
    if not HAS_OPENPYXL:
        raise RuntimeError(
            "openpyxl n'est pas installé. Lancer "
            "`pip install -r requirements.txt`.")

    wb = Workbook()
    ws = wb.active
    ws.title = "Synthèse"

    BORDER = Border(
        left=Side(style="thin", color="999999"),
        right=Side(style="thin", color="999999"),
        top=Side(style="thin", color="999999"),
        bottom=Side(style="thin", color="999999"),
    )
    HEADER_FILL = PatternFill("solid", fgColor="2D7A3E")
    HEADER_FONT = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    TITLE_FONT = Font(name="Calibri", size=16, bold=True, color="2D7A3E")
    SUBTITLE_FONT = Font(name="Calibri", size=10, color="6E7B73")
    ROW_FONT = Font(name="Calibri", size=11, color="1A2E22")
    ALT_ROW_FILL = PatternFill("solid", fgColor="F2F2F2")
    MUTED_FILL = PatternFill("solid", fgColor="E0E0E0")
    FOOTER_FONT = Font(name="Calibri", size=10, italic=True, color="6E7B73")
    CENTER = Alignment(horizontal="center", vertical="center",
                       wrap_text=True)
    LEFT = Alignment(horizontal="left", vertical="center", wrap_text=True)

    last = len(_SYNTH_HEADERS)

    # --- Titre + sous-titre mission ---
    ws.cell(row=1, column=1,
            value=f"Pénétromètre — Synthèse mission « {chantier.nom or 'Mission'} »"
            ).font = TITLE_FONT
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=last)
    subtitle_parts = []
    if chantier.adresse:
        subtitle_parts.append(chantier.adresse)
    if chantier.operateur:
        subtitle_parts.append(f"Opérateur : {chantier.operateur}")
    subtitle_parts.append(f"Relevé du {chantier.date_releve or '—'}")
    ws.cell(row=2, column=1,
            value=" • ".join(subtitle_parts)).font = SUBTITLE_FONT
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=last)

    # --- En-tête tableau ---
    header_row = 4
    for i, h in enumerate(_SYNTH_HEADERS, start=1):
        c = ws.cell(row=header_row, column=i, value=h)
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
        c.alignment = CENTER
        c.border = BORDER
    ws.row_dimensions[header_row].height = 30

    # --- Une ligne par arbre ---
    classe_col = 7  # colonne « Classe globale » → fond coloré
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
            _synth_pct_text(row.tR_moyen_pct),
            classe_txt,
            _synth_crit_text(row),
            _synth_pct_text(row.tR_min_pct),
        ]
        use_alt = k % 2 == 1
        for i, v in enumerate(values, start=1):
            c = ws.cell(row=r_idx, column=i, value=v)
            c.border = BORDER
            c.font = ROW_FONT
            c.alignment = LEFT if i in (2,) else CENTER
            if i == classe_col:
                hexa = couleur_classe.get(classe_txt, "").lstrip("#")
                if hexa:
                    c.fill = PatternFill("solid", fgColor=hexa)
                    c.font = Font(name="Calibri", size=11, bold=True,
                                  color="FFFFFF")
                else:
                    c.fill = MUTED_FILL
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

    # --- Largeurs de colonnes ---
    widths = [6, 18, 13, 10, 11, 14, 15, 20, 14]
    for i, wdt in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = wdt

    wb.save(path)
