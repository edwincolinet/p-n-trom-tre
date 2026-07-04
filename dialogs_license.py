"""
Dialogue d'activation de licence — affiché au démarrage si aucune
licence valide n'est trouvée. Non-dismissable : fermer = quitter.

Retourne :
  LicenseData  si l'utilisateur a activé une clé valide,
  TrialInfo    si l'utilisateur a démarré / repris le mode essai,
  None         si l'utilisateur a choisi de quitter.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING, Optional, Union

from palette import COLOR_ACCENT, COLOR_BG, COLOR_INK, COLOR_MUTED, COLOR_WARN

if TYPE_CHECKING:
    from license import LicenseData, TrialInfo

ActivationResult = Union["LicenseData", "TrialInfo"]


def show_activation_dialog(root: tk.Tk) -> Optional[ActivationResult]:
    """Affiche la fenêtre d'activation.

    Retourne LicenseData, TrialInfo ou None (= quitter).
    """
    from license import (
        get_machine_id,
        get_trial_info,
        save_license,
        start_trial,
        verify_license,
    )

    result: list[Optional[ActivationResult]] = [None]

    # Vérifier si un essai est déjà en cours (expiré ou actif)
    existing_trial = get_trial_info()
    trial_already_started = existing_trial is not None

    dlg = tk.Toplevel()
    dlg.title("Activation — Pénétromètre")
    dlg.resizable(False, False)
    dlg.configure(bg=COLOR_BG)

    dlg.update_idletasks()
    w, h = 560, 480
    sw = dlg.winfo_screenwidth()
    sh = dlg.winfo_screenheight()
    dlg.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

    def on_close() -> None:
        import sys
        dlg.destroy()
        root.destroy()
        sys.exit(0)

    dlg.protocol("WM_DELETE_WINDOW", on_close)

    outer = ttk.Frame(dlg, padding=28)
    outer.pack(fill="both", expand=True)

    ttk.Label(
        outer,
        text="Pénétromètre — Activation",
        font=("Helvetica", 15, "bold"),
        foreground=COLOR_ACCENT,
    ).pack(anchor="w")

    ttk.Separator(outer).pack(fill="x", pady=(8, 14))

    ttk.Label(
        outer,
        text="Ce logiciel nécessite une licence valide.\n"
             "Saisissez la clé reçue par email, ou démarrez l'essai gratuit 30 jours.",
        foreground=COLOR_INK,
        wraplength=504,
        justify="left",
    ).pack(anchor="w")

    # --- Identifiant machine ---
    machine_id = get_machine_id()
    frm_mid = ttk.Frame(outer)
    frm_mid.pack(fill="x", pady=(12, 0))

    ttk.Label(frm_mid, text="Identifiant machine :",
              style="Muted.TLabel").pack(side="left")
    mid_var = tk.StringVar(value=machine_id)
    ent_mid = ttk.Entry(frm_mid, textvariable=mid_var, width=14,
                        state="readonly", font=("Courier", 10))
    ent_mid.pack(side="left", padx=(6, 4))

    def copy_mid() -> None:
        dlg.clipboard_clear()
        dlg.clipboard_append(machine_id)
        btn_copy.configure(text="✓ Copié")
        dlg.after(2000, lambda: btn_copy.configure(text="Copier"))

    btn_copy = ttk.Button(frm_mid, text="Copier", command=copy_mid, width=8)
    btn_copy.pack(side="left")

    ttk.Label(
        outer,
        text="Communiquez cet identifiant lors de votre demande de licence "
             "pour obtenir une clé liée à cette machine.",
        foreground=COLOR_MUTED,
        wraplength=504,
        justify="left",
        font=("Helvetica", 8),
    ).pack(anchor="w", pady=(2, 0))

    ttk.Separator(outer).pack(fill="x", pady=(12, 12))

    # --- Zone de saisie de la clé ---
    ttk.Label(outer, text="Clé d'activation :", foreground=COLOR_INK).pack(anchor="w")

    frm_key = ttk.Frame(outer)
    frm_key.pack(fill="x", pady=(4, 0))

    txt_key = tk.Text(
        frm_key,
        height=3,
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

    # --- Boutons ---
    frm_btn = ttk.Frame(outer)
    frm_btn.pack(fill="x", pady=(14, 0))

    def on_activate() -> None:
        key = txt_key.get("1.0", "end").strip()
        if not key:
            lbl_status.config(text="Veuillez saisir une clé d'activation.")
            return
        ld = verify_license(key)
        if ld is None:
            lbl_status.config(
                text="Clé invalide, expirée ou liée à une autre machine.")
            return
        save_license(key)
        result[0] = ld
        dlg.destroy()

    ttk.Button(
        frm_btn, text="Activer", style="Accent.TButton", command=on_activate
    ).pack(side="left")

    def on_trial() -> None:
        trial = start_trial()
        result[0] = trial
        dlg.destroy()

    if not trial_already_started:
        btn_trial = ttk.Button(frm_btn, text="Essai gratuit 30 jours",
                               command=on_trial)
        btn_trial.pack(side="left", padx=(10, 0))

    ttk.Button(frm_btn, text="Quitter", command=on_close).pack(side="right")

    ttk.Label(
        outer,
        text="Pour obtenir une licence : e.colinet@silvavenir.fr",
        foreground=COLOR_MUTED,
        font=("Helvetica", 8),
    ).pack(anchor="w", pady=(16, 0))

    dlg.bind("<Return>", lambda e: on_activate())
    dlg.bind("<Escape>", lambda e: on_close())

    root.wait_window(dlg)
    return result[0]
