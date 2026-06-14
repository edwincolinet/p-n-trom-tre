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
- **Vue côte à côte** : référence à gauche, courant à droite (dessin +
  métriques clés), avec un verdict d'évolution de la classe globale.

Fonction publique : `open_comparison(parent, current, reference, ...)`.
Les calculs sont délégués aux helpers purs de `diagnostic`
(`arbre_compare_summary`, `evolution_classe`).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Mapping, Optional

from diagnostic import (
    ArbreCompareSummary,
    arbre_compare_summary,
    evolution_classe,
)
from model import Arbre, Chantier
from palette import COLOR_INK, COLOR_MUTED, COLOR_PANEL
from ui_fonts import font as ui_font

_THUMB = 360  # côté du dessin miniature (px)


def _classe_text(s: ArbreCompareSummary) -> str:
    """« Vert/Orange/Rouge », « Non fiable » (1-2 sondages) ou « — »."""
    if s.classe is not None:
        return s.classe
    if s.n_sondees > 0 and s.rayon_cm > 0:
        return "Non fiable"
    return "—"


def _tr_text(s: ArbreCompareSummary) -> str:
    return f"{s.tR_moyen_pct:.1f} %" if s.tR_moyen_pct is not None else "—"


def _render_thumb(arbre: Arbre) -> Any:
    """Miniature PIL → PhotoImage Tk (ou None si Pillow absent)."""
    try:
        from PIL import ImageTk

        from pil_render import render_arbre_to_pil_image
        img = render_arbre_to_pil_image(
            arbre, _THUMB, _THUMB, show_sondages=True,
            show_title=False, show_legend=False)
        return ImageTk.PhotoImage(img)
    except Exception:
        return None


def open_comparison(parent: tk.Misc, current: Arbre,
                    reference: Chantier, *,
                    couleur_classe: Mapping[str, str]) -> None:
    """Ouvre la fenêtre de comparaison de `current` (mission courante) avec
    un arbre de la mission `reference` (campagne antérieure), choisi dans
    un combobox. Non modale (consultation)."""
    dlg = tk.Toplevel(parent)
    dlg.title(f"Comparaison d'inspections — {current.display_name}")
    dlg.configure(bg=COLOR_PANEL)
    dlg.resizable(False, False)
    try:
        dlg.transient(parent)  # type: ignore[call-overload]
    except tk.TclError:
        pass

    cur_sum = arbre_compare_summary(current)
    refs = reference.arbres

    # --- Sélecteur de l'arbre de référence (lien explicite) ---
    top = ttk.Frame(dlg, style="Panel.TFrame", padding=12)
    top.pack(fill="x")
    ttk.Label(top, text="Comparer à l'arbre de la mission de référence :",
              style="Panel.TLabel").pack(side="left", padx=(0, 6))
    labels = [f"n° {a.numero_arbre} — {a.essence or '?'}" for a in refs]
    var_ref = tk.StringVar()
    cmb = ttk.Combobox(top, textvariable=var_ref, values=labels,
                       state="readonly", width=26)
    cmb.pack(side="left")

    # --- Deux colonnes côte à côte (référence | courant) ---
    body = ttk.Frame(dlg, style="Panel.TFrame", padding=(12, 0, 12, 6))
    body.pack(fill="both", expand=True)
    col_ref = _build_column(body, "Référence (campagne antérieure)")
    sep = ttk.Frame(body, width=2, style="Side.TFrame")
    sep.pack(side="left", fill="y", padx=10)
    col_cur = _build_column(body, "Inspection courante")

    # La colonne courante est figée (le dessin + les métriques de `current`).
    _fill_column(col_cur, current, cur_sum, couleur_classe)

    # --- Bandeau d'évolution + bouton fermer ---
    foot = ttk.Frame(dlg, style="Panel.TFrame", padding=12)
    foot.pack(fill="x")
    lbl_evo = ttk.Label(foot, text="", style="Panel.TLabel",
                        font=ui_font("Helvetica", 11, "bold"),
                        wraplength=620, justify="left")
    lbl_evo.pack(side="left")
    ttk.Button(foot, text="Fermer", style="Ghost.TButton",
               command=dlg.destroy).pack(side="right")

    def _on_select(_e: Any = None) -> None:
        idx = cmb.current()
        if idx < 0 or idx >= len(refs):
            return
        ref_arbre = refs[idx]
        ref_sum = arbre_compare_summary(ref_arbre)
        _fill_column(col_ref, ref_arbre, ref_sum, couleur_classe)
        lbl_evo.configure(
            text=_evolution_text(ref_sum, cur_sum),
            foreground=_evolution_color(ref_sum.classe, cur_sum.classe))

    cmb.bind("<<ComboboxSelected>>", _on_select)

    if not refs:
        ttk.Label(col_ref["host"],
                  text="La mission de référence ne contient aucun arbre.",
                  style="Muted.TLabel", wraplength=320).pack(pady=20)
    else:
        # Défaut : même n° d'arbre s'il existe dans la référence, sinon le 1er.
        default = next((i for i, a in enumerate(refs)
                        if a.numero_arbre == current.numero_arbre), 0)
        cmb.current(default)
        _on_select()

    dlg.update_idletasks()
    dlg.focus_set()


