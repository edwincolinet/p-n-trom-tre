"""
Pénétromètre — Application d'expertise
======================================

- multi-arbres dans un fichier « mission » (.json),
- tableau de sondages ↔ dessin synchronisés (altération = cavité interne),
- dessin vectoriel natif (Tkinter Canvas) avec interpolation spline
  pour une section réellement ronde,
- contreforts (empattements) et dégradations externes,
- export PNG du dessin et fiche PDF A4 par arbre.

Dépendances : Python 3.9+, tkinter (stdlib), Pillow (PNG/PDF).
"""

from __future__ import annotations

import csv
import json
import logging
import math
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional, Tuple

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

# Helpers géométriques + barème classifient des fonctions pures testées
# isolément (cf. tests/). Voir geometry.py pour le détail.
from geometry import (
    DIRECTION_LABELS,
    GRADES,
    PORTS_ARBRE,
    cavity_polygon,
    classer_prbs,
    contrefort_zone_outline,
    contrefort_zones,
    degradation_externe_outline,
    polar_idx_to_xy,
    polar_to_xy,
)
# Modèle de données : dataclasses sérialisables (Sondage, Arbre, …) avec
# leur logique métier (extrapolation, PRBS, classification). Voir
# model.py pour le détail. Sans dépendance Tk/PIL : couvert par les tests.
from model import (
    Arbre,
    Chantier,
    Contrefort,
    DegradationExterne,
    Sondage,
)
# Palette partagée Tk ↔ PIL : couleurs UI et mapping classe → hex.
from palette import (
    COLOR_ACCENT,
    COLOR_ACCENT_SOFT,
    COLOR_BARK,
    COLOR_BARK_LIGHT,
    COLOR_BG,
    COLOR_CERNE,
    COLOR_INK,
    COLOR_MUTED,
    COLOR_PANEL,
    COLOR_ROT,
    COLOR_SIDE_PANEL,
    COLOR_SOND,
    COLOR_WOOD,
    COLOR_WOOD_DARK,
    COULEUR_CLASSE,
)
from dialogs import edit_contrefort, edit_degradation, edit_sondage
from export import HAS_OPENPYXL, export_prbs_html, export_prbs_xlsx
# Rendu PIL (PNG du dessin + fiche PDF A4). `HAS_PIL` reste False si
# Pillow n'est pas installé : l'app démarre, et les actions d'export
# affichent un message clair sans planter.
from pil_render import (
    HAS_PIL,
    render_arbre_to_pil_image,
    render_fiche_arbre_to_pdf_page,
)


__version__ = "3.3.0"


# Logger applicatif — configuré par `_setup_logging()` au démarrage.
# Tant qu'aucun handler n'est attaché (cas tests / import du module
# sans `main()`), les messages partent dans le vide silencieusement.
log = logging.getLogger("penetrometre")


# ---------------------------------------------------------------------------
# Canvas de dessin — section ronde
# ---------------------------------------------------------------------------

