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

import logging
import os
import tkinter as tk
from contextlib import contextmanager
from functools import partial
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Iterator, Optional

from aide_repliable import AideRepliable
from app_arbres import (
    _RISK_FILTER_ALL,
    _RISK_FILTER_CHOICES,
    _URGENCE_FILTER_ALL,
    _URGENCE_FILTER_NONE,
    ArbreListMixin,
)
from app_export_actions import ExportActionsMixin
from app_fichier import _BACKUP_PATH, FichierMixin
from app_menu import build_menu, refresh_recent_menu
from app_recent import RecentFilesStore
from app_recovery import (
    _RECOVERY_PATH,
    RecoveryMixin,
)
from app_settings import SettingsStore
from app_style import apply_ttk_styles
from bareme import CLASSE_ORANGE, CLASSE_ROUGE, CLASSE_VERT
from dialogs import (
    ask_cepee_layout,
    ask_date,
    edit_contrefort,
    edit_degradation,
    edit_sondage,
    normaliser_date,
)
from model import URGENCE_NIVEAUX, Arbre, Brin, Chantier, Contrefort, DegradationExterne, Sondage
from palette import COLOR_ACCENT, COLOR_BG, COLOR_MUTED, COLOR_WARN, COULEUR_CLASSE
from pane_contreforts import ContrefortsPane
from pane_degradations import DegradationsPane
from pane_diagnostic import DiagnosticPane
from pane_identification import IdentificationPane
from pane_sondages import SondagesPane
from persistence import (
    chantier_from_dict,
    chantier_to_dict,
    clear_recovery,
)
from section_canvas import SectionCanvas
from tooltip import Tooltip
from ui_fonts import font as ui_font
from ui_fonts import set_ui_scale
from undo import UndoStack

__version__ = "3.6.0"

# Fichiers récents : on en garde 8, persistés en JSON dans le même
# répertoire que le log (~/.penetrometre/). 8 est un bon compromis :
# tient en un sous-menu compact, suffisant pour 1-2 semaines d'usage.
# La logique (chargement/persistance/déduplication) vit dans
# `app_recent.RecentFilesStore` ; l'autosave anti-crash et la
# récupération dans `app_recovery.RecoveryMixin`.
_RECENT_FILES_MAX = 8
_RECENT_FILES_PATH = Path.home() / ".penetrometre" / "recent.json"
_SETTINGS_PATH = Path.home() / ".penetrometre" / "settings.json"
# `_BACKUP_PATH` (dossier des sauvegardes glissantes) vit désormais dans
# `app_fichier` — responsabilité « enregistrement » — et est réimporté
# ci-dessus pour l'entrée de menu « Ouvrir le dossier des sauvegardes… ».


# Logger applicatif — configuré par `_setup_logging()` au démarrage.
# Tant qu'aucun handler n'est attaché (cas tests / import du module
# sans `main()`), les messages partent dans le vide silencieusement.
log = logging.getLogger("penetrometre")


# ---------------------------------------------------------------------------
# Application principale
# ---------------------------------------------------------------------------

