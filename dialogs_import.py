"""
Dialog d'import CSV (mapping colonnes → champs modèle).

Affiche un aperçu des premières lignes du fichier, propose un mapping
auto-détecté que l'utilisateur peut ajuster, puis renvoie la liste des
`Arbre` construits (ou None si annulé).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from csv_import import _CHAMP_IGNORE, CHAMPS_CIBLES, auto_map, build_arbres, read_csv
from dialogs import _make_modal
from i18n import _
from ui_fonts import font as ui_font

if TYPE_CHECKING:
    from model import Arbre

_MAX_PREVIEW = 5   # lignes d'aperçu


def ask_csv_import(parent: tk.Misc, path: str) -> Optional[List["Arbre"]]:
    """Ouvre le dialog de mapping CSV → modèle.

    Retourne la liste d'arbres importés si validé, None si annulé.
    """
    # --- Lecture du fichier ---
    try:
        _delim, headers, rows = read_csv(path)
    except Exception as e:
        messagebox.showerror(_("Erreur de lecture CSV"),
                             f"Impossible de lire le fichier :\n{e}",
                             parent=parent)
        return None

    if not headers:
        messagebox.showwarning(_("CSV vide"),
                               "Le fichier ne contient aucune colonne.",
                               parent=parent)
        return None

    result: Optional[List["Arbre"]] = None
    mapping: Dict[str, str] = auto_map(headers)

    dlg = tk.Toplevel(parent)
    dlg.title("Import CSV — Correspondance des colonnes")
    dlg.resizable(True, True)
    dlg.minsize(640, 480)

    content = ttk.Frame(dlg, padding=16)
    content.pack(fill="both", expand=True)

    # --- Titre ---
    ttk.Label(content,
              text=f"Fichier : {path.split('/')[-1].split(chr(92))[-1]}",
              font=ui_font("Helvetica", 10, "bold")).pack(anchor="w")
    ttk.Label(content,
              text=f"{len(rows)} ligne(s) détectée(s). "
                   "Associez chaque colonne CSV à un champ du modèle.",
              wraplength=580).pack(anchor="w", pady=(2, 10))

    # --- Aperçu CSV (5 premières lignes) ---
    preview_frame = ttk.LabelFrame(content, text=_(" Aperçu "), padding=6)
    preview_frame.pack(fill="x", pady=(0, 10))
    cols = headers[:8]   # max 8 colonnes dans l'aperçu
    tv = ttk.Treeview(preview_frame, columns=cols, show="headings", height=4)
    for c in cols:
        tv.heading(c, text=c)
        tv.column(c, width=max(80, min(140, len(c) * 10)), anchor="w")
    for row in rows[:_MAX_PREVIEW]:
        tv.insert("", "end", values=[row.get(c, "") for c in cols])
    sb = ttk.Scrollbar(preview_frame, orient="horizontal",
                       command=tv.xview)
    tv.configure(xscrollcommand=sb.set)
    tv.pack(fill="x")
    sb.pack(fill="x")

    # --- Mapping ---
    map_frame = ttk.LabelFrame(content, text=_(" Correspondance colonnes → champs "),
                                padding=8)
    map_frame.pack(fill="both", expand=True, pady=(0, 10))

    # Options du combobox : "— ignorer —" + champs disponibles
    _options = ["— ignorer —"] + list(CHAMPS_CIBLES.values())
    _val_to_champ = {v: k for k, v in CHAMPS_CIBLES.items()}
    _champ_to_val = dict(CHAMPS_CIBLES)

    canvas = tk.Canvas(map_frame, highlightthickness=0)
    scrollbar = ttk.Scrollbar(map_frame, orient="vertical",
                               command=canvas.yview)
    inner = ttk.Frame(canvas)
    inner.bind("<Configure>",
               lambda e: canvas.configure(
                   scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=inner, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    # En-têtes de la grille
    ttk.Label(inner, text=_("Colonne CSV"),
              font=ui_font("Helvetica", 9, "bold")).grid(
        row=0, column=0, padx=(0, 12), pady=(0, 4), sticky="w")
    ttk.Label(inner, text=_("Champ modèle"),
              font=ui_font("Helvetica", 9, "bold")).grid(
        row=0, column=1, padx=(0, 12), pady=(0, 4), sticky="w")
    ttk.Label(inner, text=_("Exemples (3 premières lignes)"),
              font=ui_font("Helvetica", 9, "bold")).grid(
        row=0, column=2, pady=(0, 4), sticky="w")

    cmb_vars: Dict[str, tk.StringVar] = {}

    for r, h in enumerate(headers, 1):
        ttk.Label(inner, text=h).grid(
            row=r, column=0, padx=(0, 12), pady=2, sticky="w")

        var = tk.StringVar()
        cur = mapping.get(h, _CHAMP_IGNORE)
        var.set(_champ_to_val.get(cur, "— ignorer —") if cur else "— ignorer —")
        cmb = ttk.Combobox(inner, textvariable=var, values=_options,
                            state="readonly", width=26)
        cmb.grid(row=r, column=1, padx=(0, 12), pady=2, sticky="w")
        cmb_vars[h] = var

        exemples = ", ".join(
            str(rows[i].get(h, "")) for i in range(min(3, len(rows)))
            if rows[i].get(h, "").strip()
        )
        ttk.Label(inner, text=exemples or "—",
                  foreground="#666").grid(
            row=r, column=2, pady=2, sticky="w")

    # --- Résumé dynamique ---
    lbl_resume = ttk.Label(content, text="", foreground=COLOR_ACCENT
                           if False else "#1A5A2A")

    def _couleur_resume(n: int) -> str:
        return "#1A5A2A" if n > 0 else "#B85C00"

    def _update_resume(*_: Any) -> None:
        m = _get_mapping()
        try:
            arbres, warns = build_arbres(rows, m)
        except Exception:
            lbl_resume.configure(
                text=_("Erreur d'analyse — vérifiez le mapping."),
                foreground="#CC0000")
            return
        n = len(arbres)
        ns = sum(len(a.brins[0].sondages) for a in arbres)
        msg = f"{n} arbre(s) · {ns} sondage(s) seront importés"
        if warns:
            msg += f" · ⚠ {len(warns)} avertissement(s)"
        lbl_resume.configure(text=msg, foreground=_couleur_resume(n))

    for var in cmb_vars.values():
        var.trace_add("write", _update_resume)

    lbl_resume.pack(anchor="w", pady=(0, 8))

    def _get_mapping() -> Dict[str, str]:
        m: Dict[str, str] = {}
        for h, var in cmb_vars.items():
            lbl = var.get()
            m[h] = _val_to_champ.get(lbl, _CHAMP_IGNORE)
        return m

    def _ok() -> None:
        nonlocal result
        m = _get_mapping()
        if not any(v == "numero_arbre" for v in m.values()):
            messagebox.showwarning(
                _("N° arbre requis"),
                "Associez au moins une colonne au champ « N° arbre ».",
                parent=dlg)
            return
        try:
            arbres, warns = build_arbres(rows, m)
        except Exception as e:
            messagebox.showerror(_("Erreur d'import"), str(e), parent=dlg)
            return
        if not arbres:
            messagebox.showwarning(
                _("Aucun arbre importé"),
                "Aucun arbre valide trouvé dans le fichier.\n"
                "Vérifiez le mapping et le contenu du CSV.",
                parent=dlg)
            return
        if warns:
            detail = "\n".join(f"  • {w}" for w in warns[:10])
            if len(warns) > 10:
                detail += f"\n  … et {len(warns)-10} autre(s)"
            if not messagebox.askyesno(
                    _("Avertissements"),
                    f"{len(warns)} ligne(s) ignorée(s) :\n{detail}\n\n"
                    "Continuer quand même ?",
                    parent=dlg):
                return
        result = arbres
        dlg.destroy()

    def _cancel() -> None:
        dlg.destroy()

    sep = ttk.Separator(content, orient="horizontal")
    sep.pack(fill="x", pady=(0, 8))
    btns = ttk.Frame(content)
    btns.pack(fill="x")
    ttk.Button(btns, text=_("Annuler"),
               style="Ghost.TButton",
               command=_cancel).pack(side="right")
    ttk.Button(btns, text=_("Importer"),
               style="Accent.TButton",
               command=_ok).pack(side="right", padx=(0, 6))

    dlg.bind("<Escape>", lambda e: _cancel())
    _update_resume()
    _make_modal(dlg, parent)
    dlg.wait_window()
    return result


# Import tardif pour éviter la dépendance circulaire
try:
    from palette import COLOR_ACCENT
except ImportError:
    COLOR_ACCENT = "#1A6B2A"
