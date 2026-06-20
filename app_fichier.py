"""
Cycle de vie des fichiers de mission (mixin de `App`).

Regroupe tout ce qui touche au **fichier mission** (`.json`) : créer une
mission vierge, ouvrir (boîte de dialogue, chemin direct, récents),
enregistrer (+ sauvegarde glissante), enregistrer sous — ainsi que la
**ré-inspection** (charger une mission de référence, comparer l'arbre
courant, exporter la page de comparaison), qui consiste elle aussi à
manipuler des fichiers de mission.

Extrait de `penetrometre.py` (qui restait le fichier le plus volumineux
du projet) sur le même **partitionnement par responsabilité** que
`ArbreListMixin` / `RecoveryMixin` / `ExportActionsMixin` : le mixin lit
et **mute** l'état d'`App` (`chantier`, `current_idx`, `current_file`,
`_dirty`, `_reference_chantier`, …) ; le couplage est assumé et
documenté (greppable) par le bloc `TYPE_CHECKING` ci-dessous.

Ce module fournit aussi la constante `_BACKUP_PATH` (dossier des
sauvegardes glissantes), partagée avec `penetrometre.py` qui l'ouvre
depuis le menu (`action_open_backups_folder`) — comme `app_recovery`
fournit `_RECOVERY_PATH`.
"""

from __future__ import annotations

import logging
import tkinter as tk
from contextlib import AbstractContextManager
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import TYPE_CHECKING, Any, Callable, Optional

from app_arbres import _RISK_FILTER_ALL
from app_recent import RecentFilesStore
from app_recovery import _RECOVERY_PATH
from comparaison import open_comparison
from i18n import _
from model import Arbre, Chantier
from palette import COULEUR_CLASSE
from persistence import clear_recovery, load_chantier, save_chantier, write_backup
from undo import UndoStack

log = logging.getLogger("penetrometre")

# Astuce typage des mixins : au runtime la base est `object` (aucun
# couplage, MRO propre dans `App`), mais pour mypy on la fait dériver de
# `tk.Tk` afin que `self` soit vu comme un widget. Les attributs/méthodes
# propres à `App` restent déclarés dans le bloc `TYPE_CHECKING` ci-dessous.
if TYPE_CHECKING:
    _MixinBase = tk.Tk
else:
    _MixinBase = object

# Copies horodatées des missions à chaque enregistrement (anti-écrasement).
# Vit ici (responsabilité « enregistrement ») et est réimportée par
# `penetrometre.py` pour l'entrée de menu « Ouvrir le dossier des
# sauvegardes… », comme `_RECOVERY_PATH` vit dans `app_recovery`.
_BACKUP_PATH = Path.home() / ".penetrometre" / "backups"


