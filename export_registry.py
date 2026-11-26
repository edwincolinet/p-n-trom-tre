"""
Registre des exports : **type d'export → portée → formats**.

Module pur (stdlib + `i18n`), sans Tk. Le menu Export liste les TYPES
d'export (fiche d'expertise, dessin de section, tableau PRBS…), pas les
formats de fichier : cliquer sur un type ouvre un dialogue unique qui
demande la portée (arbre courant / toute la mission) et le format. Ajouter
un format = ajouter une ligne `ExportFormat` ici, sans toucher au menu ni
au dialogue.

Chaque format désigne l'**action** à exécuter par son nom de méthode de
`App` (`action_export_*`, cf. `app_export_actions.ExportActionsMixin`) :
le registre ne dépend d'aucun module d'export.

Les libellés sont construits À L'APPEL (`export_types()`), pas à
l'import : la langue d'interface est alors prise en compte, et le test
d'i18n voit chaque `_("…")`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from i18n import _


@dataclass(frozen=True)
class ExportFormat:
    """Un format de fichier pour une portée donnée."""
    key: str      # identifiant stable ("pdf", "xlsx"…)
    label: str    # libellé affiché
    action: str   # nom de la méthode `App.action_export_*` à appeler


@dataclass(frozen=True)
class ExportScope:
    """Ce que l'export couvre (arbre courant, toute la mission…) et les
    formats disponibles pour cette portée."""
    key: str
    label: str
    formats: Tuple[ExportFormat, ...]


@dataclass(frozen=True)
class ExportType:
    """Un type d'export (une entrée du menu Export)."""
    key: str
    label: str
    scopes: Tuple[ExportScope, ...]
    # Exports qui n'existent que si l'arbre courant a un relevé antérieur
    # (entrée grisée sinon).
    needs_history: bool = False

    @property
    def needs_dialog(self) -> bool:
        """Faux s'il n'y a rien à choisir (une seule portée ET un seul
        format) : l'export part alors directement, sans dialogue."""
        return (len(self.scopes) > 1
                or any(len(s.formats) > 1 for s in self.scopes))

    def scope(self, key: str) -> Optional[ExportScope]:
        return next((s for s in self.scopes if s.key == key), None)

    def format(self, scope_key: str, format_key: str
               ) -> Optional[ExportFormat]:
        sc = self.scope(scope_key)
        if sc is None:
            return None
        return next((f for f in sc.formats if f.key == format_key), None)

    def default_choice(self) -> Tuple[str, str]:
        """(portée, format) proposés par défaut : le premier de chaque."""
        sc = self.scopes[0]
        return sc.key, sc.formats[0].key


SCOPE_ARBRE = "arbre"
SCOPE_MISSION = "mission"


def export_types() -> Tuple[ExportType, ...]:
    """Les types d'export, dans l'ordre d'affichage du menu."""
    arbre = _("Arbre courant")
    mission = _("Toute la mission")
    # Une image par arbre, rangées dans un dossier (≠ un fichier unique).
    mission_dossier = _("Toute la mission (un fichier par arbre)")
    # Un seul fichier regroupant tous les tableaux.
    mission_tableaux = _("Toute la mission (un seul fichier)")
    return (
        ExportType("fiche", _("Fiche d'expertise"), (
            ExportScope(SCOPE_ARBRE, arbre, (
                ExportFormat("pdf", "PDF", "action_export_pdf_arbre"),)),
            ExportScope(SCOPE_MISSION, mission, (
                ExportFormat("pdf", "PDF", "action_export_pdf_mission"),)),
        )),
        ExportType("dessin", _("Dessin de la section"), (
            ExportScope(SCOPE_ARBRE, arbre, (
                ExportFormat("png", "PNG", "action_export_png"),
                ExportFormat("jpeg", "JPEG", "action_export_jpeg"),
            )),
            ExportScope(SCOPE_MISSION, mission_dossier, (
                ExportFormat("png", "PNG", "action_export_png_mission"),
                ExportFormat("jpeg", "JPEG", "action_export_jpeg_mission"),
            )),
        )),
        ExportType("tableau_prbs", _("Tableau PRBS"), (
            ExportScope(SCOPE_ARBRE, arbre, (
                ExportFormat("xlsx", _("Excel (XLSX)"),
                             "action_export_prbs_xlsx"),
                ExportFormat("ods", _("LibreOffice (ODS)"),
                             "action_export_prbs_ods"),
                ExportFormat("html", _("Page web (HTML)"),
                             "action_export_prbs_html"),
            )),
            # Un seul fichier : une feuille par arbre (XLSX/ODS), une section
            # par arbre (HTML).
            ExportScope(SCOPE_MISSION, mission_tableaux, (
                ExportFormat("xlsx", _("Excel (XLSX)"),
                             "action_export_prbs_xlsx_mission"),
                ExportFormat("ods", _("LibreOffice (ODS)"),
                             "action_export_prbs_ods_mission"),
                ExportFormat("html", _("Page web (HTML)"),
                             "action_export_prbs_html_mission"),
            )),
        )),
        ExportType("sondages", _("Sondages de la mission"), (
            ExportScope(SCOPE_MISSION, mission, (
                ExportFormat("csv", "CSV", "action_export_csv"),)),
        )),
        ExportType("synthese", _("Synthèse de la mission"), (
            ExportScope(SCOPE_MISSION, mission, (
                ExportFormat("xlsx", _("Excel (XLSX)"),
                             "action_export_synthesis_xlsx"),
                ExportFormat("ods", _("LibreOffice (ODS)"),
                             "action_export_synthesis_ods"),
                ExportFormat("csv", "CSV", "action_export_synthesis_csv"),
            )),
        )),
        ExportType("comparaison", _("Évolution (ré-inspection)"), (
            ExportScope("comparaison", _("Dates de l'onglet Évolution"), (
                ExportFormat("pdf", _("Fiche PDF"),
                             "action_export_comparison_pdf"),
                ExportFormat("png", _("Évolution (PNG)"),
                             "action_export_comparison_png"),
            )),
        ), needs_history=True),
    )


def get_export_type(key: str) -> Optional[ExportType]:
    return next((t for t in export_types() if t.key == key), None)
