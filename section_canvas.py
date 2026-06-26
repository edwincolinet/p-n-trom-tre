"""
Rendu Tkinter de la section transversale du tronc.

Pendant non-PIL de `pil_render.render_arbre_to_pil_image` : dessine la
même section, avec la même géométrie (via les primitives partagées de
`geometry.py`), mais directement dans un `tk.Canvas` interactif —
l'aperçu temps réel de la colonne de droite de l'app.

Contenu :
- `SectionCanvas`  — sous-classe de `tk.Canvas`, expose `set_arbre()` /
  `set_show_sondages()` et orchestre les helpers `_draw_*` (un par
  couche logique, symétriques aux `_pil_draw_*` de `pil_render.py`).

Voir CLAUDE.md → tableau « Pendants Tk ↔ PIL » pour la convention :
toute modification d'une couche doit être répliquée dans les DEUX
fichiers (Tk + PIL).
"""

from __future__ import annotations

import math
import tkinter as tk
from typing import Any, Optional, Protocol, Tuple

from diagnostic import (
    compute_alteration_par_grade,
    sondage_render_data,
)
from geometry import (
    RadiusSpec,
    adaptive_ruler_step_cm,
    brins_layout,
    cardinal_label_positions,
    cavity_polygon,
    cerne_radii_px,
    contour_polygon,
    contrefort_zone_outline,
    contrefort_zones,
    degradation_externe_outline,
    radial_ruler_data,
    radial_ruler_grade,
    tick_endpoints,
)
from model import Arbre, Brin, Contrefort, DegradationExterne, Sondage
from palette import (
    COLOR_ACCENT,
    COLOR_BARK,
    COLOR_BARK_LIGHT,
    COLOR_CERNE,
    COLOR_INK,
    COLOR_MUTED,
    COLOR_PANEL,
    COLOR_ROT,
    COLOR_SOND,
    COLOR_WOOD,
    COULEUR_CLASSE,
)


class _CanvasHost(Protocol):
    """Surface attendue de l'App par le canvas interactif.

    Le canvas doit pouvoir ouvrir un dialogue d'édition pour
    sondage/dégradation/contrefort et rafraîchir les tables/dessin via
    l'App quand l'utilisateur a validé.
    """
    def open_edit_sondage(self, s: Sondage) -> None: ...
    def open_edit_degradation(self, d: DegradationExterne) -> None: ...
    def open_edit_contrefort(self, c: Contrefort) -> None: ...
    def open_add_sondage(self, grade: int) -> None: ...


