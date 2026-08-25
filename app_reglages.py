"""
Réglages, préférences et mises à jour (mixin de `App`).

Regroupe les handlers de **préférences** (langue, barème t/R, taille du
texte, contraste élevé, logo/cabinet) et de **mises à jour** (vérification
en arrière-plan + bannière), extraits de `penetrometre.py` pour alléger
l'orchestrateur. Ces méthodes sont appelées soit depuis `__init__`
(`_apply_ui_scale`/`_apply_bareme`/`_apply_styles`, au démarrage), soit
depuis la barre de menu (`action_*`) ou les bannières de la barre d'état
(`action_restart`).

Elles lisent/mutent l'état d'`App` (`_settings`, le `_logo_frame`, les
bannières `_update_banner`/`_restart_banner` construites par
`LayoutMixin`) — déclaré dans le bloc `TYPE_CHECKING` ci-dessous (cf.
note d'architecture dans CLAUDE.md).
"""

from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING, Any, Optional

# `_RECOVERY_PATH` : effacé avant un redémarrage (cf. `action_restart`).
from app_recovery import _RECOVERY_PATH
from app_style import apply_ttk_styles
from bareme import (
    GROUPES_DEFAUT,
    get_groupes,
    groupes_vers_brut,
    set_groupes,
    seuils_depuis_brut,
)
from bareme_store import load_bareme, save_bareme
from i18n import _, get_language
from persistence import clear_recovery
from ui_fonts import set_ui_scale

log = logging.getLogger("penetrometre")

# Cf. note dans app_recovery : base `object` au runtime, `tk.Tk` pour mypy.
if TYPE_CHECKING:
    from app_settings import SettingsStore

    _MixinBase = tk.Tk
else:
    _MixinBase = object


