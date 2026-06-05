"""
Pénétromètre — Application d'expertise
======================================

- multi-arbres dans un fichier « mission » (.json),
- tableau de sondages ↔ dessin synchronisés (altération = cavité interne),
- dessin vectoriel natif (Tkinter Canvas) avec interpolation spline
  pour une section réellement ronde,
- contreforts (empattements) et dégradations externes,
- export PNG du dessin et fiche PDF A4 par arbre.

Dépendances : Python 3.9+, tkinter (stdlib), Pillow (PNG/PDF).
"""

from __future__ import annotations

import copy
import json
import logging
import os
import tkinter as tk
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Iterator, Optional

import app_exports
from app_menu import build_menu, refresh_recent_menu
from app_style import apply_ttk_styles
from dialogs import ask_string, edit_contrefort, edit_degradation, edit_sondage
from model import Arbre, Chantier, Contrefort, DegradationExterne, Sondage
from palette import COLOR_BG
from pane_contreforts import ContrefortsPane
from pane_degradations import DegradationsPane
from pane_diagnostic import DiagnosticPane
from pane_identification import IdentificationPane
from pane_sondages import SondagesPane
from persistence import (
    chantier_from_dict,
    chantier_to_dict,
    clear_recovery,
    load_chantier,
    load_recovery,
    save_chantier,
    save_recovery,
)
from section_canvas import SectionCanvas
from tooltip import Tooltip
from undo import UndoStack

__version__ = "3.3.0"

# Fichiers récents : on en garde 8, persistés en JSON dans le même
# répertoire que le log (~/.penetrometre/). 8 est un bon compromis :
# tient en un sous-menu compact, suffisant pour 1-2 semaines d'usage.
_RECENT_FILES_MAX = 8
_RECENT_FILES_PATH = Path.home() / ".penetrometre" / "recent.json"

# Sauvegarde de récupération (autosave anti-crash). Écrite périodiquement
# tant que la mission a des modifications non enregistrées, et effacée dès
# qu'on atteint un état propre (enregistrement, nouvelle mission, ouverture)
# ou à la fermeture normale. Sa seule présence au démarrage signale donc
# un crash précédent avec du travail non sauvegardé → on propose la reprise.
_RECOVERY_PATH = Path.home() / ".penetrometre" / "recovery" / "autosave.json"
_AUTOSAVE_INTERVAL_MS = 60_000  # 60 s


# Logger applicatif — configuré par `_setup_logging()` au démarrage.
# Tant qu'aucun handler n'est attaché (cas tests / import du module
# sans `main()`), les messages partent dans le vide silencieusement.
log = logging.getLogger("penetrometre")


# ---------------------------------------------------------------------------
# Application principale
# ---------------------------------------------------------------------------

