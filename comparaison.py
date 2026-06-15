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
- **Vue côte à côte** : référence | courant | **section d'évolution**
  (couronne orange = bois sain perdu depuis la référence), un tableau
  chiffré (Δ PRBS, taux cm/an, compartimentation, t/R…) et un verdict.
- **Cépée** : un bloc de comparaison **par brin**, empilés dans une zone
  défilante (mono-caule = un seul bloc). Appariement automatique par
  index/label ; un brin courant sans homologue de référence est comparé à
  None. Le tout **exportable** PNG/PDF (une page par brin pour une cépée).

Le calcul est délégué à `diagnostic` (`comparaison_detaillee`,
`verdict_evolution`) et le rendu PIL à `comparaison_render` (sans Tk).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Mapping, Optional

from comparaison_render import (
    metric_rows,
    render_brin_section,
    render_comparison_pages,
    render_evolution_section_brin,
)
from diagnostic import (
    comparaison_par_brin,
    evolution_classe,
    verdict_evolution,
)
from dialogs import annees_entre
from model import Arbre, Chantier
from palette import COLOR_INK, COLOR_MUTED, COLOR_PANEL

_SEC = 440  # côté des dessins (px)


def _photo(img: Any) -> Any:
    from PIL import ImageTk
    return ImageTk.PhotoImage(img)


def open_comparison(parent: tk.Misc, current: Arbre, reference: Chantier,
                    *, cur_date: str, couleur_classe: Mapping[str, str],
                    export_cb: Callable[[str, Callable[[], Any], tk.Misc],
                                        None],
                    show_sondages: bool = True) -> None:
    """Fenêtre de comparaison de `current` avec un arbre de la mission
    `reference`. `cur_date` = date de la mission courante (pour le taux
    cm/an). `export_cb(fmt, builder, parent)` est appelé par les boutons
    Export (fmt ∈ {"png", "pdf"}, builder() renvoie la liste de pages PIL,
    `parent` = la fenêtre pour ancrer le filedialog au premier plan).
    `show_sondages` reprend la case « Afficher sondages » sous le canevas."""
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

    state: dict[str, Any] = {"ref_arbre": None}
    photos: list[Any] = []  # garde les PhotoImage du GC (multi-brin)

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

    # --- Zone centrale défilante : un bloc par brin (cépée). Mono-caule
    # = un seul bloc, sans en-tête de brin. Scrollbar seule (pas de binding
    # molette global, qui casserait le défilement de l'app). ---
    mid = ttk.Frame(dlg, style="Panel.TFrame")
    mid.pack(fill="both", expand=True)
    canvas = tk.Canvas(mid, bg=COLOR_PANEL, highlightthickness=0)
    vsb = ttk.Scrollbar(mid, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=vsb.set)
    vsb.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    inner = ttk.Frame(canvas, style="Panel.TFrame")
    inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")
    inner.bind("<Configure>",
               lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>",
                lambda e: canvas.itemconfigure(inner_id, width=e.width))

    # --- Boutons d'export (verdict par brin = dans chaque bloc) ---
    foot = ttk.Frame(dlg, style="Panel.TFrame", padding=12)
    foot.pack(fill="x")
    lbl_msg = ttk.Label(foot, text="", style="Muted.TLabel",
                        wraplength=900, justify="left")
    lbl_msg.pack(side="left", fill="x", expand=True)
    ttk.Button(foot, text="Fermer", style="Ghost.TButton",
               command=dlg.destroy).pack(side="right")
    ttk.Button(foot, text="🖼 PNG…", style="Ghost.TButton",
               command=lambda: export_cb("png", _page_builder(state), dlg)
               ).pack(side="right", padx=6)
    ttk.Button(foot, text="📄 PDF…", style="Accent.TButton",
               command=lambda: export_cb("pdf", _page_builder(state), dlg)
               ).pack(side="right")

    def _on_select(_e: Any = None) -> None:
        idx = cmb.current()
        if idx < 0 or idx >= len(refs):
            return
        ref_arbre = refs[idx]
        state["ref_arbre"] = ref_arbre
        # Mémo export (les pages sont recalculées à la demande dans le builder).
        state["builder_args"] = (reference.nom, ref_arbre, current, annees,
                                  ref_label, cur_label, show_sondages)
        for w in inner.winfo_children():
            w.destroy()
        photos.clear()
        pairs = comparaison_par_brin(ref_arbre, current, annees)
        multi = len(pairs) > 1
        for label, cur_b, ref_b, detail in pairs:
            _build_brin_block(inner, label if multi else None,
                              ref_arbre, current, cur_b, ref_b, detail,
                              ref_label, cur_label, photos, show_sondages)
        canvas.configure(scrollregion=canvas.bbox("all"))
        canvas.yview_moveto(0.0)

    cmb.bind("<<ComboboxSelected>>", _on_select)

    if not refs:
        ttk.Label(inner, text="La mission de référence ne contient aucun "
                  "arbre.", style="Panel.TLabel").pack(anchor="w", padx=12,
                                                       pady=12)
    else:
        default = next((i for i, a in enumerate(refs)
                        if a.numero_arbre == current.numero_arbre), 0)
        cmb.current(default)
        _on_select()

    dlg.update_idletasks()
    dlg.focus_set()


