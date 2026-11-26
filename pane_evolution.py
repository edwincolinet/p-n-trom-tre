"""
Onglet « Évolution » : comparaison de deux relevés d'un arbre, directement
dans la fenêtre principale.

Les relevés viennent de l'historique de la mission (`campagnes.serie`) :
aucun second fichier à charger. L'onglet porte la **sélection des deux
dates**, source unique pour le dessin (modes « Précédent » et « Évolution »,
cf. `VueDessin`) et pour les exports (`constructeur_export`).

Deux réponses distinctes, jamais fusionnées : la **dégradation** (a-t-elle
progressé ?) et l'**état** à chaque date (t/R minimal, classe). Les calculs
viennent de `evolution`/`diagnostic_comparaison`, les images de
`comparaison_render`.

L'onglet n'est reconstruit que lorsqu'il est visible (`rafraichir`).
"""

from __future__ import annotations

import copy
import dataclasses
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Any, Callable, List, Optional, Protocol, Sequence, Tuple

import angle_units
from campagnes import serie
from comparaison_render import (
    PHOTOS_COMPARAISON_MAX,
    PTS_LEGENDE,
    metric_rows,
    render_brin_section,
    render_comparison_pages,
    render_evolution_pngs,
    render_evolution_section_brin,
    verdict_couleur,
)
from diagnostic_comparaison import (
    ComparaisonDetail,
    comparaison_par_brin,
    evolution_degradation,
    verdict_lignes,
)
from dialogs_shared import annees_entre
from evolution import (
    EPS_CM,
    Alerte,
    Campagne,
    Conclusion,
    DirectionDelta,
    comparer_campagnes,
    etat_brin,
    suivre,
)
from i18n import _
from model import Arbre, Brin, Chantier
from palette import COLOR_ACCENT, COLOR_INK, COLOR_MUTED, COLOR_PANEL
from photo_gallery import PhotoGallery
from ui_fonts import font_body_bold, font_small_bold, font_subheading

MODES = ("actuel", "precedent", "evolution")


class _EvolutionHost(Protocol):
    chantier: Chantier
    current_file: Optional[Path]
    var_show_sondages: tk.BooleanVar

    def _current_arbre(self) -> Optional[Arbre]: ...
    def _current_brin(self) -> Optional[Brin]: ...
    def push_undo(self) -> None: ...
    def on_identification_changed(self, *, rayon_adjusted: bool) -> None: ...
    def on_evolution_dates_changed(self) -> None: ...
    def action_nouvelle_campagne(self) -> None: ...
    def action_importer_releve(self) -> None: ...


def _libelle_date(campagne: Campagne, courante: bool) -> str:
    date = campagne.date or _("non datée")
    return f"{date} ({_('en cours')})" if courante else date


def _paire_du_brin(ref: Campagne, cur: Campagne, brin: Optional[Brin]
                   ) -> "Tuple[str, Brin, Optional[Brin], ComparaisonDetail]":
    """Comparaison du brin `brin` (à défaut le premier du relevé récent)."""
    paires = comparaison_par_brin(
        ref.arbre, cur.arbre, annees_entre(ref.date, cur.date))
    return next((p for p in paires
                 if brin is not None and p[1].id == brin.id), paires[0])


def _cellule_cavite(d: DirectionDelta) -> str:
    if d.progression > EPS_CM:
        return f"▲ +{d.progression:.1f}"
    if d.anomalie:
        return _("? à vérifier")
    if d.recouverte:
        return _("✓ recouverte")
    if d.non_resondee:
        return _("non re-sondée")
    if not d.evaluee:
        return "—"
    return "="