class App(tk.Tk):

    def __init__(self) -> None:
        super().__init__()
        # minsize ajusté pour rester utilisable sur écrans 1366×768
        # (très répandus sur laptops de terrain). Le canvas se redimensionne
        # tout seul, les onglets restent lisibles à cette taille.
        self.minsize(1100, 680)
        # Géométrie souhaitée 1480×900, mais on clamp à 95 % de l'écran
        # disponible pour éviter qu'au démarrage la fenêtre déborde
        # (Windows : barre des tâches ; Linux : panel + barre titre).
        self.update_idletasks()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        w = min(1480, max(1100, int(screen_w * 0.95)))
        h = min(900, max(680, int(screen_h * 0.95)))
        self.geometry(f"{w}x{h}")
        self.configure(bg=COLOR_BG)

        self.chantier = Chantier()
        self.chantier.arbres.append(Arbre(numero_arbre="1"))
        self.current_idx = 0
        self.current_file: Optional[Path] = None
        self._dirty = False
        self._suspend_sync = False
        self._redraw_id: Optional[str] = None
        self._undo_stack = UndoStack()
        self._recent_files: list[str] = self._load_recent_files()
        # Dernier fichier exporté — cible des boutons « Ouvrir le
        # fichier / le dossier » de la barre d'état (cf. notify_export).
        self._last_export_path: Optional[Path] = None
        self.pane_s: Optional[SondagesPane] = None
        self.pane_de: Optional[DegradationsPane] = None
        self.pane_cf: Optional[ContrefortsPane] = None
        self.pane_diag: Optional[DiagnosticPane] = None

        apply_ttk_styles(self)
        build_menu(self)  # type: ignore[arg-type]
        self._build_layout()
        self._refresh_tree_arbres()
        self._load_arbre_to_ui()
        self._update_title()

        self.bind_all("<Control-z>", lambda e: self._perform_undo())
        self.bind_all("<Control-y>", lambda e: self._perform_redo())
        self.bind_all("<Control-Z>", lambda e: self._perform_redo())
        self.bind_all("<Control-e>", self._on_export_shortcut)
        # Navigation clavier entre arbres (Ctrl+PageDown/PageUp). Libre de
        # conflit : ttk.Notebook ne lie que Ctrl+Tab.
        self.bind_all("<Control-Next>", lambda e: self.action_next_arbre())
        self.bind_all("<Control-Prior>", lambda e: self.action_prev_arbre())
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Autosave anti-crash : on programme le 1er tick et on vérifie au
        # démarrage (fenêtre déjà mappée → le dialogue de reprise s'affiche
        # par-dessus une UI visible) s'il reste un autosave d'une session
        # précédente non refermée proprement.
        self._autosave_after_id: Optional[str] = None
        self._schedule_autosave()
        self.after(200, self._check_recovery_on_startup)

    def _on_export_shortcut(self, _event: "tk.Event[tk.Misc]") -> None:
        """Ctrl+E → fiche PDF de l'arbre courant. Neutralisé quand un
        champ texte a le focus : dans les `Entry`/`Combobox` Tk, Ctrl+E
        signifie « aller en fin de ligne » — on laisse le widget gérer
        plutôt que d'ouvrir un dialogue d'export en pleine saisie."""
        w = self.focus_get()
        if isinstance(w, (ttk.Entry, ttk.Combobox, tk.Entry)):
            return
        self.action_export_pdf_arbre()

    def _build_layout(self) -> None:
        header = ttk.Frame(self)
        header.pack(fill="x", padx=18, pady=(14, 6))

        # Bloc gauche : titre app
        left = ttk.Frame(header)
        left.pack(side="left")
        ttk.Label(left, text="Pénétromètre",
                  style="Title.TLabel").pack(side="left")
        ttk.Label(left, text="  Expertise arboricole",
                  style="Sub.TLabel").pack(side="left", padx=(8, 0))

        # Bloc droit : logo Silvavenir (si disponible).
        # PIL est requis pour les exports PNG/PDF — s'il est absent au
        # démarrage, l'utilisateur l'apprend ici (log + fallback texte)
        # plutôt qu'au moment d'un clic « Exporter PDF » qui échouerait
        # silencieusement. Le diagnostic est distingué de l'échec de
        # chargement du logo (fichier manquant, image corrompue), qui
        # est bénin.
        self._logo_image = None
        logo_loaded = False
        try:
            from PIL import Image as PILImage
            from PIL import ImageTk
            logo_path = Path(__file__).parent / "assets" / "silvavenir_logo.jpg"
            if logo_path.exists():
                pil = PILImage.open(logo_path)
                # Redimensionner à 60 px de haut en gardant le ratio
                target_h = 56
                ratio = target_h / pil.height
                pil = pil.resize(  # type: ignore[assignment]
                    (int(pil.width * ratio), target_h),
                    PILImage.LANCZOS)  # type: ignore[attr-defined]
                self._logo_image = ImageTk.PhotoImage(pil)
                ttk.Label(header, image=self._logo_image
                          ).pack(side="right")
                logo_loaded = True
            else:
                log.warning("Logo Silvavenir introuvable à %s",
                            logo_path)
        except ImportError as exc:
            log.warning(
                "Pillow indisponible (%s) — les exports PNG et PDF "
                "ne pourront pas être générés. Installer Pillow via "
                "`pip install -r requirements.txt`.", exc)
        except Exception:
            log.exception("Échec du chargement du logo")
        if not logo_loaded:
            # Fallback texte (Pillow absent, logo manquant ou
            # image illisible)
            ttk.Label(header, text="SILVAVENIR",
                      style="Title.TLabel").pack(side="right")

        meta = ttk.Frame(self)
        meta.pack(fill="x", padx=18, pady=(0, 10))
        self.var_ch_nom = tk.StringVar(value=self.chantier.nom)
        self.var_ch_adr = tk.StringVar(value=self.chantier.adresse)
        self.var_ch_ope = tk.StringVar(value=self.chantier.operateur)
        self.var_ch_date = tk.StringVar(value=self.chantier.date_releve)
        self._meta_snapshot: Optional[str] = None
        for lbl, var, w in [("Mission", self.var_ch_nom, 22),
                            ("Adresse", self.var_ch_adr, 30),
                            ("Opérateur", self.var_ch_ope, 18),
                            ("Date", self.var_ch_date, 12)]:
            ttk.Label(meta, text=lbl).pack(side="left", padx=(0, 4))
            e = ttk.Entry(meta, textvariable=var, width=w)
            e.pack(side="left", padx=(0, 14))
            var.trace_add("write", lambda *a: self._sync_chantier_meta())
            e.bind("<FocusIn>", lambda ev: self._meta_focus_in())
            e.bind("<FocusOut>", lambda ev: self._meta_focus_out())

        # Barre d'état AVANT le body : packée en bas, le body (expand)
        # remplit l'espace restant au-dessus.
        self._build_statusbar()

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=18, pady=(0, 14))
        body.columnconfigure(0, weight=0, minsize=230)
        body.columnconfigure(1, weight=0, minsize=440)
        body.columnconfigure(2, weight=1, minsize=500)
        body.rowconfigure(0, weight=1)
        self._build_left(body)
        self._build_center(body)
        self._build_right(body)

    def _build_left(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent, style="Side.TFrame", padding=10)
        frame.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        ttk.Label(frame, text="Arbres de la mission", style="Side.TLabel",
                  font=("Georgia", 12, "bold")).pack(anchor="w", pady=(0, 8))

        # Filtre de la liste (par n° ou essence) — utile dès que la
        # mission compte beaucoup d'arbres. N'altère PAS le modèle : ne
        # fait que masquer les lignes non concordantes (les iid `a{i}`
        # restent indexés sur la position réelle dans `chantier.arbres`,
        # cf. `_on_select_arbre`). `var_filter` est lue par
        # `_refresh_tree_arbres` (tolérante si appelée avant ce build).
        filt = ttk.Frame(frame, style="Side.TFrame")
        filt.pack(fill="x", pady=(0, 6))
        ttk.Label(filt, text="🔎", style="Side.TLabel").pack(side="left",
                                                             padx=(0, 4))
        self.var_filter = tk.StringVar()
        ent_filter = ttk.Entry(filt, textvariable=self.var_filter)
        ent_filter.pack(side="left", fill="x", expand=True)
        self.var_filter.trace_add("write",
                                  lambda *a: self._refresh_tree_arbres())
        # Échap dans le champ = vider le filtre.
        ent_filter.bind("<Escape>", lambda e: self.var_filter.set(""))

        lst_frame = ttk.Frame(frame, style="Side.TFrame")
        lst_frame.pack(fill="both", expand=True)
        self.tree_arbres = ttk.Treeview(
            lst_frame, columns=("ess", "etat"), show="tree headings",
            height=20, style="Side.Treeview")
        self.tree_arbres.heading("#0", text="Nom")
        self.tree_arbres.heading("ess", text="Essence")
        self.tree_arbres.heading("etat", text="État")
        self.tree_arbres.column("#0", width=110, anchor="w")
        self.tree_arbres.column("ess", width=80, anchor="w")
        self.tree_arbres.column("etat", width=42, anchor="center",
                                stretch=False)
        # Tags par état : coloration du foreground de toute la ligne
        # (rouge/orange/vert discrets). Plus fiable que des emojis
        # 🔴🟠🟢 dont le rendu dans ttk.Treeview dépend du thème et de
        # la police système (peut tomber sur une font monochrome où
        # les trois pastilles deviennent identiques).
        # Orange volontairement décalé vers le jaune (saturé) pour
        # bien se distinguer du rouge bordeaux.
        self.tree_arbres.tag_configure("etat_vide",
                                        foreground="#A62A1F")
        self.tree_arbres.tag_configure("etat_partiel",
                                        foreground="#D97706")
        self.tree_arbres.tag_configure("etat_ok",
                                        foreground="#1A5A2A")
        self.tree_arbres.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(lst_frame, orient="vertical",
                           command=self.tree_arbres.yview)
        sb.pack(side="right", fill="y")
        self.tree_arbres.configure(yscrollcommand=sb.set)
        self.tree_arbres.bind("<<TreeviewSelect>>", self._on_select_arbre)
        self.tree_arbres.bind("<Double-1>",
                              lambda e: self.action_rename_arbre())
        # Menu contextuel : clic droit sélectionne d'abord la ligne sous
        # le curseur (pratique Windows/Linux), puis affiche le menu.
        self._tree_arbres_ctx_menu = tk.Menu(self, tearoff=0)
        self._tree_arbres_ctx_menu.add_command(
            label="Renommer…", command=self.action_rename_arbre)
        self._tree_arbres_ctx_menu.add_command(
            label="Dupliquer", command=self.action_dup_arbre)
        self._tree_arbres_ctx_menu.add_separator()
        self._tree_arbres_ctx_menu.add_command(
            label="Supprimer…", command=self.action_del_arbre)
        # `<FocusOut>` ferme le menu si l'utilisateur clique en dehors
        # (sur Linux/X11, `tk_popup` ne pose pas de grab automatique →
        # sans ce binding, le menu reste affiché). Le menu doit pouvoir
        # prendre le focus pour que l'événement soit déclenché : Tk le
        # fait quand le menu est posté.
        self._tree_arbres_ctx_menu.bind(
            "<FocusOut>",
            lambda e: self._tree_arbres_ctx_menu.unpost())
        self.tree_arbres.bind("<Button-3>", self._on_tree_arbres_right_click)

        # Footer "X/N arbres complets" — vue macro de l'avancement.
        self.lbl_etat_footer = ttk.Label(
            frame, text="", style="Side.TLabel",
            font=("Helvetica", 9, "italic"))
        self.lbl_etat_footer.pack(anchor="w", pady=(6, 0))

        btns = ttk.Frame(frame, style="Side.TFrame")
        btns.pack(fill="x", pady=(10, 0))
        mb_add = ttk.Menubutton(btns, text="＋ Ajouter",
                                style="Accent.TMenubutton", direction="below")
        add_menu = tk.Menu(mb_add, tearoff=0)
        add_menu.add_command(label="Arbre vierge",
                             accelerator="Ctrl+T",
                             command=self.action_add_arbre)
        add_menu.add_command(
            label="Hériter du précédent (essence, port, mèche…)",
            command=self.action_add_arbre_inherit)
        mb_add["menu"] = add_menu
        mb_add.pack(side="left")
        Tooltip(mb_add, "Ajouter un arbre. « Arbre vierge » (Ctrl+T) ou "
                        "« Hériter du précédent » pour reprendre essence, "
                        "port et mèche d'un alignement.")
        ttk.Button(btns, text="Dupliquer", style="Ghost.TButton",
                   command=self.action_dup_arbre
                   ).pack(side="left", padx=(6, 0))
        ttk.Button(btns, text="Supprimer", style="Ghost.TButton",
                   command=self.action_del_arbre
                   ).pack(side="left", padx=(6, 0))

    def _build_center(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent, style="Panel.TFrame", padding=12)
        frame.grid(row=0, column=1, sticky="nsew", padx=(0, 12))
        nb = ttk.Notebook(frame)
        nb.pack(fill="both", expand=True)

        # Onglet Identification — extrait dans son propre pane (cf.
        # pane_identification.py). Le pane possède ses 10 StringVars,
        # la règle de cohérence Ø ↔ Rayon et la synchro UI ↔ modèle.
        self.pane_id = IdentificationPane(nb, host=self)
        nb.add(self.pane_id, text="Identification")

        # Onglet Sondages — extrait dans son propre pane (cf.
        # pane_sondages.py).
        self.pane_s = SondagesPane(nb, host=self)
        nb.add(self.pane_s, text="Sondages")

        # Onglet Dégradations externes — extrait dans son propre pane
        # (cf. pane_degradations.py).
        self.pane_de = DegradationsPane(nb, host=self)
        nb.add(self.pane_de, text="Dégrad. externes")

        # Onglet Contreforts — extrait dans son propre pane (cf.
        # pane_contreforts.py) : le pane possède sa table, ses boutons,
        # son refresh et ses actions add/edit/del.
        self.pane_cf = ContrefortsPane(nb, host=self)
        nb.add(self.pane_cf, text="Contreforts")

        # Onglet Diagnostic — extrait dans son propre pane (cf.
        # pane_diagnostic.py). Le pane possède son sous-canvas
        # scrollable, ses 5 boutons d'export, son résumé, la checkbox
        # show_sondages et le tableau PRBS.
        self.pane_diag = DiagnosticPane(nb, host=self)
        nb.add(self.pane_diag, text="Diagnostic")

    def _build_right(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent, style="Panel.TFrame", padding=10)
        frame.grid(row=0, column=2, sticky="nsew")
        self.section = SectionCanvas(frame, host=self,
                                      width=550, height=550)
        self.section.pack(fill="both", expand=True)
        # Contrôle d'affichage : cohabite avec le dessin (visible quel
        # que soit l'onglet actif, plutôt que caché dans l'onglet
        # Diagnostic).
        self.var_show_sondages = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            frame,
            text="Afficher l'emplacement des sondages sur le dessin",
            variable=self.var_show_sondages,
            command=lambda: self.section.set_show_sondages(
                self.var_show_sondages.get()),
            style="TCheckbutton",
        ).pack(anchor="w", pady=(6, 0))
        # Indice de découvrabilité : le canevas est interactif (clic sur
        # un élément = édition, clic sur une direction vide = ajout).
        # Rien ne le signalait a priori — d'où ce rappel discret.
        ttk.Label(
            frame,
            text="ⓘ Cliquez un élément du dessin pour le modifier, "
                 "ou une direction libre pour ajouter un sondage.",
            style="Muted.TLabel", wraplength=440, justify="left",
        ).pack(anchor="w", pady=(2, 0))

    def _build_statusbar(self) -> None:
        """Barre d'état en bas de fenêtre : message + boutons d'ouverture
        du dernier export. Remplace les `messagebox` de succès d'export
        (un « OK » à cliquer à chaque fois) par un retour non-modal."""
        bar = ttk.Frame(self, style="Side.TFrame")
        bar.pack(side="bottom", fill="x")
        self.lbl_status = ttk.Label(bar, text="Prêt.", style="Side.TLabel",
                                    font=("Helvetica", 9))
        self.lbl_status.pack(side="left", padx=12, pady=3)
        self._btn_open_folder = ttk.Button(
            bar, text="Ouvrir le dossier", style="Ghost.TButton",
            command=self._open_last_export_folder, state="disabled")
        self._btn_open_folder.pack(side="right", padx=(0, 10), pady=2)
        self._btn_open_file = ttk.Button(
            bar, text="Ouvrir le fichier", style="Ghost.TButton",
            command=self._open_last_export_file, state="disabled")
        self._btn_open_file.pack(side="right", padx=(0, 4), pady=2)

    def set_status(self, text: str) -> None:
        """Met à jour le message de la barre d'état (no-op si la barre
        n'est pas encore construite — cas tests sans UI complète)."""
        if hasattr(self, "lbl_status"):
            self.lbl_status.configure(text=text)

    def notify_export(self, path: str, label: str) -> None:
        """Feedback non-modal après un export réussi (appelé par
        `app_exports`). Met à jour la barre d'état et active les boutons
        d'ouverture du fichier / dossier."""
        p = Path(path)
        self._last_export_path = p
        self.set_status(f"✓ {label} — {p.name}")
        self._btn_open_file.configure(state="normal")
        self._btn_open_folder.configure(state="normal")

    def _open_last_export_file(self) -> None:
        if self._last_export_path:
            self._open_in_system(self._last_export_path)

    def _open_last_export_folder(self) -> None:
        if self._last_export_path:
            self._open_in_system(self._last_export_path.parent)

    def _open_in_system(self, path: Path) -> None:
        """Ouvre un fichier ou dossier avec l'application système par
        défaut (Explorateur, Finder, gestionnaire de fichiers Linux)."""
        import subprocess
        import sys
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", str(path)], check=False)
            else:
                subprocess.run(["xdg-open", str(path)], check=False)
        except Exception as e:
            log.exception("Échec ouverture %s", path)
            messagebox.showerror(
                "Erreur", f"Impossible d'ouvrir :\n{path}\n\n{e}")

    # --- Dirty flag + fermeture ----------------------------------------

    def _mark_dirty(self) -> None:
        if not self._dirty:
            self._dirty = True
            self._update_title()

    def _update_title(self) -> None:
        name = self.current_file.name if self.current_file else "Sans titre"
        dirty = " •" if self._dirty else ""
        self.title(f"Pénétromètre — {name}{dirty}")

    def _on_close(self) -> None:
        if self._dirty:
            if not messagebox.askyesno(
                    "Quitter",
                    "Des modifications n'ont pas été enregistrées.\n"
                    "Quitter quand même ?"):
                return
        # Fermeture normale (même en abandonnant des modifications) : on
        # efface l'autosave. Sa survivance ne doit signaler QUE le crash.
        clear_recovery(_RECOVERY_PATH)
        self.destroy()

    # --- Autosave anti-crash + récupération ----------------------------

    def _schedule_autosave(self) -> None:
        """(Re)programme le prochain tick d'autosave. Idempotent : annule
        un tick en attente avant d'en reprogrammer un."""
        if self._autosave_after_id is not None:
            try:
                self.after_cancel(self._autosave_after_id)
            except (ValueError, tk.TclError):
                pass
        self._autosave_after_id = self.after(
            _AUTOSAVE_INTERVAL_MS, self._autosave_tick)

    def _autosave_tick(self) -> None:
        """Écrit l'autosave si la mission a des modifications non
        enregistrées, puis se reprogramme. Tout échec est journalisé sans
        interrompre l'app (l'autosave est un filet, pas un point dur)."""
        try:
            if self._dirty:
                save_recovery(
                    self.chantier,
                    str(self.current_file) if self.current_file else None,
                    _RECOVERY_PATH)
                log.info("Autosave écrit (%s)", _RECOVERY_PATH.name)
        except Exception:
            log.exception("Échec de l'autosave")
        finally:
            self._schedule_autosave()

    def _check_recovery_on_startup(self) -> None:
        """Au démarrage : si un autosave subsiste (crash précédent avec
        travail non enregistré), propose de le récupérer."""
        if not _RECOVERY_PATH.exists():
            return
        try:
            chantier, original, saved_at = load_recovery(_RECOVERY_PATH)
        except Exception:
            log.exception("Autosave illisible — ignoré")
            clear_recovery(_RECOVERY_PATH)
            return
        details = (f"Fichier : {original}" if original
                   else "Mission jamais enregistrée.")
        when = f" du {saved_at}" if saved_at else ""
        if messagebox.askyesno(
                "Récupération",
                "Une session non enregistrée a été retrouvée "
                f"(sauvegarde automatique{when}).\n\n{details}\n\n"
                "La récupérer ?"):
            self._restore_recovery(chantier, original)
            # On laisse l'autosave en place : il reflète l'état restauré
            # (toujours non enregistré). Il sera rafraîchi au prochain tick
            # et effacé au 1er enregistrement.
        else:
            clear_recovery(_RECOVERY_PATH)

    def _restore_recovery(self, chantier: Chantier,
                          original: Optional[str]) -> None:
        """Recharge l'UI complète depuis un chantier récupéré. Marque la
        mission comme modifiée (le travail n'est pas encore réenregistré)
        et pointe sur le fichier d'origine s'il existe encore (pour que
        Ctrl+S réécrive au bon endroit)."""
        self._undo_stack.clear()
        self.chantier = chantier
        if not self.chantier.arbres:
            self.chantier.arbres.append(Arbre(numero_arbre="1"))
        self.current_idx = 0
        if original and Path(original).exists():
            self.current_file = Path(original)
        else:
            self.current_file = None
        with self._suspend_sync_block():
            self.var_ch_nom.set(self.chantier.nom)
            self.var_ch_adr.set(self.chantier.adresse)
            self.var_ch_ope.set(self.chantier.operateur)
            self.var_ch_date.set(self.chantier.date_releve)
        self.var_filter.set("")  # nouvelle mission → filtre remis à zéro
        self._refresh_tree_arbres()
        self._load_arbre_to_ui()
        self._dirty = True
        self._update_title()
        self.set_status("Session récupérée — pensez à l'enregistrer.")

    # --- Undo / redo --------------------------------------------------

    def push_undo(self) -> None:
        """Sauvegarde l'état courant avant une mutation discrète."""
        self._undo_stack.push(chantier_to_dict(self.chantier))
        self._mark_dirty()

    def _perform_undo(self) -> None:
        snapshot = self._undo_stack.undo(chantier_to_dict(self.chantier))
        if snapshot is None:
            return
        self._restore_snapshot(snapshot)

    def _perform_redo(self) -> None:
        snapshot = self._undo_stack.redo()
        if snapshot is None:
            return
        self._restore_snapshot(snapshot)

    def _restore_snapshot(self, snapshot: dict) -> None:
        self.chantier = chantier_from_dict(snapshot)
        if not self.chantier.arbres:
            self.chantier.arbres.append(Arbre(numero_arbre="1"))
        self.current_idx = min(self.current_idx,
                               len(self.chantier.arbres) - 1)
        with self._suspend_sync_block():
            self.var_ch_nom.set(self.chantier.nom)
            self.var_ch_adr.set(self.chantier.adresse)
            self.var_ch_ope.set(self.chantier.operateur)
            self.var_ch_date.set(self.chantier.date_releve)
        self._refresh_tree_arbres()
        self._load_arbre_to_ui()

    # --- Synchro -----------------------------------------------------

    def _current_arbre(self) -> Optional[Arbre]:
        if not self.chantier.arbres:
            return None
        return self.chantier.arbres[self.current_idx]

    @contextmanager
    def _suspend_sync_block(self) -> Iterator[None]:
        """Suspend la synchro UI → modèle pendant un bloc d'écriture
        dans les StringVar. Garantit la remise à l'état précédent même
        si une exception survient à l'intérieur (un set/reset manuel
        laissait l'UI gelée silencieusement en cas d'erreur)."""
        prev = self._suspend_sync
        self._suspend_sync = True
        try:
            yield
        finally:
            self._suspend_sync = prev

    def _meta_focus_in(self) -> None:
        self._meta_snapshot = (
            f"{self.var_ch_nom.get()}|{self.var_ch_adr.get()}|"
            f"{self.var_ch_ope.get()}|{self.var_ch_date.get()}")

    def _meta_focus_out(self) -> None:
        current = (
            f"{self.var_ch_nom.get()}|{self.var_ch_adr.get()}|"
            f"{self.var_ch_ope.get()}|{self.var_ch_date.get()}")
        if self._meta_snapshot is not None and current != self._meta_snapshot:
            self.push_undo()
        self._meta_snapshot = None

    def _sync_chantier_meta(self) -> None:
        if self._suspend_sync:
            return
        self.chantier.nom = self.var_ch_nom.get()
        self.chantier.adresse = self.var_ch_adr.get()
        self.chantier.operateur = self.var_ch_ope.get()
        self.chantier.date_releve = self.var_ch_date.get()
        self._mark_dirty()

    def on_identification_changed(self, *, rayon_adjusted: bool) -> None:
        """Callback appelé par `IdentificationPane` quand l'utilisateur
        modifie un champ."""
        self._mark_dirty()
        if rayon_adjusted:
            self._refresh_sondages_table()
            self._refresh_degradations_table()
            self._refresh_contreforts_table()
        self._debounced_redraw()
        a = self._current_arbre()
        if not a:
            return
        sel = self.tree_arbres.selection()
        if sel:
            label = f"n° {a.numero_arbre}" if a.numero_arbre else "(sans n°)"
            glyph, tag = self._arbre_etat(a)
            self.tree_arbres.item(sel[0], text=label,
                                  values=(a.essence, glyph),
                                  tags=(tag,))
            # Recalcule le footer (le passage d'un arbre orange→vert
            # change le compteur global).
            n_ok = sum(1 for x in self.chantier.arbres
                       if self._arbre_etat(x)[1] == "etat_ok")
            self._update_etat_footer(n_ok, len(self.chantier.arbres))

    def _load_arbre_to_ui(self) -> None:
        """Recharge l'UI complète depuis l'arbre courant : identification
        + tables Sondages/Dégradations/Contreforts + redraw du dessin."""
        self.pane_id.load_from_arbre()
        self._refresh_sondages_table()
        self._refresh_degradations_table()
        self._refresh_contreforts_table()
        self._debounced_redraw()

    def _debounced_redraw(self) -> None:
        if self._redraw_id is not None:
            self.after_cancel(self._redraw_id)
        self._redraw_id = self.after(80, self._redraw_all)

    def _redraw_all(self) -> None:
        a = self._current_arbre()
        self.section.set_arbre(a)
        self._refresh_diag()
        # Réactualise la pastille d'état de l'arbre courant : les
        # ajouts/suppressions de sondages, dégradations ou contreforts
        # passent par `_debounced_redraw` → `_redraw_all`, mais ne
        # touchent pas la liste d'arbres autrement. Sans ce refresh,
        # passer de 0 à 2 sondages laisserait la pastille rouge.
        self._refresh_current_arbre_etat()

    def _refresh_current_arbre_etat(self) -> None:
        """Met à jour la pastille d'état + le footer après une mutation
        sur l'arbre courant. N'agit que sur la ligne sélectionnée pour
        éviter de reconstruire toute la tree (préserve la sélection et
        la position de scroll)."""
        a = self._current_arbre()
        if a is None:
            return
        sel = self.tree_arbres.selection()
        if sel:
            label = f"n° {a.numero_arbre}" if a.numero_arbre else "(sans n°)"
            glyph, tag = self._arbre_etat(a)
            self.tree_arbres.item(sel[0], text=label,
                                  values=(a.essence, glyph),
                                  tags=(tag,))
        n_ok = sum(1 for x in self.chantier.arbres
                   if self._arbre_etat(x)[1] == "etat_ok")
        self._update_etat_footer(n_ok, len(self.chantier.arbres))

    # --- Liste d'arbres ---------------------------------------------

    def _arbre_matches_filter(self, a: Arbre) -> bool:
        """Vrai si l'arbre concorde avec le filtre courant (sous-chaîne,
        insensible à la casse, sur le n° OU l'essence). Filtre vide =
        tout passe. Tolérant si appelé avant la construction du champ."""
        q = getattr(self, "var_filter", None)
        if q is None:
            return True
        needle = q.get().strip().lower()
        if not needle:
            return True
        return (needle in a.numero_arbre.lower()
                or needle in a.essence.lower())

    def _refresh_tree_arbres(self) -> None:
        self.tree_arbres.delete(*self.tree_arbres.get_children())
        # Le compteur footer reste sur TOUTE la mission (vue macro), pas
        # sur la sous-liste filtrée.
        n_ok = sum(1 for a in self.chantier.arbres
                   if self._arbre_etat(a)[1] == "etat_ok")
        for i, a in enumerate(self.chantier.arbres):
            if not self._arbre_matches_filter(a):
                continue
            # Affichage compact : "n°X" (l'essence est dans la 2e colonne)
            label = f"n° {a.numero_arbre}" if a.numero_arbre else "(sans n°)"
            glyph, tag = self._arbre_etat(a)
            # iid = position réelle dans chantier.arbres (cf.
            # _on_select_arbre) — préservée même quand des lignes sont
            # masquées par le filtre.
            self.tree_arbres.insert("", "end", iid=f"a{i}",
                                    text=label,
                                    values=(a.essence, glyph),
                                    tags=(tag,))
        self._update_etat_footer(n_ok, len(self.chantier.arbres))
        # Re-sélectionne l'arbre courant s'il est visible dans la liste
        # filtrée (sinon on laisse la sélection vide : le panneau de droite
        # continue d'afficher l'arbre courant).
        target = f"a{self.current_idx}"
        if target in self.tree_arbres.get_children():
            self.tree_arbres.selection_set(target)
            self.tree_arbres.focus(target)

    def _update_etat_footer(self, n_ok: int, n_total: int) -> None:
        """Met à jour le footer « X/N arbres complets » sous la liste."""
        if not hasattr(self, "lbl_etat_footer"):
            return
        self.lbl_etat_footer.configure(
            text=f"● {n_ok}/{n_total} arbres avec diagnostic fiable")

    @staticmethod
    def _arbre_etat(a: Arbre) -> tuple[str, str]:
        """Renvoie `(glyphe, tag)` pour la colonne État d'un arbre.

        Le glyphe est un caractère universellement disponible (●),
        c'est le tag — appliqué à toute la ligne via `tag_configure` —
        qui colorise (rouge/orange/vert) le foreground et permet la
        distinction visuelle. On évite les emojis couleur (🔴🟠🟢)
        qui s'affichent souvent en monochrome dans ttk.Treeview selon
        la police système : trois pastilles devenaient indistinguables.

        Seuil de complétude aligné sur la règle métier : un diagnostic
        global n'est publié (t/R moyen + classe) qu'à partir de 3
        directions sondées (cf. `diagnostic.DiagnosticSnapshot`). La
        pastille verte signale donc exactement les arbres dont le
        diagnostic est fiable et exportable.

        Règles :
          - `etat_vide`    : pas de rayon OU pas de sondage
          - `etat_partiel` : 1 ou 2 sondages (diagnostic non fiable)
          - `etat_ok`      : 3 sondages ou plus (diagnostic fiable)
        """
        if a.rayon_tronc_cm <= 0 or not a.sondages:
            return "●", "etat_vide"
        if len(a.sondages) < 3:
            return "●", "etat_partiel"
        return "●", "etat_ok"

    def _on_tree_arbres_right_click(self, event: "tk.Event[tk.Misc]") -> None:
        """Sélectionne la ligne sous le curseur puis affiche le menu
        contextuel. Sélectionner avant l'action garantit que les
        commandes (Renommer/Dupliquer/Supprimer) agissent sur l'arbre
        sous le clic, pas sur l'arbre précédemment sélectionné.

        NB : pas de `grab_release()` après `tk_popup()` — Tk gère le
        grab tout seul, l'appel immédiat l'annulait et empêchait le
        menu de se fermer au clic externe (cf. binding `<FocusOut>`
        posé à la construction du menu)."""
        row_id = self.tree_arbres.identify_row(event.y)
        if not row_id:
            return
        self.tree_arbres.selection_set(row_id)
        self.tree_arbres.focus(row_id)
        self._tree_arbres_ctx_menu.tk_popup(event.x_root, event.y_root)

    def _on_select_arbre(self, event: Optional["tk.Event[tk.Misc]"] = None) -> None:
        sel = self.tree_arbres.selection()
        if not sel:
            return
        idx = int(sel[0][1:])
        if idx == self.current_idx:
            return
        self.current_idx = idx
        self._load_arbre_to_ui()

    def _next_arbre_numero(self) -> str:
        """Prochain n° d'arbre : max numérique existant + 1, borné au
        moins au nombre d'arbres + 1 (cas de numéros non numériques)."""
        max_num = 0
        for arb in self.chantier.arbres:
            try:
                max_num = max(max_num, int(arb.numero_arbre))
            except (ValueError, TypeError):
                pass
        return str(max(max_num + 1, len(self.chantier.arbres) + 1))

    def action_add_arbre(self) -> None:
        """Ajoute un arbre vierge (tous champs par défaut)."""
        self.push_undo()
        self.chantier.arbres.append(
            Arbre(numero_arbre=self._next_arbre_numero()))
        self.current_idx = len(self.chantier.arbres) - 1
        self._clear_filter_if_set()
        self._refresh_tree_arbres()
        self._load_arbre_to_ui()

    def _clear_filter_if_set(self) -> None:
        """Vide le filtre de la liste s'il est actif — pour qu'un arbre
        nouvellement créé reste visible même s'il ne concorde pas avec le
        filtre courant. No-op (donc pas de refresh parasite) si vide."""
        if getattr(self, "var_filter", None) is not None and self.var_filter.get():
            self.var_filter.set("")

    def action_add_arbre_inherit(self) -> None:
        """Ajoute un arbre héritant des champs d'« identité » de l'arbre
        courant (essence, port, longueur de mèche, épaisseur d'écorce,
        hauteur de sondage) mais SANS ses sondages / dégradations /
        contreforts ni sa géométrie mesurée (rayon, diamètre, hauteur de
        l'arbre restent à mesurer). Pensé pour les alignements d'arbres
        identiques (30 platanes de même essence et même port) : on ne
        re-saisit pas le protocole commun à chaque arbre."""
        cur = self._current_arbre()
        if cur is None:
            return self.action_add_arbre()
        self.push_undo()
        new = Arbre(
            numero_arbre=self._next_arbre_numero(),
            essence=cur.essence,
            port_arbre=cur.port_arbre,
            meche_cm=cur.meche_cm,
            epaisseur_ecorce_cm=cur.epaisseur_ecorce_cm,
            hauteur_sondage_cm=cur.hauteur_sondage_cm,
        )
        self.chantier.arbres.append(new)
        self.current_idx = len(self.chantier.arbres) - 1
        self._clear_filter_if_set()
        self._refresh_tree_arbres()
        self._load_arbre_to_ui()

    def _select_arbre_relative(self, delta: int) -> None:
        """Navigation clavier entre arbres (Ctrl+PgDown / Ctrl+PgUp) :
        passe à l'arbre suivant/précédent **parmi les arbres visibles**
        (le filtre est respecté), sans boucler."""
        visible = [i for i, a in enumerate(self.chantier.arbres)
                   if self._arbre_matches_filter(a)]
        if len(visible) <= 1:
            return
        if self.current_idx in visible:
            pos = visible.index(self.current_idx)
            new_idx = visible[min(len(visible) - 1, max(0, pos + delta))]
        else:
            # Arbre courant masqué par le filtre : on entre dans la liste
            # visible par son 1er (avance) ou son dernier (recul) élément.
            new_idx = visible[0] if delta > 0 else visible[-1]
        if new_idx == self.current_idx:
            return
        # Donne le focus clavier à la liste AVANT de changer d'arbre :
        # déclenche le <FocusOut> d'une éventuelle case de grille en cours
        # d'édition (commit undo + normalisation) sur l'arbre encore
        # courant, avant de basculer.
        self.tree_arbres.focus_set()
        self.current_idx = new_idx
        target = f"a{new_idx}"
        if target in self.tree_arbres.get_children():
            self.tree_arbres.selection_set(target)
            self.tree_arbres.focus(target)
            self.tree_arbres.see(target)
        self._load_arbre_to_ui()

    def action_next_arbre(self) -> None:
        self._select_arbre_relative(1)

    def action_prev_arbre(self) -> None:
        self._select_arbre_relative(-1)

    def action_dup_arbre(self) -> None:
        a = self._current_arbre()
        if not a:
            return
        self.push_undo()
        new = copy.deepcopy(a)
        # Nouveau numéro = numéro existant + suffixe 'bis', 'ter', etc.
        suffixes = ["", " bis", " ter", " quater"]
        base = a.numero_arbre
        for suf in suffixes[1:]:
            candidate = base + suf
            if not any(x.numero_arbre == candidate for x in self.chantier.arbres):
                new.numero_arbre = candidate
                break
        else:
            new.numero_arbre = base + " (copie)"
        self.chantier.arbres.insert(self.current_idx + 1, new)
        self.current_idx += 1
        self._clear_filter_if_set()
        self._refresh_tree_arbres()
        self._load_arbre_to_ui()

    def action_del_arbre(self) -> None:
        if len(self.chantier.arbres) <= 1:
            messagebox.showinfo("Information",
                                "La mission doit contenir au moins un arbre.")
            return
        a = self._current_arbre()
        if a is None:
            return
        if not messagebox.askyesno("Supprimer",
                                   f"Supprimer définitivement « {a.display_name} » ?"):
            return
        self.push_undo()
        del self.chantier.arbres[self.current_idx]
        self.current_idx = max(0, self.current_idx - 1)
        self._refresh_tree_arbres()
        self._load_arbre_to_ui()

    def action_rename_arbre(self) -> None:
        a = self._current_arbre()
        if not a:
            return
        # Boucle de retry : si la saisie ne contient pas de chiffre,
        # on ré-ouvre le dialogue pré-rempli avec la valeur invalide
        # plutôt que de refermer et perdre la saisie de l'utilisateur.
        # Règle alignée sur `_revert_num_if_invalid` du pane Identification :
        # au moins un chiffre, lettres autorisées (« 12 bis », « 3 ter »).
        proposed = a.numero_arbre
        while True:
            new = ask_string(
                self, "Renuméroter l'arbre",
                "Nouveau n° d'arbre :",
                initial=proposed,
                info="Doit contenir au moins un chiffre "
                     "(ex. « 1 », « 42 », « 12 bis »).")
            if new is None:
                return
            new = new.strip()
            if not new or new == a.numero_arbre:
                return
            if not any(c.isdigit() for c in new):
                messagebox.showwarning(
                    "Numéro invalide",
                    "Le numéro d'arbre doit contenir au moins un "
                    "chiffre.\n\nExemples valides : « 1 », « 42 », "
                    "« 12 bis ».",
                    parent=self)
                proposed = new
                continue
            break
        # Avertissement non bloquant si le numéro est déjà utilisé par
        # un autre arbre de la mission. L'utilisateur peut quand même
        # confirmer (cas d'un renommage en chaîne, ou d'un doublon
        # volontaire pour un arbre jumeau identifié sur le terrain).
        already_used = any(x is not a and x.numero_arbre == new
                           for x in self.chantier.arbres)
        if already_used:
            confirmer = messagebox.askyesno(
                "Numéro déjà utilisé",
                f"Un autre arbre porte déjà le n° « {new} ».\n\n"
                "Continuer quand même ?")
            if not confirmer:
                return
        self.push_undo()
        a.numero_arbre = new
        self.pane_id.load_from_arbre()
        self._refresh_tree_arbres()

    # --- Sondages ---------------------------------------------------
    # Le refresh et les actions vivent dans SondagesPane
    # (pane_sondages.py). Thin wrapper pour les sites qui rafraîchissent
    # en cascade.
    def _refresh_sondages_table(self) -> None:
        if self.pane_s is not None:
            self.pane_s.refresh()

    def on_sondages_changed(self) -> None:
        """Notifié par `SondagesPane` après une mutation live (saisie
        directe dans la grille). Marque dirty + redessine (debouncé) — ce
        qui rafraîchit aussi le diagnostic et la pastille d'état. On ne
        rappelle PAS `_refresh_sondages_table` ici : la grille est déjà à
        jour (c'est elle qui a muté), inutile de lutter contre la frappe."""
        self._mark_dirty()
        self._debounced_redraw()

    def capture_undo_snapshot(self) -> dict:
        """Renvoie un snapshot de l'état courant sans l'empiler. Utilisé
        par les éditions live (grille de sondages) : on capture l'état
        AVANT édition au focus-in, on ne l'empile (`push_undo_snapshot`)
        qu'au focus-out si la valeur a réellement changé."""
        return chantier_to_dict(self.chantier)

    def push_undo_snapshot(self, snapshot: dict) -> None:
        """Empile un snapshot pré-édition capturé par `capture_undo_snapshot`
        (cf. édition live de la grille de sondages)."""
        self._undo_stack.push(snapshot)
        self._mark_dirty()

    # ---- Dégradations externes -------------------------------------
    # Le refresh et les actions vivent dans DegradationsPane (cf.
    # pane_degradations.py). Thin wrapper pour les sites qui
    # rafraîchissent en cascade.
    def _refresh_degradations_table(self) -> None:
        if self.pane_de is not None:
            self.pane_de.refresh()

    # --- Contreforts ---
    # Le refresh et les actions vivent maintenant dans ContrefortsPane
    # (cf. pane_contreforts.py). `_refresh_contreforts_table` reste
    # comme thin wrapper pour les sites qui rafraîchissent en cascade
    # (changement de rayon, chargement d'arbre).
    def _refresh_contreforts_table(self) -> None:
        if self.pane_cf is not None:
            self.pane_cf.refresh()

    def _refresh_diag(self) -> None:
        if self.pane_diag is not None:
            self.pane_diag.refresh()

    # --- Callbacks d'édition depuis le canvas interactif --------------
    # Le `SectionCanvas` les appelle au clic sur une pastille sondage,
    # un arc de dégradation ou un contrefort. Chacun ouvre le dialogue
    # idoine et, si l'utilisateur valide, pousse l'undo + rafraîchit la
    # table correspondante + redessine.

    def open_add_sondage(self, grade: int) -> None:
        """Ajoute un sondage à un grade donné (clic sur une direction
        vide du dessin). Pré-rempli avec bois sain = rayon (cavité
        nulle), comme le bouton « Ajouter sondage » de l'onglet."""
        a = self._current_arbre()
        if not a:
            return
        s = Sondage(numero=len(a.sondages) + 1, grade=grade,
                    bois_sain_cm=a.rayon_tronc_cm, bois_altere_cm=0.0)
        if edit_sondage(self, a, s):
            self.push_undo()
            a.sondages.append(s)
            a.renumeroter_sondages()
            self._refresh_sondages_table()
            self._debounced_redraw()

    def open_edit_sondage(self, s: Sondage) -> None:
        a = self._current_arbre()
        if not a:
            return
        if edit_sondage(self, a, s):
            self.push_undo()
            self._refresh_sondages_table()
            self._debounced_redraw()

    def open_edit_degradation(self, d: DegradationExterne) -> None:
        a = self._current_arbre()
        if not a:
            return
        if edit_degradation(self, a, d):
            self.push_undo()
            self._refresh_degradations_table()
            self._debounced_redraw()

    def open_edit_contrefort(self, c: Contrefort) -> None:
        a = self._current_arbre()
        if not a:
            return
        if edit_contrefort(self, a, c):
            self.push_undo()
            self._refresh_contreforts_table()
            self._debounced_redraw()

    # --- Fichier ----------------------------------------------------

    def action_new(self) -> None:
        if self._dirty:
            if not messagebox.askyesno(
                    "Nouvelle mission",
                    "Des modifications n'ont pas été enregistrées.\n"
                    "Continuer quand même ?"):
                return
        self._undo_stack.clear()
        self._dirty = False
        clear_recovery(_RECOVERY_PATH)
        self.chantier = Chantier()
        self.chantier.arbres.append(Arbre(numero_arbre="1"))
        self.current_idx = 0
        self.current_file = None
        with self._suspend_sync_block():
            self.var_ch_nom.set(self.chantier.nom)
            self.var_ch_adr.set("")
            self.var_ch_ope.set("")
            self.var_ch_date.set(self.chantier.date_releve)
        self.var_filter.set("")  # nouvelle mission → filtre remis à zéro
        self._refresh_tree_arbres()
        self._load_arbre_to_ui()
        self._update_title()

    def action_open(self) -> None:
        if self._dirty:
            if not messagebox.askyesno(
                    "Ouvrir",
                    "Des modifications n'ont pas été enregistrées.\n"
                    "Continuer quand même ?"):
                return
        p = filedialog.askopenfilename(
            title="Ouvrir une mission",
            filetypes=[("Mission Pénétromètre", "*.json"),
                       ("Tous", "*.*")])
        if not p:
            return
        self._open_path(p)

    def _open_path(self, p: str) -> None:
        """Ouvre un fichier de mission par son chemin (factorise
        `action_open` et `action_open_recent`). Pousse le chemin dans
        l'historique des récents même en cas de succès."""
        try:
            self._undo_stack.clear()
            self._dirty = False
            clear_recovery(_RECOVERY_PATH)
            self.chantier = load_chantier(p)
            if not self.chantier.arbres:
                self.chantier.arbres.append(Arbre())
            self.current_idx = 0
            self.current_file = Path(p)
            with self._suspend_sync_block():
                self.var_ch_nom.set(self.chantier.nom)
                self.var_ch_adr.set(self.chantier.adresse)
                self.var_ch_ope.set(self.chantier.operateur)
                self.var_ch_date.set(self.chantier.date_releve)
            self.var_filter.set("")  # mission ouverte → filtre remis à zéro
            self._refresh_tree_arbres()
            self._load_arbre_to_ui()
            self._update_title()
            self._push_recent_file(p)
        except FileNotFoundError:
            messagebox.showerror(
                "Fichier introuvable",
                f"Le fichier suivant n'existe plus :\n{p}\n\n"
                "Il a été retiré de la liste des fichiers récents.")
            self._remove_recent_file(p)
        except Exception as e:
            log.exception("Échec ouverture mission")
            messagebox.showerror("Erreur d'ouverture", str(e))

    def action_open_recent(self, path: str) -> None:
        """Ouvre un fichier récent (appelé par le sous-menu Récents)."""
        if self._dirty:
            if not messagebox.askyesno(
                    "Ouvrir",
                    "Des modifications n'ont pas été enregistrées.\n"
                    "Continuer quand même ?"):
                return
        self._open_path(path)

    def get_recent_files(self) -> list[str]:
        """Lecture pure pour `refresh_recent_menu`."""
        return list(self._recent_files)

    def _load_recent_files(self) -> list[str]:
        """Charge la liste depuis `~/.penetrometre/recent.json`.
        Tolérant : tout problème (fichier absent, JSON invalide,
        permission) renvoie liste vide sans interrompre le démarrage."""
        try:
            if _RECENT_FILES_PATH.exists():
                with open(_RECENT_FILES_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    return [str(x) for x in data
                            if isinstance(x, str)][:_RECENT_FILES_MAX]
        except Exception:
            log.exception("Lecture recent.json")
        return []

    def _save_recent_files(self) -> None:
        try:
            _RECENT_FILES_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(_RECENT_FILES_PATH, "w", encoding="utf-8") as f:
                json.dump(self._recent_files, f, ensure_ascii=False, indent=2)
        except Exception:
            log.exception("Écriture recent.json")

    def _push_recent_file(self, path: str) -> None:
        """Pousse un chemin en tête de l'historique (déduplication).
        Met à jour le sous-menu et persiste."""
        path = str(Path(path).resolve())
        self._recent_files = [path] + [p for p in self._recent_files
                                        if p != path]
        self._recent_files = self._recent_files[:_RECENT_FILES_MAX]
        self._save_recent_files()
        refresh_recent_menu(self)  # type: ignore[arg-type]

    def _remove_recent_file(self, path: str) -> None:
        target = str(Path(path).resolve()) if Path(path).exists() else path
        self._recent_files = [p for p in self._recent_files
                              if p != target and p != path]
        self._save_recent_files()
        refresh_recent_menu(self)  # type: ignore[arg-type]

    def action_save(self) -> None:
        if not self.current_file:
            return self.action_save_as()
        try:
            save_chantier(self.chantier, self.current_file)
            self._dirty = False
            self._update_title()
            self._push_recent_file(str(self.current_file))
            # Le fichier réel est à jour → l'autosave n'a plus de raison
            # d'être ; on l'efface pour ne pas proposer une reprise inutile.
            clear_recovery(_RECOVERY_PATH)
            self.set_status(f"✓ Enregistré — {self.current_file.name}")
        except Exception as e:
            log.exception("Échec enregistrement mission")
            messagebox.showerror("Erreur", str(e))

    def action_save_as(self) -> None:
        p = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("Mission Pénétromètre", "*.json")])
        if not p:
            return
        self.current_file = Path(p)
        self.action_save()

    def action_export_png(self) -> None:
        app_exports.export_png(self, self._current_arbre(),
                                self.var_show_sondages.get())

    def action_export_pdf_arbre(self) -> None:
        app_exports.export_pdf_arbre(self, self._current_arbre(),
                                      self.chantier)

    def action_export_pdf_mission(self) -> None:
        app_exports.export_pdf_mission(self, self.chantier)

    def action_export_csv(self) -> None:
        app_exports.export_csv_mission(self, self.chantier)

    def action_export_synthesis_xlsx(self) -> None:
        app_exports.export_synthesis_xlsx_mission(self, self.chantier)

    def action_export_synthesis_csv(self) -> None:
        app_exports.export_synthesis_csv_mission(self, self.chantier)

    def action_export_prbs_xlsx(self) -> None:
        app_exports.export_xlsx_arbre(self, self._current_arbre(),
                                       self.chantier)

    def action_export_prbs_html(self) -> None:
        app_exports.export_html_arbre(self, self._current_arbre(),
                                       self.chantier)

    def action_about(self) -> None:
        messagebox.showinfo(
            "À propos",
            f"Pénétromètre — Expertise arboricole\n"
            f"Version {__version__}\n\n"
            "Application desktop Python autonome.\n"
            "Tableau de sondages ↔ dessin synchronisés.\n"
            "Section ronde par interpolation spline.\n\n"
            "Note : « Résistographe » étant une marque déposée,\n"
            "ce logiciel utilise le terme générique « pénétromètre »."
            "\n\n— Silvavenir, Foresterie urbaine.")

    def action_shortcuts(self) -> None:
        messagebox.showinfo(
            "Raccourcis clavier",
            "Fichier\n"
            "  Ctrl+N   Nouvelle mission\n"
            "  Ctrl+O   Ouvrir une mission\n"
            "  Ctrl+S   Enregistrer\n"
            "  Ctrl+E   Exporter la fiche PDF de l'arbre courant\n"
            "\n"
            "Arbres\n"
            "  Ctrl+T        Ajouter un arbre\n"
            "  Ctrl+PgDown   Arbre suivant\n"
            "  Ctrl+PgUp     Arbre précédent\n"
            "  Double-clic sur un arbre : le renommer\n"
            "  Clic droit sur un arbre : menu d'actions\n"
            "\n"
            "Édition\n"
            "  Ctrl+Z   Annuler\n"
            "  Ctrl+Y   Rétablir\n"
            "  (Ctrl+Maj+Z fonctionne aussi pour Rétablir)")

    def action_open_log(self) -> None:
        """Ouvre le fichier de log de l'application avec l'éditeur par
        défaut du système. Utile quand un utilisateur cherche à
        comprendre une erreur ou à transmettre le log à un développeur."""
        log_path = Path.home() / ".penetrometre" / "penetrometre.log"
        if not log_path.exists():
            messagebox.showinfo(
                "Fichier de log",
                f"Aucun fichier de log trouvé à :\n{log_path}")
            return
        self._open_in_system(log_path)


