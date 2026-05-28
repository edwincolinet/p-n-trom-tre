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
import logging
import tkinter as tk
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Iterator, Optional

import app_exports
from app_menu import build_menu
from app_style import apply_ttk_styles
from model import Arbre, Chantier
from palette import COLOR_BG
from pane_contreforts import ContrefortsPane
from pane_degradations import DegradationsPane
from pane_diagnostic import DiagnosticPane
from pane_identification import IdentificationPane
from pane_sondages import SondagesPane
from persistence import chantier_from_dict, chantier_to_dict, load_chantier, save_chantier
from section_canvas import SectionCanvas
from undo import UndoStack

__version__ = "3.3.0"


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
        self.geometry("1480x900")
        self.minsize(1280, 780)
        self.configure(bg=COLOR_BG)

        self.chantier = Chantier()
        self.chantier.arbres.append(Arbre(numero_arbre="1"))
        self.current_idx = 0
        self.current_file: Optional[Path] = None
        self._dirty = False
        self._suspend_sync = False
        self._redraw_id: Optional[str] = None
        self._undo_stack = UndoStack()
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
        self.protocol("WM_DELETE_WINDOW", self._on_close)

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

        lst_frame = ttk.Frame(frame, style="Side.TFrame")
        lst_frame.pack(fill="both", expand=True)
        self.tree_arbres = ttk.Treeview(
            lst_frame, columns=("ess",), show="tree headings",
            height=20, style="Side.Treeview")
        self.tree_arbres.heading("#0", text="Nom")
        self.tree_arbres.heading("ess", text="Essence")
        self.tree_arbres.column("#0", width=130, anchor="w")
        self.tree_arbres.column("ess", width=90, anchor="w")
        self.tree_arbres.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(lst_frame, orient="vertical",
                           command=self.tree_arbres.yview)
        sb.pack(side="right", fill="y")
        self.tree_arbres.configure(yscrollcommand=sb.set)
        self.tree_arbres.bind("<<TreeviewSelect>>", self._on_select_arbre)
        self.tree_arbres.bind("<Double-1>",
                              lambda e: self.action_rename_arbre())

        btns = ttk.Frame(frame, style="Side.TFrame")
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="＋ Ajouter", style="Accent.TButton",
                   command=self.action_add_arbre).pack(side="left")
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
        self.section = SectionCanvas(frame, width=550, height=550)
        self.section.pack(fill="both", expand=True)

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
        self.destroy()

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
            self.tree_arbres.item(sel[0], text=label,
                                  values=(a.essence,))

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

    # --- Liste d'arbres ---------------------------------------------

    def _refresh_tree_arbres(self) -> None:
        self.tree_arbres.delete(*self.tree_arbres.get_children())
        for i, a in enumerate(self.chantier.arbres):
            # Affichage compact : "n°X" (l'essence est dans la 2e colonne)
            label = f"n° {a.numero_arbre}" if a.numero_arbre else "(sans n°)"
            self.tree_arbres.insert("", "end", iid=f"a{i}",
                                    text=label, values=(a.essence,))
        if self.chantier.arbres:
            target = f"a{self.current_idx}"
            if target in self.tree_arbres.get_children():
                self.tree_arbres.selection_set(target)
                self.tree_arbres.focus(target)

    def _on_select_arbre(self, event: Optional["tk.Event[tk.Misc]"] = None) -> None:
        sel = self.tree_arbres.selection()
        if not sel:
            return
        idx = int(sel[0][1:])
        if idx == self.current_idx:
            return
        self.current_idx = idx
        self._load_arbre_to_ui()

    def action_add_arbre(self) -> None:
        self.push_undo()
        max_num = 0
        for arb in self.chantier.arbres:
            try:
                max_num = max(max_num, int(arb.numero_arbre))
            except (ValueError, TypeError):
                pass
        new_num = str(max(max_num + 1, len(self.chantier.arbres) + 1))
        self.chantier.arbres.append(Arbre(numero_arbre=new_num))
        self.current_idx = len(self.chantier.arbres) - 1
        self._refresh_tree_arbres()
        self._load_arbre_to_ui()

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
            new = simpledialog.askstring(
                "Renuméroter l'arbre",
                "Nouveau n° d'arbre (doit contenir au moins un chiffre,\n"
                "ex. « 1 », « 42 », « 12 bis ») :",
                initialvalue=proposed, parent=self)
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

    def on_show_sondages_toggled(self, show: bool) -> None:
        """Callback du DiagnosticPane : répercute le toggle sur le
        SectionCanvas (propriété de l'App)."""
        self.section.set_show_sondages(show)

    def _refresh_diag(self) -> None:
        if self.pane_diag is not None:
            self.pane_diag.refresh()

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
        self.chantier = Chantier()
        self.chantier.arbres.append(Arbre(numero_arbre="1"))
        self.current_idx = 0
        self.current_file = None
        with self._suspend_sync_block():
            self.var_ch_nom.set(self.chantier.nom)
            self.var_ch_adr.set("")
            self.var_ch_ope.set("")
            self.var_ch_date.set(self.chantier.date_releve)
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
        try:
            self._undo_stack.clear()
            self._dirty = False
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
            self._refresh_tree_arbres()
            self._load_arbre_to_ui()
            self._update_title()
        except Exception as e:
            log.exception("Échec ouverture mission")
            messagebox.showerror("Erreur d'ouverture", str(e))

    def action_save(self) -> None:
        if not self.current_file:
            return self.action_save_as()
        try:
            save_chantier(self.chantier, self.current_file)
            self._dirty = False
            self._update_title()
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
                                self.section.show_sondages)

    def action_export_pdf_arbre(self) -> None:
        app_exports.export_pdf_arbre(self, self._current_arbre(),
                                      self.chantier)

    def action_export_pdf_mission(self) -> None:
        app_exports.export_pdf_mission(self, self.chantier)

    def action_export_csv(self) -> None:
        app_exports.export_csv_mission(self, self.chantier)

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
