"""Dialogues de configuration du cabinet et des listes personnalisées.

Extraits de `dialogs.py` pour en réduire la taille. Ces dialogues ne
sont appelés que depuis `penetrometre.py` (paramètres cabinet) et
`pane_diagnostic.py` (urgences / suivi custom).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Optional

from dialogs import _make_modal
from ui_fonts import font as ui_font


def ask_cabinet_settings(parent: tk.Misc,
                         settings: Any) -> bool:
    """Dialogue de configuration du cabinet : nom et logo.

    `settings` est un `SettingsStore`. Retourne True si au moins un
    champ a été modifié (le caller peut alors recharger le logo).
    """
    import shutil
    from pathlib import Path as _Path
    from tkinter import filedialog as _filedialog

    dlg = tk.Toplevel(parent)
    dlg.title("Paramètres du cabinet")
    dlg.resizable(False, False)
    dlg.columnconfigure(1, weight=1)

    result: dict[str, bool] = {"changed": False}
    _pending_logo: list[str | None] = [getattr(settings, "logo_path", None)]
    _preview_img: list[Any] = [None]

    # --- Nom du cabinet ---
    ttk.Label(dlg, text="Nom du cabinet :").grid(
        row=0, column=0, sticky="w", padx=(16, 8), pady=(16, 6))
    var_name = tk.StringVar(value=getattr(settings, "cabinet_name", ""))
    ttk.Entry(dlg, textvariable=var_name, width=34).grid(
        row=0, column=1, columnspan=2, sticky="ew", padx=(0, 16), pady=(16, 6))

    # --- Logo ---
    ttk.Label(dlg, text="Logo :").grid(
        row=1, column=0, sticky="nw", padx=(16, 8), pady=(6, 0))

    btn_frame = ttk.Frame(dlg)
    btn_frame.grid(row=1, column=1, columnspan=2, sticky="w",
                   padx=(0, 16), pady=(6, 0))

    preview_lbl = ttk.Label(dlg, style="Muted.TLabel")
    preview_lbl.grid(row=2, column=0, columnspan=3, padx=16, pady=(6, 4))

    ttk.Label(dlg, text="Formats acceptés : PNG, JPEG, GIF, BMP, TIFF",
              style="Muted.TLabel").grid(
        row=3, column=0, columnspan=3, padx=16, pady=(0, 12))

    def _update_preview(path: "str | None") -> None:
        _pending_logo[0] = path
        if not path:
            preview_lbl.configure(image="", text="Aucun logo configuré")
            _preview_img[0] = None
            return
        try:
            from PIL import Image as _PILImage
            from PIL import ImageTk as _ImageTk
            pil = _PILImage.open(path)
            target_h = 80
            ratio = target_h / pil.height
            pil = pil.resize(  # type: ignore[assignment]
                (int(pil.width * ratio), target_h),
                _PILImage.LANCZOS)  # type: ignore[attr-defined]
            img = _ImageTk.PhotoImage(pil)
            _preview_img[0] = img
            preview_lbl.configure(image=img, text="")
        except ImportError:
            preview_lbl.configure(image="",
                                  text="(aperçu indisponible — Pillow requis)")
        except Exception:
            preview_lbl.configure(image="", text="(image illisible)")

    _update_preview(_pending_logo[0])

    def _choose_logo() -> None:
        p = _filedialog.askopenfilename(
            parent=dlg,
            title="Choisir un logo",
            filetypes=[
                ("Images", "*.png *.jpg *.jpeg *.gif *.bmp *.tiff *.tif"),
                ("PNG", "*.png"),
                ("JPEG", "*.jpg *.jpeg"),
                ("Tous les fichiers", "*.*"),
            ],
        )
        if p:
            _update_preview(p)

    def _remove_logo() -> None:
        _update_preview(None)

    ttk.Button(btn_frame, text="Choisir un fichier…",
               command=_choose_logo).pack(side="left", padx=(0, 8))
    ttk.Button(btn_frame, text="Supprimer",
               style="Ghost.TButton",
               command=_remove_logo).pack(side="left")

    ttk.Separator(dlg).grid(row=4, column=0, columnspan=3,
                             sticky="ew", padx=16, pady=(4, 0))

    def _ok() -> None:
        # Persistance du nom
        name = var_name.get().strip()
        if name != getattr(settings, "cabinet_name", ""):
            settings.set_cabinet_name(name)
            result["changed"] = True

        # Persistance du logo
        new_logo = _pending_logo[0]
        old_logo = getattr(settings, "logo_path", None)
        if new_logo != old_logo:
            result["changed"] = True
            if new_logo:
                ext = _Path(new_logo).suffix.lower()
                dest_dir = _Path.home() / ".penetrometre"
                dest_dir.mkdir(parents=True, exist_ok=True)
                # Supprimer les anciens logos (autre extension)
                for old_f in dest_dir.glob("logo.*"):
                    try:
                        old_f.unlink()
                    except Exception:
                        pass
                dest = dest_dir / f"logo{ext}"
                shutil.copy2(new_logo, dest)
                settings.set_logo_path(str(dest))
            else:
                # Supprimer le fichier copié s'il existe
                if old_logo:
                    try:
                        _Path(old_logo).unlink(missing_ok=True)
                    except Exception:
                        pass
                settings.set_logo_path(None)
        dlg.destroy()

    def _cancel() -> None:
        dlg.destroy()

    btns = ttk.Frame(dlg)
    btns.grid(row=5, column=0, columnspan=3, sticky="e",
              padx=16, pady=(8, 16))
    ttk.Button(btns, text="Annuler", style="Ghost.TButton",
               command=_cancel).pack(side="right", padx=(8, 0))
    ttk.Button(btns, text="OK", style="Accent.TButton",
               command=_ok).pack(side="right")

    dlg.bind("<Return>", lambda e: _ok())
    dlg.bind("<Escape>", lambda e: _cancel())

    _make_modal(dlg, parent)
    dlg.wait_window()
    return result["changed"]


def ask_list_custom(parent: tk.Misc, title: str, description: str,
                    current: "list[str]") -> "Optional[list[str]]":
    """Dialogue générique de gestion d'une liste de valeurs personnalisées.

    Affiche la liste des valeurs custom ; l'utilisateur peut en ajouter
    (champ texte + bouton « ＋ Ajouter ») ou en supprimer (sélection +
    bouton « − Supprimer »). Renvoie la nouvelle liste si OK, `None` si
    Annulé.
    """
    result: "dict[str, Optional[list[str]]]" = {"value": None}

    dlg = tk.Toplevel(parent)
    dlg.title(title)
    dlg.resizable(False, False)

    ttk.Label(dlg, text=title,
              style="H.TLabel").pack(anchor="w", padx=16, pady=(14, 2))
    ttk.Label(dlg, text=description,
              style="Muted.TLabel").pack(anchor="w", padx=16, pady=(0, 8))

    # --- Liste des niveaux existants ---
    list_frame = ttk.Frame(dlg)
    list_frame.pack(fill="both", padx=16, pady=(0, 8))

    lb = tk.Listbox(list_frame, height=6, width=32,
                    font=ui_font("Helvetica", 10),
                    selectmode="single", activestyle="none")
    sb = ttk.Scrollbar(list_frame, orient="vertical", command=lb.yview)
    lb.configure(yscrollcommand=sb.set)
    lb.pack(side="left", fill="both", expand=True)
    sb.pack(side="left", fill="y")

    items: list[str] = list(current)
    for item in items:
        lb.insert("end", item)

    # --- Champ d'ajout ---
    add_frame = ttk.Frame(dlg)
    add_frame.pack(fill="x", padx=16, pady=(0, 4))
    var_new = tk.StringVar()
    ent_new = ttk.Entry(add_frame, textvariable=var_new, width=24)
    ent_new.pack(side="left", padx=(0, 6))

    def _add() -> None:
        txt = var_new.get().strip()
        if not txt:
            return
        if txt in items:
            messagebox.showwarning("Doublon",
                                   f"« {txt} » est déjà dans la liste.",
                                   parent=dlg)
            return
        items.append(txt)
        lb.insert("end", txt)
        var_new.set("")
        ent_new.focus_set()

    ttk.Button(add_frame, text="＋ Ajouter", style="Accent.TButton",
               command=_add).pack(side="left")

    def _remove() -> None:
        sel = lb.curselection()
        if not sel:
            return
        idx = sel[0]
        lb.delete(idx)
        del items[idx]

    ttk.Button(dlg, text="− Supprimer la sélection", style="Ghost.TButton",
               command=_remove).pack(anchor="w", padx=16, pady=(0, 8))

    ttk.Separator(dlg, orient="horizontal").pack(fill="x", padx=16, pady=4)

    def _ok() -> None:
        result["value"] = list(items)
        dlg.destroy()

    def _cancel() -> None:
        dlg.destroy()

    btns = ttk.Frame(dlg)
    btns.pack(anchor="e", padx=16, pady=(4, 16))
    ttk.Button(btns, text="Annuler", style="Ghost.TButton",
               command=_cancel).pack(side="right", padx=(8, 0))
    ttk.Button(btns, text="OK", style="Accent.TButton",
               command=_ok).pack(side="right")

    ent_new.bind("<Return>", lambda e: _add())
    dlg.bind("<Escape>", lambda e: _cancel())

    _make_modal(dlg, parent)
    dlg.wait_window()
    return result["value"]


def ask_bareme_settings(
        parent: tk.Misc,
        seuils: "dict[str, dict[str, float]]",
        defaults: "dict[str, dict[str, float]]",
) -> "Optional[dict[str, dict[str, float]]]":
    """Dialogue de paramétrage du barème t/R (seuils Vert/Orange/Rouge).

    `seuils`   — dict courant {'libre': {'vert': 0.30, 'orange': 0.15}, 'strict': …}
    `defaults` — valeurs d'origine pour le bouton « Restaurer ».
    Retourne le nouveau dict si validé, None si annulé.

    Deux groupes de ports :
      • Libre / semi-libre / délaissé (végétation non contrainte)
      • Architecturé / traumatique    (végétation contrainte / taillée)

    Pour chaque groupe : seuil t/R Vert (%) et seuil t/R Orange (%),
    avec contrainte vert > orange > 0.
    """
    from dialogs_shared import validate_numeric

    result: "Optional[dict[str, dict[str, float]]]" = None

    dlg = tk.Toplevel(parent)
    dlg.title("Paramétrage du barème")
    dlg.resizable(False, False)

    content = ttk.Frame(dlg, padding=18)
    content.pack(fill="both", expand=True)

    ttk.Label(content,
              text="Seuils de classification t/R par groupe de port",
              font=ui_font("Helvetica", 11, "bold")).pack(anchor="w",
                                                          pady=(0, 4))
    ttk.Label(content,
              text="Vert = paroi saine (t/R > seuil Vert) · "
                   "Orange = paroi fragilisée · Rouge = paroi critique (t/R < seuil Orange)",
              wraplength=460, justify="left").pack(anchor="w", pady=(0, 12))

    GROUPES = [
        ("libre",  "Libre / Semi-libre / Délaissé",
         "Végétation en développement libre ou naturel"),
        ("strict", "Architecturé / Traumatique",
         "Végétation taillée ou ayant subi un traumatisme"),
    ]

    vcmd = (dlg.register(validate_numeric), "%P")
    entries: "dict[str, dict[str, ttk.Entry]]" = {}

    for grp_key, grp_label, grp_sub in GROUPES:
        box = ttk.LabelFrame(content, text=f" {grp_label} ", padding=10)
        box.pack(fill="x", pady=(0, 10))
        ttk.Label(box, text=grp_sub,
                  foreground="#555").pack(anchor="w", pady=(0, 8))

        row = ttk.Frame(box)
        row.pack(fill="x")
        entries[grp_key] = {}

        for col, (field, label, color) in enumerate([
            ("vert",   "Seuil Vert (%)",   "#1A6B2A"),
            ("orange", "Seuil Orange (%)", "#B85C00"),
        ]):
            cell = ttk.Frame(row)
            cell.grid(row=0, column=col, padx=(0, 20))
            ttk.Label(cell, text=label,
                      foreground=color,
                      font=ui_font("Helvetica", 10, "bold")).pack(anchor="w")
            val_pct = round(seuils[grp_key][field] * 100, 2)
            var = tk.StringVar(value=f"{val_pct:g}")
            e = ttk.Entry(cell, textvariable=var, width=8,
                          validate="key", validatecommand=vcmd)
            e.pack(anchor="w", pady=(2, 0))
            entries[grp_key][field] = e

            def _make_hint(k: str, f: str) -> str:
                return f"  (défaut : {defaults[k][f]*100:g} %)"
            ttk.Label(cell,
                      text=_make_hint(grp_key, field),
                      foreground="#888",
                      font=ui_font("Helvetica", 8)).pack(anchor="w")

    def _parse() -> "Optional[dict[str, dict[str, float]]]":
        out: "dict[str, dict[str, float]]" = {}
        for grp_key, _, __ in GROUPES:
            try:
                vert   = float(entries[grp_key]["vert"].get().replace(",", ".")) / 100
                orange = float(entries[grp_key]["orange"].get().replace(",", ".")) / 100
            except ValueError:
                messagebox.showerror("Valeur invalide",
                                     "Saisissez des nombres (ex. 30, 15).",
                                     parent=dlg)
                return None
            if not (0 < orange < vert <= 1):
                messagebox.showerror(
                    "Seuils incohérents",
                    f"Pour le groupe « {grp_key} » : le seuil Vert doit être "
                    f"strictement supérieur au seuil Orange, et les deux entre "
                    f"0 % et 100 %.\n\nEx. Vert = 30, Orange = 15.",
                    parent=dlg)
                return None
            out[grp_key] = {"vert": round(vert, 4), "orange": round(orange, 4)}
        return out

    def _restore_defaults() -> None:
        for grp_key, _, __ in GROUPES:
            for field in ("vert", "orange"):
                v = defaults[grp_key][field] * 100
                entries[grp_key][field].delete(0, "end")
                entries[grp_key][field].insert(0, f"{v:g}")

    def _ok() -> None:
        nonlocal result
        parsed = _parse()
        if parsed is not None:
            result = parsed
            dlg.destroy()

    def _cancel() -> None:
        dlg.destroy()

    sep = ttk.Separator(content, orient="horizontal")
    sep.pack(fill="x", pady=(8, 10))

    btns = ttk.Frame(content)
    btns.pack(fill="x")
    ttk.Button(btns, text="Restaurer les valeurs par défaut",
               style="Ghost.TButton",
               command=_restore_defaults).pack(side="left")
    ttk.Button(btns, text="Annuler",
               style="Ghost.TButton",
               command=_cancel).pack(side="right")
    ttk.Button(btns, text="Enregistrer",
               style="Accent.TButton",
               command=_ok).pack(side="right", padx=(0, 6))

    dlg.bind("<Return>", lambda e: _ok())
    dlg.bind("<Escape>", lambda e: _cancel())
    _make_modal(dlg, parent)
    dlg.wait_window()
    return result


def ask_urgences_custom(parent: tk.Misc,
                        current: "list[str]") -> "Optional[list[str]]":
    """Dialogue de gestion des niveaux d'urgence personnalisés (wrapper)."""
    return ask_list_custom(
        parent,
        "Niveaux d'urgence personnalisés",
        "Ces niveaux s'ajoutent aux niveaux standard dans le combobox.",
        current,
    )


def ask_suivi_custom(parent: tk.Misc,
                     current: "list[str]") -> "Optional[list[str]]":
    """Dialogue de gestion des durées de suivi personnalisées."""
    return ask_list_custom(
        parent,
        "Durées de suivi personnalisées",
        "Ces durées s'ajoutent aux durées standard dans le combobox.",
        current,
    )
