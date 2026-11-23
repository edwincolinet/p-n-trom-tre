"""
Exports du tableau PRBS de **toute la mission** : un tableau par arbre, dans
un seul fichier.

- **XLSX / ODS** : un classeur, une feuille par arbre (« Arbre 12 »), précédée
  d'une feuille « Synthèse » (une ligne par arbre) quand les lignes de
  synthèse sont fournies.
- **HTML** : une page unique, un sommaire cliquable et une section par arbre
  (saut de page à l'impression).

Chaque tableau est EXACTEMENT celui de l'export d'un seul arbre (mêmes
fonctions de remplissage : `export._fill_prbs_sheet` / `export.prbs_sheet` /
`export._html_arbre_section`) — pas de seconde mise en page à maintenir.

Module pur (aucun Tk) : l'adaptateur UI (dialogue de fichier, progression,
contrôle de complétude) est dans `app_exports`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Mapping, Optional, Sequence

import export as _exp
from export import (
    _NOM_PRODUIT,
    ArbreLike,
    ChantierLike,
    ClasserPrbs,
    _h,
    _html_arbre_section,
    _html_meta,
    _html_page,
)
from export_synthesis import _fill_synthesis_sheet, synthesis_sheet
from i18n import _
from ods_writer import Sheet, safe_sheet_name, write_ods

if TYPE_CHECKING:
    from diagnostic import MissionSynthesisRow  # noqa: F401


def noms_feuilles(arbres: Sequence[ArbreLike],
                  reserves: Sequence[str] = ()) -> List[str]:
    """Nom de feuille de chaque arbre (« Arbre <n°> ») : valide et **unique**
    (casse ignorée) y compris vis-à-vis des noms `reserves` (feuille
    « Synthèse »). Deux arbres de même n° reçoivent « (2) », « (3) »…"""
    utilises: List[str] = list(reserves)
    noms: List[str] = []
    for a in arbres:
        base = (_("Arbre") + f" {a.numero_arbre}" if a.numero_arbre
                else _("Arbre"))
        nom = safe_sheet_name(base, utilises)
        utilises.append(nom)
        noms.append(nom)
    return noms


def export_prbs_mission_xlsx(
        arbres: Sequence[ArbreLike], chantier: ChantierLike, path: str,
        couleur_classe: Mapping[str, str], classer_prbs: ClasserPrbs,
        cabinet_name: str = "", bareme_desc: str = "",
        synthese: "Optional[Sequence[MissionSynthesisRow]]" = None) -> None:
    """Classeur .xlsx : feuille « Synthèse » (si `synthese`) puis une feuille
    par arbre. Nécessite openpyxl."""
    if not _exp.HAS_OPENPYXL:
        raise RuntimeError(
            "openpyxl n'est pas installé. Lancer "
            "`pip install -r requirements.txt`.")
    if not arbres:
        raise ValueError("Aucun arbre à exporter.")
    wb = _exp.Workbook()
    ws = wb.active
    reserves: List[str] = []
    if synthese is not None:
        ws.title = safe_sheet_name(_("Synthèse"))
        reserves.append(ws.title)
        _fill_synthesis_sheet(ws, synthese, chantier, couleur_classe,
                              bareme_desc)
        ws = None
    for nom, arbre in zip(noms_feuilles(arbres, reserves), arbres):
        if ws is None:
            ws = wb.create_sheet()
        ws.title = nom
        _exp._fill_prbs_sheet(ws, arbre, chantier, couleur_classe,
                              classer_prbs, cabinet_name, bareme_desc)
        ws = None
    wb.save(path)


def export_prbs_mission_ods(
        arbres: Sequence[ArbreLike], chantier: ChantierLike, path: str,
        couleur_classe: Mapping[str, str], classer_prbs: ClasserPrbs,
        cabinet_name: str = "", bareme_desc: str = "",
        synthese: "Optional[Sequence[MissionSynthesisRow]]" = None) -> None:
    """Classeur .ods : même contenu que `export_prbs_mission_xlsx`. Aucune
    dépendance (cf. `ods_writer`)."""
    if not arbres:
        raise ValueError("Aucun arbre à exporter.")
    feuilles: List[Sheet] = []
    reserves: List[str] = []
    if synthese is not None:
        sh = synthesis_sheet(synthese, chantier, couleur_classe, bareme_desc)
        sh.name = safe_sheet_name(sh.name)
        reserves.append(sh.name)
        feuilles.append(sh)
    for nom, arbre in zip(noms_feuilles(arbres, reserves), arbres):
        feuilles.append(_exp.prbs_sheet(
            arbre, chantier, couleur_classe, classer_prbs, cabinet_name,
            bareme_desc, name=nom))
    write_ods(path, feuilles,
              title=f"{_NOM_PRODUIT} — {chantier.nom or _('Mission')}")


_MISSION_CSS = """
nav.sommaire { margin: 4px 0 8px 0; font-size: 13px; color: #595959; }
nav.sommaire a { color: #385623; margin-right: 14px; white-space: nowrap; }
section.arbre { margin-top: 34px; padding-top: 6px;
                border-top: 2px solid #D9D7CF; }
@media print { section.arbre { page-break-before: always; border-top: 0;
                               margin-top: 0; }
               nav.sommaire { display: none; } }
"""


def export_prbs_mission_html(
        arbres: Sequence[ArbreLike], chantier: ChantierLike, path: str,
        couleur_classe: Mapping[str, str], classer_prbs: ClasserPrbs,
        cabinet_name: str = "", bareme_desc: str = "") -> None:
    """Page .html unique : sommaire + une section par arbre. Aucun fichier
    externe (CSS embarqué)."""
    if not arbres:
        raise ValueError("Aucun arbre à exporter.")
    liens = "".join(
        f'<a href="#arbre-{i}">'
        f'{_h(a.numero_arbre or _("Arbre") + f" {i}")}</a>'
        for i, a in enumerate(arbres, start=1))
    sections = "\n".join(
        f'<section class="arbre" id="arbre-{i}">\n'
        + _html_arbre_section(a, couleur_classe, classer_prbs, bareme_desc)
        + "\n</section>"
        for i, a in enumerate(arbres, start=1))
    corps = (f'<nav class="sommaire">{_h(_("Arbres"))} : {liens}</nav>\n'
             + sections)
    nom = chantier.nom or _("Mission")
    page = _html_page(
        f"{_NOM_PRODUIT} — {nom}", f"{_NOM_PRODUIT} — {nom}",
        _html_meta(chantier), corps, cabinet_name, extra_css=_MISSION_CSS)
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)
