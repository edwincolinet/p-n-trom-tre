"""
Construction de l'interface (mixin de `App`).

Regroupe la **fabrique de widgets** de la fenêtre principale, extraite de
`penetrometre.py` pour alléger l'orchestrateur : le header (titre +
boutons de comparaison + logo cabinet), la rangée de métadonnées mission,
la barre d'état (avec ses bannières mise-à-jour / redémarrage), les trois
colonnes redimensionnables (`_build_left`/`_center`/`_right`) et la
persistance des poignées (`sash`).

Pur câblage Tk : ces méthodes **créent et assignent** la plupart des
attributs UI d'`App` (`tree_arbres`, `nb`, `section`, `var_*`, panes…),
puis l'orchestrateur les lit/mute. C'est un découpage par responsabilité,
pas une encapsulation — au runtime le mixin partage l'état d'`App` (cf.
note d'architecture dans CLAUDE.md). Les attributs/méthodes fournis par
`App` ou les autres mixins sont déclarés dans le bloc `TYPE_CHECKING`
ci-dessous (greppable, pour mypy ; sans effet au runtime).
"""

from __future__ import annotations

import logging
import sys
import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING, Any, Optional, cast

from aide_repliable import AideRepliable
from app_arbres import (
    _COMPLET_FILTER_ALL,
    _ECHEANCE_FILTER_ALL,
    _RISK_FILTER_ALL,
    _URGENCE_FILTER_ALL,
    _complet_filter_choices,
    _echeance_filter_choices,
    _risk_filter_choices,
)
from bareme import CLASSE_ORANGE, CLASSE_ROUGE, CLASSE_VERT
from chrome_icons import calendar_icon, save_icon
from i18n import _
from icons import ICON_CALENDAR, ICON_DELETE
from palette import (
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_BRAND_ORANGE,
    COLOR_MUTED,
    COLOR_PANEL,
    COLOR_WARN,
    COULEUR_CLASSE,
)
from pane_contreforts import ContrefortsPane
from pane_degradations import DegradationsPane
from pane_diagnostic import DiagnosticPane
from pane_identification import IdentificationPane
from pane_sondages import SondagesPane
from section_canvas import SectionCanvas
from tooltip import Tooltip
from ui_fonts import font as ui_font
from ui_fonts import (
    font_heading,
    font_small,
    font_small_bold,
    font_small_italic,
)

log = logging.getLogger("penetrometre")

# Cf. note dans app_recovery : base `object` au runtime (MRO propre dans
# `App`), `tk.Tk` pour mypy afin que `self` soit vu comme un widget.
if TYPE_CHECKING:
    from app_settings import SettingsStore
    from model import Chantier
    from penetrometre import App

    _MixinBase = tk.Tk
else:
    _MixinBase = object


