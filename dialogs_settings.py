"""Dialogues de configuration du cabinet et des listes personnalisées.

Extraits de `dialogs.py` pour en réduire la taille. Ces dialogues ne
sont appelés que depuis `penetrometre.py` (paramètres cabinet) et
`pane_diagnostic.py` (urgences / suivi custom).
"""

from __future__ import annotations

import itertools
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Dict, List, Optional

from bareme import PORTS_ARBRE, GroupeBareme
from dialogs import _make_modal
from i18n import _
from ui_fonts import font_body, font_body_bold, font_small_bold, font_subheading


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
    ttk.Label(dlg, text=_("Nom du cabinet :")).grid(
        row=0, column=0, sticky="w", padx=(16, 8), pady=(16, 6))
    var_name = tk.StringVar(value=getattr(settings, "cabinet_name", ""))
    ttk.Entry(dlg, textvariable=var_name, width=34).grid(
        row=0, column=1, columnspan=2, sticky="ew", padx=(0, 16), pady=(16, 6))

    # --- Logo ---
    ttk.Label(dlg, text=_("Logo :")).grid(
        row=1, column=0, sticky="nw", padx=(16, 8), pady=(6, 0))

    btn_frame = ttk.Frame(dlg)
    btn_frame.grid(row=1, column=1, columnspan=2, sticky="w",
                   padx=(0, 16), pady=(6, 0))

    preview_lbl = ttk.Label(dlg, style="Muted.TLabel")
    preview_lbl.grid(row=2, column=0, columnspan=3, padx=16, pady=(6, 4))

    ttk.Label(dlg, text=_("Formats acceptés : PNG, JPEG, GIF, BMP, TIFF"),
              style="Muted.TLabel").grid(
        row=3, column=0, columnspan=3, padx=16, pady=(0, 12))

    def _update_preview(path: "str | None") -> None:
        _pending_logo[0] = path
        if not path:
            preview_lbl.configure(image="", text=_("Aucun logo configuré"))
            _preview_img[0] = None
            return
        try:
            from PIL import Image as _PILImage
            from PIL import ImageTk as _ImageTk
            pil = _PILImage.open(path)
            target_h = 80
            ratio = target_h / pil.height
            resized = pil.resize(
                (int(pil.width * ratio), target_h),
                _PILImage.Resampling.LANCZOS)
            img = _ImageTk.PhotoImage(resized)
            _preview_img[0] = img
            preview_lbl.configure(image=img, text="")
        except ImportError:
            preview_lbl.configure(image="",
                                  text=_("(aperçu indisponible — Pillow requis)"))
        except Exception:
            preview_lbl.configure(image="", text=_("(image illisible)"))

    _update_preview(_pending_logo[0])

    def _choose_logo() -> None:
        p = _filedialog.askopenfilename(
            parent=dlg,
            title=_("Choisir un logo"),
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

    ttk.Button(btn_frame, text=_("Choisir un fichier…"),
               command=_choose_logo).pack(side="left", padx=(0, 8))
    ttk.Button(btn_frame, text=_("Supprimer"),
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
    ttk.Button(btns, text=_("Annuler"), style="Ghost.TButton",
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
                    font=font_body(),
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
            messagebox.showwarning(_("Doublon"),
                                   f"« {txt} » est déjà dans la liste.",
                                   parent=dlg)
            return
        items.append(txt)
        lb.insert("end", txt)
        var_new.set("")
        ent_new.focus_set()

    ttk.Button(add_frame, text=_("＋ Ajouter"), style="Accent.TButton",
               command=_add).pack(side="left")

    def _remove() -> None:
        sel = lb.curselection()
        if not sel:
            return
        idx = sel[0]
        lb.delete(idx)
        del items[idx]

    ttk.Button(dlg, text=_("− Supprimer la sélection"), style="Ghost.TButton",
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


class _EditGroup:
    """État d'édition d'UN groupe dans `ask_bareme_settings` (id stable,
    indépendant de la position d'affichage — survit aux
    ajouts/suppressions/réordonnancements d'autres groupes)."""

    def __init__(self, gid: int, nom: str, seuil_vert_pct: float,
                seuil_orange_pct: float) -> None:
        self.gid = gid
        self.nom = tk.StringVar(value=nom)
        self.vert = tk.StringVar(value=f"{seuil_vert_pct:g}")
        self.orange = tk.StringVar(value=f"{seuil_orange_pct:g}")


def ask_bareme_settings(
        parent: tk.Misc,
        groupes: "List[GroupeBareme]",
        defaults: "List[GroupeBareme]",
) -> "Optional[List[GroupeBareme]]":
    """Éditeur complet du barème t/R : seuils Vert/Orange **par groupe de
    ports**, groupes librement composés par l'expert (jusqu'à un groupe
    par port individuel).

    `groupes`  — partition courante (`bareme.get_groupes()`).
    `defaults` — partition d'origine pour le bouton « Restaurer »
    (`bareme.GROUPES_DEFAUT`).
    Retourne la nouvelle partition si validée, `None` si annulé.

    Chaque port de `bareme.PORTS_ARBRE` appartient à **exactement un**
    groupe : garanti PAR CONSTRUCTION (pas par validation a posteriori) —
    chaque port a une seule `tk.StringVar` (id du groupe propriétaire)
    partagée par ses `Radiobutton` dans le tableau d'assignation ; changer
    de colonne désélectionne automatiquement l'ancienne (exclusivité Tk
    native), donc aucun port ne peut se retrouver sans groupe ou dans deux
    groupes à la fois.
    """
    from dialogs_shared import validate_numeric

    result: "Optional[List[GroupeBareme]]" = None
    counter = itertools.count()

    dlg = tk.Toplevel(parent)
    dlg.title(_("Paramétrage du barème"))
    dlg.resizable(False, False)

    content = ttk.Frame(dlg, padding=18)
    content.pack(fill="both", expand=True)

    ttk.Label(content,
              text=_("Seuils de classification t/R par groupe de port"),
              font=font_subheading()).pack(anchor="w",
                                                          pady=(0, 4))
    ttk.Label(content,
              text=_("Vert = paroi saine (t/R > seuil Vert) · ")
                   + "Orange = paroi fragilisée · Rouge = paroi critique (t/R < seuil Orange)",
              wraplength=520, justify="left").pack(anchor="w", pady=(0, 4))
    ttk.Label(content,
              text=_("Chaque port appartient à un seul groupe de seuils : "
                     "composez vos propres groupes (même un port par "
                     "groupe) ou gardez le découpage par défaut."),
              foreground="#555", wraplength=520,
              justify="left").pack(anchor="w", pady=(0, 12))

    groups: "List[_EditGroup]" = []
    port_owner: "Dict[str, tk.StringVar]" = {}

    def _populate_from(src: "List[GroupeBareme]") -> None:
        for g in src:
            eg = _EditGroup(next(counter), g.nom, g.seuil_vert * 100,
                            g.seuil_orange * 100)
            groups.append(eg)
            for p in g.ports:
                port_owner[p] = tk.StringVar(value=str(eg.gid))
        # Ports absents de `src` (config incomplète) : rattachés au 1er
        # groupe pour ne jamais laisser un port sans variable.
        for p in PORTS_ARBRE:
            if p not in port_owner:
                port_owner[p] = tk.StringVar(value=str(groups[0].gid))

    _populate_from(groupes)

    groups_frame = ttk.Frame(content)
    groups_frame.pack(fill="x")
    ttk.Label(content, text="").pack(pady=(2, 2))  # espace fixe
    add_row = ttk.Frame(content)
    add_row.pack(fill="x", pady=(0, 10))

    ttk.Separator(content, orient="horizontal").pack(fill="x", pady=(0, 10))
    ttk.Label(content, text=_("Port de l'arbre → groupe"),
              font=font_body_bold()).pack(anchor="w",
                                                          pady=(0, 6))
    matrix_frame = ttk.Frame(content)
    matrix_frame.pack(fill="x", pady=(0, 10))

    vcmd = (dlg.register(validate_numeric), "%P")

    def _delete_group(gid: int) -> None:
        if len(groups) <= 1:
            return
        idx = next(i for i, g in enumerate(groups) if g.gid == gid)
        fallback = groups[0].gid if idx != 0 else groups[1].gid
        for var in port_owner.values():
            if var.get() == str(gid):
                var.set(str(fallback))
        del groups[idx]
        _rebuild()

    def _add_group() -> None:
        groups.append(_EditGroup(next(counter),
                                 _("Nouveau groupe"), 30.0, 15.0))
        _rebuild()

    def _rebuild() -> None:
        for w in groups_frame.winfo_children():
            w.destroy()
        for w in add_row.winfo_children():
            w.destroy()
        for w in matrix_frame.winfo_children():
            w.destroy()

        headers = [_("Nom du groupe"), _("Vert (%)"), _("Orange (%)"), ""]
        for c, h in enumerate(headers):
            ttk.Label(groups_frame, text=h,
                      font=font_small_bold()).grid(
                row=0, column=c, sticky="w", padx=(0, 10), pady=(0, 4))
        for r, eg in enumerate(groups, start=1):
            ttk.Entry(groups_frame, textvariable=eg.nom, width=28).grid(
                row=r, column=0, sticky="we", padx=(0, 10), pady=2)
            ttk.Entry(groups_frame, textvariable=eg.vert, width=7,
                     validate="key", validatecommand=vcmd).grid(
                row=r, column=1, sticky="w", padx=(0, 10), pady=2)
            ttk.Entry(groups_frame, textvariable=eg.orange, width=7,
                     validate="key", validatecommand=vcmd).grid(
                row=r, column=2, sticky="w", padx=(0, 10), pady=2)
            btn = ttk.Button(groups_frame, text="✕", width=3,
                             style="Ghost.TButton",
                             command=lambda gid=eg.gid: _delete_group(gid))
            if len(groups) <= 1:
                btn.state(["disabled"])
            btn.grid(row=r, column=3, sticky="w")

        ttk.Button(add_row, text=_("＋ Nouveau groupe"),
                  style="Ghost.TButton", command=_add_group).pack(anchor="w")

        for c, eg in enumerate(groups, start=1):
            ttk.Label(matrix_frame, textvariable=eg.nom,
                     font=font_small_bold(),
                     wraplength=140, justify="center").grid(
                row=0, column=c, padx=8, pady=(0, 6))
        for r, port in enumerate(PORTS_ARBRE, start=1):
            ttk.Label(matrix_frame, text=port).grid(
                row=r, column=0, sticky="w", padx=(0, 14), pady=2)
            for c, eg in enumerate(groups, start=1):
                ttk.Radiobutton(matrix_frame, variable=port_owner[port],
                               value=str(eg.gid)).grid(
                    row=r, column=c, pady=2)

    _rebuild()

    def _parse() -> "Optional[List[GroupeBareme]]":
        ports_par_groupe: "Dict[int, List[str]]" = {g.gid: [] for g in groups}
        for p, var in port_owner.items():
            ports_par_groupe[int(var.get())].append(p)
        out: "List[GroupeBareme]" = []
        for g in groups:
            nom = g.nom.get().strip()
            if not nom:
                messagebox.showerror(_("Nom manquant"),
                                     _("Chaque groupe doit avoir un nom."),
                                     parent=dlg)
                return None
            ports = ports_par_groupe[g.gid]
            if not ports:
                messagebox.showerror(
                    _("Groupe vide"),
                    _("Le groupe « {nom} » n'a aucun port assigné. "
                      "Assignez-lui au moins un port (tableau ci-dessous) "
                      "ou supprimez-le.").format(nom=nom),
                    parent=dlg)
                return None
            try:
                vert = float(g.vert.get().replace(",", ".")) / 100
                orange = float(g.orange.get().replace(",", ".")) / 100
            except ValueError:
                messagebox.showerror(_("Valeur invalide"),
                                     _("Groupe « {nom} » : saisissez des "
                                       "nombres (ex. 30, 15).").format(nom=nom),
                                     parent=dlg)
                return None
            if not (0 < orange < vert <= 1):
                messagebox.showerror(
                    _("Seuils incohérents"),
                    _("Pour le groupe « {nom} » : le seuil Vert doit être "
                      "strictement supérieur au seuil Orange, et les deux "
                      "entre 0 % et 100 %.\n\nEx. Vert = 30, "
                      "Orange = 15.").format(nom=nom),
                    parent=dlg)
                return None
            out.append(GroupeBareme(nom, tuple(ports),
                                    round(vert, 4), round(orange, 4)))
        return out

    def _restore_defaults() -> None:
        groups.clear()
        port_owner.clear()
        _populate_from(defaults)
        _rebuild()

    def _ok() -> None:
        nonlocal result
        parsed = _parse()
        if parsed is not None:
            result = parsed
            dlg.destroy()

    def _cancel() -> None:
        dlg.destroy()

    ttk.Separator(content, orient="horizontal").pack(fill="x", pady=(4, 10))

    btns = ttk.Frame(content)
    btns.pack(fill="x")
    ttk.Button(btns, text=_("Restaurer les valeurs par défaut"),
               style="Ghost.TButton",
               command=_restore_defaults).pack(side="left")
    ttk.Button(btns, text="Annuler",
               style="Ghost.TButton",
               command=_cancel).pack(side="right")
    ttk.Button(btns, text=_("Enregistrer"),
               style="Accent.TButton",
               command=_ok).pack(side="right", padx=(0, 6))

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
