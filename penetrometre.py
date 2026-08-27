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
import os
import sys
import tkinter as tk
from contextlib import contextmanager
from functools import partial
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Iterator, Optional

from app_arbres import (
    _COMPLET_FILTER_ALL,
    _ECHEANCE_FILTER_ALL,
    _RISK_FILTER_ALL,
    _URGENCE_FILTER_ALL,
    _URGENCE_FILTER_NONE,
    ArbreListMixin,
)
from app_export_actions import ExportActionsMixin
from app_fichier import _BACKUP_PATH, FichierMixin
from app_layout import LayoutMixin
from app_menu import build_menu, refresh_recent_menu
from app_recent import RecentFilesStore
from app_recovery import (
    _RECOVERY_PATH,
    RecoveryMixin,
)
from app_reglages import ReglagesMixin
from app_settings import SettingsStore
from dialogs import (
    ask_date,
    normaliser_date,
)
from dialogs_cepee import ask_cepee_layout
from dialogs_license import show_activation_dialog
from dialogs_saisie import edit_contrefort, edit_degradation, edit_sondage
from dialogs_shared import message_chevauchement
from i18n import _, setup_language, translate_values
from license import (
    LicenseData,
    TrialInfo,
    durcir_config_existante,
    get_trial_info,
    is_bundled,
    load_license,
    masquer_email,
)
from model import (
    URGENCE_NIVEAUX,
    Arbre,
    Brin,
    Chantier,
    Contrefort,
    DegradationExterne,
    Sondage,
    degradations_chevauchements,
)
from palette import (
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_INK,
    COLOR_MUTED,
    COLOR_PANEL,
    COLOR_WARN,
)
from pane_contreforts import ContrefortsPane
from pane_degradations import DegradationsPane
from pane_diagnostic import DiagnosticPane
from pane_sondages import SondagesPane
from persistence import (
    chantier_from_dict,
    chantier_to_dict,
    clear_recovery,
)
from ui_fonts import font as ui_font
from ui_fonts import font_small_bold
from undo import UndoStack

__version__ = "3.6.0"
_SUPPORT_EMAIL = "e.colinet@silvavenir.fr"

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