class EvolutionPane(ttk.Frame):
    """Pane Tk autonome : dates, verdict, détail, chronologie, photos."""

    def __init__(self, master: tk.Misc, host: _EvolutionHost,
                 **kw: Any) -> None:
        super().__init__(master, style="Panel.TFrame", **kw)
        self._host = host
        self._arbre_id = ""
        self._dates: List[str] = []
        self._i_ref = 0
        self._i_cur = 0
        self._galeries: List[PhotoGallery] = []
        self._build()

    # --- Sélection ------------------------------------------------------

    def _serie(self) -> List[Campagne]:
        a = self._host._current_arbre()
        if a is None or not a.campagnes:
            return []
        return serie(a, self._host.chantier.date_releve)

    def selection(self) -> Optional[Tuple[Campagne, Campagne]]:
        """Les deux relevés comparés (ancien, récent), ou `None` sans
        historique. Par défaut : le dernier relevé archivé et l'actuel ; le
        choix de l'expert est gardé tant que l'arbre et ses dates ne
        changent pas."""
        campagnes = self._serie()
        if not campagnes:
            self._arbre_id = ""
            return None
        a = self._host._current_arbre()
        assert a is not None
        dates = [c.date for c in campagnes]
        if a.id != self._arbre_id or dates != self._dates:
            self._arbre_id, self._dates = a.id, dates
            self._i_ref, self._i_cur = len(campagnes) - 2, len(campagnes) - 1
        return campagnes[self._i_ref], campagnes[self._i_cur]

    def choisir(self, i_ref: int, i_cur: int) -> None:
        """Sélectionne deux relevés par leur rang chronologique ; l'ordre
        est rétabli si l'ancien est choisi après le récent."""
        if self.selection() is None or i_ref == i_cur:
            return
        self._i_ref, self._i_cur = sorted((i_ref, i_cur))
        self.rafraichir()
        self._host.on_evolution_dates_changed()

    # --- Construction ---------------------------------------------------

    def _build(self) -> None:
        canvas = tk.Canvas(self, bg=COLOR_PANEL, highlightthickness=0, bd=0)
        scroll = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        contenu = ttk.Frame(canvas, style="Panel.TFrame", padding=10)
        fenetre = canvas.create_window((0, 0), window=contenu, anchor="nw")
        contenu.bind("<Configure>", lambda _e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(
            fenetre, width=e.width))

        # Molette : active seulement quand le pointeur est sur l'onglet.
        def _molette(e: Any) -> None:
            if e.num in (4, 5):
                canvas.yview_scroll(-1 if e.num == 4 else 1, "units")
            else:
                canvas.yview_scroll(int(-e.delta / 120), "units")

        def _activer(_e: Any) -> None:
            for s in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                canvas.bind_all(s, _molette)

        def _desactiver(_e: Any) -> None:
            for s in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                canvas.unbind_all(s)

        canvas.bind("<Enter>", _activer)
        canvas.bind("<Leave>", _desactiver)
        self._canvas = canvas

        # Sans historique : explication et les deux façons d'en créer un.
        self._vide = ttk.Frame(contenu, style="Panel.TFrame")
        ttk.Label(self._vide, text=_(
            "Cet arbre n'a pas de relevé antérieur. Pour suivre son "
            "évolution :"), style="Panel.TLabel", wraplength=420,
            justify="left").pack(anchor="w", pady=(0, 8))
        ttk.Button(self._vide, text=_("Nouvelle campagne…"),
                   command=self._host.action_nouvelle_campagne
                   ).pack(anchor="w")
        ttk.Button(self._vide, text=_("Importer un relevé antérieur…"),
                   command=self._host.action_importer_releve
                   ).pack(anchor="w", pady=(6, 0))

        corps = self._corps = ttk.Frame(contenu, style="Panel.TFrame")
        dates = ttk.Frame(corps, style="Panel.TFrame")
        dates.pack(fill="x")
        ttk.Label(dates, text=_("Comparer"), style="Panel.TLabel"
                  ).pack(side="left", padx=(0, 6))
        self._cmb_ref = ttk.Combobox(dates, state="readonly", width=16)
        self._cmb_ref.pack(side="left")
        ttk.Label(dates, text="→", style="Panel.TLabel"
                  ).pack(side="left", padx=6)
        self._cmb_cur = ttk.Combobox(dates, state="readonly", width=22)
        self._cmb_cur.pack(side="left")
        for cmb in (self._cmb_ref, self._cmb_cur):
            cmb.bind("<<ComboboxSelected>>", lambda _e: self.choisir(
                self._cmb_ref.current(), self._cmb_cur.current()))

        def _titre(texte: str) -> None:
            ttk.Label(corps, text=texte, style="Panel.TLabel",
                      font=font_subheading()).pack(anchor="w", pady=(14, 4))

        def _paragraphe(style: str = "Panel.TLabel", **kw: Any) -> ttk.Label:
            lbl = ttk.Label(corps, style=style, wraplength=420,
                            justify="left", **kw)
            lbl.pack(anchor="w")
            return lbl

        _titre(_("Dégradation"))
        self._lbl_brin = _paragraphe("Muted.TLabel")
        self._lbl_verdict = _paragraphe(font=font_body_bold())
        self._lbl_detail = _paragraphe()

        _titre(_("État à chaque date"))
        self._lbl_etat = _paragraphe()

        _titre(_("Par direction"))
        self._tbl_dir = self._tableau(corps, (
            ("dir", _("Direction"), 70), ("ref", _("PRBS préc."), 80),
            ("cur", _("PRBS"), 70), ("croissance", _("Croissance"), 85),
            ("cavite", _("Cavité"), 110)))

        _titre(_("Chiffres"))
        self._tbl = self._tableau(corps, (
            ("ind", _("Indicateur"), 170), ("ref", _("Ancien"), 80),
            ("cur", _("Récent"), 80), ("evo", _("Évolution"), 150)))
        _paragraphe("Muted.TLabel").configure(text=PTS_LEGENDE)

        self._chrono = ttk.Frame(corps, style="Panel.TFrame")
        self._chrono.pack(fill="x")
        ttk.Label(self._chrono, text=_("Chronologie"), style="Panel.TLabel",
                  font=font_subheading()).pack(anchor="w", pady=(14, 4))
        self._tbl_chrono = self._tableau(self._chrono, (
            ("date", _("Date"), 90), ("tr", _("t/R minimal"), 90),
            ("classe", _("Classe"), 70), ("conclusion", _("Depuis le précédent"),
                                          170)))
        self._courbe = tk.Canvas(self._chrono, height=110, bg=COLOR_PANEL,
                                 highlightthickness=0)
        self._courbe.pack(fill="x", pady=(4, 0))
        self._courbe.bind("<Configure>", lambda _e: self._tracer_courbe())
        self._points: List[Tuple[str, float]] = []

        self._titre_photos = ttk.Label(
            corps, text=_("Photos de la comparaison"), style="Panel.TLabel",
            font=font_subheading())
        self._titre_photos.pack(anchor="w", pady=(14, 4))
        _paragraphe("Muted.TLabel").configure(text=_(
            "Reprises dans le PDF (page « Évolution photographique », {n} "
            "photos maximum par colonne).").format(n=PHOTOS_COMPARAISON_MAX))
        self._zone_photos = ttk.Frame(corps, style="Panel.TFrame")
        self._zone_photos.pack(fill="x")
        for titre in (_("Photos du relevé antérieur"),
                      _("Photos du relevé récent")):
            galerie = PhotoGallery(
                self._zone_photos, photos=[], on_change=self._photos_changees,
                get_mission_file=lambda: self._host.current_file,
                on_before_change=self._host.push_undo, title=titre)
            galerie.pack(fill="x", pady=(4, 0))
            self._galeries.append(galerie)

    @staticmethod
    def _tableau(parent: tk.Misc,
                 colonnes: "Tuple[Tuple[str, str, int], ...]") -> ttk.Treeview:
        tbl = ttk.Treeview(parent, columns=[c for c, _t, _w in colonnes],
                           show="headings", height=1)
        for cle, titre, largeur in colonnes:
            tbl.heading(cle, text=titre)
            tbl.column(cle, width=largeur, anchor="w")
        tbl.pack(fill="x")
        return tbl

    @staticmethod
    def _remplir(tbl: ttk.Treeview, lignes: "Sequence[Tuple[str, ...]]") -> None:
        tbl.delete(*tbl.get_children())
        for ligne in lignes:
            tbl.insert("", "end", values=ligne)
        tbl.configure(height=max(1, len(lignes)))

    def _photos_changees(self) -> None:
        self._host.on_identification_changed(rayon_adjusted=False)

    # --- Rafraîchissement -----------------------------------------------

    def rafraichir(self) -> None:
        choisis = self.selection()
        if choisis is None:
            self._corps.pack_forget()
            self._vide.pack(anchor="w", fill="x")
            return
        self._vide.pack_forget()
        self._corps.pack(fill="x")
        ref, cur = choisis
        campagnes = self._serie()
        libelles = [_libelle_date(c, i == len(campagnes) - 1)
                    for i, c in enumerate(campagnes)]
        for cmb, rang in ((self._cmb_ref, self._i_ref),
                          (self._cmb_cur, self._i_cur)):
            cmb.configure(values=libelles)
            cmb.current(rang)

        label, cur_b, _ref_b, detail = _paire_du_brin(
            ref, cur, self._host._current_brin())
        suivi = suivre(campagnes)
        notes = []
        if len(cur.arbre.brins) > 1:
            notes.append(_("Brin {label}").format(label=label))
        if any(Alerte.BRIN_DISPARU in b.alertes
               for b in comparer_campagnes(ref, cur).brins):
            notes.append(_("Un brin du relevé antérieur n'existe plus."))
        self._lbl_brin.configure(text="  ·  ".join(notes))

        titre, precisions = verdict_lignes(detail)
        couleur = verdict_couleur(detail) or (
            COLOR_MUTED if evolution_degradation(detail) is None
            else COLOR_INK)
        self._lbl_verdict.configure(text=titre, foreground=couleur)
        self._lbl_detail.configure(text=precisions)

        def _etat(classe: Optional[str], tr: Optional[float]) -> str:
            if classe is None or tr is None:
                return _("non publié")
            return f"{classe} — t/R {tr:.1f} %"

        self._lbl_etat.configure(text="\n".join((
            f"{ref.date} : {_etat(detail.classe_ref, detail.tR_min_ref)}",
            f"{cur.date} : {_etat(detail.classe_cur, detail.tR_min_cur)}")))

        self._remplir(self._tbl_dir, [
            (f"{d.direction} ({angle_units.fmt(d.grade)})",
             f"{d.prbs_ref:.1f}", f"{d.prbs_cur:.1f}",
             f"{d.croissance:+.1f}", _cellule_cavite(d))
            for d in detail.directions
            if (d.evaluee or d.non_resondee)
            and not detail.hauteurs_incompatibles])
        self._remplir(self._tbl, list(metric_rows(detail)))
        self._rafraichir_chronologie(suivi.campagnes, suivi.intervalles)
        self._rafraichir_photos()

    def _rafraichir_chronologie(self, campagnes: List[Campagne],
                                intervalles: List[Any]) -> None:
        if len(campagnes) < 3:
            self._chrono.pack_forget()
            return
        self._chrono.pack(fill="x", before=self._titre_photos)
        conclusions = {
            Conclusion.PROGRESSION: _("▲ progression"),
            Conclusion.A_VERIFIER: _("? à vérifier"),
            Conclusion.NON_COMPARABLE: _("non comparable"),
            Conclusion.NON_EVALUABLE: _("non évaluable"),
            Conclusion.RECOUVREMENT: _("✓ recouvrement"),
            Conclusion.STABLE: _("= pas de progression")}
        brin = self._host._current_brin()
        lignes, points = [], []
        for i, campagne in enumerate(campagnes):
            # État du brin suivi à cette date (s'il y figure).
            releve = campagne.arbre
            suivi_b = next((b for b in releve.brins
                            if brin is not None and b.id == brin.id), None)
            classe, tr = (etat_brin(suivi_b, releve.port_arbre)
                          if suivi_b is not None else (None, None))
            lignes.append((
                campagne.date or "—",
                f"{tr:.1f} %" if tr is not None else "—", classe or "—",
                conclusions[intervalles[i - 1].conclusion] if i else ""))
            if tr is not None:
                points.append((campagne.date, tr))
        self._remplir(self._tbl_chrono, lignes)
        self._points = points
        self._tracer_courbe()

    def _tracer_courbe(self) -> None:
        """t/R minimal dans le temps (relevés à intervalles réguliers)."""
        c = self._courbe
        c.delete("all")
        if len(self._points) < 2:
            return
        largeur = max(c.winfo_width(), 200)
        hauteur = int(c.cget("height"))
        haut = max(tr for _d, tr in self._points) * 1.15 or 1.0
        pas = (largeur - 60) / (len(self._points) - 1)
        xy = [(30 + i * pas, hauteur - 20 - (hauteur - 40) * tr / haut)
              for i, (_d, tr) in enumerate(self._points)]
        c.create_line(*[v for p in xy for v in p], fill=COLOR_ACCENT, width=2)
        for (x, y), (date, tr) in zip(xy, self._points):
            c.create_oval(x - 3, y - 3, x + 3, y + 3, fill=COLOR_ACCENT,
                          outline="")
            c.create_text(x, y - 10, text=f"{tr:.0f} %", fill=COLOR_INK,
                          font=font_small_bold())
            c.create_text(x, hauteur - 8, text=date[-4:], fill=COLOR_MUTED,
                          font=font_small_bold())

    def _rafraichir_photos(self) -> None:
        a = self._host._current_arbre()
        assert a is not None
        for galerie, liste in zip(self._galeries, (a.photos_comparaison_ref,
                                                   a.photos_comparaison_cur)):
            if galerie._photos is not liste:
                galerie.reload(liste)

    # --- Dessin et exports ------------------------------------------------

    def image(self, mode: str, taille: int, show_sondages: bool) -> Any:
        """Image PIL du dessin pour `mode` (« precedent » ou
        « evolution »), ou `None` sans historique."""
        choisis = self.selection()
        if choisis is None or mode not in MODES[1:]:
            return None
        ref, cur = choisis
        _label, cur_b, ref_b, detail = _paire_du_brin(
            ref, cur, self._host._current_brin())
        if mode == "precedent":
            if ref_b is None:
                return None
            return render_brin_section(ref.arbre, ref_b, taille,
                                       show_sondages=show_sondages)
        return render_evolution_section_brin(
            ref_b, cur_b, taille,
            non_comparable=detail.hauteurs_incompatibles is not None)

    def constructeur_export(self, fmt: str, *, cabinet_name: str,
                            logo_path: Optional[str]
                            ) -> Optional[Callable[[], Any]]:
        """Closure qui rend le contenu à exporter pour les dates choisies :
        pages du PDF (`fmt="pdf"`) ou images d'évolution (`"png"`). `None`
        sans historique. Tout est relu à l'appel de la closure : la mission
        a pu être enregistrée entre-temps (chemin des photos)."""
        a = self._host._current_arbre()
        if a is None or self.selection() is None:
            return None

        def _construire() -> Any:
            choisis = self.selection()
            assert choisis is not None
            ref, cur = choisis
            show = bool(self._host.var_show_sondages.get())
            annees = annees_entre(ref.date, cur.date)
            chantier = self._host.chantier
            # Les photos de comparaison vivent sur l'arbre courant, même
            # quand le relevé récent comparé est archivé.
            recent = copy.copy(cur.arbre)
            recent.photos_comparaison_ref = a.photos_comparaison_ref
            recent.photos_comparaison_cur = a.photos_comparaison_cur
            if fmt == "png":
                return render_evolution_pngs(
                    chantier.nom, ref.arbre, recent, annees,
                    ref_label=ref.date, cur_label=cur.date,
                    show_sondages=show)
            fichier = self._host.current_file
            return render_comparison_pages(
                chantier.nom, ref.arbre, recent, annees, ref_label=ref.date,
                cur_label=cur.date, show_sondages=show,
                chantier=dataclasses.replace(chantier, date_releve=cur.date),
                mission_dir=Path(fichier).parent if fichier else None,
                cabinet_name=cabinet_name, logo_path=logo_path)

        return _construire


