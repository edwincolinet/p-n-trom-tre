"""
Helpers géométriques et logique de classification du Pénétromètre.

Ce module ne dépend QUE de la stdlib (`math`). Il est volontairement
isolé de Tkinter, de PIL et de toute UI : il contient les briques pures
qui peuvent être couvertes par des tests unitaires sans embarquer la
couche graphique.

Contenu :
- `GRADES`, `DIRECTION_LABELS` : 16 directions du sondage (constantes
  métier, source unique partagée par le modèle et les exports).
- `catmull_rom_closed` : interpolation spline fermée (Catmull & Rom).
- `bell_max_at_grade`  : hauteur de cloche cosinus² maximale à un grade
  donné, sur l'ensemble des contreforts qui couvrent ce grade.
- `contrefort_zones`   : fusion des arcs angulaires couverts par des
  contreforts adjacents ou chevauchants.
- `classer_prbs`       : barème Silvavenir (label Vert/Orange/Rouge
  selon le ratio t/R et le port de l'arbre).

Les couleurs hexa associées aux classes ne sont PAS définies ici : ce
sont des conventions de présentation qui vivent côté UI dans
`penetrometre.py` (`COULEUR_CLASSE`).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple


# ----------------------------------------------------------------------
# Constantes métier des 16 directions
# ----------------------------------------------------------------------
#
# Le sondage couvre 16 directions cardinales et inter-cardinales, par
# pas de 25 grades (= 22,5°). Grade 0 = Nord, sens horaire.
# `DIRECTION_LABELS` mappe chaque grade vers son libellé cardinal court
# ("N", "NE", "E", ...) — chaîne vide pour les inter-quadrants
# (25, 75, 125, …) qui n'ont pas de nom court.
#
# Source unique partagée par le modèle (`model.py`), les exports
# (`export.py`) et les renderers (`penetrometre.py`, `pil_render.py`).

GRADES: List[int] = [i * 25 for i in range(16)]  # 0, 25, 50, …, 375

DIRECTION_LABELS: Dict[int, str] = {
    0: "N",   25: "",    50: "NE",  75: "",
    100: "E", 125: "",  150: "SE", 175: "",
    200: "S", 225: "",  250: "SO", 275: "",
    300: "O", 325: "",  350: "NO", 375: "",
}


# ----------------------------------------------------------------------
# Interpolation spline (Catmull-Rom fermée)
# ----------------------------------------------------------------------

def catmull_rom_closed(points: List[Tuple[float, float]],
                       samples_per_segment: int = 24
                       ) -> List[Tuple[float, float]]:
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


# ----------------------------------------------------------------------
# Géométrie des contreforts (cloche cosinus² + fusion de zones)
# ----------------------------------------------------------------------
#
# Les fonctions ci-dessous prennent une liste de contreforts typée
# `List[Any]` plutôt que `List[Contrefort]` : la dataclass `Contrefort`
# vit dans `penetrometre.py` (avec le reste du modèle) et l'importer
# créerait une dépendance circulaire. On exploite simplement les
# attributs publics (`longueur_cm`, `largeur_grades`, `grade_centre`).

def bell_max_at_grade(grade: float, contreforts: List[Any]) -> float:
    """Hauteur de cloche maximale (en cm) à l'angle `grade`, prise comme
    le maximum des hauteurs de tous les contreforts qui couvrent ce
    grade.

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
        # Distance angulaire signée dans [-200, 200)
        diff = ((grade - c.grade_centre + 200) % 400) - 200
        if -demi <= diff <= demi:
            profil = math.cos(diff / demi * math.pi / 2.0) ** 2
            h = max(h, c.longueur_cm * profil)
    return h