class App(ArbreListMixin, RecoveryMixin, ExportActionsMixin, FichierMixin, tk.Tk):

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

        # Échelle du texte (accessibilité). Fixée AVANT la création des
        # widgets/styles pour que toutes les polices (styles ttk + tuples
        # explicites) naissent à la bonne taille. On agit sur le nombre
        # de taille des polices (`ui_fonts`), pas sur `tk scaling` qui est
        # inopérant sur plusieurs builds Tk/Linux. Le canvas (pixels) et
        # les paddings ne sont pas affectés.
        self._settings = SettingsStore(_SETTINGS_PATH)
        self._apply_ui_scale(self._settings.ui_scale)

        self.chantier = Chantier()
        self.chantier.arbres.append(Arbre(numero_arbre="1"))
        self.current_idx = 0
        # Brin (ramet) actuellement piloté par les onglets de saisie
        # (Identification géométrie / Sondages / Dégradations / Contreforts).
        # 0 = 1er brin ; remis à 0 à chaque changement d'arbre. Le sélecteur
        # de brin (cépée) le repointe via `set_current_brin`.
        self._current_brin_idx = 0
        self.current_file: Optional[Path] = None
        self._dirty = False
        self._suspend_sync = False
        self._redraw_id: Optional[str] = None
        self._undo_stack = UndoStack()
        self._recent = RecentFilesStore(
            _RECENT_FILES_PATH, _RECENT_FILES_MAX,
            on_change=lambda: refresh_recent_menu(self))  # type: ignore[arg-type]
        # Dernier fichier exporté — cible des boutons « Ouvrir le
        # fichier / le dossier » de la barre d'état (cf. notify_export).
        self._last_export_path: Optional[Path] = None
        # Mission de référence pour la comparaison inter-missions
        # (ré-inspection) : chargée en mémoire, PAR SESSION (rien de
        # persisté dans le fichier courant).
        self._reference_chantier: Optional[Chantier] = None
        self.pane_s: Optional[SondagesPane] = None
        self.pane_de: Optional[DegradationsPane] = None
        self.pane_cf: Optional[ContrefortsPane] = None
        self.pane_diag: Optional[DiagnosticPane] = None
        # Déclarés ici pour que mypy connaisse les types avant _build_layout.
        self._logo_image: Optional[Any] = None
        self._logo_frame: tk.Frame = tk.Frame(self)  # réassigné dans _build_layout

        self._apply_styles()
        build_menu(self)  # type: ignore[arg-type]
        self._build_layout()
        self._refresh_tree_arbres()
        self._load_arbre_to_ui()
        self._update_title()

        self.bind_all("<Control-z>", lambda e: self._perform_undo())
        self.bind_all("<Control-y>", lambda e: self._perform_redo())
        self.bind_all("<Control-Z>", lambda e: self._perform_redo())
        self.bind_all("<Control-e>", self._on_export_shortcut)
        self.bind_all("<Control-p>", self._on_print_shortcut)
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

    def _apply_ui_scale(self, scale: float) -> None:
        """Applique le facteur d'échelle du texte. `tk scaling` étant
        inopérant sur plusieurs builds Tk/Linux (métriques de police
        indépendantes du scaling), on agit sur le **nombre de taille**
        de chaque police via `ui_fonts` : les styles ttk et les tuples
        de police explicites le lisent à leur création."""
        set_ui_scale(scale)

    def _apply_styles(self) -> None:
        """Applique le thème ttk avec les réglages d'accessibilité courants
        (contraste élevé). Point unique pour ne jamais perdre le mode
        contraste en ré-appliquant les styles (p. ex. au changement de
        taille du texte)."""
        apply_ttk_styles(self, high_contrast=self._settings.high_contrast)

    def action_set_ui_scale(self, scale: float) -> None:
        """Change la taille du texte (menu Affichage) : persiste, met à
        jour le facteur, puis ré-applique les styles ttk pour un effet
        immédiat sur la majorité de l'UI. Les quelques widgets à police
        en tuple (déjà réalisés) ne se redimensionnent qu'au redémarrage
        — d'où le rappel en barre d'état."""
        self._settings.set_ui_scale(scale)
        self._apply_ui_scale(self._settings.ui_scale)
        self._apply_styles()
        self.set_status(
            "Taille du texte modifiée. Relancez l'application pour "
            "l'appliquer entièrement.")

    def action_set_high_contrast(self, on: bool) -> None:
        """Active/désactive le contraste élevé (menu Affichage) : persiste
        et ré-applique les styles ttk à chaud. Les widgets à couleur déjà
        peinte hors styles (tags de la liste, dessin) ne changent pas —
        d'où le rappel d'un redémarrage pour un effet complet."""
        self._settings.set_high_contrast(on)
        self._apply_styles()
        self.set_status(
            "Contraste élevé " + ("activé." if on else "désactivé.")
            + " Relancez l'application pour l'appliquer entièrement.")

    def get_high_contrast(self) -> bool:
        """État courant du contraste élevé (pour cocher l'item de menu)."""
        return self._settings.high_contrast

    def get_ui_scale(self) -> float:
        """Facteur d'échelle courant (pour cocher le bon item de menu)."""
        return self._settings.ui_scale

    def _reload_logo(self) -> None:
        """Recharge le logo depuis les settings et met à jour la zone header."""
        for child in self._logo_frame.winfo_children():
            child.destroy()
        self._logo_image = None

        logo_path_str = self._settings.logo_path
        if not logo_path_str:
            # Placeholder cliquable quand aucun logo n'est configuré
            btn = ttk.Button(self._logo_frame,
                             text="+ Logo cabinet",
                             style="Ghost.TButton",
                             command=self.action_cabinet_settings)
            btn.pack()
            return
        try:
            from PIL import Image as PILImage
            from PIL import ImageTk
            p = Path(logo_path_str)
            if not p.exists():
                log.warning("Logo configuré introuvable : %s", p)
                return
            pil = PILImage.open(p)
            target_h = 56
            ratio = target_h / pil.height
            pil = pil.resize(  # type: ignore[assignment]
                (int(pil.width * ratio), target_h),
                PILImage.LANCZOS)  # type: ignore[attr-defined]
            self._logo_image = ImageTk.PhotoImage(pil)
            lbl = ttk.Label(self._logo_frame, image=self._logo_image)
            lbl.pack()
            lbl.bind("<Button-1>",
                     lambda e: self.action_cabinet_settings())
        except ImportError:
            log.warning("Pillow indisponible — logo non affiché dans le header")
        except Exception:
            log.exception("Échec du chargement du logo")

    def action_cabinet_settings(self) -> None:
        """Ouvre le dialogue de configuration du cabinet (logo + nom)."""
        from dialogs_settings import ask_cabinet_settings
        changed = ask_cabinet_settings(self, self._settings)
        if changed:
            self._reload_logo()

    def _on_export_shortcut(self, _event: "tk.Event[tk.Misc]") -> None:
        """Ctrl+E → fiche PDF de l'arbre courant. Neutralisé quand un
        champ texte a le focus : dans les `Entry`/`Combobox` Tk, Ctrl+E
        signifie « aller en fin de ligne » — on laisse le widget gérer
        plutôt que d'ouvrir un dialogue d'export en pleine saisie."""
        w = self.focus_get()
        if isinstance(w, (ttk.Entry, ttk.Combobox, tk.Entry)):
            return
        self.action_export_pdf_arbre()

    def _on_print_shortcut(self, _event: "tk.Event[tk.Misc]") -> None:
        """Ctrl+P → impression directe de la fiche PDF de l'arbre courant.
        Neutralisé dans les champs texte (Ctrl+P = début de ligne)."""
        w = self.focus_get()
        if isinstance(w, (ttk.Entry, ttk.Combobox, tk.Entry)):
            return
        self.action_print_arbre()

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

        # Boutons « Comparaison » mis en avant (la ré-inspection n'est plus
        # une fonctionnalité cachée du menu). Cf. menu Comparaison (app_menu).
        comp = ttk.Frame(header)
        comp.pack(side="left", padx=(28, 0))
        btn_reinsp = ttk.Button(
            comp, text="🔍 Faire une comparaison…", style="Accent.TButton",
            command=self.action_reinspection)
        btn_reinsp.pack(side="left")
        Tooltip(btn_reinsp,
                "Repartir d'une mission antérieure comme base : on met à jour "
                "diamètres et sondages au lieu de tout ressaisir, et elle sert "
                "de référence.")
        self._btn_compare = ttk.Button(
            comp, text="📊 Diagnostic de la comparaison…", style="Ghost.TButton",
            command=self.action_compare_arbre, state="disabled")
        self._btn_compare.pack(side="left", padx=(6, 0))
        Tooltip(self._btn_compare, "Ouvrir la fenêtre de comparaison de l'arbre "
                                   "courant avec la mission de référence.")

        # Bloc droit : zone logo cabinet (cliquable → paramètres cabinet).
        # PIL est requis pour les exports PNG/PDF — s'il est absent au
        # démarrage, l'utilisateur l'apprend ici (log) plutôt qu'au
        # moment d'un clic « Exporter PDF » qui échouerait silencieusement.
        self._logo_frame = tk.Frame(header, cursor="hand2")
        self._logo_frame.pack(side="right", padx=(12, 0))
        self._logo_frame.bind(
            "<Button-1>", lambda e: self.action_cabinet_settings())
        Tooltip(self._logo_frame,
                "Cliquer pour configurer le logo et le nom du cabinet…")
        try:
            from PIL import Image as PILImage  # noqa: F401
        except ImportError as exc:
            log.warning(
                "Pillow indisponible (%s) — les exports PNG et PDF "
                "ne pourront pas être générés. Installer Pillow via "
                "`pip install -r requirements.txt`.", exc)
        self._reload_logo()

        meta = ttk.Frame(self)
        meta.pack(fill="x", padx=18, pady=(0, 10))
        self.var_ch_nom = tk.StringVar(value=self.chantier.nom)
        self.var_ch_adr = tk.StringVar(value=self.chantier.adresse)
        self.var_ch_ope = tk.StringVar(value=self.chantier.operateur)
        self.var_ch_date = tk.StringVar(value=self.chantier.date_releve)
        self._meta_snapshot: Optional[str] = None
        self._date_focus_in_value = ""
        for lbl, var, w in [("Mission", self.var_ch_nom, 22),
                            ("Adresse", self.var_ch_adr, 30),
                            ("Opérateur", self.var_ch_ope, 18),
                            ("Date", self.var_ch_date, 12)]:
            ttk.Label(meta, text=lbl).pack(side="left", padx=(0, 4))
            e = ttk.Entry(meta, textvariable=var, width=w)
            var.trace_add("write", lambda *a: self._sync_chantier_meta())
            if lbl == "Date":
                # Saisie clavier libre normalisée en JJ/MM/AAAA au focus-out
                # (`14-6-26`, `2026/06/14`, …) ; saisie non interprétable
                # rétablie. Bouton « 📅 » : sélection au calendrier (Tk pur).
                e.pack(side="left", padx=(0, 2))
                e.bind("<FocusIn>", lambda ev: self._date_focus_in())
                e.bind("<FocusOut>", lambda ev: self._date_focus_out())
                Tooltip(e, "Date du relevé — format JJ/MM/AAAA "
                           "(normalisée automatiquement).")
                btn_cal = ttk.Button(meta, text="📅", width=3,
                                     style="Ghost.TButton",
                                     command=self._pick_date)
                btn_cal.pack(side="left", padx=(0, 14))
                Tooltip(btn_cal, "Choisir la date au calendrier")
            else:
                e.pack(side="left", padx=(0, 14))
                e.bind("<FocusIn>", lambda ev: self._meta_focus_in())
                e.bind("<FocusOut>", lambda ev: self._meta_focus_out())

        # Barre d'état AVANT le body : packée en bas, le body (expand)
        # remplit l'espace restant au-dessus.
        self._build_statusbar()

        # 3 colonnes redimensionnables à la souris (poignées) : l'opérateur
        # réalloue l'espace selon la tâche — élargir le tableau de saisie au
        # détriment du dessin, ou réduire la liste/le dessin sur un petit
        # écran. `tk.PanedWindow` (classique) car il gère un `minsize` par
        # panneau ; le dessin (`SectionCanvas`) se redessine sur <Configure>.
        # Positions de sash restaurées/persistées via SettingsStore.
        body = tk.PanedWindow(self, orient="horizontal", bg=COLOR_BG,
                              sashwidth=8, sashrelief="flat", bd=0,
                              opaqueresize=True)
        body.pack(fill="both", expand=True, padx=18, pady=(0, 14))
        self._paned = body
        self._build_left(body)
        self._build_center(body)
        self._build_right(body)
        self._restore_sash_positions()

    def _build_left(self, parent: tk.PanedWindow) -> None:
        frame = ttk.Frame(parent, style="Side.TFrame", padding=10)
        parent.add(frame, minsize=280, width=340, stretch="never")
        ttk.Label(frame, text="Arbres de la mission", style="Side.TLabel",
                  font=ui_font("Georgia", 12, "bold")).pack(anchor="w", pady=(0, 8))

        # Filtre de la liste (par n°, essence ou commentaire) — utile dès que la
        # mission compte beaucoup d'arbres. N'altère PAS le modèle : ne
        # fait que masquer les lignes non concordantes (les iid `a{i}`
        # restent indexés sur la position réelle dans `chantier.arbres`,
        # cf. `_on_select_arbre`). `var_filter` est lue par
        # `_refresh_tree_arbres` (tolérante si appelée avant ce build).
        filt = ttk.Frame(frame, style="Side.TFrame")
        filt.pack(fill="x", pady=(0, 4))
        ttk.Label(filt, text="🔎", style="Side.TLabel").pack(side="left",
                                                             padx=(0, 4))
        self.var_filter = tk.StringVar()
        ent_filter = ttk.Entry(filt, textvariable=self.var_filter)
        ent_filter.pack(side="left", fill="x", expand=True)
        self.var_filter.trace_add("write",
                                  lambda *a: self._refresh_tree_arbres())
        # Échap dans le champ = vider le filtre.
        ent_filter.bind("<Escape>", lambda e: self.var_filter.set(""))

        # Filtre par classe de risque (complète la recherche texte ; les
        # deux se cumulent). Sur une grosse mission, « ne montrer que les
        # rouges » est le tri prioritaire de l'expert. Cf. _RISK_FILTER_*
        # et `_arbre_matches_filter`.
        rfilt = ttk.Frame(frame, style="Side.TFrame")
        rfilt.pack(fill="x", pady=(0, 4))
        ttk.Label(rfilt, text="Risque", style="Side.TLabel").pack(
            side="left", padx=(0, 4))
        self.var_risk_filter = tk.StringVar(value=_RISK_FILTER_ALL)
        cmb_risk = ttk.Combobox(rfilt, textvariable=self.var_risk_filter,
                                values=list(_RISK_FILTER_CHOICES),
                                state="readonly", width=12)
        cmb_risk.pack(side="left", fill="x", expand=True)
        cmb_risk.bind("<<ComboboxSelected>>",
                      lambda e: self._refresh_tree_arbres())

        ufilt = ttk.Frame(frame, style="Side.TFrame")
        ufilt.pack(fill="x", pady=(0, 6))
        ttk.Label(ufilt, text="Urgence", style="Side.TLabel").pack(
            side="left", padx=(0, 4))
        self.var_urgence_filter = tk.StringVar(value=_URGENCE_FILTER_ALL)
        self._cmb_urgence_filter = ttk.Combobox(
            ufilt, textvariable=self.var_urgence_filter,
            values=self._urgence_filter_choices(),
            state="readonly", width=12)
        self._cmb_urgence_filter.pack(side="left", fill="x", expand=True)
        self._cmb_urgence_filter.bind("<<ComboboxSelected>>",
                                      lambda e: self._refresh_tree_arbres())

        # Bandeau "filtre actif" : apparaît sous les filtres quand au moins
        # un arbre est masqué. Propose un bouton de réinitialisation rapide
        # — évite de devoir remettre chaque combobox à la main.
        self._filtre_actif_frame = ttk.Frame(frame, style="Side.TFrame")
        self._lbl_filtre_actif = ttk.Label(
            self._filtre_actif_frame, text="",
            style="Side.TLabel", foreground=COLOR_ACCENT,
            font=ui_font("Helvetica", 9, "italic"))
        self._lbl_filtre_actif.pack(side="left", padx=(0, 6))
        ttk.Button(
            self._filtre_actif_frame, text="✕ Réinitialiser",
            style="Ghost.TButton",
            command=self._reset_all_filters,
        ).pack(side="left")

        lst_frame = ttk.Frame(frame, style="Side.TFrame")
        self._lst_frame = lst_frame
        self.tree_arbres = ttk.Treeview(
            lst_frame, columns=("ess", "etat", "risque"),
            show="tree headings", height=20, style="Side.Treeview")
        self.tree_arbres.heading("#0", text="Nom")
        self.tree_arbres.heading("ess", text="Essence")
        self.tree_arbres.heading("etat", text="État")
        self.tree_arbres.heading("risque", text="Risque")
        self.tree_arbres.column("#0", width=64, anchor="w")
        self.tree_arbres.column("ess", width=58, anchor="w")
        self.tree_arbres.column("etat", width=30, anchor="center",
                                stretch=False)
        self.tree_arbres.column("risque", width=56, anchor="center",
                                stretch=False)
        # Deux canaux distincts (cf. _arbre_etat) : la FORME du glyphe
        # (colonne État) porte la complétude ; le MOT (colonne Risque) +
        # la couleur de ligne portent la classe de risque. La couleur ne
        # signifie donc plus qu'UNE chose (le risque) : les arbres
        # incomplets (○/◐) sont en gris NEUTRE, plus en rouge/orange —
        # ce qui levait l'ambiguïté « ligne orange = partielle ou classe
        # orange ? ». On évite les emojis 🔴🟠🟢 (rendu monochrome
        # imprévisible selon la police système dans ttk.Treeview).
        self.tree_arbres.tag_configure("etat_vide", foreground=COLOR_MUTED)
        self.tree_arbres.tag_configure("etat_partiel", foreground=COLOR_MUTED)
        self.tree_arbres.tag_configure("etat_ok",
                                        foreground="#1A5A2A")
        # Arbre au diagnostic fiable (≥3 sondages) : ligne colorée selon la
        # CLASSE DE RISQUE globale (cf. _arbre_etat) — repérage du risque
        # dans la liste sans ouvrir l'onglet Diagnostic, doublé du mot.
        self.tree_arbres.tag_configure("etat_ok_vert",
                                        foreground=COULEUR_CLASSE[CLASSE_VERT])
        self.tree_arbres.tag_configure(
            "etat_ok_orange", foreground=COULEUR_CLASSE[CLASSE_ORANGE])
        self.tree_arbres.tag_configure(
            "etat_ok_rouge", foreground=COULEUR_CLASSE[CLASSE_ROUGE])
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

        # Éléments du bas packés en side="bottom" AVANT lst_frame (sinon
        # lst_frame avec expand=True les pousserait hors de l'écran quand le
        # bandeau filtre actif agrandit la zone des filtres). Ordre inverse
        # de l'ordre visuel : le premier packé en bottom est le plus bas.
        btns = ttk.Frame(frame, style="Side.TFrame")
        btns.pack(side="bottom", fill="x", pady=(10, 0))
        mb_add = ttk.Menubutton(btns, text="＋ Ajouter",
                                style="Accent.TMenubutton", direction="above")
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

        # Triage de fin de mission : saute au prochain arbre incomplet
        # (pendant du compteur « N à finir » juste au-dessous).
        btn_afinir = ttk.Button(
            frame, text="⏭ Prochain arbre à finir", style="Ghost.TButton",
            command=self.action_next_a_finir)
        btn_afinir.pack(side="bottom", anchor="w", pady=(4, 0))
        Tooltip(btn_afinir, "Sélectionne le prochain arbre au diagnostic "
                            "non fiable (rayon manquant ou < 3 sondages), "
                            "en bouclant. Vide les filtres si besoin.")

        # Footer = vue de triage macro (répartition rouge/orange/vert/à
        # finir) — cf. `_update_etat_footer`. Wrap pour tenir dans le
        # panneau gauche étroit.
        self.lbl_etat_footer = ttk.Label(
            frame, text="", style="Side.TLabel", wraplength=250,
            justify="left", font=ui_font("Helvetica", 9, "italic"))
        self.lbl_etat_footer.pack(side="bottom", anchor="w", pady=(6, 0))

        lst_frame.pack(fill="both", expand=True)

    def _build_center(self, parent: tk.PanedWindow) -> None:
        frame = ttk.Frame(parent, style="Panel.TFrame", padding=12)
        parent.add(frame, minsize=400, width=510, stretch="always")
        # Sélecteur de brin (cépée) : barre de boutons « Brin a / b / c »
        # au-dessus des onglets, qui repointe la saisie (Identification
        # géométrie / Sondages / Dégradations / Contreforts) sur le brin
        # choisi. Masquée pour un genet mono-caule (1 brin) — voir
        # `_refresh_brin_selector`.
        self.brin_bar = ttk.Frame(frame, style="BrinBar.TFrame")
        self.var_current_brin = tk.IntVar(value=0)
        self._brin_btns: list[ttk.Radiobutton] = []
        # Barre d'accent verticale gauche (identique à la fiche PDF préconisation)
        tk.Frame(self.brin_bar, bg=COLOR_ACCENT, width=3).pack(
            side="left", fill="y", padx=(0, 10))
        ttk.Label(self.brin_bar, text="Brin :", style="BrinBar.TLabel").pack(
            side="left", padx=(0, 8), pady=7)
        self._brin_btns_holder = ttk.Frame(self.brin_bar, style="BrinBar.TFrame")
        self._brin_btns_holder.pack(side="left", fill="x", expand=True, pady=5)
        # Flow layout : re-répartir les boutons de brin quand la largeur
        # disponible change (sinon, sur une cépée à nombreux brins, la
        # rangée unique déborde du panneau — cf. `_reflow_brin_btns`).
        self._brin_bar_last_w = -1
        self._brin_btns_holder.bind("<Configure>", self._on_brin_bar_configure)

        nb = ttk.Notebook(frame)
        self.nb = nb
        # Navigation clavier entre onglets (Ctrl+Tab / Ctrl+Maj+Tab) : sans
        # cet appel, ttk.Notebook ne lie AUCUNE touche. Complète le flux de
        # saisie au clavier (rayon → Ctrl+Tab → sondages → …) sans repasser
        # par la souris. Pas de conflit avec Ctrl+PgUp/PgDown (navigation
        # entre arbres) ni Ctrl+Z/Y.
        nb.enable_traversal()
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

    def _build_right(self, parent: tk.PanedWindow) -> None:
        frame = ttk.Frame(parent, style="Panel.TFrame", padding=10)
        parent.add(frame, minsize=360, width=460, stretch="always")
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
        # Rien ne le signalait a priori — d'où ce rappel, repliable.
        AideRepliable(
            frame,
            "Cliquez un élément du dessin pour le modifier, ou une "
            "direction libre pour ajouter un sondage.",
            wraplength=440,
        ).pack(anchor="w", pady=(2, 0))
        # Indice visible quand l'arbre n'a aucun sondage : guide le premier
        # geste de saisie sans devoir déplier l'aide. Disparaît dès que le
        # premier sondage est ajouté.
        self._lbl_canvas_hint = ttk.Label(
            frame,
            text="→ Cliquer sur une direction libre du dessin pour ajouter "
                 "un sondage",
            style="Muted.TLabel", wraplength=440)
        self._lbl_canvas_hint.pack(anchor="w", pady=(2, 0))

    # --- Poignées de disposition (PanedWindow) -------------------------

    def _restore_sash_positions(self) -> None:
        """Restaure les positions de poignées persistées et branche leur
        sauvegarde après chaque glisser. Les positions ne s'appliquent
        qu'une fois la PanedWindow dimensionnée (sinon `sash_place` lève
        une TclError) → différé via `after`."""
        positions = self._settings.get_sash_positions()
        if positions:
            self.after(150, lambda: self._apply_sash_positions(positions))
        self._paned.bind("<ButtonRelease-1>",
                         lambda e: self._save_sash_positions())

    def _apply_sash_positions(self, positions: list[int]) -> None:
        try:
            for i, x in enumerate(positions):
                self._paned.sash_place(i, x, 1)
        except tk.TclError:
            pass

    def _save_sash_positions(self) -> None:
        """Mémorise les positions des poignées (réglage souris persistant
        de la répartition liste / saisie / dessin)."""
        try:
            n_sashes = len(self._paned.panes()) - 1
            coords = [self._paned.sash_coord(i)[0] for i in range(n_sashes)]
        except tk.TclError:
            return
        self._settings.set_sash_positions(coords)

    def _build_statusbar(self) -> None:
        """Barre d'état en bas de fenêtre : message + boutons d'ouverture
        du dernier export. Remplace les `messagebox` de succès d'export
        (un « OK » à cliquer à chaque fois) par un retour non-modal."""
        bar = ttk.Frame(self, style="Side.TFrame")
        bar.pack(side="bottom", fill="x")
        # Bouton Enregistrer TOUJOURS visible : le menu / Ctrl+S ne donne
        # aucun repère permanent à l'opérateur terrain (« ai-je enregistré ? »).
        self._btn_save = ttk.Button(bar, text="💾 Enregistrer",
                                    style="Ghost.TButton",
                                    command=self.action_save)
        self._btn_save.pack(side="left", padx=(10, 6), pady=2)
        Tooltip(self._btn_save, "Enregistrer la mission (Ctrl+S)")
        # Indicateur d'état d'enregistrement, mis à jour à chaque mutation
        # (le « • » du titre est trop discret, et masquable par le WM).
        self.lbl_save_state = ttk.Label(
            bar, text="", style="Side.TLabel",
            font=ui_font("Helvetica", 9, "bold"))
        self.lbl_save_state.pack(side="left", padx=(0, 14), pady=3)
        self.lbl_status = ttk.Label(bar, text="Prêt.", style="Side.TLabel",
                                    font=ui_font("Helvetica", 9))
        self.lbl_status.pack(side="left", padx=(0, 12), pady=3)
        self._btn_open_folder = ttk.Button(
            bar, text="Ouvrir le dossier", style="Ghost.TButton",
            command=self._open_last_export_folder, state="disabled")
        self._btn_open_folder.pack(side="right", padx=(0, 10), pady=2)
        self._btn_open_file = ttk.Button(
            bar, text="Ouvrir le fichier", style="Ghost.TButton",
            command=self._open_last_export_file, state="disabled")
        self._btn_open_file.pack(side="right", padx=(0, 4), pady=2)
        self._update_save_indicator()

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
        self._update_save_indicator()

    def _update_compare_state(self) -> None:
        """Active ou désactive le bouton et l'entrée menu « Diagnostic de la
        comparaison » selon qu'une mission de référence est chargée ou non."""
        state = "normal" if self._reference_chantier is not None else "disabled"
        if hasattr(self, "_btn_compare"):
            self._btn_compare.configure(state=state)
        if hasattr(self, "_menu_comparaison"):
            self._menu_comparaison.entryconfigure(1, state=state)

    def _update_save_indicator(self) -> None:
        """Reflète l'état d'enregistrement dans la barre d'état (texte +
        couleur) et l'activation du bouton Enregistrer. Centralisé via
        `_update_title`, donc à jour à chaque changement du dirty flag.
        No-op tant que la barre n'est pas construite (ordre d'`__init__`)."""
        if not hasattr(self, "lbl_save_state"):
            return
        if self._dirty:
            self.lbl_save_state.configure(
                text="● Modifications non enregistrées",
                foreground=COLOR_WARN)
            self._btn_save.configure(state="normal")
        elif self.current_file is not None:
            self.lbl_save_state.configure(
                text="✓ Enregistré", foreground=COLOR_ACCENT)
            self._btn_save.configure(state="disabled")
        else:
            # Mission neuve jamais enregistrée : rien à perdre, mais le
            # bouton reste actif (premier « Enregistrer sous… »).
            self.lbl_save_state.configure(
                text="Mission non enregistrée", foreground=COLOR_MUTED)
            self._btn_save.configure(state="normal")

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

    # Autosave anti-crash + récupération : cf. `app_recovery.RecoveryMixin`
    # (_schedule_autosave / _autosave_tick / _check_recovery_on_startup /
    # _restore_recovery).

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

    def _current_brin(self) -> Optional[Brin]:
        """Le brin (ramet) actuellement édité par les onglets de saisie.

        Pour un genet mono-caule, c'est l'unique brin (= `brins[0]`, donc
        comportement historique inchangé). Pour une cépée, c'est le brin
        désigné par le sélecteur (`_current_brin_idx`). L'index est borné
        ici pour rester valide même si des brins ont été retirés."""
        a = self._current_arbre()
        if a is None or not a.brins:
            return None
        self._current_brin_idx = max(
            0, min(self._current_brin_idx, len(a.brins) - 1))
        return a.brins[self._current_brin_idx]

    def set_current_brin(self, idx: int) -> None:
        """Repointe les onglets de saisie sur le brin `idx` (sélecteur de
        cépée). Commite d'abord une édition de rayon éventuellement en cours
        sur le brin ACTUEL, puis recharge les vues sans réinitialiser
        l'index (contrairement à `_load_arbre_to_ui`)."""
        a = self._current_arbre()
        if a is None:
            return
        idx = max(0, min(idx, len(a.brins) - 1))
        if idx == self._current_brin_idx:
            return
        self.pane_id.flush()
        self._current_brin_idx = idx
        self._reload_current_views()

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

    def _date_focus_in(self) -> None:
        self._date_focus_in_value = self.var_ch_date.get()
        self._meta_focus_in()

    def _date_focus_out(self) -> None:
        """Normalise la date au format JJ/MM/AAAA si elle a changé. Une
        saisie non interprétable rétablit la valeur d'avant l'édition
        (motif de revert déjà utilisé pour le n° d'arbre)."""
        raw = self.var_ch_date.get()
        if raw != self._date_focus_in_value:
            norm = normaliser_date(raw)
            if norm is None:
                self.var_ch_date.set(self._date_focus_in_value)
                self.set_status(
                    "Date non reconnue — format attendu JJ/MM/AAAA ; "
                    "valeur précédente rétablie.")
            elif norm != raw:
                self.var_ch_date.set(norm)
        self._meta_focus_out()

    def _pick_date(self) -> None:
        """Ouvre le calendrier (`dialogs.ask_date`) et applique la date
        choisie (undo si elle change). `None` = annulation → no-op ; `""`
        = l'utilisateur a effacé la date."""
        res = ask_date(self, self.var_ch_date.get())
        if res is None or res == self.var_ch_date.get():
            return
        self.push_undo()
        self.var_ch_date.set(res)  # trace → _sync_chantier_meta (dirty)

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
            glyph, risque, tag = self._arbre_etat(a)
            self.tree_arbres.item(sel[0], text=label,
                                  values=(a.essence, glyph, risque),
                                  tags=(tag,))
            # Recalcule le footer (le passage d'un arbre orange→vert
            # change la répartition de la mission).
            self._update_etat_footer()

    def add_brin(self) -> None:
        """Ajoute un brin (ramet) à l'arbre courant (cépée) : push undo,
        mutation modèle, dirty + redraw. Le formulaire d'identification
        continue d'éditer le 1er brin ; le nouveau brin apparaît dans le
        dessin (lecture seule jusqu'à l'éditeur multi-brins)."""
        a = self._current_arbre()
        if not a:
            return
        self.push_undo()
        a.ajouter_brin()
        # Le brin neuf devient courant : l'opérateur enchaîne directement
        # sur sa saisie (rayon/sondages). Recharge toutes les vues.
        self._current_brin_idx = len(a.brins) - 1
        self._reload_current_views()

    def remove_last_brin(self) -> None:
        """Retire le dernier brin de la cépée (no-op si genet mono-caule)."""
        a = self._current_arbre()
        if not a or len(a.brins) <= 1:
            return
        self.push_undo()
        a.supprimer_brin(len(a.brins) - 1)
        # `_current_brin_idx` est borné par `_current_brin`/`set_current_brin`,
        # mais on recharge les vues pour resynchroniser sélecteur + tables.
        self._current_brin_idx = min(self._current_brin_idx, len(a.brins) - 1)
        self._reload_current_views()

    def edit_cepee_layout(self) -> None:
        """Ouvre l'éditeur de disposition de la cépée (placement des brins à
        la souris) et applique les nouvelles positions. No-op si moins de
        2 brins ou si l'utilisateur annule / ne déplace rien."""
        a = self._current_arbre()
        if a is None or len(a.brins) < 2:
            return
        # Flush d'une édition de rayon en cours (le contour dessiné doit être
        # à jour) avant d'ouvrir l'éditeur.
        self.pane_id.flush()
        res = ask_cepee_layout(self, a)
        if res is None or len(res) != len(a.brins):
            return
        changed = any(
            abs(res[i][0] - b.pos_x_cm) > 1e-9
            or abs(res[i][1] - b.pos_y_cm) > 1e-9
            or res[i][2] != b.rotation_grades
            for i, b in enumerate(a.brins))
        if not changed:
            return
        self.push_undo()
        for i, b in enumerate(a.brins):
            b.pos_x_cm, b.pos_y_cm, b.rotation_grades = res[i]
        self._mark_dirty()
        self._debounced_redraw()

    def _refresh_brin_selector(self) -> None:
        """Reconstruit la barre « Brin a / b / c » au-dessus des onglets.

        Masquée pour un genet mono-caule (un seul brin → pas de choix à
        faire). Sinon, un bouton-bascule (Radiobutton style Toolbutton) par
        brin, le courant coché. Reconstruite à chaque rechargement car le
        nombre de brins et leurs labels varient (ajout/suppression)."""
        bar = getattr(self, "brin_bar", None)
        if bar is None:
            return
        for b in self._brin_btns:
            b.destroy()
        self._brin_btns = []
        a = self._current_arbre()
        n = len(a.brins) if a else 1
        if a is None or n <= 1:
            bar.pack_forget()
            return
        self.var_current_brin.set(self._current_brin_idx)
        for i, brin in enumerate(a.brins):
            label = brin.label or chr(ord("a") + i)
            rb = ttk.Radiobutton(
                self._brin_btns_holder, text=f"Brin {label}",
                value=i, variable=self.var_current_brin, style="Brin.Toolbutton",
                command=partial(self.set_current_brin, i))
            self._brin_btns.append(rb)
        bar.pack(fill="x", pady=(0, 8), before=self.nb)
        self._reflow_brin_btns()

    def _on_brin_bar_configure(self, event: "tk.Event[tk.Misc]") -> None:
        """Re-répartit les boutons de brin quand la largeur du holder
        change (redimensionnement du panneau central)."""
        w = event.width
        if w == self._brin_bar_last_w:
            return
        self._brin_bar_last_w = w
        self._reflow_brin_btns(avail=w)

    def _reflow_brin_btns(self, avail: "int | None" = None) -> None:
        """Dispose les boutons de brin en grille à retour à la ligne.

        Une rangée unique `side="left"` déborde du panneau central sur une
        cépée à nombreux brins → les derniers brins sortent de la page et
        deviennent incliquables. On calcule combien de boutons tiennent dans
        la largeur disponible et on les répartit sur plusieurs rangées."""
        btns = self._brin_btns
        if not btns:
            return
        holder = self._brin_btns_holder
        if avail is None:
            holder.update_idletasks()
            avail = holder.winfo_width()
        pad = 6
        bw = max((b.winfo_reqwidth() for b in btns), default=1) + pad
        # avail <= 1 : holder pas encore dimensionné → tout sur une rangée
        # (sera reflowé au 1er <Configure>).
        cols = len(btns) if avail <= 1 else max(1, avail // bw)
        for idx, b in enumerate(btns):
            r, c = divmod(idx, cols)
            b.grid(row=r, column=c, padx=(0, pad), pady=2, sticky="w")

    def _load_arbre_to_ui(self) -> None:
        """Recharge l'UI complète depuis l'arbre courant : identification
        + tables Sondages/Dégradations/Contreforts + redraw du dessin.

        Repointe le brin courant sur le 1er brin (changement d'arbre =
        on repart du brin a), puis recharge les vues."""
        self._current_brin_idx = 0
        self._reload_current_views()

    def _reload_current_views(self) -> None:
        """Recharge identification + tables + sélecteur de brin + dessin
        depuis l'arbre/brin courants, SANS toucher `_current_brin_idx`.
        Mutualisé entre `_load_arbre_to_ui` (changement d'arbre) et
        `set_current_brin` (changement de brin dans une cépée)."""
        self.pane_id.load_from_arbre()
        self._refresh_sondages_table()
        self._refresh_degradations_table()
        self._refresh_contreforts_table()
        self._refresh_brin_selector()
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
        self._refresh_tab_progress()
        self._update_canvas_hint()
        # Garde-fou fusion (⚠ non bloquant) : recalculé après toute
        # mutation car la condition croise les DEUX saisies (altération
        # des sondages + profondeur des dégradations). Ces méthodes ne
        # touchent que des labels en lecture seule — sûres pendant la
        # frappe, contrairement à un refresh() complet des grilles.
        if self.pane_s is not None:
            self.pane_s.refresh_fusion_warnings()
        if self.pane_de is not None:
            self.pane_de.refresh_fusion_warnings()

    def _update_canvas_hint(self) -> None:
        """Affiche/masque l'indice « → Cliquer pour ajouter un sondage »
        selon qu'il existe ou non des sondages sur l'arbre courant."""
        if not hasattr(self, "_lbl_canvas_hint"):
            return
        a = self._current_arbre()
        has_sondages = a is not None and any(b.sondages for b in a.brins)
        if has_sondages:
            if self._lbl_canvas_hint.winfo_ismapped():
                self._lbl_canvas_hint.pack_forget()
        elif not self._lbl_canvas_hint.winfo_ismapped():
            self._lbl_canvas_hint.pack(anchor="w", pady=(2, 0))

    def _reset_all_filters(self) -> None:
        """Réinitialise les trois filtres de la liste d'arbres en une action."""
        self.var_risk_filter.set(_RISK_FILTER_ALL)
        self.var_urgence_filter.set(_URGENCE_FILTER_ALL)
        self.var_filter.set("")  # la trace sur var_filter déclenche le refresh

    def essences_utilisees(self) -> list[str]:
        """Essences déjà saisies dans la mission (ordre d'apparition, sans
        doublons). Alimente la combobox Essence de l'onglet Identification."""
        seen: list[str] = []
        for a in self.chantier.arbres:
            if a.essence and a.essence not in seen:
                seen.append(a.essence)
        return seen

    def _refresh_tab_progress(self) -> None:
        """Préfixe les onglets de l'étape par un glyphe d'avancement
        (même vocabulaire que les pastilles : `○` à faire · `◐` en cours
        · `●` prêt). La FORME porte l'info (lisible en daltonisme), les
        onglets ttk n'autorisant de toute façon pas de couleur par
        onglet. Donne au notebook le sens de progression du protocole
        (Identification → Sondages → Diagnostic) que de simples libellés
        ne transmettaient pas. Dégradations/Contreforts restent sans
        glyphe : étapes optionnelles, un `○` y suggérerait à tort un
        manque."""
        a = self._current_arbre()
        if a is None:
            return
        g_ident = "●" if (a.rayon_tronc_cm > 0 and a.essence.strip()) else "○"
        g_sond = self._arbre_etat(a)[0]
        g_diag = "●" if self._arbre_diag_fiable(a) else "○"
        self.nb.tab(self.pane_id, text=f"{g_ident} Identification")
        self.nb.tab(self.pane_s, text=f"{g_sond} Sondages")
        self.nb.tab(self.pane_diag, text=f"{g_diag} Diagnostic")

    # Liste d'arbres (filtre, Treeview, pastilles d'état, navigation,
    # CRUD ajouter/dupliquer/supprimer/renommer) : cf.
    # `app_arbres.ArbreListMixin`. `_refresh_current_arbre_etat`,
    # `_refresh_tree_arbres` et `_arbre_etat` y vivent aussi.

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

    def on_section_changed(self) -> None:
        """Notifié par `DegradationsPane`/`ContrefortsPane` après une
        mutation live (saisie directe dans leurs grilles). Même contrat
        que `on_sondages_changed` : dirty + redraw debouncé — sans
        re-rafraîchir la grille émettrice (elle est déjà à jour)."""
        self._mark_dirty()
        self._debounced_redraw()

    def on_preconisation_changed(self) -> None:
        """Notifié par `DiagnosticPane` après édition de la préconisation
        (urgence / échéance / texte / suivi). Marque dirty seulement : ces
        champs n'affectent ni le dessin ni la pastille de la liste, et la
        synthèse de mission est recalculée à l'export. On ne déclenche pas de
        redraw (qui re-`refresh`-erait le pane et lutterait contre la frappe)."""
        self._mark_dirty()

    def get_urgences_custom(self) -> "list[str]":
        """Niveaux d'urgence personnalisés persistés dans les réglages."""
        return self._settings.get_urgences_custom()

    def set_urgences_custom(self, values: "list[str]") -> None:
        """Persiste les niveaux d'urgence personnalisés."""
        self._settings.set_urgences_custom(values)
        self._refresh_urgence_filter_choices()

    def _urgence_filter_choices(self) -> "list[str]":
        """Choices du filtre urgence : Toutes + standards + personnalisés + Non renseignée."""
        return ([_URGENCE_FILTER_ALL]
                + list(URGENCE_NIVEAUX)
                + self.get_urgences_custom()
                + [_URGENCE_FILTER_NONE])

    def _refresh_urgence_filter_choices(self) -> None:
        """Met à jour les valeurs du combobox filtre urgence après un changement
        des niveaux personnalisés. No-op si le combobox n'est pas encore construit."""
        if hasattr(self, "_cmb_urgence_filter"):
            self._cmb_urgence_filter.configure(
                values=self._urgence_filter_choices())

    def get_suivi_custom(self) -> "list[str]":
        """Durées de suivi personnalisées persistées dans les réglages."""
        return self._settings.get_suivi_custom()

    def set_suivi_custom(self, values: "list[str]") -> None:
        """Persiste les durées de suivi personnalisées."""
        self._settings.set_suivi_custom(values)

    def capture_undo_snapshot(self) -> dict:
        """Renvoie un snapshot de l'état courant sans l'empiler. Utilisé
        par les éditions live (grilles de saisie) : on capture l'état
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
        # Snapshot AVANT le dialogue : il mute l'objet en place au clic
        # Valider — capturer après reviendrait à empiler l'état déjà
        # modifié (undo sans effet).
        snap = self.capture_undo_snapshot()
        if edit_sondage(self, a, s):
            self.push_undo_snapshot(snap)
            self._refresh_sondages_table()
            self._debounced_redraw()

    def open_edit_degradation(self, d: DegradationExterne) -> None:
        a = self._current_arbre()
        if not a:
            return
        snap = self.capture_undo_snapshot()
        if edit_degradation(self, a, d):
            self.push_undo_snapshot(snap)
            self._refresh_degradations_table()
            self._debounced_redraw()

    def open_edit_contrefort(self, c: Contrefort) -> None:
        a = self._current_arbre()
        if not a:
            return
        snap = self.capture_undo_snapshot()
        if edit_contrefort(self, a, c):
            self.push_undo_snapshot(snap)
            self._refresh_contreforts_table()
            self._debounced_redraw()

    # Actions d'export (action_export_png / _pdf_arbre / _pdf_mission /
    # _csv / _synthesis_{xlsx,csv} / _prbs_{xlsx,html}) : cf.
    # `app_export_actions.ExportActionsMixin`.

    def action_about(self) -> None:
        messagebox.showinfo(
            "À propos",
            f"Pénétromètre — Expertise arboricole\n"
            f"Version {__version__}\n\n"
            "Application desktop Python autonome.\n"
            "Tableau de sondages ↔ dessin synchronisés.\n"
            "Section ronde par interpolation spline.\n\n"
            "Note : « Résistographe » étant une marque déposée,\n"
            "ce logiciel utilise le terme générique « pénétromètre ».")

    def action_shortcuts(self) -> None:
        messagebox.showinfo(
            "Raccourcis clavier",
            "Fichier\n"
            "  Ctrl+N   Nouvelle mission\n"
            "  Ctrl+O   Ouvrir une mission\n"
            "  Ctrl+S   Enregistrer\n"
            "  Ctrl+E   Exporter la fiche PDF de l'arbre courant\n"
            "  Ctrl+P   Imprimer la fiche PDF de l'arbre courant\n"
            "\n"
            "Arbres\n"
            "  Ctrl+T        Ajouter un arbre\n"
            "  Ctrl+PgDown   Arbre suivant\n"
            "  Ctrl+PgUp     Arbre précédent\n"
            "  Double-clic sur un arbre : le renommer\n"
            "  Clic droit sur un arbre : menu d'actions\n"
            "\n"
            "Onglets\n"
            "  Ctrl+Tab      Onglet suivant\n"
            "  Ctrl+Maj+Tab  Onglet précédent\n"
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

    def action_open_backups_folder(self) -> None:
        """Ouvre le dossier des sauvegardes glissantes (copies horodatées
        déposées à chaque enregistrement). Permet de récupérer une version
        antérieure d'une mission écrasée ou corrompue."""
        try:
            _BACKUP_PATH.mkdir(parents=True, exist_ok=True)
        except OSError:
            log.exception("Création du dossier de sauvegardes")
        vide = (not _BACKUP_PATH.is_dir()
                or not any(_BACKUP_PATH.iterdir()))
        if vide:
            messagebox.showinfo(
                "Sauvegardes",
                "Aucune sauvegarde pour l'instant.\n\nUne copie horodatée "
                "de la mission est créée à chaque enregistrement, dans :\n"
                f"{_BACKUP_PATH}")
            return
        self._open_in_system(_BACKUP_PATH)


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