def _build_brin_block(parent: tk.Misc, label: Optional[str], ref_arbre: Arbre,
                      cur_arbre: Arbre, cur_b: Any, ref_b: Any,
                      detail: Any, ref_label: str, cur_label: str,
                      photos: list, show_sondages: bool = True) -> None:
    """Construit un bloc de comparaison (3 dessins + tableau + verdict) pour
    un brin. `label=None` ⟹ mono-caule (pas d'en-tête de brin). `ref_b=None`
    ⟹ brin courant sans homologue de référence (colonne réf. vide).
    `show_sondages` reprend la case « Afficher sondages »."""
    block = ttk.Frame(parent, style="Panel.TFrame", padding=(0, 6))
    block.pack(fill="x", expand=True)
    if label is not None:
        ttk.Label(block, text=f"Brin {label}", style="H.TLabel",
                  font=("Helvetica", 13, "bold")).pack(anchor="w", padx=12)

    row = ttk.Frame(block, style="Panel.TFrame", padding=(12, 4))
    row.pack(fill="x")
    img_ref = _build_image_col(row, f"Référence — {ref_label}")
    img_cur = _build_image_col(row, f"Courant — {cur_label}")
    img_evo = _build_image_col(row, "Évolution de l'altération")
    if ref_b is not None:
        p = _photo(render_brin_section(ref_arbre, ref_b, _SEC,
                                       show_sondages=show_sondages))
        photos.append(p)
        img_ref.configure(image=p)
    else:
        img_ref.configure(text="(pas de brin de référence)")
    pc = _photo(render_brin_section(cur_arbre, cur_b, _SEC,
                                    show_sondages=show_sondages))
    photos.append(pc)
    img_cur.configure(image=pc)
    pe = _photo(render_evolution_section_brin(ref_b, cur_b, _SEC))
    photos.append(pe)
    img_evo.configure(image=pe)

    rows = metric_rows(detail)
    tbl_frame = ttk.Frame(block, style="Panel.TFrame", padding=(12, 4))
    tbl_frame.pack(fill="x")
    cols = ("ind", "ref", "cur", "evo")
    tbl = ttk.Treeview(tbl_frame, columns=cols, show="headings",
                       height=len(rows))
    for c, txt, w in (("ind", "Indicateur", 280), ("ref", "Référence", 150),
                      ("cur", "Courant", 150), ("evo", "Évolution", 230)):
        tbl.heading(c, text=txt)
        tbl.column(c, width=w, anchor="w")
    for r in rows:
        tbl.insert("", "end", values=r)
    tbl.pack(fill="x")

    ttk.Label(block, text=verdict_evolution(detail), style="Panel.TLabel",
              font=("Helvetica", 11, "bold"), wraplength=900, justify="left",
              foreground=_verdict_color(detail.classe_ref, detail.classe_cur)
              ).pack(anchor="w", padx=12, pady=(2, 6))
    ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=2)


def _build_image_col(parent: tk.Misc, titre: str) -> ttk.Label:
    host = ttk.Frame(parent, style="Panel.TFrame")
    host.pack(side="left", fill="both", expand=True, padx=4)
    ttk.Label(host, text=titre, style="H.TLabel").pack(anchor="w")
    img = ttk.Label(host, style="Panel.TLabel")
    img.pack(pady=4)
    return img


def _page_builder(state: dict) -> Callable[[], Any]:
    """Renvoie une closure qui rend **la liste des pages** d'export depuis la
    sélection courante (capturée dans `state`) : une page par brin pour une
    cépée, une page genet pour un mono-caule (cf. `render_comparison_pages`)."""
    def _build() -> Any:
        args = state.get("builder_args")
        if args is None:
            raise RuntimeError("Aucun arbre de référence sélectionné.")
        (nom, ref_arbre, cur, annees, ref_label, cur_label,
         show_sondages) = args
        return render_comparison_pages(
            nom, ref_arbre, cur, annees, ref_label=ref_label,
            cur_label=cur_label, show_sondages=show_sondages)
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
