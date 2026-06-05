"""
Onglet « Diagnostic » : boutons d'export, résumé textuel, checkbox
d'affichage des sondages, tableau PRBS par sondage.

C'est le plus gros pane : le contenu vit dans un sous-`tk.Canvas`
scrollable (verticalement) pour rester utilisable même quand la
fenêtre est étroite.

Contrat host (Protocol structural) :
- `_current_arbre()`         : arbre courant ou None.
- `action_export_*`          : 5 actions d'export (PDF, PNG, XLSX,
                                HTML, CSV mission).
- `on_show_sondages_toggled(show)` : notifie l'App du toggle de la
                                checkbox — l'App répercute sur le
                                `SectionCanvas` qu'elle possède.

`refresh()` est appelé à chaque redraw : il met à jour le label de
résumé (`lbl_diag`) et le tableau PRBS par sondage.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Optional, Protocol

from bareme import classer_prbs
from diagnostic import (
    degradation_externe_par_grade,
    diagnostic_summary_lines,
)
from geometry import DIRECTION_LABELS, GRADES
from model import Arbre
from palette import COLOR_PANEL
from tooltip import Tooltip


class _DiagnosticHost(Protocol):
    def _current_arbre(self) -> Optional[Arbre]: ...
    def action_export_pdf_arbre(self) -> None: ...
    def action_export_png(self) -> None: ...
    def action_export_prbs_xlsx(self) -> None: ...
    def action_export_prbs_html(self) -> None: ...
    def action_export_csv(self) -> None: ...


class DiagnosticPane(ttk.Frame):
    """Pane Tk : enveloppe le contenu dans un canvas vertical scrollable."""

    def __init__(self, master: tk.Misc, host: _DiagnosticHost, **kw: Any) -> None:
        super().__init__(master, style="Panel.TFrame", **kw)
        self._host = host
        self._build()

    def _build(self) -> None:
        # Canvas + scrollbar : le contenu peut dépasser verticalement
        # (bandeau d'export + résumé + checkbox + tableau PRBS sur 16 lignes
        # max → ~600 px), on garde tout accessible même en fenêtre
        # étroite.
        diag_canvas = tk.Canvas(self, bg=COLOR_PANEL,
                                 highlightthickness=0, bd=0)
        diag_scroll = ttk.Scrollbar(self, orient="vertical",
                                     command=diag_canvas.yview)
        diag_canvas.configure(yscrollcommand=diag_scroll.set)
        diag_canvas.pack(side="left", fill="both", expand=True)
        diag_scroll.pack(side="right", fill="y")

        content = ttk.Frame(diag_canvas, style="Panel.TFrame", padding=14)
        content_window = diag_canvas.create_window((0, 0), window=content,
                                                     anchor="nw")

        def _on_configure_inner(_e):
            diag_canvas.configure(scrollregion=diag_canvas.bbox("all"))
        def _on_configure_outer(event):
            diag_canvas.itemconfigure(content_window, width=event.width)
        content.bind("<Configure>", _on_configure_inner)
        diag_canvas.bind("<Configure>", _on_configure_outer)

        # Molette : bindings globaux N'ACTIVÉS QUE si pointeur sur ce
        # canvas — sinon la molette détourne le scroll des autres
        # onglets (cf. correctif Tier 1).
        def _on_mousewheel(event):
            diag_canvas.yview_scroll(int(-event.delta / 120), "units")
        def _on_mousewheel_linux(event):
            diag_canvas.yview_scroll(-1 if event.num == 4 else 1, "units")
        def _bind_wheel(_e):
            diag_canvas.bind_all("<MouseWheel>", _on_mousewheel)
            diag_canvas.bind_all("<Button-4>", _on_mousewheel_linux)
            diag_canvas.bind_all("<Button-5>", _on_mousewheel_linux)
        def _unbind_wheel(_e):
            diag_canvas.unbind_all("<MouseWheel>")
            diag_canvas.unbind_all("<Button-4>")
            diag_canvas.unbind_all("<Button-5>")
        diag_canvas.bind("<Enter>", _bind_wheel)
        diag_canvas.bind("<Leave>", _unbind_wheel)

        self._build_content(content)

    def _build_content(self, parent: ttk.Frame) -> None:
        # --- Boutons d'export EN HAUT (toujours accessibles) ---
        # Le livrable (fiche PDF) et l'image (PNG) restent en boutons
        # directs ; les 3 exports de tableau (XLSX/HTML/CSV) — variantes
        # de format d'une même donnée — sont regroupés sous un menu
        # déroulant pour alléger la barre (5 boutons → 2 boutons + 1 menu).
        btn_exp = ttk.Frame(parent, style="Panel.TFrame")
        btn_exp.pack(fill="x", pady=(0, 12))
        btn_pdf = ttk.Button(btn_exp, text="📄 Fiche PDF (arbre courant)",
                             style="Accent.TButton",
                             command=self._host.action_export_pdf_arbre)
        btn_pdf.pack(side="left", padx=(0, 6))
        Tooltip(btn_pdf, "Exporter la fiche PDF de l'arbre courant "
                         "(dessin + tableau + diagnostic) — Ctrl+E")
        btn_png = ttk.Button(btn_exp, text="🖼 PNG du dessin",
                             style="Ghost.TButton",
                             command=self._host.action_export_png)
        btn_png.pack(side="left", padx=(0, 6))
        Tooltip(btn_png, "Exporter le dessin de la section en image PNG")

        mb_table = ttk.Menubutton(btn_exp, text="📊 Exporter le tableau",
                                  style="Ghost.TMenubutton", direction="below")
        table_menu = tk.Menu(mb_table, tearoff=0)
        table_menu.add_command(
            label="Tableau PRBS — Excel (XLSX)…",
            command=self._host.action_export_prbs_xlsx)
        table_menu.add_command(
            label="Tableau PRBS — page HTML…",
            command=self._host.action_export_prbs_html)
        table_menu.add_separator()
        table_menu.add_command(
            label="Sondages de la mission (CSV)…",
            command=self._host.action_export_csv)
        mb_table["menu"] = table_menu
        mb_table.pack(side="left")
        Tooltip(mb_table,
                "Exporter le tableau PRBS de l'arbre (Excel / HTML) ou "
                "tous les sondages de la mission (CSV)")

        # --- Bloc résumé haut ---
        ttk.Label(parent, text="Résumé de l'arbre courant",
                  style="H.TLabel").pack(anchor="w", pady=(4, 4))
        self.lbl_diag = ttk.Label(
            parent, text="", style="Panel.TLabel",
            wraplength=400, justify="left", font=("Helvetica", 10))
        self.lbl_diag.pack(anchor="w", fill="x", pady=(0, 10))

        # --- Tableau PRBS par sondage ---
        ttk.Label(parent, text="Paroi Résiduelle de Bois Sain par sondage",
                  style="H.TLabel").pack(anchor="w", pady=(4, 4))
        ttk.Label(parent,
                  text="Classe colorée selon t/R et le port (barème "
                       "Silvavenir).",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 6))

        prbs_frame = ttk.Frame(parent, style="Panel.TFrame")
        prbs_frame.pack(fill="x", pady=(0, 10))
        cols = ("n", "dir", "prbs", "tR", "classe")
        self.tbl_prbs = ttk.Treeview(prbs_frame, columns=cols,
                                      show="headings", height=8)
        self.tbl_prbs.heading("n", text="N°")
        self.tbl_prbs.heading("dir", text="Direction")
        self.tbl_prbs.heading("prbs", text="PRBS (cm)")
        self.tbl_prbs.heading("tR", text="t/R (%)")
        self.tbl_prbs.heading("classe", text="Classe")
        self.tbl_prbs.column("n", width=35, anchor="center")
        self.tbl_prbs.column("dir", width=80, anchor="center")
        self.tbl_prbs.column("prbs", width=85, anchor="center")
        self.tbl_prbs.column("tR", width=70, anchor="center")
        self.tbl_prbs.column("classe", width=90, anchor="center")
        self.tbl_prbs.pack(side="left", fill="x", expand=True)
        self.tbl_prbs.tag_configure(
            "vert",   background="#E3F1E6", foreground="#1A5A2A")
        self.tbl_prbs.tag_configure(
            "orange", background="#FDEBD5", foreground="#8A4A10")
        self.tbl_prbs.tag_configure(
            "rouge",  background="#FADBD8", foreground="#7B1B12")

    def refresh(self) -> None:
        """Recharge le tableau PRBS et le résumé textuel à partir de
        l'arbre courant. Appelé par App._redraw_all après le debounce."""
        a = self._host._current_arbre()

        # --- Tableau PRBS par sondage ---
        self.tbl_prbs.delete(*self.tbl_prbs.get_children())
        if a and a.rayon_tronc_cm > 0:
            R = a.rayon_tronc_cm
            port = a.port_arbre
            deg_ext_par_grade = degradation_externe_par_grade(a)
            for s in a.sondages:
                direction = DIRECTION_LABELS.get(s.grade, "")
                if not direction and s.grade in GRADES:
                    idx = GRADES.index(s.grade)
                    for delta in (1, -1, 2, -2):
                        g2 = GRADES[(idx + delta) % 16]
                        if DIRECTION_LABELS.get(g2):
                            direction = f"~{DIRECTION_LABELS[g2]}"
                            break
                # PRBS ajustée = bois sain mesuré - dégradation externe
                # qui couvre cette direction.
                idx_grade = GRADES.index(s.grade) if s.grade in GRADES else 0
                deg_ext = deg_ext_par_grade[idx_grade]
                prbs_adj = max(0.0, s.prbs_cm - deg_ext)
                ratio = prbs_adj / R if R > 0 else 0.0
                classe = classer_prbs(ratio, port)
                tag = classe.lower()
                if deg_ext > 0:
                    prbs_txt = f"{prbs_adj:g} (–{deg_ext:g} ext.)"
                else:
                    prbs_txt = f"{prbs_adj:g}"
                self.tbl_prbs.insert(
                    "", "end",
                    values=(s.numero, f"{direction} ({s.grade} gr)",
                            prbs_txt,
                            f"{100*ratio:.1f}",
                            classe),
                    tags=(tag,))

        # --- Texte de résumé enrichi ---
        if not a:
            self.lbl_diag.configure(
                text="Renseignez le rayon du tronc et ajoutez des "
                     "sondages pour obtenir un résumé.")
            return
        self.lbl_diag.configure(
            text="\n".join(diagnostic_summary_lines(a)))