def _setup_logging() -> Path:
    """Configure le logger applicatif vers un fichier rotatif lisible
    par l'utilisateur final.

    Sans cela, `traceback.print_exc()` part sur stdout — invisible
    quand l'app est lancée par double-clic Windows ou via le `.desktop`
    Linux. Avec ce logging, on peut demander à un utilisateur "envoie-
    moi le contenu de ~/.penetrometre/penetrometre.log" en cas de
    bug à distance.

    Renvoie le chemin du fichier de log (utilisable pour journaliser
    son emplacement au démarrage).
    """
    log_dir = Path.home() / ".penetrometre"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "penetrometre.log"

    logger = logging.getLogger("penetrometre")
    # Idempotence : ne pas doubler les handlers si _setup_logging est
    # rappelé (cas test, ou rechargement à chaud).
    if logger.handlers:
        return log_path
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        log_path, maxBytes=512_000, backupCount=2,
        encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)
    # On ne propage pas vers le root logger : pas de duplication si une
    # autre lib configure son propre handler.
    logger.propagate = False
    return log_path


def main() -> None:
    log_path = _setup_logging()
    log = logging.getLogger("penetrometre")
    log.info("Démarrage Pénétromètre v%s", __version__)
    try:
        App().mainloop()
    except Exception:
        log.exception("Crash non rattrapé dans la boucle principale")
        raise
    finally:
        log.info("Arrêt Pénétromètre — log: %s", log_path)


if __name__ == "__main__":
    main()