class FichierMixin(_MixinBase):
    """Nouvelle / Ouvrir / Enregistrer / Enregistrer sous + récents +
    ré-inspection. Mixin de `App` : compte sur les attributs/méthodes
    propres à `App` déclarés ci-dessous."""

    if TYPE_CHECKING:
        # Fournis par App (déclarés pour le type-check du mixin).
        chantier: Chantier
        current_idx: int
        current_file: Optional[Path]
        _dirty: bool
        _reference_chantier: Optional[Chantier]
        _recent: RecentFilesStore
        _undo_stack: UndoStack
        _settings: "Any"    # SettingsStore (import circulaire évité)
        _ope_cmb: "Any"     # ttk.Combobox opérateur
        var_ch_nom: tk.StringVar
        var_ch_adr: tk.StringVar
        var_ch_ope: tk.StringVar
        var_ch_date: tk.StringVar
        var_filter: tk.StringVar
        var_risk_filter: tk.StringVar
        var_show_sondages: tk.BooleanVar

        def _suspend_sync_block(self) -> AbstractContextManager[None]: ...
        def _refresh_tree_arbres(self) -> None: ...
        def _load_arbre_to_ui(self) -> None: ...
        def _clear_filter_if_set(self) -> None: ...
        def _update_title(self) -> None: ...
        def _current_arbre(self) -> Optional[Arbre]: ...
        def set_status(self, text: str) -> None: ...
        def notify_export(self, path: str, label: str) -> None: ...

    def action_new(self) -> None:
        if self._dirty:
            if not messagebox.askyesno(
                    _("Nouvelle mission"),
                    _("Des modifications n'ont pas été enregistrées.\nContinuer quand même ?")):
                return
        self._undo_stack.clear()
        self._dirty = False
        clear_recovery(_RECOVERY_PATH)
        self.chantier = Chantier()
        self.chantier.arbres.append(Arbre(numero_arbre="1"))
        self.current_idx = 0
        self.current_file = None
        # Pré-remplir l'opérateur avec le dernier nom utilisé (évite
        # de le retaper à chaque nouvelle mission).
        last_ope = (self._settings.get_operateurs_history() or [""])[0]
        with self._suspend_sync_block():
            self.var_ch_nom.set(self.chantier.nom)
            self.var_ch_adr.set("")
            self.var_ch_ope.set(last_ope)
            self.var_ch_date.set(self.chantier.date_releve)
        self.chantier.operateur = last_ope
        self.var_filter.set("")  # nouvelle mission → filtres remis à zéro
        self.var_risk_filter.set(_RISK_FILTER_ALL)
        self._refresh_tree_arbres()
        self._load_arbre_to_ui()
        self._update_title()

    def action_open(self) -> None:
        if self._dirty:
            if not messagebox.askyesno(
                    _("Ouvrir"),
                    _("Des modifications n'ont pas été enregistrées.\nContinuer quand même ?")):
                return
        p = filedialog.askopenfilename(
            title=_("Ouvrir une mission"),
            filetypes=[("Mission Pénétromètre", "*.json"),
                       ("Tous", "*.*")])
        if not p:
            return
        self._open_path(p)

    def action_import_csv(self) -> None:
        """Importe des arbres/sondages depuis un fichier CSV.

        Ouvre un dialog de mapping colonnes → champs modèle, puis ajoute
        les arbres importés à la mission courante. La mission n'est pas
        enregistrée automatiquement (le flag _dirty est levé)."""
        p = filedialog.askopenfilename(
            title=_("Importer depuis CSV"),
            filetypes=[("Fichiers CSV", "*.csv *.txt"),
                       ("Tous", "*.*")])
        if not p:
            return
        from dialogs_import import ask_csv_import
        arbres = ask_csv_import(self, p)
        if arbres is None:
            return   # annulé
        self.push_undo()
        debut = len(self.chantier.arbres)
        self.chantier.arbres.extend(arbres)
        # Sélectionner le premier arbre importé
        self.current_idx = debut
        self._clear_filter_if_set()
        self._refresh_tree_arbres()
        self._load_arbre_to_ui()
        n_sond = sum(len(a.brins[0].sondages) for a in arbres)
        self.set_status(
            f"{len(arbres)} arbre(s) importé(s) "
            f"({n_sond} sondage(s)) — pensez à enregistrer.")

    def action_open_demo(self) -> None:
        """Ouvre la mission d'exemple en lecture seule.

        La mission illustre les 5 cas types : arbre sain (Vert), arbre
        dégradé (Orange), arbre urgent (Rouge + dégradation externe),
        arbre partiellement sondé (non fiable), et cépée 2 brins.

        « Lecture seule » = current_file reste None → « Enregistrer »
        force « Enregistrer sous… » (jamais d'écrasement du fichier
        d'exemple)."""
        demo = Path(__file__).parent / "exemples" / "mission_demo.json"
        if not demo.exists():
            messagebox.showerror(
                _("Mission d'exemple introuvable"),
                f"Le fichier d'exemple est absent :\n{demo}\n\n"
                "Réinstallez l'application pour le restaurer.")
            return
        if self._dirty:
            if not messagebox.askyesno(
                    _("Ouvrir"),
                    _("Des modifications n'ont pas été enregistrées.\nContinuer quand même ?")):
                return
        try:
            self._undo_stack.clear()
            self._dirty = False
            clear_recovery(_RECOVERY_PATH)
            self.chantier = load_chantier(str(demo))
            self.current_file = None   # lecture seule : Enregistrer → Enregistrer sous…
            self._install_chantier_ui()
            # Pas de push_recent : le fichier d'exemple n'est pas une vraie mission.
            self.set_status(
                "Mission d'exemple ouverte en lecture seule. "
                "Utilisez « Enregistrer sous… » pour créer votre propre mission.")
        except Exception as e:
            log.exception("Échec ouverture mission d'exemple")
            messagebox.showerror(_("Erreur"), str(e))

    def action_load_reference(self) -> bool:
        """Charge en mémoire une mission de référence (campagne antérieure)
        pour la comparaison inter-missions. Par session : rien n'est écrit
        dans la mission courante. Renvoie True si chargée."""
        p = filedialog.askopenfilename(
            title=_("Choisir la mission de référence (campagne antérieure)"),
            filetypes=[("Mission Pénétromètre", "*.json"), ("Tous", "*.*")])
        if not p:
            return False
        try:
            self._reference_chantier = load_chantier(p)
        except Exception as e:
            log.exception("Échec chargement mission de référence")
            messagebox.showerror("Erreur", str(e))
            return False
        n = len(self._reference_chantier.arbres)
        self.set_status(f"Mission de référence chargée — {Path(p).name} "
                        f"({n} arbre(s)). « Comparer l'arbre courant… »")
        self._update_compare_state()
        return True

    def action_reinspection(self) -> None:
        """« Faire une comparaison » (ré-inspection) : charge une mission
        antérieure comme **base de travail** (on ré-mesure au lieu de tout
        ressaisir) ET la **fige comme référence** dans le même geste.

        Trois garde-fous, conformes au protocole de ré-inspection :
        - la **date de relevé** est redemandée (campagne nouvelle ; aujourd'hui
          par défaut) — sinon `annees=0` rendrait la comparaison absurde ;
        - le **lien fichier est détaché** (`current_file=None`) → « Enregistrer »
          forcera un « Enregistrer sous… », pour ne JAMAIS écraser la mission
          de référence ;
        - la référence est un **instantané pris avant toute édition**
          (`deepcopy`), donc figée pendant qu'on met à jour diamètres/sondages.
        """
        import copy
        from datetime import datetime

        from dialogs import ask_date

        if self._dirty:
            if not messagebox.askyesno(
                    "Faire une comparaison",
                    "Des modifications n'ont pas été enregistrées.\n"
                    "Continuer quand même ?"):
                return
        p = filedialog.askopenfilename(
            title="Mission antérieure à ré-inspecter (servira de référence)",
            filetypes=[("Mission Pénétromètre", "*.json"), ("Tous", "*.*")])
        if not p:
            return
        try:
            loaded = load_chantier(p)
        except Exception as e:
            log.exception("Échec chargement pour ré-inspection")
            messagebox.showerror("Erreur", str(e))
            return
        # Nouvelle date de relevé (aujourd'hui par défaut). Annulé → on
        # abandonne ; effacé → on retombe sur aujourd'hui (une date est
        # indispensable au calcul du taux d'évolution).
        today = datetime.now().strftime("%d/%m/%Y")
        new_date = ask_date(self, today)
        if new_date is None:
            return
        if not new_date:
            new_date = today

        # Référence = instantané figé AVANT toute édition (garde l'ancienne
        # date, donc l'intervalle « annees » est correct).
        self._reference_chantier = copy.deepcopy(loaded)
        ref_date = self._reference_chantier.date_releve or "?"

        self._undo_stack.clear()
        clear_recovery(_RECOVERY_PATH)
        self.chantier = loaded
        self.chantier.date_releve = new_date
        self.current_file = None          # détaché → Enregistrer sous… forcé
        self._dirty = True
        self._install_chantier_ui()
        self._update_compare_state()
        n = len(self.chantier.arbres)
        self.set_status(
            f"Ré-inspection : « {Path(p).name} » chargée comme base "
            f"({n} arbre(s) ; réf. du {ref_date} → courant du {new_date}). "
            "Mettez à jour les diamètres et sondages, puis « Diagnostic de "
            "la comparaison ».")

    def action_compare_arbre(self) -> None:
        """Ouvre la fenêtre « Diagnostic de la comparaison » : l'arbre courant
        confronté à son homologue de la mission de référence (figée par
        `action_reinspection`). Disponible seulement après un clic sur
        « Faire une comparaison… » — bouton et menu désactivés sinon."""
        ref = self._reference_chantier
        a = self._current_arbre()
        if ref is None or a is None:
            return
        open_comparison(self, self.chantier, ref,
                        default_arbre=a,
                        cur_date=self.chantier.date_releve,
                        couleur_classe=COULEUR_CLASSE,
                        export_cb=self._export_comparison,
                        show_sondages=self.var_show_sondages.get())

    def _export_comparison(self, fmt: str, builder: Callable[[], Any],
                           parent: "tk.Misc") -> None:
        """Enregistre la comparaison (PNG ou PDF) construite par `builder`
        (appelé par les boutons d'export de la fenêtre). `builder()` renvoie
        une **liste de pages** (une par brin pour une cépée). `parent` = la
        fenêtre de comparaison : on y ancre le filedialog pour qu'il s'ouvre
        AU PREMIER PLAN (sinon il passe derrière la fenêtre)."""
        from comparaison_render import save_comparison_pdf, save_comparison_png
        ext = ".pdf" if fmt == "pdf" else ".png"
        typ = "PDF" if fmt == "pdf" else "Image PNG"
        p = filedialog.asksaveasfilename(
            parent=parent, defaultextension=ext,
            filetypes=[(typ, f"*{ext}"), ("Tous", "*.*")])
        if not p:
            return
        try:
            pages = builder()
            if fmt == "pdf":
                save_comparison_pdf(pages, p)
            else:
                save_comparison_png(pages, p)
            self.notify_export(p, "Comparaison d'inspections")
        except Exception as e:
            log.exception("Échec export comparaison")
            messagebox.showerror("Erreur", str(e))

    def _install_chantier_ui(self) -> None:
        """Recharge toute l'UI depuis `self.chantier` (méta, liste d'arbres,
        onglets, filtres remis à zéro). Mutualisé entre l'ouverture de fichier
        et la ré-inspection. NE touche PAS `current_file` / `_dirty` / récents
        — câblés par l'appelant selon le contexte (ouverture vs ré-inspection)."""
        if not self.chantier.arbres:
            self.chantier.arbres.append(Arbre())
        self.current_idx = 0
        with self._suspend_sync_block():
            self.var_ch_nom.set(self.chantier.nom)
            self.var_ch_adr.set(self.chantier.adresse)
            self.var_ch_ope.set(self.chantier.operateur)
            self.var_ch_date.set(self.chantier.date_releve)
        self.var_filter.set("")  # mission rechargée → filtres remis à zéro
        self.var_risk_filter.set(_RISK_FILTER_ALL)
        self._refresh_tree_arbres()
        self._load_arbre_to_ui()
        self._update_title()

    def _open_path(self, p: str) -> None:
        """Ouvre un fichier de mission par son chemin (factorise
        `action_open` et `action_open_recent`). Pousse le chemin dans
        l'historique des récents même en cas de succès."""
        try:
            self._undo_stack.clear()
            self._dirty = False
            clear_recovery(_RECOVERY_PATH)
            self.chantier = load_chantier(p)
            self.current_file = Path(p)
            self._install_chantier_ui()
            self._recent.push(p)
        except FileNotFoundError:
            messagebox.showerror(
                "Fichier introuvable",
                f"Le fichier suivant n'existe plus :\n{p}\n\n"
                "Il a été retiré de la liste des fichiers récents.")
            self._recent.remove(p)
        except Exception as e:
            log.exception("Échec ouverture mission")
            messagebox.showerror(_("Erreur d'ouverture"), str(e))

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
        """Lecture pure pour `refresh_recent_menu` (délègue au store)."""
        return self._recent.get()

    # Le chargement / la persistance / la déduplication de l'historique
    # vivent dans `app_recent.RecentFilesStore` (`self._recent`) ; les
    # sites d'ouverture/enregistrement appellent `self._recent.push` /
    # `self._recent.remove`, qui rafraîchissent le sous-menu via le
    # callback `on_change` câblé dans `__init__`.

    def action_save(self) -> None:
        if not self.current_file:
            return self.action_save_as()
        try:
            save_chantier(self.chantier, self.current_file)
            self._dirty = False
            self._update_title()
            self._recent.push(str(self.current_file))
            # Mémoriser l'opérateur pour le pré-remplissage des prochaines
            # missions (combobox Opérateur dans l'en-tête).
            if self.chantier.operateur.strip():
                self._settings.push_operateur(self.chantier.operateur)
                if hasattr(self, "_ope_cmb"):
                    self._ope_cmb.configure(
                        values=self._settings.get_operateurs_history())
            # Le fichier réel est à jour → l'autosave n'a plus de raison
            # d'être ; on l'efface pour ne pas proposer une reprise inutile.
            clear_recovery(_RECOVERY_PATH)
            # Sauvegarde glissante (best-effort) : copie horodatée pour
            # survivre à un écrasement ou une corruption ultérieurs.
            write_backup(self.current_file, _BACKUP_PATH)
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
