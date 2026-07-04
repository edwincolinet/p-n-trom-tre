"""
Exports stylés du tableau PRBS d'un arbre.

Deux formats au choix :
- `export_prbs_xlsx`  : fichier .xlsx avec mise en forme (en-têtes
  colorés, cellule t/R color-codée par classe, bordures, gel de lignes,
  largeurs ajustées). Nécessite openpyxl.
- `export_prbs_html`  : fichier .html autonome (CSS embarqué). Aucune
  dépendance — ouvrable dans n'importe quel navigateur, imprimable en
  PDF via le navigateur.

Mise en page (propre à Pénétromètre, terminologie interne) :
- Un titre mission + un sous-titre méta (adresse, opérateur, date…).
- Deux lignes d'identité de l'arbre en toutes lettres (N°, essence,
  port ; puis Ø sous écorce, hauteur de sondage, hauteur de l'arbre) —
  lisibles, sans bande de cellules fusionnées.
- L'en-tête des colonnes.
- UNE LIGNE PAR SONDAGE : N° · Direction (N/NE/…) · Grade · Rayon ·
  PRBS bois sain · Bois altéré · t/R coloré · Classe (en toutes
  lettres) · Compartimentation ✔/✘/—.
- Une ligne « Diagnostic » (t/R moyen, classe globale, t/R min),
  alignée sur la fiche PDF (classe publiée = celle du t/R moyen,
  masquée si < 3 directions sondées).
- Une légende compartimentation (✔ active / ✘ absente / — neutre) et
  une légende des classes (Vert/Orange/Rouge).

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

from diagnostic import genet_diagnostic as _diag_genet_diagnostic
from diagnostic import ratio_tR_par_grade as _diag_ratio_tR_par_grade
from diagnostic import repartition_classes as _diag_repartition_classes
from dialogs_shared import compart_glyph, compart_visual
from geometry import GRADES, WIND_LABELS
from i18n import _

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
# rendrait `export.py` dépendant du modèle Pénétromètre ; les protocols
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
    client: str
    reference: str


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
            "incertain": getattr(s, "incertain", False),
        })
    return rows


# ----------------------------------------------------------------------
# Helpers présentation
# ----------------------------------------------------------------------

def _compart_visual(value: str) -> Tuple[str, str]:
    """(glyphe, couleur_hex_SANS_dièse) pour openpyxl. Symbole & couleur =
    source unique `dialogs_shared` (mêmes ✔/✘/— qu'à la saisie)."""
    glyph, hexa = compart_visual(value)
    return glyph, hexa.lstrip("#")


def _value_or_dash(value: Any, unit: str = "") -> str:
    """Formate une valeur métier en remplaçant le vide/0 par « — »."""
    if value in (None, "", 0, 0.0):
        return "—"
    if isinstance(value, (int, float)):
        return f"{value:g}{(' ' + unit) if unit else ''}"
    return str(value) + ((" " + unit) if unit else "")


def _identity_line(arbre: ArbreLike) -> str:
    """Ligne d'identité de l'arbre, en toutes lettres (remplace l'ancienne
    bande méta fusionnée sur 7 colonnes)."""
    parts = [f"Arbre n°{arbre.numero_arbre}"
             if arbre.numero_arbre else "Arbre"]
    if arbre.essence:
        parts.append(arbre.essence)
    if arbre.port_arbre:
        parts.append(f"Port {arbre.port_arbre}")
    return "  ·  ".join(parts)


def _dimension_line(arbre: ArbreLike) -> str:
    """Dimensions mesurées de l'arbre, en sous-titre lisible."""
    dims = [
        ("Ø sous écorce",
         _value_or_dash(arbre.diametre_sous_ecorce_cm, "cm")),
        ("Hauteur sondage", _value_or_dash(arbre.hauteur_sondage_cm, "cm")),
        ("Hauteur arbre", _value_or_dash(arbre.hauteur_arbre_m, "m")),
    ]
    return "  ·  ".join(f"{k} {v}" for k, v in dims)


def _diagnostic_summary(arbre: ArbreLike) -> Tuple[str, str]:
    """(texte, classe|"") de la ligne « Diagnostic » sous le tableau.

    Aligne l'export sur la fiche PDF : la classe publiée est celle du
    **t/R moyen** et elle est masquée si < 3 directions sondées
    (`DiagnosticSnapshot.diagnostic_global`). Une cépée reporte la pire
    classe parmi les brins fiables (`genet_diagnostic`). La 2ᵉ valeur du
    tuple = label de classe (ou "") pour coloriser la ligne."""
    a = cast("Arbre", arbre)
    brins = list(getattr(arbre, "brins", []) or [])
    if len(brins) > 1:
        gd = _diag_genet_diagnostic(a)
        if gd.classe_globale is None:
            return ("⚠ Diagnostic global indisponible : aucun brin avec au "
                    "moins 3 directions sondées.", "")
        return (f"Classe globale (pire brin fiable) : {gd.classe_globale}",
                gd.classe_globale)
    snap = _diag_repartition_classes(a)
    diag = snap.diagnostic_global
    if diag is None:
        return ("⚠ Diagnostic non fiable : au moins 3 directions sondées "
                "sont requises pour publier une classe.", "")
    tR_moyen, classe = diag
    crit = (f"{snap.tR_min_dir} ({snap.tR_min_grade} gr)"
            if snap.tR_min_dir else f"{snap.tR_min_grade} gr")
    return (f"Diagnostic — t/R moyen {100 * tR_moyen:.1f} %   ·   "
            f"Classe globale {classe}   ·   "
            f"t/R minimal {100 * snap.tR_min:.1f} %  ({crit})", classe)


# ----------------------------------------------------------------------
# Export XLSX
# ----------------------------------------------------------------------

# En-têtes du tableau (ordre des colonnes). Terminologie interne
# (Direction / t/R / Classe), pas de retour à la ligne forcé.
_HEADERS = [
    "N°",
    "Direction",
    "Grade (gr)",
    "Rayon (cm)",
    "PRBS bois sain (cm)",
    "Bois altéré (cm)",
    "t/R (%)",
    "Classe",
    "Compart.",
]
_NCOLS = len(_HEADERS)

# Index (1-based) des colonnes à traitement spécial.
_COL_TR = 7        # fond coloré par classe (heatmap)
_COL_CLASSE = 8    # texte de classe, police colorée
_COL_COMPART = 9   # glyphe ✔/✘/—

# Libellés de la légende des classes (sous le tableau) — explique le code
# couleur des colonnes « t/R » et « Classe ». Keyé par les labels de classe
# de `bareme` (Vert/Orange/Rouge) tels qu'ils arrivent dans
# `couleur_classe`. Source unique, partagée XLSX ↔ HTML. Fallback générique
# si un label inattendu apparaît.
_CLASSE_LEGENDE = {
    "Vert": "Classe verte",
    "Orange": "Classe orange",
    "Rouge": "Classe rouge",
}


def export_prbs_xlsx(arbre: ArbreLike, chantier: ChantierLike, path: str,
                     couleur_classe: Mapping[str, str],
                     classer_prbs: ClasserPrbs,
                     cabinet_name: str = "") -> None:
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
    TITLE_FONT = Font(name="Calibri", size=16, bold=True, color="2D7A3E")
    SUBTITLE_FONT = Font(name="Calibri", size=10, color="6E7B73")
    IDENTITY_FONT = Font(name="Calibri", size=12, bold=True, color="1A2E22")
    ROW_FONT = Font(name="Calibri", size=11, color="1A2E22")
    ALT_ROW_FILL = PatternFill("solid", fgColor="F2F2F2")
    LEGEND_FONT = Font(name="Calibri", size=10, italic=True,
                       color="6E7B73")

    LEFT = Alignment(horizontal="left", vertical="center", wrap_text=True)
    CENTER = Alignment(horizontal="center", vertical="center",
                       wrap_text=True)

    last = _NCOLS

    def _banner(row: int, value: str, font: Font,
                align: Alignment = LEFT) -> None:
        """Cellule pleine largeur (fusion col 1 → dernière)."""
        c = ws.cell(row=row, column=1, value=value)
        c.font = font
        c.alignment = align
        ws.merge_cells(start_row=row, start_column=1,
                       end_row=row, end_column=last)

    # --- Titre + sous-titre mission + identité arbre ---
    _banner(1, f"Pénétromètre — {chantier.nom or 'Mission'}", TITLE_FONT)
    subtitle_parts = []
    if chantier.client:
        subtitle_parts.append(_("Client") + f" : {chantier.client}")
    if chantier.reference:
        subtitle_parts.append(_("Référence") + f" : {chantier.reference}")
    if chantier.adresse:
        subtitle_parts.append(chantier.adresse)
    if chantier.operateur:
        subtitle_parts.append(_("Opérateur") + f" : {chantier.operateur}")
    subtitle_parts.append(_("Relevé du") + f" {chantier.date_releve or '—'}")
    _banner(2, " • ".join(subtitle_parts), SUBTITLE_FONT)
    _banner(3, _identity_line(arbre), IDENTITY_FONT)
    _banner(4, _dimension_line(arbre), SUBTITLE_FONT)

    # --- En-tête tableau ---
    header_row = 6  # ligne 5 laissée vide
    for i, h in enumerate(_HEADERS, start=1):
        c = ws.cell(row=header_row, column=i, value=h)
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
        c.alignment = CENTER
        c.border = BORDER
    ws.row_dimensions[header_row].height = 30
    row = header_row + 1

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
    for row_idx, r in enumerate(rows_data):
        # Préfixe "~" si sondage incertain
        _id = r["sondage_id"]
        if r.get("incertain"):
            _id = f"~{_id}"
        values = [
            _id,
            WIND_LABELS.get(r["grade"], ""),
            r["grade"],
            round(r["rayon_cm"], 2),
            round(r["prbs_cm"], 2),
            round(r["bois_altere_cm"], 2),
            round(100 * r["ratio_tR"], 1),
            r["classe"],                   # colonne texte
            None,                          # Compart. rempli ci-dessous
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
            if i == _COL_COMPART:
                c.value = glyph
                c.font = Font(name="Calibri", size=14, bold=True,
                              color=glyph_hex)
            elif i == _COL_TR:
                c.value = v
                c.fill = PatternFill("solid", fgColor=classe_hex)
                c.font = Font(name="Calibri", size=11, bold=True,
                              color="FFFFFF")
            elif i == _COL_CLASSE:
                c.value = v
                c.font = Font(name="Calibri", size=11, bold=True,
                              color=classe_hex)
            else:
                c.value = v
        ws.row_dimensions[row].height = 22
        row += 1

    # --- Ligne « Diagnostic » (t/R moyen · classe globale · t/R min) ---
    row += 1  # ligne vide
    diag_text, diag_classe = _diagnostic_summary(arbre)
    diag_hex = couleur_classe.get(diag_classe, "1A2E22").lstrip("#")
    _banner(row, diag_text,
            Font(name="Calibri", size=12, bold=True, color=diag_hex))
    row += 2

    # --- Légende compartimentation (une bannière, glyphes en clair) ---
    _banner(row,
            "Compartimentation :   ✔ active     ✘ absente     "
            "— non renseignée / pas d'altération",
            LEGEND_FONT)
    row += 1

    # --- Légende des classes : un point coloré + libellé par classe ---
    col = 1
    for class_key, hex_ in couleur_classe.items():
        label = _CLASSE_LEGENDE.get(class_key, f"Classe {class_key}")
        c = ws.cell(row=row, column=col, value=f"● {label}")
        c.font = Font(name="Calibri", size=11, bold=True,
                      color=hex_.lstrip("#"))
        c.alignment = CENTER
        col += 1
    row += 2

    # --- Pied : édition + signature ---
    suffix = f" · {cabinet_name}" if cabinet_name else ""
    _banner(row,
            _("Édité le")
            + f" {datetime.now().strftime('%d/%m/%Y à %H:%M')} — Pénétromètre"
            + suffix,
            Font(name="Calibri", size=9, italic=True, color="6E7B73"))

    # --- Largeurs de colonnes fixes (contenu court et régulier) ---
    widths = [6, 11, 10, 11, 18, 15, 10, 11, 10]
    for i, wdt in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = wdt

    # Gel : tout l'en-tête (titre + identité + en-tête tableau)
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
.meta-mission { color: #6E7B73; font-size: 13px; margin-bottom: 10px; }
.identity { font-size: 15px; font-weight: 700; color: #1A2E22;
            margin-bottom: 2px; }
.dimensions { color: #6E7B73; font-size: 13px; margin-bottom: 16px; }
table {
    border-collapse: collapse; width: 100%; margin-top: 6px;
    background: #FFFFFF; font-size: 13px;
    border: 1px solid #999999;
}
table th, table td {
    border: 1px solid #999999;
    padding: 6px 10px;
}
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
td.classe { font-weight: 700; }
td.compart-active { color: #2D7A3E; font-size: 18px; font-weight: 700; }
td.compart-absente { color: #C0392B; font-size: 18px; font-weight: 700; }
td.compart-neutre { color: #6E7B73; }
.diagnostic {
    margin-top: 14px; font-size: 15px; font-weight: 700;
    padding: 8px 12px; border-left: 5px solid #2D7A3E;
    background: #FFFFFF;
}
.legend {
    margin-top: 12px; color: #6E7B73; font-size: 12px; font-style: italic;
}
.legend .ok { color: #2D7A3E; font-style: normal; font-weight: 700; }
.legend .ko { color: #C0392B; font-style: normal; font-weight: 700; }
.legend .neutre { color: #6E7B73; font-style: normal; font-weight: 700; }
.classe-legend { margin-top: 8px; display: flex; gap: 22px;
                 font-weight: 700; font-size: 13px; }
.classe-legend .classe-item { white-space: nowrap; }
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
                     classer_prbs: ClasserPrbs,
                     cabinet_name: str = "") -> None:
    """Écrit le tableau PRBS dans `path` (.html). Aucun fichier externe :
    le CSS est embarqué. Mise en page alignée sur l'export XLSX."""
    rows_data = prbs_table_rows_par_sondage(arbre, classer_prbs)
    title = (f"Pénétromètre — {chantier.nom or 'Mission'} — "
             f"{arbre.numero_arbre or ''}")

    # En-tête mission
    meta_chunks = []
    if chantier.client:
        meta_chunks.append(_("Client") + f" : {_h(chantier.client)}")
    if chantier.reference:
        meta_chunks.append(_("Référence") + f" : {_h(chantier.reference)}")
    if chantier.adresse:
        meta_chunks.append(_h(chantier.adresse))
    if chantier.operateur:
        meta_chunks.append(_("Opérateur") + f" : {_h(chantier.operateur)}")
    meta_chunks.append(_("Relevé du") + f" {_h(chantier.date_releve or '—')}")
    meta_html = " • ".join(meta_chunks)

    headers_html = "".join(f'<th>{_h(h)}</th>' for h in _HEADERS)

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
            glyph = compart_glyph(comp)  # ✔ / ✘ / — (source unique)
            if comp == "active":
                comp_html = f'<td class="compart-active">{glyph}</td>'
            elif comp == "absente":
                comp_html = f'<td class="compart-absente">{glyph}</td>'
            else:
                comp_html = f'<td class="compart-neutre">{glyph}</td>'
            body_rows.append(
                "<tr>"
                f'<td>{_h(r["sondage_id"])}</td>'
                f'<td>{_h(WIND_LABELS.get(r["grade"], ""))}</td>'
                f'<td>{r["grade"]}</td>'
                f'<td>{round(r["rayon_cm"], 2):g}</td>'
                f'<td>{round(r["prbs_cm"], 2):g}</td>'
                f'<td>{round(r["bois_altere_cm"], 2):g}</td>'
                f'<td class="tR" style="background:{classe_color}">'
                f'{100*r["ratio_tR"]:.1f}</td>'
                f'<td class="classe" style="color:{classe_color}">'
                f'{_h(r["classe"])}</td>'
                f'{comp_html}'
                "</tr>"
            )
        body_html = "\n".join(body_rows)

    # Ligne « Diagnostic » (mêmes valeurs et règle de fiabilité que le XLSX
    # et la fiche PDF).
    diag_text, diag_classe = _diagnostic_summary(arbre)
    diag_color = couleur_classe.get(diag_classe, "#2D7A3E")
    diagnostic_html = (
        f'<div class="diagnostic" style="border-left-color:{diag_color}">'
        f'{_h(diag_text)}</div>')

    # Légende compartimentation : ✔ active · ✘ absente · — neutre.
    legend_html = (
        '<div class="legend">Compartimentation : '
        '<span class="ok">✔</span> active&nbsp;&nbsp; '
        '<span class="ko">✘</span> absente&nbsp;&nbsp; '
        '<span class="neutre">—</span> non renseignée / pas '
        'd&#39;altération</div>')

    # Légende des classes (code couleur des colonnes « t/R » et « Classe »),
    # comme dans le XLSX : une entrée par classe, texte coloré.
    classe_legend_html = "".join(
        f'<span class="classe-item" style="color:{couleur_classe.get(k, "#CCCCCC")}">'
        f'● {_h(_CLASSE_LEGENDE.get(k, "Classe " + k))}</span>'
        for k in couleur_classe)

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
<div class="identity">{_h(_identity_line(arbre))}</div>
<div class="dimensions">{_h(_dimension_line(arbre))}</div>

<table>
<thead>
<tr>{headers_html}</tr>
</thead>
<tbody>
{body_html}
</tbody>
</table>

{diagnostic_html}
{legend_html}
<div class="classe-legend">{classe_legend_html}</div>

<footer>
Édité le {datetime.now().strftime('%d/%m/%Y à %H:%M')} — Pénétromètre{' · ' + cabinet_name if cabinet_name else ''}.
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
                  "t/R critique (%)", "Urgence", "Échéance", "Préconisation",
                  "Validité suivi", "Commentaire suivi"]

# Couleur de la cellule « Urgence » dans le XLSX : (fond, police) en hexa.
# Aligne la lecture du délai d'intervention sur celle de la classe de risque.
_URGENCE_FILL = {
    "Immédiate": ("C0392B", "FFFFFF"),
    "< 6 mois":  ("E67E22", "FFFFFF"),
    "< 1 an":    ("F1C40F", "1A2E22"),
    "< 2 ans":   ("A9DFBF", "1A2E22"),
}


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


def _synth_or_dash(s: str) -> str:
    """Texte d'un champ de préconisation, « — » si vide (ou sous-ligne de
    brin où la préconisation n'est pas répétée)."""
    return s if s else "—"


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
                _synth_or_dash(r.urgence),
                _synth_or_dash(r.echeance),
                _synth_or_dash(r.preconisation),
                _synth_or_dash(r.suivi_validite),
                _synth_or_dash(r.suivi_texte),
            ])


def export_synthesis_xlsx(rows: "Sequence[MissionSynthesisRow]",
                          chantier: ChantierLike, path: str,
                          couleur_classe: Mapping[str, str]) -> None:
    """Synthèse mission en .xlsx thémé Pénétromètre : une ligne par arbre,
    cellule « Classe globale » colorée, autofiltre (tri par n'importe
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
            value=_("Pénétromètre — Synthèse mission « {nom} »").format(nom=chantier.nom or _("Mission"))
            ).font = TITLE_FONT
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=last)
    subtitle_parts = []
    if chantier.client:
        subtitle_parts.append(_("Client") + f" : {chantier.client}")
    if chantier.reference:
        subtitle_parts.append(_("Référence") + f" : {chantier.reference}")
    if chantier.adresse:
        subtitle_parts.append(chantier.adresse)
    if chantier.operateur:
        subtitle_parts.append(_("Opérateur") + f" : {chantier.operateur}")
    subtitle_parts.append(_("Relevé du") + f" {chantier.date_releve or '—'}")
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
            _synth_or_dash(row.urgence),
            _synth_or_dash(row.echeance),
            _synth_or_dash(row.preconisation),
            _synth_or_dash(row.suivi_validite),
            _synth_or_dash(row.suivi_texte),
        ]
        urgence_col = 10
        preco_col = 12
        suivi_texte_col = 14
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
                    c.font = Font(name="Calibri", size=11, bold=True,
                                  color="FFFFFF")
                else:
                    c.fill = MUTED_FILL
            elif i == urgence_col and row.urgence in _URGENCE_FILL:
                fill_hex, font_hex = _URGENCE_FILL[row.urgence]
                c.fill = PatternFill("solid", fgColor=fill_hex)
                c.font = Font(name="Calibri", size=11, bold=True,
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

    # --- Largeurs de colonnes ---
    widths = [6, 18, 13, 10, 11, 14, 15, 20, 14, 20, 12, 40, 14, 40]
    for i, wdt in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = wdt

    wb.save(path)
