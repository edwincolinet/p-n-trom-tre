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
from typing import TYPE_CHECKING, Any, Callable, Optional

import app_exports
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
        chantier: Chantier
        current_file: "Optional[_Path]"
        var_show_sondages: tk.BooleanVar

        def _current_arbre(self) -> Optional[Arbre]: ...
        # Fourni par `FichierMixin` — export comparaison (cf. plus bas).
        def _export_comparison(self, fmt: str,
                               builder: Callable[[], Any],
                               parent: "tk.Misc") -> None: ...

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
        if etype.needs_comparison:
            from comparaison import is_comparison_active
            if not is_comparison_active():
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

    def action_export_png(self) -> None:
        app_exports.export_dessin_arbre(self, self._current_arbre(),
                                        self.var_show_sondages.get(), "png")

    def action_export_jpeg(self) -> None:
        app_exports.export_dessin_arbre(self, self._current_arbre(),
                                        self.var_show_sondages.get(), "jpeg")

    def action_export_png_mission(self) -> None:
        app_exports.export_dessin_mission(self, self.chantier,
                                          self.var_show_sondages.get(), "png")

    def action_export_jpeg_mission(self) -> None:
        app_exports.export_dessin_mission(self, self.chantier,
                                          self.var_show_sondages.get(), "jpeg")

    def action_export_pdf_arbre(self) -> None:
        app_exports.export_pdf_arbre(self, self._current_arbre(),
                                     self.chantier,
                                     self.var_show_sondages.get(),
                                     mission_file=self.current_file)

    def action_export_pdf_mission(self) -> None:
        app_exports.export_pdf_mission(self, self.chantier,
                                       self.var_show_sondages.get(),
                                       mission_file=self.current_file)

    def action_export_csv(self) -> None:
        app_exports.export_csv_mission(self, self.chantier)

    def action_export_synthesis_xlsx(self) -> None:
        app_exports.export_synthesis_xlsx_mission(self, self.chantier)

    def action_export_synthesis_csv(self) -> None:
        app_exports.export_synthesis_csv_mission(self, self.chantier)

    def action_export_prbs_xlsx(self) -> None:
        app_exports.export_xlsx_arbre(self, self._current_arbre(),
                                      self.chantier)

    def action_export_prbs_html(self) -> None:
        app_exports.export_html_arbre(self, self._current_arbre(),
                                      self.chantier)

    def action_export_prbs_ods(self) -> None:
        app_exports.export_ods_arbre(self, self._current_arbre(),
                                     self.chantier)

    def action_export_prbs_xlsx_mission(self) -> None:
        app_exports.export_tableaux_mission(self, self.chantier, "xlsx")

    def action_export_prbs_ods_mission(self) -> None:
        app_exports.export_tableaux_mission(self, self.chantier, "ods")

    def action_export_prbs_html_mission(self) -> None:
        app_exports.export_tableaux_mission(self, self.chantier, "html")

    def action_export_synthesis_ods(self) -> None:
        app_exports.export_synthesis_ods_mission(self, self.chantier)

    # --- Comparaison (ré-inspection) ------------------------------------
    # Ne vivent plus dans des boutons de `comparaison.py` (coupaient du
    # menu Export pendant que la fenêtre était ouverte) : entrées du menu
    # Export, activées seulement si une comparaison est en cours
    # (`comparaison.is_comparison_active`, relu par un `postcommand` sur
    # le menu dans `app_menu.py` — pas d'état à synchroniser à la main).

    def action_export_comparison_pdf(self) -> None:
        from comparaison import export_active_comparison, get_comparison_window
        builder = export_active_comparison("pdf")
        if builder is None:
            return
        self._export_comparison("pdf", builder, get_comparison_window() or self)

    def action_export_comparison_png(self) -> None:
        from comparaison import export_active_comparison, get_comparison_window
        builder = export_active_comparison("png")
        if builder is None:
            return
        self._export_comparison("png", builder, get_comparison_window() or self)
