"""
Autosave anti-crash + récupération de session (mixin de `App`).

Tick `after` périodique qui n'écrit `~/.penetrometre/recovery/
autosave.json` **que si la mission a des modifications non
enregistrées** (`_dirty`). Le fichier enveloppe le chantier sérialisé +
des métadonnées (`saved_at`, `original_file`).

**Invariant clé** : l'autosave est effacé dès qu'on atteint un état
propre (enregistrement, nouvelle mission, ouverture) et à la fermeture
normale — donc sa seule présence au démarrage ⟺ crash précédent avec
travail non enregistré. `_check_recovery_on_startup` (programmé via
`after` pour s'afficher sur une UI déjà mappée) propose la reprise.

Ce module fournit aussi les constantes `_RECOVERY_PATH` /
`_AUTOSAVE_INTERVAL_MS`, partagées avec `penetrometre.py` (qui efface
l'autosave dans `_on_close`, `action_new`, `_open_path`, `action_save`).
"""

from __future__ import annotations

import logging
import tkinter as tk
from contextlib import AbstractContextManager
from pathlib import Path
from tkinter import messagebox
from typing import TYPE_CHECKING, Optional

from i18n import _
from model import Arbre, Chantier
from persistence import clear_recovery, load_recovery, save_recovery
from undo import UndoStack

log = logging.getLogger("penetrometre")

# Astuce typage des mixins : au runtime la base est `object` (aucun
# couplage, MRO propre dans `App`), mais pour mypy on la fait dériver de
# `tk.Tk` afin que `self` soit vu comme un widget (méthodes `after`,
# `after_cancel`, `messagebox(parent=self)`…). Les attributs/méthodes
# propres à `App` restent déclarés explicitement dans le bloc
# `TYPE_CHECKING` de chaque mixin.
if TYPE_CHECKING:
    _MixinBase = tk.Tk
else:
    _MixinBase = object

# Sauvegarde de récupération (autosave anti-crash). Écrite périodiquement
# tant que la mission a des modifications non enregistrées, et effacée dès
# qu'on atteint un état propre (enregistrement, nouvelle mission, ouverture)
# ou à la fermeture normale. Sa seule présence au démarrage signale donc
# un crash précédent avec du travail non sauvegardé → on propose la reprise.
_RECOVERY_PATH = Path.home() / ".penetrometre" / "recovery" / "autosave.json"
_AUTOSAVE_INTERVAL_MS = 60_000  # 60 s


class RecoveryMixin(_MixinBase):
    """Méthodes d'autosave et de récupération. Mixin de `App` : compte
    sur les attributs/méthodes propres à `App` déclarés ci-dessous."""

    if TYPE_CHECKING:
        # Fournis par App (déclarés pour le type-check du mixin).
        chantier: Chantier
        current_idx: int
        current_file: Optional[Path]
        _dirty: bool
        _autosave_after_id: Optional[str]
        var_ch_nom: tk.StringVar
        var_ch_adr: tk.StringVar
        var_ch_ope: tk.StringVar
        var_ch_date: tk.StringVar
        var_filter: tk.StringVar
        _undo_stack: UndoStack

        def _suspend_sync_block(self) -> AbstractContextManager[None]: ...
        def _refresh_tree_arbres(self) -> None: ...
        def _load_arbre_to_ui(self) -> None: ...
        def _update_title(self) -> None: ...
        def set_status(self, text: str) -> None: ...

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
                _("Récupération"),
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
