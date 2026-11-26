"""
Actions d'export câblées sur l'App (mixin de `App`).

Fine couche de raccordement : chaque méthode `action_export_*` est une
commande utilisateur (entrée de menu) qui résout l'arbre courant + le
chantier, puis délègue à la fonction adaptatrice de `app_exports`
(laquelle gère filedialog, vérif Pillow/openpyxl, try/except + log et le
feedback de succès). Ces noms sont appelés par `app_menu.py` (menu
Export, groupé par format, seul point d'entrée UI des exports depuis le
2026-09-05) : ils doivent rester des méthodes de `App`.

Mixin de `App` : s'appuie sur les attributs/méthodes déclarés en
`TYPE_CHECKING`, fournis par l'hôte.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox
from typing import TYPE_CHECKING, Any, Callable, Optional

import app_exports
from i18n import _
from model import Arbre, Chantier

# Cf. note dans `app_recovery` : base `tk.Tk` pour mypy (self = widget),
# `object` au runtime.
if TYPE_CHECKING:
    _MixinBase = tk.Tk
else:
    _MixinBase = object


class ExportActionsMixin(_MixinBase):
    """Méthodes `action_export_*`. Mixin de `App`."""

    if TYPE_CHECKING:
        from pathlib import Path as _Path

        from app_settings import SettingsStore
        from pane_evolution import EvolutionPane
        chantier: Chantier
        current_file: "Optional[_Path]"
        var_show_sondages: tk.BooleanVar

        def _current_arbre(self) -> Optional[Arbre]: ...
        # Fourni par `FichierMixin` — export de l'évolution (cf. plus bas).
        def _export_comparison(
            self, fmt: str,
            builder: "Optional[Callable[[], Any]]") -> None: ...
        pane_evo: Optional[EvolutionPane]
        _settings: SettingsStore

    def action_export_choose(self, type_key: str) -> None:
        """Point d'entrée UNIQUE du menu Export : un TYPE d'export
        (`export_registry`). Demande portée + format dans un dialogue
        unique (omis s'il n'y a rien à choisir), puis lance l'action
        `action_export_*` correspondante."""
        from dialogs_export import ask_export_choice
        from export_registry import get_export_type
        etype = get_export_type(type_key)
        if etype is None:
            return
        if etype.needs_history:
            a = self._current_arbre()
            if a is None or not a.campagnes:
                return
        if etype.needs_dialog:
            choice = ask_export_choice(self, etype)
            if choice is None:
                return
        else:
            choice = etype.default_choice()
        fmt = etype.format(*choice)
        if fmt is None:
            return
        getattr(self, fmt.action)()

    # --- Garde-fou : pas de livrable avec des valeurs reprises -----------
    # Un export est la version définitive remise au client : il est refusé
    # tant qu'un sondage repris d'un relevé précédent n'a pas été actualisé.

    def _arbre_a_exporter(self) -> "list[Arbre]":
        a = self._current_arbre()
        return [a] if a is not None else []

    def _non_actualises(self, arbres: "list[Arbre]") -> bool:
        """Vrai (et message affiché) s'il faut refuser l'export."""
        comptes = [(a.numero_arbre or "?",
                    sum(s.a_confirmer for b in a.brins for s in b.sondages))
                   for a in arbres]
        comptes = [(numero, n) for numero, n in comptes if n]
        if not comptes:
            return False
        total = sum(n for _numero, n in comptes)
        detail = ", ".join(f"n° {numero} ({n})"
                           for numero, n in comptes[:8])
        if len(comptes) > 8:
            detail += ", …"
        messagebox.showerror(_("Export impossible"), _(
            "{n} sondage(s) n'ont pas été actualisé(s).\n\nArbre(s) : {d}"
            "\n\nRetapez ou validez ces valeurs dans l'onglet Sondages."
        ).format(n=total, d=detail))
        return True

    def action_export_png(self) -> None:
        if self._non_actualises(self._arbre_a_exporter()):
            return
        app_exports.export_dessin_arbre(self, self._current_arbre(),
                                        self.var_show_sondages.get(), "png")

    def action_export_jpeg(self) -> None:
        if self._non_actualises(self._arbre_a_exporter()):
            return
        app_exports.export_dessin_arbre(self, self._current_arbre(),
                                        self.var_show_sondages.get(), "jpeg")

    def action_export_png_mission(self) -> None:
        if self._non_actualises(self.chantier.arbres):
            return
        app_exports.export_dessin_mission(self, self.chantier,
                                          self.var_show_sondages.get(), "png")

    def action_export_jpeg_mission(self) -> None:
        if self._non_actualises(self.chantier.arbres):
            return
        app_exports.export_dessin_mission(self, self.chantier,
                                          self.var_show_sondages.get(), "jpeg")

    def action_export_pdf_arbre(self) -> None:
        if self._non_actualises(self._arbre_a_exporter()):
            return
        app_exports.export_pdf_arbre(self, self._current_arbre(),
                                     self.chantier,
                                     self.var_show_sondages.get(),
                                     mission_file=self.current_file)

    def action_export_pdf_mission(self) -> None:
        if self._non_actualises(self.chantier.arbres):
            return
        app_exports.export_pdf_mission(self, self.chantier,
                                       self.var_show_sondages.get(),
                                       mission_file=self.current_file)

    def action_export_csv(self) -> None:
        if self._non_actualises(self.chantier.arbres):
            return
        app_exports.export_csv_mission(self, self.chantier)

    def action_export_synthesis_xlsx(self) -> None:
        if self._non_actualises(self.chantier.arbres):
            return
        app_exports.export_synthesis_xlsx_mission(self, self.chantier)

    def action_export_synthesis_csv(self) -> None:
        if self._non_actualises(self.chantier.arbres):
            return
        app_exports.export_synthesis_csv_mission(self, self.chantier)

    def action_export_prbs_xlsx(self) -> None:
        if self._non_actualises(self._arbre_a_exporter()):
            return
        app_exports.export_xlsx_arbre(self, self._current_arbre(),
                                      self.chantier)

    def action_export_prbs_html(self) -> None:
        if self._non_actualises(self._arbre_a_exporter()):
            return
        app_exports.export_html_arbre(self, self._current_arbre(),
                                      self.chantier)

    def action_export_prbs_ods(self) -> None:
        if self._non_actualises(self._arbre_a_exporter()):
            return
        app_exports.export_ods_arbre(self, self._current_arbre(),
                                     self.chantier)

    def action_export_prbs_xlsx_mission(self) -> None:
        if self._non_actualises(self.chantier.arbres):
            return
        app_exports.export_tableaux_mission(self, self.chantier, "xlsx")

    def action_export_prbs_ods_mission(self) -> None:
        if self._non_actualises(self.chantier.arbres):
            return
        app_exports.export_tableaux_mission(self, self.chantier, "ods")

    def action_export_prbs_html_mission(self) -> None:
        if self._non_actualises(self.chantier.arbres):
            return
        app_exports.export_tableaux_mission(self, self.chantier, "html")

    def action_export_synthesis_ods(self) -> None:
        if self._non_actualises(self.chantier.arbres):
            return
        app_exports.export_synthesis_ods_mission(self, self.chantier)

    # --- Évolution (ré-inspection) --------------------------------------
    # Les dates comparées sont celles choisies dans l'onglet Évolution.

    def _export_evolution(self, fmt: str) -> None:
        if self.pane_evo is None:
            return
        choisis = self.pane_evo.selection()
        if choisis is None or self._non_actualises([choisis[1].arbre]):
            return
        self._export_comparison(fmt, self.pane_evo.constructeur_export(
            fmt, cabinet_name=self._settings.cabinet_name,
            logo_path=self._settings.logo_path))

    def action_export_comparison_pdf(self) -> None:
        self._export_evolution("pdf")

    def action_export_comparison_png(self) -> None:
        self._export_evolution("png")
