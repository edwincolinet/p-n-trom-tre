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

from app_recent import RecentFilesStore
from app_recovery import _RECOVERY_PATH
from app_settings import SettingsStore
from bareme import description_seuils, get_groupes, seuils_depuis_brut
from comparaison import open_comparison
from i18n import _
from model import Arbre, Chantier
from palette import COLOR_BG, COULEUR_CLASSE
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
        def _update_compare_state(self) -> None: ...
        # Fournis par `ExportActionsMixin` (menu Export ET menu propre à
        # la fenêtre de comparaison — cf. `action_compare_arbre`).
        def action_export_comparison_pdf(self) -> None: ...
        def action_export_comparison_png(self) -> None: ...

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

    def action_load_reference(self) -> bool:
        """Charge en mémoire une mission de référence (campagne antérieure)
        pour la comparaison inter-missions. Par session : rien n'est écrit
        dans la mission courante. Renvoie True si chargée."""
        p = filedialog.askopenfilename(
            title=_("Choisir la mission de référence (campagne antérieure)"),
            filetypes=[("Mission Pénétromètre Silvavenir", "*.json"), ("Tous", "*.*")])
        if not p:
            return False
        try:
            self._reference_chantier = load_chantier(p)
        except Exception as e:
            log.exception("Échec chargement mission de référence")
            messagebox.showerror(_("Erreur"), str(e))
            return False
        n = len(self._reference_chantier.arbres)
        self.set_status(_("Mission de référence chargée — {nom} ({n} arbre(s)).").format(nom=Path(p).name, n=n))
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
                    _("Faire une comparaison"),
                    "Des modifications n'ont pas été enregistrées.\n"
                    "Continuer quand même ?"):
                return
        p = filedialog.askopenfilename(
            title=_("Mission antérieure à ré-inspecter (servira de référence)"),
            filetypes=[("Mission Pénétromètre Silvavenir", "*.json"), ("Tous", "*.*")])
        if not p:
            return
        try:
            loaded = load_chantier(p)
        except Exception as e:
            log.exception("Échec chargement pour ré-inspection")
            messagebox.showerror(_("Erreur"), str(e))
            return
        # Nouvelle date de relevé (aujourd'hui par défaut). Annulé → on
        # abandonne ; effacé → on retombe sur aujourd'hui (une date est
        # indispensable au calcul du taux d'évolution). Calculée AVANT
        # l'appel à `ask_date` pour être affichée dans son `info` — sans
        # ça, rien n'indiquait à l'utilisateur QUELLE date on lui demande
        # (celle du diagnostic présent, pas celle de la référence) ni la
        # date de référence à laquelle elle sera comparée (repéré à
        # l'usage : la fenêtre de calendrier, générique, ne le disait pas).
        today = datetime.now().strftime("%d/%m/%Y")
        ref_date = loaded.date_releve or _("non renseignée")
        new_date = ask_date(
            self, today,
            title=_("Date du diagnostic actuel"),
            prompt=_("Choisissez la date du présent diagnostic"),
            info=_("Mission de référence « {nom} » : relevée le "
                    "{date}. La date choisie ici sera comparée à "
                    "celle-ci.").format(nom=loaded.nom, date=ref_date))
        if new_date is None:
            return
        if not new_date:
            new_date = today

        # Référence = instantané figé AVANT toute édition (garde l'ancienne
        # date, donc l'intervalle « annees » est correct).
        self._reference_chantier = copy.deepcopy(loaded)

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
        « Faire une comparaison… » — bouton et menu désactivés sinon.

        La fenêtre partage le bandeau de l'App (même `tk.Menu`, cf.
        `comparaison.open_comparison`) : l'export PDF/PNG de cette
        comparaison se fait depuis le menu Export, comme partout ailleurs
        (entrées activées par `comparaison.is_comparison_active()`, pointant
        vers `app_export_actions.action_export_comparison_pdf/_png`)."""
        ref = self._reference_chantier
        a = self._current_arbre()
        if ref is None or a is None:
            return
        open_comparison(self, self.chantier, ref,
                        default_arbre=a,
                        cur_date=self.chantier.date_releve,
                        couleur_classe=COULEUR_CLASSE,
                        on_save=self.action_save)

    def _export_comparison(self, fmt: str, builder: Callable[[], Any],
                           parent: "tk.Misc") -> None:
        """Enregistre la comparaison (PNG ou PDF) construite par `builder`
        (appelé depuis le menu Export — cf. `action_export_comparison_pdf`/
        `_png` de `ExportActionsMixin`). `parent` = la fenêtre de
        comparaison si elle est encore ouverte (ancre le filedialog pour
        qu'il s'ouvre AU PREMIER PLAN, sinon il passe derrière), sinon la
        fenêtre principale.

        `builder()` renvoie une **liste de pages** PDF (une par brin pour
        une cépée, assemblées en un seul PDF multi-pages) ; pour le PNG,
        `render_evolution_pngs` renvoie des `(label, image)` et
        `save_evolution_pngs` écrit **un fichier par brin** — une cépée
        n'est jamais empilée dans un unique PNG, ce qui la rendrait
        réinsérable dans un rapport uniquement en la recadrant.

        Le succès est signalé à DEUX endroits : la barre d'état principale
        (`notify_export`, comme tout export) et le pied de la fenêtre de
        comparaison (`show_export_feedback`) — la première est invisible
        tant que la seconde couvre l'écran."""
        from comparaison import show_export_feedback
        from comparaison_render import save_comparison_pdf, save_evolution_pngs
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
                out_path = Path(p)
                label = "Comparaison d'inspections"
            else:
                written = save_evolution_pngs(pages, p)
                out_path = Path(written[0])
                label = ("Comparaison d'inspections" if len(written) == 1
                         else f"Comparaison d'inspections ({len(written)} fichiers)")
            self.notify_export(str(out_path), label)
            show_export_feedback(
                f"✓ {label} — {out_path.name}",
                on_open_file=lambda: self._open_in_system(out_path),
                on_open_folder=lambda: self._open_in_system(out_path.parent))
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
