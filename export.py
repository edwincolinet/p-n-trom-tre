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
  lettres) · Compartimentation ✓/✗/–.
- Une ligne « Diagnostic » (t/R moyen, classe globale, t/R min),
  alignée sur la fiche PDF (classe publiée = celle du t/R moyen,
  masquée si < 3 directions sondées).
- Une légende compartimentation (✓ active / ✗ absente / – neutre) et
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
    source unique `dialogs_shared` (mêmes ✓/✗/– qu'à la saisie)."""
    glyph, hexa = compart_visual(value)
    return glyph, hexa.lstrip("#")



# Caractères qui font qu'un tableur (Excel/LibreOffice) interprète une
# cellule comme une formule à l'ouverture — pour un .xlsx natif, openpyxl
# bascule lui-même `data_type='f'` dès qu'une valeur texte commence par
# "=" ; pour un .csv, c'est Excel qui le fait à l'import. Un champ texte
# libre de mission (essence, n° d'arbre — qui peut légalement commencer
# par « =1 », préconisation, commentaire de suivi, adresse…) est une
# entrée semi-fiable au même titre que les chemins de photo
# (cf. CLAUDE.md `photo_paths.py`) : un confrère pourrait y glisser
# `=WEBSERVICE(...)`. Neutralisé comme le ferait la case « Texte » d'un
# tableur : préfixe d'une apostrophe, qui force le type texte.
_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def _defuse(value: Any) -> Any:
    """Neutralise une valeur de cellule pouvant être interprétée comme une
    formule par un tableur. No-op sur les valeurs non textuelles."""
    if isinstance(value, str) and value.startswith(_FORMULA_TRIGGERS):
        return "'" + value
    return value


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
    parts = [_("Arbre n°{n}").format(n=arbre.numero_arbre)
             if arbre.numero_arbre else _("Arbre")]
    if arbre.essence:
        parts.append(arbre.essence)
    if arbre.port_arbre:
        parts.append(_("Port {port}").format(port=arbre.port_arbre))
    return "  ·  ".join(parts)


def _dimension_line(arbre: ArbreLike) -> str:
    """Dimensions mesurées de l'arbre, en sous-titre lisible."""
    dims = [
        (_("Ø sous écorce"),
         _value_or_dash(arbre.diametre_sous_ecorce_cm, "cm")),
        (_("Hauteur sondage"), _value_or_dash(arbre.hauteur_sondage_cm, "cm")),
        (_("Hauteur arbre"), _value_or_dash(arbre.hauteur_arbre_m, "m")),
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
_COL_COMPART = 9   # glyphe ✓/✗/–

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
                     cabinet_name: str = "",
                     bareme_desc: str = "") -> None:
    """Écrit le tableau PRBS dans `path` (.xlsx). `couleur_classe` est
    le dict label → hex injecté depuis la couche UI.

    `bareme_desc` : description des seuils ayant produit les classes
    (cf. `bareme.description_seuils_mission`), injectée depuis la couche
    UI comme `classer_prbs` — ce module reste sans dépendance vers
    `bareme`. Vide = ligne omise."""
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
        c = ws.cell(row=row, column=1, value=_defuse(value))
        c.font = font
        c.alignment = align
        ws.merge_cells(start_row=row, start_column=1,
                       end_row=row, end_column=last)

    # --- Titre + sous-titre mission + identité arbre ---
    _banner(1, f"Pénétromètre — {chantier.nom or _('Mission')}", TITLE_FONT)
    subtitle_parts = []
    if chantier.client:
        subtitle_parts.append(_("Client") + f" : {chantier.client}")
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
        c = ws.cell(row=header_row, column=i, value=_(h))
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
                          value=_("Aucun sondage enregistré."))
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
        values = [_defuse(v) for v in values]
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
    # Glyphes issus de la source unique (`dialogs_shared`) pour rester
    # alignés sur la saisie et les cellules du tableau.
    _banner(row,
            f"Compartimentation :   {compart_glyph('active')} active     "
            f"{compart_glyph('absente')} absente     "
            f"{compart_glyph('non renseignée')} non renseignée / pas d'altération",
            LEGEND_FONT)
    row += 1

    # --- Légende des classes : un point coloré + libellé par classe ---
    col = 1
    for class_key, hex_ in couleur_classe.items():
        if class_key in _CLASSE_LEGENDE:
            label = _(_CLASSE_LEGENDE[class_key])
        else:
            label = f"Classe {class_key}"
        c = ws.cell(row=row, column=col, value=f"● {label}")
        c.font = Font(name="Calibri", size=11, bold=True,
                      color=hex_.lstrip("#"))
        c.alignment = CENTER
        col += 1
    row += 1

    # --- Barème appliqué : sans lui, les classes ci-dessus ne sont pas
    # reproductibles (les seuils sont un réglage de poste). ---
    if bareme_desc:
        _banner(row, f"Barème appliqué :   {bareme_desc}", LEGEND_FONT)
        row += 1
    row += 1

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
td.compart-neutre { color: #55605A; }
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
.legend .neutre { color: #55605A; font-style: normal; font-weight: 700; }
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
                     cabinet_name: str = "",
                     bareme_desc: str = "") -> None:
    """Écrit le tableau PRBS dans `path` (.html). Aucun fichier externe :
    le CSS est embarqué. Mise en page alignée sur l'export XLSX
    (`bareme_desc` compris — cf. `export_prbs_xlsx`)."""
    rows_data = prbs_table_rows_par_sondage(arbre, classer_prbs)
    title = (f"Pénétromètre — {chantier.nom or _('Mission')} — "
             f"{arbre.numero_arbre or ''}")

    # En-tête mission
    meta_chunks = []
    if chantier.client:
        meta_chunks.append(_("Client") + f" : {_h(chantier.client)}")
    if chantier.adresse:
        meta_chunks.append(_h(chantier.adresse))
    if chantier.operateur:
        meta_chunks.append(_("Opérateur") + f" : {_h(chantier.operateur)}")
    meta_chunks.append(_("Relevé du") + f" {_h(chantier.date_releve or '—')}")
    meta_html = " • ".join(meta_chunks)

    headers_html = "".join(f'<th>{_h(_(h))}</th>' for h in _HEADERS)

    # Données
    if not rows_data:
        body_html = (
            f'<tr class="empty-row"><td colspan="{_NCOLS}">'
            f'{_h(_("Aucun sondage enregistré."))}</td></tr>')
    else:
        body_rows = []
        for r in rows_data:
            classe_color = couleur_classe.get(r["classe"], "#CCCCCC")
            comp = (r["compartimentation"] or "").lower().strip()
            glyph = compart_glyph(comp)  # ✓ / ✗ / – (source unique)
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

    # Légende compartimentation (glyphes source-unique `dialogs_shared`).
    legend_html = (
        '<div class="legend">Compartimentation : '
        f'<span class="ok">{compart_glyph("active")}</span> active&nbsp;&nbsp; '
        f'<span class="ko">{compart_glyph("absente")}</span> absente&nbsp;&nbsp; '
        f'<span class="neutre">{compart_glyph("non renseignée")}</span> '
        'non renseignée / pas d&#39;altération</div>')

    # Légende des classes (code couleur des colonnes « t/R » et « Classe »),
    # comme dans le XLSX : une entrée par classe, texte coloré.
    classe_legend_html = "".join(
        f'<span class="classe-item" style="color:{couleur_classe.get(k, "#CCCCCC")}">'
        f'● {_h(_(_CLASSE_LEGENDE[k]) if k in _CLASSE_LEGENDE else "Classe " + k)}</span>'
        for k in couleur_classe)

    # Barème appliqué — même information que dans le XLSX (parité
    # verrouillée par `HtmlExportAlignementTests`).
    bareme_html = (f'<div class="legend">Barème appliqué : '
                   f'{_h(bareme_desc)}</div>') if bareme_desc else ""

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>{_h(title)}</title>
<style>{_HTML_CSS}</style>
</head>
<body>
<h1>{_h('Pénétromètre — ' + (chantier.nom or _('Mission')))}</h1>
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
{bareme_html}

<footer>
Édité le {datetime.now().strftime('%d/%m/%Y à %H:%M')} — Pénétromètre{' · ' + cabinet_name if cabinet_name else ''}.
</footer>
</body>
</html>
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


# La synthèse de mission (une ligne par arbre, CSV/XLSX) vit dans
# `export_synthesis.py` — sous-domaine distinct de l'export PRBS par
# arbre ci-dessus, qui ne partage avec lui que `ChantierLike`/`_defuse`.