class VueDessin:
    """Sélecteur « Actuel | Précédent | Évolution » du dessin principal.

    Hors du mode « Actuel », une image en lecture seule recouvre le canevas
    interactif : un relevé archivé ne se modifie pas au clic."""

    def __init__(self, parent: tk.Misc, canevas: tk.Widget,
                 on_change: Callable[[], None]) -> None:
        self.mode = tk.StringVar(value="actuel")
        self.barre = ttk.Frame(parent, style="Panel.TFrame")
        for valeur, texte in zip(MODES, (_("Actuel"), _("Précédent"),
                                         _("Évolution"))):
            ttk.Radiobutton(self.barre, text=texte, value=valeur,
                            variable=self.mode, command=on_change,
                            style="Panel.TRadiobutton"
                            ).pack(side="left", padx=(0, 12))
        self._canevas = canevas
        self.image = tk.Label(parent, bg=COLOR_PANEL, bd=0,
                              compound="top", font=font_small_bold())
        self._photo: Any = None
        canevas.bind("<Configure>", lambda _e: on_change(), add="+")

    def actualiser(self, pane: EvolutionPane, show_sondages: bool) -> None:
        choisis = pane.selection()
        if choisis is None:
            self.mode.set("actuel")
            self.barre.pack_forget()
            self.image.place_forget()
            return
        if not self.barre.winfo_manager():
            self.barre.pack(anchor="w", pady=(0, 6), before=self._canevas)
        mode = self.mode.get()
        if mode == "actuel":
            self.image.place_forget()
            return
        cote = max(240, min(self._canevas.winfo_width(),
                            self._canevas.winfo_height()) - 24)
        img = pane.image(mode, cote, show_sondages)
        ref, cur = choisis
        legende = (ref.date if mode == "precedent"
                   else f"{ref.date} → {cur.date}")
        if img is None:
            self._photo = None
            legende += " — " + _("pas de brin de référence")
        else:
            from PIL import ImageTk
            self._photo = ImageTk.PhotoImage(img, master=self.image)
        self.image.configure(image=self._photo or "", text=legende)
        self.image.place(in_=self._canevas, x=0, y=0, relwidth=1,
                         relheight=1)
        self.image.lift()
