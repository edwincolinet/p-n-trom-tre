"""
Actions d'export câblées sur l'App (mixin de `App`).

Fine couche de raccordement : chaque méthode `action_export_*` est une
commande utilisateur (bouton/menu) qui résout l'arbre courant + le
chantier, puis délègue à la fonction adaptatrice de `app_exports`
(laquelle gère filedialog, vérif Pillow/openpyxl, try/except + log et le
feedback de succès). Ces noms sont appelés par `app_menu.py` et
`pane_diagnostic.py` : ils doivent rester des méthodes de `App`.

Mixin de `App` : s'appuie sur les attributs/méthodes déclarés en
`TYPE_CHECKING`, fournis par l'hôte.
"""

from __future__ import annotations

import tkinter as tk
from typing import TYPE_CHECKING, Optional

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
        chantier: Chantier
        var_show_sondages: tk.BooleanVar

        def _current_arbre(self) -> Optional[Arbre]: ...

    def action_export_png(self) -> None:
        app_exports.export_png(self, self._current_arbre(),
                               self.var_show_sondages.get())

    def action_export_pdf_arbre(self) -> None:
        app_exports.export_pdf_arbre(self, self._current_arbre(),
                                     self.chantier,
                                     self.var_show_sondages.get())

    def action_export_pdf_mission(self) -> None:
        app_exports.export_pdf_mission(self, self.chantier,
                                       self.var_show_sondages.get())

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
