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
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


__version__ = "3.3.0"


# ---------------------------------------------------------------------------
# Constantes métier
# ---------------------------------------------------------------------------

GRADES: List[int] = [i * 25 for i in range(16)]  # 0, 25, 50, ..., 375

DIRECTION_LABELS = {
    0: "N",   25: "",    50: "NE",  75: "",
    100: "E", 125: "",  150: "SE", 175: "",
    200: "S", 225: "",  250: "SO", 275: "",
    300: "O", 325: "",  350: "NO", 375: "",
}

# Palette — vive, naturaliste, pensée pour l'expertise arboricole
COLOR_BG         = "#F7F3EA"
COLOR_PANEL      = "#FFFFFF"
COLOR_INK        = "#1A2E22"
COLOR_MUTED      = "#6E7B73"

COLOR_ACCENT     = "#2D7A3E"
COLOR_ACCENT_SOFT= "#C9E4CE"

COLOR_BARK       = "#5C3A1E"   # brun écorce (intact)
COLOR_BARK_LIGHT = "#8B6244"
COLOR_WOOD       = "#F0DC9E"   # beige doré (bois ancien jaunissant)
COLOR_WOOD_DARK  = "#C9B486"   # ancien usage : conservé pour compat.
COLOR_CERNE      = "#2A1F10"   # cernes : brun très foncé presque noir
# COLOR_ROT distinct de COLOR_BARK : la dégradation (cavité interne et
# dégradation externe) doit se voir comme un brun NETTEMENT plus foncé
# que l'écorce intacte, pour que la « plaie » soit lisible quand elle
# traverse la couche d'écorce.
COLOR_ROT        = "#3E2510"   # brun très foncé : bois dégradé
COLOR_ROT_DARK   = "#3E2510"   # alias (legacy)
COLOR_SOND       = "#1F3A8A"


# ---------------------------------------------------------------------------
# Interpolation spline (Catmull-Rom fermée)
# ---------------------------------------------------------------------------

def catmull_rom_closed(points: List[Tuple[float, float]],
                       samples_per_segment: int = 24) -> List[Tuple[float, float]]:
    n = len(points)
    if n < 3:
        return list(points)
    out: List[Tuple[float, float]] = []
    for i in range(n):
        p0 = points[(i - 1) % n]
        p1 = points[i]
        p2 = points[(i + 1) % n]
        p3 = points[(i + 2) % n]
        for k in range(samples_per_segment):
            t = k / samples_per_segment
            t2 = t * t
            t3 = t2 * t
            x = 0.5 * ((2 * p1[0]) +
                       (-p0[0] + p2[0]) * t +
                       (2*p0[0] - 5*p1[0] + 4*p2[0] - p3[0]) * t2 +
                       (-p0[0] + 3*p1[0] - 3*p2[0] + p3[0]) * t3)
            y = 0.5 * ((2 * p1[1]) +
                       (-p0[1] + p2[1]) * t +
                       (2*p0[1] - 5*p1[1] + 4*p2[1] - p3[1]) * t2 +
                       (-p0[1] + 3*p1[1] - 3*p2[1] + p3[1]) * t3)
            out.append((x, y))
    out.append(out[0])
    return out


# ---------------------------------------------------------------------------
# Modèle de données
# ---------------------------------------------------------------------------

@dataclass
class Sondage:
    numero: int = 1
    grade: int = 0
    bois_sain_cm: float = 0.0
    bois_altere_cm: float = 0.0
    compartimentation: str = "-"
    commentaire: str = ""

    @property
    def prbs_cm(self) -> float:
        """Paroi Résiduelle de Bois Sain (alias métier de bois_sain_cm).

        Terme utilisé dans la méthode VTA de Claus Mattheck :
        épaisseur de bois sain mesurée par le résistographe entre
        l'écorce et la zone altérée.
        """
        return self.bois_sain_cm

    def ratio_tR(self, rayon_cm: float) -> float:
        """Ratio t/R (Mattheck) : PRBS / Rayon, en valeur décimale 0-1."""
        if rayon_cm <= 0:
            return 0.0
        return min(1.0, self.prbs_cm / rayon_cm)


@dataclass
class DegradationExterne:
    """Dégradation visible sur l'écorce : arc continu défini par un grade
    de début et un grade de fin (sens horaire), avec une profondeur radiale
    en cm depuis l'écorce vers l'intérieur.

    Exemple : "dégradation entre 50 gr et 100 gr, profondeur 3 cm" =
    arc qui couvre les directions NE→E, sur 3 cm de profondeur.
    """
    numero: int = 1
    grade_debut: int = 0       # 0 à 375 gr (inclus)
    grade_fin: int = 25        # 0 à 375 gr (inclus), sens horaire
    profondeur_cm: float = 1.0 # épaisseur radiale depuis l'écorce
    commentaire: str = ""

    def largeur_grades(self) -> int:
        """Étendue angulaire en grades (sens horaire), de 25 à 400."""
        d = (self.grade_fin - self.grade_debut) % 400
        # Si on a saisi début == fin, on considère que c'est un secteur
        # d'au moins 25 gr (la résolution minimale du dessin).
        return d if d > 0 else 25

    def largeur_cm(self, rayon_cm: float) -> float:
        """Largeur de l'arc en cm sur le périmètre (utile pour la saisie
        en cm). 1 grade = 360°/400 = 0.9° donc largeur = R × angle_rad."""
        if rayon_cm <= 0:
            return 0.0
        angle_rad = self.largeur_grades() * math.pi / 200.0
        return rayon_cm * angle_rad

    def couvre_grade(self, grade: int) -> bool:
        """Vrai si la dégradation couvre la direction donnée."""
        if grade not in GRADES:
            return False
        # On parcourt l'arc du début à la fin dans le sens horaire
        start = self.grade_debut
        n = self.largeur_grades() // 25 + 1
        for _ in range(n):
            if start == grade:
                return True
            start = (start + 25) % 400
            if start == self.grade_fin:
                # on inclut la borne fin
                if start == grade:
                    return True
                break
        return False


@dataclass
class Contrefort:
    """Contrefort (empattement) : excroissance radiale à la base du tronc,
    centrée sur une orientation donnée (grade), avec une largeur angulaire
    et une longueur (saillie radiale vers l'extérieur depuis l'écorce).

    Élément purement descriptif/visuel : n'impacte ni la PRBS, ni le
    ratio t/R, ni la classification. Le sondage étant fait à
    `hauteur_sondage_cm` plus haut, le contrefort n'intervient pas dans
    le diagnostic.

    Exemple : "contrefort orienté à 100 gr (E), largeur 75 gr,
    longueur 12 cm" = bosse de 12 cm de long centrée à l'Est, large
    de 75 grades sur le pourtour.
    """
    numero: int = 1
    grade_centre: int = 0      # orientation (0 à 375 gr, par pas de 25)
    largeur_grades: int = 50   # étendue angulaire (multiple de 25)
    longueur_cm: float = 10.0  # saillie radiale vers l'extérieur (cm)
    commentaire: str = ""

    def grade_debut(self) -> int:
        """Grade de début de l'arc couvert par le contrefort (sens horaire)."""
        demi = self.largeur_grades // 2
        return (self.grade_centre - demi) % 400

    def grade_fin(self) -> int:
        """Grade de fin de l'arc couvert (sens horaire)."""
        return (self.grade_debut() + self.largeur_grades) % 400

    def largeur_cm(self, rayon_cm: float) -> float:
        """Largeur de la base du contrefort en cm sur le périmètre."""
        if rayon_cm <= 0:
            return 0.0
        angle_rad = self.largeur_grades * math.pi / 200.0
        return rayon_cm * angle_rad


def bell_max_at_grade(grade: float,
                      contreforts: List["Contrefort"]) -> float:
    """Hauteur de cloche maximale (en cm) à l'angle `grade` donné, en
    prenant le maximum sur tous les contreforts qui couvrent ce grade.

    Renvoie 0 si aucun contrefort ne projette de cloche à cet angle.

    Sert à fusionner les contreforts adjacents : à la jonction de deux
    cloches, on prend celle qui culmine le plus haut, ce qui évite
    l'encoche en V qui apparaissait quand chaque contrefort était
    dessiné isolément.
    """
    h = 0.0
    for c in contreforts:
        if c.longueur_cm <= 0 or c.largeur_grades <= 0:
            continue
        demi = c.largeur_grades / 2.0
        # distance angulaire signée dans [-200, 200)
        diff = ((grade - c.grade_centre + 200) % 400) - 200
        if -demi <= diff <= demi:
            profil = math.cos(diff / demi * math.pi / 2.0) ** 2
            h = max(h, c.longueur_cm * profil)
    return h


def contrefort_zones(contreforts: List["Contrefort"]
                     ) -> List[Tuple[float, float]]:
    """Renvoie la liste des zones angulaires `(a, b)` (en grades) sur
    lesquelles au moins un contrefort projette une cloche.

    Les contreforts qui se chevauchent ou se touchent sont fusionnés en
    une seule zone (un seul polygone à dessiner). Les zones peuvent
    avoir `a < 0` lorsqu'elles enjambent le grade 0 — l'appelant fait
    `g % 400` au moment d'échantillonner.
    """
    cs = [c for c in contreforts
          if c.longueur_cm > 0 and c.largeur_grades > 0]
    if not cs:
        return []
    raw = []
    for c in cs:
        demi = c.largeur_grades / 2.0
        a = (c.grade_centre - demi) % 400
        b = a + c.largeur_grades  # peut dépasser 400 (wrap)
        raw.append((a, b))
    raw.sort()
    merged = [list(raw[0])]
    for a, b in raw[1:]:
        if a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    # Wrap : la dernière zone enjambe-t-elle 400 et chevauche-t-elle
    # la première ? Si oui, on les fusionne.
    while len(merged) >= 2 and merged[-1][1] - 400 >= merged[0][0]:
        last = merged.pop()
        first = merged[0]
        first[0] = last[0] - 400
        first[1] = max(first[1], last[1] - 400)
    if len(merged) == 1 and merged[0][1] - merged[0][0] >= 400:
        merged = [[0.0, 400.0]]
    return [tuple(z) for z in merged]


PORTS_ARBRE = ["libre", "semi-libre", "architecturé", "traumatique"]

# Groupes de barèmes PRBS (Silvavenir) :
#   - libre + semi-libre : Vert > 30%, Orange 15-30%, Rouge < 15%
#   - architecturé + traumatique : Vert > 20%, Orange 10-20%, Rouge < 10%
PORTS_GROUPE_LIBRE = ("libre", "semi-libre")
PORTS_GROUPE_STRICT = ("architecturé", "traumatique")


