"""
Écriture de classeurs **ODS** (OpenDocument Tableur, LibreOffice / OpenOffice /
Excel) sans dépendance : `zipfile` + XML de la bibliothèque standard.

Module pur, de niveau « stdlib » : il ne connaît rien du métier. Les modules
d'export construisent des `Sheet` (lignes de `Cell` stylées) et appellent
`write_ods`. Le sous-ensemble ODF produit est volontairement minimal mais
complet pour nos tableaux : texte et nombres, fond/couleur/gras/italique/taille
de police, alignement, bordures fines, cellules fusionnées, largeurs de
colonnes, hauteurs de lignes, plusieurs feuilles.

Sécurité : toute valeur texte est écrite comme `office:value-type="string"` —
elle n'est JAMAIS interprétée comme une formule par le tableur (pas de
`table:formula`), donc inutile de la « neutraliser » comme pour un .xlsx
(cf. `export._defuse`).
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple, Union
from xml.sax.saxutils import escape, quoteattr

_ODS_MIME = "application/vnd.oasis.opendocument.spreadsheet"

_NS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
    'xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" '
)

Value = Union[str, int, float, None]


@dataclass(frozen=True)
class Cell:
    """Une cellule. `value` : texte, nombre ou `None` (vide). Les couleurs
    sont en hexa `RRGGBB` (avec ou sans « # »). `span` : nombre de colonnes
    fusionnées à partir de cette cellule (≥ 1)."""
    value: Value = None
    bg: Optional[str] = None
    fg: Optional[str] = None
    bold: bool = False
    italic: bool = False
    size: Optional[float] = None          # points
    font: Optional[str] = None
    align: str = "center"                 # "left" | "center" | "right"
    border: bool = False
    wrap: bool = True
    span: int = 1


@dataclass
class Sheet:
    """Une feuille. `rows[i]` = cellules de la ligne i (`None` = vide). Les
    cellules fusionnées (`span > 1`) occupent leur colonne de départ ; les
    suivantes sont complétées automatiquement."""
    name: str
    rows: List[List[Optional[Cell]]] = field(default_factory=list)
    col_widths_cm: List[float] = field(default_factory=list)
    row_heights_cm: Dict[int, float] = field(default_factory=dict)


# ----------------------------------------------------------------------
# Noms de feuilles
# ----------------------------------------------------------------------

_FORBIDDEN_SHEET_CHARS = set("[]:*?/\\'")


def safe_sheet_name(name: str, used: Sequence[str] = ()) -> str:
    """Nom de feuille valide ET unique : 31 caractères au plus (limite Excel,
    respectée par prudence pour l'ouverture dans Excel), sans `[ ] : * ? / \\
    '`, jamais vide, et distinct (sans tenir compte de la casse) de ceux de
    `used` — suffixe « (2) », « (3) »… sinon."""
    base = "".join("_" if (c in _FORBIDDEN_SHEET_CHARS or ord(c) < 32) else c
                   for c in name).strip() or "Feuille"
    base = base[:31]
    pris = {u.lower() for u in used}
    if base.lower() not in pris:
        return base
    n = 2
    while True:
        suffixe = f" ({n})"
        cand = base[:31 - len(suffixe)] + suffixe
        if cand.lower() not in pris:
            return cand
        n += 1


# ----------------------------------------------------------------------
# XML
# ----------------------------------------------------------------------

def _clean(text: str) -> str:
    """Retire les caractères de contrôle interdits en XML 1.0."""
    return "".join(c for c in text
                   if c in "\t\n\r" or ord(c) >= 0x20)


def _hex(color: str) -> str:
    return "#" + color.lstrip("#").upper()


def _cell_style_key(c: Cell) -> Tuple:
    return (c.bg, c.fg, c.bold, c.italic, c.size, c.font, c.align,
            c.border, c.wrap)


def _cell_style_xml(name: str, c: Cell) -> str:
    tcp = ['style:vertical-align="middle"']
    if c.bg:
        tcp.append(f'fo:background-color="{_hex(c.bg)}"')
    if c.border:
        tcp.append('fo:border="0.5pt solid #D9D7CF"')
    tcp.append(f'fo:wrap-option="{"wrap" if c.wrap else "no-wrap"}"')
    tp = []
    if c.fg:
        tp.append(f'fo:color="{_hex(c.fg)}"')
    if c.bold:
        tp.append('fo:font-weight="bold"')
    if c.italic:
        tp.append('fo:font-style="italic"')
    if c.size:
        tp.append(f'fo:font-size="{c.size:g}pt"')
    if c.font:
        tp.append(f"fo:font-family={quoteattr(c.font)}")
    align = {"left": "start", "right": "end"}.get(c.align, "center")
    return (
        f'<style:style style:name="{name}" style:family="table-cell">'
        f'<style:table-cell-properties {" ".join(tcp)}/>'
        f'<style:paragraph-properties fo:text-align="{align}"/>'
        f'<style:text-properties {" ".join(tp)}/>'
        "</style:style>")


def _fmt_number(v: Union[int, float]) -> str:
    return repr(float(v)) if isinstance(v, float) else str(v)


def _cell_xml(c: Optional[Cell], style: Optional[str],
              covered: bool = False) -> str:
    tag = "table:covered-table-cell" if covered else "table:table-cell"
    st = f' table:style-name="{style}"' if style else ""
    if c is None or c.value is None or c.value == "":
        return f"<{tag}{st}/>"
    span = (f' table:number-columns-spanned="{c.span}"'
            if c.span > 1 and not covered else "")
    v = c.value
    if isinstance(v, bool):           # bool est un int : traité comme texte
        v = str(v)
    if isinstance(v, (int, float)):
        shown = f"{v:g}"
        return (f'<{tag}{st}{span} office:value-type="float" '
                f'office:value="{_fmt_number(v)}"><text:p>{shown}</text:p>'
                f"</{tag}>")
    texte = _clean(str(v))
    paras = "".join(f"<text:p>{escape(p)}</text:p>"
                    for p in texte.split("\n"))
    return (f'<{tag}{st}{span} office:value-type="string">{paras}'
            f"</{tag}>")


def _content_xml(sheets: Sequence[Sheet]) -> str:
    cell_styles: Dict[Tuple, str] = {}
    cell_style_defs: List[str] = []
    col_styles: Dict[float, str] = {}
    col_style_defs: List[str] = []
    row_styles: Dict[float, str] = {}
    row_style_defs: List[str] = []

    def style_for(c: Optional[Cell]) -> Optional[str]:
        if c is None:
            return None
        key = _cell_style_key(c)
        if key not in cell_styles:
            name = f"ce{len(cell_styles) + 1}"
            cell_styles[key] = name
            cell_style_defs.append(_cell_style_xml(name, c))
        return cell_styles[key]

    def col_style(w: float) -> str:
        if w not in col_styles:
            name = f"co{len(col_styles) + 1}"
            col_styles[w] = name
            col_style_defs.append(
                f'<style:style style:name="{name}" '
                'style:family="table-column"><style:table-column-properties '
                f'style:column-width="{w:g}cm"/></style:style>')
        return col_styles[w]

    def row_style(h: float) -> str:
        if h not in row_styles:
            name = f"ro{len(row_styles) + 1}"
            row_styles[h] = name
            row_style_defs.append(
                f'<style:style style:name="{name}" '
                'style:family="table-row"><style:table-row-properties '
                f'style:row-height="{h:g}cm" '
                'style:use-optimal-row-height="false"/></style:style>')
        return row_styles[h]

    tables: List[str] = []
    for sh in sheets:
        ncols = max([len(r) + sum(max(0, (c.span if c else 1) - 1)
                                  for c in r) for r in sh.rows]
                    + [len(sh.col_widths_cm)] or [1])
        parts = [f"<table:table table:name={quoteattr(sh.name)}>"]
        for i in range(ncols):
            w = sh.col_widths_cm[i] if i < len(sh.col_widths_cm) else 2.5
            parts.append(
                f'<table:table-column table:style-name="{col_style(w)}"/>')
        for ri, row in enumerate(sh.rows):
            h = sh.row_heights_cm.get(ri)
            rs = f' table:style-name="{row_style(h)}"' if h else ""
            parts.append(f"<table:table-row{rs}>")
            for c in row:
                parts.append(_cell_xml(c, style_for(c)))
                if c is not None and c.span > 1:
                    parts.extend(_cell_xml(None, style_for(c), covered=True)
                                 for _ in range(c.span - 1))
            parts.append("</table:table-row>")
        parts.append("</table:table>")
        tables.append("".join(parts))

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<office:document-content {_NS}office:version="1.2">'
        "<office:automatic-styles>"
        + "".join(col_style_defs + row_style_defs + cell_style_defs)
        + "</office:automatic-styles><office:body><office:spreadsheet>"
        + "".join(tables)
        + "</office:spreadsheet></office:body></office:document-content>")


def _styles_xml() -> str:
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            f'<office:document-styles {_NS}office:version="1.2">'
            "<office:styles/></office:document-styles>")


def _meta_xml(title: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            f'<office:document-meta {_NS}office:version="1.2">'
            "<office:meta>"
            "<meta:generator>Pénétromètre Silvavenir</meta:generator>"
            f"<dc:title>{escape(_clean(title))}</dc:title>"
            f"<meta:creation-date>{now}</meta:creation-date>"
            "</office:meta></office:document-meta>")


def _manifest_xml() -> str:
    def entry(path: str, mime: str = "text/xml") -> str:
        return ('<manifest:file-entry manifest:full-path="%s" '
                'manifest:media-type="%s"/>' % (path, mime))
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:'
            'opendocument:xmlns:manifest:1.0" manifest:version="1.2">'
            '<manifest:file-entry manifest:full-path="/" '
            f'manifest:media-type="{_ODS_MIME}" manifest:version="1.2"/>'
            + entry("content.xml") + entry("styles.xml") + entry("meta.xml")
            + "</manifest:manifest>")


def write_ods(path: str, sheets: Sequence[Sheet], title: str = "") -> None:
    """Écrit `sheets` dans `path` (.ods). Le fichier n'est créé qu'une fois
    tout le contenu produit en mémoire : une erreur de construction ne laisse
    pas d'archive tronquée."""
    if not sheets:
        raise ValueError("Un classeur ODS doit contenir au moins une feuille.")
    content = _content_xml(sheets)
    # `mimetype` EN PREMIER et NON compressé : exigence de la spécification
    # (les lecteurs détectent ainsi le type sans décompresser).
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), _ODS_MIME,
                   compress_type=zipfile.ZIP_STORED)
        for name, data in (("content.xml", content),
                           ("styles.xml", _styles_xml()),
                           ("meta.xml", _meta_xml(title)),
                           ("META-INF/manifest.xml", _manifest_xml())):
            z.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
