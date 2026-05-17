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

import logging
import tkinter as tk
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Optional, Tuple

# Actions d'export (PNG / PDF / CSV / XLSX / HTML) : adaptateur Tk qui
# glue les fonctions pures de `pil_render.py` / `export.py` aux
# filedialogs et au logger applicatif.
import app_exports
from app_menu import build_menu
from app_style import apply_ttk_styles
from pane_contreforts import ContrefortsPane
from pane_degradations import DegradationsPane
from pane_identification import IdentificationPane
from pane_sondages import SondagesPane

# Helpers géométriques + barème (fonctions pures testées isolément).
from bareme import classer_prbs
from geometry import (
    DIRECTION_LABELS,
    GRADES,
    cavity_polygon,
    contrefort_zone_outline,
    contrefort_zones,
    degradation_externe_outline,
    polar_idx_to_xy,
)

# Modèle de données : dataclasses sérialisables (Sondage, Arbre, …) avec
# leur logique métier (extrapolation, PRBS, classification). Voir
# model.py pour le détail. Sans dépendance Tk/PIL : couvert par les tests.
# Les classes Sondage/DegradationExterne/Contrefort sont instanciées
# dans leurs panes respectifs (pane_sondages, pane_degradations,
# pane_contreforts) au moment de la création depuis l'UI.
from model import Arbre, Chantier