class SectionCanvas(tk.Canvas):

    def __init__(self, master, **kw):
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
        # Marges :
        # - haut : 70 px (titre 24 + méta 44 + 25 px pour lettre N hors écorce)
        # - bas : 105 px (lettre S à 25 + règle graduée à ~30 + chiffres + label)
        margin_top = 70
        margin_bottom = 105
        margin_side = 50
        available_v = h - margin_top - margin_bottom
        available_h = w - 2 * margin_side
        radius_px = min(available_h / 2, available_v / 2)
        cy = margin_top + radius_px
        R_eff = R + max(0.0, expansion_cm)
        scale = radius_px / R_eff if R_eff > 0 else 1.0
        return cx, cy, scale

    def _draw_contreforts_canvas(self, cx, cy, scale, R,
                                  contreforts,
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

    def _draw_degradation_externe_canvas(self, cx, cy, scale, R, ep_cm,
                                          contreforts, deg) -> None:
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
        self.delete("all")
        if not self.arbre or self.arbre.rayon_tronc_cm <= 0:
            w = max(self.winfo_width(), 1)
            h = max(self.winfo_height(), 1)
            self.create_text(w/2, h/2,
                             text="Renseignez le rayon du tronc\npour afficher la section",
                             font=("Georgia", 14, "italic"),
                             fill=COLOR_MUTED, justify="center")
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
        w = max(self.winfo_width(), 1)
        h = max(self.winfo_height(), 1)
        radius_px = R * scale
        radius_ext_px = R_ext * scale

        # 1. Disque bois sain
        self.create_oval(cx - radius_px, cy - radius_px,
                         cx + radius_px, cy + radius_px,
                         fill=COLOR_WOOD, outline="", width=0)

        # 2. Cernes de croissance — par-dessus le bois sain, en brun très
        # foncé fin pour qu'ils soient bien visibles. Ils seront ensuite
        # effacés naturellement dans la zone dégradée par la cavité.
        for k in range(1, 9):
            rr = radius_px * k / 9
            self.create_oval(cx - rr, cy - rr, cx + rr, cy + rr,
                             outline=COLOR_CERNE, width=1)

        # 3. Cavité d'altération (spline) — efface les cernes dans sa zone
        # Convention métier : bois_altéré = épaisseur d'altération mesurée
        # au résistographe, qui correspond à une zone centrale de rayon
        # égal à cette épaisseur. La couronne externe de bois sain fait
        # donc (R - altéré) d'épaisseur.
        alt = A.compute_alteration_par_grade()
        if any(a > 0 for a in alt):
            smooth = cavity_polygon(alt, cx, cy, scale,
                                     samples_per_segment=28)
            flat = [c for p in smooth for c in p]
            # Pas de contour : la couleur est uniforme avec les dégradations
            # externes, ce qui permet la fusion visuelle quand elles se
            # rejoignent (zone connectée écorce↔cavité).
            self.create_polygon(*flat, fill=COLOR_ROT,
                                outline="", smooth=False)

        # 4. Écorce. Si une épaisseur est renseignée, on dessine un anneau
        # brun épais entre R et R+ep (centré sur R+ep/2 avec width=ep_px).
        # Sinon on garde le trait fin classique au bord du bois.
        if ep > 0:
            ep_px = max(1.0, ep * scale)
            mid_radius = (R + ep / 2) * scale
            self.create_oval(cx - mid_radius, cy - mid_radius,
                             cx + mid_radius, cy + mid_radius,
                             outline=COLOR_BARK, width=ep_px)
        else:
            self.create_oval(cx - radius_px, cy - radius_px,
                             cx + radius_px, cy + radius_px,
                             outline=COLOR_BARK, width=3)

        # 5. Contreforts (empattements à la base du tronc) — fusionnés
        # par zones connectées : si plusieurs contreforts se chevauchent
        # ou se touchent, ils sont rendus comme une seule cloche unifiée
        # (max des hauteurs à chaque grade), évitant les encoches en V.
        cf_inner = R - 1.0 / scale
        self._draw_contreforts_canvas(cx, cy, scale, R, A.contreforts,
                                       ep_cm=ep, R_inner=cf_inner)

        # 6. Dégradations externes — dessinées EN DERNIER pour qu'elles
        # creusent l'écorce ET les contreforts dans leur secteur. Le bord
        # externe du polygone suit la surface réelle (R + ep + cloche),
        # ce qui permet à une dégradation de mordre dans un contrefort
        # qu'elle traverse.
        for deg in A.degradations_externes:
            self._draw_degradation_externe_canvas(cx, cy, scale, R, ep,
                                                   A.contreforts, deg)

        # 4. Graduations des 16 grades (tirets à l'extérieur de l'écorce)
        for i, g in enumerate(GRADES):
            x1, y1 = polar_idx_to_xy(cx, cy, scale, R_ext, i)
            tick_len_cm = 8 / scale
            x2, y2 = polar_idx_to_xy(cx, cy, scale,
                                            R_ext + tick_len_cm, i)
            major = (g % 50 == 0)
            self.create_line(x1, y1, x2, y2,
                             fill=COLOR_BARK if major else COLOR_BARK_LIGHT,
                             width=2 if major else 1)

        # 5. Lettres cardinales — à 25 px hors écorce, halo blanc
        for i, g in enumerate(GRADES):
            lbl = DIRECTION_LABELS.get(g, "")
            if not lbl:
                continue
            lx, ly = polar_idx_to_xy(cx, cy, scale,
                                            R_ext + 25/scale, i)
            for dx, dy in ((-1, -1), (-1, 1), (1, -1), (1, 1),
                           (-2, 0), (2, 0), (0, -2), (0, 2)):
                self.create_text(lx + dx, ly + dy, text=lbl,
                                 font=("Georgia", 13, "bold"), fill="white")
            self.create_text(lx, ly, text=lbl,
                             font=("Georgia", 13, "bold"), fill=COLOR_INK)

        # 6. Sondages (flèches + pastilles) — affichage optionnel.
        # Pastilles à l'INTÉRIEUR du tronc, juste sous l'écorce.
        if self.show_sondages:
            port = A.port_arbre
            meche = A.meche_cm if A.meche_cm > 0 else float("inf")
            # Profondeur de dégradation externe par direction : la
            # pastille est classée sur la PRBS AJUSTÉE (PRBS - dégrad.
            # externe couvrant le grade) afin d'être cohérente avec le
            # tableau Diagnostic et la fiche PDF.
            deg_ext_par_grade = A.degradation_externe_par_grade()
            for s in A.sondages:
                if s.grade not in GRADES:
                    continue
                i = GRADES.index(s.grade)
                penetration = min(s.bois_sain_cm + s.bois_altere_cm, meche)
                penetration = max(0.0, min(penetration, R))
                end_radius = R - penetration
                # Flèche : depuis 13 px sous l'écorce
                x_ext, y_ext = polar_idx_to_xy(cx, cy, scale,
                                                     R - 13/scale, i)
                x_end, y_end = polar_idx_to_xy(cx, cy, scale,
                                                     end_radius, i)
                self.create_line(x_ext, y_ext, x_end, y_end,
                                 fill=COLOR_SOND, width=2,
                                 arrow=tk.LAST, arrowshape=(10, 12, 4))

                # Pastille à 13 px sous l'écorce, classée sur la PRBS
                # ajustée (cohérence avec le tableau et la fiche PDF).
                prbs_adj = max(0.0, s.prbs_cm - deg_ext_par_grade[i])
                ratio_adj = prbs_adj / R if R > 0 else 0.0
                col_class = COULEUR_CLASSE[classer_prbs(ratio_adj, port)]
                px, py = polar_idx_to_xy(cx, cy, scale,
                                               R - 13/scale, i)
                r_bul = 11
                self.create_oval(px - r_bul - 2, py - r_bul - 2,
                                 px + r_bul + 2, py + r_bul + 2,
                                 fill="white", outline="")
                self.create_oval(px - r_bul, py - r_bul,
                                 px + r_bul, py + r_bul,
                                 fill=col_class, outline="white", width=2)
                self.create_text(px, py, text=str(s.numero),
                                 font=("Helvetica", 10, "bold"), fill="white")

        # 7. RÈGLE GRADUÉE — placée SOUS la section, hors du tronc.
        # Étendue jusqu'au rayon externe (R + ep). La portion bois
        # ([-R, +R]) est en trait noir fin ; les portions écorce
        # ([-R_ext, -R] et [+R, +R_ext]) sont des barres brun foncé
        # épaisses qui évoquent l'écorce — l'œil peut ainsi mesurer
        # bois et écorce sur la même règle.
        step = 5 if R >= 15 else (2 if R >= 6 else 1)
        # Position verticale : au bas du canvas, juste sous l'écorce
        # (rayon externe) + lettres cardinales + petit padding.
        y_axis = cy + radius_ext_px + 75
        # Si on dépasse en bas du canvas, on remonte
        y_axis = min(y_axis, h - 30)
        # Demi-largeurs en pixels : portion bois et portion totale
        wood_half_px = R * scale
        ext_half_px = R_ext * scale
        x_lw, x_rw = cx - wood_half_px, cx + wood_half_px
        x_le, x_re = cx - ext_half_px, cx + ext_half_px

        # Bandeau blanc de fond pour bien détacher
        self.create_rectangle(x_le - 8, y_axis - 14,
                              x_re + 35, y_axis + 24,
                              fill="white", outline="")
        # Trait bois (noir fin) au centre
        self.create_line(x_lw, y_axis, x_rw, y_axis,
                         fill=COLOR_INK, width=2)
        # Barres écorce (brun foncé épais) aux extrémités
        if ep > 0:
            bar_h = 7
            self.create_rectangle(x_le, y_axis - bar_h/2,
                                  x_lw, y_axis + bar_h/2,
                                  fill=COLOR_BARK, outline="")
            self.create_rectangle(x_rw, y_axis - bar_h/2,
                                  x_re, y_axis + bar_h/2,
                                  fill=COLOR_BARK, outline="")
        # Tirets aux extrémités externes (R+ep)
        end_color = COLOR_BARK if ep > 0 else COLOR_INK
        self.create_line(x_le, y_axis - 8, x_le, y_axis + 8,
                         fill=end_color, width=2)
        self.create_line(x_re, y_axis - 8, x_re, y_axis + 8,
                         fill=end_color, width=2)
        # Tirets à la transition bois/écorce (R)
        if ep > 0:
            self.create_line(x_lw, y_axis - 6, x_lw, y_axis + 6,
                             fill=COLOR_INK, width=2)
            self.create_line(x_rw, y_axis - 6, x_rw, y_axis + 6,
                             fill=COLOR_INK, width=2)
        # Graduations intermédiaires (bois) tous les `step` cm,
        # exclues à la valeur R (déjà marquée par le tiret de transition).
        for r in range(step, int(R), step):
            rr = r * scale
            for sign in (-1, 1):
                xg = cx + sign * rr
                self.create_line(xg, y_axis - 4, xg, y_axis + 4,
                                 fill=COLOR_INK, width=1)
                self.create_text(xg, y_axis + 15, text=f"{r}",
                                 anchor="center",
                                 font=("Helvetica", 8), fill=COLOR_INK)
        # Étiquette à R (bord bois/écorce) en gras
        if R > 0:
            label_R = f"{R:g}"
            for xg in (x_lw, x_rw):
                self.create_text(xg, y_axis + 15, text=label_R,
                                 anchor="center",
                                 font=("Helvetica", 8, "bold"),
                                 fill=COLOR_INK)
        # Étiquette à R+ep (extrémité externe) en gras brun.
        # Si l'écart bois/écorce est trop serré (ep_px < 25), on
        # décale l'étiquette d'une ligne en dessous pour ne pas
        # chevaucher l'étiquette R.
        if ep > 0:
            label_ext = f"{R + ep:g}"
            ext_y = y_axis + (27 if ep * scale < 25 else 15)
            for xg in (x_le, x_re):
                self.create_text(xg, ext_y, text=label_ext,
                                 anchor="center",
                                 font=("Helvetica", 8, "bold"),
                                 fill=COLOR_BARK)
        # Repère "0" au centre + label "cm" à droite
        self.create_text(cx, y_axis + 15, text="0", anchor="center",
                         font=("Helvetica", 8, "bold"), fill=COLOR_INK)
        self.create_text(x_re + 18, y_axis, text="cm",
                         anchor="w",
                         font=("Helvetica", 9, "bold italic"),
                         fill=COLOR_INK)

        # 8. Titre + méta — placés au-dessus de la zone du tronc
        title = A.display_name
        # Position : entre y=10 et la lettre N (à cy - radius_px - 25)
        title_y = 16
        sub_y = 38
        self.create_text(w/2, title_y, text=title,
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

        # (Stats globales déplacées dans l'onglet Diagnostic)

    @staticmethod
    def _mix(c1: str, c2: str, t: float) -> str:
        def h2r(c): return tuple(int(c[i:i+2], 16) for i in (1, 3, 5))
        r1, g1, b1 = h2r(c1)
        r2, g2, b2 = h2r(c2)
        return f"#{int(r1+(r2-r1)*t):02x}{int(g1+(g2-g1)*t):02x}{int(b1+(b2-b1)*t):02x}"


# ---------------------------------------------------------------------------
# Application principale
# ---------------------------------------------------------------------------

class App(tk.Tk):

    def __init__(self) -> None:
        super().__init__()
        self.title(f"Pénétromètre — Expertise arboricole (v{__version__})")
        self.geometry("1480x900")
        self.minsize(1280, 780)
        self.configure(bg=COLOR_BG)

        self.chantier = Chantier()
        self.chantier.arbres.append(Arbre(numero_arbre="1"))
        self.current_idx = 0
        self.current_file: Optional[Path] = None
        self._suspend_sync = False

        self._setup_style()
        self._build_menu()
        self._build_layout()
        self._refresh_tree_arbres()
        self._load_arbre_to_ui()

    def _setup_style(self) -> None:
        s = ttk.Style(self)
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass
        s.configure(".", background=COLOR_BG, foreground=COLOR_INK,
                    font=("Helvetica", 10))
        s.configure("TFrame", background=COLOR_BG)
        s.configure("Panel.TFrame", background=COLOR_PANEL)
        s.configure("Side.TFrame", background=COLOR_SIDE_PANEL)
        s.configure("TLabel", background=COLOR_BG, foreground=COLOR_INK)
        s.configure("Panel.TLabel", background=COLOR_PANEL, foreground=COLOR_INK)
        s.configure("Side.TLabel", background=COLOR_SIDE_PANEL, foreground=COLOR_INK)
        s.configure("Title.TLabel", background=COLOR_BG,
                    foreground=COLOR_ACCENT,
                    font=("Georgia", 18, "bold"))
        s.configure("Sub.TLabel", background=COLOR_BG, foreground=COLOR_MUTED,
                    font=("Helvetica", 10, "italic"))
        s.configure("H.TLabel", background=COLOR_PANEL, foreground=COLOR_ACCENT,
                    font=("Georgia", 12, "bold"))
        s.configure("Muted.TLabel", background=COLOR_PANEL, foreground=COLOR_MUTED,
                    font=("Helvetica", 9))
        s.configure("TButton", padding=6)
        s.configure("Accent.TButton", background=COLOR_ACCENT,
                    foreground="white", padding=(12, 7),
                    font=("Helvetica", 10, "bold"), borderwidth=0)
        s.map("Accent.TButton",
              background=[("active", COLOR_WOOD_DARK),
                          ("pressed", COLOR_WOOD_DARK)])
        s.configure("Ghost.TButton", background=COLOR_PANEL,
                    foreground=COLOR_ACCENT, padding=(10, 6),
                    font=("Helvetica", 10), borderwidth=1)
        s.map("Ghost.TButton",
              background=[("active", COLOR_ACCENT_SOFT)])
        s.configure("TEntry", fieldbackground=COLOR_PANEL, foreground=COLOR_INK,
                    padding=3)
        s.configure("TNotebook", background=COLOR_PANEL, borderwidth=0)
        s.configure("TNotebook.Tab", padding=(16, 9),
                    font=("Helvetica", 10, "bold"),
                    background="#E7E2D4", foreground=COLOR_MUTED)
        s.map("TNotebook.Tab",
              background=[("selected", COLOR_PANEL)],
              foreground=[("selected", COLOR_ACCENT)])
        s.configure("Treeview", background=COLOR_PANEL,
                    fieldbackground=COLOR_PANEL, foreground=COLOR_INK,
                    rowheight=26, borderwidth=0)
        s.configure("Treeview.Heading",
                    background=COLOR_ACCENT, foreground="white",
                    font=("Helvetica", 10, "bold"), borderwidth=0)
        s.map("Treeview",
              background=[("selected", COLOR_ACCENT_SOFT)],
              foreground=[("selected", COLOR_INK)])
        s.configure("Side.Treeview", background=COLOR_SIDE_PANEL,
                    fieldbackground=COLOR_SIDE_PANEL, rowheight=28)
        s.map("Side.Treeview",
              background=[("selected", COLOR_ACCENT)],
              foreground=[("selected", "white")])

    def _build_menu(self) -> None:
        m = tk.Menu(self)
        self.config(menu=m)
        f = tk.Menu(m, tearoff=0)
        f.add_command(label="Nouvelle mission", accelerator="Ctrl+N",
                      command=self.action_new)
        f.add_command(label="Ouvrir mission…", accelerator="Ctrl+O",
                      command=self.action_open)
        f.add_command(label="Enregistrer", accelerator="Ctrl+S",
                      command=self.action_save)
        f.add_command(label="Enregistrer sous…", command=self.action_save_as)
        f.add_separator()
        f.add_command(label="Exporter dessin (PNG)…",
                      command=self.action_export_png)
        f.add_command(label="Exporter fiche arbre (PDF)…",
                      command=self.action_export_pdf_arbre)
        f.add_command(label="Exporter tableau arbre (XLSX)…",
                      command=self.action_export_prbs_xlsx)
        f.add_command(label="Exporter tableau arbre (HTML)…",
                      command=self.action_export_prbs_html)
        f.add_command(label="Exporter sondages mission (CSV)…",
                      command=self.action_export_csv)
        f.add_separator()
        f.add_command(label="Quitter", command=self.destroy)
        m.add_cascade(label="Fichier", menu=f)

        a = tk.Menu(m, tearoff=0)
        a.add_command(label="Ajouter un arbre", accelerator="Ctrl+T",
                      command=self.action_add_arbre)
        a.add_command(label="Dupliquer l'arbre courant",
                      command=self.action_dup_arbre)
        a.add_command(label="Renommer l'arbre courant",
                      command=self.action_rename_arbre)
        a.add_command(label="Supprimer l'arbre courant",
                      command=self.action_del_arbre)
        m.add_cascade(label="Arbres", menu=a)

        h = tk.Menu(m, tearoff=0)
        h.add_command(label="À propos", command=self.action_about)
        m.add_cascade(label="?", menu=h)

        self.bind_all("<Control-n>", lambda e: self.action_new())
        self.bind_all("<Control-o>", lambda e: self.action_open())
        self.bind_all("<Control-s>", lambda e: self.action_save())
        self.bind_all("<Control-t>", lambda e: self.action_add_arbre())

    def _build_layout(self) -> None:
        header = ttk.Frame(self)
        header.pack(fill="x", padx=18, pady=(14, 6))

        # Bloc gauche : titre app
        left = ttk.Frame(header)
        left.pack(side="left")
        ttk.Label(left, text="Pénétromètre",
                  style="Title.TLabel").pack(side="left")
        ttk.Label(left, text="  Expertise arboricole",
                  style="Sub.TLabel").pack(side="left", padx=(8, 0))

        # Bloc droit : logo Silvavenir (si disponible)
        self._logo_image = None
        try:
            from PIL import Image as PILImage, ImageTk
            logo_path = Path(__file__).parent / "assets" / "silvavenir_logo.jpg"
            if logo_path.exists():
                pil = PILImage.open(logo_path)
                # Redimensionner à 60 px de haut en gardant le ratio
                target_h = 56
                ratio = target_h / pil.height
                pil = pil.resize(
                    (int(pil.width * ratio), target_h),
                    PILImage.LANCZOS)
                self._logo_image = ImageTk.PhotoImage(pil)
                logo_lbl = ttk.Label(header, image=self._logo_image)
                logo_lbl.pack(side="right")
        except Exception:
            # Fallback texte si PIL/logo indisponible
            ttk.Label(header, text="SILVAVENIR",
                      style="Title.TLabel").pack(side="right")

        meta = ttk.Frame(self)
        meta.pack(fill="x", padx=18, pady=(0, 10))
        self.var_ch_nom = tk.StringVar(value=self.chantier.nom)
        self.var_ch_adr = tk.StringVar(value=self.chantier.adresse)
        self.var_ch_ope = tk.StringVar(value=self.chantier.operateur)
        self.var_ch_date = tk.StringVar(value=self.chantier.date_releve)
        for lbl, var, w in [("Mission", self.var_ch_nom, 22),
                            ("Adresse", self.var_ch_adr, 30),
                            ("Opérateur", self.var_ch_ope, 18),
                            ("Date", self.var_ch_date, 12)]:
            ttk.Label(meta, text=lbl).pack(side="left", padx=(0, 4))
            e = ttk.Entry(meta, textvariable=var, width=w)
            e.pack(side="left", padx=(0, 14))
            var.trace_add("write", lambda *a: self._sync_chantier_meta())

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=18, pady=(0, 14))
        body.columnconfigure(0, weight=0, minsize=230)
        body.columnconfigure(1, weight=0, minsize=440)
        body.columnconfigure(2, weight=1, minsize=500)
        body.rowconfigure(0, weight=1)
        self._build_left(body)
        self._build_center(body)
        self._build_right(body)

    def _build_left(self, parent) -> None:
        frame = ttk.Frame(parent, style="Side.TFrame", padding=10)
        frame.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        ttk.Label(frame, text="Arbres de la mission", style="Side.TLabel",
                  font=("Georgia", 12, "bold")).pack(anchor="w", pady=(0, 8))

        lst_frame = ttk.Frame(frame, style="Side.TFrame")
        lst_frame.pack(fill="both", expand=True)
        self.tree_arbres = ttk.Treeview(
            lst_frame, columns=("ess",), show="tree headings",
            height=20, style="Side.Treeview")
        self.tree_arbres.heading("#0", text="Nom")
        self.tree_arbres.heading("ess", text="Essence")
        self.tree_arbres.column("#0", width=130, anchor="w")
        self.tree_arbres.column("ess", width=90, anchor="w")
        self.tree_arbres.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(lst_frame, orient="vertical",
                           command=self.tree_arbres.yview)
        sb.pack(side="right", fill="y")
        self.tree_arbres.configure(yscrollcommand=sb.set)
        self.tree_arbres.bind("<<TreeviewSelect>>", self._on_select_arbre)
        self.tree_arbres.bind("<Double-1>",
                              lambda e: self.action_rename_arbre())

        btns = ttk.Frame(frame, style="Side.TFrame")
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="＋ Ajouter", style="Accent.TButton",
                   command=self.action_add_arbre).pack(side="left")
        ttk.Button(btns, text="Dupliquer", style="Ghost.TButton",
                   command=self.action_dup_arbre
                   ).pack(side="left", padx=(6, 0))
        ttk.Button(btns, text="Supprimer", style="Ghost.TButton",
                   command=self.action_del_arbre
                   ).pack(side="left", padx=(6, 0))

    def _build_center(self, parent) -> None:
        frame = ttk.Frame(parent, style="Panel.TFrame", padding=12)
        frame.grid(row=0, column=1, sticky="nsew", padx=(0, 12))
        nb = ttk.Notebook(frame)
        nb.pack(fill="both", expand=True)

        # Onglet Identification
        t1 = ttk.Frame(nb, style="Panel.TFrame", padding=12)
        nb.add(t1, text="Identification")
        self.var_num = tk.StringVar()
        self.var_essence = tk.StringVar()
        self.var_h_s = tk.StringVar()
        self.var_diam = tk.StringVar()
        self.var_h_arb = tk.StringVar()
        self.var_port = tk.StringVar(value="libre")
        self.var_rayon = tk.StringVar(value="20")
        self.var_meche = tk.StringVar(value="40")
        self.var_ep_ecorce = tk.StringVar(value="0")
        self.var_comm = tk.StringVar()

        rows = [
            ("N° arbre",                  self.var_num, None),
            ("Essence",                   self.var_essence, None),
            ("Diamètre sous écorce (cm)", self.var_diam, None),
            ("Rayon du tronc (cm)",       self.var_rayon, None),
            ("Longueur de la mèche (cm)", self.var_meche, None),
            ("Épaisseur de l'écorce (cm)", self.var_ep_ecorce, None),
            ("Hauteur du sondage (cm)",   self.var_h_s, None),
            ("Hauteur de l'arbre (m)",    self.var_h_arb, None),
            ("Port de l'arbre",           self.var_port, list(PORTS_ARBRE)),
            ("Commentaire",               self.var_comm, None),
        ]
        for i, (lbl, var, choices) in enumerate(rows):
            ttk.Label(t1, text=lbl, style="Panel.TLabel").grid(
                row=i, column=0, sticky="w", pady=5, padx=(0, 10))
            if choices:
                w = ttk.Combobox(t1, textvariable=var, values=choices,
                                 state="readonly", width=30)
            else:
                w = ttk.Entry(t1, textvariable=var, width=32)
            w.grid(row=i, column=1, sticky="we", pady=5)
            var.trace_add("write", lambda *a: self._sync_ui_to_model())

        # Note d'aide sous les champs
        ttk.Label(t1,
                  text="ⓘ Saisir le diamètre sous écorce calcule le rayon "
                       "automatiquement (÷ 2). Le rayon reste modifiable "
                       "indépendamment si besoin.",
                  style="Muted.TLabel", wraplength=380, justify="left"
                  ).grid(row=len(rows), column=0, columnspan=2,
                         sticky="we", pady=(10, 0))
        ttk.Label(t1,
                  text="ⓘ Si vous corrigez le rayon après avoir saisi des "
                       "sondages, la PRBS (bois sain) reste inchangée car "
                       "elle correspond à la mesure physique du "
                       "pénétromètre. Le bois altéré est recalculé "
                       "automatiquement (= rayon − bois sain).",
                  style="Muted.TLabel", wraplength=380, justify="left"
                  ).grid(row=len(rows)+1, column=0, columnspan=2,
                         sticky="we", pady=(6, 0))
        t1.columnconfigure(1, weight=1)

        # Onglet Sondages
        t2 = ttk.Frame(nb, style="Panel.TFrame", padding=10)
        nb.add(t2, text="Sondages")
        ttk.Label(t2,
                  text="Chaque ligne = un sondage. Le dessin et les épaisseurs "
                       "d'altération par direction sont recalculés automatiquement.",
                  style="Muted.TLabel", wraplength=400, justify="left"
                  ).pack(anchor="w", pady=(0, 8))

        tbl_frame = ttk.Frame(t2, style="Panel.TFrame")
        tbl_frame.pack(fill="both", expand=True)
        cols = ("n", "grade", "dir", "sain", "altere", "comp")
        self.tbl = ttk.Treeview(tbl_frame, columns=cols, show="headings",
                                height=12)
        heads = [("n", "N°", 40), ("grade", "Grade (gr)", 80),
                 ("dir", "Direction", 80),
                 ("sain", "Bois sain (cm)", 100),
                 ("altere", "Altéré (cm)", 95),
                 ("comp", "Compart.", 85)]
        for k, lbl, w in heads:
            self.tbl.heading(k, text=lbl)
            self.tbl.column(k, width=w, anchor="center")
        self.tbl.pack(side="left", fill="both", expand=True)
        sb2 = ttk.Scrollbar(tbl_frame, orient="vertical",
                            command=self.tbl.yview)
        sb2.pack(side="right", fill="y")
        self.tbl.configure(yscrollcommand=sb2.set)
        self.tbl.bind("<Double-1>", lambda e: self.action_edit_sondage())

        tb = ttk.Frame(t2, style="Panel.TFrame")
        tb.pack(fill="x", pady=(10, 0))
        ttk.Button(tb, text="＋ Ajouter sondage", style="Accent.TButton",
                   command=self.action_add_sondage).pack(side="left")
        ttk.Button(tb, text="Éditer", style="Ghost.TButton",
                   command=self.action_edit_sondage
                   ).pack(side="left", padx=(6, 0))
        ttk.Button(tb, text="Supprimer", style="Ghost.TButton",
                   command=self.action_del_sondage
                   ).pack(side="left", padx=(6, 0))

        # Onglet Dégradations externes
        t_de = ttk.Frame(nb, style="Panel.TFrame", padding=10)
        nb.add(t_de, text="Dégrad. externes")

        ttk.Label(t_de,
                  text="Une dégradation externe = un arc continu sur l'écorce, "
                       "défini par un grade de début, un grade de fin (sens "
                       "horaire) et une profondeur radiale en cm.",
                  style="Muted.TLabel", wraplength=400, justify="left"
                  ).pack(anchor="w", pady=(0, 8))

        de_frame = ttk.Frame(t_de, style="Panel.TFrame")
        de_frame.pack(fill="both", expand=True)

        cols_de = ("n", "debut", "fin", "largeur_gr", "largeur_cm",
                   "profondeur", "comm")
        self.tbl_de = ttk.Treeview(de_frame, columns=cols_de,
                                    show="headings", height=10)
        de_heads = [("n", "N°", 35),
                    ("debut", "Début (gr)", 75),
                    ("fin", "Fin (gr)", 75),
                    ("largeur_gr", "Largeur (gr)", 85),
                    ("largeur_cm", "Largeur (cm)", 85),
                    ("profondeur", "Profondeur (cm)", 105),
                    ("comm", "Commentaire", 100)]
        for k, lbl, w in de_heads:
            self.tbl_de.heading(k, text=lbl)
            self.tbl_de.column(k, width=w, anchor="center")
        self.tbl_de.pack(side="left", fill="both", expand=True)
        sb_de = ttk.Scrollbar(de_frame, orient="vertical",
                              command=self.tbl_de.yview)
        sb_de.pack(side="right", fill="y")
        self.tbl_de.configure(yscrollcommand=sb_de.set)
        self.tbl_de.bind("<Double-1>",
                          lambda e: self.action_edit_degradation())

        tb_de = ttk.Frame(t_de, style="Panel.TFrame")
        tb_de.pack(fill="x", pady=(10, 0))
        ttk.Button(tb_de, text="＋ Ajouter dégradation",
                   style="Accent.TButton",
                   command=self.action_add_degradation
                   ).pack(side="left")
        ttk.Button(tb_de, text="Éditer", style="Ghost.TButton",
                   command=self.action_edit_degradation
                   ).pack(side="left", padx=(6, 0))
        ttk.Button(tb_de, text="Supprimer", style="Ghost.TButton",
                   command=self.action_del_degradation
                   ).pack(side="left", padx=(6, 0))

        # Onglet Contreforts (empattements à la base du tronc)
        t_cf = ttk.Frame(nb, style="Panel.TFrame", padding=10)
        nb.add(t_cf, text="Contreforts")

        ttk.Label(t_cf,
                  text="Un contrefort = empattement saillant à la base du "
                       "tronc, défini par une orientation (grade central), "
                       "une largeur en grades et une longueur radiale en cm "
                       "vers l'extérieur. Élément descriptif (n'impacte pas "
                       "le diagnostic).",
                  style="Muted.TLabel", wraplength=420, justify="left"
                  ).pack(anchor="w", pady=(0, 8))

        cf_frame = ttk.Frame(t_cf, style="Panel.TFrame")
        cf_frame.pack(fill="both", expand=True)

        cols_cf = ("n", "centre", "largeur_gr", "largeur_cm",
                   "longueur", "comm")
        self.tbl_cf = ttk.Treeview(cf_frame, columns=cols_cf,
                                    show="headings", height=10)
        cf_heads = [("n", "N°", 35),
                    ("centre", "Orientation (gr)", 120),
                    ("largeur_gr", "Largeur (gr)", 90),
                    ("largeur_cm", "Largeur (cm)", 90),
                    ("longueur", "Longueur (cm)", 100),
                    ("comm", "Commentaire", 120)]
        for k, lbl, w in cf_heads:
            self.tbl_cf.heading(k, text=lbl)
            self.tbl_cf.column(k, width=w, anchor="center")
        self.tbl_cf.pack(side="left", fill="both", expand=True)
        sb_cf = ttk.Scrollbar(cf_frame, orient="vertical",
                              command=self.tbl_cf.yview)
        sb_cf.pack(side="right", fill="y")
        self.tbl_cf.configure(yscrollcommand=sb_cf.set)
        self.tbl_cf.bind("<Double-1>",
                          lambda e: self.action_edit_contrefort())

        tb_cf = ttk.Frame(t_cf, style="Panel.TFrame")
        tb_cf.pack(fill="x", pady=(10, 0))
        ttk.Button(tb_cf, text="＋ Ajouter contrefort",
                   style="Accent.TButton",
                   command=self.action_add_contrefort
                   ).pack(side="left")
        ttk.Button(tb_cf, text="Éditer", style="Ghost.TButton",
                   command=self.action_edit_contrefort
                   ).pack(side="left", padx=(6, 0))
        ttk.Button(tb_cf, text="Supprimer", style="Ghost.TButton",
                   command=self.action_del_contrefort
                   ).pack(side="left", padx=(6, 0))

        # Onglet Diagnostic — wrapper scrollable
        t3_outer = ttk.Frame(nb, style="Panel.TFrame")
        nb.add(t3_outer, text="Diagnostic")

        # Canvas pour scroll + scrollbar verticale
        diag_canvas = tk.Canvas(t3_outer, bg=COLOR_PANEL,
                                 highlightthickness=0, bd=0)
        diag_scroll = ttk.Scrollbar(t3_outer, orient="vertical",
                                     command=diag_canvas.yview)
        diag_canvas.configure(yscrollcommand=diag_scroll.set)
        diag_canvas.pack(side="left", fill="both", expand=True)
        diag_scroll.pack(side="right", fill="y")

        # Frame intérieur (le vrai conteneur du contenu)
        t3 = ttk.Frame(diag_canvas, style="Panel.TFrame", padding=14)
        t3_window = diag_canvas.create_window((0, 0), window=t3, anchor="nw")

        # Mise à jour de la scrollregion à chaque changement de taille du
        # contenu, et redimensionnement de la largeur du frame intérieur
        # pour qu'il occupe toute la largeur visible.
        def _on_configure_inner(event):
            diag_canvas.configure(scrollregion=diag_canvas.bbox("all"))
        def _on_configure_outer(event):
            diag_canvas.itemconfigure(t3_window, width=event.width)
        t3.bind("<Configure>", _on_configure_inner)
        diag_canvas.bind("<Configure>", _on_configure_outer)

        # Molette de souris (Windows / Linux)
        def _on_mousewheel(event):
            diag_canvas.yview_scroll(int(-event.delta / 120), "units")
        def _on_mousewheel_linux(event):
            diag_canvas.yview_scroll(-1 if event.num == 4 else 1, "units")
        diag_canvas.bind_all("<MouseWheel>", _on_mousewheel)
        diag_canvas.bind_all("<Button-4>", _on_mousewheel_linux)
        diag_canvas.bind_all("<Button-5>", _on_mousewheel_linux)

        # --- Boutons d'export EN HAUT (toujours accessibles) ---
        btn_exp = ttk.Frame(t3, style="Panel.TFrame")
        btn_exp.pack(fill="x", pady=(0, 12))
        ttk.Button(btn_exp, text="📄 Fiche PDF (arbre courant)",
                   style="Accent.TButton",
                   command=self.action_export_pdf_arbre
                   ).pack(side="left", padx=(0, 6))
        ttk.Button(btn_exp, text="🖼 PNG du dessin", style="Ghost.TButton",
                   command=self.action_export_png
                   ).pack(side="left", padx=(0, 6))
        ttk.Button(btn_exp, text="📊 Tableau XLSX", style="Ghost.TButton",
                   command=self.action_export_prbs_xlsx
                   ).pack(side="left", padx=(0, 6))
        ttk.Button(btn_exp, text="🌐 Tableau HTML", style="Ghost.TButton",
                   command=self.action_export_prbs_html
                   ).pack(side="left", padx=(0, 6))
        ttk.Button(btn_exp, text="📋 CSV mission", style="Ghost.TButton",
                   command=self.action_export_csv
                   ).pack(side="left")

        # --- Bloc résumé haut ---
        ttk.Label(t3, text="Résumé de l'arbre courant",
                  style="H.TLabel").pack(anchor="w", pady=(4, 4))
        self.lbl_diag = ttk.Label(
            t3, text="", style="Panel.TLabel",
            wraplength=400, justify="left", font=("Helvetica", 10))
        self.lbl_diag.pack(anchor="w", fill="x", pady=(0, 10))

        # --- Case à cocher affichage des sondages ---
        self.var_show_sondages = tk.BooleanVar(value=True)
        cb = ttk.Checkbutton(
            t3, text="Afficher l'emplacement des sondages sur le dessin",
            variable=self.var_show_sondages,
            command=self._toggle_show_sondages, style="TCheckbutton")
        cb.pack(anchor="w", pady=(0, 10))

        # --- Tableau PRBS par sondage ---
        ttk.Label(t3, text="Paroi Résiduelle de Bois Sain par sondage",
                  style="H.TLabel").pack(anchor="w", pady=(4, 4))
        ttk.Label(t3,
                  text="Classe colorée selon t/R et le port (barème "
                       "Silvavenir).",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 6))

        prbs_frame = ttk.Frame(t3, style="Panel.TFrame")
        prbs_frame.pack(fill="x", pady=(0, 10))
        cols_p = ("n", "dir", "prbs", "tR", "classe")
        self.tbl_prbs = ttk.Treeview(prbs_frame, columns=cols_p,
                                     show="headings", height=8)
        self.tbl_prbs.heading("n", text="N°")
        self.tbl_prbs.heading("dir", text="Direction")
        self.tbl_prbs.heading("prbs", text="PRBS (cm)")
        self.tbl_prbs.heading("tR", text="t/R (%)")
        self.tbl_prbs.heading("classe", text="Classe")
        self.tbl_prbs.column("n", width=35, anchor="center")
        self.tbl_prbs.column("dir", width=80, anchor="center")
        self.tbl_prbs.column("prbs", width=85, anchor="center")
        self.tbl_prbs.column("tR", width=70, anchor="center")
        self.tbl_prbs.column("classe", width=90, anchor="center")
        self.tbl_prbs.pack(side="left", fill="x", expand=True)
        # Tags colorés pour les 3 classes
        self.tbl_prbs.tag_configure(
            "vert",   background="#E3F1E6", foreground="#1A5A2A")
        self.tbl_prbs.tag_configure(
            "orange", background="#FDEBD5", foreground="#8A4A10")
        self.tbl_prbs.tag_configure(
            "rouge",  background="#FADBD8", foreground="#7B1B12")

    def _build_right(self, parent) -> None:
        frame = ttk.Frame(parent, style="Panel.TFrame", padding=10)
        frame.grid(row=0, column=2, sticky="nsew")
        self.section = SectionCanvas(frame, width=550, height=550)
        self.section.pack(fill="both", expand=True)

    # --- Synchro -----------------------------------------------------

    def _current_arbre(self) -> Optional[Arbre]:
        if not self.chantier.arbres:
            return None
        return self.chantier.arbres[self.current_idx]

    def _sync_chantier_meta(self) -> None:
        if self._suspend_sync:
            return
        self.chantier.nom = self.var_ch_nom.get()
        self.chantier.adresse = self.var_ch_adr.get()
        self.chantier.operateur = self.var_ch_ope.get()
        self.chantier.date_releve = self.var_ch_date.get()

    def _sync_ui_to_model(self) -> None:
        if self._suspend_sync:
            return
        a = self._current_arbre()
        if not a:
            return

        # Détecter lequel des deux champs Ø / rayon vient d'être modifié
        # pour répercuter automatiquement sur l'autre (sans boucle infinie).
        try:
            new_diam = float(self.var_diam.get() or 0)
        except ValueError:
            new_diam = a.diametre_sous_ecorce_cm
        try:
            new_rayon = float(self.var_rayon.get() or 0)
        except ValueError:
            new_rayon = a.rayon_tronc_cm

        diam_changed = abs(new_diam - a.diametre_sous_ecorce_cm) > 1e-9
        rayon_changed = abs(new_rayon - a.rayon_tronc_cm) > 1e-9
        old_rayon = a.rayon_tronc_cm

        try:
            a.numero_arbre = self.var_num.get()
            a.essence = self.var_essence.get()
            a.hauteur_sondage_cm = float(self.var_h_s.get() or 0)
            a.hauteur_arbre_m = float(self.var_h_arb.get() or 0)
            a.meche_cm = float(self.var_meche.get() or 0)
            a.epaisseur_ecorce_cm = max(0.0,
                float(self.var_ep_ecorce.get() or 0))
            a.port_arbre = self.var_port.get()
            a.commentaire = self.var_comm.get()

            # Règle de cohérence Ø / rayon :
            # - si l'utilisateur a édité le diamètre, on recalcule le rayon
            # - si l'utilisateur a édité le rayon, on laisse le diamètre tel quel
            #   (cas "j'ai mesuré directement sur le sondage")
            if diam_changed and not rayon_changed:
                a.diametre_sous_ecorce_cm = new_diam
                a.rayon_tronc_cm = new_diam / 2.0
                # répercuter dans l'UI sans redéclencher la synchro
                self._suspend_sync = True
                self.var_rayon.set(f"{a.rayon_tronc_cm:g}")
                self._suspend_sync = False
            else:
                a.diametre_sous_ecorce_cm = new_diam
                a.rayon_tronc_cm = new_rayon
        except ValueError:
            return

        # Si le rayon a changé, on conserve la PRBS (bois sain) qui est
        # la mesure physique du pénétromètre, et on ajuste le bois altéré
        # pour rester cohérent avec le nouveau rayon (sain + altéré = R).
        # - rayon plus grand : altéré augmente
        # - rayon plus petit : altéré diminue (et on borne sain à R)
        # Idem pour la profondeur des dégradations externes : on la
        # conserve telle quelle (mesure physique d'épaisseur d'écorce
        # dégradée), elle ne dépend pas du rayon.
        if old_rayon > 0 and abs(a.rayon_tronc_cm - old_rayon) > 1e-9:
            R_new = a.rayon_tronc_cm
            for s in a.sondages:
                # Si le nouveau rayon est plus petit que la PRBS saisie,
                # on borne la PRBS au nouveau rayon (pas physique sinon).
                s.bois_sain_cm = min(s.bois_sain_cm, R_new)
                s.bois_altere_cm = max(0.0, R_new - s.bois_sain_cm)
            # Les profondeurs de dégradations externes sont des mesures
            # physiques (épaisseur d'écorce dégradée) — on les borne juste
            # au nouveau rayon par sécurité.
            for deg in a.degradations_externes:
                deg.profondeur_cm = min(deg.profondeur_cm, R_new)
            # On rafraîchit les tableaux car les valeurs altéré/profondeur
            # ont changé
            self._refresh_sondages_table()
            self._refresh_degradations_table()
            # La colonne "Largeur (cm)" des contreforts dépend de R
            self._refresh_contreforts_table()

        self._debounced_redraw()
        sel = self.tree_arbres.selection()
        if sel:
            label = f"n° {a.numero_arbre}" if a.numero_arbre else "(sans n°)"
            self.tree_arbres.item(sel[0], text=label,
                                  values=(a.essence,))

    def _load_arbre_to_ui(self) -> None:
        a = self._current_arbre()
        if not a:
            return
        self._suspend_sync = True
        self.var_num.set(a.numero_arbre)
        self.var_essence.set(a.essence)
        self.var_rayon.set(f"{a.rayon_tronc_cm:g}")
        self.var_h_s.set(f"{a.hauteur_sondage_cm:g}" if a.hauteur_sondage_cm else "")
        self.var_diam.set(f"{a.diametre_sous_ecorce_cm:g}" if a.diametre_sous_ecorce_cm else "")
        self.var_h_arb.set(f"{a.hauteur_arbre_m:g}" if a.hauteur_arbre_m else "")
        self.var_meche.set(f"{a.meche_cm:g}" if a.meche_cm else "40")
        self.var_ep_ecorce.set(f"{a.epaisseur_ecorce_cm:g}"
                                if a.epaisseur_ecorce_cm else "0")
        self.var_port.set(a.port_arbre)
        self.var_comm.set(a.commentaire)
        self._suspend_sync = False
        self._refresh_sondages_table()
        self._refresh_degradations_table()
        self._refresh_contreforts_table()
        self._debounced_redraw()

    def _debounced_redraw(self) -> None:
        if getattr(self, "_redraw_id", None):
            self.after_cancel(self._redraw_id)
        self._redraw_id = self.after(80, self._redraw_all)

    def _redraw_all(self) -> None:
        a = self._current_arbre()
        self.section.set_arbre(a)
        self._refresh_diag()

    # --- Liste d'arbres ---------------------------------------------

    def _refresh_tree_arbres(self) -> None:
        self.tree_arbres.delete(*self.tree_arbres.get_children())
        for i, a in enumerate(self.chantier.arbres):
            # Affichage compact : "n°X" (l'essence est dans la 2e colonne)
            label = f"n° {a.numero_arbre}" if a.numero_arbre else "(sans n°)"
            self.tree_arbres.insert("", "end", iid=f"a{i}",
                                    text=label, values=(a.essence,))
        if self.chantier.arbres:
            target = f"a{self.current_idx}"
            if target in self.tree_arbres.get_children():
                self.tree_arbres.selection_set(target)
                self.tree_arbres.focus(target)

    def _on_select_arbre(self, event=None) -> None:
        sel = self.tree_arbres.selection()
        if not sel:
            return
        idx = int(sel[0][1:])
        if idx == self.current_idx:
            return
        self.current_idx = idx
        self._load_arbre_to_ui()

    def action_add_arbre(self) -> None:
        # Numéro = plus grand numéro numérique existant + 1, ou len + 1
        max_num = 0
        for arb in self.chantier.arbres:
            try:
                max_num = max(max_num, int(arb.numero_arbre))
            except (ValueError, TypeError):
                pass
        new_num = str(max(max_num + 1, len(self.chantier.arbres) + 1))
        self.chantier.arbres.append(Arbre(numero_arbre=new_num))
        self.current_idx = len(self.chantier.arbres) - 1
        self._refresh_tree_arbres()
        self._load_arbre_to_ui()

    def action_dup_arbre(self) -> None:
        a = self._current_arbre()
        if not a:
            return
        import copy
        new = copy.deepcopy(a)
        # Nouveau numéro = numéro existant + suffixe 'bis', 'ter', etc.
        suffixes = ["", " bis", " ter", " quater"]
        base = a.numero_arbre
        for suf in suffixes[1:]:
            candidate = base + suf
            if not any(x.numero_arbre == candidate for x in self.chantier.arbres):
                new.numero_arbre = candidate
                break
        else:
            new.numero_arbre = base + " (copie)"
        self.chantier.arbres.insert(self.current_idx + 1, new)
        self.current_idx += 1
        self._refresh_tree_arbres()
        self._load_arbre_to_ui()

    def action_del_arbre(self) -> None:
        if len(self.chantier.arbres) <= 1:
            messagebox.showinfo("Information",
                                "La mission doit contenir au moins un arbre.")
            return
        a = self._current_arbre()
        if not messagebox.askyesno("Supprimer",
                                   f"Supprimer définitivement « {a.display_name} » ?"):
            return
        del self.chantier.arbres[self.current_idx]
        self.current_idx = max(0, self.current_idx - 1)
        self._refresh_tree_arbres()
        self._load_arbre_to_ui()

    def action_rename_arbre(self) -> None:
        a = self._current_arbre()
        if not a:
            return
        new = simpledialog.askstring("Renuméroter l'arbre",
                                     "Nouveau n° d'arbre :",
                                     initialvalue=a.numero_arbre, parent=self)
        if not new or new == a.numero_arbre:
            return
        # Avertissement non bloquant si le numéro est déjà utilisé par
        # un autre arbre de la mission. L'utilisateur peut quand même
        # confirmer (cas d'un renommage en chaîne, ou d'un doublon
        # volontaire pour un arbre jumeau identifié sur le terrain).
        already_used = any(x is not a and x.numero_arbre == new
                           for x in self.chantier.arbres)
        if already_used:
            confirmer = messagebox.askyesno(
                "Numéro déjà utilisé",
                f"Un autre arbre porte déjà le n° « {new} ».\n\n"
                "Continuer quand même ?")
            if not confirmer:
                return
        a.numero_arbre = new
        self.var_num.set(new)
        self._refresh_tree_arbres()

    # --- Sondages ---------------------------------------------------

    def _refresh_sondages_table(self) -> None:
        self.tbl.delete(*self.tbl.get_children())
        a = self._current_arbre()
        if not a:
            return
        for i, s in enumerate(a.sondages):
            direction = DIRECTION_LABELS.get(s.grade, "")
            if not direction and s.grade in GRADES:
                idx = GRADES.index(s.grade)
                for delta in (1, -1, 2, -2):
                    g2 = GRADES[(idx + delta) % 16]
                    if DIRECTION_LABELS.get(g2):
                        direction = f"~{DIRECTION_LABELS[g2]}"
                        break
            self.tbl.insert("", "end", iid=f"s{i}",
                            values=(s.numero, f"{s.grade}", direction,
                                    f"{s.bois_sain_cm:g}",
                                    f"{s.bois_altere_cm:g}",
                                    s.compartimentation))

    def action_add_sondage(self) -> None:
        a = self._current_arbre()
        if not a:
            return
        s = Sondage(numero=len(a.sondages) + 1, grade=0,
                    bois_sain_cm=a.rayon_tronc_cm, bois_altere_cm=0.0)
        if edit_sondage(self, a, s):
            a.sondages.append(s)
            self._renum_sondages(a)
            self._refresh_sondages_table()
            self._debounced_redraw()

    def action_edit_sondage(self) -> None:
        sel = self.tbl.selection()
        if not sel:
            return
        idx = int(sel[0][1:])
        a = self._current_arbre()
        if not a:
            return
        s = a.sondages[idx]
        if edit_sondage(self, a, s):
            self._refresh_sondages_table()
            self._debounced_redraw()

    def action_del_sondage(self) -> None:
        sel = self.tbl.selection()
        if not sel:
            return
        idx = int(sel[0][1:])
        a = self._current_arbre()
        if not a:
            return
        del a.sondages[idx]
        self._renum_sondages(a)
        self._refresh_sondages_table()
        self._debounced_redraw()

    def _renum_sondages(self, a: Arbre) -> None:
        for i, s in enumerate(a.sondages, 1):
            s.numero = i

    # ---- Dégradations externes -------------------------------------

    def _refresh_degradations_table(self) -> None:
        if not hasattr(self, "tbl_de"):
            return
        self.tbl_de.delete(*self.tbl_de.get_children())
        a = self._current_arbre()
        if not a:
            return
        R = a.rayon_tronc_cm
        for i, deg in enumerate(a.degradations_externes):
            self.tbl_de.insert(
                "", "end", iid=f"d{i}",
                values=(deg.numero,
                        f"{deg.grade_debut}",
                        f"{deg.grade_fin}",
                        f"{deg.largeur_grades()}",
                        f"{deg.largeur_cm(R):.1f}",
                        f"{deg.profondeur_cm:g}",
                        deg.commentaire))

    def action_add_degradation(self) -> None:
        a = self._current_arbre()
        if not a:
            return
        deg = DegradationExterne(
            numero=len(a.degradations_externes) + 1,
            grade_debut=0, grade_fin=50, profondeur_cm=2.0)
        if edit_degradation(self, a, deg):
            a.degradations_externes.append(deg)
            self._renum_degradations(a)
            self._refresh_degradations_table()
            self._debounced_redraw()

    def action_edit_degradation(self) -> None:
        sel = self.tbl_de.selection()
        if not sel:
            return
        idx = int(sel[0][1:])
        a = self._current_arbre()
        if not a:
            return
        deg = a.degradations_externes[idx]
        if edit_degradation(self, a, deg):
            self._refresh_degradations_table()
            self._debounced_redraw()

    def action_del_degradation(self) -> None:
        sel = self.tbl_de.selection()
        if not sel:
            return
        idx = int(sel[0][1:])
        a = self._current_arbre()
        if not a:
            return
        del a.degradations_externes[idx]
        self._renum_degradations(a)
        self._refresh_degradations_table()
        self._debounced_redraw()

    def _renum_degradations(self, a: Arbre) -> None:
        for i, deg in enumerate(a.degradations_externes, 1):
            deg.numero = i

    # --- Contreforts ---
    def _refresh_contreforts_table(self) -> None:
        if not hasattr(self, "tbl_cf"):
            return
        self.tbl_cf.delete(*self.tbl_cf.get_children())
        a = self._current_arbre()
        if not a:
            return
        R = a.rayon_tronc_cm
        for i, c in enumerate(a.contreforts):
            lbl = DIRECTION_LABELS.get(c.grade_centre, "")
            centre_txt = f"{c.grade_centre}" + (f" — {lbl}" if lbl else "")
            self.tbl_cf.insert(
                "", "end", iid=f"c{i}",
                values=(c.numero,
                        centre_txt,
                        f"{c.largeur_grades}",
                        f"{c.largeur_cm(R):.1f}",
                        f"{c.longueur_cm:g}",
                        c.commentaire))

    def action_add_contrefort(self) -> None:
        a = self._current_arbre()
        if not a:
            return
        c = Contrefort(numero=len(a.contreforts) + 1,
                       grade_centre=0, largeur_grades=75, longueur_cm=10.0)
        if edit_contrefort(self, a, c):
            a.contreforts.append(c)
            self._renum_contreforts(a)
            self._refresh_contreforts_table()
            self._debounced_redraw()

    def action_edit_contrefort(self) -> None:
        sel = self.tbl_cf.selection()
        if not sel:
            return
        idx = int(sel[0][1:])
        a = self._current_arbre()
        if not a:
            return
        c = a.contreforts[idx]
        if edit_contrefort(self, a, c):
            self._refresh_contreforts_table()
            self._debounced_redraw()

    def action_del_contrefort(self) -> None:
        sel = self.tbl_cf.selection()
        if not sel:
            return
        idx = int(sel[0][1:])
        a = self._current_arbre()
        if not a:
            return
        del a.contreforts[idx]
        self._renum_contreforts(a)
        self._refresh_contreforts_table()
        self._debounced_redraw()

    def _renum_contreforts(self, a: Arbre) -> None:
        for i, c in enumerate(a.contreforts, 1):
            c.numero = i

    def _toggle_show_sondages(self) -> None:
        """Réagit au check/uncheck de la case 'emplacement des sondages'."""
        self.section.set_show_sondages(self.var_show_sondages.get())

    def _refresh_diag(self) -> None:
        a = self._current_arbre()

        # --- Tableau PRBS par sondage ---
        self.tbl_prbs.delete(*self.tbl_prbs.get_children())
        if a and a.rayon_tronc_cm > 0:
            R = a.rayon_tronc_cm
            port = a.port_arbre
            deg_ext_par_grade = a.degradation_externe_par_grade()
            for s in a.sondages:
                direction = DIRECTION_LABELS.get(s.grade, "")
                if not direction and s.grade in GRADES:
                    idx = GRADES.index(s.grade)
                    for delta in (1, -1, 2, -2):
                        g2 = GRADES[(idx + delta) % 16]
                        if DIRECTION_LABELS.get(g2):
                            direction = f"~{DIRECTION_LABELS[g2]}"
                            break
                # PRBS ajustée = bois sain mesuré - dégradation externe
                # qui couvre cette direction
                idx_grade = GRADES.index(s.grade) if s.grade in GRADES else 0
                deg_ext = deg_ext_par_grade[idx_grade]
                prbs_adj = max(0.0, s.prbs_cm - deg_ext)
                ratio = prbs_adj / R if R > 0 else 0.0
                classe = classer_prbs(ratio, port)
                tag = classe.lower()
                # Affichage : si dégradation ext. présente, on note
                # la PRBS ajustée + le composant ext. en parenthèses
                if deg_ext > 0:
                    prbs_txt = f"{prbs_adj:g} (–{deg_ext:g} ext.)"
                else:
                    prbs_txt = f"{prbs_adj:g}"
                self.tbl_prbs.insert(
                    "", "end",
                    values=(s.numero, f"{direction} ({s.grade} gr)",
                            prbs_txt,
                            f"{100*ratio:.1f}",
                            classe),
                    tags=(tag,))

        # --- Texte de résumé enrichi ---
        if not a or a.rayon_tronc_cm <= 0:
            self.lbl_diag.configure(text="Renseignez le rayon du tronc et "
                                         "ajoutez des sondages pour obtenir "
                                         "un résumé.")
            return
        R = a.rayon_tronc_cm
        rep = a.repartition_classes()
        # En-tête
        lignes = [
            f"« {a.display_name} »",
            f"Rayon : {R:g} cm   •   Sondages : {len(a.sondages)}"
            f"   •   Dégrad. ext. : {len(a.degradations_externes)}"
            f"   •   Contreforts : {len(a.contreforts)}",
            f"Port : {a.port_arbre}",
            "",
        ]

        # Si rien de saisi
        ratios = a.ratio_tR_par_grade()
        if all(r >= 0.999 for r in ratios):
            lignes.append("Aucune altération saisie (interne ou externe).")
            self.lbl_diag.configure(text="\n".join(lignes))
            return

        # Direction critique
        lignes.append(
            f"t/R minimal : {100*rep['tR_min']:.1f} %  "
            f"(grade {rep['tR_min_grade']} gr — {rep['tR_min_dir']})")

        # Répartition sur les 16 directions
        lignes.append("")
        lignes.append("Répartition sur le pourtour (16 directions) :")
        for cls, symbol in (("Vert", "🟢"), ("Orange", "🟠"), ("Rouge", "🔴")):
            n = rep[cls]["n"]
            pct = rep[cls]["pct"]
            grades = rep[cls]["grades"]
            if n > 0:
                lignes.append(
                    f"  {symbol} {cls:<7} : {n}/16 directions  "
                    f"({grades} gr / {pct:.0f} % du pourtour)")

        lignes.append("")
        lignes.append(
            f"t/R moyen sur le pourtour : {100*rep['tR_moyen']:.1f} %")
        lignes.append(f"→ Classe globale : {rep['classe_globale']}")

        self.lbl_diag.configure(text="\n".join(lignes))

    # --- Fichier ----------------------------------------------------

    def action_new(self) -> None:
        if not messagebox.askyesno("Nouvelle mission",
                                   "Perdre les données non enregistrées ?"):
            return
        self.chantier = Chantier()
        self.chantier.arbres.append(Arbre(numero_arbre="1"))
        self.current_idx = 0
        self.current_file = None
        self._suspend_sync = True
        self.var_ch_nom.set(self.chantier.nom)
        self.var_ch_adr.set("")
        self.var_ch_ope.set("")
        self.var_ch_date.set(self.chantier.date_releve)
        self._suspend_sync = False
        self._refresh_tree_arbres()
        self._load_arbre_to_ui()

    def action_open(self) -> None:
        p = filedialog.askopenfilename(
            title="Ouvrir une mission",
            filetypes=[("Mission Pénétromètre", "*.json"),
                       ("Tous", "*.*")])
        if not p:
            return
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.chantier = Chantier.from_dict(data)
            if not self.chantier.arbres:
                self.chantier.arbres.append(Arbre())
            self.current_idx = 0
            self.current_file = Path(p)
            self._suspend_sync = True
            self.var_ch_nom.set(self.chantier.nom)
            self.var_ch_adr.set(self.chantier.adresse)
            self.var_ch_ope.set(self.chantier.operateur)
            self.var_ch_date.set(self.chantier.date_releve)
            self._suspend_sync = False
            self._refresh_tree_arbres()
            self._load_arbre_to_ui()
        except Exception as e:
            log.exception("Échec ouverture mission")
            messagebox.showerror("Erreur d'ouverture", str(e))

    def action_save(self) -> None:
        if not self.current_file:
            return self.action_save_as()
        try:
            with open(self.current_file, "w", encoding="utf-8") as f:
                json.dump(self.chantier.to_dict(), f, indent=2,
                          ensure_ascii=False)
            self.title(f"Pénétromètre — {self.current_file.name}")
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

    def action_export_png(self) -> None:
        if not HAS_PIL:
            messagebox.showinfo(
                "Pillow requis",
                "L'export PNG nécessite Pillow.\n"
                "Installez-le :  pip install Pillow")
            return
        a = self._current_arbre()
        if not a:
            return
        p = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("Image PNG", "*.png")])
        if not p:
            return
        try:
            img = render_arbre_to_pil_image(
                a, width=1600, height=1600,
                show_sondages=self.section.show_sondages,
                show_legend=True)
            img.save(p, "PNG")
            messagebox.showinfo("Exporté", f"Image enregistrée : {p}")
        except Exception as e:
            log.exception("Échec export PNG")
            messagebox.showerror("Erreur d'export", str(e))

    def action_export_pdf_arbre(self) -> None:
        """Exporte une fiche PDF (dessin + tableau + diagnostic) pour
        l'arbre courant. Utilise uniquement Pillow (multi-pages via save)."""
        if not HAS_PIL:
            messagebox.showinfo(
                "Pillow requis",
                "L'export PDF nécessite Pillow.\n"
                "Installez-le :  pip install Pillow")
            return
        a = self._current_arbre()
        if not a:
            return
        suggest = f"fiche_arbre_{a.numero_arbre or 'sans_num'}.pdf".replace(
            " ", "_")
        p = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            initialfile=suggest,
            filetypes=[("Document PDF", "*.pdf")])
        if not p:
            return
        try:
            page = render_fiche_arbre_to_pdf_page(a, self.chantier)
            # Pillow : sauvegarder une image en PDF donne un PDF 1 page
            page.save(p, "PDF", resolution=150.0)
            messagebox.showinfo("Exporté",
                                f"Fiche PDF enregistrée : {p}")
        except Exception as e:
            log.exception("Échec export PDF")
            messagebox.showerror("Erreur d'export PDF", str(e))

    def action_export_csv(self) -> None:
        p = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")])
        if not p:
            return
        try:
            with open(p, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f, delimiter=";")
                # Colonnes brutes : PRBS et Bois altéré tels que mesurés
                # par le pénétromètre. t/R (%) reste basé sur la PRBS
                # brute pour ne pas casser les ré-analyses existantes.
                # Colonnes ajustées : Dégrad. ext. retranchée + PRBS
                # effective et t/R ajusté + classe — cohérents avec le
                # tableau Diagnostic, la fiche PDF et les exports
                # XLSX/HTML.
                w.writerow(["N° arbre", "Essence", "Rayon (cm)",
                            "Port",
                            "N° sondage", "Grade (gr)", "Direction",
                            "PRBS (cm)", "Bois altéré (cm)",
                            "t/R (%)",
                            "Dégrad. ext. (cm)",
                            "PRBS ajustée (cm)",
                            "t/R ajusté (%)",
                            "Classe",
                            "Compartimentation", "Commentaire"])
                for a in self.chantier.arbres:
                    R = a.rayon_tronc_cm
                    deg_ext_par_grade = a.degradation_externe_par_grade()
                    for s in a.sondages:
                        d = DIRECTION_LABELS.get(s.grade, "")
                        tR_pct = f"{100*s.ratio_tR_brut(R):.1f}"
                        idx_g = (GRADES.index(s.grade)
                                 if s.grade in GRADES else 0)
                        deg_ext = deg_ext_par_grade[idx_g]
                        prbs_adj = max(0.0, s.prbs_cm - deg_ext)
                        ratio_adj = prbs_adj / R if R > 0 else 0.0
                        tR_adj_pct = f"{100*ratio_adj:.1f}"
                        classe = classer_prbs(ratio_adj, a.port_arbre)
                        w.writerow([a.numero_arbre, a.essence,
                                    a.rayon_tronc_cm, a.port_arbre,
                                    s.numero,
                                    s.grade, d,
                                    s.prbs_cm, s.bois_altere_cm,
                                    tR_pct,
                                    deg_ext,
                                    prbs_adj,
                                    tR_adj_pct,
                                    classe,
                                    s.compartimentation, s.commentaire])
            messagebox.showinfo("Exporté", f"CSV enregistré : {p}")
        except Exception as e:
            log.exception("Échec export CSV")
            messagebox.showerror("Erreur", str(e))

    def action_export_prbs_xlsx(self) -> None:
        a = self._current_arbre()
        if not a:
            return
        if not HAS_OPENPYXL:
            messagebox.showerror(
                "Export XLSX indisponible",
                "Le module openpyxl n'est pas installé.\n\n"
                "Pour activer cet export, lance dans un terminal :\n"
                "    pip install -r requirements.txt\n\n"
                "L'export HTML reste disponible sans dépendance.")
            return
        if a.rayon_tronc_cm <= 0:
            messagebox.showerror("Export impossible",
                "Renseigne un rayon de tronc avant l'export.")
            return
        default = (f"tableau_arbre_{a.numero_arbre or 'X'}.xlsx"
                   .replace(" ", "_"))
        p = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            initialfile=default,
            filetypes=[("Classeur Excel", "*.xlsx")])
        if not p:
            return
        try:
            export_prbs_xlsx(a, self.chantier, p,
                              couleur_classe=COULEUR_CLASSE,
                              classer_prbs=classer_prbs)
            messagebox.showinfo("Exporté", f"Tableau XLSX enregistré :\n{p}")
        except Exception as e:
            log.exception("Échec export XLSX")
            messagebox.showerror("Erreur", str(e))

    def action_export_prbs_html(self) -> None:
        a = self._current_arbre()
        if not a:
            return
        if a.rayon_tronc_cm <= 0:
            messagebox.showerror("Export impossible",
                "Renseigne un rayon de tronc avant l'export.")
            return
        default = (f"tableau_arbre_{a.numero_arbre or 'X'}.html"
                   .replace(" ", "_"))
        p = filedialog.asksaveasfilename(
            defaultextension=".html",
            initialfile=default,
            filetypes=[("Page HTML", "*.html")])
        if not p:
            return
        try:
            export_prbs_html(a, self.chantier, p,
                              couleur_classe=COULEUR_CLASSE,
                              classer_prbs=classer_prbs)
            messagebox.showinfo("Exporté", f"Tableau HTML enregistré :\n{p}")
        except Exception as e:
            log.exception("Échec export HTML")
            messagebox.showerror("Erreur", str(e))

    def action_about(self) -> None:
        messagebox.showinfo(
            "À propos",
            f"Pénétromètre — Expertise arboricole\n"
            f"Version {__version__}\n\n"
            "Application desktop Python autonome.\n"
            "Tableau de sondages ↔ dessin synchronisés.\n"
            "Section ronde par interpolation spline.\n\n"
            "Note : « Résistographe » étant une marque déposée,\n"
            "ce logiciel utilise le terme générique « pénétromètre »."
            "\n\n— Silvavenir, Foresterie urbaine.")


