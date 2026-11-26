"""
Cycle de vie des fichiers de mission (mixin de `App`).

Regroupe tout ce qui touche au **fichier mission** (`.json`) : créer une
mission vierge, ouvrir (boîte de dialogue, chemin direct, récents),
enregistrer (+ sauvegarde glissante), enregistrer sous — ainsi que
l'historique des relevés (nouvelle campagne, import d'une ancienne mission)
et l'export de l'évolution.

L'état muté est celui d'`App` (`chantier`, `current_idx`, `current_file`,
`_dirty`, …) ; le couplage est assumé et documenté (greppable) par le bloc
`TYPE_CHECKING` ci-dessous.

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

from app_recent import RecentFilesStore
from app_recovery import _RECOVERY_PATH
from app_settings import SettingsStore
from bareme import (
    description_seuils,
    get_groupes,
    groupes_vers_brut,
    seuils_depuis_brut,
)
from campagnes import (
    importer,
    nouvelle_campagne,
    proposer_appariement,
)
from dialogs_campagne import ask_appariement, libelle_arbre
from dialogs_shared import annees_entre, normaliser_date
from evolution import appariement_par_defaut
from i18n import _
from model import Arbre, Chantier
from palette import COLOR_BG
from persistence import (
    chantier_to_dict,
    clear_recovery,
    file_stamp,
    load_chantier,
    save_chantier,
    write_backup,
)
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
        _file_stamp: Optional[tuple[Path, tuple[int, int]]]
        _dirty: bool
        _recent: RecentFilesStore
        _undo_stack: UndoStack
        _settings: SettingsStore
        _ope_cmb: "Any"     # ttk.Combobox opérateur
        var_ch_nom: tk.StringVar
        var_ch_adr: tk.StringVar
        var_ch_client: tk.StringVar
        var_ch_ope: tk.StringVar
        var_ch_date: tk.StringVar

        def _suspend_sync_block(self) -> AbstractContextManager[None]: ...
        def _refresh_tree_arbres(self) -> None: ...
        def _load_arbre_to_ui(self) -> None: ...
        def _clear_filter_if_set(self) -> None: ...
        def _reset_all_filters(self) -> None: ...
        def _update_title(self) -> None: ...
        def _current_arbre(self) -> Optional[Arbre]: ...
        def set_status(self, text: str) -> None: ...
        def notify_export(self, path: str, label: str) -> None: ...
        def _open_in_system(self, path: Path) -> None: ...
        def push_undo(self) -> None: ...
        def push_undo_snapshot(self, snapshot: Any) -> None: ...

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
            self.var_ch_client.set("")
            self.var_ch_ope.set(last_ope)
            self.var_ch_date.set(self.chantier.date_releve)
        self.chantier.operateur = last_ope
        # Remet TOUS les filtres à zéro (pas seulement texte + risque) :
        # sinon un filtre Urgence/Échéance/Sondages laissé actif par la
        # mission précédente masquait l'arbre n°1 fraîchement créé — un
        # utilisateur créant une mission vierge se retrouvait devant une
        # liste vide, sans indice que l'arbre existait bel et bien.
        self._reset_all_filters()
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
            filetypes=[("Mission Pénétromètre Silvavenir", "*.json"),
                       ("Tous", "*.*")])
        if not p:
            return
        self._open_path(p)

    def action_save_as_template(self) -> None:
        """Enregistre la mission courante comme modèle réutilisable."""
        from dialogs import ask_string
        from template_store import save_template, template_from_chantier
        nom = ask_string(
            self,
            _("Enregistrer comme modèle"),
            _("Nom du modèle :"),
            initial=self.chantier.nom,
            info=_("Le modèle mémorise : client, adresse, opérateur, "
                   "essence, port, mèche, H sondage et écorce du 1er arbre."))
        if nom is None:
            return
        nom = nom.strip()
        if not nom:
            return
        data = template_from_chantier(self.chantier)
        p = save_template(nom, data)
        self.set_status(_("Modèle « {nom} » enregistré.").format(nom=nom))
        # Nom de fichier seul : le journal est destiné au support, le
        # chemin complet n'ajoute rien et expose l'arborescence du poste.
        log.info("Modèle enregistré : %s", p.name)

    def action_new_from_template(self) -> None:
        """Crée une nouvelle mission en choisissant un modèle existant."""
        import tkinter as tk
        from tkinter import ttk

        from template_store import delete_template, list_templates

        templates = list_templates()
        if not templates:
            from tkinter import messagebox
            messagebox.showinfo(
                _("Aucun modèle"),
                _("Aucun modèle enregistré.")
                + "\n\n" + _("Créez via Fichier → Enregistrer comme modèle…"),
                parent=self)
            return

        # Dialog de sélection
        result: dict[str, Optional[dict[str, Any]]] = {"chosen": None}

        dlg = tk.Toplevel(self)
        dlg.title(_("Nouvelle mission depuis un modèle"))
        dlg.resizable(False, False)
        dlg.configure(bg=COLOR_BG)

        from ui_fonts import font_body, font_subheading
        frm = ttk.Frame(dlg, padding=16)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text=_("Choisissez un modèle :"),
                  font=font_subheading()).pack(anchor="w",
                                                pady=(0, 8))

        lb_frame = ttk.Frame(frm)
        lb_frame.pack(fill="both", expand=True)
        lb = tk.Listbox(lb_frame, height=8, width=40,
                        font=font_body(), selectmode="single")
        sb = ttk.Scrollbar(lb_frame, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")

        for t in templates:
            lb.insert("end", t.get("nom_modele", "?"))
        if templates:
            lb.selection_set(0)

        def _detail() -> str:
            sel = lb.curselection()
            if not sel:
                return ""
            t = templates[sel[0]]
            ad = t.get("arbre_defaut", {})
            lines = []
            if t.get("client"):
                lines.append(f"Client : {t['client']}")
            if t.get("adresse"):
                lines.append(f"Adresse : {t['adresse']}")
            if t.get("operateur"):
                lines.append(f"Opérateur : {t['operateur']}")
            if ad.get("essence"):
                lines.append(f"Essence : {ad['essence']}")
            if ad.get("port_arbre"):
                lines.append(f"Port : {ad['port_arbre']}")
            if ad.get("meche_cm"):
                lines.append(f"Mèche : {ad['meche_cm']:g} cm")
            return "\n".join(lines) or "—"

        lbl_detail = ttk.Label(frm, text="", style="Muted.TLabel",
                               justify="left")
        lbl_detail.pack(anchor="w", pady=(8, 0))

        def _on_select(*_: object) -> None:
            lbl_detail.configure(text=_detail())

        lb.bind("<<ListboxSelect>>", _on_select)
        _on_select()

        def _ok() -> None:
            sel = lb.curselection()
            if sel:
                result["chosen"] = templates[sel[0]]
            dlg.destroy()

        def _delete() -> None:
            sel = lb.curselection()
            if not sel:
                return
            idx = sel[0]
            t = templates[idx]
            from tkinter import messagebox as _mb
            if _mb.askyesno(
                    _("Supprimer le modèle"),
                    _("Supprimer « {nom} » ?").format(
                        nom=t.get("nom_modele", "?")),
                    parent=dlg):
                delete_template(t["_path"])
                templates.pop(idx)
                lb.delete(idx)
                if templates:
                    lb.selection_set(max(0, idx - 1))
                    _on_select()
                else:
                    dlg.destroy()

        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(12, 0))
        ttk.Button(btns, text=_("Supprimer"), style="Ghost.TButton",
                   command=_delete).pack(side="left")
        ttk.Button(btns, text=_("Annuler"), style="Ghost.TButton",
                   command=dlg.destroy).pack(side="right")
        ttk.Button(btns, text=_("Créer la mission"), style="Accent.TButton",
                   command=_ok).pack(side="right", padx=(0, 6))

        dlg.bind("<Return>", lambda e: _ok())
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        dlg.bind("<Double-Button-1>", lambda e: _ok())
        from dialogs import _make_modal
        _make_modal(dlg, self)
        dlg.wait_window()

        chosen = result.get("chosen")
        if not chosen:
            return

        # Créer la nouvelle mission depuis le modèle
        if self._dirty:
            from tkinter import messagebox
            if not messagebox.askyesno(
                    _("Nouvelle mission"),
                    _("Des modifications non enregistrées seront perdues.\n"
                      "Continuer quand même ?"),
                    parent=self):
                return

        self._undo_stack.clear()
        self._dirty = False
        clear_recovery(_RECOVERY_PATH)
        self.chantier = Chantier()

        # Appliquer les champs du modèle
        self.chantier.client    = chosen.get("client", "")
        self.chantier.adresse   = chosen.get("adresse", "")
        self.chantier.operateur = chosen.get("operateur", "")

        # Premier arbre avec les valeurs par défaut du modèle
        ad = chosen.get("arbre_defaut", {})
        a0 = Arbre(
            numero_arbre="1",
            essence=ad.get("essence", ""),
            port_arbre=ad.get("port_arbre", "libre"),
            meche_cm=float(ad.get("meche_cm", 40.0)),
            hauteur_sondage_cm=float(ad.get("hauteur_sondage_cm", 0.0)),
            hauteur_arbre_m=float(ad.get("hauteur_arbre_m", 0.0)),
        )
        a0.epaisseur_ecorce_cm = float(ad.get("epaisseur_ecorce_cm", 0.0))
        self.chantier.arbres = [a0]
        self.current_idx = 0
        self.current_file = None

        with self._suspend_sync_block():
            self.var_ch_nom.set(self.chantier.nom)
            self.var_ch_adr.set(self.chantier.adresse)
            self.var_ch_client.set(self.chantier.client)
            self.var_ch_ope.set(self.chantier.operateur)
            self.var_ch_date.set(self.chantier.date_releve)
        self.chantier.operateur = self.chantier.operateur

        self._reset_all_filters()  # cf. action_new
        self._refresh_tree_arbres()
        self._load_arbre_to_ui()
        self._update_title()
        self.set_status(
            _("Nouvelle mission depuis le modèle « {nom} ».").format(
                nom=t.get("nom_modele", "?")))

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

    def action_nouvelle_campagne(self) -> None:
        """Archive le relevé actuel de chaque arbre mesuré dans la mission ;
        la nouvelle visite repart des mêmes valeurs, à confirmer."""
        from datetime import datetime

        from dialogs import ask_date

        titre = _("Nouvelle campagne")
        date = ask_date(
            self, datetime.now().strftime("%d/%m/%Y"), title=titre,
            prompt=_("Date de la nouvelle visite"),
            info=_("Relevé actuel : {date}.").format(
                date=self.chantier.date_releve or _("non renseignée")))
        if not date:
            return
        if not messagebox.askyesno(titre, _(
                "Le relevé actuel sera archivé dans la mission.\n\n"
                "Tout reste prérempli pour la nouvelle visite. Les sondages "
                "sont marqués « à confirmer » : ils ne comptent pas dans la "
                "comparaison tant qu'ils ne sont pas retapés ou validés.\n"
                "Pensez à revoir le diamètre, les diamètres locaux, la "
                "préconisation, le suivi et les photos.\n\n"
                "Continuer ?")):
            return
        avant = chantier_to_dict(self.chantier)
        try:
            n = nouvelle_campagne(
                self.chantier, date,
                self.chantier.bareme_seuils or groupes_vers_brut(get_groupes()))
        except ValueError as e:
            messagebox.showerror(titre, str(e))
            return
        self.push_undo_snapshot(avant)
        self._apres_changement_historique()
        self.set_status(_("{n} arbre(s) archivé(s). Saisissez la nouvelle "
                          "visite (Ctrl+Z pour annuler).").format(n=n))

    def action_importer_releve(self) -> None:
        """Rattache aux arbres de la mission les relevés d'une ancienne
        mission, après validation de la correspondance."""
        from dialogs import ask_date

        titre = _("Importer un relevé antérieur")
        p = filedialog.askopenfilename(
            title=_("Ancienne mission à importer"),
            filetypes=[("Mission Pénétromètre Silvavenir", "*.json"),
                       ("Tous", "*.*")])
        if not p:
            return
        try:
            ancienne = load_chantier(p)
        except Exception as e:
            log.exception("Échec chargement du relevé à importer")
            messagebox.showerror(_("Erreur"), str(e))
            return
        date = normaliser_date(ancienne.date_releve)
        if not date:
            date = ask_date(self, "", title=titre,
                            prompt=_("Date de cette ancienne visite"))
            if not date:
                return
        ecart = annees_entre(date, self.chantier.date_releve)
        if ecart is not None and ecart <= 0:
            messagebox.showerror(titre, _(
                "Ce relevé ({a}) n'est pas antérieur à la mission "
                "ouverte ({b}).").format(a=date, b=self.chantier.date_releve))
            return
        arbres = self.chantier.arbres
        choix = ask_appariement(self, arbres, ancienne.arbres,
                                proposer_appariement(self.chantier, ancienne))
        if choix is None:
            return
        avant = chantier_to_dict(self.chantier)
        n, remarques = 0, []
        for arbre, i_ancien in zip(arbres, choix):
            if i_ancien is None:
                continue
            ancien = ancienne.arbres[i_ancien]
            sans_pair = appariement_par_defaut(ancien, arbre).count(None)
            try:
                importer(arbre, ancien, date, ancienne.operateur,
                         ancienne.bareme_seuils)
            except ValueError as e:
                remarques.append(f"{libelle_arbre(arbre)} : {e}")
                continue
            n += 1
            if sans_pair:
                remarques.append(_("{arbre} : {n} brin(s) sans correspondance."
                                   ).format(arbre=libelle_arbre(arbre),
                                            n=sans_pair))
        if n:
            self.push_undo_snapshot(avant)
            self._apres_changement_historique()
        self.set_status(_("{n} arbre(s) : relevé du {date} importé.").format(
            n=n, date=date))
        if remarques:
            messagebox.showwarning(titre, "\n".join(remarques[:15]))

    def _apres_changement_historique(self) -> None:
        with self._suspend_sync_block():
            self.var_ch_date.set(self.chantier.date_releve)
        self._refresh_tree_arbres()
        self._load_arbre_to_ui()

    def _export_comparison(self, fmt: str,
                           builder: "Optional[Callable[[], Any]]") -> None:
        """Enregistre l'évolution construite par `builder` (menu Export).

        PDF : liste de pages (une par brin pour une cépée). PNG :
        `(label, image)`, **un fichier par brin** — jamais empilés, pour
        rester insérables dans un rapport."""
        from comparaison_render import save_comparison_pdf, save_evolution_pngs
        if builder is None:
            return
        ext = ".pdf" if fmt == "pdf" else ".png"
        typ = "PDF" if fmt == "pdf" else "Image PNG"
        p = filedialog.asksaveasfilename(
            parent=self, defaultextension=ext,
            filetypes=[(typ, f"*{ext}"), ("Tous", "*.*")])
        if not p:
            return
        try:
            pages = builder()
            label = "Comparaison d'inspections"
            if fmt == "pdf":
                save_comparison_pdf(pages, p)
                out_path = Path(p)
            else:
                written = save_evolution_pngs(pages, p)
                out_path = Path(written[0])
                if len(written) > 1:
                    label += f" ({len(written)} fichiers)"
            self.notify_export(str(out_path), label)
        except Exception as e:
            log.exception("Échec export comparaison")
            messagebox.showerror(_("Erreur"), str(e))

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
            self.var_ch_client.set(self.chantier.client)
            self.var_ch_ope.set(self.chantier.operateur)
            self.var_ch_date.set(self.chantier.date_releve)
        self._reset_all_filters()  # mission rechargée → cf. action_new
        self._refresh_tree_arbres()
        self._load_arbre_to_ui()
        self._update_title()
        self._avertir_bareme_different()

    def _avertir_bareme_different(self) -> None:
        """Signale que la mission ouverte a été classée avec d'autres seuils.

        Le barème est un réglage de POSTE : rouvrir une mission relevée
        avec d'autres seuils **reclasse** silencieusement les arbres
        (un Orange peut devenir Vert). On ne réapplique pas les seuils du
        fichier — ouvrir une mission ne doit pas reconfigurer le poste —
        mais l'écart doit être visible, sinon l'opérateur compare deux
        campagnes sur des bases différentes sans le savoir.

        Non bloquant : message de barre d'état, pas de modale.
        """
        seuils_fichier = getattr(self.chantier, "bareme_seuils", None)
        if not seuils_fichier:
            return           # mission antérieure à cette trace : rien à dire
        groupes_fichier = seuils_depuis_brut(seuils_fichier)
        if groupes_fichier == get_groupes():
            return
        log.warning("Barème du fichier ≠ barème du poste (%s vs %s)",
                    groupes_fichier, get_groupes())
        self.set_status(
            _("⚠ Cette mission a été classée avec un autre barème "
              "({b}). Les classes affichées sont recalculées avec "
              "le barème de ce poste.").format(
                  b=description_seuils(groupes_fichier)))

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
            self._memoriser_empreinte()
            self._install_chantier_ui()
            self._recent.push(p)
        except FileNotFoundError:
            messagebox.showerror(
                _("Fichier introuvable"),
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

    def _memoriser_empreinte(self) -> None:
        """Retient l'empreinte du fichier courant (ouverture / enregistrement)."""
        st = file_stamp(self.current_file) if self.current_file else None
        self._file_stamp = (
            (self.current_file, st) if self.current_file and st else None)

    def _fichier_modifie_ailleurs(self) -> bool:
        """Vrai si le fichier courant a changé sur le disque depuis qu'on
        l'a ouvert / enregistré (autre poste sur un dossier partagé, autre
        instance). Faux si on ne sait pas (pas d'empreinte, autre chemin)."""
        if not self.current_file or self._file_stamp is None:
            return False
        chemin, ancienne = self._file_stamp
        if chemin != self.current_file:
            return False
        actuelle = file_stamp(self.current_file)
        return actuelle is not None and actuelle != ancienne

    def _confirmer_ecrasement(self) -> str:
        """Garde-fou anti-écrasement silencieux. Renvoie `"ecraser"`,
        `"copie"` (Enregistrer sous…) ou `"annuler"`. Quand l'utilisateur
        choisit d'écraser, la version présente sur le disque est d'abord
        sauvegardée (`write_backup`), pour ne rien perdre."""
        if not self._fichier_modifie_ailleurs():
            return "ecraser"
        assert self.current_file is not None
        rep = messagebox.askyesnocancel(
            _("Mission modifiée ailleurs"),
            _("Ce fichier a été modifié depuis son ouverture (par un autre "
              "poste ou une autre fenêtre) :") + f"\n{self.current_file.name}\n\n"
            + _("Oui : écraser avec ma version (l'autre version est "
                "conservée dans les sauvegardes)") + "\n"
            + _("Non : enregistrer ma version sous un autre nom") + "\n"
            + _("Annuler : ne rien enregistrer"),
            icon="warning", parent=self)
        if rep is None:
            return "annuler"
        if rep is False:
            return "copie"
        write_backup(self.current_file, _BACKUP_PATH)
        return "ecraser"

    def action_save(self) -> None:
        if not self.current_file:
            return self.action_save_as()
        choix = self._confirmer_ecrasement()
        if choix == "annuler":
            self.set_status(_("Enregistrement annulé."))
            return
        if choix == "copie":
            return self.action_save_as()
        try:
            save_chantier(self.chantier, self.current_file)
            self._memoriser_empreinte()
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
            self.set_status(_("✓ Enregistré — {nom}").format(nom=self.current_file.name))
        except Exception as e:
            log.exception("Échec enregistrement mission")
            messagebox.showerror(_("Erreur"), str(e))

    def action_save_as(self) -> None:
        p = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("Mission Pénétromètre Silvavenir", "*.json")])
        if not p:
            return
        self.current_file = Path(p)
        self.action_save()