class LayoutMixin(_MixinBase):
    """Méthodes de construction de l'UI. Mixin de `App` : s'appuie sur les
    attributs/méthodes propres à `App` déclarés ci-dessous."""

    if TYPE_CHECKING:
        # Fournis par App / les autres mixins (déclarés pour le type-check).
        chantier: Chantier
        _settings: SettingsStore
        _logo_frame: tk.Frame
        _logo_image: Optional[Any]
        # Panes assignés ici mais déclarés Optional pour rester alignés sur
        # les annotations d'`App.__init__` (qui les initialise à None).
        pane_s: Optional[SondagesPane]
        pane_de: Optional[DegradationsPane]
        pane_cf: Optional[ContrefortsPane]
        pane_diag: Optional[DiagnosticPane]

        def action_cabinet_settings(self) -> None: ...
        def _reload_logo(self) -> None: ...
        def _refresh_tree_arbres(self) -> None: ...
        def _on_select_arbre(self, event: "tk.Event[tk.Misc]") -> None: ...
        def _on_tree_arbres_right_click(
            self, event: "tk.Event[tk.Misc]") -> None: ...
        def action_rename_arbre(self) -> None: ...
        def action_dup_arbre(self) -> None: ...
        def action_del_arbre(self) -> None: ...
        def action_add_arbre(self) -> None: ...
        def action_next_a_finir(self) -> None: ...
        def _reset_all_filters(self) -> None: ...
        def _urgence_filter_choices(self) -> "list[str]": ...
        def action_new(self) -> None: ...
        def action_open(self) -> None: ...
        def action_save(self) -> None: ...
        def _open_last_export_folder(self) -> None: ...
        def _open_last_export_file(self) -> None: ...
        def _update_save_indicator(self) -> None: ...
        def _open_update_url(self) -> None: ...
        def _dismiss_update_banner(self) -> None: ...
        def action_restart(self) -> None: ...
        def _dismiss_restart_banner(self) -> None: ...
        def _show_trial_banner(self, days_remaining: int) -> None: ...
        def _action_activate_from_trial(self) -> None: ...
        def _on_brin_bar_configure(
            self, event: "tk.Event[tk.Misc]") -> None: ...
        def _meta_focus_in(self) -> None: ...
        def _meta_focus_out(self) -> None: ...
        def _date_focus_in(self) -> None: ...
        def _date_focus_out(self) -> None: ...
        def _sync_chantier_meta(self) -> None: ...
        def _pick_date(self) -> None: ...

    def _build_layout(self) -> None:
        # Bandeau de marque de la charte SILVAVENIR : fond blanc, filet
        # orange de 3 px dessous.
        header = ttk.Frame(self, style="Brand.TFrame", padding=(18, 14))
        header.pack(fill="x")
        tk.Frame(self, bg=COLOR_BRAND_ORANGE, height=3).pack(fill="x",
                                                             pady=(0, 6))

        # Bloc gauche : titre app
        left = ttk.Frame(header, style="Brand.TFrame")
        left.pack(side="left")
        # `anchor="s"` sur les deux labels : sans lui, chacun est centré
        # dans son propre parcel (haut/bas déterminés par sa police), et
        # le sous-titre (petite police) flotte visuellement plus haut que
        # la ligne de base du titre (grande police) au lieu de s'aligner
        # dessus. Aligner les deux sur le bas des parcels ne suffit pas
        # tout à fait : Georgia 18 gras (titre) a un « descent » (espace
        # sous la ligne de base) de 2px de plus qu'Helvetica 10 italique
        # (sous-titre), donc un simple `anchor="s"` fait déborder le
        # sous-titre 2px SOUS la ligne de base du titre. `pady=(0, 2)`
        # compense cet écart mesuré (vérifié pixel à pixel sur une
        # capture d'écran) pour aligner les deux lignes de base.
        ttk.Label(left, text=_("Pénétromètre Silvavenir"),
                  style="Brand.Title.TLabel").pack(side="left", anchor="s")
        ttk.Label(left, text=_("  Expertise arboricole"),
                  style="Brand.Sub.TLabel").pack(side="left", anchor="s",
                                                 padx=(8, 0), pady=(0, 2))

        # Bloc droit : zone logo cabinet (cliquable → paramètres cabinet).
        # PIL est requis pour les exports PNG/PDF — s'il est absent au
        # démarrage, l'utilisateur l'apprend ici (log) plutôt qu'au
        # moment d'un clic « Exporter PDF » qui échouerait silencieusement.
        self._logo_frame = tk.Frame(header, cursor="hand2", bg=COLOR_PANEL)
        self._logo_frame.pack(side="right", padx=(12, 0))
        self._logo_frame.bind(
            "<Button-1>", lambda e: self.action_cabinet_settings())
        Tooltip(self._logo_frame,
                _("Cliquer pour configurer le logo et le nom du cabinet…"))
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
        self.var_ch_client = tk.StringVar(value=self.chantier.client)
        self.var_ch_ope = tk.StringVar(value=self.chantier.operateur)
        self.var_ch_date = tk.StringVar(value=self.chantier.date_releve)
        self._meta_snapshot: Optional[str] = None
        self._date_focus_in_value = ""
        # Rangée unique : mission, adresse, client, opérateur, date — tout
        # sur la même ligne (gain de place et de lisibilité par rapport aux
        # deux rangées précédentes).
        row1 = ttk.Frame(meta, style="Panel.TFrame")
        row1.pack(fill="x")
        for lbl, var, w in [(_("Mission"), self.var_ch_nom, 18),
                             (_("Adresse"), self.var_ch_adr, 22)]:
            ttk.Label(row1, text=lbl).pack(side="left", padx=(0, 4))
            e = ttk.Entry(row1, textvariable=var, width=w)
            e.pack(side="left", padx=(0, 14))
            var.trace_add("write", lambda *a: self._sync_chantier_meta())
            e.bind("<FocusIn>", lambda ev: self._meta_focus_in())
            e.bind("<FocusOut>", lambda ev: self._meta_focus_out())
            if lbl == _("Mission"):
                Tooltip(e, _("Nom de la mission — peut aussi porter une "
                             "référence ou un n° de commande."))
        for lbl, var, w in [(_("Client"), self.var_ch_client, 16),
                             (_("Opérateur"), self.var_ch_ope, 14),
                             (_("Date"), self.var_ch_date, 12)]:
            ttk.Label(row1, text=lbl).pack(side="left", padx=(0, 4))
            var.trace_add("write", lambda *a: self._sync_chantier_meta())
            if lbl == _("Client"):
                e = ttk.Entry(row1, textvariable=var, width=w)
                e.pack(side="left", padx=(0, 14))
                e.bind("<FocusIn>", lambda ev: self._meta_focus_in())
                e.bind("<FocusOut>", lambda ev: self._meta_focus_out())
            elif lbl == _("Opérateur"):
                # Combobox éditable : propose l'historique des opérateurs.
                self._ope_cmb = ttk.Combobox(
                    row1, textvariable=var, width=w, state="normal",
                    values=self._settings.get_operateurs_history())
                self._ope_cmb.pack(side="left", padx=(0, 14))
                self._ope_cmb.bind("<FocusIn>",
                                   lambda ev: self._meta_focus_in())
                self._ope_cmb.bind("<FocusOut>",
                                   lambda ev: self._meta_focus_out())
                Tooltip(self._ope_cmb,
                        _("Nom de l'opérateur — mémorisé entre les sessions."))
            elif lbl == _("Date"):
                e = ttk.Entry(row1, textvariable=var, width=w)
                e.pack(side="left", padx=(0, 2))
                e.bind("<FocusIn>", lambda ev: self._date_focus_in())
                e.bind("<FocusOut>", lambda ev: self._date_focus_out())
                Tooltip(e, _("Date du relevé — format JJ/MM/AAAA "
                           "(normalisée automatiquement)."))
                # Icône bitmap plutôt qu'ICON_CALENDAR sur Windows
                # (2026-09-06) : l'emoji 📅 rend mal et son repli glyphe
                # (▦) s'est révélé tout aussi risqué (absent de l'encodage
                # Windows par défaut) — cf. icons.py/chrome_icons.py. Une
                # image PIL est garantie identique quelle que soit la
                # police installée.
                if sys.platform == "win32":
                    btn_cal = ttk.Button(row1, image=calendar_icon(),
                                         style="Ghost.TButton",
                                         command=self._pick_date)
                else:
                    btn_cal = ttk.Button(row1, text=ICON_CALENDAR, width=3,
                                         style="Ghost.TButton",
                                         command=self._pick_date)
                btn_cal.pack(side="left", padx=(0, 14))
                Tooltip(btn_cal, _("Choisir la date au calendrier"))
            else:
                e = ttk.Entry(row1, textvariable=var, width=w)
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
        ttk.Label(frame, text=_("Arbres de la mission"), style="Side.TLabel",
                  font=font_heading()).pack(anchor="w", pady=(0, 8))

        # Filtre de la liste (par n°, essence ou commentaire) — utile dès que la
        # mission compte beaucoup d'arbres. N'altère PAS le modèle : ne
        # fait que masquer les lignes non concordantes (les iid `a{i}`
        # restent indexés sur la position réelle dans `chantier.arbres`,
        # cf. `_on_select_arbre`). `var_filter` est lue par
        # `_refresh_tree_arbres` (tolérante si appelée avant ce build).
        # Libellé texte (pas d'icône loupe) : aligné sur les 4 filtres
        # avancés ci-dessous, qui utilisent tous un libellé texte plutôt
        # qu'un pictogramme — cohérence + évite un glyphe sans bon
        # équivalent monochrome (cf. design system, `icons.py`).
        filt = ttk.Frame(frame, style="Side.TFrame")
        filt.pack(fill="x", pady=(0, 4))
        ttk.Label(filt, text=_("Filtrer"), style="Side.TLabel").pack(
            side="left", padx=(0, 4))
        self.var_filter = tk.StringVar()
        ent_filter = ttk.Entry(filt, textvariable=self.var_filter)
        ent_filter.pack(side="left", fill="x", expand=True)
        self.var_filter.trace_add("write",
                                  lambda *a: self._refresh_tree_arbres())
        # Échap dans le champ = vider le filtre.
        ent_filter.bind("<Escape>", lambda e: self.var_filter.set(""))

        # Filtres « avancés » (risque / urgence / échéance / complétude des
        # sondages) : repliés par défaut derrière un en-tête cliquable —
        # même principe que `AideRepliable` (flèche ▸/▾, sans emoji : la
        # Treeview évite déjà les emojis de couleur pour la même raison,
        # rendu imprévisible selon la police système d'une plateforme à
        # l'autre). Sur une mission de quelques arbres — l'échelle courante
        # de l'outil — quatre comboboxes en permanence encombraient le
        # panneau pour un usage occasionnel ; le compteur dans l'en-tête
        # reste visible même replié, pour qu'un filtre actif ne soit
        # jamais oublié « hors de vue » (cf. `_sync_filtres_avances`).
        self._filtres_avances_expanded = False
        adv_header = ttk.Frame(frame, style="Side.TFrame")
        adv_header.pack(fill="x", pady=(0, 4))
        self._lbl_filtres_toggle = ttk.Label(
            adv_header, style="Side.TLabel", cursor="hand2")
        self._lbl_filtres_toggle.pack(anchor="w")
        self._lbl_filtres_toggle.bind(
            "<Button-1>", lambda e: self._toggle_filtres_avances())

        self._filtres_avances = ttk.Frame(frame, style="Side.TFrame")

        # Filtre par classe de risque. Sur une grosse mission, « ne montrer
        # que les rouges » est le tri prioritaire de l'expert. Cf.
        # _RISK_FILTER_* et `_arbre_matches_filter`.
        rfilt = ttk.Frame(self._filtres_avances, style="Side.TFrame")
        rfilt.pack(fill="x", pady=(0, 4))
        ttk.Label(rfilt, text=_("Risque"), style="Side.TLabel").pack(
            side="left", padx=(0, 4))
        self.var_risk_filter = tk.StringVar(value=_(_RISK_FILTER_ALL))
        cmb_risk = ttk.Combobox(rfilt, textvariable=self.var_risk_filter,
                                values=list(_risk_filter_choices()),
                                state="readonly", width=12)
        cmb_risk.pack(side="left", fill="x", expand=True)
        cmb_risk.bind("<<ComboboxSelected>>",
                      lambda e: self._refresh_tree_arbres())

        ufilt = ttk.Frame(self._filtres_avances, style="Side.TFrame")
        ufilt.pack(fill="x", pady=(0, 4))
        ttk.Label(ufilt, text=_("Urgence"), style="Side.TLabel").pack(
            side="left", padx=(0, 4))
        self.var_urgence_filter = tk.StringVar(value=_(_URGENCE_FILTER_ALL))
        self._cmb_urgence_filter = ttk.Combobox(
            ufilt, textvariable=self.var_urgence_filter,
            values=self._urgence_filter_choices(),
            state="readonly", width=12)
        self._cmb_urgence_filter.pack(side="left", fill="x", expand=True)
        self._cmb_urgence_filter.bind("<<ComboboxSelected>>",
                                      lambda e: self._refresh_tree_arbres())

        efilt = ttk.Frame(self._filtres_avances, style="Side.TFrame")
        efilt.pack(fill="x", pady=(0, 4))
        ttk.Label(efilt, text=_("Échéance"), style="Side.TLabel").pack(
            side="left", padx=(0, 4))
        self.var_echeance_filter = tk.StringVar(value=_(_ECHEANCE_FILTER_ALL))
        cmb_ech = ttk.Combobox(
            efilt, textvariable=self.var_echeance_filter,
            values=list(_echeance_filter_choices()),
            state="readonly", width=12)
        cmb_ech.pack(side="left", fill="x", expand=True)
        cmb_ech.bind("<<ComboboxSelected>>",
                     lambda e: self._refresh_tree_arbres())

        cfilt = ttk.Frame(self._filtres_avances, style="Side.TFrame")
        cfilt.pack(fill="x", pady=(0, 6))
        ttk.Label(cfilt, text=_("Sondages"), style="Side.TLabel").pack(
            side="left", padx=(0, 4))
        self.var_complet_filter = tk.StringVar(value=_(_COMPLET_FILTER_ALL))
        cmb_complet = ttk.Combobox(
            cfilt, textvariable=self.var_complet_filter,
            values=list(_complet_filter_choices()),
            state="readonly", width=12)
        cmb_complet.pack(side="left", fill="x", expand=True)
        cmb_complet.bind("<<ComboboxSelected>>",
                         lambda e: self._refresh_tree_arbres())

        # Réinitialisation directement dans le panneau (pas seulement via
        # le bandeau « filtre actif » sous la liste, qui ne s'affiche que
        # si au moins un arbre est masqué — un filtre actif qui ne masque
        # rien pour l'instant, ex. Risque=Rouge sur une mission où tous
        # les arbres sont déjà rouges, resterait sinon sans bouton visible
        # tant que le panneau est ouvert). Réutilise `_reset_all_filters`.
        ttk.Button(
            self._filtres_avances, text=_("↺ Réinitialiser les filtres"),
            style="Ghost.TButton",
            command=self._reset_all_filters,
        ).pack(fill="x", pady=(2, 0))

        self._sync_filtres_avances()  # pose le texte initial de l'en-tête

        # Bandeau "filtre actif" : apparaît sous les filtres quand au moins
        # un arbre est masqué. Purement informatif — le bouton de
        # réinitialisation vit uniquement dans le panneau Filtres avancés
        # ci-dessus (un seul bouton reset, pas deux : un doublon a été
        # remonté quand les deux étaient visibles en même temps).
        self._filtre_actif_frame = ttk.Frame(frame, style="Side.TFrame")
        self._lbl_filtre_actif = ttk.Label(
            self._filtre_actif_frame, text="",
            style="Side.TLabel", foreground=COLOR_ACCENT,
            font=font_small_italic())
        self._lbl_filtre_actif.pack(side="left", padx=(0, 6))

        lst_frame = ttk.Frame(frame, style="Side.TFrame")
        self._lst_frame = lst_frame
        self.tree_arbres = ttk.Treeview(
            lst_frame, columns=("ess", "etat", "risque"),
            show="tree headings", height=20, style="Side.Treeview")
        self.tree_arbres.heading("#0", text=_("Nom"))
        self.tree_arbres.heading("ess", text=_("Essence"))
        self.tree_arbres.heading("etat", text=_("État"))
        self.tree_arbres.heading("risque", text=_("Risque"))
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
            label=_("Renommer…"), command=self.action_rename_arbre)
        self._tree_arbres_ctx_menu.add_command(
            label=_("Dupliquer"), command=self.action_dup_arbre)
        self._tree_arbres_ctx_menu.add_separator()
        self._tree_arbres_ctx_menu.add_command(
            label=_("Supprimer…"), command=self.action_del_arbre)
        # `<FocusOut>` ferme le menu si l'utilisateur clique en dehors
        # (sur Linux/X11, `tk_popup` ne pose pas de grab automatique →
        # sans ce binding, le menu reste affiché). Le menu doit pouvoir
        # prendre le focus pour que l'événement soit déclenché : Tk le
        # fait quand le menu est posté.
        self._tree_arbres_ctx_menu.bind(
            "<FocusOut>",
            lambda e: self._tree_arbres_ctx_menu.unpost())
        self.tree_arbres.bind("<Button-3>", self._on_tree_arbres_right_click)
        Tooltip(self.tree_arbres,
                _("Ctrl+PgBas / Ctrl+PgHaut → arbre suivant / précédent\n"
                "Double-clic → renommer · Clic droit → menu contextuel"))

        # Éléments du bas packés en side="bottom" AVANT lst_frame (sinon
        # lst_frame avec expand=True les pousserait hors de l'écran quand le
        # bandeau filtre actif agrandit la zone des filtres). Ordre inverse
        # de l'ordre visuel : le premier packé en bottom est le plus bas.
        btns = ttk.Frame(frame, style="Side.TFrame")
        btns.pack(side="bottom", fill="x", pady=(10, 0))
        # Rangée 1 : bouton d'ajout toujours visible (1 clic)
        row_add = ttk.Frame(btns, style="Side.TFrame")
        row_add.pack(fill="x", pady=(0, 4))
        btn_vierge = ttk.Button(row_add, text=_("＋ Ajouter"),
                                style="Accent.TButton",
                                command=self.action_add_arbre)
        btn_vierge.pack(side="left")
        Tooltip(btn_vierge, _("Ajouter un arbre vierge") + " (Ctrl+T)")
        # Rangée 2 : actions secondaires
        row_sec = ttk.Frame(btns, style="Side.TFrame")
        row_sec.pack(fill="x")
        ttk.Button(row_sec, text=_("Dupliquer"), style="Ghost.TButton",
                   command=self.action_dup_arbre).pack(side="left")
        ttk.Button(row_sec, text=_("Supprimer"), style="Ghost.TButton",
                   command=self.action_del_arbre).pack(side="left",
                                                       padx=(6, 0))

        # Triage de fin de mission : saute au prochain arbre incomplet
        # (pendant du compteur « N à finir » juste au-dessous).
        btn_afinir = ttk.Button(
            frame, text=_("⏭ Prochain arbre à finir"), style="Ghost.TButton",
            command=self.action_next_a_finir)
        btn_afinir.pack(side="bottom", anchor="w", pady=(4, 0))
        Tooltip(btn_afinir, _("Sélectionne le prochain arbre au diagnostic "
                            "non fiable (rayon manquant ou < 3 sondages), "
                            "en bouclant. Vide les filtres si besoin."))

        # Footer = vue de triage macro (répartition rouge/orange/vert/à
        # finir) — cf. `_update_etat_footer`. Wrap pour tenir dans le
        # panneau gauche étroit.
        self.lbl_etat_footer = ttk.Label(
            frame, text="", style="Side.TLabel", wraplength=250,
            justify="left", font=font_small_italic())
        self.lbl_etat_footer.pack(side="bottom", anchor="w", pady=(6, 0))

        lst_frame.pack(fill="both", expand=True)

    def _count_filtres_avances_actifs(self) -> int:
        """Nombre de filtres « avancés » actifs (hors recherche texte,
        toujours visible) — alimente le compteur de l'en-tête replié."""
        n = 0
        if self.var_risk_filter.get() != _(_RISK_FILTER_ALL):
            n += 1
        if self.var_urgence_filter.get() != _(_URGENCE_FILTER_ALL):
            n += 1
        if self.var_echeance_filter.get() != _(_ECHEANCE_FILTER_ALL):
            n += 1
        if self.var_complet_filter.get() != _(_COMPLET_FILTER_ALL):
            n += 1
        return n

    def _toggle_filtres_avances(self) -> None:
        """Replie/déplie le panneau des filtres avancés."""
        self._filtres_avances_expanded = not self._filtres_avances_expanded
        self._sync_filtres_avances()

    def _sync_filtres_avances(self) -> None:
        """Reflète l'état courant : flèche + compteur de l'en-tête,
        visibilité du panneau. Appelé à chaque `_refresh_tree_arbres` pour
        que le compteur reste juste même quand un filtre change sans
        passer par le clic sur l'en-tête (combobox, réinitialisation)."""
        n = self._count_filtres_avances_actifs()
        fleche = "▾" if self._filtres_avances_expanded else "▸"
        texte = _("Filtres avancés")
        if n:
            texte += f" ({n})"
        self._lbl_filtres_toggle.configure(
            text=f"{texte}  {fleche}",
            foreground=COLOR_ACCENT if n else "")
        if self._filtres_avances_expanded:
            if not self._filtres_avances.winfo_ismapped():
                self._filtres_avances.pack(fill="x", pady=(0, 0),
                                           before=self._lst_frame)
        else:
            self._filtres_avances.pack_forget()

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
        self._brin_bar_lbl = ttk.Label(
            self.brin_bar, text=_("Brin :"), style="BrinBar.TLabel")
        self._brin_bar_lbl.pack(side="left", padx=(0, 8), pady=7)
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
        # nb n'est PAS packagé ici : affiché seulement quand des arbres
        # existent (_refresh_welcome_visibility bascule entre welcome et nb).

        # Écran de bienvenue : affiché quand la mission est vide.
        self._welcome_frame = ttk.Frame(frame, style="Panel.TFrame")
        _inner = ttk.Frame(self._welcome_frame, style="Panel.TFrame")
        _inner.place(relx=0.5, rely=0.44, anchor="center")
        ttk.Label(
            _inner, text="Pénétromètre Silvavenir",
            font=ui_font("Georgia", 28), style="Panel.TLabel",
        ).pack(pady=(0, 2))
        ttk.Label(
            _inner, text=_("  Expertise arboricole"),
            font=ui_font("Helvetica", 12), style="Sub.TLabel",
        ).pack(pady=(0, 28))
        ttk.Label(
            _inner,
            text=_("Créez ou ouvrez une mission pour commencer."),
            font=ui_font("Helvetica", 11), style="Muted.TLabel",
        ).pack(pady=(0, 18))
        _btns = ttk.Frame(_inner, style="Panel.TFrame")
        _btns.pack()
        _btn_new = ttk.Button(
            _btns, text=_("Nouvelle mission"), style="Accent.TButton",
            command=cast("App", self).action_new,
        )
        _btn_new.pack(side="left", padx=8)
        Tooltip(_btn_new, "Ctrl+N")
        _btn_open = ttk.Button(
            _btns, text=_("Ouvrir mission…"),
            command=cast("App", self).action_open,
        )
        _btn_open.pack(side="left", padx=8)
        Tooltip(_btn_open, "Ctrl+O")
        self._welcome_frame.pack(fill="both", expand=True)

        # Les panes attendent un `host` satisfaisant leur Protocol (toute
        # la surface d'`App`). `self` est ici typé `LayoutMixin` ; le cast
        # rétablit le type réel au runtime — `App` — pour mypy (no-op à
        # l'exécution, l'objet EST l'App).
        host = cast("App", self)

        # Onglet Identification — extrait dans son propre pane (cf.
        # pane_identification.py). Le pane possède ses 10 StringVars,
        # la règle de cohérence Ø ↔ Rayon et la synchro UI ↔ modèle.
        self.pane_id = IdentificationPane(nb, host=host)
        nb.add(self.pane_id, text=_("Identification"))

        # Onglet Sondages — extrait dans son propre pane (cf.
        # pane_sondages.py).
        self.pane_s = SondagesPane(nb, host=host)
        nb.add(self.pane_s, text=_("Sondages"))

        # Onglet Dégradations externes — extrait dans son propre pane
        # (cf. pane_degradations.py).
        self.pane_de = DegradationsPane(nb, host=host)
        nb.add(self.pane_de, text=_("Dégrad. externes"))

        # Onglet Contreforts — extrait dans son propre pane (cf.
        # pane_contreforts.py) : le pane possède sa table, ses boutons,
        # son refresh et ses actions add/edit/del.
        self.pane_cf = ContrefortsPane(nb, host=host)
        nb.add(self.pane_cf, text=_("Contreforts"))

        # Onglet Diagnostic — extrait dans son propre pane (cf.
        # pane_diagnostic.py). Le pane possède son sous-canvas
        # scrollable, son résumé, la checkbox show_sondages, le tableau
        # PRBS et la préconisation. Les exports n'y sont plus (→ menu
        # Export de la barre de menu, cf. `app_menu.py`).
        self.pane_diag = DiagnosticPane(nb, host=host)
        nb.add(self.pane_diag, text=_("Diagnostic"))

    def _build_right(self, parent: tk.PanedWindow) -> None:
        frame = ttk.Frame(parent, style="Panel.TFrame", padding=10)
        parent.add(frame, minsize=360, width=460, stretch="always")
        self.section = SectionCanvas(frame, host=cast("App", self),
                                      width=550, height=550)
        self.section.pack(fill="both", expand=True)
        # Contrôle d'affichage : cohabite avec le dessin (visible quel
        # que soit l'onglet actif, plutôt que caché dans l'onglet
        # Diagnostic).
        self.var_show_sondages = tk.BooleanVar(value=True)
        # `trace_add` (et non `command=` sur ce seul Checkbutton) : la
        # fenêtre de comparaison (`comparaison.open_comparison`) porte sa
        # PROPRE case cochée sur cette MÊME `BooleanVar` (partagée, un seul
        # interpréteur Tcl pour toute l'app) pour ne pas avoir à changer de
        # fenêtre — `command=` n'aurait réagi qu'aux clics sur CE
        # Checkbutton-ci, pas à ceux de l'autre fenêtre sur la même variable.
        self.var_show_sondages.trace_add(
            "write",
            lambda *_a: self.section.set_show_sondages(
                self.var_show_sondages.get()))
        ttk.Checkbutton(
            frame,
            text=_("Afficher l'emplacement des sondages sur le dessin"),
            variable=self.var_show_sondages,
            style="Panel.TCheckbutton",
        ).pack(anchor="w", pady=(6, 0))
        # Indice de découvrabilité : le canevas est interactif (clic sur
        # un élément = édition, clic sur une direction vide = ajout).
        # Rien ne le signalait a priori — d'où ce rappel, repliable.
        AideRepliable(
            frame,
            _("Cliquez un élément du dessin pour le modifier, "
              "ou une direction libre pour ajouter un sondage."),
            wraplength=440,
        ).pack(anchor="w", pady=(2, 0))
        # Indice visible quand l'arbre n'a aucun sondage : guide le premier
        # geste de saisie sans devoir déplier l'aide. Disparaît dès que le
        # premier sondage est ajouté.
        self._lbl_canvas_hint = ttk.Label(
            frame,
            text=_("→ Cliquer sur une direction libre du dessin pour ajouter un sondage"),
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
        # Bannière de mise à jour : cachée par défaut, packée side="bottom"
        # par _on_update_result (elle s'insère alors AU-DESSUS de la barre
        # d'état grâce à l'ordre de packing Tk).
        self._update_banner = ttk.Frame(self, style="Side.TFrame",
                                        padding=(10, 3))
        self._update_banner_lbl = ttk.Label(
            self._update_banner, text="",
            style="Side.TLabel", foreground=COLOR_ACCENT,
            font=font_small_bold())
        self._update_banner_lbl.pack(side="left")
        self._update_banner_url = ""
        ttk.Button(
            self._update_banner, text=_("Télécharger"), style="Accent.TButton",
            command=self._open_update_url,
        ).pack(side="left", padx=(10, 0))
        ttk.Button(
            self._update_banner, text=ICON_DELETE, style="Ghost.TButton",
            command=self._dismiss_update_banner,
        ).pack(side="right")

        # Bannière « redémarrage requis » : certains réglages (langue,
        # taille du texte, contraste) ne s'appliquent pleinement qu'au
        # prochain lancement. Plutôt qu'un message passif en barre d'état
        # (manqué) ou un modal à chaque changement (intrusif quand on
        # compare des tailles), on affiche une bande non-modale avec un
        # bouton de redémarrage direct. Cachée par défaut, packée
        # side="bottom" par _show_restart_banner.
        self._restart_banner = ttk.Frame(self, style="Side.TFrame",
                                         padding=(10, 3))
        ttk.Label(
            self._restart_banner,
            text=_("⟳ Redémarrez pour appliquer entièrement les changements."),
            style="Side.TLabel", foreground=COLOR_WARN,
            font=font_small_bold()).pack(side="left")
        ttk.Button(
            self._restart_banner, text=_("Redémarrer maintenant"),
            style="Accent.TButton", command=self.action_restart,
        ).pack(side="left", padx=(10, 0))
        ttk.Button(
            self._restart_banner, text=ICON_DELETE, style="Ghost.TButton",
            command=self._dismiss_restart_banner,
        ).pack(side="right")

        # Bannière mode essai : affichée durant les 30 jours d'essai, non
        # dismissable (rappel permanent de l'état non-licencié). Packée
        # side="bottom" par _show_trial_banner.
        self._trial_banner = ttk.Frame(self, style="Side.TFrame",
                                       padding=(10, 3))
        self._trial_banner_lbl = ttk.Label(
            self._trial_banner, text="",
            style="Side.TLabel", foreground=COLOR_WARN,
            font=font_small_bold())
        self._trial_banner_lbl.pack(side="left")
        ttk.Button(
            self._trial_banner, text=_("Activer une licence"),
            style="Accent.TButton",
            command=self._action_activate_from_trial,
        ).pack(side="left", padx=(12, 0))

        bar = ttk.Frame(self, style="Side.TFrame")
        bar.pack(side="bottom", fill="x")
        # Bouton Enregistrer TOUJOURS visible : le menu / Ctrl+S ne donne
        # aucun repère permanent à l'opérateur terrain (« ai-je enregistré ? »).
        # Icône bitmap plutôt que le préfixe emoji « 💾 » sur Windows
        # (2026-09-06, cf. `chrome_icons.py`) : rendu couleur surdimensionné
        # confirmé sur un test Windows réel, mais rendu correct constaté sur
        # Linux/macOS — pas de raison de le retirer là où il fonctionne.
        if sys.platform == "win32":
            self._btn_save = ttk.Button(
                bar, image=save_icon(), text=_("Enregistrer"),
                compound="left", style="Ghost.TButton",
                command=self.action_save)
        else:
            self._btn_save = ttk.Button(bar, text=_("💾 Enregistrer"),
                                        style="Ghost.TButton",
                                        command=self.action_save)
        self._btn_save.pack(side="left", padx=(10, 6), pady=2)
        Tooltip(self._btn_save, _("Enregistrer la mission") + " (Ctrl+S)")
        # Indicateur d'état d'enregistrement, mis à jour à chaque mutation
        # (le « • » du titre est trop discret, et masquable par le WM).
        self.lbl_save_state = ttk.Label(
            bar, text="", style="Side.TLabel",
            font=font_small_bold())
        self.lbl_save_state.pack(side="left", padx=(0, 14), pady=3)
        self.lbl_status = ttk.Label(bar, text=_("Prêt."), style="Side.TLabel",
                                    font=font_small())
        self.lbl_status.pack(side="left", padx=(0, 12), pady=3)
        self._btn_open_folder = ttk.Button(
            bar, text=_("Ouvrir le dossier"), style="Ghost.TButton",
            command=self._open_last_export_folder, state="disabled")
        self._btn_open_folder.pack(side="right", padx=(0, 10), pady=2)
        self._btn_open_file = ttk.Button(
            bar, text=_("Ouvrir le fichier"), style="Ghost.TButton",
            command=self._open_last_export_file, state="disabled")
        self._btn_open_file.pack(side="right", padx=(0, 4), pady=2)
        self._update_save_indicator()
