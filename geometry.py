"""
Helpers géométriques et logique de classification du Pénétromètre.

Ce module ne dépend QUE de la stdlib (`math`). Il est volontairement
isolé de Tkinter, de PIL et de toute UI : il contient les briques pures
qui peuvent être couvertes par des tests unitaires sans embarquer la
couche graphique.

Contenu :
- `catmull_rom_closed` : interpolation spline fermée (Catmull & Rom).
- `bell_max_at_grade`  : hauteur de cloche cosinus² maximale à un grade
  donné, sur l'ensemble des contreforts qui couvrent ce grade.
- `contrefort_zones`   : fusion des arcs angulaires couverts par des
  contreforts adjacents ou chevauchants.
- `classer_prbs`       : barème Silvavenir (label Vert/Orange/Rouge
  selon le ratio t/R et le port de l'arbre).

Les couleurs hexa associées aux classes ne sont PAS définies ici : ce
sont des conventions de présentation qui vivent côté UI dans
`resistographe.py` (`COULEUR_CLASSE`).
"""

from __future__ import annotations

import math
from typing import Any, List, Tuple


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
# vit dans `resistographe.py` (avec le reste du modèle) et l'importer
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
# `COULEUR_CLASSE` (dans resistographe.py).
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