class App(ArbreListMixin, RecoveryMixin, ExportActionsMixin, FichierMixin,
          LayoutMixin, ReglagesMixin, tk.Tk):

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
        # Langue AVANT la création des widgets (les chaînes sont évaluées
        # à la création — un changement de langue nécessite un redémarrage).
        setup_language(self._settings.language())
        self._apply_bareme()
        self._apply_styles()

        # Vérification de licence — seulement dans le bundle de distribution.
        # En développement (python penetrometre.py), le check est sauté.
        self._license: Optional[LicenseData] = None
        self._trial: Optional[TrialInfo] = None
        if is_bundled():
            self.withdraw()
            _lic: Optional[LicenseData] = load_license()
            if _lic is None:
                # Pas de licence valide : essai actif ?
                _trial_existing = get_trial_info()
                if _trial_existing is not None:
                    self._trial = _trial_existing
                else:
                    # Dialogue d'activation (licence OU démarrage essai)
                    result = show_activation_dialog(self)
                    if isinstance(result, LicenseData):
                        _lic = result
                    elif isinstance(result, TrialInfo):
                        self._trial = result
                    else:
                        self.destroy()
                        sys.exit(0)
            if _lic is None and self._trial is None:
                self.destroy()
                sys.exit(0)
            self.deiconify()
            self._license = _lic
            if _lic is not None:
                # Email masqué : le journal est destiné au support (cf.
                # `license.masquer_email`).
                log.info("Licence valide — %s <%s>", _lic.name,
                         masquer_email(_lic.email))
            elif self._trial is not None:
                log.info("Mode essai — %d jours restants", self._trial.days_remaining)

        self.chantier = Chantier()
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
        # Cache des résultats _arbre_etat(a) indexé par id(a).
        # Peuplé par _refresh_tree_arbres, invalidé pour l'arbre courant
        # par _refresh_current_arbre_etat. Réduit genet_diagnostic de
        # O(N) à O(1) par redraw live (seul l'arbre muté est recalculé).
        self._etat_cache: dict[int, tuple[str, str, str]] = {}
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
        # Vérification des mises à jour en arrière-plan, 3 s après le
        # démarrage (laisse le temps à l'UI de se stabiliser, et évite
        # de bloquer le démarrage si le réseau est lent).
        self.after(3000, self._check_for_update_async)
        # Bannière mode essai — après deiconify pour ne pas flasher en blanc.
        if self._trial is not None:
            self.after(100, lambda: self._show_trial_banner(
                self._trial.days_remaining if self._trial else 0))

    def _show_trial_banner(self, days_remaining: int) -> None:
        """Affiche la bannière d'essai avec le nombre de jours restants."""
        if not hasattr(self, "_trial_banner"):
            return
        self._trial_banner_lbl.configure(
            text=f"Mode essai — {days_remaining} jour(s) restant(s) sur 30"
        )
        if not self._trial_banner.winfo_ismapped():
            self._trial_banner.pack(side="bottom", fill="x")

    def _action_activate_from_trial(self) -> None:
        """Ouvre le dialogue d'activation depuis la bannière essai."""
        from dialogs_license import show_activation_dialog
        result = show_activation_dialog(self)
        if isinstance(result, LicenseData):
            self._license = result
            self._trial = None
            if hasattr(self, "_trial_banner"):
                self._trial_banner.pack_forget()
            log.info("Licence activée depuis mode essai — %s <%s>",
                     result.name, masquer_email(result.email))
            self.set_status(f"✓ Licence activée — {result.name}")

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
                _("Erreur"), f"Impossible d'ouvrir :\n{path}\n\n{e}")

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
                text=_("● Modifications non enregistrées"),
                foreground=COLOR_WARN)
            self._btn_save.configure(state="normal")
        elif self.current_file is not None:
            self.lbl_save_state.configure(
                text=_("✓ Enregistré"), foreground=COLOR_ACCENT)
            self._btn_save.configure(state="disabled")
        else:
            # Mission neuve jamais enregistrée : rien à perdre, mais le
            # bouton reste actif (premier « Enregistrer sous… »).
            self.lbl_save_state.configure(
                text=_("Mission non enregistrée"), foreground=COLOR_MUTED)
            self._btn_save.configure(state="normal")

    def _on_close(self) -> None:
        if self._dirty:
            if not messagebox.askyesno(
                    _("Quitter"),
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
        if not self._undo_stack.can_undo:
            return
        # set_live_tip est idempotent (no-op si déjà positionné).
        # On aligne le type du live_tip sur le type du snapshot qu'on va
        # annuler : si c'est un snapshot arbre scopé, on capture seulement
        # l'arbre concerné (deepcopy rapide) ; sinon chantier complet (JSON).
        top = self._undo_stack.peek_top()
        if isinstance(top, dict) and top.get("_type") == "arbre":
            idx = top["_idx"]
            if 0 <= idx < len(self.chantier.arbres):
                live: Any = {"_type": "arbre", "_idx": idx,
                             "_arbre": copy.deepcopy(self.chantier.arbres[idx])}
            else:
                live = chantier_to_dict(self.chantier)
        else:
            live = chantier_to_dict(self.chantier)
        self._undo_stack.set_live_tip(live)
        snapshot = self._undo_stack.undo()
        if snapshot is None:
            return
        self._restore_snapshot(snapshot)

    def _perform_redo(self) -> None:
        snapshot = self._undo_stack.redo()
        if snapshot is None:
            return
        self._restore_snapshot(snapshot)

    def _restore_snapshot(self, snapshot: Any) -> None:
        if isinstance(snapshot, dict) and snapshot.get("_type") == "arbre":
            # Snapshot arbre scopé : on ne touche qu'à un seul arbre dans la
            # liste — le reste du chantier (méta, autres arbres) est inchangé.
            idx: int = snapshot["_idx"]
            if 0 <= idx < len(self.chantier.arbres):
                self.chantier.arbres[idx] = snapshot["_arbre"]
            # _refresh_tree_arbres vide le cache et le repeuple.
            self._refresh_tree_arbres()
            if idx == self.current_idx:
                self._load_arbre_to_ui()
            return
        # Snapshot chantier complet (mutations globales : add/delete arbre,
        # méta chantier, ou live_tip du premier undo d'une séquence mixte).
        self.chantier = chantier_from_dict(snapshot)
        if not self.chantier.arbres:
            self.chantier.arbres.append(Arbre(numero_arbre="1"))
        self.current_idx = min(self.current_idx,
                               len(self.chantier.arbres) - 1)
        with self._suspend_sync_block():
            self.var_ch_nom.set(self.chantier.nom)
            self.var_ch_adr.set(self.chantier.adresse)
            self.var_ch_client.set(self.chantier.client)
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
            f"{self.var_ch_client.get()}|"
            f"{self.var_ch_ope.get()}|{self.var_ch_date.get()}")

    def _meta_focus_out(self) -> None:
        current = (
            f"{self.var_ch_nom.get()}|{self.var_ch_adr.get()}|"
            f"{self.var_ch_client.get()}|"
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
        self.chantier.client = self.var_ch_client.get()
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

    def _refresh_welcome_visibility(self) -> None:
        """Bascule entre l'écran de bienvenue et le notebook selon qu'il
        existe ou non des arbres dans la mission courante."""
        wf = getattr(self, "_welcome_frame", None)
        if wf is None:
            return
        has = bool(self.chantier.arbres)
        if has:
            if wf.winfo_ismapped():
                wf.pack_forget()
            if not self.nb.winfo_ismapped():
                self.nb.pack(fill="both", expand=True)
        else:
            if self.nb.winfo_ismapped():
                self.nb.pack_forget()
            if not wf.winfo_ismapped():
                wf.pack(fill="both", expand=True)

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
        # Accent visuel quand le brin sélectionné n'est pas le premier :
        # le libellé « Brin : » passe en vert pour signaler qu'on n'est
        # pas sur le brin par défaut, évitant de saisir sur le mauvais brin.
        lbl = getattr(self, "_brin_bar_lbl", None)
        if lbl is not None:
            non_default = self._current_brin_idx > 0
            lbl.configure(foreground=COLOR_ACCENT if non_default else "")
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
        """Réinitialise tous les filtres de la liste d'arbres en une action."""
        self.var_risk_filter.set(_(_RISK_FILTER_ALL))
        self.var_urgence_filter.set(_(_URGENCE_FILTER_ALL))
        if hasattr(self, "var_echeance_filter"):
            self.var_echeance_filter.set(_(_ECHEANCE_FILTER_ALL))
        if hasattr(self, "var_complet_filter"):
            self.var_complet_filter.set(_(_COMPLET_FILTER_ALL))
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
        return ([_(_URGENCE_FILTER_ALL)]
                + translate_values(list(URGENCE_NIVEAUX))
                + self.get_urgences_custom()
                + [_(_URGENCE_FILTER_NONE)])

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

    def capture_undo_snapshot(self) -> Any:
        """Renvoie un snapshot de l'état courant sans l'empiler. Utilisé
        par les éditions live (grilles de saisie) : on capture l'état
        AVANT édition au focus-in, on ne l'empile (`push_undo_snapshot`)
        qu'au focus-out si la valeur a réellement changé.

        Quand un arbre courant existe, renvoie un snapshot arbre scopé
        (deepcopy de l'arbre seul) — beaucoup plus léger que la
        sérialisation JSON complète du chantier.
        """
        a = self._current_arbre()
        if a is None:
            return chantier_to_dict(self.chantier)
        return {"_type": "arbre", "_idx": self.current_idx,
                "_arbre": copy.deepcopy(a)}

    def push_undo_snapshot(self, snapshot: Any) -> None:
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

    def open_add_degradation(self, grade_debut: int, grade_fin: int) -> None:
        """Crée une dégradation externe sur l'arc debut→fin (glissé canvas).
        Vérifie l'absence de chevauchement, bascule vers l'onglet Dégradations
        et pose le focus sur la profondeur de la nouvelle ligne."""
        b = self._current_brin()
        if not b:
            return
        conflicts = degradations_chevauchements(
            b.degradations_externes, None, grade_debut, grade_fin)
        if conflicts:
            other, shared = conflicts[0]
            messagebox.showwarning(
                "Chevauchement",
                message_chevauchement(other, shared),
                parent=self,
            )
            return
        self.push_undo()
        deg = DegradationExterne(
            numero=len(b.degradations_externes) + 1,
            grade_debut=grade_debut, grade_fin=grade_fin,
            profondeur_cm=2.0,
        )
        b.degradations_externes.append(deg)
        b.renumeroter_degradations()
        self._refresh_degradations_table()
        self._debounced_redraw()
        if self.pane_de is not None:
            self.nb.select(self.pane_de)
            self.after(50, self.pane_de.focus_last_row)

    # Actions d'export (action_export_png / _pdf_arbre / _pdf_mission /
    # _csv / _synthesis_{xlsx,csv} / _prbs_{xlsx,html}) : cf.
    # `app_export_actions.ExportActionsMixin`.

    def action_about(self) -> None:
        dlg = tk.Toplevel(self)
        dlg.title("À propos d'Pénétromètre")
        dlg.resizable(False, False)
        dlg.configure(bg=COLOR_BG)
        frm = ttk.Frame(dlg, padding=24)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm,
                  text="Pénétromètre",
                  font=ui_font("Georgia", 16, "bold")).pack(anchor="w")
        ttk.Label(frm,
                  text=_("Expertise arboricole au pénétromètre"),
                  style="Sub.TLabel").pack(anchor="w")
        ttk.Separator(frm, orient="horizontal").pack(fill="x", pady=10)

        from license import get_machine_id
        if self._license:
            lic_titulaire = self._license.name
            if self._license.expires:
                lic_expiration = self._license.expires.strftime("%d/%m/%Y")
            else:
                lic_expiration = "Illimitée"
            lic_machine = self._license.machine_id or "toutes machines"
            lic_mode = "Licence active"
        elif self._trial:
            lic_titulaire = "Mode essai"
            lic_expiration = f"{self._trial.days_remaining} jour(s) restant(s)"
            lic_machine = get_machine_id()
            lic_mode = "Essai gratuit 30 jours"
        else:
            lic_titulaire = "Mode développement"
            lic_expiration = "—"
            lic_machine = get_machine_id()
            lic_mode = "Développement (non bundlé)"

        infos = [
            ("Version",        __version__),
            ("Auteur",         "Edwin Colinet"),
            ("Licence",        lic_mode),
            ("Titulaire",      lic_titulaire),
            ("Expiration",     lic_expiration),
            ("Machine ID",     lic_machine),
        ]
        for lbl, val in infos:
            row = ttk.Frame(frm)
            row.pack(fill="x", pady=1)
            ttk.Label(row, text=f"{lbl} :",
                      width=10, anchor="e",
                      style="Muted.TLabel").pack(side="left", padx=(0, 8))
            ttk.Label(row, text=val).pack(side="left")

        ttk.Label(frm,
                  text="\nNote : « Résistographe » est une marque déposée.\n"
                       "Ce logiciel utilise le terme générique « pénétromètre ».",
                  wraplength=360, style="Muted.TLabel",
                  justify="left").pack(anchor="w", pady=(8, 0))

        ttk.Separator(frm, orient="horizontal").pack(fill="x", pady=10)

        btns = ttk.Frame(frm)
        btns.pack(fill="x")

        def _open_doc(name: str) -> None:
            doc = Path(__file__).parent / name
            if doc.exists():
                import subprocess
                import sys
                if sys.platform == "win32":
                    os.startfile(str(doc))
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(doc)])
                else:
                    subprocess.Popen(["xdg-open", str(doc)])
            else:
                messagebox.showwarning(
                    _("Fichier introuvable"),
                    f"{name} est absent de l'installation.",
                    parent=dlg)

        ttk.Button(btns, text=_("Licence (CLU)"),
                   style="Ghost.TButton",
                   command=lambda: _open_doc("LICENSE")).pack(side="left")
        ttk.Button(btns, text=_("Confidentialité"),
                   style="Ghost.TButton",
                   command=lambda: _open_doc("PRIVACY.md")).pack(side="left",
                                                                  padx=(6, 0))
        ttk.Button(btns, text=_("Fermer"),
                   style="Accent.TButton",
                   command=dlg.destroy).pack(side="right")

        dlg.bind("<Escape>", lambda e: dlg.destroy())
        from dialogs import _make_modal
        _make_modal(dlg, self)

    def action_shortcuts(self) -> None:
        # Aide-mémoire des raccourcis. Mise en forme « pro » : dialogue
        # thématisé avec touches dessinées en keycaps plutôt qu'un
        # messagebox monospace. Les libellés restent en français brut
        # (comme l'ancien corps non traduit) ; seuls le titre et le
        # bouton passent par _() (clés déjà au catalogue).
        # Données : liste de (titre de section, [(touches, description)]).
        # `touches` = liste de jetons rendus en keycaps joints par « + ».
        colonne_gauche = [
            ("Fichier", [
                (["Ctrl", "N"], "Nouvelle mission"),
                (["Ctrl", "O"], "Ouvrir une mission"),
                (["Ctrl", "S"], "Enregistrer"),
                (["Ctrl", "E"], "Exporter la fiche PDF (arbre courant)"),
                (["Ctrl", "P"], "Imprimer la fiche PDF (arbre courant)"),
            ]),
            ("Arbres", [
                (["Ctrl", "T"], "Ajouter un arbre vierge"),
                (["Ctrl", "Maj", "T"], "Hériter du précédent (Ø, essence…)"),
                (["Ctrl", "Pg.Suiv"], "Arbre suivant"),
                (["Ctrl", "Pg.Préc"], "Arbre précédent"),
                (["Échap"], "Vider le filtre de recherche"),
            ]),
        ]
        colonne_droite = [
            ("Onglets", [
                (["Ctrl", "Tab"], "Onglet suivant"),
                (["Ctrl", "Maj", "Tab"], "Onglet précédent"),
            ]),
            ("Édition", [
                (["Ctrl", "Z"], "Annuler"),
                (["Ctrl", "Y"], "Rétablir"),
                (["Ctrl", "Maj", "Z"], "Rétablir (variante)"),
            ]),
            ("Souris", [
                (["Double-clic"], "Sur un arbre : le renommer"),
                (["Clic droit"], "Sur un arbre : menu (dupliquer…)"),
                (["Clic"], "Sur le dessin : ajouter / éditer un sondage"),
            ]),
        ]

        dlg = tk.Toplevel(self)
        dlg.title(_("Raccourcis clavier"))
        dlg.resizable(False, False)
        dlg.configure(bg=COLOR_BG)
        frm = ttk.Frame(dlg, padding=24)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text=_("Raccourcis clavier"),
                  font=ui_font("Georgia", 16, "bold")).pack(anchor="w")
        ttk.Label(frm,
                  text="Aide-mémoire des commandes clavier et souris",
                  style="Sub.TLabel").pack(anchor="w")
        ttk.Separator(frm, orient="horizontal").pack(fill="x", pady=(10, 12))

        def _keycap(parent: tk.Misc, texte: str) -> tk.Label:
            """Une touche dessinée façon « capuchon de clavier »."""
            return tk.Label(parent, text=texte,
                            font=ui_font("DejaVu Sans Mono", 9, "bold"),
                            bg=COLOR_PANEL, fg=COLOR_INK,
                            relief="solid", borderwidth=1,
                            padx=6, pady=1)

        def _render_section(parent: tk.Misc, titre: str,
                            lignes: list) -> None:
            ttk.Label(parent, text=titre.upper(),
                      font=font_small_bold(),
                      foreground=COLOR_ACCENT).grid(
                          sticky="w", pady=(10, 4), columnspan=2)
            grille = ttk.Frame(parent)
            grille.grid(sticky="w", columnspan=2)
            grille.columnconfigure(0, minsize=132)
            for r, (touches, desc) in enumerate(lignes):
                cell = ttk.Frame(grille)
                cell.grid(row=r, column=0, sticky="w", pady=2)
                for i, tok in enumerate(touches):
                    if i:
                        ttk.Label(cell, text="+",
                                  foreground=COLOR_MUTED).pack(
                                      side="left", padx=2)
                    _keycap(cell, tok).pack(side="left")
                ttk.Label(grille, text=desc).grid(
                    row=r, column=1, sticky="w", padx=(10, 0))

        cols = ttk.Frame(frm)
        cols.pack(fill="both", expand=True)
        gauche = ttk.Frame(cols)
        gauche.pack(side="left", anchor="n", padx=(0, 28))
        droite = ttk.Frame(cols)
        droite.pack(side="left", anchor="n")
        for titre, lignes in colonne_gauche:
            _render_section(gauche, titre, lignes)
        for titre, lignes in colonne_droite:
            _render_section(droite, titre, lignes)

        ttk.Separator(frm, orient="horizontal").pack(fill="x", pady=(14, 10))
        ttk.Button(frm, text=_("Fermer"), style="Accent.TButton",
                   command=dlg.destroy).pack(side="right")

        dlg.bind("<Escape>", lambda e: dlg.destroy())
        from dialogs import _make_modal
        _make_modal(dlg, self)

    def action_open_guide(self) -> None:
        """Ouvre le guide de démarrage rapide (HTML) dans le navigateur."""
        guide = Path(__file__).parent / "docs" / "guide_demarrage.html"
        if not guide.exists():
            messagebox.showinfo(
                _("Guide de démarrage"),
                _("Guide introuvable : {p}").format(p=guide))
            return
        self._open_in_system(guide)

    def action_contact_support(self) -> None:
        """Dialogue de support : contact, Machine ID, lien vers le log."""
        from license import get_machine_id
        machine_id = get_machine_id()
        log_path = Path.home() / ".penetrometre" / "penetrometre.log"

        dlg = tk.Toplevel(self)
        dlg.title(_("Contacter le support"))
        dlg.resizable(False, False)
        dlg.configure(bg=COLOR_BG)
        frm = ttk.Frame(dlg, padding=22)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text=_("Contacter le support"),
                  font=ui_font("Helvetica", 13, "bold"),
                  foreground=COLOR_ACCENT).pack(anchor="w")
        ttk.Separator(frm).pack(fill="x", pady=(8, 12))

        def _row(label: str, value: str, copy: bool = False) -> None:
            r = ttk.Frame(frm)
            r.pack(fill="x", pady=2)
            ttk.Label(r, text=f"{label} :", width=16, anchor="e",
                      style="Muted.TLabel").pack(side="left", padx=(0, 8))
            if copy:
                ttk.Label(r, text=value,
                          font=("Courier", 10)).pack(side="left")
            else:
                ttk.Label(r, text=value).pack(side="left")
            if copy:
                def _copy(v: str = value) -> None:
                    dlg.clipboard_clear()
                    dlg.clipboard_append(v)
                ttk.Button(r, text=_("Copier"), width=7,
                           command=_copy).pack(side="left", padx=(8, 0))

        _row(_("Email"), _SUPPORT_EMAIL, copy=True)
        _row(_("Machine ID"), machine_id, copy=True)

        _row(_("Version"), __version__)

        ttk.Separator(frm).pack(fill="x", pady=(12, 8))
        ttk.Label(frm,
                  text=_("Pour tout signalement, joignez le fichier de log "
                          "à votre message."),
                  foreground=COLOR_MUTED, wraplength=360,
                  justify="left").pack(anchor="w")

        frm_btn = ttk.Frame(frm)
        frm_btn.pack(fill="x", pady=(10, 0))

        def _open_log() -> None:
            if log_path.exists():
                self._open_in_system(log_path)
            else:
                messagebox.showinfo(
                    _("Fichier de log"),
                    _("Aucun fichier de log trouvé à :\n{p}").format(p=log_path),
                    parent=dlg)

        def _open_mail() -> None:
            import urllib.parse
            import webbrowser
            subject = urllib.parse.quote(f"Support Pénétromètre {__version__}")
            body = urllib.parse.quote(
                f"Machine ID : {machine_id}\nVersion : {__version__}\n\n"
                f"[Décrivez votre problème ici]")
            webbrowser.open(f"mailto:{_SUPPORT_EMAIL}?subject={subject}&body={body}")

        ttk.Button(frm_btn, text=_("Ouvrir le log"),
                   command=_open_log).pack(side="left")
        ttk.Button(frm_btn, text=_("Envoyer un email"),
                   style="Accent.TButton",
                   command=_open_mail).pack(side="left", padx=(8, 0))
        ttk.Button(frm_btn, text=_("Fermer"),
                   command=dlg.destroy).pack(side="right")

        from dialogs import _make_modal
        _make_modal(dlg, self)

    def action_open_log(self) -> None:
        """Ouvre le fichier de log de l'application avec l'éditeur par
        défaut du système. Utile quand un utilisateur cherche à
        comprendre une erreur ou à transmettre le log à un développeur."""
        log_path = Path.home() / ".penetrometre" / "penetrometre.log"
        if not log_path.exists():
            messagebox.showinfo(
                _("Fichier de log"),
                _("Aucun fichier de log trouvé à :\n{p}").format(p=log_path))
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
                _("Sauvegardes"),
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
    # Rattrape les installations antérieures au durcissement : dossier de
    # config en 0700, licence/essai/repère en 0600. Ici plutôt que dans la
    # branche licence, pour que le parc se corrige à TOUS les lancements —
    # y compris en mode essai et en développement.
    durcir_config_existante()
    try:
        App().mainloop()
    except Exception:
        log.exception("Crash non rattrapé dans la boucle principale")
        raise
    finally:
        log.info("Arrêt Pénétromètre — log: %s", log_path)


if __name__ == "__main__":
    main()