class ReglagesMixin(_MixinBase):
    """Préférences + mises à jour. Mixin de `App` : s'appuie sur les
    attributs/méthodes propres à `App` déclarés ci-dessous."""

    if TYPE_CHECKING:
        # Fournis par App / les autres mixins (déclarés pour le type-check).
        _settings: SettingsStore
        _dirty: bool
        _logo_frame: tk.Frame
        _logo_image: Optional[Any]
        _update_banner: ttk.Frame
        _update_banner_lbl: ttk.Label
        _update_banner_url: str
        _restart_banner: ttk.Frame

        def set_status(self, text: str) -> None: ...
        def _redraw_all(self) -> None: ...

    # --- Mise à jour -------------------------------------------------------

    def _check_for_update_async(self) -> None:
        """Lance la vérification de mise à jour dans un thread daemon.

        Appelé via `after(3000, …)` au démarrage, seulement si le réglage
        « vérification automatique » est activé. Le résultat arrive dans
        `_on_update_result` via `after(0, …)` depuis le thread (thread-safe)."""
        if not self._settings.check_updates():
            return
        import threading

        from penetrometre import __version__
        from update_checker import check_for_update

        def _worker() -> None:
            result = check_for_update(__version__)
            if result is not None:
                tag, url = result
                self.after(0, lambda: self._on_update_result(tag, url))

        threading.Thread(target=_worker, daemon=True,
                         name="update-check").start()

    def _on_update_result(self, tag: str, url: str) -> None:
        """Affiche la bannière de mise à jour (appelé depuis le thread de vérification)."""
        if not hasattr(self, "_update_banner"):
            return
        self._update_banner_url = url
        self._update_banner_lbl.configure(
            text=f"🆕 Nouvelle version disponible : {tag}")
        if not self._update_banner.winfo_ismapped():
            self._update_banner.pack(side="bottom", fill="x")

    def _open_update_url(self) -> None:
        """Ouvre la page de téléchargement de la mise à jour dans le navigateur.

        Re-filtre l'URL au moment de l'ouverture : `check_for_update` la
        valide déjà à la réception, mais c'est ici qu'elle est passée au
        navigateur — le contrôle vit donc aussi au point d'usage, pour ne
        pas dépendre du chemin par lequel `_update_banner_url` a été posé.
        """
        import webbrowser

        from update_checker import url_de_release_sure
        url = getattr(self, "_update_banner_url", "")
        if url:
            webbrowser.open(url_de_release_sure(url))

    def _dismiss_update_banner(self) -> None:
        """Ferme la bannière pour la session courante (ne désactive pas le check)."""
        if hasattr(self, "_update_banner"):
            self._update_banner.pack_forget()

    def _show_restart_banner(self) -> None:
        """Affiche la bande « redémarrage requis » (réglages langue / taille
        du texte / contraste). Non-modale : laisse comparer plusieurs valeurs
        sans interruption, le bouton « Redémarrer maintenant » relance d'un
        clic. No-op si la barre d'état n'est pas construite (tests sans UI)."""
        if not hasattr(self, "_restart_banner"):
            return
        if not self._restart_banner.winfo_ismapped():
            self._restart_banner.pack(side="bottom", fill="x")

    def _dismiss_restart_banner(self) -> None:
        """Ferme la bande de redémarrage pour la session courante."""
        if hasattr(self, "_restart_banner"):
            self._restart_banner.pack_forget()

    def action_check_updates(self) -> None:
        """Vérifie manuellement les mises à jour (Aide → Vérifier les mises à jour)."""
        from penetrometre import __version__
        from update_checker import check_for_update
        self.set_status(_("Vérification des mises à jour…"))
        result = check_for_update(__version__, timeout=5.0)
        if result is None:
            from tkinter import messagebox as _mb
            _mb.showinfo(
                "Mises à jour",
                f"Vous utilisez la version {__version__}.\n\n"
                "Aucune mise à jour disponible ou aucune connexion réseau.",
                parent=self)
            self.set_status("Prêt.")
        else:
            tag, url = result
            self._on_update_result(tag, url)
            self.set_status(_("Mise à jour disponible : {tag}").format(tag=tag))

    def action_toggle_check_updates(self) -> None:
        """Active/désactive la vérification automatique des mises à jour."""
        new_val = not self._settings.check_updates()
        self._settings.set_check_updates(new_val)
        état = "activée" if new_val else "désactivée"
        self.set_status(_("Vérification automatique des mises à jour {état}.").format(état=état))

    def get_check_updates(self) -> bool:
        """État courant du réglage de vérification automatique."""
        return self._settings.check_updates()

    def action_set_language(self, lang: str) -> None:
        """Change la langue de l'interface. La langue n'est lue qu'à la
        création des widgets → un redémarrage est nécessaire ; on l'offre
        via la bande non-modale (bouton « Redémarrer maintenant »)."""
        if lang == self._settings.language():
            return
        self._settings.set_language(lang)
        self.set_status(_("Langue modifiée."))
        self._show_restart_banner()

    def action_restart(self) -> None:
        """Relance l'application (remplace le processus courant)."""
        import os
        import sys
        if self._dirty:
            if not messagebox.askyesno(
                    _("Redémarrer"),
                    _("Des modifications non enregistrées seront perdues.")
                    + "\n" + _("Redémarrer quand même ?"),
                    parent=self):
                return
        clear_recovery(_RECOVERY_PATH)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    def get_language_code(self) -> str:
        """Code de langue courante (fr/en/it)."""
        return get_language()

    def _apply_bareme(self) -> None:
        """Charge le barème personnalisé depuis ~/.penetrometre/bareme.json
        et l'injecte dans `bareme.set_groupes`. No-op si le fichier est
        absent (les défauts codés dans bareme.py s'appliquent déjà)."""
        set_groupes(seuils_depuis_brut(load_bareme()))

    def action_bareme_settings(self) -> None:
        """Ouvre le dialog de paramétrage du barème t/R (Affichage → Barème…)."""
        from dialogs_settings import ask_bareme_settings
        result = ask_bareme_settings(self, get_groupes(), list(GROUPES_DEFAUT))
        if result is None:
            return
        save_bareme(groupes_vers_brut(result))
        set_groupes(result)
        # Redessiner l'arbre courant (les pastilles et le diagnostic
        # peuvent avoir changé de classe avec les nouveaux seuils).
        self._redraw_all()
        self.set_status("Barème mis à jour. Les diagnostics utilisent les nouveaux seuils.")

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
        — d'où la bande de redémarrage non-modale."""
        self._settings.set_ui_scale(scale)
        self._apply_ui_scale(self._settings.ui_scale)
        self._apply_styles()
        self.set_status(_("Taille du texte modifiée."))
        self._show_restart_banner()

    def action_set_high_contrast(self, on: bool) -> None:
        """Active/désactive le contraste élevé (menu Affichage) : persiste
        et ré-applique les styles ttk à chaud. Les widgets à couleur déjà
        peinte hors styles (tags de la liste, dessin) ne changent pas —
        d'où la bande de redémarrage non-modale pour un effet complet."""
        self._settings.set_high_contrast(on)
        self._apply_styles()
        self.set_status(
            _("Contraste élevé activé.") if on
            else _("Contraste élevé désactivé."))
        self._show_restart_banner()

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
                             text=_("+ Logo cabinet"),
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
            resized = pil.resize(
                (int(pil.width * ratio), target_h),
                PILImage.Resampling.LANCZOS)
            self._logo_image = ImageTk.PhotoImage(resized)
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