def classer_prbs(ratio_tR: float, port_arbre: str) -> tuple[str, str]:
    """Classe un sondage selon son ratio t/R et le port de l'arbre.

    Seuils Silvavenir :
    - libre / semi-libre :        Vert > 30%, Orange 15-30%, Rouge < 15%
    - architecturé / traumatique :Vert > 20%, Orange 10-20%, Rouge < 10%

    Retourne (label, couleur_hex).
    """
    p = port_arbre.lower().strip()
    seuils = (0.20, 0.10) if p in PORTS_GROUPE_STRICT else (0.30, 0.15)
    if ratio_tR > seuils[0]:
        return "Vert", "#2D7A3E"
    elif ratio_tR >= seuils[1]:
        return "Orange", "#E67E22"
    else:
        return "Rouge", "#C0392B"


@dataclass
class Arbre:
    numero_arbre: str = "1"
    essence: str = ""
    hauteur_sondage_cm: float = 0.0
    diametre_sous_ecorce_cm: float = 0.0
    hauteur_arbre_m: float = 0.0
    port_arbre: str = "libre"
    rayon_tronc_cm: float = 20.0
    meche_cm: float = 40.0   # longueur de la mèche du pénétromètre (cm)
    epaisseur_ecorce_cm: float = 0.0  # épaisseur radiale de l'écorce, ajoutée
    # vers l'extérieur du tronc — purement visuel, n'intervient pas dans la
    # PRBS ni le diagnostic. 0 = pas d'épaisseur (trait fin classique).
    alteration_par_grade: List[float] = field(
        default_factory=lambda: [0.0] * 16)
    sondages: List[Sondage] = field(default_factory=list)
    degradations_externes: List[DegradationExterne] = field(
        default_factory=list)
    contreforts: List["Contrefort"] = field(default_factory=list)
    commentaire: str = ""

    @property
    def display_name(self) -> str:
        """Nom affiché : 'Arbre n°X' ou 'Arbre n°X — Essence'."""
        base = f"Arbre n°{self.numero_arbre}" if self.numero_arbre else "Arbre"
        if self.essence:
            return f"{base} — {self.essence}"
        return base

    def recompute_alteration_from_sondages(self) -> None:
        """Recalcule les 16 épaisseurs d'altération :

        - directions sondées : valeur la plus défavorable des sondages,
        - directions non sondées : moyenne pondérée entre les 2 sondages
          voisins (sens horaire / anti-horaire) — uniquement s'il y a
          au moins 2 sondages. Sinon 0 (bois sain).
        """
        # Étape 1 : valeurs aux directions sondées
        measured: dict[int, float] = {}
        for s in self.sondages:
            if s.grade not in GRADES:
                continue
            idx = GRADES.index(s.grade)
            measured[idx] = max(measured.get(idx, 0.0), s.bois_altere_cm)

        new_vals = [0.0] * 16
        if len(measured) < 2:
            # Pas assez de points pour extrapoler : on garde les mesures
            # là où elles existent, et 0 ailleurs.
            for idx, v in measured.items():
                new_vals[idx] = v
            self.alteration_par_grade = new_vals
            return

        # Étape 2 : pour chaque grade, soit mesuré, soit extrapolé
        sorted_idx = sorted(measured.keys())
        for i in range(16):
            if i in measured:
                new_vals[i] = measured[i]
                continue
            # voisin horaire (j > i en circulaire) + anti-horaire (j < i)
            next_idx = None
            for j in sorted_idx:
                if j > i:
                    next_idx = j
                    break
            if next_idx is None:
                next_idx = sorted_idx[0]  # boucle
            prev_idx = None
            for j in reversed(sorted_idx):
                if j < i:
                    prev_idx = j
                    break
            if prev_idx is None:
                prev_idx = sorted_idx[-1]  # boucle

            # distances angulaires (en nombre de pas de 22,5°)
            d_next = (next_idx - i) % 16
            d_prev = (i - prev_idx) % 16
            total = d_next + d_prev
            if total == 0:
                new_vals[i] = measured[i]  # cas dégénéré impossible ici
            else:
                # Moyenne pondérée : plus le voisin est proche, plus il
                # pèse. 20 cm à 0° + 10 cm à 100° (4 crans) donnent
                # 15 cm à 50° (2 crans de part et d'autre).
                w_next = d_prev / total
                w_prev = d_next / total
                new_vals[i] = (measured[next_idx] * w_next
                               + measured[prev_idx] * w_prev)
        self.alteration_par_grade = new_vals

    def degradation_externe_par_grade(self) -> List[float]:
        """Pour chaque direction (16 grades), retourne la profondeur
        maximale de dégradation externe qui couvre cette direction.
        0 si aucune dégradation ne la couvre.
        """
        out = [0.0] * 16
        for deg in self.degradations_externes:
            for i, g in enumerate(GRADES):
                if deg.couvre_grade(g):
                    out[i] = max(out[i], deg.profondeur_cm)
        return out

    def prbs_par_grade(self) -> List[float]:
        """Pour chaque direction (16 grades), retourne la PRBS réelle :
        rayon - altération interne - dégradation externe.

        C'est l'épaisseur de bois sain effectivement disponible, qui
        intègre les deux types de dégradation.
        """
        R = self.rayon_tronc_cm
        if R <= 0:
            return [0.0] * 16
        self.recompute_alteration_from_sondages()
        alt_int = self.alteration_par_grade
        deg_ext = self.degradation_externe_par_grade()
        return [max(0.0, R - alt_int[i] - deg_ext[i]) for i in range(16)]

    def ratio_tR_par_grade(self) -> List[float]:
        """Pour chaque direction, ratio t/R = PRBS / Rayon (entre 0 et 1)."""
        R = self.rayon_tronc_cm
        if R <= 0:
            return [0.0] * 16
        return [p / R for p in self.prbs_par_grade()]

    def repartition_classes(self) -> dict:
        """Répartition des 16 directions par classe (Vert/Orange/Rouge),
        avec étendue angulaire en grades et en pourcentage du périmètre.

        Retourne un dict :
          {
            "Vert":   {"n": int, "grades": int, "pct": float},
            "Orange": {...},
            "Rouge":  {...},
            "tR_min": float,         # ratio t/R minimal sur les 16
            "tR_min_grade": int,     # grade où t/R est minimal
            "tR_min_dir": str,       # direction cardinale ou voisine
            "classe_globale": str,   # pire classe rencontrée
          }
        """
        ratios = self.ratio_tR_par_grade()
        result = {
            "Vert":   {"n": 0, "grades": 0, "pct": 0.0},
            "Orange": {"n": 0, "grades": 0, "pct": 0.0},
            "Rouge":  {"n": 0, "grades": 0, "pct": 0.0},
        }
        for i, r in enumerate(ratios):
            classe, _ = classer_prbs(r, self.port_arbre)
            result[classe]["n"] += 1
            result[classe]["grades"] += 25  # chaque secteur fait 25 gr
        # Pourcentage du périmètre (16 secteurs = 400 gr)
        for cls in ("Vert", "Orange", "Rouge"):
            result[cls]["pct"] = 100.0 * result[cls]["grades"] / 400.0

        # Direction critique (t/R minimal — info conservée)
        tR_min = min(ratios)
        i_crit = ratios.index(tR_min)
        grade_crit = GRADES[i_crit]
        dir_crit = DIRECTION_LABELS.get(grade_crit, "")
        if not dir_crit:
            for delta in (1, -1, 2, -2):
                g2 = GRADES[(i_crit + delta) % 16]
                lbl = DIRECTION_LABELS.get(g2)
                if lbl:
                    dir_crit = f"~{lbl}"
                    break
        result["tR_min"] = tR_min
        result["tR_min_grade"] = grade_crit
        result["tR_min_dir"] = dir_crit

        # Classe globale = barème Silvavenir appliqué au t/R MOYEN
        # sur les 16 directions du pourtour.
        #
        # Cette approche reflète l'état général de la section :
        # - une seule direction critique ne déclasse pas tout l'arbre,
        # - mais une dégradation répartie tire la moyenne vers le bas.
        #
        # On conserve aussi t/R minimal et la pire classe ponctuelle
        # comme indicateurs complémentaires d'alerte locale.
        tR_moyen = sum(ratios) / len(ratios) if ratios else 1.0
        result["tR_moyen"] = tR_moyen
        result["classe_globale"], _ = classer_prbs(tR_moyen,
                                                    self.port_arbre)
        # Pire classe ponctuelle (info compl√©mentaire)
        if result["Rouge"]["n"] > 0:
            result["classe_pire"] = "Rouge"
        elif result["Orange"]["n"] > 0:
            result["classe_pire"] = "Orange"
        else:
            result["classe_pire"] = "Vert"
        return result