def _build_column(parent: tk.Misc, titre: str) -> dict:
    """Crée une colonne (titre, zone dessin, zone métriques) et renvoie ses
    widgets pour remplissage ultérieur par `_fill_column`."""
    host = ttk.Frame(parent, style="Panel.TFrame")
    host.pack(side="left", fill="both", expand=True)
    ttk.Label(host, text=titre, style="H.TLabel").pack(anchor="w",
                                                       pady=(0, 4))
    name = ttk.Label(host, text="", style="Panel.TLabel",
                     font=ui_font("Helvetica", 11, "bold"))
    name.pack(anchor="w")
    img = ttk.Label(host, style="Panel.TLabel")
    img.pack(pady=4)
    metrics = ttk.Label(host, text="", style="Panel.TLabel",
                        justify="left", font=ui_font("Helvetica", 10))
    metrics.pack(anchor="w")
    return {"host": host, "name": name, "img": img, "metrics": metrics}


def _fill_column(col: dict, arbre: Arbre, summ: ArbreCompareSummary,
                 couleur_classe: Mapping[str, str]) -> None:
    col["name"].configure(text=arbre.display_name)
    photo = _render_thumb(arbre)
    # Garde une référence (sinon l'image est ramassée par le GC → vide).
    col["img"].configure(image=photo or "")
    col["img"].image = photo
    classe_txt = _classe_text(summ)
    classe_col = couleur_classe.get(classe_txt, COLOR_MUTED)
    col["metrics"].configure(
        text=(f"Rayon : {summ.rayon_cm:g} cm\n"
              f"Sondages : {summ.n_sondees}\n"
              f"t/R moyen : {_tr_text(summ)}"))
    # Le nom porte aussi la couleur de classe (repère visuel rapide).
    col["name"].configure(foreground=classe_col if summ.classe else COLOR_INK)


def _evolution_text(ref: ArbreCompareSummary,
                    cur: ArbreCompareSummary) -> str:
    """Phrase de verdict : évolution de la classe + delta de t/R moyen."""
    rc, cc = _classe_text(ref), _classe_text(cur)
    evo = evolution_classe(ref.classe, cur.classe)
    if evo is None:
        verdict = "Évolution de classe non comparable (diagnostic non publié)."
    elif evo > 0:
        verdict = f"⚠ Aggravation : classe {rc} → {cc}."
    elif evo < 0:
        verdict = f"✓ Amélioration : classe {rc} → {cc}."
    else:
        verdict = f"= Stable : classe {cc}."
    if ref.tR_moyen_pct is not None and cur.tR_moyen_pct is not None:
        delta = cur.tR_moyen_pct - ref.tR_moyen_pct
        fleche = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
        verdict += (f"   t/R moyen : {ref.tR_moyen_pct:.1f} % → "
                    f"{cur.tR_moyen_pct:.1f} %  ({fleche} {abs(delta):.1f} pts)")
    return verdict


def _evolution_color(ref_classe: Optional[str],
                     cur_classe: Optional[str]) -> str:
    evo = evolution_classe(ref_classe, cur_classe)
    if evo is None:
        return COLOR_MUTED
    if evo > 0:
        return "#C0392B"   # aggravation = rouge
    if evo < 0:
        return "#2D7A3E"   # amélioration = vert
    return COLOR_INK
