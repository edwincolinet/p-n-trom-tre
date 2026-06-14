"""
Fenêtre de comparaison d'inspections (ré-inspection inter-missions).

Le suivi patrimonial d'un arbre se lit dans la **durée** : comparer la
campagne courante à une campagne antérieure montre si l'état se dégrade.

Design (choix métier, cf. mémoire) :
- **Référence par session** : on charge une mission antérieure en mémoire
  (aucun champ persisté dans le fichier → pas de lien cassé).
- **Lien explicite par arbre** : l'opérateur choisit, dans un combobox,
  l'arbre de la mission de référence à comparer (défaut : même n° s'il
  existe). Robuste même si la numérotation a changé entre campagnes.
- **Vue côte à côte** : référence | courant | **carte d'évolution**
  (heatmap des 16 directions colorée par l'aggravation de l'altération),
  un tableau chiffré (Δ PRBS, taux cm/an, compartimentation, t/R…) et un
  verdict. Le tout **exportable** en PNG et PDF (livrable client).

Le calcul est délégué à `diagnostic` (`comparaison_detaillee`,
`verdict_evolution`) et le rendu PIL à `comparaison_render` (sans Tk).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Mapping, Optional

from comparaison_render import (
    metric_rows,
    render_comparison_page,
    render_evolution_heatmap,
)
from diagnostic import comparaison_detaillee, evolution_classe, verdict_evolution
from dialogs import annees_entre
from model import Arbre, Chantier
from palette import COLOR_INK, COLOR_MUTED, COLOR_PANEL
from pil_render import render_arbre_to_pil_image

_SEC = 440  # côté des dessins (px)


def _photo(img: Any) -> Any:
    from PIL import ImageTk
    return ImageTk.PhotoImage(img)


def open_comparison(parent: tk.Misc, current: Arbre, reference: Chantier,
                    *, cur_date: str, couleur_classe: Mapping[str, str],
                    export_cb: Callable[[str, Callable[[], Any]], None]
                    ) -> None:
    """Fenêtre de comparaison de `current` avec un arbre de la mission
    `reference`. `cur_date` = date de la mission courante (pour le taux
    cm/an). `export_cb(fmt, builder)` est appelé par les boutons Export
    (fmt ∈ {"png", "pdf"}, builder() renvoie la page PIL à enregistrer)."""
    refs = reference.arbres
    annees = annees_entre(reference.date_releve, cur_date)
    ref_label = reference.date_releve or reference.nom or "référence"
    cur_label = cur_date or "courant"

    dlg = tk.Toplevel(parent)
    dlg.title(f"Comparaison d'inspections — {current.display_name}")
    dlg.configure(bg=COLOR_PANEL)
    dlg.minsize(1000, 720)
    try:
        dlg.transient(parent)  # type: ignore[call-overload]
    except tk.TclError:
        pass

    state: dict[str, Any] = {"ref_arbre": None, "detail": None}
    photos: dict[str, Any] = {}  # garde les PhotoImage du GC

    # --- Sélecteur de l'arbre de référence (lien explicite) ---
    top = ttk.Frame(dlg, style="Panel.TFrame", padding=(12, 10, 12, 4))
    top.pack(fill="x")
    ttk.Label(top, text="Comparer à l'arbre de la mission de référence :",
              style="Panel.TLabel").pack(side="left", padx=(0, 6))
    labels = [f"n° {a.numero_arbre} — {a.essence or '?'}" for a in refs]
    var_ref = tk.StringVar()
    cmb = ttk.Combobox(top, textvariable=var_ref, values=labels,
                       state="readonly", width=28)
    cmb.pack(side="left")
    ttk.Label(top, text=f"(réf. {ref_label}  →  courant {cur_label})",
              style="Muted.TLabel").pack(side="left", padx=(10, 0))

    # --- Trois dessins côte à côte ---
    row = ttk.Frame(dlg, style="Panel.TFrame", padding=(12, 4))
    row.pack(fill="x")
    img_ref = _build_image_col(row, f"Référence — {ref_label}")
    img_cur = _build_image_col(row, f"Courant — {cur_label}")
    img_evo = _build_image_col(row, "Évolution de l'altération")

    # Dessin courant : figé.
    photos["cur"] = _photo(render_arbre_to_pil_image(
        current, _SEC, _SEC, show_sondages=True, show_title=False,
        show_legend=False))
    img_cur.configure(image=photos["cur"])

    # --- Tableau chiffré ---
    tbl_frame = ttk.Frame(dlg, style="Panel.TFrame", padding=(12, 4))
    tbl_frame.pack(fill="x")
    cols = ("ind", "ref", "cur", "evo")
    tbl = ttk.Treeview(tbl_frame, columns=cols, show="headings", height=6)
    for c, txt, w in (("ind", "Indicateur", 280), ("ref", "Référence", 150),
                      ("cur", "Courant", 150), ("evo", "Évolution", 230)):
        tbl.heading(c, text=txt)
        tbl.column(c, width=w, anchor="w")
    tbl.pack(fill="x")

    # --- Verdict + boutons ---
    foot = ttk.Frame(dlg, style="Panel.TFrame", padding=12)
    foot.pack(fill="x")
    lbl_evo = ttk.Label(foot, text="", style="Panel.TLabel",
                        font=("Helvetica", 11, "bold"),
                        wraplength=900, justify="left")
    lbl_evo.pack(side="left", fill="x", expand=True)
    ttk.Button(foot, text="Fermer", style="Ghost.TButton",
               command=dlg.destroy).pack(side="right")
    ttk.Button(foot, text="🖼 PNG…", style="Ghost.TButton",
               command=lambda: export_cb("png", _page_builder(state))
               ).pack(side="right", padx=6)
    ttk.Button(foot, text="📄 PDF…", style="Accent.TButton",
               command=lambda: export_cb("pdf", _page_builder(state))
               ).pack(side="right")

    def _on_select(_e: Any = None) -> None:
        idx = cmb.current()
        if idx < 0 or idx >= len(refs):
            return
        ref_arbre = refs[idx]
        detail = comparaison_detaillee(ref_arbre, current, annees)
        state["ref_arbre"] = ref_arbre
        state["detail"] = detail
        photos["ref"] = _photo(render_arbre_to_pil_image(
            ref_arbre, _SEC, _SEC, show_sondages=True, show_title=False,
            show_legend=False))
        img_ref.configure(image=photos["ref"])
        photos["evo"] = _photo(render_evolution_heatmap(detail, _SEC))
        img_evo.configure(image=photos["evo"])
        tbl.delete(*tbl.get_children())
        for r in metric_rows(detail):
            tbl.insert("", "end", values=r)
        lbl_evo.configure(
            text=verdict_evolution(detail),
            foreground=_verdict_color(detail.classe_ref, detail.classe_cur))
        # Mémo pour l'export (capture l'arbre + le détail courants).
        state["builder_args"] = (reference.nom, ref_arbre, current, detail,
                                  ref_label, cur_label)

    cmb.bind("<<ComboboxSelected>>", _on_select)

    if not refs:
        lbl_evo.configure(
            text="La mission de référence ne contient aucun arbre.")
    else:
        default = next((i for i, a in enumerate(refs)
                        if a.numero_arbre == current.numero_arbre), 0)
        cmb.current(default)
        _on_select()

    dlg.update_idletasks()
    dlg.focus_set()


def _build_image_col(parent: tk.Misc, titre: str) -> ttk.Label:
    host = ttk.Frame(parent, style="Panel.TFrame")
    host.pack(side="left", fill="both", expand=True, padx=4)
    ttk.Label(host, text=titre, style="H.TLabel").pack(anchor="w")
    img = ttk.Label(host, style="Panel.TLabel")
    img.pack(pady=4)
    return img


def _page_builder(state: dict) -> Callable[[], Any]:
    """Renvoie une closure qui rend la page d'export à partir de la
    sélection courante (capturée dans `state`)."""
    def _build() -> Any:
        args = state.get("builder_args")
        if args is None:
            raise RuntimeError("Aucun arbre de référence sélectionné.")
        nom, ref_arbre, cur, detail, ref_label, cur_label = args
        return render_comparison_page(nom, ref_arbre, cur, detail,
                                      ref_label=ref_label, cur_label=cur_label)
    return _build


def _verdict_color(ref_classe: Optional[str],
                   cur_classe: Optional[str]) -> str:
    evo = evolution_classe(ref_classe, cur_classe)
    if evo is None:
        return COLOR_MUTED
    if evo > 0:
        return "#C0392B"   # aggravation = rouge
    if evo < 0:
        return "#2D7A3E"   # amélioration = vert
    return COLOR_INK