@dataclass
class Chantier:
    nom: str = "Nouvelle mission"
    adresse: str = ""
    operateur: str = ""
    date_releve: str = field(
        default_factory=lambda: datetime.now().strftime("%d/%m/%Y"))
    arbres: List[Arbre] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"nom": self.nom, "adresse": self.adresse,
                "operateur": self.operateur, "date_releve": self.date_releve,
                "arbres": [asdict(a) for a in self.arbres]}

    @classmethod
    def from_dict(cls, d: dict) -> "Chantier":
        # Mapping de migration des anciens libellés de port (v3.1 → v3.2)
        port_legacy = {
            "Libre, semi-libre ou traumatique": "libre",
            "Architecturé ou traumatique": "architecturé",
        }
        arbres = []
        for a in d.get("arbres", []):
            sondages = [Sondage(**s) for s in a.pop("sondages", [])]
            degs = [DegradationExterne(**dg)
                    for dg in a.pop("degradations_externes", [])]
            # Contreforts : ajout v3.3 — anciens fichiers → liste vide
            contreforts = [Contrefort(**c)
                           for c in a.pop("contreforts", [])]
            # Migration du port si ancien format
            if "port_arbre" in a:
                a["port_arbre"] = port_legacy.get(a["port_arbre"],
                                                  a["port_arbre"])
            arb = Arbre(**a)
            arb.sondages = sondages
            arb.degradations_externes = degs
            arb.contreforts = contreforts
            arbres.append(arb)
        c = cls(nom=d.get("nom", ""), adresse=d.get("adresse", ""),
                operateur=d.get("operateur", ""),
                date_releve=d.get("date_releve", ""))
        c.arbres = arbres
        return c


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

    def _polar_idx_to_xy(self, cx, cy, scale, r_cm, idx):
        a = math.radians(idx * (360.0 / 16) - 90.0)
        return (cx + r_cm * scale * math.cos(a),
                cy + r_cm * scale * math.sin(a))

    def _polar_grade_to_xy(self, cx, cy, scale, r_cm, grade):
        """Convertit (rayon en cm, grade en gr 0-400) en (x,y) écran.
        0 gr = Nord (en haut), sens horaire."""
        a = math.radians(grade * 360.0 / 400.0 - 90.0)
        return (cx + r_cm * scale * math.cos(a),
                cy + r_cm * scale * math.sin(a))

    def _draw_contreforts_canvas(self, cx, cy, scale, R,
                                  contreforts,
                                  ep_cm: float = 0.0,
                                  R_inner: Optional[float] = None) -> None:
        """Dessine TOUS les contreforts en fusionnant les zones qui se
        chevauchent ou se touchent — une seule cloche unifiée par zone
        connectée, dont la hauteur en chaque grade est le maximum des
        hauteurs des contreforts qui la composent.

        Évite l'encoche en V qui apparaissait quand chaque contrefort
        était dessiné isolément.
        """
        if R <= 0 or not contreforts:
            return
        if R_inner is None:
            R_inner = R - 1.0 / scale
        for a, b in contrefort_zones(contreforts):
            span = b - a
            n_steps = max(32, int(span) + 1)
            wood_outer = []
            bark_outer = []
            for k in range(n_steps + 1):
                t = a + k * span / n_steps
                g = t % 400
                bell = bell_max_at_grade(g, contreforts)
                r_wood = R + bell
                wood_outer.append(
                    self._polar_grade_to_xy(cx, cy, scale, r_wood, g))
                if ep_cm > 0:
                    bark_outer.append(
                        self._polar_grade_to_xy(cx, cy, scale,
                                                r_wood + ep_cm, g))
            base = []
            for k in range(n_steps, -1, -1):
                t = a + k * span / n_steps
                g = t % 400
                base.append(
                    self._polar_grade_to_xy(cx, cy, scale, R_inner, g))
            if ep_cm > 0:
                # Couche d'écorce : bord interne à R (arc constant),
                # bord externe à r_wood + ep (suit la cloche).
                bark_inner = []
                for k in range(n_steps, -1, -1):
                    t = a + k * span / n_steps
                    g = t % 400
                    bark_inner.append(
                        self._polar_grade_to_xy(cx, cy, scale, R, g))
                flat_bark = [coord for p in (bark_outer + bark_inner)
                             for coord in p]
                self.create_polygon(*flat_bark, fill=COLOR_BARK,
                                    outline="")
            # Polygone bois : noyau de bois sous l'écorce.
            flat_wood = [coord for p in (wood_outer + base)
                         for coord in p]
            self.create_polygon(*flat_wood, fill=COLOR_WOOD, outline="")
            if ep_cm == 0:
                # Pas d'écorce : trait brun en surface
                flat_outer = [coord for p in wood_outer for coord in p]
                self.create_line(*flat_outer, fill=COLOR_BARK, width=3,
                                 smooth=True)

    def _draw_degradation_externe_canvas(self, cx, cy, scale, R, ep_cm,
                                          contreforts, deg) -> None:
        """Dessine une dégradation externe sur le canvas Tkinter.

        Le bord externe du polygone suit la SURFACE réelle de l'arbre :
        `R + ep + bell_max(grade)`. En zone sans contrefort, cela vaut
        `R + ep` ; en zone de contrefort, cela suit la cloche, ce qui
        permet à la dégradation de creuser le contrefort dans le secteur
        qu'elle couvre.

        Le bord interne est à `outer - profondeur`, donc la profondeur
        est mesurée depuis la surface externe — ce qui est cohérent avec
        la sémantique d'une plaie radiale.
        """
        if deg.profondeur_cm <= 0 or R <= 0:
            return
        # Échantillonnage fin pour suivre la cloche dans le secteur du
        # contrefort éventuel.
        n_steps = max(16, int(deg.largeur_grades()) + 1)
        outer_pts = []
        inner_pts = []
        for k in range(n_steps + 1):
            g = (deg.grade_debut
                 + k * deg.largeur_grades() / n_steps) % 400
            bell = bell_max_at_grade(g, contreforts)
            r_out = R + ep_cm + bell
            r_in = max(0.0, r_out - deg.profondeur_cm)
            outer_pts.append(
                self._polar_grade_to_xy(cx, cy, scale, r_out, g))
            inner_pts.append(
                self._polar_grade_to_xy(cx, cy, scale, r_in, g))
        points = outer_pts + list(reversed(inner_pts))
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
        alt = A.alteration_par_grade
        inner_cm = [max(0.0, alt[i]) for i in range(16)]
        if any(a > 0 for a in alt):
            pts_inner = [self._polar_idx_to_xy(cx, cy, scale, inner_cm[i], i)
                         for i in range(16)]
            smooth = catmull_rom_closed(pts_inner, 28)
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
            x1, y1 = self._polar_idx_to_xy(cx, cy, scale, R_ext, i)
            tick_len_cm = 8 / scale
            x2, y2 = self._polar_idx_to_xy(cx, cy, scale,
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
            lx, ly = self._polar_idx_to_xy(cx, cy, scale,
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
            for s in A.sondages:
                if s.grade not in GRADES:
                    continue
                i = GRADES.index(s.grade)
                penetration = min(s.bois_sain_cm + s.bois_altere_cm, meche)
                penetration = max(0.0, min(penetration, R))
                end_radius = R - penetration
                # Flèche : depuis 13 px sous l'écorce
                x_ext, y_ext = self._polar_idx_to_xy(cx, cy, scale,
                                                     R - 13/scale, i)
                x_end, y_end = self._polar_idx_to_xy(cx, cy, scale,
                                                     end_radius, i)
                self.create_line(x_ext, y_ext, x_end, y_end,
                                 fill=COLOR_SOND, width=2,
                                 arrow=tk.LAST, arrowshape=(10, 12, 4))

                # Pastille à 13 px sous l'écorce
                _, col_class = classer_prbs(s.ratio_tR(R), port)
                px, py = self._polar_idx_to_xy(cx, cy, scale,
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
        s.configure("Side.TFrame", background="#EAE5D8")
        s.configure("TLabel", background=COLOR_BG, foreground=COLOR_INK)
        s.configure("Panel.TLabel", background=COLOR_PANEL, foreground=COLOR_INK)
        s.configure("Side.TLabel", background="#EAE5D8", foreground=COLOR_INK)
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
        s.configure("Side.Treeview", background="#EAE5D8",
                    fieldbackground="#EAE5D8", rowheight=28)
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
        f.add_command(label="Exporter tableau CSV…",
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
            logo_path = Path(__file__).parent / "silvavenir_logo.jpg"
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
            ("Port de l'arbre",           self.var_port,
             ["libre", "semi-libre", "architecturé", "traumatique"]),
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
        ttk.Button(btn_exp, text="📊 CSV de la mission", style="Ghost.TButton",
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
        if a:
            a.recompute_alteration_from_sondages()
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
        if new:
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
        if self._dialog_sondage(s, creating=True):
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
        if self._dialog_sondage(s, creating=False):
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
        if self._dialog_degradation(deg, creating=True):
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
        if self._dialog_degradation(deg, creating=False):
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
        if self._dialog_contrefort(c, creating=True):
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
        if self._dialog_contrefort(c, creating=False):
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

    def _dialog_degradation(self, deg: DegradationExterne,
                             creating: bool) -> bool:
        """Boîte de dialogue d'édition d'une dégradation externe.

        Permet de saisir :
        - direction de début (combobox des grades)
        - direction de fin OU largeur en grades OU largeur en cm
          (lien automatique entre les trois)
        - profondeur radiale en cm
        - commentaire
        """
        dlg = tk.Toplevel(self)
        dlg.title(f"Dégradation externe n° {deg.numero}")
        dlg.configure(bg=COLOR_PANEL)
        dlg.transient(self)
        dlg.grab_set()
        dlg.resizable(False, False)

        a = self._current_arbre()
        R = a.rayon_tronc_cm if a else 0.0

        # Variables locales
        v_debut = tk.StringVar()
        v_fin = tk.StringVar()
        v_largeur_gr = tk.StringVar(value=str(deg.largeur_grades()))
        v_largeur_cm = tk.StringVar(value=f"{deg.largeur_cm(R):.1f}")
        v_prof = tk.StringVar(value=f"{deg.profondeur_cm:g}")
        v_com = tk.StringVar(value=deg.commentaire)
        result = {"ok": False}
        dlg._syncing = False

        # Liste des grades
        grade_choices = []
        for g in GRADES:
            lbl = DIRECTION_LABELS.get(g, "")
            grade_choices.append(f"{g} gr" + (f" — {lbl}" if lbl else ""))

        def find_grade_choice(grade_value):
            for c in grade_choices:
                if c.startswith(f"{grade_value} gr"):
                    return c
            return grade_choices[0]
        v_debut.set(find_grade_choice(deg.grade_debut))
        v_fin.set(find_grade_choice(deg.grade_fin))

        # --- Layout ---
        pad = {"padx": 10, "pady": 6}

        ttk.Label(dlg, text="Direction de début (grade)",
                  background=COLOR_PANEL).grid(row=0, column=0,
                                               sticky="w", **pad)
        ttk.Combobox(dlg, textvariable=v_debut, values=grade_choices,
                     state="readonly", width=24
                     ).grid(row=0, column=1, sticky="we", **pad)

        ttk.Label(dlg, text="Direction de fin (grade, sens horaire)",
                  background=COLOR_PANEL).grid(row=1, column=0,
                                               sticky="w", **pad)
        ttk.Combobox(dlg, textvariable=v_fin, values=grade_choices,
                     state="readonly", width=24
                     ).grid(row=1, column=1, sticky="we", **pad)

        ttk.Label(dlg, text="— ou —", background=COLOR_PANEL,
                  foreground=COLOR_MUTED, font=("Helvetica", 9, "italic")
                  ).grid(row=2, column=0, columnspan=2, pady=(2, 2))

        ttk.Label(dlg, text="Largeur en grades",
                  background=COLOR_PANEL).grid(row=3, column=0,
                                               sticky="w", **pad)
        ttk.Entry(dlg, textvariable=v_largeur_gr, width=12
                  ).grid(row=3, column=1, sticky="w", **pad)

        ttk.Label(dlg, text="Largeur en cm (sur l'écorce)",
                  background=COLOR_PANEL).grid(row=4, column=0,
                                               sticky="w", **pad)
        ttk.Entry(dlg, textvariable=v_largeur_cm, width=12
                  ).grid(row=4, column=1, sticky="w", **pad)

        ttk.Label(dlg, text="Profondeur (cm, depuis l'écorce)",
                  background=COLOR_PANEL).grid(row=5, column=0,
                                               sticky="w", **pad)
        ttk.Entry(dlg, textvariable=v_prof, width=12
                  ).grid(row=5, column=1, sticky="w", **pad)

        ttk.Label(dlg, text="Commentaire", background=COLOR_PANEL
                  ).grid(row=6, column=0, sticky="w", **pad)
        ttk.Entry(dlg, textvariable=v_com, width=28
                  ).grid(row=6, column=1, sticky="we", **pad)

        # --- Liens auto entre fin / largeur_gr / largeur_cm ---
        def parse_grade(s: str) -> int:
            return int(s.replace("°", " ").split(" ")[0].strip())

        def round_to_grade(v: int) -> int:
            """Arrondit à 25 gr près et ramène dans [0, 375]."""
            v = round(v / 25) * 25
            return v % 400

        def _on_fin(*_):
            if dlg._syncing:
                return
            try:
                d = parse_grade(v_debut.get())
                f = parse_grade(v_fin.get())
                largeur = (f - d) % 400
                if largeur == 0:
                    largeur = 25
                dlg._syncing = True
                v_largeur_gr.set(str(largeur))
                if R > 0:
                    v_largeur_cm.set(
                        f"{R * largeur * math.pi / 200:.1f}")
                dlg._syncing = False
            except (ValueError, IndexError):
                pass

        def _on_largeur_gr(*_):
            if dlg._syncing:
                return
            try:
                gr = round_to_grade(int(float(v_largeur_gr.get() or 25)))
                if gr == 0:
                    gr = 25
                d = parse_grade(v_debut.get())
                f = (d + gr) % 400
                dlg._syncing = True
                v_fin.set(find_grade_choice(f))
                if R > 0:
                    v_largeur_cm.set(
                        f"{R * gr * math.pi / 200:.1f}")
                dlg._syncing = False
            except (ValueError, IndexError):
                pass

        def _on_largeur_cm(*_):
            if dlg._syncing or R <= 0:
                return
            try:
                cm = float(v_largeur_cm.get() or 0)
                # cm = R × angle_rad → angle_gr = cm × 200 / (R × π)
                gr = round_to_grade(int(cm * 200 / (R * math.pi)))
                if gr == 0:
                    gr = 25
                d = parse_grade(v_debut.get())
                f = (d + gr) % 400
                dlg._syncing = True
                v_largeur_gr.set(str(gr))
                v_fin.set(find_grade_choice(f))
                dlg._syncing = False
            except (ValueError, IndexError, ZeroDivisionError):
                pass

        v_debut.trace_add("write", _on_fin)
        v_fin.trace_add("write", _on_fin)
        v_largeur_gr.trace_add("write", _on_largeur_gr)
        v_largeur_cm.trace_add("write", _on_largeur_cm)

        def ok():
            try:
                deg.grade_debut = round_to_grade(parse_grade(v_debut.get()))
                deg.grade_fin = round_to_grade(parse_grade(v_fin.get()))
                deg.profondeur_cm = max(0.0, float(v_prof.get() or 0))
                deg.commentaire = v_com.get()
                result["ok"] = True
                dlg.destroy()
            except (ValueError, IndexError) as e:
                messagebox.showerror("Erreur de saisie",
                                     f"Valeur invalide : {e}", parent=dlg)

        btns = ttk.Frame(dlg, style="Panel.TFrame")
        btns.grid(row=7, column=0, columnspan=2, pady=(10, 12))
        ttk.Button(btns, text="Annuler", style="Ghost.TButton",
                   command=dlg.destroy).pack(side="right", padx=6)
        ttk.Button(btns, text="Valider", style="Accent.TButton",
                   command=ok).pack(side="right")

        dlg.wait_window()
        return result["ok"]

    def _dialog_contrefort(self, c: "Contrefort",
                            creating: bool) -> bool:
        """Boîte de dialogue d'édition d'un contrefort.

        Saisie : orientation (combobox des grades), largeur en grades
        (multiple de 25), longueur radiale en cm, commentaire.
        Largeur cm sur le périmètre affichée à titre indicatif.
        """
        dlg = tk.Toplevel(self)
        dlg.title(f"Contrefort n° {c.numero}")
        dlg.configure(bg=COLOR_PANEL)
        dlg.transient(self)
        dlg.grab_set()
        dlg.resizable(False, False)

        a = self._current_arbre()
        R = a.rayon_tronc_cm if a else 0.0

        v_centre = tk.StringVar()
        v_largeur_gr = tk.StringVar(value=str(c.largeur_grades))
        v_largeur_cm = tk.StringVar(value=f"{c.largeur_cm(R):.1f}")
        v_long = tk.StringVar(value=f"{c.longueur_cm:g}")
        v_com = tk.StringVar(value=c.commentaire)
        result = {"ok": False}
        dlg._syncing = False

        grade_choices = []
        for g in GRADES:
            lbl = DIRECTION_LABELS.get(g, "")
            grade_choices.append(f"{g} gr" + (f" — {lbl}" if lbl else ""))

        def find_grade_choice(grade_value):
            for ch in grade_choices:
                if ch.startswith(f"{grade_value} gr"):
                    return ch
            return grade_choices[0]
        v_centre.set(find_grade_choice(c.grade_centre))

        pad = {"padx": 10, "pady": 6}

        ttk.Label(dlg, text="Orientation (grade central)",
                  background=COLOR_PANEL).grid(row=0, column=0,
                                               sticky="w", **pad)
        ttk.Combobox(dlg, textvariable=v_centre, values=grade_choices,
                     state="readonly", width=24
                     ).grid(row=0, column=1, sticky="we", **pad)

        ttk.Label(dlg, text="Largeur en grades (multiple de 25)",
                  background=COLOR_PANEL).grid(row=1, column=0,
                                               sticky="w", **pad)
        ttk.Entry(dlg, textvariable=v_largeur_gr, width=12
                  ).grid(row=1, column=1, sticky="w", **pad)

        ttk.Label(dlg, text="Largeur en cm (sur l'écorce)",
                  background=COLOR_PANEL).grid(row=2, column=0,
                                               sticky="w", **pad)
        ttk.Entry(dlg, textvariable=v_largeur_cm, width=12
                  ).grid(row=2, column=1, sticky="w", **pad)

        ttk.Label(dlg, text="Longueur radiale (cm, vers l'extérieur)",
                  background=COLOR_PANEL).grid(row=3, column=0,
                                               sticky="w", **pad)
        ttk.Entry(dlg, textvariable=v_long, width=12
                  ).grid(row=3, column=1, sticky="w", **pad)

        ttk.Label(dlg, text="Commentaire", background=COLOR_PANEL
                  ).grid(row=4, column=0, sticky="w", **pad)
        ttk.Entry(dlg, textvariable=v_com, width=28
                  ).grid(row=4, column=1, sticky="we", **pad)

        # Liens auto entre largeur_gr et largeur_cm
        def round_to_grade(v: int) -> int:
            v = round(v / 25) * 25
            return max(25, min(400, v))

        def _on_largeur_gr(*_):
            if dlg._syncing:
                return
            try:
                gr = round_to_grade(int(float(v_largeur_gr.get() or 25)))
                dlg._syncing = True
                if R > 0:
                    v_largeur_cm.set(f"{R * gr * math.pi / 200:.1f}")
                dlg._syncing = False
            except (ValueError, IndexError):
                pass

        def _on_largeur_cm(*_):
            if dlg._syncing or R <= 0:
                return
            try:
                cm = float(v_largeur_cm.get() or 0)
                gr = round_to_grade(int(cm * 200 / (R * math.pi)))
                dlg._syncing = True
                v_largeur_gr.set(str(gr))
                dlg._syncing = False
            except (ValueError, IndexError, ZeroDivisionError):
                pass

        v_largeur_gr.trace_add("write", _on_largeur_gr)
        v_largeur_cm.trace_add("write", _on_largeur_cm)

        def parse_grade(s: str) -> int:
            return int(s.replace("°", " ").split(" ")[0].strip())

        def ok():
            try:
                c.grade_centre = parse_grade(v_centre.get()) % 400
                c.largeur_grades = round_to_grade(
                    int(float(v_largeur_gr.get() or 25)))
                c.longueur_cm = max(0.0, float(v_long.get() or 0))
                c.commentaire = v_com.get()
                result["ok"] = True
                dlg.destroy()
            except (ValueError, IndexError) as e:
                messagebox.showerror("Erreur de saisie",
                                     f"Valeur invalide : {e}", parent=dlg)

        btns = ttk.Frame(dlg, style="Panel.TFrame")
        btns.grid(row=5, column=0, columnspan=2, pady=(10, 12))
        ttk.Button(btns, text="Annuler", style="Ghost.TButton",
                   command=dlg.destroy).pack(side="right", padx=6)
        ttk.Button(btns, text="Valider", style="Accent.TButton",
                   command=ok).pack(side="right")

        dlg.wait_window()
        return result["ok"]

    def _dialog_sondage(self, s: Sondage, creating: bool) -> bool:
        dlg = tk.Toplevel(self)
        dlg.title(f"Sondage n° {s.numero}")
        dlg.configure(bg=COLOR_PANEL)
        dlg.transient(self)
        dlg.grab_set()
        dlg.resizable(False, False)

        a = self._current_arbre()
        R = a.rayon_tronc_cm if a else 0.0

        v_grade = tk.StringVar()
        v_sain = tk.StringVar(value=f"{s.bois_sain_cm:g}")
        v_alt = tk.StringVar(value=f"{s.bois_altere_cm:g}")
        v_comp = tk.StringVar(value=s.compartimentation)
        v_com = tk.StringVar(value=s.commentaire)
        result = {"ok": False}
        # drapeau pour éviter la récursion quand on met à jour l'un
        # à partir de l'autre
        dlg._syncing = False

        grade_choices = []
        for g in GRADES:
            lbl = DIRECTION_LABELS.get(g, "")
            # Format : "100 gr — E"  (grade sans ° car unité = grade)
            grade_choices.append(f"{g} gr" + (f" — {lbl}" if lbl else ""))
        for choice in grade_choices:
            if choice.startswith(f"{s.grade} gr"):
                v_grade.set(choice)
                break
        else:
            v_grade.set(grade_choices[0])

        pad = {"padx": 10, "pady": 6}

        # Bandeau rappelant le rayon (référence pour le calcul auto)
        if R > 0:
            rappel = (f"Rayon du tronc de cet arbre : {R:g} cm\n"
                      f"Règle : Bois sain + Bois altéré = Rayon.\n"
                      f"Modifier l'un recalcule l'autre automatiquement.")
        else:
            rappel = ("⚠ Rayon du tronc non renseigné : le calcul auto "
                      "entre bois sain et bois altéré est désactivé.")
        ttk.Label(dlg, text=rappel, background=COLOR_PANEL,
                  foreground=COLOR_MUTED, font=("Helvetica", 9, "italic"),
                  wraplength=300, justify="left"
                  ).grid(row=0, column=0, columnspan=2, sticky="we",
                         padx=10, pady=(10, 4))

        ttk.Label(dlg, text="Direction (grade)", background=COLOR_PANEL
                  ).grid(row=1, column=0, sticky="w", **pad)
        ttk.Combobox(dlg, textvariable=v_grade, values=grade_choices,
                     state="readonly", width=26
                     ).grid(row=1, column=1, sticky="we", **pad)

        ttk.Label(dlg, text="Épaisseur bois sain (cm)",
                  background=COLOR_PANEL
                  ).grid(row=2, column=0, sticky="w", **pad)
        ent_sain = ttk.Entry(dlg, textvariable=v_sain, width=12)
        ent_sain.grid(row=2, column=1, sticky="w", **pad)

        ttk.Label(dlg, text="Épaisseur bois altéré (cm)",
                  background=COLOR_PANEL
                  ).grid(row=3, column=0, sticky="w", **pad)
        ent_alt = ttk.Entry(dlg, textvariable=v_alt, width=12)
        ent_alt.grid(row=3, column=1, sticky="w", **pad)

        # --- Lien automatique bois sain <-> bois altéré -----------------
        def _on_sain_changed(*_):
            if dlg._syncing or R <= 0:
                return
            try:
                v = float(v_sain.get() or 0)
            except ValueError:
                return
            v = max(0.0, min(v, R))
            dlg._syncing = True
            v_alt.set(f"{R - v:g}")
            dlg._syncing = False

        def _on_alt_changed(*_):
            if dlg._syncing or R <= 0:
                return
            try:
                v = float(v_alt.get() or 0)
            except ValueError:
                return
            v = max(0.0, min(v, R))
            dlg._syncing = True
            v_sain.set(f"{R - v:g}")
            dlg._syncing = False

        v_sain.trace_add("write", _on_sain_changed)
        v_alt.trace_add("write", _on_alt_changed)

        ttk.Label(dlg, text="Compartimentation", background=COLOR_PANEL
                  ).grid(row=4, column=0, sticky="w", **pad)
        ttk.Combobox(dlg, textvariable=v_comp,
                     values=["active", "absente", "-"],
                     state="readonly", width=16
                     ).grid(row=4, column=1, sticky="w", **pad)

        ttk.Label(dlg, text="Commentaire", background=COLOR_PANEL
                  ).grid(row=5, column=0, sticky="w", **pad)
        ttk.Entry(dlg, textvariable=v_com, width=28
                  ).grid(row=5, column=1, sticky="we", **pad)

        def ok():
            try:
                # Accepte "100 gr — E" ou ancien "100° — E"
                raw = v_grade.get().replace("°", " ").split(" ")[0].strip()
                s.grade = int(raw)
                sain = float(v_sain.get() or 0)
                alt = float(v_alt.get() or 0)
                if R > 0:
                    # Clamp et recoller à R pour éviter toute incohérence
                    sain = max(0.0, min(sain, R))
                    alt = max(0.0, min(alt, R))
                    # si la somme ne fait pas R, on fait confiance à
                    # l'altéré (dernière grandeur pertinente métier)
                    if abs(sain + alt - R) > 1e-6:
                        sain = R - alt
                s.bois_sain_cm = sain
                s.bois_altere_cm = alt
                s.compartimentation = v_comp.get()
                s.commentaire = v_com.get()
                result["ok"] = True
                dlg.destroy()
            except ValueError as e:
                messagebox.showerror("Erreur de saisie",
                                     f"Valeur invalide : {e}", parent=dlg)

        btns = ttk.Frame(dlg, style="Panel.TFrame")
        btns.grid(row=6, column=0, columnspan=2, pady=(10, 12))
        ttk.Button(btns, text="Annuler", style="Ghost.TButton",
                   command=dlg.destroy).pack(side="right", padx=6)
        ttk.Button(btns, text="Valider", style="Accent.TButton",
                   command=ok).pack(side="right")

        dlg.wait_window()
        return result["ok"]

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
                classe, _ = classer_prbs(ratio, port)
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
            import traceback
            traceback.print_exc()
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
                w.writerow(["N° arbre", "Essence", "Rayon (cm)",
                            "N° sondage", "Grade (gr)", "Direction",
                            "PRBS (cm)", "Bois altéré (cm)",
                            "t/R (%)",
                            "Compartimentation", "Commentaire"])
                for a in self.chantier.arbres:
                    for s in a.sondages:
                        d = DIRECTION_LABELS.get(s.grade, "")
                        tR_pct = f"{100*s.ratio_tR(a.rayon_tronc_cm):.1f}"
                        w.writerow([a.numero_arbre, a.essence,
                                    a.rayon_tronc_cm, s.numero,
                                    s.grade, d,
                                    s.prbs_cm, s.bois_altere_cm,
                                    tR_pct,
                                    s.compartimentation, s.commentaire])
            messagebox.showinfo("Exporté", f"CSV enregistré : {p}")
        except Exception as e:
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


# ---------------------------------------------------------------------------
# Rendu PIL : dessin de la section + fiche PDF complète
# ---------------------------------------------------------------------------

def _pil_load_fonts():
    """Charge un jeu de polices cohérent, avec fallback sur le défaut PIL."""
    if not HAS_PIL:
        return None
    from PIL import ImageFont
    candidates = [
        # Linux
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        # Windows
        r"C:\Windows\Fonts\georgiab.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
        # macOS
        "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
        "/Library/Fonts/Arial.ttf",
    ]
    paths = {"serif_bold": None, "sans": None, "sans_bold": None}
    for c in candidates:
        try:
            ImageFont.truetype(c, 12)
            name = c.lower()
            if paths["serif_bold"] is None and ("serifb" in name or "georgiab" in name):
                paths["serif_bold"] = c
            elif paths["sans_bold"] is None and "bold" in name and "serif" not in name:
                paths["sans_bold"] = c
            elif paths["sans"] is None and "serif" not in name:
                paths["sans"] = c
        except Exception:
            continue
    def f(size, variant="sans"):
        path = paths.get(variant) or paths.get("sans") or paths.get("serif_bold")
        try:
            return ImageFont.truetype(path, size) if path \
                else ImageFont.load_default()
        except Exception:
            return ImageFont.load_default()
    return f


def render_arbre_to_pil_image(arbre: "Arbre",
                              width: int = 1600, height: int = 1600,
                              show_sondages: bool = True,
                              show_title: bool = True,
                              show_legend: bool = False) -> "Image.Image":
    """Rend la section transversale d'un arbre en image PIL (PNG/PDF).
    Logique identique à SectionCanvas.redraw() mais sans dépendance tk.

    Si `show_legend=True`, une légende adaptative est dessinée à gauche
    du tronc (Bois sain / Bois dégradé / Écorce / Sondage / Classes) ;
    la section circulaire est alors décalée vers la droite pour ménager
    une bande dédiée à la légende.
    """
    from PIL import Image, ImageDraw
    f = _pil_load_fonts()
    img = Image.new("RGB", (width, height), COLOR_PANEL)
    d = ImageDraw.Draw(img, "RGBA")

    if arbre.rayon_tronc_cm <= 0:
        d.text((width/2, height/2),
               "Rayon non renseigné", fill=COLOR_MUTED,
               font=f(28, "sans"), anchor="mm")
        return img

    R = arbre.rayon_tronc_cm
    # Marges adaptées à la taille (responsive) :
    # - haut : titre+méta+lettre N hors écorce (proportionnel)
    # - bas : pastille S à l'intérieur, règle graduée + label
    if show_title:
        margin_top = max(140, int(height * 0.13))
    else:
        margin_top = 70   # juste pour que la lettre N tienne au-dessus
    # Si la légende doit être affichée, on la pose en bas (sous la règle
    # graduée), sur une seule ligne horizontale. On réserve donc une
    # bande de hauteur en bas, ce qui repousse la section vers le haut.
    legend_bottom_h = max(70, int(height * 0.085)) if show_legend else 0
    margin_bottom = max(160, int(height * 0.16)) + legend_bottom_h
    margin_side = max(80, int(width * 0.08))
    available_v = height - margin_top - margin_bottom
    available_h = width - 2 * margin_side
    radius_px_max = min(available_h / 2, available_v / 2)
    cx = width / 2
    cy = margin_top + radius_px_max
    # Réserver l'espace pour l'écorce + les contreforts. L'écorce ajoute
    # `epaisseur_ecorce_cm` vers l'extérieur, et les contreforts encore
    # `longueur_cm` au-delà.
    # `radius_px` reste le rayon en pixels du BOIS (tronc sous écorce) ;
    # `radius_ext_px` est le rayon externe (bois + écorce).
    ep = max(0.0, arbre.epaisseur_ecorce_cm)
    R_ext = R + ep
    expansion = ep + max((c.longueur_cm for c in arbre.contreforts),
                          default=0.0)
    R_eff = R + expansion
    scale = radius_px_max / R_eff
    radius_px = R * scale
    radius_ext_px = R_ext * scale

    def polar(r_cm, idx):
        a = math.radians(idx * (360/16) - 90)
        return (cx + r_cm * scale * math.cos(a),
                cy + r_cm * scale * math.sin(a))

    def polar_grade(r_cm, grade):
        a = math.radians(grade * 360/400 - 90)
        return (cx + r_cm * scale * math.cos(a),
                cy + r_cm * scale * math.sin(a))

    # Disque bois sain
    d.ellipse([cx-radius_px, cy-radius_px, cx+radius_px, cy+radius_px],
              fill=COLOR_WOOD)

    # Cernes de croissance — par-dessus le bois, en brun très foncé fin.
    # Ils seront partiellement effacés par la cavité qui suit, ce qui les
    # rend visibles uniquement dans le bois sain.
    for k in range(1, 9):
        rr = radius_px * k / 9
        d.ellipse([cx-rr, cy-rr, cx+rr, cy+rr],
                  outline=COLOR_CERNE, width=1)

    # Cavité altération (spline) — couleur uniforme, pas de contour
    arbre.recompute_alteration_from_sondages()
    alt = arbre.alteration_par_grade
    inner_cm = [max(0, alt[i]) for i in range(16)]
    if any(a > 0 for a in alt):
        pts = [polar(inner_cm[i], i) for i in range(16)]
        smooth = catmull_rom_closed(pts, 32)
        d.polygon(smooth, fill=COLOR_ROT, outline=None)

    # Écorce. Si une épaisseur est renseignée, on dessine un anneau
    # brun épais entre R et R+ep ; sinon trait fin classique au bord
    # du bois.
    # Note PIL : `d.ellipse(outline, width)` trace l'outline À
    # L'INTÉRIEUR du bounding box (pas centré sur la frontière
    # comme Tkinter). Avec bbox de rayon R_ext et width=ep_px,
    # l'outline va de R_ext-ep à R_ext, soit exactement [R, R_ext].
    if ep > 0:
        ep_px = max(1.0, ep * scale)
        d.ellipse([cx-radius_ext_px, cy-radius_ext_px,
                   cx+radius_ext_px, cy+radius_ext_px],
                  outline=COLOR_BARK, width=int(round(ep_px)))
    else:
        d.ellipse([cx-radius_px, cy-radius_px,
                   cx+radius_px, cy+radius_px],
                  outline=COLOR_BARK, width=4)

    # Contreforts (empattements à la base du tronc) — fusionnés par
    # zones connectées. Les contreforts qui se chevauchent ou se
    # touchent sont rendus comme une seule cloche unifiée (max des
    # hauteurs à chaque grade), ce qui évite les encoches en V à la
    # jonction de deux contreforts proches.
    cf_inner_r = R - 1.0 / scale
    for a, b in contrefort_zones(arbre.contreforts):
        span = b - a
        n_steps = max(32, int(span) + 1)
        wood_outer = []
        bark_outer = []
        for k in range(n_steps + 1):
            t = a + k * span / n_steps
            g = t % 400
            bell = bell_max_at_grade(g, arbre.contreforts)
            r_wood = R + bell
            wood_outer.append(polar_grade(r_wood, g))
            if ep > 0:
                bark_outer.append(polar_grade(r_wood + ep, g))
        base = []
        for k in range(n_steps, -1, -1):
            t = a + k * span / n_steps
            g = t % 400
            base.append(polar_grade(cf_inner_r, g))
        if ep > 0:
            bark_inner = []
            for k in range(n_steps, -1, -1):
                t = a + k * span / n_steps
                g = t % 400
                bark_inner.append(polar_grade(R, g))
            d.polygon(bark_outer + bark_inner, fill=COLOR_BARK)
        d.polygon(wood_outer + base, fill=COLOR_WOOD)
        if ep == 0:
            d.line(wood_outer, fill=COLOR_BARK, width=4, joint="curve")

    # Dégradations externes — dessinées EN DERNIER pour qu'elles
    # creusent l'écorce ET les contreforts dans leur secteur.
    # Le bord externe du polygone suit la surface réelle de l'arbre
    # (R + ep + cloche), donc une dégradation qui passe sur un
    # contrefort y mord à concurrence de sa profondeur.
    for deg in arbre.degradations_externes:
        if deg.profondeur_cm <= 0:
            continue
        n_steps = max(16, int(deg.largeur_grades()) + 1)
        outer_pts = []
        inner_pts = []
        for k in range(n_steps + 1):
            g = (deg.grade_debut
                 + k * deg.largeur_grades() / n_steps) % 400
            bell = bell_max_at_grade(g, arbre.contreforts)
            r_out = R + ep + bell
            r_in = max(0.0, r_out - deg.profondeur_cm)
            outer_pts.append(polar_grade(r_out, g))
            inner_pts.append(polar_grade(r_in, g))
        pts_arc = outer_pts + list(reversed(inner_pts))
        d.polygon(pts_arc, fill=COLOR_ROT, outline=None)

    # Ticks 16 grades — à l'extérieur de l'écorce
    for i, g in enumerate(GRADES):
        x1, y1 = polar(R_ext, i)
        x2, y2 = polar(R_ext + 12/scale, i)
        maj = (g % 50 == 0)
        d.line([x1, y1, x2, y2],
               fill=COLOR_BARK if maj else COLOR_BARK_LIGHT,
               width=3 if maj else 1)

    # Lettres cardinales — à 35 px hors écorce, halo blanc
    for i, g in enumerate(GRADES):
        lbl = DIRECTION_LABELS.get(g, "")
        if not lbl:
            continue
        lx, ly = polar(R_ext + 45/scale, i)
        for dx in (-4, -3, 0, 3, 4):
            for dy in (-4, -3, 0, 3, 4):
                if dx or dy:
                    d.text((lx+dx, ly+dy), lbl, font=f(36, "serif_bold"),
                           fill="white", anchor="mm")
        d.text((lx, ly), lbl, font=f(36, "serif_bold"),
               fill=COLOR_INK, anchor="mm")

    # Sondages (optionnel) — pastilles à l'INTÉRIEUR du tronc, juste sous
    # l'écorce. Cela libère tout l'extérieur pour les lettres cardinales.
    if show_sondages:
        port = arbre.port_arbre
        meche = arbre.meche_cm if arbre.meche_cm > 0 else float("inf")
        for s in arbre.sondages:
            if s.grade not in GRADES:
                continue
            i = GRADES.index(s.grade)
            penetration = min(s.bois_sain_cm + s.bois_altere_cm, meche)
            penetration = max(0.0, min(penetration, R))
            end_radius = R - penetration
            _, col_class = classer_prbs(s.ratio_tR(R), port)
            # Flèche : depuis 18 px sous l'écorce vers la fin de pénétration
            x_ext, y_ext = polar(R - 18/scale, i)
            x_end, y_end = polar(end_radius, i)
            d.line([x_ext, y_ext, x_end, y_end], fill=COLOR_SOND, width=4)
            ang = math.atan2(y_end-y_ext, x_end-x_ext)
            ah = 12
            d.polygon([
                (x_end, y_end),
                (x_end - ah*math.cos(ang-0.5), y_end - ah*math.sin(ang-0.5)),
                (x_end - ah*math.cos(ang+0.5), y_end - ah*math.sin(ang+0.5)),
            ], fill=COLOR_SOND)
            # Pastille à 18 px à l'INTÉRIEUR de l'écorce
            px, py = polar(R - 18/scale, i)
            r_b = 22
            d.ellipse([px-r_b-2, py-r_b-2, px+r_b+2, py+r_b+2],
                      fill="white")
            d.ellipse([px-r_b, py-r_b, px+r_b, py+r_b],
                      fill=col_class, outline="white", width=2)
            d.text((px, py), str(s.numero), font=f(20, "sans_bold"),
                   fill="white", anchor="mm")

    # RÈGLE GRADUÉE — placée SOUS la section, hors de l'écorce.
    # Étendue jusqu'au rayon externe (R + ep). La portion bois
    # ([-R, +R]) est en trait noir fin ; les portions écorce
    # ([-R_ext, -R] et [+R, +R_ext]) sont des barres brun foncé
    # épaisses qui évoquent l'écorce.
    step = 5 if R >= 15 else (2 if R >= 6 else 1)
    y_axis = cy + radius_ext_px + 105
    y_axis = min(y_axis, height - 60)
    wood_half_px = R * scale
    ext_half_px = R_ext * scale
    x_lw, x_rw = cx - wood_half_px, cx + wood_half_px
    x_le, x_re = cx - ext_half_px, cx + ext_half_px

    # Trait bois (noir fin) au centre
    d.line([x_lw, y_axis, x_rw, y_axis], fill=COLOR_INK, width=3)
    # Barres écorce (brun foncé épais) aux extrémités
    if ep > 0:
        bar_h = 10
        d.rectangle([x_le, y_axis - bar_h/2,
                     x_lw, y_axis + bar_h/2], fill=COLOR_BARK)
        d.rectangle([x_rw, y_axis - bar_h/2,
                     x_re, y_axis + bar_h/2], fill=COLOR_BARK)
    # Tirets aux extrémités externes (R+ep)
    end_color = COLOR_BARK if ep > 0 else COLOR_INK
    d.line([x_le, y_axis-12, x_le, y_axis+12], fill=end_color, width=3)
    d.line([x_re, y_axis-12, x_re, y_axis+12], fill=end_color, width=3)
    # Tirets à la transition bois/écorce (R)
    if ep > 0:
        d.line([x_lw, y_axis-9, x_lw, y_axis+9], fill=COLOR_INK, width=3)
        d.line([x_rw, y_axis-9, x_rw, y_axis+9], fill=COLOR_INK, width=3)
    # Graduations intermédiaires (bois) tous les `step` cm,
    # exclues à la valeur R (déjà marquée par le tiret de transition).
    for r in range(step, int(R), step):
        rr = r * scale
        for sign in (-1, 1):
            xg = cx + sign * rr
            d.line([xg, y_axis-7, xg, y_axis+7], fill=COLOR_INK, width=2)
            d.text((xg, y_axis+28), f"{r}",
                   font=f(18, "sans_bold"), fill=COLOR_INK, anchor="mm")
    # Étiquette à R (bord bois/écorce) en gras
    if R > 0:
        label_R = f"{R:g}"
        for xg in (x_lw, x_rw):
            d.text((xg, y_axis+28), label_R,
                   font=f(18, "sans_bold"), fill=COLOR_INK, anchor="mm")
    # Étiquette à R+ep (extrémité externe) en gras brun.
    # Si l'écart bois/écorce est trop serré (ep_px < 45 px en PIL),
    # on décale d'une ligne en dessous pour ne pas chevaucher R.
    if ep > 0:
        label_ext = f"{R + ep:g}"
        ext_y = y_axis + (52 if ep * scale < 45 else 28)
        for xg in (x_le, x_re):
            d.text((xg, ext_y), label_ext,
                   font=f(18, "sans_bold"), fill=COLOR_BARK, anchor="mm")
    # Repère "0" au centre
    d.text((cx, y_axis+28), "0",
           font=f(18, "sans_bold"), fill=COLOR_INK, anchor="mm")
    # Label "cm" à droite
    d.text((x_re+35, y_axis), "cm",
           font=f(20, "sans_bold"), fill=COLOR_INK, anchor="lm")
    # Point central de la section
    d.ellipse([cx-5, cy-5, cx+5, cy+5], fill=COLOR_INK)

    # Titre — positions proportionnelles à la hauteur (si show_title)
    if show_title:
        title_y = max(45, int(height * 0.045))
        sub_y = title_y + 52
        d.text((width/2, title_y), arbre.display_name,
               font=f(44, "serif_bold"), fill=COLOR_ACCENT, anchor="mm")
        sub_parts = [f"Rayon {R:g} cm"]
        if arbre.diametre_sous_ecorce_cm:
            sub_parts.append(f"Ø sous écorce {arbre.diametre_sous_ecorce_cm:g} cm")
        if arbre.hauteur_arbre_m:
            sub_parts.append(f"H {arbre.hauteur_arbre_m:g} m")
        if arbre.meche_cm:
            sub_parts.append(f"Mèche {arbre.meche_cm:g} cm")
        d.text((width/2, sub_y), "   •   ".join(sub_parts),
               font=f(24, "sans"), fill=COLOR_MUTED, anchor="mm")

    # Légende horizontale (uniquement si demandée), placée sous la
    # règle graduée. Elle occupe la bande inférieure réservée par
    # `legend_bottom_h` plus haut.
    if show_legend:
        legend_y = y_axis + max(50, int(height * 0.045))
        _draw_horizontal_legend_pil(d, arbre, y_top=legend_y,
                                     width=width, height=height,
                                     font_fn=f)

    return img


def _draw_horizontal_legend_pil(d, arbre, y_top, width, height,
                                font_fn) -> None:
    """Dessine la légende du dessin de section sur UNE LIGNE horizontale,
    centrée, sous la règle graduée.

    Légende adaptative : on n'affiche que les éléments effectivement
    présents sur le dessin (Bois dégradé seulement s'il y a des
    altérations ou dégradations externes ; Écorce seulement si une
    épaisseur > 0 a été renseignée ; etc.). Les classes du sondage
    (Vert/Orange/Rouge) sont toujours affichées si l'arbre a au moins
    un sondage — elles documentent la signification des pastilles
    colorées sur le dessin.
    """
    ep = max(0.0, arbre.epaisseur_ecorce_cm)
    has_decay = (
        bool(arbre.degradations_externes)
        or any(s.bois_altere_cm > 0 for s in arbre.sondages)
        or any(a > 0 for a in arbre.alteration_par_grade)
    )
    has_bark = ep > 0
    has_sondages = bool(arbre.sondages)

    item_size = max(13, int(height * 0.018))
    swatch_w = max(20, int(height * 0.024))
    swatch_h = max(14, int(height * 0.018))
    r_p = max(8, int(height * 0.012))
    item_font = font_fn(item_size, "sans")
    bold_font = font_fn(item_size, "sans_bold")

    items = [("wood", "Bois sain")]
    if has_decay:
        items.append(("rot", "Bois dégradé"))
    if has_bark:
        items.append(("bark", "Écorce"))
    if has_sondages:
        items.append(("arrow", "Sondage"))

    classes = (
        ("Vert", "#2D7A3E"),
        ("Orange", "#E67E22"),
        ("Rouge", "#C0392B"),
    ) if has_sondages else ()
    classes_prefix = "Classe du sondage :"

    # Pré-calcul des largeurs pour centrer le bloc complet.
    def text_w(txt, font):
        bbox = d.textbbox((0, 0), txt, font=font)
        return bbox[2] - bbox[0]

    item_widths = [swatch_w + 8 + text_w(label, item_font)
                   for _, label in items]
    classes_w = 0
    if classes:
        classes_w = text_w(classes_prefix, bold_font) + 12
        for label, _ in classes:
            classes_w += 2 * r_p + 6 + text_w(label, item_font) + 14
        classes_w -= 14  # pas de gap après le dernier

    gap = max(22, int(width * 0.018))
    total_w = sum(item_widths) + gap * max(0, len(items) - 1)
    if classes:
        total_w += gap + classes_w

    x_cur = max(20, (width - total_w) // 2)
    sw_top = y_top + (item_size - swatch_h) // 2 + 2  # alignement vertical

    for i, (kind, label) in enumerate(items):
        if kind == "wood":
            d.rectangle([x_cur, sw_top,
                         x_cur + swatch_w, sw_top + swatch_h],
                        fill=COLOR_WOOD, outline=COLOR_BARK, width=1)
        elif kind == "rot":
            d.rectangle([x_cur, sw_top,
                         x_cur + swatch_w, sw_top + swatch_h],
                        fill=COLOR_ROT)
        elif kind == "bark":
            d.rectangle([x_cur, sw_top,
                         x_cur + swatch_w, sw_top + swatch_h],
                        fill=COLOR_BARK)
        elif kind == "arrow":
            ay = sw_top + swatch_h / 2
            ax1 = x_cur + 2
            ax2 = x_cur + swatch_w - 4
            d.line([(ax1, ay), (ax2, ay)],
                   fill=COLOR_SOND, width=max(2, int(height * 0.0028)))
            ah = max(6, int(height * 0.008))
            d.polygon([(ax2 + ah, ay),
                       (ax2 - 1, ay - ah * 0.65),
                       (ax2 - 1, ay + ah * 0.65)], fill=COLOR_SOND)
        d.text((x_cur + swatch_w + 8, sw_top + swatch_h / 2), label,
               font=item_font, fill=COLOR_INK, anchor="lm")
        x_cur += item_widths[i] + gap

    if classes:
        d.text((x_cur, sw_top + swatch_h / 2), classes_prefix,
               font=bold_font, fill=COLOR_INK, anchor="lm")
        x_cur += text_w(classes_prefix, bold_font) + 12
        for label, hex_col in classes:
            cy_p = sw_top + swatch_h / 2
            d.ellipse([x_cur, cy_p - r_p,
                       x_cur + 2 * r_p, cy_p + r_p],
                      fill=hex_col, outline="white",
                      width=max(1, int(height * 0.0018)))
            x_cur += 2 * r_p + 6
            d.text((x_cur, cy_p), label, font=item_font,
                   fill=hex_col, anchor="lm")
            x_cur += text_w(label, item_font) + 14


def _fit_text(text: str, font, max_width: float, draw) -> str:
    """Tronque `text` avec une ellipsis « … » si sa largeur dépasse
    `max_width`. Évite que les valeurs débordent de leur colonne."""
    if not text:
        return ""
    bbox = draw.textbbox((0, 0), text, font=font)
    if bbox[2] - bbox[0] <= max_width:
        return text
    ellipsis = "…"
    while text:
        text = text[:-1]
        bbox = draw.textbbox((0, 0), text + ellipsis, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return text + ellipsis
    return ellipsis


def render_fiche_arbre_to_pdf_page(arbre: "Arbre",
                                   chantier: "Chantier") -> "Image.Image":
    """Construit une page A4 portrait 150 DPI (1240 × 1754 px environ)
    avec : en-tête chantier, dessin, tableau PRBS, diagnostic.

    Les tailles de police, largeurs de colonnes et marges sont calibrées
    pour rester lisibles à l'impression (≈ 12 pt minimum au tirage A4).
    """
    from PIL import Image, ImageDraw
    f = _pil_load_fonts()

    # A4 portrait à 150 DPI
    W, H = 1240, 1754
    page = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(page)

    margin = 60
    y = margin

    # --- En-tête mission avec logo Silvavenir ---
    header_h = 116
    d.rectangle([margin, y, W-margin, y+header_h], fill=COLOR_ACCENT)
    # Logo à droite
    logo_w = 0
    try:
        logo_path = Path(__file__).parent / "silvavenir_logo.jpg"
        if logo_path.exists():
            logo = Image.open(logo_path).convert("RGBA")
            target_h = header_h - 24
            ratio = target_h / logo.height
            logo = logo.resize(
                (int(logo.width * ratio), target_h),
                Image.LANCZOS)
            # Fond blanc derrière le logo pour le détacher du vert
            logo_bg = Image.new("RGB", logo.size, "white")
            logo_bg.paste(logo, (0, 0), logo if logo.mode == "RGBA" else None)
            page.paste(logo_bg,
                       (W - margin - logo.width - 12, y + 12))
            logo_w = logo.width + 24
    except Exception:
        pass

    # Largeur disponible pour le texte d'en-tête (sans empiéter sur le logo)
    header_text_w = W - margin*2 - logo_w - 20
    title_txt = "Fiche d'expertise — Pénétromètre"
    d.text((margin+20, y+22), title_txt,
           font=f(30, "serif_bold"), fill="white")
    mission_txt = _fit_text(
        f"Mission : {chantier.nom}   •   {chantier.adresse}",
        f(19, "sans"), header_text_w, d)
    d.text((margin+20, y+64), mission_txt,
           font=f(19, "sans"), fill="white")
    d.text((margin+20, y+92),
           f"{chantier.date_releve}   •   Opérateur : {chantier.operateur}",
           font=f(17, "sans"), fill="white")
    y += header_h + 18

    # --- Identité de l'arbre ---
    d.text((margin, y), arbre.display_name,
           font=f(35, "serif_bold"), fill=COLOR_INK)
    y += 50
    R = arbre.rayon_tronc_cm
    ligne = (f"Rayon : {R:g} cm   •   "
             f"Ø sous écorce : {arbre.diametre_sous_ecorce_cm:g} cm   •   "
             f"Hauteur : {arbre.hauteur_arbre_m:g} m   •   "
             f"Port : {arbre.port_arbre}")
    ligne = _fit_text(ligne, f(18, "sans"), W - 2*margin, d)
    d.text((margin, y), ligne, font=f(18, "sans"), fill=COLOR_MUTED)
    y += 32
    if arbre.commentaire:
        comm = _fit_text(f"Commentaire : {arbre.commentaire}",
                          f(17, "sans"), W - 2*margin, d)
        d.text((margin, y), comm, font=f(17, "sans"), fill=COLOR_INK)
        y += 30

    # --- Dessin ---
    # Taille adaptative : on estime la hauteur que vont occuper le
    # tableau PRBS et le diagnostic, puis on alloue le reste au dessin
    # (entre 480 et 900 px). Évite que la page déborde quand l'arbre a
    # beaucoup de sondages, sans rapetisser inutilement le dessin quand
    # il en a peu.
    n_sond = len(arbre.sondages) if R > 0 else 0
    # Hauteur de ligne adaptative : on resserre les lignes du tableau
    # quand l'arbre a beaucoup de sondages, pour éviter de déborder de la
    # page. La police reste lisible (15 pt minimum).
    if n_sond > 12:
        row_h = 32
        row_font_size = 15
    elif n_sond > 8:
        row_h = 35
        row_font_size = 16
    else:
        row_h = 38
        row_font_size = 17
    est_table_h = (36 + 44 + n_sond * row_h + 18) if n_sond > 0 else 0
    est_diag_h = 360  # majorant : t/R + bar + détail + classe globale
    # La légende horizontale est dessinée APRÈS le dessin du tronc, sur
    # la pleine largeur de la page (pas dans l'image du tronc qui est
    # plus étroite). On réserve une bande pour elle dans le calcul.
    est_legend_h = 56
    footer_reserve = 60
    used_so_far = y - margin   # depuis le haut de la page utile
    remaining = (H - margin - footer_reserve) - used_so_far \
                - est_table_h - est_diag_h - est_legend_h - 22
    drawing_h = max(420, min(900, remaining))
    drawing_w = drawing_h
    # Le dessin lui-même est rendu sans légende ; la légende est tracée
    # ci-dessous, en dehors du dessin, pour profiter de toute la largeur.
    drawing = render_arbre_to_pil_image(arbre, drawing_w, drawing_h,
                                        show_sondages=True,
                                        show_title=False,
                                        show_legend=False)
    x_draw = (W - drawing_w) // 2
    page.paste(drawing, (x_draw, y))
    y += drawing_h + 6
    # Légende horizontale, centrée, sur la pleine largeur utile. Calibrée
    # pour donner des polices ≈ 16 pt et des pastilles bien lisibles.
    if R > 0:
        _draw_horizontal_legend_pil(d, arbre, y_top=y,
                                     width=W, height=900, font_fn=f)
        y += est_legend_h

    # --- Tableau PRBS ajustée par sondage ---
    if R > 0 and arbre.sondages:
        d.text((margin, y), "Paroi Résiduelle de Bois Sain par sondage",
               font=f(22, "serif_bold"), fill=COLOR_ACCENT)
        y += 36
        deg_ext_par_grade = arbre.degradation_externe_par_grade()
        # Largeurs de colonnes redistribuées : Direction et PRBS plus
        # généreuses (où les valeurs sont les plus longues), Compart.
        # rétrécie (souvent juste « - » ou « active »).
        # Total = 70 + 220 + 270 + 130 + 160 + 270 = 1120 = W - 2*margin.
        col_widths = [70, 220, 270, 130, 160, 270]
        cols_x = [margin]
        for w in col_widths:
            cols_x.append(cols_x[-1] + w)
        # cols_x = [60, 130, 350, 620, 750, 910, 1180]
        headers = ["N°", "Direction", "PRBS ajustée (cm)", "t/R (%)",
                   "Classe", "Compart."]
        # Alignement : N° et nombres à droite ; texte à gauche.
        right_align = {0, 3}            # N°, t/R (%)
        right_align_data = {0, 3}       # idem pour les valeurs
        header_h_row = 44
        d.rectangle([cols_x[0], y, cols_x[-1], y+header_h_row],
                    fill=COLOR_ACCENT)
        for i, h in enumerate(headers):
            if i in right_align:
                d.text((cols_x[i+1]-12, y+header_h_row/2), h,
                       font=f(17, "sans_bold"), fill="white",
                       anchor="rm")
            else:
                d.text((cols_x[i]+12, y+header_h_row/2), h,
                       font=f(17, "sans_bold"), fill="white",
                       anchor="lm")
        y += header_h_row
        for k, s in enumerate(arbre.sondages):
            dir_lbl = DIRECTION_LABELS.get(s.grade, "")
            direction = f"{dir_lbl} ({s.grade} gr)" if dir_lbl \
                else f"{s.grade} gr"
            idx_g = GRADES.index(s.grade) if s.grade in GRADES else 0
            deg_ext = deg_ext_par_grade[idx_g]
            prbs_adj = max(0.0, s.prbs_cm - deg_ext)
            ratio = prbs_adj / R
            classe, col_c = classer_prbs(ratio, arbre.port_arbre)
            if k % 2 == 0:
                d.rectangle([cols_x[0], y, cols_x[-1], y+row_h],
                            fill="#F7F3EA")
            if deg_ext > 0:
                prbs_txt = f"{prbs_adj:g}  (–{deg_ext:g} ext.)"
            else:
                prbs_txt = f"{prbs_adj:g}"
            vals = [str(s.numero), direction, prbs_txt,
                    f"{100*ratio:.1f}", classe, s.compartimentation]
            for i, v in enumerate(vals):
                col = col_c if i == 4 else COLOR_INK
                wt = "sans_bold" if i == 4 else "sans"
                font_v = f(row_font_size, wt)
                col_w = col_widths[i] - 24  # padding 12 de chaque côté
                txt = _fit_text(v, font_v, col_w, d)
                if i in right_align_data:
                    d.text((cols_x[i+1]-12, y+row_h/2), txt,
                           font=font_v, fill=col, anchor="rm")
                else:
                    d.text((cols_x[i]+12, y+row_h/2), txt,
                           font=font_v, fill=col, anchor="lm")
            y += row_h
        y += 18

    # --- Diagnostic global enrichi (répartition par classe) ---
    d.text((margin, y), "Diagnostic",
           font=f(22, "serif_bold"), fill=COLOR_ACCENT)
    y += 36
    rep = arbre.repartition_classes()
    ratios = arbre.ratio_tR_par_grade()
    if R > 0 and not all(r >= 0.999 for r in ratios):
        d.text((margin, y),
               f"t/R moyen sur le pourtour : {100*rep['tR_moyen']:.1f} %",
               font=f(18, "sans_bold"), fill=COLOR_INK)
        y += 28
        d.text((margin, y),
               f"t/R minimal : {100*rep['tR_min']:.1f} %  "
               f"(grade {rep['tR_min_grade']} gr — {rep['tR_min_dir']})",
               font=f(18, "sans"), fill=COLOR_INK)
        y += 32
        d.text((margin, y),
               "Répartition sur le pourtour (16 directions) :",
               font=f(18, "sans_bold"), fill=COLOR_INK)
        y += 30
        # Barre horizontale empilée Vert/Orange/Rouge — plus haute pour
        # que le pourcentage soit lisible même sur des segments étroits.
        bar_w = W - 2*margin
        bar_h = 36
        x_cur = margin
        # Petites étiquettes hors-barre pour les segments trop étroits
        # pour porter leur texte à l'intérieur.
        outside_labels = []
        for cls in ("Vert", "Orange", "Rouge"):
            seg_pct = rep[cls]["pct"]
            seg_w = bar_w * seg_pct / 100.0
            if seg_w > 0:
                _, col = classer_prbs(
                    {"Vert": 1.0, "Orange": 0.20, "Rouge": 0.05}[cls],
                    arbre.port_arbre)
                d.rectangle([x_cur, y, x_cur + seg_w, y + bar_h],
                            fill=col)
                if seg_w > 95:
                    d.text((x_cur + seg_w/2, y + bar_h/2),
                           f"{cls} {seg_pct:.0f} %",
                           font=f(15, "sans_bold"), fill="white",
                           anchor="mm")
                else:
                    outside_labels.append((cls, seg_pct, col,
                                            x_cur + seg_w/2))
                x_cur += seg_w
        y += bar_h + 4
        # Étiquettes externes (au-dessous de la barre, en couleur du
        # segment), avec petit triangle indicateur au-dessus.
        for cls, pct, col, x_center in outside_labels:
            d.polygon([(x_center, y),
                       (x_center - 6, y + 8),
                       (x_center + 6, y + 8)], fill=col)
            d.text((x_center, y + 12), f"{cls} {pct:.0f} %",
                   font=f(15, "sans_bold"), fill=col, anchor="mt")
        if outside_labels:
            y += 36
        else:
            y += 8
        # Détail textuel — sur UNE seule ligne pour économiser l'espace.
        # On n'affiche que les classes non vides, séparées par " • ", et
        # chaque libellé est rendu dans la couleur de sa classe.
        chunks = []
        for cls in ("Vert", "Orange", "Rouge"):
            n = rep[cls]["n"]
            if n > 0:
                grades = rep[cls]["grades"]
                _, col = classer_prbs(
                    {"Vert": 1.0, "Orange": 0.20, "Rouge": 0.05}[cls],
                    arbre.port_arbre)
                chunks.append(
                    (f"{cls} {n}/16 ({grades} gr)", col))
        if chunks:
            font_chunk = f(17, "sans")
            font_sep = f(17, "sans")
            sep = "   •   "
            sep_w = d.textbbox((0, 0), sep, font=font_sep)[2]
            x_chunk = margin
            for i, (txt, col) in enumerate(chunks):
                if i > 0:
                    d.text((x_chunk, y), sep,
                           font=font_sep, fill=COLOR_MUTED)
                    x_chunk += sep_w
                d.text((x_chunk, y), txt, font=font_chunk, fill=col)
                bbox = d.textbbox((0, 0), txt, font=font_chunk)
                x_chunk += bbox[2] - bbox[0]
            y += 28
        y += 10
        # Gros marqueur coloré pour la classe globale (basée sur t/R moyen).
        # Boîte plus large et plus haute pour rester proportionnée aux
        # autres éléments de la page.
        classe_g = rep["classe_globale"]
        _, col_g = classer_prbs(
            {"Vert": 1.0, "Orange": 0.20, "Rouge": 0.05}[classe_g],
            arbre.port_arbre)
        box_w, box_h = 460, 60
        d.rectangle([margin, y, margin+box_w, y+box_h], fill=col_g)
        d.text((margin+box_w/2, y+box_h/2),
               f"Classe globale : {classe_g}",
               font=f(24, "sans_bold"), fill="white", anchor="mm")
        y += box_h + 8
    else:
        d.text((margin, y), "Aucune altération saisie.",
               font=f(18, "sans"), fill=COLOR_INK)

    # --- Pied de page ---
    d.line([margin, H-46, W-margin, H-46], fill=COLOR_MUTED, width=1)
    d.text((W/2, H-24),
           f"Pénétromètre — Silvavenir, Foresterie urbaine   •   "
           f"Édité le {datetime.now().strftime('%d/%m/%Y à %H:%M')}",
           font=f(14, "sans"), fill=COLOR_MUTED, anchor="mm")

    return page


def main():
    App().mainloop()

if __name__ == "__main__":
    main()