# Palette partagée Tk ↔ PIL : couleurs UI et mapping classe → hex.
# Les couleurs purement ttk-thème (Side, Accent_soft, Wood_dark) sont
# importées par `app_style.py`, pas ici.
from palette import (
    COLOR_ACCENT,
    COLOR_BARK,
    COLOR_BARK_LIGHT,
    COLOR_BG,
    COLOR_CERNE,
    COLOR_INK,
    COLOR_MUTED,
    COLOR_PANEL,
    COLOR_ROT,
    COLOR_SOND,
    COLOR_WOOD,
    COULEUR_CLASSE,
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
    # Helpers de dessin — un par couche logique
    # ------------------------------------------------------------------

    def _draw_placeholder(self) -> None:
        w = max(self.winfo_width(), 1)
        h = max(self.winfo_height(), 1)
        self.create_text(w/2, h/2,
                         text="Renseignez le rayon du tronc\npour afficher la section",
                         font=("Georgia", 14, "italic"),
                         fill=COLOR_MUTED, justify="center")

    def _draw_bois_sain(self, cx, cy, R, scale) -> None:
        radius_px = R * scale
        self.create_oval(cx - radius_px, cy - radius_px,
                         cx + radius_px, cy + radius_px,
                         fill=COLOR_WOOD, outline="", width=0)

    def _draw_cernes(self, cx, cy, R, scale) -> None:
        # Cernes par-dessus le bois sain, en brun foncé fin. Effacés
        # naturellement dans la zone dégradée par la cavité dessinée
        # juste après.
        radius_px = R * scale
        for k in range(1, 9):
            rr = radius_px * k / 9
            self.create_oval(cx - rr, cy - rr, cx + rr, cy + rr,
                             outline=COLOR_CERNE, width=1)

    def _draw_cavite(self, A, cx, cy, scale) -> None:
        # bois_altéré = épaisseur d'altération mesurée au résistographe,
        # qui correspond à une zone centrale de rayon égal à cette
        # épaisseur. La couronne externe de bois sain fait (R - altéré).
        alt = A.compute_alteration_par_grade()
        if not any(a > 0 for a in alt):
            return
        smooth = cavity_polygon(alt, cx, cy, scale, samples_per_segment=28)
        flat = [c for p in smooth for c in p]
        # Pas de contour : couleur uniforme avec les dégradations
        # externes, permettant la fusion visuelle écorce↔cavité quand
        # elles se rejoignent.
        self.create_polygon(*flat, fill=COLOR_ROT,
                            outline="", smooth=False)

    def _draw_ecorce(self, cx, cy, R, ep, scale) -> None:
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

    def _draw_ticks(self, cx, cy, R_ext, scale) -> None:
        # Graduations des 16 grades, tirets à l'extérieur de l'écorce.
        for i, g in enumerate(GRADES):
            x1, y1 = polar_idx_to_xy(cx, cy, scale, R_ext, i)
            tick_len_cm = 8 / scale
            x2, y2 = polar_idx_to_xy(cx, cy, scale,
                                     R_ext + tick_len_cm, i)
            major = (g % 50 == 0)
            self.create_line(x1, y1, x2, y2,
                             fill=COLOR_BARK if major else COLOR_BARK_LIGHT,
                             width=2 if major else 1)

    def _draw_cardinales(self, cx, cy, R_ext, scale) -> None:
        # Lettres cardinales à 25 px hors écorce, halo blanc.
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

    def _draw_sondages(self, A, cx, cy, R, scale) -> None:
        # Flèches + pastilles à l'INTÉRIEUR du tronc, juste sous l'écorce.
        # Pastille classée sur la PRBS AJUSTÉE (PRBS - dégradation
        # externe couvrant le grade) pour être cohérente avec le tableau
        # Diagnostic et la fiche PDF.
        port = A.port_arbre
        meche = A.meche_cm if A.meche_cm > 0 else float("inf")
        deg_ext_par_grade = A.degradation_externe_par_grade()
        for s in A.sondages:
            if s.grade not in GRADES:
                continue
            i = GRADES.index(s.grade)
            penetration = min(s.bois_sain_cm + s.bois_altere_cm, meche)
            penetration = max(0.0, min(penetration, R))
            end_radius = R - penetration
            # Flèche depuis 13 px sous l'écorce
            x_ext, y_ext = polar_idx_to_xy(cx, cy, scale,
                                           R - 13/scale, i)
            x_end, y_end = polar_idx_to_xy(cx, cy, scale, end_radius, i)
            self.create_line(x_ext, y_ext, x_end, y_end,
                             fill=COLOR_SOND, width=2,
                             arrow=tk.LAST, arrowshape=(10, 12, 4))

            prbs_adj = max(0.0, s.prbs_cm - deg_ext_par_grade[i])
            ratio_adj = prbs_adj / R if R > 0 else 0.0
            col_class = COULEUR_CLASSE[classer_prbs(ratio_adj, port)]
            px, py = polar_idx_to_xy(cx, cy, scale, R - 13/scale, i)
            r_bul = 11
            self.create_oval(px - r_bul - 2, py - r_bul - 2,
                             px + r_bul + 2, py + r_bul + 2,
                             fill="white", outline="")
            self.create_oval(px - r_bul, py - r_bul,
                             px + r_bul, py + r_bul,
                             fill=col_class, outline="white", width=2)
            self.create_text(px, py, text=str(s.numero),
                             font=("Helvetica", 10, "bold"), fill="white")

    def _draw_regle(self, cx, cy, R, ep, R_ext, scale) -> None:
        # RÈGLE GRADUÉE sous la section. Portion bois [-R, +R] en trait
        # noir fin ; portions écorce ([-R_ext, -R] et [+R, +R_ext]) en
        # barres brun foncé épaisses — l'œil mesure bois et écorce sur
        # la même règle.
        h = max(self.winfo_height(), 1)
        radius_ext_px = R_ext * scale
        step = 5 if R >= 15 else (2 if R >= 6 else 1)
        # Position verticale : juste sous l'écorce + lettres cardinales
        # + petit padding ; on remonte si on dépasse en bas du canvas.
        y_axis = min(cy + radius_ext_px + 75, h - 30)
        wood_half_px = R * scale
        ext_half_px = R_ext * scale
        x_lw, x_rw = cx - wood_half_px, cx + wood_half_px
        x_le, x_re = cx - ext_half_px, cx + ext_half_px

        # Bandeau blanc de fond
        self.create_rectangle(x_le - 8, y_axis - 14,
                              x_re + 35, y_axis + 24,
                              fill="white", outline="")
        # Trait bois (noir fin) au centre
        self.create_line(x_lw, y_axis, x_rw, y_axis,
                         fill=COLOR_INK, width=2)
        # Barres écorce aux extrémités
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
        # Graduations intermédiaires (bois) tous les `step` cm, exclues
        # à la valeur R (déjà marquée par le tiret de transition).
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
        # Étiquette à R+ep — décalée d'une ligne si écart < 25 px.
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

    def _draw_titre(self, A, R) -> None:
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

        apply_ttk_styles(self)
        build_menu(self)
        self._build_layout()
        self._refresh_tree_arbres()
        self._load_arbre_to_ui()

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

        # Bloc droit : logo Silvavenir (si disponible).
        # PIL est requis pour les exports PNG/PDF — s'il est absent au
        # démarrage, l'utilisateur l'apprend ici (log + fallback texte)
        # plutôt qu'au moment d'un clic « Exporter PDF » qui échouerait
        # silencieusement. Le diagnostic est distingué de l'échec de
        # chargement du logo (fichier manquant, image corrompue), qui
        # est bénin.
        self._logo_image = None
        logo_loaded = False
        try:
            from PIL import Image as PILImage
            from PIL import ImageTk
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
                ttk.Label(header, image=self._logo_image
                          ).pack(side="right")
                logo_loaded = True
            else:
                log.warning("Logo Silvavenir introuvable à %s",
                            logo_path)
        except ImportError as exc:
            log.warning(
                "Pillow indisponible (%s) — les exports PNG et PDF "
                "ne pourront pas être générés. Installer Pillow via "
                "`pip install -r requirements.txt`.", exc)
        except Exception:
            log.exception("Échec du chargement du logo")
        if not logo_loaded:
            # Fallback texte (Pillow absent, logo manquant ou
            # image illisible)
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

        # Onglet Identification — extrait dans son propre pane (cf.
        # pane_identification.py). Le pane possède ses 10 StringVars,
        # la règle de cohérence Ø ↔ Rayon et la synchro UI ↔ modèle.
        self.pane_id = IdentificationPane(nb, host=self)
        nb.add(self.pane_id, text="Identification")

        # Onglet Sondages — extrait dans son propre pane (cf.
        # pane_sondages.py).
        self.pane_s = SondagesPane(nb, host=self)
        nb.add(self.pane_s, text="Sondages")

        # Onglet Dégradations externes — extrait dans son propre pane
        # (cf. pane_degradations.py).
        self.pane_de = DegradationsPane(nb, host=self)
        nb.add(self.pane_de, text="Dégrad. externes")

        # Onglet Contreforts — extrait dans son propre pane (cf.
        # pane_contreforts.py) : le pane possède sa table, ses boutons,
        # son refresh et ses actions add/edit/del.
        self.pane_cf = ContrefortsPane(nb, host=self)
        nb.add(self.pane_cf, text="Contreforts")

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

        # Molette de souris (Windows / Linux). On n'active les bindings
        # globaux QUE quand le pointeur survole le canvas Diagnostic —
        # sinon la molette détourne le scroll des autres onglets
        # (tables Sondages, Dégradations, Contreforts) qui ont leur
        # propre scrollbar.
        def _on_mousewheel(event):
            diag_canvas.yview_scroll(int(-event.delta / 120), "units")
        def _on_mousewheel_linux(event):
            diag_canvas.yview_scroll(-1 if event.num == 4 else 1, "units")
        def _bind_wheel(_e):
            diag_canvas.bind_all("<MouseWheel>", _on_mousewheel)
            diag_canvas.bind_all("<Button-4>", _on_mousewheel_linux)
            diag_canvas.bind_all("<Button-5>", _on_mousewheel_linux)
        def _unbind_wheel(_e):
            diag_canvas.unbind_all("<MouseWheel>")
            diag_canvas.unbind_all("<Button-4>")
            diag_canvas.unbind_all("<Button-5>")
        diag_canvas.bind("<Enter>", _bind_wheel)
        diag_canvas.bind("<Leave>", _unbind_wheel)

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

    @contextmanager
    def _suspend_sync_block(self):
        """Suspend la synchro UI → modèle pendant un bloc d'écriture
        dans les StringVar. Garantit la remise à l'état précédent même
        si une exception survient à l'intérieur (un set/reset manuel
        laissait l'UI gelée silencieusement en cas d'erreur)."""
        prev = self._suspend_sync
        self._suspend_sync = True
        try:
            yield
        finally:
            self._suspend_sync = prev

    def _sync_chantier_meta(self) -> None:
        if self._suspend_sync:
            return
        self.chantier.nom = self.var_ch_nom.get()
        self.chantier.adresse = self.var_ch_adr.get()
        self.chantier.operateur = self.var_ch_ope.get()
        self.chantier.date_releve = self.var_ch_date.get()

    def on_identification_changed(self, *, rayon_adjusted: bool) -> None:
        """Callback appelé par `IdentificationPane` quand l'utilisateur
        modifie un champ. Si le rayon a été ajusté, les sondages et
        dégradations ont vu leur bois altéré / profondeur recalculés
        par `set_rayon` : on rafraîchit les trois tables. Sinon on
        redessine seulement et on met à jour la ligne de l'arbre dans
        la liste de gauche (n°, essence).
        """
        if rayon_adjusted:
            self._refresh_sondages_table()
            self._refresh_degradations_table()
            self._refresh_contreforts_table()
        self._debounced_redraw()
        a = self._current_arbre()
        if not a:
            return
        sel = self.tree_arbres.selection()
        if sel:
            label = f"n° {a.numero_arbre}" if a.numero_arbre else "(sans n°)"
            self.tree_arbres.item(sel[0], text=label,
                                  values=(a.essence,))

    def _load_arbre_to_ui(self) -> None:
        """Recharge l'UI complète depuis l'arbre courant : identification
        + tables Sondages/Dégradations/Contreforts + redraw du dessin."""
        self.pane_id.load_from_arbre()
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
        # Pane recharge ses 10 vars depuis l'arbre (suspend interne) —
        # plus simple que de toucher une var précise sans déclencher la
        # trace.
        self.pane_id.load_from_arbre()
        self._refresh_tree_arbres()

    # --- Sondages ---------------------------------------------------
    # Le refresh et les actions vivent dans SondagesPane
    # (pane_sondages.py). Thin wrapper pour les sites qui rafraîchissent
    # en cascade.
    def _refresh_sondages_table(self) -> None:
        if hasattr(self, "pane_s"):
            self.pane_s.refresh()

    # ---- Dégradations externes -------------------------------------
    # Le refresh et les actions vivent dans DegradationsPane (cf.
    # pane_degradations.py). Thin wrapper pour les sites qui
    # rafraîchissent en cascade.
    def _refresh_degradations_table(self) -> None:
        if hasattr(self, "pane_de"):
            self.pane_de.refresh()

    # --- Contreforts ---
    # Le refresh et les actions vivent maintenant dans ContrefortsPane
    # (cf. pane_contreforts.py). `_refresh_contreforts_table` reste
    # comme thin wrapper pour les sites qui rafraîchissent en cascade
    # (changement de rayon, chargement d'arbre).
    def _refresh_contreforts_table(self) -> None:
        if hasattr(self, "pane_cf"):
            self.pane_cf.refresh()

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
        if not a:
            self.lbl_diag.configure(
                text="Renseignez le rayon du tronc et ajoutez des "
                     "sondages pour obtenir un résumé.")
            return
        self.lbl_diag.configure(
            text="\n".join(a.diagnostic_summary_lines()))

    # --- Fichier ----------------------------------------------------

    def action_new(self) -> None:
        if not messagebox.askyesno("Nouvelle mission",
                                   "Perdre les données non enregistrées ?"):
            return
        self.chantier = Chantier()
        self.chantier.arbres.append(Arbre(numero_arbre="1"))
        self.current_idx = 0
        self.current_file = None
        with self._suspend_sync_block():
            self.var_ch_nom.set(self.chantier.nom)
            self.var_ch_adr.set("")
            self.var_ch_ope.set("")
            self.var_ch_date.set(self.chantier.date_releve)
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
            self.chantier = Chantier.load_from(p)
            if not self.chantier.arbres:
                self.chantier.arbres.append(Arbre())
            self.current_idx = 0
            self.current_file = Path(p)
            with self._suspend_sync_block():
                self.var_ch_nom.set(self.chantier.nom)
                self.var_ch_adr.set(self.chantier.adresse)
                self.var_ch_ope.set(self.chantier.operateur)
                self.var_ch_date.set(self.chantier.date_releve)
            self._refresh_tree_arbres()
            self._load_arbre_to_ui()
        except Exception as e:
            log.exception("Échec ouverture mission")
            messagebox.showerror("Erreur d'ouverture", str(e))

    def action_save(self) -> None:
        if not self.current_file:
            return self.action_save_as()
        try:
            self.chantier.save_to(self.current_file)
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
        app_exports.export_png(self, self._current_arbre(),
                                self.section.show_sondages)

    def action_export_pdf_arbre(self) -> None:
        app_exports.export_pdf_arbre(self, self._current_arbre(),
                                      self.chantier)

    def action_export_csv(self) -> None:
        app_exports.export_csv_mission(self, self.chantier)

    def action_export_prbs_xlsx(self) -> None:
        app_exports.export_xlsx_arbre(self, self._current_arbre(),
                                       self.chantier)

    def action_export_prbs_html(self) -> None:
        app_exports.export_html_arbre(self, self._current_arbre(),
                                       self.chantier)

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
