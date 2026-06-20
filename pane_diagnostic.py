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
    FUSION_WARN_TEXT,
    degradation_externe_par_grade,
    genet_summary_tagged,
)
from dialogs import ask_date
from dialogs_settings import ask_suivi_custom, ask_urgences_custom
from dialogs_shared import SUIVI_VALIDITES, normaliser_date
from geometry import DIRECTION_LABELS, GRADES
from i18n import _
from model import URGENCE_NIVEAUX, Arbre
from palette import COLOR_MUTED, COLOR_PANEL, COLOR_WARN
from tooltip import Tooltip
from ui_fonts import font as ui_font

# Premier item des comboboxes = « non renseignée » (stocke "").
_URGENCE_VIDE = "— Non renseignée —"
_SUIVI_VIDE = "— Non renseignée —"


class _DiagnosticHost(Protocol):
    def _current_arbre(self) -> Optional[Arbre]: ...
    def action_export_pdf_arbre(self) -> None: ...
    def action_print_arbre(self) -> None: ...
    def action_export_png(self) -> None: ...
    def action_export_prbs_xlsx(self) -> None: ...
    def action_export_prbs_html(self) -> None: ...
    def action_export_csv(self) -> None: ...
    # Préconisation (urgence / échéance / texte / suivi) — édition + undo/dirty.
    def on_preconisation_changed(self) -> None: ...
    def push_undo(self) -> None: ...
    def capture_undo_snapshot(self) -> dict: ...
    def push_undo_snapshot(self, snap: dict) -> None: ...
    def get_urgences_custom(self) -> "list[str]": ...
    def set_urgences_custom(self, values: "list[str]") -> None: ...
    def get_suivi_custom(self) -> "list[str]": ...
    def set_suivi_custom(self, values: "list[str]") -> None: ...


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
        btn_pdf = ttk.Button(btn_exp, text=_("📄 Fiche PDF (arbre courant)"),
                             style="Accent.TButton",
                             command=self._host.action_export_pdf_arbre)
        btn_pdf.pack(side="left", padx=(0, 6))
        Tooltip(btn_pdf, "Exporter la fiche PDF de l'arbre courant "
                         "(dessin + tableau + diagnostic) — Ctrl+E")
        btn_print = ttk.Button(btn_exp, text=_("🖨 Imprimer"),
                               style="Ghost.TButton",
                               command=self._host.action_print_arbre)
        btn_print.pack(side="left", padx=(0, 6))
        Tooltip(btn_print, "Imprimer la fiche PDF directement "
                           "(sans dialogue de sauvegarde) — Ctrl+P")
        btn_png = ttk.Button(btn_exp, text=_("🖼 PNG du dessin"),
                             style="Ghost.TButton",
                             command=self._host.action_export_png)
        btn_png.pack(side="left", padx=(0, 6))
        Tooltip(btn_png, "Exporter le dessin de la section en image PNG")

        mb_table = ttk.Menubutton(btn_exp, text=_("📊 Exporter le tableau"),
                                  style="Ghost.TMenubutton", direction="below")
        table_menu = tk.Menu(mb_table, tearoff=0)
        table_menu.add_command(
            label=_("Tableau PRBS — Excel (XLSX)…"),
            command=self._host.action_export_prbs_xlsx)
        table_menu.add_command(
            label=_("Tableau PRBS — page HTML…"),
            command=self._host.action_export_prbs_html)
        table_menu.add_separator()
        table_menu.add_command(
            label=_("Sondages de la mission (CSV)…"),
            command=self._host.action_export_csv)
        mb_table["menu"] = table_menu
        mb_table.pack(side="left")
        Tooltip(mb_table,
                "Exporter le tableau PRBS de l'arbre (Excel / HTML) ou "
                "tous les sondages de la mission (CSV)")

        # --- Bloc résumé haut ---
        ttk.Label(parent, text=_("Résumé de l'arbre courant"),
                  style="H.TLabel").pack(anchor="w", pady=(4, 4))
        self._txt_diag = tk.Text(
            parent, state="disabled", wrap="word", relief="flat", bd=0,
            bg=COLOR_PANEL, cursor="arrow", takefocus=False,
            font=ui_font("Helvetica", 10), height=1)
        self._txt_diag.tag_configure("vert",   foreground="#2D7A3E")
        self._txt_diag.tag_configure("orange", foreground="#C25C00")
        self._txt_diag.tag_configure("rouge",  foreground="#C0392B")
        self._txt_diag.tag_configure("warn",   foreground=COLOR_WARN)
        self._txt_diag.pack(anchor="w", fill="x", pady=(0, 10))

        # --- Bloc Préconisation (la décision = le livrable) ---
        self._build_preconisation(parent)

        # --- Tableau PRBS par sondage ---
        ttk.Label(parent, text=_("Paroi Résiduelle de Bois Sain par sondage"),
                  style="H.TLabel").pack(anchor="w", pady=(4, 4))
        ttk.Label(parent,
                  text="Classe colorée selon t/R et le port (barème expert).",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 6))

        prbs_frame = ttk.Frame(parent, style="Panel.TFrame")
        prbs_frame.pack(fill="x", pady=(0, 10))
        cols = ("n", "dir", "prbs", "tR", "classe")
        self.tbl_prbs = ttk.Treeview(prbs_frame, columns=cols,
                                      show="headings", height=8)
        self.tbl_prbs.heading("n", text=_("N°"))
        self.tbl_prbs.heading("dir", text=_("Direction"))
        self.tbl_prbs.heading("prbs", text=_("PRBS (cm)"))
        self.tbl_prbs.heading("tR", text=_("t/R (%)"))
        self.tbl_prbs.heading("classe", text=_("Classe"))
        self.tbl_prbs.column("n", width=35, anchor="center")
        self.tbl_prbs.column("dir", width=80, anchor="center")
        self.tbl_prbs.column("prbs", width=85, anchor="center")
        self.tbl_prbs.column("tR", width=70, anchor="center")
        self.tbl_prbs.column("classe", width=90, anchor="center")
        self.tbl_prbs.pack(side="left", fill="x", expand=True)
        self.tbl_prbs.tag_configure(
            "vert",   background="#A8D8AE", foreground="#1A4E22")
        self.tbl_prbs.tag_configure(
            "orange", background="#FFCC80", foreground="#6D3000")
        self.tbl_prbs.tag_configure(
            "rouge",  background="#EF9A9A", foreground="#6B1010")

        # Bandeau du garde-fou fusion : créé non packé, montré/caché par
        # `refresh()` quand une ligne du tableau est écrêtée (⚠) — même
        # message que les onglets Sondages / Dégradations.
        self._lbl_fusion = ttk.Label(
            parent, text=FUSION_WARN_TEXT, style="Panel.TLabel",
            foreground=COLOR_WARN, wraplength=400, justify="left")

    # --- Préconisation ------------------------------------------------

    def _build_preconisation(self, parent: ttk.Frame) -> None:
        """Deux blocs indépendants : Intervention (urgence + échéance + texte)
        et Suivi (validité + texte). Édite le genet courant. `_loading`
        neutralise les callbacks pendant `refresh()` pour ne pas marquer dirty
        / empiler un undo parasite."""
        self._loading = False
        self._preco_snapshot: Optional[dict] = None
        self._suivi_snapshot: Optional[dict] = None
        # Identité du dernier arbre chargé : on ne recharge les champs que
        # lorsqu'elle change (changement d'arbre / undo restaurant un objet
        # neuf), JAMAIS sur un simple redraw — sinon on écraserait la frappe
        # en cours dans la zone de texte.
        self._preco_loaded_id: Optional[int] = None

        ttk.Label(parent, text=_("Préconisation"),
                  style="H.TLabel").pack(anchor="w", pady=(4, 2))
        ttk.Label(parent,
                  text="La décision d'expertise : quoi faire, et quand.",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 8))

        # ── Intervention ──────────────────────────────────────────────
        ttk.Label(parent, text=_("── Intervention ──"),
                  style="Sub.TLabel").pack(anchor="w", pady=(0, 6))

        line = ttk.Frame(parent, style="Panel.TFrame")
        line.pack(fill="x", pady=(0, 6))
        ttk.Label(line, text=_("Urgence"), style="Panel.TLabel").pack(
            side="left", padx=(0, 4))
        self.var_urgence = tk.StringVar(value=_URGENCE_VIDE)
        self._cmb_urgence = ttk.Combobox(
            line, textvariable=self.var_urgence,
            values=self._urgence_choices(),
            state="readonly", width=18)
        self._cmb_urgence.pack(side="left", padx=(0, 4))
        self._cmb_urgence.bind("<<ComboboxSelected>>",
                               lambda e: self._on_urgence_changed())
        btn_edit_urg = ttk.Button(line, text="…", style="Ghost.TButton",
                                  width=3,
                                  command=self._edit_urgences_custom)
        btn_edit_urg.pack(side="left", padx=(0, 12))
        Tooltip(btn_edit_urg, "Gérer les niveaux d'urgence personnalisés")

        ttk.Label(line, text=_("Échéance"), style="Panel.TLabel").pack(
            side="left", padx=(0, 4))
        self.var_echeance = tk.StringVar()
        ent_ech = ttk.Entry(line, textvariable=self.var_echeance, width=12)
        ent_ech.pack(side="left", padx=(0, 2))
        ent_ech.bind("<FocusIn>", lambda e: self._preco_focus_in())
        ent_ech.bind("<FocusOut>", lambda e: self._on_echeance_focus_out())
        btn_cal = ttk.Button(line, text="📅", style="Ghost.TButton", width=3,
                             command=self._pick_echeance)
        btn_cal.pack(side="left")
        Tooltip(btn_cal, "Choisir l'échéance au calendrier")
        ttk.Label(line, text=_("(facultatif)"), style="Muted.TLabel",
                  foreground=COLOR_MUTED).pack(side="left", padx=(6, 0))

        ttk.Label(parent, text=_("Action recommandée (texte libre)"),
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 2))
        self.txt_preco = tk.Text(parent, height=3, wrap="word",
                                 font=ui_font("Helvetica", 10),
                                 relief="solid", borderwidth=1)
        self.txt_preco.pack(fill="x", pady=(0, 14))
        self.txt_preco.bind("<FocusIn>", lambda e: self._preco_focus_in())
        self.txt_preco.bind("<FocusOut>", lambda e: self._on_preco_focus_out())

        # ── Suivi ─────────────────────────────────────────────────────
        ttk.Label(parent, text=_("── Suivi ──"),
                  style="Sub.TLabel").pack(anchor="w", pady=(0, 6))

        suivi_line = ttk.Frame(parent, style="Panel.TFrame")
        suivi_line.pack(fill="x", pady=(0, 6))
        ttk.Label(suivi_line, text=_("Validité"), style="Panel.TLabel").pack(
            side="left", padx=(0, 4))
        self.var_suivi_validite = tk.StringVar(value=_SUIVI_VIDE)
        self._cmb_suivi = ttk.Combobox(
            suivi_line, textvariable=self.var_suivi_validite,
            values=self._suivi_choices(),
            state="readonly", width=16)
        self._cmb_suivi.pack(side="left", padx=(0, 4))
        self._cmb_suivi.bind("<<ComboboxSelected>>",
                             lambda e: self._on_suivi_validite_changed())
        btn_edit_suivi = ttk.Button(suivi_line, text="…", style="Ghost.TButton",
                                    width=3,
                                    command=self._edit_suivi_custom)
        btn_edit_suivi.pack(side="left")
        Tooltip(btn_edit_suivi, "Gérer les durées de suivi personnalisées")

        ttk.Label(parent, text=_("Contenu du suivi (texte libre)"),
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 2))
        self.txt_suivi = tk.Text(parent, height=3, wrap="word",
                                 font=ui_font("Helvetica", 10),
                                 relief="solid", borderwidth=1)
        self.txt_suivi.pack(fill="x", pady=(0, 12))
        self.txt_suivi.bind("<FocusIn>", lambda e: self._suivi_focus_in())
        self.txt_suivi.bind("<FocusOut>", lambda e: self._on_suivi_texte_focus_out())

    def _urgence_choices(self) -> "list[str]":
        """Niveaux standards + personnalisés pour le combobox urgence."""
        return [_URGENCE_VIDE, *URGENCE_NIVEAUX,
                *self._host.get_urgences_custom()]

    def _refresh_urgence_choices(self) -> None:
        """Met à jour les valeurs du combobox après modification des niveaux."""
        self._cmb_urgence.configure(values=self._urgence_choices())

    def _edit_urgences_custom(self) -> None:
        result = ask_urgences_custom(self, self._host.get_urgences_custom())
        if result is not None:
            self._host.set_urgences_custom(result)
            self._refresh_urgence_choices()

    def _suivi_choices(self) -> "list[str]":
        """Durées standards + personnalisées pour le combobox validité."""
        return [_SUIVI_VIDE, *SUIVI_VALIDITES, *self._host.get_suivi_custom()]

    def _refresh_suivi_choices(self) -> None:
        """Met à jour les valeurs du combobox après modification des durées."""
        self._cmb_suivi.configure(values=self._suivi_choices())

    def _edit_suivi_custom(self) -> None:
        result = ask_suivi_custom(self, self._host.get_suivi_custom())
        if result is not None:
            self._host.set_suivi_custom(result)
            self._refresh_suivi_choices()

    def _refresh_preconisation(self, a: Optional[Arbre]) -> None:
        """Recharge les 5 champs depuis l'arbre courant **si l'arbre a
        changé** (cf. `_preco_loaded_id`), callbacks neutralisés
        (`_loading`). Ne touche à rien sur un redraw du même arbre → ne
        lutte pas contre la frappe."""
        aid = id(a) if a is not None else None
        if aid == self._preco_loaded_id:
            return
        self._preco_loaded_id = aid
        self._loading = True
        try:
            all_urg = list(URGENCE_NIVEAUX) + self._host.get_urgences_custom()
            urg = a.urgence if a and a.urgence in all_urg else ""
            self.var_urgence.set(urg or _URGENCE_VIDE)
            self.var_echeance.set(a.echeance if a else "")
            self.txt_preco.delete("1.0", "end")
            self.txt_preco.insert("1.0", a.preconisation if a else "")
            all_suivi = list(SUIVI_VALIDITES) + self._host.get_suivi_custom()
            sv = a.suivi_validite if a and a.suivi_validite in all_suivi else ""
            self.var_suivi_validite.set(sv or _SUIVI_VIDE)
            self.txt_suivi.delete("1.0", "end")
            self.txt_suivi.insert("1.0", a.suivi_texte if a else "")
        finally:
            self._loading = False

    def _preco_focus_in(self) -> None:
        if not self._loading:
            self._preco_snapshot = self._host.capture_undo_snapshot()

    def _suivi_focus_in(self) -> None:
        if not self._loading:
            self._suivi_snapshot = self._host.capture_undo_snapshot()

    def _on_urgence_changed(self) -> None:
        if self._loading:
            return
        a = self._host._current_arbre()
        if a is None:
            return
        choice = self.var_urgence.get()
        new = "" if choice == _URGENCE_VIDE else choice
        if new == a.urgence:
            return
        self._host.push_undo()
        a.urgence = new
        self._host.on_preconisation_changed()

    def _on_echeance_focus_out(self) -> None:
        a = self._host._current_arbre()
        if a is None:
            return
        raw = self.var_echeance.get()
        norm = normaliser_date(raw)
        if norm is None:                 # illisible → revert
            self.var_echeance.set(a.echeance)
        elif norm != a.echeance:
            self._commit_preco_undo()
            a.echeance = norm
            self.var_echeance.set(norm)
            self._host.on_preconisation_changed()
        self._preco_snapshot = None

    def _pick_echeance(self) -> None:
        a = self._host._current_arbre()
        if a is None:
            return
        res = ask_date(self, self.var_echeance.get())
        if res is None or res == a.echeance:
            return
        self._host.push_undo()
        a.echeance = res
        self.var_echeance.set(res)
        self._host.on_preconisation_changed()

    def _on_preco_focus_out(self) -> None:
        a = self._host._current_arbre()
        if a is None:
            return
        new = self.txt_preco.get("1.0", "end-1c")
        if new != a.preconisation:
            self._commit_preco_undo()
            a.preconisation = new
            self._host.on_preconisation_changed()
        self._preco_snapshot = None

    def _on_suivi_validite_changed(self) -> None:
        if self._loading:
            return
        a = self._host._current_arbre()
        if a is None:
            return
        choice = self.var_suivi_validite.get()
        new = "" if choice == _SUIVI_VIDE else choice
        if new == a.suivi_validite:
            return
        self._host.push_undo()
        a.suivi_validite = new
        self._host.on_preconisation_changed()

    def _on_suivi_texte_focus_out(self) -> None:
        a = self._host._current_arbre()
        if a is None:
            return
        new = self.txt_suivi.get("1.0", "end-1c")
        if new != a.suivi_texte:
            self._commit_suivi_undo()
            a.suivi_texte = new
            self._host.on_preconisation_changed()
        self._suivi_snapshot = None

    def _commit_preco_undo(self) -> None:
        if self._preco_snapshot is not None:
            self._host.push_undo_snapshot(self._preco_snapshot)
            self._preco_snapshot = None

    def _commit_suivi_undo(self) -> None:
        if self._suivi_snapshot is not None:
            self._host.push_undo_snapshot(self._suivi_snapshot)
            self._suivi_snapshot = None

    def refresh(self) -> None:
        """Recharge le tableau PRBS et le résumé textuel à partir de
        l'arbre courant. Appelé par App._redraw_all après le debounce."""
        a = self._host._current_arbre()
        self._refresh_preconisation(a)

        # --- Tableau PRBS par sondage (par brin pour une cépée) ---
        self.tbl_prbs.delete(*self.tbl_prbs.get_children())
        any_ecrete = False
        if a:
            # Une cépée préfixe le N° par le label du brin (« a1 », « b2 »).
            multi = len(a.brins) > 1
            port = a.port_arbre
            for b in a.brins:
                R = b.rayon_tronc_cm
                if R <= 0:
                    continue
                deg_ext_par_grade = degradation_externe_par_grade(b)
                for s in b.sondages:
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
                    idx_grade = (GRADES.index(s.grade)
                                 if s.grade in GRADES else 0)
                    deg_ext = deg_ext_par_grade[idx_grade]
                    prbs_adj = max(0.0, s.prbs_cm - deg_ext)
                    ratio = prbs_adj / R if R > 0 else 0.0
                    classe = classer_prbs(ratio, port)
                    tag = classe.lower()
                    if deg_ext > s.prbs_cm:
                        # Fusion écrêtée : la dégradation externe dépasse
                        # la paroi mesurée — données à vérifier (garde-fou
                        # aligné sur le ⚠ des grilles de saisie).
                        prbs_txt = f"{prbs_adj:g} (–{deg_ext:g} ext. ⚠)"
                        any_ecrete = True
                    elif deg_ext > 0:
                        prbs_txt = f"{prbs_adj:g} (–{deg_ext:g} ext.)"
                    else:
                        prbs_txt = f"{prbs_adj:g}"
                    num = (f"{b.label}{s.numero}" if multi and b.label
                           else str(s.numero))
                    self.tbl_prbs.insert(
                        "", "end",
                        values=(num, f"{direction} ({s.grade} gr)",
                                prbs_txt,
                                f"{100*ratio:.1f}",
                                classe),
                        tags=(tag,))

        # Bandeau fusion sous le tableau (dernier élément du contenu).
        if any_ecrete:
            self._lbl_fusion.pack(anchor="w", fill="x", pady=(0, 10))
        else:
            self._lbl_fusion.pack_forget()

        # --- Texte de résumé enrichi (agrégé par brin pour une cépée) ---
        if not a:
            tagged = [("Renseignez le rayon du tronc et ajoutez des "
                       "sondages pour obtenir un résumé.", "")]
        else:
            tagged = genet_summary_tagged(a)
        self._txt_diag.configure(state="normal")
        self._txt_diag.delete("1.0", "end")
        for text, tag in tagged:
            tags: tuple = (tag,) if tag else ()
            self._txt_diag.insert("end", text + "\n", tags)
        # Ajuste la hauteur du widget au nombre de lignes insérées.
        n_lines = int(self._txt_diag.index("end-1c").split(".")[0])
        self._txt_diag.configure(state="disabled", height=max(1, n_lines))
