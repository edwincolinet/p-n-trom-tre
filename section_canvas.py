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
    cardinal_label_positions,
    cavity_polygon,
    cerne_radii_px,
    contour_polygon,
    contrefort_zone_outline,
    contrefort_zones,
    degradation_externe_outline,
    ruler_graduation_positions,
    tick_endpoints,
)
from model import Arbre, Contrefort, DegradationExterne, Sondage
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
    MARGIN_BOTTOM_PX = 105   # lettre S 25 + règle 30 + chiffres + label
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
        self.bind("<Configure>", lambda e: self.redraw())
        # Bindings sur tags : valent pour tous les items recréés à
        # chaque redraw qui portent le tag correspondant. Le curseur
        # passe en « main » au survol pour signaler la zone cliquable.
        if host is not None:
            for tag in ("sondage_item", "degradation_item",
                         "contrefort_item"):
                self.tag_bind(tag, "<Enter>",
                              lambda e: self.configure(cursor="hand2"))
                self.tag_bind(tag, "<Leave>",
                              lambda e: self.configure(cursor=""))
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

    # NB sur l'usage d'`after_idle` : on diffère l'ouverture du
    # dialogue à la fin du traitement du clic. Sans cela, le `tk.Toplevel`
    # + `grab_set()` créé en plein dispatch d'événement entrait en
    # conflit avec le focus du Canvas — sur Linux/X11 (GNOME/Mutter),
    # la fenêtre apparaissait vide car ses widgets n'avaient pas eu le
    # temps d'être posés avant `wait_window()`. `after_idle` rend la
    # main à la boucle Tk, qui finalise le clic puis ouvre le dialogue
    # à blanc.

    def _on_click_sondage(self, _event: "tk.Event[tk.Misc]") -> None:
        if self._host is None or self.arbre is None:
            return
        idx = self._picked_index("sondage_idx_")
        if idx is None or idx >= len(self.arbre.sondages):
            return
        s = self.arbre.sondages[idx]
        host = self._host
        self.after_idle(lambda: host.open_edit_sondage(s))

    def _on_click_degradation(self, _event: "tk.Event[tk.Misc]") -> None:
        if self._host is None or self.arbre is None:
            return
        idx = self._picked_index("degradation_idx_")
        if idx is None or idx >= len(self.arbre.degradations_externes):
            return
        d = self.arbre.degradations_externes[idx]
        host = self._host
        self.after_idle(lambda: host.open_edit_degradation(d))

    def _on_click_contrefort(self, _event: "tk.Event[tk.Misc]") -> None:
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
        dans le titre ou la règle. Inverse de `geometry.polar_to_xy` :
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
                                  R_inner: Any = None) -> None:
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
                                            cx, cy, scale, R_inner=R_inner)
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
                                          idx: int = -1) -> None:
        """Dessine une dégradation externe sur le canvas Tkinter à partir
        des points renvoyés par `degradation_externe_outline` (cf.
        geometry.py). `idx` (>= 0) tague le polygone pour le clic-édit."""
        points = degradation_externe_outline(deg, contreforts, R, ep_cm,
                                              cx, cy, scale)
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
        self.delete("all")
        self._geom = None
        if not self.arbre or self.arbre.rayon_tronc_cm <= 0:
            self._draw_placeholder()
            return

        A = self.arbre
        R = A.rayon_tronc_cm
        ep = max(0.0, A.epaisseur_ecorce_cm)
        R_ext = R + ep   # rayon externe = bois + écorce
        # Réserver l'espace pour l'écorce + les contreforts (qui partent
        # de R_ext et dépassent encore de longueur_cm).
        expansion = ep + max((c.longueur_cm for c in A.contreforts),
                              default=0.0)
        cx, cy, scale = self._center_and_scale(R, expansion_cm=expansion)
        self._geom = (cx, cy, scale, R, R_ext)

        R_h = A.rayon_a_grade(100)  # règle horizontale → axe E-O
        # Section elle-même (bois → pastilles), centrée en (cx, cy). Isolée
        # dans `_draw_brin` pour préparer la composition multi-brins (cépées) :
        # un appel par brin à son propre centre. Le repère partagé (règle,
        # titre) reste global, dessiné ensuite.
        self._draw_brin(A, cx, cy, R, ep, scale)
        self._draw_regle(cx, cy, R_h, ep, R_h + ep, scale)
        self._draw_titre(A, R)

    def _draw_brin(self, A: Arbre, cx: float, cy: float,
                   R: float, ep: float, scale: float) -> None:
        """Dessine UNE section (bois → pastilles) centrée en (cx, cy).

        Regroupe les couches **propres à un brin** dans l'ordre de
        superposition. Pour une cépée, `redraw` appellera ce helper une fois
        par brin à son centre écran ; pour un genet mono-brin centré, le
        rendu est strictement identique à l'ancien (goldens préservés).
        """
        # Fournisseurs de rayon par direction : constants si circulaire
        # (rendu identique à l'ancien), variables si ellipse.
        r_of = A.rayon_a_grade
        r_ext_of: "RadiusSpec" = (
            (lambda g: A.rayon_a_grade(g) + ep) if ep else r_of)
        self._draw_bois_sain(A, cx, cy, R, scale)
        self._draw_cernes(A, cx, cy, R, scale)
        self._draw_cavite(A, cx, cy, scale)
        self._draw_ecorce(A, cx, cy, R, ep, scale)
        # Contreforts : R_inner descend de 1 px sous le rayon LOCAL pour
        # qu'aucun pixel de trou n'apparaisse entre polygone bois et disque.
        self._draw_contreforts_canvas(
            cx, cy, scale, r_of, A.contreforts, ep_cm=ep,
            R_inner=(lambda g: A.rayon_a_grade(g) - 1.0 / scale))
        # Dégradations externes EN DERNIER (cf. CLAUDE.md).
        for idx, deg in enumerate(A.degradations_externes):
            self._draw_degradation_externe_canvas(cx, cy, scale, r_of, ep,
                                                   A.contreforts, deg,
                                                   idx=idx)
        self._draw_ticks(cx, cy, r_ext_of, scale)
        self._draw_cardinales(cx, cy, r_ext_of, scale)
        if self.show_sondages:
            self._draw_sondages(A, cx, cy, R, scale)

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
    #   _draw_regle                    ↔ _pil_draw_regle
    #   _draw_titre                    ↔ _pil_draw_titre
    # ------------------------------------------------------------------

    def _draw_placeholder(self) -> None:
        w = max(self.winfo_width(), 1)
        h = max(self.winfo_height(), 1)
        self.create_text(w/2, h/2,
                         text="Renseignez le rayon du tronc\npour afficher la section",
                         font=("Georgia", 14, "italic"),
                         fill=COLOR_MUTED, justify="center")

    def _draw_bois_sain(self, A: Arbre, cx: float, cy: float,
                        R: float, scale: float) -> None:
        if A.est_ovale:
            flat = [c for p in contour_polygon(A.rayon_a_grade, cx, cy, scale)
                    for c in p]
            self.create_polygon(*flat, fill=COLOR_WOOD, outline="", width=0)
            return
        radius_px = R * scale
        self.create_oval(cx - radius_px, cy - radius_px,
                         cx + radius_px, cy + radius_px,
                         fill=COLOR_WOOD, outline="", width=0)

    def _draw_cernes(self, A: Arbre, cx: float, cy: float,
                     R: float, scale: float) -> None:
        if A.est_ovale:
            for k in range(1, self.N_CERNES + 1):
                frac = k / (self.N_CERNES + 1)

                def r_cerne(g: float, frac: float = frac) -> float:
                    return A.rayon_a_grade(g) * frac

                flat = [c for p in contour_polygon(r_cerne, cx, cy, scale)
                        for c in p]
                self.create_polygon(*flat, fill="", outline=COLOR_CERNE,
                                    width=1)
            return
        for rr in cerne_radii_px(R, scale, self.N_CERNES):
            self.create_oval(cx - rr, cy - rr, cx + rr, cy + rr,
                             outline=COLOR_CERNE, width=1)

    def _draw_cavite(self, A: Arbre, cx: float, cy: float, scale: float) -> None:
        # bois_altéré = épaisseur d'altération mesurée au résistographe,
        # qui correspond à une zone centrale de rayon égal à cette
        # épaisseur. La couronne externe de bois sain fait (R - altéré).
        alt = compute_alteration_par_grade(A)
        if not any(a > 0 for a in alt):
            return
        smooth = cavity_polygon(alt, cx, cy, scale,
                                  samples_per_segment=self.CAVITY_SAMPLES_PER_SEGMENT)
        flat = [c for p in smooth for c in p]
        # Pas de contour : couleur uniforme avec les dégradations
        # externes, permettant la fusion visuelle écorce↔cavité quand
        # elles se rejoignent.
        self.create_polygon(*flat, fill=COLOR_ROT,
                            outline="", smooth=False)

    def _draw_ecorce(self, A: Arbre, cx: float, cy: float, R: float,
                     ep: float, scale: float) -> None:
        # Si une épaisseur est renseignée, anneau brun épais entre R et
        # R+ep (centré sur R+ep/2 avec width=ep_px). Sinon trait fin
        # classique au bord du bois.
        if A.est_ovale:
            inner = contour_polygon(A.rayon_a_grade, cx, cy, scale)
            if ep > 0:
                def r_outer(g: float) -> float:
                    return A.rayon_a_grade(g) + ep

                outer = contour_polygon(r_outer, cx, cy, scale)
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

    def _draw_sondages(self, A: Arbre, cx: float, cy: float, R: float, scale: float) -> None:
        inset_cm = self.SONDAGE_INSET_PX / scale
        r_bul = self.BULLET_RADIUS_PX
        items = sondage_render_data(A, cx, cy, R, scale, inset_cm,
                                    COULEUR_CLASSE)
        # Pour le tag click, on retrouve l'index du sondage dans la
        # liste métier via son numéro (numero = position+1 en pratique,
        # cf. `renumeroter_sondages`).
        numero_to_idx = {s.numero: i for i, s in enumerate(A.sondages)}
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

    def _draw_regle(self, cx: float, cy: float, R: float, ep: float, R_ext: float, scale: float) -> None:
        h = max(self.winfo_height(), 1)
        radius_ext_px = R_ext * scale
        step = adaptive_ruler_step_cm(scale, min_gap_px=24)
        y_bar = min(cy + radius_ext_px + 55, h - 30)
        half_px = R * scale
        ext_half_px = R_ext * scale
        x_left = cx - half_px
        x_right = cx + half_px

        self.create_rectangle(cx - ext_half_px - 8, y_bar - 12,
                              cx + ext_half_px + 30, y_bar + 22,
                              fill="white", outline="")
        # Trait principal de -R à +R
        self.create_line(x_left, y_bar, x_right, y_bar,
                         fill=COLOR_INK, width=2)
        # Barres d'écorce aux deux extrémités + tiret au bout
        if ep > 0:
            bar_h = 7
            x_ext_r = cx + ext_half_px
            x_ext_l = cx - ext_half_px
            self.create_rectangle(x_right, y_bar - bar_h / 2,
                                  x_ext_r, y_bar + bar_h / 2,
                                  fill=COLOR_BARK, outline="")
            self.create_rectangle(x_ext_l, y_bar - bar_h / 2,
                                  x_left, y_bar + bar_h / 2,
                                  fill=COLOR_BARK, outline="")
            self.create_line(x_ext_r, y_bar - 6, x_ext_r, y_bar + 6,
                             fill=COLOR_BARK, width=2)
            self.create_line(x_ext_l, y_bar - 6, x_ext_l, y_bar + 6,
                             fill=COLOR_BARK, width=2)
        # Tirets aux extrémités bois (R) et au centre
        self.create_line(x_left, y_bar - 6, x_left, y_bar + 6,
                         fill=COLOR_INK, width=2)
        self.create_line(x_right, y_bar - 6, x_right, y_bar + 6,
                         fill=COLOR_INK, width=2)
        self.create_line(cx, y_bar - 6, cx, y_bar + 6,
                         fill=COLOR_INK, width=2)
        if R > 0:
            for xg, label in ruler_graduation_positions(cx, scale, R, step):
                self.create_line(xg, y_bar - 4, xg, y_bar + 4,
                                 fill=COLOR_INK, width=1)
                self.create_text(xg, y_bar + 14, text=label,
                                 anchor="center",
                                 font=("Helvetica", 8), fill=COLOR_INK)
                x_mirror = cx - (xg - cx)
                self.create_line(x_mirror, y_bar - 4, x_mirror, y_bar + 4,
                                 fill=COLOR_INK, width=1)
                self.create_text(x_mirror, y_bar + 14, text=label,
                                 anchor="center",
                                 font=("Helvetica", 8), fill=COLOR_INK)
            self.create_text(cx, y_bar + 14, text="0",
                             anchor="center",
                             font=("Helvetica", 8, "bold"),
                             fill=COLOR_INK)
            self.create_text(x_right, y_bar + 14, text=f"{R:g}",
                             anchor="center",
                             font=("Helvetica", 8, "bold"),
                             fill=COLOR_INK)
            self.create_text(x_left, y_bar + 14, text=f"{R:g}",
                             anchor="center",
                             font=("Helvetica", 8, "bold"),
                             fill=COLOR_INK)
        self.create_text(cx + ext_half_px + 18, y_bar, text="cm",
                         anchor="w",
                         font=("Helvetica", 9, "bold italic"),
                         fill=COLOR_INK)

    def _draw_titre(self, A: Arbre, R: float) -> None:
        # Titre + méta au-dessus du tronc (entre y=10 et la lettre N à
        # cy - radius_px - 25). Stats globales : onglet Diagnostic.
        w = max(self.winfo_width(), 1)
        title_y = 16
        sub_y = 38
        self.create_text(w/2, title_y, text=A.display_name,
                         font=("Georgia", 15, "bold"), fill=COLOR_ACCENT)
        sub_parts = [f"Rayon {R:g} cm"]
        if A.diametre_sous_ecorce_cm:
            sub_parts.append(f"Ø sous écorce {A.diametre_sous_ecorce_cm:g} cm")
        if A.hauteur_arbre_m:
            sub_parts.append(f"H {A.hauteur_arbre_m:g} m")
        if A.meche_cm:
            sub_parts.append(f"Mèche {A.meche_cm:g} cm")
        self.create_text(w/2, sub_y, text="   •   ".join(sub_parts),
                         font=("Helvetica", 10, "italic"), fill=COLOR_MUTED)