def contrefort_zones(contreforts: List[Any]
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


# ----------------------------------------------------------------------
# Barème Silvavenir
# ----------------------------------------------------------------------

PORTS_ARBRE = ["libre", "semi-libre", "architecturé", "traumatique"]

# Groupes de barèmes PRBS (Silvavenir) :
#   - libre + semi-libre :        Vert > 30 %, Orange 15-30 %, Rouge < 15 %
#   - architecturé + traumatique : Vert > 20 %, Orange 10-20 %, Rouge < 10 %
PORTS_GROUPE_LIBRE = ("libre", "semi-libre")
PORTS_GROUPE_STRICT = ("architecturé", "traumatique")

# Labels canoniques : la couche UI s'en sert comme clés du dict
# `COULEUR_CLASSE` (dans penetrometre.py).
CLASSE_VERT = "Vert"
CLASSE_ORANGE = "Orange"
CLASSE_ROUGE = "Rouge"


def classer_prbs(ratio_tR: float, port_arbre: str) -> str:
    """Classe un sondage selon son ratio t/R et le port de l'arbre.

    Seuils Silvavenir :
    - libre / semi-libre :         Vert > 30 %, Orange 15-30 %, Rouge < 15 %
    - architecturé / traumatique : Vert > 20 %, Orange 10-20 %, Rouge < 10 %

    Convention de bornes : seuil haut strict (`>`), seuil bas inclusif
    (`>=`). Donc pile 30 % en port libre est Orange, pile 15 % est
    Orange, 14,9 % est Rouge.

    Renvoie le label de classe (`Vert`, `Orange` ou `Rouge`). La couleur
    hexa associée est une convention de présentation et vit côté UI.
    """
    p = port_arbre.lower().strip()
    seuils = (0.20, 0.10) if p in PORTS_GROUPE_STRICT else (0.30, 0.15)
    if ratio_tR > seuils[0]:
        return CLASSE_VERT
    elif ratio_tR >= seuils[1]:
        return CLASSE_ORANGE
    else:
        return CLASSE_ROUGE


# ----------------------------------------------------------------------
# Primitives géométriques de rendu (partagées Tkinter ↔ PIL)
# ----------------------------------------------------------------------
#
# Les fonctions ci-dessous renvoient des listes de points `(x, y)` en
# coordonnées écran (pixels), prêtes à être passées à `Canvas
# .create_polygon` (Tkinter, en aplatissant) ou à `ImageDraw.polygon`
# (PIL, qui accepte directement la liste de tuples).
#
# Convention :
# - `cx, cy` : centre du tronc en pixels.
# - `scale`  : facteur cm → pixels.
# - `grade`  : direction angulaire en grades (0 à 400, sens horaire,
#              0 = Nord en haut).
# - `idx`    : indice de direction (0 à 15) pour les 16 directions
#              sondées, équivalent à `grade = idx * 25`.

def polar_to_xy(cx: float, cy: float, scale: float,
                r_cm: float, grade: float) -> Tuple[float, float]:
    """Convertit (rayon en cm, grade 0-400) en pixels (x, y).
    0 gr = Nord (en haut), sens horaire."""
    a = math.radians(grade * 360.0 / 400.0 - 90.0)
    return (cx + r_cm * scale * math.cos(a),
            cy + r_cm * scale * math.sin(a))


def polar_idx_to_xy(cx: float, cy: float, scale: float,
                    r_cm: float, idx: int) -> Tuple[float, float]:
    """Variante indexée : `idx` est un entier dans [0, 16) qui
    correspond à `grade = idx * 25`. Utilisé pour les 16 directions
    sondées."""
    a = math.radians(idx * (360.0 / 16) - 90.0)
    return (cx + r_cm * scale * math.cos(a),
            cy + r_cm * scale * math.sin(a))


def cavity_polygon(alteration_par_grade: List[float],
                   cx: float, cy: float, scale: float,
                   samples_per_segment: int = 28
                   ) -> List[Tuple[float, float]]:
    """Renvoie le polygone lissé de la cavité d'altération (Catmull-
    Rom fermée passant par les 16 points sondés/extrapolés).

    `alteration_par_grade` est la liste de 16 épaisseurs d'altération
    en cm (correspond à `Arbre.alteration_par_grade`).
    """
    pts = [polar_idx_to_xy(cx, cy, scale, max(0.0, alteration_par_grade[i]), i)
           for i in range(16)]
    return catmull_rom_closed(pts, samples_per_segment)


def contrefort_zone_outline(zone: Tuple[float, float],
                            contreforts: List[Any],
                            R: float, ep_cm: float,
                            cx: float, cy: float, scale: float,
                            R_inner: Any = None) -> dict:
    """Pour une zone fusionnée `(a, b)` renvoyée par `contrefort_zones`,
    échantillonne la cloche cosinus² fusionnée et renvoie les listes de
    points qui composent les polygones à dessiner.

    Le dict renvoyé contient toujours :
    - `wood_outer` : bord externe du noyau bois (suit `R + bell`)
    - `base`       : retour à `R_inner` (déjà inversé pour
                     concaténation directe → polygone fermé).

    Et si `ep_cm > 0` (écorce non nulle), il contient en plus :
    - `bark_outer` : bord externe de la couche d'écorce
                     (suit `R + bell + ep`)
    - `bark_inner` : bord interne plat de la couche d'écorce (à `R`,
                     déjà inversé).

    Le caller construit ensuite ses polygones :
    - polygone bois : `wood_outer + base`
    - polygone écorce (si ep>0) : `bark_outer + bark_inner`
    """
    a, b = zone
    span = b - a
    n_steps = max(32, int(span) + 1)
    if R_inner is None:
        R_inner = R - 1.0 / scale

    wood_outer: List[Tuple[float, float]] = []
    bark_outer: List[Tuple[float, float]] = []
    for k in range(n_steps + 1):
        t = a + k * span / n_steps
        g = t % 400
        bell = bell_max_at_grade(g, contreforts)
        r_wood = R + bell
        wood_outer.append(polar_to_xy(cx, cy, scale, r_wood, g))
        if ep_cm > 0:
            bark_outer.append(polar_to_xy(cx, cy, scale, r_wood + ep_cm, g))

    base: List[Tuple[float, float]] = []
    for k in range(n_steps, -1, -1):
        t = a + k * span / n_steps
        g = t % 400
        base.append(polar_to_xy(cx, cy, scale, R_inner, g))

    out = {"wood_outer": wood_outer, "base": base}
    if ep_cm > 0:
        bark_inner: List[Tuple[float, float]] = []
        for k in range(n_steps, -1, -1):
            t = a + k * span / n_steps
            g = t % 400
            bark_inner.append(polar_to_xy(cx, cy, scale, R, g))
        out["bark_outer"] = bark_outer
        out["bark_inner"] = bark_inner
    return out


def degradation_externe_outline(deg: Any,
                                contreforts: List[Any],
                                R: float, ep_cm: float,
                                cx: float, cy: float, scale: float
                                ) -> List[Tuple[float, float]]:
    """Renvoie le polygone d'une dégradation externe : bord externe
    qui suit la surface réelle (`R + ep + bell_max(g)`) puis bord
    interne en sens inverse (à `outer - profondeur`).

    `deg` est typé `Any` (duck-typing) : on lit `grade_debut`,
    `profondeur_cm` et la méthode `largeur_grades()`. La dataclass
    `DegradationExterne` vit dans penetrometre.py.

    Renvoie une liste vide si la dégradation est dégénérée (profondeur
    nulle ou rayon nul).
    """
    if deg.profondeur_cm <= 0 or R <= 0:
        return []
    largeur = deg.largeur_grades()
    n_steps = max(16, int(largeur) + 1)
    outer_pts: List[Tuple[float, float]] = []
    inner_pts: List[Tuple[float, float]] = []
    for k in range(n_steps + 1):
        g = (deg.grade_debut + k * largeur / n_steps) % 400
        bell = bell_max_at_grade(g, contreforts)
        r_out = R + ep_cm + bell
        r_in = max(0.0, r_out - deg.profondeur_cm)
        outer_pts.append(polar_to_xy(cx, cy, scale, r_out, g))
        inner_pts.append(polar_to_xy(cx, cy, scale, r_in, g))
    return outer_pts + list(reversed(inner_pts))
