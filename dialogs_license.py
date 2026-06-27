"""
Dialogue d'activation de licence — affiché au démarrage si aucune
licence valide n'est trouvée. Non-dismissable : fermer = quitter.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING, Optional

from palette import COLOR_ACCENT, COLOR_BG, COLOR_INK, COLOR_MUTED, COLOR_WARN

if TYPE_CHECKING:
    from license import LicenseData


def show_activation_dialog(root: tk.Tk) -> "Optional[LicenseData]":
    """Affiche la fenêtre d'activation et retourne LicenseData si succès, None si abandon."""
    from license import save_license, verify_license

    result: list[Optional[LicenseData]] = [None]

    dlg = tk.Toplevel()
    dlg.title("Activation — Pénétromètre")
    dlg.resizable(False, False)
    dlg.configure(bg=COLOR_BG)

    dlg.update_idletasks()
    w, h = 540, 380
    sw = dlg.winfo_screenwidth()
    sh = dlg.winfo_screenheight()
    dlg.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

    # Empêche la fermeture sans quitter
    def on_close() -> None:
        import sys
        dlg.destroy()
        root.destroy()
        sys.exit(0)

    dlg.protocol("WM_DELETE_WINDOW", on_close)

    # --- Contenu ---
    outer = ttk.Frame(dlg, padding=30)
    outer.pack(fill="both", expand=True)

    ttk.Label(
        outer,
        text="Pénétromètre — Activation",
        font=("Helvetica", 15, "bold"),
        foreground=COLOR_ACCENT,
    ).pack(anchor="w")

    ttk.Separator(outer).pack(fill="x", pady=(8, 16))

    ttk.Label(
        outer,
        text="Ce logiciel nécessite une licence valide pour fonctionner.\n"
             "Saisissez ou collez la clé reçue par email :",
        foreground=COLOR_INK,
        wraplength=480,
        justify="left",
    ).pack(anchor="w")

    # Zone de saisie de la clé
    frm_key = ttk.Frame(outer)
    frm_key.pack(fill="x", pady=(12, 0))

    txt_key = tk.Text(
        frm_key,
        height=4,
        wrap="char",
        font=("Courier", 9),
        relief="solid",
        bd=1,
        bg="#FFFFFF",
        fg=COLOR_INK,
        insertbackground=COLOR_INK,
    )
    txt_key.pack(fill="x")
    txt_key.focus_set()

    # Label d'état (erreur / succès)
    lbl_status = ttk.Label(outer, text="", foreground=COLOR_WARN)
    lbl_status.pack(anchor="w", pady=(6, 0))

    # Boutons
    frm_btn = ttk.Frame(outer)
    frm_btn.pack(fill="x", pady=(16, 0))

    def on_activate() -> None:
        key = txt_key.get("1.0", "end").strip()
        if not key:
            lbl_status.config(text="Veuillez saisir une clé.")
            return
        ld = verify_license(key)
        if ld is None:
            lbl_status.config(text="Clé invalide ou expirée. Contactez e.colinet@silvavenir.fr")
            return
        save_license(key)
        result[0] = ld
        dlg.destroy()

    btn_activate = ttk.Button(
        frm_btn, text="Activer", style="Accent.TButton", command=on_activate
    )
    btn_activate.pack(side="left")

    ttk.Button(frm_btn, text="Quitter", command=on_close).pack(side="right")

    ttk.Label(
        outer,
        text="Pour obtenir une licence : e.colinet@silvavenir.fr",
        foreground=COLOR_MUTED,
        font=("Helvetica", 8),
    ).pack(anchor="w", pady=(20, 0))

    dlg.bind("<Return>", lambda e: on_activate())
    dlg.bind("<Escape>", lambda e: on_close())

    root.wait_window(dlg)
    return result[0]
