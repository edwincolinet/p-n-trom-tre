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

import tkinter as tk
from typing import Any, Optional, Tuple

from diagnostic import (
    compute_alteration_par_grade,
    sondage_render_data,
)
from geometry import (
    adaptive_ruler_step_cm,
    cardinal_label_positions,
    cavity_polygon,
    contrefort_zone_outline,
    contrefort_zones,
    degradation_externe_outline,
    ruler_graduation_positions,
    tick_endpoints,
)
from model import Arbre
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

    def __init__(self, master: tk.Misc, **kw: Any) -> None:
        super().__init__(master, bg=COLOR_PANEL, highlightthickness=0,
                         bd=0, **kw)
        self.arbre: Optional[Arbre] = None
        self.show_sondages: bool = True
        self.bind("<Configure>", lambda e: self.redraw())

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
                                  R: float, contreforts: Any,
                                  ep_cm: float = 0.0,
                                  R_inner: Optional[float] = None) -> None:
        """Dessine TOUS les contreforts en utilisant les polygones fusionnés
        renvoyés par `contrefort_zone_outline` (cf. geometry.py). Évite
        l'encoche en V à la jonction de deux contreforts proches.
        """
        if R <= 0 or not contreforts:
            return
        for zone in contrefort_zones(contreforts):
            poly = contrefort_zone_outline(zone, contreforts, R, ep_cm,
                                            cx, cy, scale, R_inner=R_inner)
            wood_outer = poly["wood_outer"]
            if ep_cm > 0:
                # Couche d'écorce : bord interne à R (arc constant),
                # bord externe suit la cloche r_wood + ep.
                flat_bark = [coord for p in (poly["bark_outer"]
                                              + poly["bark_inner"])
                             for coord in p]
                self.create_polygon(*flat_bark, fill=COLOR_BARK,
                                    outline="")
            # Polygone bois : noyau de bois sous l'écorce.
            flat_wood = [coord for p in (wood_outer + poly["base"])
                         for coord in p]
            self.create_polygon(*flat_wood, fill=COLOR_WOOD, outline="")
            if ep_cm == 0:
                # Pas d'écorce : trait brun en surface
                flat_outer = [coord for p in wood_outer for coord in p]
                self.create_line(*flat_outer, fill=COLOR_BARK, width=3,
                                 smooth=True)

    def _draw_degradation_externe_canvas(self, cx: float, cy: float,
                                          scale: float, R: float, ep_cm: float,
                                          contreforts: Any, deg: Any) -> None:
        """Dessine une dégradation externe sur le canvas Tkinter à partir
        des points renvoyés par `degradation_externe_outline` (cf.
        geometry.py)."""
        points = degradation_externe_outline(deg, contreforts, R, ep_cm,
                                              cx, cy, scale)
        if not points:
            return
        flat = [c for p in points for c in p]
        # Pas de contour : fusion visuelle avec la cavité interne
        self.create_polygon(*flat, fill=COLOR_ROT, outline="")

    def redraw(self) -> None:
        """Orchestre le rendu de la section. Chaque couche est déléguée à
        un helper `_draw_*` ; l'ordre ci-dessous est l'ordre de
        superposition (du fond vers le dessus). Voir CLAUDE.md → « Ordre
        global des couches » pour la convention métier.
        """
        self.delete("all")
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

        self._draw_bois_sain(cx, cy, R, scale)
        self._draw_cernes(cx, cy, R, scale)
        self._draw_cavite(A, cx, cy, scale)
        self._draw_ecorce(cx, cy, R, ep, scale)
        # Contreforts : R_inner descend de 1 px sous R pour qu'aucun
        # pixel de trou n'apparaisse entre polygone bois et disque.
        self._draw_contreforts_canvas(cx, cy, scale, R, A.contreforts,
                                       ep_cm=ep, R_inner=R - 1.0 / scale)
        # Dégradations externes EN DERNIER (cf. CLAUDE.md).
        for deg in A.degradations_externes:
            self._draw_degradation_externe_canvas(cx, cy, scale, R, ep,
                                                   A.contreforts, deg)
        self._draw_ticks(cx, cy, R_ext, scale)
        self._draw_cardinales(cx, cy, R_ext, scale)
        if self.show_sondages:
            self._draw_sondages(A, cx, cy, R, scale)

        self._draw_regle(cx, cy, R, ep, R_ext, scale)
        self._draw_titre(A, R)

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

    def _draw_bois_sain(self, cx: float, cy: float, R: float, scale: float) -> None:
        radius_px = R * scale
        self.create_oval(cx - radius_px, cy - radius_px,
                         cx + radius_px, cy + radius_px,
                         fill=COLOR_WOOD, outline="", width=0)

    def _draw_cernes(self, cx: float, cy: float, R: float, scale: float) -> None:
        # Cernes par-dessus le bois sain, en brun foncé fin. Effacés
        # naturellement dans la zone dégradée par la cavité dessinée
        # juste après.
        radius_px = R * scale
        n = self.N_CERNES
        for k in range(1, n + 1):
            rr = radius_px * k / (n + 1)
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

    def _draw_ecorce(self, cx: float, cy: float, R: float, ep: float, scale: float) -> None:
        # Si une épaisseur est renseignée, anneau brun épais entre R et
        # R+ep (centré sur R+ep/2 avec width=ep_px). Sinon trait fin
        # classique au bord du bois.
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

    def _draw_ticks(self, cx: float, cy: float, R_ext: float, scale: float) -> None:
        # Graduations des 16 grades, tirets à l'extérieur de l'écorce.
        tick_len_cm = self.TICK_LEN_PX / scale
        for x1, y1, x2, y2, major in tick_endpoints(
                cx, cy, scale, R_ext, tick_len_cm):
            self.create_line(x1, y1, x2, y2,
                             fill=COLOR_BARK if major else COLOR_BARK_LIGHT,
                             width=2 if major else 1)

    def _draw_cardinales(self, cx: float, cy: float, R_ext: float, scale: float) -> None:
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
        for item in items:
            x_ext, y_ext = item.arrow_start
            x_end, y_end = item.arrow_end
            self.create_line(x_ext, y_ext, x_end, y_end,
                             fill=COLOR_SOND, width=2,
                             arrow=tk.LAST, arrowshape=(10, 12, 4))
            px, py = item.bullet_center
            self.create_oval(px - r_bul - 2, py - r_bul - 2,
                             px + r_bul + 2, py + r_bul + 2,
                             fill="white", outline="")
            self.create_oval(px - r_bul, py - r_bul,
                             px + r_bul, py + r_bul,
                             fill=item.classe_color, outline="white", width=2)
            self.create_text(px, py, text=str(item.numero),
                             font=("Helvetica", 10, "bold"), fill="white")

    def _draw_regle(self, cx: float, cy: float, R: float, ep: float, R_ext: float, scale: float) -> None:
        # RÈGLE GRADUÉE sous la section, DEMI-RÈGLE : 0 au centre de
        # l'arbre, graduation seulement vers la droite jusqu'à R (bord
        # du bois). La barre écorce (si ep > 0) prolonge la règle sans
        # label numérique — l'épaisseur d'écorce reste lisible via
        # l'onglet Diagnostic.
        h = max(self.winfo_height(), 1)
        radius_ext_px = R_ext * scale
        # Pas adaptatif : on veut ~24 px mini entre deux étiquettes pour
        # la police 8 pt du canvas.
        step = adaptive_ruler_step_cm(scale, min_gap_px=24)
        # Position verticale : juste sous l'écorce + lettres cardinales
        # + petit padding ; on remonte si on dépasse en bas du canvas.
        y_axis = min(cy + radius_ext_px + 75, h - 30)
        wood_half_px = R * scale
        ext_half_px = R_ext * scale
        x_rw = cx + wood_half_px
        x_re = cx + ext_half_px

        # Bandeau blanc de fond (centré sur la demi-règle)
        self.create_rectangle(cx - 8, y_axis - 14,
                              x_re + 35, y_axis + 24,
                              fill="white", outline="")
        # Trait bois (noir fin) du centre au bord droit
        self.create_line(cx, y_axis, x_rw, y_axis,
                         fill=COLOR_INK, width=2)
        # Barre écorce à l'extrémité droite
        if ep > 0:
            bar_h = 7
            self.create_rectangle(x_rw, y_axis - bar_h/2,
                                  x_re, y_axis + bar_h/2,
                                  fill=COLOR_BARK, outline="")
        # Tiret à l'extrémité externe (R+ep)
        end_color = COLOR_BARK if ep > 0 else COLOR_INK
        self.create_line(x_re, y_axis - 8, x_re, y_axis + 8,
                         fill=end_color, width=2)
        # Tiret central (origine 0) et transition bois/écorce (R)
        self.create_line(cx, y_axis - 6, cx, y_axis + 6,
                         fill=COLOR_INK, width=2)
        if ep > 0:
            self.create_line(x_rw, y_axis - 6, x_rw, y_axis + 6,
                             fill=COLOR_INK, width=2)
        # Graduations intermédiaires (bois) tous les `step` cm depuis 0
        # (centre) jusqu'à R (bord droit).
        if R > 0:
            for xg, label in ruler_graduation_positions(cx, scale, R, step):
                self.create_line(xg, y_axis - 4, xg, y_axis + 4,
                                 fill=COLOR_INK, width=1)
                self.create_text(xg, y_axis + 15, text=label,
                                 anchor="center",
                                 font=("Helvetica", 8), fill=COLOR_INK)
            # Étiquettes des deux extrémités : 0 au centre, R au bord
            self.create_text(cx, y_axis + 15, text="0",
                             anchor="center",
                             font=("Helvetica", 8, "bold"),
                             fill=COLOR_INK)
            self.create_text(x_rw, y_axis + 15, text=f"{R:g}",
                             anchor="center",
                             font=("Helvetica", 8, "bold"),
                             fill=COLOR_INK)
        # Label "cm" à droite
        self.create_text(x_re + 18, y_axis, text="cm",
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