def _setup_logging() -> Path:
    """Configure le logger applicatif vers un fichier rotatif lisible
    par l'utilisateur final.

    Sans cela, `traceback.print_exc()` part sur stdout — invisible
    quand l'app est lancée par double-clic Windows ou via le `.desktop`
    Linux. Avec ce logging, on peut demander à un utilisateur "envoie-
    moi le contenu de ~/.penetrometre/penetrometre.log" en cas de
    bug à distance.

    Renvoie le chemin du fichier de log (utilisable pour journaliser
    son emplacement au démarrage).
    """
    log_dir = Path.home() / ".penetrometre"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "penetrometre.log"

    logger = logging.getLogger("penetrometre")
    # Idempotence : ne pas doubler les handlers si _setup_logging est
    # rappelé (cas test, ou rechargement à chaud).
    if logger.handlers:
        return log_path
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        log_path, maxBytes=512_000, backupCount=2,
        encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)
    # On ne propage pas vers le root logger : pas de duplication si une
    # autre lib configure son propre handler.
    logger.propagate = False
    return log_path


def main():
    log_path = _setup_logging()
    log = logging.getLogger("penetrometre")
    log.info("Démarrage Pénétromètre v%s", __version__)
    try:
        App().mainloop()
    except Exception:
        log.exception("Crash non rattrapé dans la boucle principale")
        raise
    finally:
        log.info("Arrêt Pénétromètre — log: %s", log_path)


if __name__ == "__main__":
    main()