class SectionCanvas(tk.Canvas):

    # ------------------------------------------------------------------
    # Constantes de layout — pixels hors-scale, tunées pour le rendu Tk.
    # Le rendu PIL a son propre jeu de constantes (cf. pil_render.py)
    # parce que le moteur de dessin diffère (font hinting, épaisseurs).
    # ------------------------------------------------------------------

    # Marges autour du tronc (`_center_and_scale`).
    MARGIN_TOP_PX = 70       # titre 24 + méta 44 + lettre N à 25 px
    MARGIN_BOTTOM_PX = 45    # lettre S à 25 px + demi-lettre + marge
    MARGIN_SIDE_PX = 50

    # Nombre de cernes de croissance dessinés à l'intérieur du tronc.
    N_CERNES = 8

    # Décalages des éléments hors-tronc (cardinales, ticks, pastilles).
    # Stockés en px puis convertis à `px/scale` au point d'usage pour
    # rester visuellement constants quel que soit le rayon.
    SONDAGE_INSET_PX = 13         # début de flèche / centre pastille
    CARDINALES_OFFSET_PX = 25     # lettres N/NE/E/SE/S/SO/O/NO
    TICK_LEN_PX = 8               # tirets de graduation des 16 grades
    BULLET_RADIUS_PX = 11         # rayon de la pastille numérotée

    # Échantillonnage du polygone d'altération (segments Catmull-Rom).
    CAVITY_SAMPLES_PER_SEGMENT = 28

    def __init__(self, master: tk.Misc,
                 host: Optional[_CanvasHost] = None, **kw: Any) -> None:
        super().__init__(master, bg=COLOR_PANEL, highlightthickness=0,
                         bd=0, **kw)
        self.arbre: Optional[Arbre] = None
        self.show_sondages: bool = True
        self._host = host
        # Géométrie du dernier rendu (cx, cy, scale, R, R_ext), mise à
        # jour à chaque `redraw`. Sert au clic sur fond pour convertir
        # un pixel cliqué en grade. `None` tant qu'aucune section
        # valide n'est dessinée (placeholder).
        self._geom: Optional[Tuple[float, float, float, float, float]] = None
        # Infobulle de commentaire (survol d'un élément interactif) :
        # fenêtre flottante + tick `after` différé, cf. `_show_comment_tip`.
        self._tip: Optional[tk.Toplevel] = None
        self._tip_after: Optional[str] = None
        self.bind("<Configure>", lambda e: self.redraw())
        # Bindings sur tags : valent pour tous les items recréés à
        # chaque redraw qui portent le tag correspondant. Le curseur
        # passe en « main » au survol pour signaler la zone cliquable, et
        # une infobulle montre le commentaire de l'objet survolé (le seul
        # endroit où ces notes par mesure sont relues).
        if host is not None:
            for tag in ("sondage_item", "degradation_item",
                         "contrefort_item"):
                self.tag_bind(tag, "<Enter>", self._on_item_enter)
                self.tag_bind(tag, "<Leave>", self._on_item_leave)
            self.tag_bind("sondage_item", "<Button-1>",
                          self._on_click_sondage)
            self.tag_bind("degradation_item", "<Button-1>",
                          self._on_click_degradation)
            self.tag_bind("contrefort_item", "<Button-1>",
                          self._on_click_contrefort)
            # Clic sur le fond (hors élément interactif) : ajoute un
            # sondage dans la direction la plus proche. Binding au
            # niveau widget — il se déclenche aussi sur les items, d'où
            # le garde par tags dans le handler (cf. `_on_click_background`).
            self.bind("<Button-1>", self._on_click_background)

    # ------------------------------------------------------------------
    # Handlers d'interaction — actifs uniquement si un host a été fourni.
    # ------------------------------------------------------------------

    def _picked_index(self, prefix: str) -> Optional[int]:
        """Renvoie l'index de l'objet métier sous le curseur, d'après les
        tags `prefix_<idx>` portés par l'item canvas cliqué."""
        for tag in self.gettags("current"):
            if tag.startswith(prefix):
                try:
                    return int(tag[len(prefix):])
                except ValueError:
                    return None
        return None

    # --- Infobulle de commentaire au survol ----------------------------

    _TIP_BG = "#FFFFE0"  # jaune pâle d'infobulle (cf. tooltip.Tooltip)

    def _hovered_comment(self) -> str:
        """Commentaire (non vide, rogné) de l'objet métier sous le curseur,
        d'après les tags `<type>_idx_<i>` de l'item « current ». Reprend
        exactement la résolution d'index des handlers de clic → cohérent
        avec le clic-pour-éditer (mono-brin)."""
        if self.arbre is None:
            return ""
        for prefix, objs in (
                ("sondage_idx_", self.arbre.sondages),
                ("degradation_idx_", self.arbre.degradations_externes),
                ("contrefort_idx_", self.arbre.contreforts)):
            idx = self._picked_index(prefix)
            if idx is not None and idx < len(objs):
                return (objs[idx].commentaire or "").strip()
        return ""

    def _on_item_enter(self, _event: "tk.Event[tk.Misc]") -> None:
        self.configure(cursor="hand2")
        text = self._hovered_comment()
        if text:
            self._hide_comment_tip()
            self._tip_after = self.after(
                450, lambda: self._show_comment_tip(text))

    def _on_item_leave(self, _event: "tk.Event[tk.Misc]") -> None:
        self.configure(cursor="")
        self._hide_comment_tip()

    def _show_comment_tip(self, text: str) -> None:
        """Affiche l'infobulle près du pointeur. Fenêtre sans bordure,
        jaune pâle, texte enveloppé (un commentaire long ne déborde pas)."""
        if self._tip is not None or not text:
            return
        x = self.winfo_pointerx() + 14
        y = self.winfo_pointery() + 16
        tip = tk.Toplevel(self)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f"+{x}+{y}")
        tk.Label(tip, text=text, justify="left", background=self._TIP_BG,
                 foreground=COLOR_INK, relief="solid", borderwidth=1,
                 font=("Helvetica", 9), padx=6, pady=3,
                 wraplength=280).pack()
        self._tip = tip

    def _hide_comment_tip(self) -> None:
        if self._tip_after is not None:
            self.after_cancel(self._tip_after)
            self._tip_after = None
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None

    # NB sur l'usage d'`after_idle` : on diffère l'ouverture du
    # dialogue à la fin du traitement du clic. Sans cela, le `tk.Toplevel`
    # + `grab_set()` créé en plein dispatch d'événement entrait en
    # conflit avec le focus du Canvas — sur Linux/X11 (GNOME/Mutter),
    # la fenêtre apparaissait vide car ses widgets n'avaient pas eu le
    # temps d'être posés avant `wait_window()`. `after_idle` rend la
    # main à la boucle Tk, qui finalise le clic puis ouvre le dialogue
    # à blanc.

    def _on_click_sondage(self, _event: "tk.Event[tk.Misc]") -> None:
        self._hide_comment_tip()
        if self._host is None or self.arbre is None:
            return
        idx = self._picked_index("sondage_idx_")
        if idx is None or idx >= len(self.arbre.sondages):
            return
        s = self.arbre.sondages[idx]
        host = self._host
        self.after_idle(lambda: host.open_edit_sondage(s))

    def _on_click_degradation(self, _event: "tk.Event[tk.Misc]") -> None:
        self._hide_comment_tip()
        if self._host is None or self.arbre is None:
            return
        idx = self._picked_index("degradation_idx_")
        if idx is None or idx >= len(self.arbre.degradations_externes):
            return
        d = self.arbre.degradations_externes[idx]
        host = self._host
        self.after_idle(lambda: host.open_edit_degradation(d))

    def _on_click_contrefort(self, _event: "tk.Event[tk.Misc]") -> None:
        self._hide_comment_tip()
        if self._host is None or self.arbre is None:
            return
        idx = self._picked_index("contrefort_idx_")
        if idx is None or idx >= len(self.arbre.contreforts):
            return
        c = self.arbre.contreforts[idx]
        host = self._host
        self.after_idle(lambda: host.open_edit_contrefort(c))

    def _grade_at_event(self, event: "tk.Event[tk.Misc]") -> Optional[int]:
        """Convertit le pixel cliqué en grade (multiple de 25, 0-375).

        Renvoie `None` si aucune section n'est dessinée ou si le clic est
        hors de la zone de la section (au-delà de l'anneau des lettres
        cardinales) — on évite ainsi d'ajouter un sondage sur un clic
        dans le titre. Inverse de `geometry.polar_to_xy` :
        `a = grade·360/400 − 90°`, sens horaire, grade 0 = Nord.
        """
        if self._geom is None:
            return None
        cx, cy, scale, _R, R_ext = self._geom
        dx = event.x - cx
        dy = event.y - cy
        dist_px = math.hypot(dx, dy)
        max_px = R_ext * scale + self.CARDINALES_OFFSET_PX
        if dist_px > max_px:
            return None
        deg = math.degrees(math.atan2(dy, dx))
        grade = round((deg + 90.0) * 400.0 / 360.0 / 25.0) * 25
        return int(grade % 400)

    def _on_click_background(self, event: "tk.Event[tk.Misc]") -> None:
        """Clic sur le fond du dessin : ajoute un sondage dans la
        direction la plus proche (ou édite celui qui existe déjà à ce
        grade). Ignoré si le clic porte sur un élément interactif, dont
        le handler dédié (`_on_click_sondage`/`_degradation`/`_contrefort`)
        a déjà géré l'événement."""
        if self._host is None or self.arbre is None:
            return
        for tag in self.gettags("current"):
            if tag in ("sondage_item", "degradation_item",
                       "contrefort_item"):
                return
        grade = self._grade_at_event(event)
        if grade is None:
            return
        host = self._host
        existing = next((s for s in self.arbre.sondages
                         if s.grade == grade), None)
        if existing is not None:
            self.after_idle(lambda: host.open_edit_sondage(existing))
        else:
            self.after_idle(lambda: host.open_add_sondage(grade))

    def set_arbre(self, arbre: Optional[Arbre]) -> None:
        self.arbre = arbre
        self.redraw()

    def set_show_sondages(self, show: bool) -> None:
        self.show_sondages = bool(show)
        self.redraw()

    def _center_and_scale(self, R: float,
                          expansion_cm: float = 0.0
                          ) -> Tuple[float, float, float]:
        """Calcule (cx, cy, scale).

        `expansion_cm` est l'épaisseur supplémentaire à réserver autour du
        tronc pour des éléments qui dépassent du rayon (ex. contreforts).
        Le scale est ajusté pour que tronc + expansion tiennent dans la
        zone disponible.
        """
        w = max(self.winfo_width(), 1)
        h = max(self.winfo_height(), 1)
        cx = w / 2
        margin_top = self.MARGIN_TOP_PX
        margin_bottom = self.MARGIN_BOTTOM_PX
        margin_side = self.MARGIN_SIDE_PX
        available_v = h - margin_top - margin_bottom
        available_h = w - 2 * margin_side
        radius_px = min(available_h / 2, available_v / 2)
        cy = margin_top + radius_px
        R_eff = R + max(0.0, expansion_cm)
        scale = radius_px / R_eff if R_eff > 0 else 1.0
        return cx, cy, scale

    def _draw_contreforts_canvas(self, cx: float, cy: float, scale: float,
                                  R: "RadiusSpec", contreforts: Any,
                                  ep_cm: float = 0.0,
                                  R_inner: Any = None,
                                  rotation_grades: float = 0.0) -> None:
        """Dessine TOUS les contreforts en utilisant les polygones fusionnés
        renvoyés par `contrefort_zone_outline` (cf. geometry.py). Évite
        l'encoche en V à la jonction de deux contreforts proches.

        Tags : chaque zone fusionnée est cliquable et porte l'index du
        premier contrefort qu'elle contient (cas mono-CF = 99 % des
        usages). Pour les zones multi-CF, le clic ouvre le 1er ;
        l'utilisateur peut éditer les autres via l'onglet Contreforts.
        """
        if not contreforts:
            return
        for zone in contrefort_zones(contreforts):
            poly = contrefort_zone_outline(zone, contreforts, R, ep_cm,
                                            cx, cy, scale, R_inner=R_inner,
                                            rotation_grades=rotation_grades)
            wood_outer = poly["wood_outer"]
            # Identifier le premier contrefort de la zone par son
            # grade_centre (sens horaire avec wrap au grade 0).
            zone_idx = self._pick_first_contrefort_in_zone(zone, contreforts)
            wood_tags: Tuple[str, ...] = ()
            if zone_idx >= 0:
                wood_tags = ("contrefort_item",
                              f"contrefort_idx_{zone_idx}")
            if ep_cm > 0:
                # Couche d'écorce : bord interne à R (arc constant),
                # bord externe suit la cloche r_wood + ep.
                flat_bark = [coord for p in (poly["bark_outer"]
                                              + poly["bark_inner"])
                             for coord in p]
                self.create_polygon(*flat_bark, fill=COLOR_BARK,
                                    outline="", tags=wood_tags)
            # Polygone bois : noyau de bois sous l'écorce.
            flat_wood = [coord for p in (wood_outer + poly["base"])
                         for coord in p]
            self.create_polygon(*flat_wood, fill=COLOR_WOOD, outline="",
                                tags=wood_tags)
            if ep_cm == 0:
                # Pas d'écorce : trait brun en surface
                flat_outer = [coord for p in wood_outer for coord in p]
                self.create_line(*flat_outer, fill=COLOR_BARK, width=3,
                                 smooth=True, tags=wood_tags)

    @staticmethod
    def _pick_first_contrefort_in_zone(zone: Tuple[float, float],
                                        contreforts: Any) -> int:
        """Renvoie l'index dans `contreforts` du premier CF dont l'arc
        chevauche la zone (a, b). -1 si aucun (ne devrait pas arriver
        puisque les zones sont calculées depuis ces CFs)."""
        a, b = zone
        for i, c in enumerate(contreforts):
            if c.longueur_cm <= 0 or c.largeur_grades <= 0:
                continue
            demi = c.largeur_grades / 2.0
            ca = (c.grade_centre - demi) % 400
            cb = ca + c.largeur_grades
            # Chevauchement avec [a, b], gestion du wrap par décalage ±400
            for shift in (-400.0, 0.0, 400.0):
                if (ca + shift) < b and (cb + shift) > a:
                    return i
        return -1

    def _draw_degradation_externe_canvas(self, cx: float, cy: float,
                                          scale: float, R: "RadiusSpec",
                                          ep_cm: float,
                                          contreforts: Any, deg: Any,
                                          idx: int = -1,
                                          rotation_grades: float = 0.0) -> None:
        """Dessine une dégradation externe sur le canvas Tkinter à partir
        des points renvoyés par `degradation_externe_outline` (cf.
        geometry.py). `idx` (>= 0) tague le polygone pour le clic-édit."""
        points = degradation_externe_outline(deg, contreforts, R, ep_cm,
                                              cx, cy, scale,
                                              rotation_grades=rotation_grades)
        if not points:
            return
        flat = [c for p in points for c in p]
        tags: Tuple[str, ...] = ()
        if idx >= 0:
            tags = ("degradation_item", f"degradation_idx_{idx}")
        # Pas de contour : fusion visuelle avec la cavité interne
        self.create_polygon(*flat, fill=COLOR_ROT, outline="",
                            tags=tags)

    def redraw(self) -> None:
        """Orchestre le rendu de la section. Chaque couche est déléguée à
        un helper `_draw_*` ; l'ordre ci-dessous est l'ordre de
        superposition (du fond vers le dessus). Voir CLAUDE.md → « Ordre
        global des couches » pour la convention métier.
        """
        self._hide_comment_tip()
        self.delete("all")
        self._geom = None
        if not self.arbre:
            self._draw_placeholder()
            return

        A = self.arbre
        # Cépée (≥ 2 brins, ou un brin décentré) : composition multi-brins.
        # Dérivée tôt pour laisser le cas mono-brin centré (99 %) strictement
        # inchangé en dessous (goldens préservés). `_geom` reste None : le
        # clic-pour-éditer est mono-brin (interaction multi-brins = Étape 4).
        brins = A.brins
        if not (len(brins) == 1 and brins[0].pos_x_cm == 0.0
                and brins[0].pos_y_cm == 0.0):
            self._draw_cepee(A)
            return

        if A.rayon_tronc_cm <= 0:
            self._draw_placeholder()
            return

        R = A.rayon_tronc_cm
        ep = max(0.0, A.epaisseur_ecorce_cm)
        R_ext = R + ep   # rayon externe = bois + écorce
        # Réserver l'espace pour l'écorce + les contreforts (qui partent
        # de R_ext et dépassent encore de longueur_cm).
        expansion = ep + max((c.longueur_cm for c in A.contreforts),
                              default=0.0)
        cx, cy, scale = self._center_and_scale(R, expansion_cm=expansion)
        self._geom = (cx, cy, scale, R, R_ext)

        # Section elle-même (bois → pastilles + échelle radiale), centrée en
        # (cx, cy). Isolée dans `_draw_brin` pour la composition multi-brins
        # (cépées) : un appel par brin à son propre centre. Le repère partagé
        # (titre) reste global, dessiné ensuite. `port`/`meche` sont
        # genet-level (partagés par tous les brins) → passés explicitement.
        self._draw_brin(A.brin_courant, A.port_arbre, A.meche_cm,
                        cx, cy, R, ep, scale)
        self._draw_titre(A, R)

    def _draw_brin(self, brin: "Brin", port: str, meche: float,
                   cx: float, cy: float,
                   R: float, ep: float, scale: float,
                   draw_cardinales: bool = True) -> None:
        """Dessine UNE section (bois → pastilles) centrée en (cx, cy).

        Regroupe les couches **propres à un brin** dans l'ordre de
        superposition. Pour une cépée, `redraw` appellera ce helper une fois
        par brin à son centre écran ; pour un genet mono-brin centré, le
        rendu est strictement identique à l'ancien (goldens préservés).

        `port`/`meche` sont genet-level (sur l'`Arbre`) : passés explicitement
        pour positionner les sondages par brin. `draw_cardinales=False` omet
        les lettres N/E/S/O de CE brin (la cépée a une boussole globale ; les
        ticks restent par brin).
        """
        # Fournisseurs de rayon par direction : constants si circulaire
        # (rendu identique à l'ancien), variables si ellipse.
        r_of = brin.rayon_a_grade
        r_ext_of: "RadiusSpec" = (
            (lambda g: brin.rayon_a_grade(g) + ep) if ep else r_of)
        self._draw_bois_sain(brin, cx, cy, R, scale)
        self._draw_cernes(brin, cx, cy, R, scale)
        self._draw_cavite(brin, cx, cy, scale)
        self._draw_ecorce(brin, cx, cy, R, ep, scale)
        # Contreforts : R_inner descend de 1 px sous le rayon LOCAL pour
        # qu'aucun pixel de trou n'apparaisse entre polygone bois et disque.
        self._draw_contreforts_canvas(
            cx, cy, scale, r_of, brin.contreforts, ep_cm=ep,
            R_inner=(lambda g: brin.rayon_a_grade(g) - 1.0 / scale),
            rotation_grades=brin.rotation_grades)
        # Dégradations externes EN DERNIER (cf. CLAUDE.md).
        for idx, deg in enumerate(brin.degradations_externes):
            self._draw_degradation_externe_canvas(cx, cy, scale, r_of, ep,
                                                   brin.contreforts, deg,
                                                   idx=idx,
                                                   rotation_grades=brin.rotation_grades)
        self._draw_ticks(cx, cy, r_ext_of, scale)
        if draw_cardinales:
            self._draw_cardinales(cx, cy, r_ext_of, scale)
        if self.show_sondages:
            self._draw_sondages(brin, port, meche, cx, cy, R, scale)
        # Échelle radiale EN DERNIER : au premier plan pour rester lisible
        # par-dessus cavité, dégradations et flèches de sondage.
        self._draw_echelle_radiale(brin, cx, cy, scale)

    def _draw_brin_label(self, brin: "Brin", cx: float, cy: float,
                         R: float, scale: float) -> None:
        """Étiquette d'un brin (« a », « b », …) au-dessus de sa moelle, halo
        blanc pour rester lisible sur le bois. Rien si le brin n'a pas de
        label (brin unique d'un genet mono-caule)."""
        if not brin.label:
            return
        y = cy - max(6.0, R * scale * 0.45)
        for dx, dy in ((-1, -1), (-1, 1), (1, -1), (1, 1),
                       (-2, 0), (2, 0), (0, -2), (0, 2)):
            self.create_text(cx + dx, y + dy, text=brin.label,
                             font=("Georgia", 13, "bold"), fill="white")
        self.create_text(cx, y, text=brin.label,
                         font=("Georgia", 13, "bold"), fill=COLOR_ACCENT)

    def _draw_cepee(self, A: Arbre) -> None:
        """Compose une cépée : N brins positionnés dans un cadrage commun.

        Pendant Tk de `pil_render._pil_draw_cepee`. Chaque brin est dessiné à
        son centre écran (via `geometry.brins_layout`) SANS sa boussole ; une
        seule boussole globale (orientation partagée) et le titre du genet
        sont ajoutés autour de la bounding box.
        """
        drawable = [b for b in A.brins if b.rayon_tronc_cm > 0]
        if not drawable:
            self._draw_placeholder()
            return
        w = max(self.winfo_width(), 1)
        h = max(self.winfo_height(), 1)
        # Réserver la place de la boussole globale (offset + demi-largeur
        # d'une lettre) pour qu'elle ne déborde pas du canvas.
        clear = self.CARDINALES_OFFSET_PX + 18
        margin_top = max(self.MARGIN_TOP_PX, clear)
        margin_bottom = max(self.MARGIN_BOTTOM_PX, clear)
        margin_side = max(self.MARGIN_SIDE_PX, clear)
        pe = [(b.pos_x_cm, b.pos_y_cm, b.extent_cm()) for b in drawable]
        scale, origin_x, origin_y = brins_layout(
            pe, w, h, margin_top, margin_bottom, margin_side)
        # Centrage vertical (cf. `_pil_draw_cepee`) : descendre les brins
        # pour les centrer dans [margin_top, h - margin_bottom].
        y0_cm = min(py - e for _px, py, e in pe)
        y1_cm = max(py + e for _px, py, e in pe)
        bbox_h_px = (y1_cm - y0_cm) * scale
        avail_h_px = (h - margin_bottom) - margin_top
        origin_y += max(0.0, (avail_h_px - bbox_h_px) / 2.0)
        port = A.port_arbre
        meche = A.meche_cm
        for b in drawable:
            cxb = origin_x + b.pos_x_cm * scale
            cyb = origin_y + b.pos_y_cm * scale
            epb = max(0.0, b.epaisseur_ecorce_cm)
            self._draw_brin(b, port, meche, cxb, cyb, b.rayon_tronc_cm, epb,
                            scale, draw_cardinales=False)
            self._draw_brin_label(b, cxb, cyb, b.rayon_tronc_cm, scale)
        # Boussole globale sur le rectangle de la bounding box (N/S/E/O sur
        # les bords, diagonales aux coins) — cf. _pil_draw_cepee.
        x0 = min(px - e for px, _py, e in pe)
        x1 = max(px + e for px, _py, e in pe)
        y0 = min(py - e for _px, py, e in pe)
        y1 = max(py + e for _px, py, e in pe)
        x0s = origin_x + x0 * scale
        x1s = origin_x + x1 * scale
        y0s = origin_y + y0 * scale
        y1s = origin_y + y1 * scale
        cxg = (x0s + x1s) / 2.0
        cyg = (y0s + y1s) / 2.0
        off = self.CARDINALES_OFFSET_PX
        compass = (
            ("N", cxg, y0s - off), ("S", cxg, y1s + off),
            ("E", x1s + off, cyg), ("O", x0s - off, cyg),
            ("NE", x1s + off, y0s - off), ("NO", x0s - off, y0s - off),
            ("SE", x1s + off, y1s + off), ("SO", x0s - off, y1s + off),
        )
        for lbl, lx, ly in compass:
            for dx, dy in ((-1, -1), (-1, 1), (1, -1), (1, 1),
                           (-2, 0), (2, 0), (0, -2), (0, 2)):
                self.create_text(lx + dx, ly + dy, text=lbl,
                                 font=("Georgia", 13, "bold"), fill="white")
            self.create_text(lx, ly, text=lbl,
                             font=("Georgia", 13, "bold"), fill=COLOR_INK)
        self._draw_titre(A, drawable[0].rayon_tronc_cm)

    def _draw_echelle_radiale(self, brin: "Brin", cx: float, cy: float,
                              scale: float) -> None:
        """Échelle radiale d'un brin : axe gradué du centre au bord du bois,
        prolongé d'un segment d'écorce, le long de l'axe Est (ou de la
        direction libre la plus proche si un sondage y est rendu, cf.
        `geometry.radial_ruler_grade`). Dessinée au premier plan avec un
        halo blanc — pendant Tk de `_pil_draw_echelle_radiale`.

        L'esquive n'opère que si les sondages sont AFFICHÉS (case sous le
        canevas) : masqués, pas de flèche à éviter → échelle plein Est."""
        sond_grades = [s.grade for s in brin.sondages] \
            if self.show_sondages else []
        gw = radial_ruler_grade(sond_grades, brin.rotation_grades)
        # La forme du brin est pivotée de `rotation_grades` : le rayon à la
        # direction MONDE `gw` est le rayon local à `gw - rotation`.
        R = brin.rayon_a_grade(gw - brin.rotation_grades)
        if brin.est_ovale and R < brin.rayon_tronc_cm * 0.5:
            gw = float((brin.orientation_grade + brin.rotation_grades) % 400)
            R = brin.rayon_tronc_cm
        ep = max(0.0, brin.epaisseur_ecorce_cm)
        step = adaptive_ruler_step_cm(scale, min_gap_px=24)
        data = radial_ruler_data(cx, cy, scale, R, ep, gw, step,
                                 tick_len_px=8, label_offset_px=13)
        if data is None:
            return
        (x0, y0), (xr, yr) = data.axis
        segments = [(x0, y0, xr, yr, COLOR_INK, 2)]
        if data.bark is not None:
            (bx0, by0), (bx1, by1) = data.bark
            segments.append((bx0, by0, bx1, by1, COLOR_BARK, 2))
        # Passe 1 : halo blanc sous tous les traits (axe + écorce + tirets).
        for x1, y1, x2, y2, _col, w in segments:
            self.create_line(x1, y1, x2, y2, fill="white", width=w + 4)
        for x1, y1, x2, y2, _lx, _ly, _lbl in data.ticks:
            self.create_line(x1, y1, x2, y2, fill="white", width=5)
        # Passe 2 : encre.
        for x1, y1, x2, y2, col, w in segments:
            self.create_line(x1, y1, x2, y2, fill=col, width=w)
        for x1, y1, x2, y2, lx, ly, lbl in data.ticks:
            self.create_line(x1, y1, x2, y2, fill=COLOR_INK, width=1)
            for dx, dy in ((-1, -1), (-1, 1), (1, -1), (1, 1),
                           (-2, 0), (2, 0), (0, -2), (0, 2)):
                self.create_text(lx + dx, ly + dy, text=lbl,
                                 font=("Helvetica", 8, "bold"), fill="white")
            self.create_text(lx, ly, text=lbl,
                             font=("Helvetica", 8, "bold"), fill=COLOR_INK)

    # ------------------------------------------------------------------
    # Helpers de dessin — un par couche logique.
    #
    # **Pendants Tk ↔ PIL**. Chaque helper ci-dessous a un jumeau dans
    # `pil_render.py` (préfixé `_pil_draw_`) qui dessine la même couche
    # sur une `PIL.Image`. La géométrie est partagée via `geometry.py` ;
    # seuls subsistent ici les paramètres visuels propres à Tk (polices,
    # `outline+width` semantics, splines `smooth=True`, flèches natives
    # de `create_line`). Toute modification d'une couche doit être
    # répliquée dans les DEUX fichiers — cf. tableau dans CLAUDE.md
    # « Pendants Tk ↔ PIL ».
    #
    #   _draw_placeholder              ↔ _pil_draw_placeholder
    #   _draw_bois_sain                ↔ _pil_draw_bois_sain
    #   _draw_cernes                   ↔ _pil_draw_cernes
    #   _draw_cavite                   ↔ _pil_draw_cavite
    #   _draw_ecorce                   ↔ _pil_draw_ecorce
    #   _draw_contreforts_canvas       ↔ _pil_draw_contreforts
    #   _draw_degradation_externe_…    ↔ _pil_draw_degradations
    #   _draw_ticks                    ↔ _pil_draw_ticks
    #   _draw_cardinales               ↔ _pil_draw_cardinales
    #   _draw_sondages                 ↔ _pil_draw_sondages
    #   _draw_echelle_radiale          ↔ _pil_draw_echelle_radiale
    #   _draw_titre                    ↔ _pil_draw_titre
    # ------------------------------------------------------------------

    def _draw_placeholder(self) -> None:
        w = max(self.winfo_width(), 1)
        h = max(self.winfo_height(), 1)
        self.create_text(w/2, h/2,
                         text="Renseignez le rayon du tronc\npour afficher la section",
                         font=("Georgia", 14, "italic"),
                         fill=COLOR_MUTED, justify="center")

    def _draw_bois_sain(self, brin: "Brin", cx: float, cy: float,
                        R: float, scale: float) -> None:
        if brin.est_ovale:
            flat = [c for p in contour_polygon(
                        brin.rayon_a_grade, cx, cy, scale,
                        rotation_grades=brin.rotation_grades)
                    for c in p]
            self.create_polygon(*flat, fill=COLOR_WOOD, outline="", width=0)
            return
        # Section circulaire : un cercle est invariant par rotation → la
        # primitive native suffit (rendu byte-identique, goldens stables).
        radius_px = R * scale
        self.create_oval(cx - radius_px, cy - radius_px,
                         cx + radius_px, cy + radius_px,
                         fill=COLOR_WOOD, outline="", width=0)

    def _draw_cernes(self, brin: "Brin", cx: float, cy: float,
                     R: float, scale: float) -> None:
        if brin.est_ovale:
            for k in range(1, self.N_CERNES + 1):
                frac = k / (self.N_CERNES + 1)

                def r_cerne(g: float, frac: float = frac) -> float:
                    return brin.rayon_a_grade(g) * frac

                flat = [c for p in contour_polygon(
                            r_cerne, cx, cy, scale,
                            rotation_grades=brin.rotation_grades)
                        for c in p]
                self.create_polygon(*flat, fill="", outline=COLOR_CERNE,
                                    width=1)
            return
        for rr in cerne_radii_px(R, scale, self.N_CERNES):
            self.create_oval(cx - rr, cy - rr, cx + rr, cy + rr,
                             outline=COLOR_CERNE, width=1)

    def _draw_cavite(self, brin: "Brin", cx: float, cy: float, scale: float) -> None:
        # bois_altéré = épaisseur d'altération mesurée au résistographe,
        # qui correspond à une zone centrale de rayon égal à cette
        # épaisseur. La couronne externe de bois sain fait (R - altéré).
        alt = compute_alteration_par_grade(brin)
        if not any(a > 0 for a in alt):
            return
        smooth = cavity_polygon(alt, cx, cy, scale,
                                  samples_per_segment=self.CAVITY_SAMPLES_PER_SEGMENT,
                                  rotation_grades=brin.rotation_grades)
        flat = [c for p in smooth for c in p]
        # Pas de contour : couleur uniforme avec les dégradations
        # externes, permettant la fusion visuelle écorce↔cavité quand
        # elles se rejoignent.
        self.create_polygon(*flat, fill=COLOR_ROT,
                            outline="", smooth=False)

    def _draw_ecorce(self, brin: "Brin", cx: float, cy: float, R: float,
                     ep: float, scale: float) -> None:
        # Si une épaisseur est renseignée, anneau brun épais entre R et
        # R+ep (centré sur R+ep/2 avec width=ep_px). Sinon trait fin
        # classique au bord du bois.
        if brin.est_ovale:
            rot = brin.rotation_grades
            inner = contour_polygon(brin.rayon_a_grade, cx, cy, scale,
                                    rotation_grades=rot)
            if ep > 0:
                def r_outer(g: float) -> float:
                    return brin.rayon_a_grade(g) + ep

                outer = contour_polygon(r_outer, cx, cy, scale,
                                        rotation_grades=rot)
                flat = [c for p in (outer + inner[::-1]) for c in p]
                self.create_polygon(*flat, fill=COLOR_BARK, outline="")
            else:
                flat = [c for p in (inner + [inner[0]]) for c in p]
                self.create_line(*flat, fill=COLOR_BARK, width=3,
                                 smooth=True)
            return
        if ep > 0:
            ep_px = max(1.0, ep * scale)
            mid_radius = (R + ep / 2) * scale
            self.create_oval(cx - mid_radius, cy - mid_radius,
                             cx + mid_radius, cy + mid_radius,
                             outline=COLOR_BARK, width=ep_px)
        else:
            radius_px = R * scale
            self.create_oval(cx - radius_px, cy - radius_px,
                             cx + radius_px, cy + radius_px,
                             outline=COLOR_BARK, width=3)

    def _draw_ticks(self, cx: float, cy: float, R_ext: "RadiusSpec",
                    scale: float) -> None:
        # Graduations des 16 grades, tirets à l'extérieur de l'écorce.
        tick_len_cm = self.TICK_LEN_PX / scale
        for x1, y1, x2, y2, major in tick_endpoints(
                cx, cy, scale, R_ext, tick_len_cm):
            self.create_line(x1, y1, x2, y2,
                             fill=COLOR_BARK if major else COLOR_BARK_LIGHT,
                             width=2 if major else 1)

    def _draw_cardinales(self, cx: float, cy: float, R_ext: "RadiusSpec",
                         scale: float) -> None:
        # Lettres cardinales à `CARDINALES_OFFSET_PX` au-delà de l'écorce.
        offset_cm = self.CARDINALES_OFFSET_PX / scale
        for lx, ly, lbl in cardinal_label_positions(
                cx, cy, scale, R_ext, offset_cm):
            for dx, dy in ((-1, -1), (-1, 1), (1, -1), (1, 1),
                           (-2, 0), (2, 0), (0, -2), (0, 2)):
                self.create_text(lx + dx, ly + dy, text=lbl,
                                 font=("Georgia", 13, "bold"), fill="white")
            self.create_text(lx, ly, text=lbl,
                             font=("Georgia", 13, "bold"), fill=COLOR_INK)

    def _draw_sondages(self, brin: "Brin", port: str, meche: float,
                       cx: float, cy: float, R: float, scale: float) -> None:
        inset_cm = self.SONDAGE_INSET_PX / scale
        r_bul = self.BULLET_RADIUS_PX
        items = sondage_render_data(brin, port, meche, cx, cy, R, scale,
                                    inset_cm, COULEUR_CLASSE,
                                    rotation_grades=brin.rotation_grades)
        # Pour le tag click, on retrouve l'index du sondage dans la
        # liste métier via son numéro (numero = position+1 en pratique,
        # cf. `renumeroter_sondages`).
        numero_to_idx = {s.numero: i for i, s in enumerate(brin.sondages)}
        for item in items:
            x_ext, y_ext = item.arrow_start
            x_end, y_end = item.arrow_end
            self.create_line(x_ext, y_ext, x_end, y_end,
                             fill=COLOR_SOND, width=2,
                             arrow=tk.LAST, arrowshape=(10, 12, 4))
            px, py = item.bullet_center
            idx = numero_to_idx.get(item.numero, item.numero - 1)
            tags = ("sondage_item", f"sondage_idx_{idx}")
            self.create_oval(px - r_bul - 2, py - r_bul - 2,
                             px + r_bul + 2, py + r_bul + 2,
                             fill="white", outline="", tags=tags)
            self.create_oval(px - r_bul, py - r_bul,
                             px + r_bul, py + r_bul,
                             fill=item.classe_color, outline="white",
                             width=2, tags=tags)
            self.create_text(px, py, text=str(item.numero),
                             font=("Helvetica", 10, "bold"), fill="white",
                             tags=tags)

    def _draw_titre(self, A: Arbre, R: float) -> None:
        # Titre seul au-dessus du tronc. La ligne de sous-titre (rayon, Ø,
        # hauteur, mèche) a été retirée : redondante avec l'onglet
        # Identification, elle prenait de la place pour rien. Le canvas
        # s'aligne ainsi sur le PNG (`_pil_draw_titre`, titre seul).
        w = max(self.winfo_width(), 1)
        self.create_text(w/2, 16, text=A.display_name,
                         font=("Georgia", 15, "bold"), fill=COLOR_ACCENT)
