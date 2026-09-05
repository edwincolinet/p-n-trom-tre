"""
Onglet « Export » : point d'entrée UNIQUE de tous les exports.

Avant ce pane (2026-09-05), les exports étaient dispersés entre le menu
Fichier (synthèse mission, toutes les fiches PDF, sondages CSV) et
l'onglet Diagnostic (fiche PDF, PNG, tableau PRBS Excel/HTML) — deux
chemins différents selon qu'on exportait au niveau arbre ou mission,
sans logique de rangement commune. Ce pane regroupe tout, **organisé par
format de fichier** (une section PDF, une PNG, une XLSX, une CSV, une
HTML) plutôt que par portée : chaque bouton précise lui-même s'il porte
sur l'arbre courant ou sur la mission entière.

Le bouton « Imprimer » (impression directe sans dialogue) a été retiré
avec ce rangement : il faisait doublon avec la fiche PDF (l'export PDF
suffit, l'utilisateur l'imprime depuis son lecteur PDF habituel) et son
raccourci Ctrl+P a été retiré avec lui.

Contrat host (Protocol structural) : les 8 `action_export_*` de
`app_export_actions.ExportActionsMixin`. Aucun état propre (pas de
`refresh()` à appeler) — chaque bouton résout l'arbre courant au clic.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, List, Protocol, Tuple

from i18n import _
from tooltip import Tooltip


class _ExportHost(Protocol):
    def action_export_pdf_arbre(self) -> None: ...
    def action_export_pdf_mission(self) -> None: ...
    def action_export_png(self) -> None: ...
    def action_export_prbs_xlsx(self) -> None: ...
    def action_export_prbs_html(self) -> None: ...
    def action_export_csv(self) -> None: ...
    def action_export_synthesis_xlsx(self) -> None: ...
    def action_export_synthesis_csv(self) -> None: ...


# Une entrée = (libellé bouton, commande, tooltip, accent). `accent=True`
# pour l'export le plus fréquent d'une section (style visuel distinct,
# comme l'ancien bouton PDF de l'onglet Diagnostic).
_Item = Tuple[str, Callable[[], None], str, bool]


class ExportPane(ttk.Frame):
    """Pane Tk : une `ttk.LabelFrame` par format, boutons empilés dedans."""

    def __init__(self, master: tk.Misc, host: _ExportHost, **kw: Any) -> None:
        super().__init__(master, style="Panel.TFrame", **kw)
        self._host = host
        self._build()

    def _build(self) -> None:
        content = ttk.Frame(self, style="Panel.TFrame", padding=14)
        content.pack(fill="both", expand=True, anchor="n")

        ttk.Label(content, text=_("Exports"), style="H.TLabel").pack(
            anchor="w", pady=(0, 2))
        ttk.Label(
            content,
            text=_("Chaque bouton précise s'il porte sur l'arbre courant "
                  "ou sur toute la mission."),
            style="Muted.TLabel", wraplength=420, justify="left"
        ).pack(anchor="w", pady=(0, 12))

        h = self._host
        sections: List[Tuple[str, List[_Item]]] = [
            ("PDF", [
                (_("Fiche PDF (arbre courant)"),
                 h.action_export_pdf_arbre,
                 _("Exporter la fiche PDF de l'arbre courant "
                   "(dessin + tableau + diagnostic) — Ctrl+E"),
                 True),
                (_("Exporter toutes les fiches (PDF)…"),
                 h.action_export_pdf_mission,
                 _("Un seul PDF multi-pages regroupant la fiche de "
                   "chaque arbre de la mission."),
                 False),
            ]),
            ("PNG", [
                (_("PNG du dessin"),
                 h.action_export_png,
                 _("Exporter le dessin de la section en image PNG"),
                 False),
            ]),
            ("XLSX", [
                (_("Tableau PRBS — Excel (XLSX)…"),
                 h.action_export_prbs_xlsx,
                 _("Tableau des 16 sondages de l'arbre courant, au "
                   "format Excel."),
                 False),
                (_("Exporter la synthèse mission (XLSX)…"),
                 h.action_export_synthesis_xlsx,
                 _("Une ligne par arbre de la mission (risque, urgence, "
                   "échéance…), triable et filtrable dans Excel."),
                 False),
            ]),
            ("CSV", [
                (_("Exporter sondages mission (CSV)…"),
                 h.action_export_csv,
                 _("Tous les sondages de tous les arbres de la mission, "
                   "un fichier plat."),
                 False),
                (_("Exporter la synthèse mission (CSV)…"),
                 h.action_export_synthesis_csv,
                 _("Même contenu que la synthèse XLSX, au format CSV."),
                 False),
            ]),
            ("HTML", [
                (_("Tableau PRBS — page HTML…"),
                 h.action_export_prbs_html,
                 _("Version imprimable du tableau PRBS de l'arbre "
                   "courant, sans Excel."),
                 False),
            ]),
        ]

        for titre, items in sections:
            self._build_section(content, titre, items)

    def _build_section(self, parent: ttk.Frame, titre: str,
                       items: List[_Item]) -> None:
        box = ttk.LabelFrame(parent, text=f" {titre} ",
                             padding=(10, 8, 10, 10))
        box.pack(fill="x", pady=(0, 10))
        for i, (label, command, tip, accent) in enumerate(items):
            btn = ttk.Button(box, text=label,
                             style="Accent.TButton" if accent
                             else "Ghost.TButton",
                             command=command)
            btn.pack(anchor="w", pady=(0 if i == 0 else 6, 0))
            Tooltip(btn, tip)
