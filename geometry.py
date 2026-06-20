"""
Helpers géométriques purs du Pénétromètre.

Ce module ne dépend QUE de la stdlib (`math`). Il est volontairement
isolé de Tkinter, de PIL et de toute UI : il contient les briques
géométriques qui peuvent être couvertes par des tests unitaires sans
embarquer la couche graphique.

Contenu :
- `GRADES`, `DIRECTION_LABELS` : 16 directions du sondage (constantes
  métier, source unique partagée par le modèle et les exports).
- `catmull_rom_closed` : interpolation spline fermée (Catmull & Rom).
- `bell_max_at_grade`  : hauteur de cloche cosinus² maximale à un grade
  donné, sur l'ensemble des contreforts qui couvrent ce grade.
- `contrefort_zones`   : fusion des arcs angulaires couverts par des
  contreforts adjacents ou chevauchants.
- `polar_to_xy`, `polar_idx_to_xy`, `cavity_polygon`,
  `contrefort_zone_outline`, `degradation_externe_outline` :
  primitives de rendu partagées Tkinter ↔ PIL.

Le barème métier (`classer_prbs` + labels de classe + ports) vit dans
`bareme.py`. Les couleurs hexa associées aux classes vivent dans
`palette.py`.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, NamedTuple, Tuple, Union

# Un rayon peut être donné soit comme un scalaire (section circulaire,
# `rayon_tronc_cm`), soit comme une fonction `grade -> rayon_cm` (section
# ovale, `Brin.rayon_a_grade`). Les primitives de rendu partagées acceptent
# les deux : pour un scalaire le calcul est strictement identique à l'ancien
# (aucun golden touché), pour une fonction le contour suit l'ellipse.
RadiusSpec = Union[float, Callable[[float], float]]


def _radius_at(R: "RadiusSpec", grade: float) -> float:
    """Résout un `RadiusSpec` à une direction donnée (scalaire ou fonction)."""
    return R(grade) if callable(R) else R


# Recouvrement (en px) du bord externe d'une dégradation qui comprend
# l'écorce, pour souder la couture d'anti-aliasing avec le bord de l'écorce
# (deux remplissages jointifs laissent sinon ~1 px de fond visible).
_BARK_SEAM_PX = 1.0

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

# Rose des vents complète : un libellé par direction, y compris les 8
# intermédiaires en combiné ("N-NE", "NE-E", …) que `DIRECTION_LABELS`
# laisse vides. Sert aux grilles de saisie 16 directions (onglets
# Sondages et Contreforts) où chaque ligne doit se lire seule.
WIND_LABELS: Dict[int, str] = {
    0: "N", 25: "N-NE", 50: "NE", 75: "NE-E",
    100: "E", 125: "E-SE", 150: "SE", 175: "SE-S",
    200: "S", 225: "S-SO", 250: "SO", 275: "SO-O",
    300: "O", 325: "O-NO", 350: "NO", 375: "NO-N",
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


def ellipse_radius(a: float, b: float,
                   orientation_grade: float, grade: float) -> float:
    """Rayon polaire (cm) d'une ellipse dans la direction `grade`.

    `a` = demi-grand-axe, `b` = demi-petit-axe, `orientation_grade` = grade
    du grand axe (0–400). Équation polaire de l'ellipse centrée, mesurée
    depuis le centre : à `grade == orientation_grade` le rayon vaut `a`, à
    90° de là il vaut `b`.

    Robuste aux dégénérescences : si l'un des axes est nul/négatif, renvoie
    l'autre (cercle) — jamais de division par zéro.
    """
    if a <= 0 or b <= 0:
        return max(a, b, 0.0)
    phi = math.radians((grade - orientation_grade) * 360.0 / 400.0)
    ca = b * math.cos(phi)
    sa = a * math.sin(phi)
    denom = math.hypot(ca, sa)
    if denom == 0:
        return max(a, b)
    return a * b / denom


def contour_polygon(r_of: "RadiusSpec",
                    cx: float, cy: float, scale: float,
                    n_samples: int = 160,
                    rotation_grades: float = 0.0
                    ) -> List[Tuple[float, float]]:
    """Polygone fermé du contour du tronc, échantillonné finement.

    `r_of` = rayon (cm) par direction (scalaire = cercle, fonction =
    ellipse). Renvoie `n_samples` points répartis sur 400 gr ; le contour
    est implicitement fermé par les API de dessin (PIL `polygon`, Tk
    `create_polygon`). Utilisé pour le **remplissage** bois/écorce/cernes
    d'une section OVALE — le cas circulaire continue d'utiliser la
    primitive ellipse native des renderers (rendu lisse, goldens stables).

    `rotation_grades` : rotation du brin (cépée). Le rayon est évalué au grade
    LOCAL `g` mais le point est **placé** à `g + rotation_grades` → la forme
    (ellipse comprise) pivote. Défaut 0.0 ⟹ `g + 0.0 == g`, rendu byte-identique.
    """
    pts: List[Tuple[float, float]] = []
    for k in range(n_samples):
        g = k * 400.0 / n_samples
        pts.append(polar_to_xy(cx, cy, scale, _radius_at(r_of, g),
                               g + rotation_grades))
    return pts


def cavity_polygon(alteration_par_grade: List[float],
                   cx: float, cy: float, scale: float,
                   samples_per_segment: int = 28,
                   rotation_grades: float = 0.0
                   ) -> List[Tuple[float, float]]:
    """Renvoie le polygone lissé de la cavité d'altération (Catmull-
    Rom fermée passant par les 16 points sondés/extrapolés).

    `alteration_par_grade` est la liste de 16 épaisseurs d'altération
    en cm (le résultat de `Arbre.compute_alteration_par_grade()`).

    `rotation_grades` : rotation du brin (cépée) — chaque point est placé au
    grade `i*25 + rotation_grades`. Défaut 0.0 ⟹ chemin `polar_idx_to_xy`
    historique (byte-identique aux goldens).
    """
    if rotation_grades:
        pts = [polar_to_xy(cx, cy, scale, max(0.0, alteration_par_grade[i]),
                           i * 25.0 + rotation_grades)
               for i in range(16)]
    else:
        pts = [polar_idx_to_xy(cx, cy, scale,
                               max(0.0, alteration_par_grade[i]), i)
               for i in range(16)]
    return catmull_rom_closed(pts, samples_per_segment)


def contrefort_zone_outline(zone: Tuple[float, float],
                            contreforts: List[Any],
                            R: "RadiusSpec", ep_cm: float,
                            cx: float, cy: float, scale: float,
                            R_inner: Any = None,
                            rotation_grades: float = 0.0
                            ) -> Dict[str, List[Tuple[float, float]]]:
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

    wood_outer: List[Tuple[float, float]] = []
    bark_outer: List[Tuple[float, float]] = []
    for k in range(n_steps + 1):
        t = a + k * span / n_steps
        g = t % 400
        bell = bell_max_at_grade(g, contreforts)
        r_wood = _radius_at(R, g) + bell
        wood_outer.append(polar_to_xy(cx, cy, scale, r_wood,
                                      g + rotation_grades))
        if ep_cm > 0:
            bark_outer.append(polar_to_xy(cx, cy, scale, r_wood + ep_cm,
                                          g + rotation_grades))

    base: List[Tuple[float, float]] = []
    for k in range(n_steps, -1, -1):
        t = a + k * span / n_steps
        g = t % 400
        # Bord interne du polygone : légèrement en-deçà du rayon LOCAL pour
        # masquer la couture (R_inner explicite l'emporte si fourni).
        r_in = (_radius_at(R_inner, g) if R_inner is not None
                else _radius_at(R, g) - 1.0 / scale)
        base.append(polar_to_xy(cx, cy, scale, r_in, g + rotation_grades))

    out = {"wood_outer": wood_outer, "base": base}
    if ep_cm > 0:
        bark_inner: List[Tuple[float, float]] = []
        for k in range(n_steps, -1, -1):
            t = a + k * span / n_steps
            g = t % 400
            bark_inner.append(polar_to_xy(cx, cy, scale, _radius_at(R, g),
                                          g + rotation_grades))
        out["bark_outer"] = bark_outer
        out["bark_inner"] = bark_inner
    return out


def degradation_externe_outline(deg: Any,
                                contreforts: List[Any],
                                R: "RadiusSpec", ep_cm: float,
                                cx: float, cy: float, scale: float,
                                rotation_grades: float = 0.0
                                ) -> List[Tuple[float, float]]:
    """Renvoie le polygone d'une dégradation externe : bord externe
    puis bord interne en sens inverse (à `outer - profondeur`).

    La dégradation suit **toujours** la saillie des contreforts (cloche
    `bell_max(g)`, qui fait gonfler la surface du bois). Le drapeau
    `comprend_ecorce` (défaut True) décide seulement du départ radial :
    - comprend l'écorce → part de la surface extérieure `R + bell + ep`
      (l'écorce est visuellement dégradée) ;
    - commence sous l'écorce → part de la surface du bois `R + bell`
      (écorce laissée intacte).

    Dans les **deux** cas, le bord externe est prolongé d'un léger
    recouvrement (`_BARK_SEAM_PX`) vers l'extérieur : deux remplissages
    jointifs (dégradation / écorce, ou dégradation / bord de l'écorce)
    laissent sinon une couture d'~1 px d'anti-aliasing (un liseré de bois
    ou de fond visible entre les deux). Le recouvrement ne déborde que
    vers l'extérieur — il ne change pas la profondeur creusée.

    `deg` est typé `Any` (duck-typing) : on lit `grade_debut`,
    `profondeur_cm`, `comprend_ecorce` et la méthode `largeur_grades()`.

    Renvoie une liste vide si la dégradation est dégénérée (profondeur
    nulle ou rayon nul).
    """
    if deg.profondeur_cm <= 0 or _radius_at(R, deg.grade_debut) <= 0:
        return []
    comprend_ecorce = getattr(deg, "comprend_ecorce", True)
    # Recouvrement anti-couture, exprimé en cm (constant ~1 px à l'écran).
    seam_cm = (_BARK_SEAM_PX / scale) if scale > 0 else 0.0
    largeur = deg.largeur_grades()
    n_steps = max(16, int(largeur) + 1)
    outer_pts: List[Tuple[float, float]] = []
    inner_pts: List[Tuple[float, float]] = []
    for k in range(n_steps + 1):
        g = (deg.grade_debut + k * largeur / n_steps) % 400
        # Surface du bois (suit la saillie des contreforts), puis écorce.
        r_surface = _radius_at(R, g) + bell_max_at_grade(g, contreforts)
        if comprend_ecorce:
            r_surface += ep_cm
        # Profondeur creusée depuis la surface réelle ; le recouvrement ne
        # déborde que vers l'extérieur (ne change pas la profondeur creusée).
        r_in = max(0.0, r_surface - deg.profondeur_cm)
        r_out = r_surface + seam_cm
        outer_pts.append(polar_to_xy(cx, cy, scale, r_out, g + rotation_grades))
        inner_pts.append(polar_to_xy(cx, cy, scale, r_in, g + rotation_grades))
    return outer_pts + list(reversed(inner_pts))


# ----------------------------------------------------------------------
# Règle graduée — pas adaptatif (présentation, partagé Tk ↔ PIL)
# ----------------------------------------------------------------------

def adaptive_ruler_step_cm(scale_px_per_cm: float,
                           min_gap_px: float) -> int:
    """Pas de graduation (en cm) tel que deux étiquettes consécutives
    soient séparées d'au moins `min_gap_px` pixels.

    On choisit dans la suite 1, 2, 5, 10, 20, 50, 100 — multiples
    « naturels » pour qu'un œil humain reconnaisse vite la grille. Le
    seuil `min_gap_px` dépend de la taille de la police du renderer
    (Tk : police petite → ≈ 24 px ; PIL : police grande → ≈ 50 px).
    """
    for step in (1, 2, 5, 10, 20, 50, 100):
        if step * scale_px_per_cm >= min_gap_px:
            return step
    return 100


def radial_ruler_grade(sondage_grades: List[int],
                       rotation_grades: float = 0.0) -> float:
    """Grade MONDE de l'échelle radiale d'un brin (esquive des sondages).

    L'échelle se pose à l'Est (100 gr) par défaut. Si un sondage est
    **rendu** dans cette direction (grade local + rotation du brin), elle
    bascule sur la direction libre la plus proche, en alternant de part et
    d'autre de l'Est (125, 75, 150, 50, …) — déterministe pour un jeu de
    sondages donné. Si les 16 directions sont toutes sondées, renvoie
    100.0 : l'échelle est alors dessinée par-dessus la flèche Est, son
    halo blanc la garde lisible (la pastille au bord reste visible).
    """
    occupied = {round((g + rotation_grades) % 400.0, 6)
                for g in sondage_grades}
    for k in range(16):
        delta = ((k + 1) // 2) * 25
        g = (100 + delta) % 400 if k % 2 == 1 else (100 - delta) % 400
        if round(float(g), 6) not in occupied:
            return float(g)
    return 100.0


class RadialRulerData(NamedTuple):
    """Géométrie (px écran) de l'échelle radiale d'un brin."""
    axis: Tuple[Tuple[float, float], Tuple[float, float]]   # centre → bois
    bark: Union[Tuple[Tuple[float, float], Tuple[float, float]], None]
    ticks: List[Tuple[float, float, float, float, float, float, str]]


def radial_ruler_data(cx: float, cy: float, scale: float,
                      R: float, ep: float, grade: float, step_cm: int,
                      tick_len_px: float, label_offset_px: float,
                      min_gap_px: float = 0.0,
                      ) -> Union[RadialRulerData, None]:
    """Géométrie de l'échelle radiale centre→écorce le long de `grade`.

    Échelle **asymétrique** propre à un brin : axe du centre (0) au bord
    du bois (R, rayon local de la direction), prolongé d'un segment
    d'écorce jusqu'à R+ep si `ep > 0`. Tirets perpendiculaires étiquetés :
    « 0 » au centre, multiples de `step_cm`, et le terminal au **bout de
    l'écorce** avec l'étiquette « R+ep cm ». Si aucun multiple ne tient
    (petit brin / pas trop grand), une graduation **médiane** est ajoutée —
    l'échelle garde toujours au moins un segment intermédiaire lisible.
    Les étiquettes sont décalées de `label_offset_px` du côté `grade + 100`
    (sous l'axe quand l'échelle est à l'Est).

    `ticks` = `[(x1, y1, x2, y2, lx, ly, label), ...]` : segment du tiret
    (centré sur l'axe, longueur totale `tick_len_px`) + position de son
    étiquette. Renvoie `None` si `R <= 0`.
    """
    if R <= 0:
        return None
    r_ext = R + max(0.0, ep)
    a = math.radians(grade * 360.0 / 400.0 - 90.0)
    ux, uy = math.cos(a), math.sin(a)        # le long de l'axe
    vx, vy = -uy, ux                          # perpendiculaire (grade+100)
    p0 = (cx, cy)
    p_r = (cx + ux * R * scale, cy + uy * R * scale)
    bark = None
    if ep > 0:
        p_ext = (cx + ux * r_ext * scale, cy + uy * r_ext * scale)
        bark = (p_r, p_ext)
    ticks: List[Tuple[float, float, float, float, float, float, str]] = []
    half = tick_len_px / 2.0
    radii: List[Tuple[float, str]] = [(0.0, "0")]
    inter: List[Tuple[float, str]] = []
    if step_cm > 0:
        # Tirets intermédiaires ; on omet ceux à moins d'un pas entier du
        # terminal — son étiquette « N cm » est large, un tiret trop proche
        # la télescoperait (ex. R=16, pas 10 : « 10 » collerait « 16 cm »).
        # Si min_gap_px est fourni, on vérifie aussi que l'espacement
        # en pixels vers « 0 » ET vers le terminal est suffisant.
        inter = [(float(r), str(r))
                 for r in range(step_cm, int(r_ext), step_cm)
                 if r_ext - r >= step_cm]
    if not inter:
        # Au moins UN segment intermédiaire : graduation médiane arrondie
        # au cm (petit brin de cépée où le pas adaptatif ne tient pas).
        mid = round(r_ext / 2.0)
        if 0 < mid < r_ext:
            inter = [(float(mid), f"{mid:g}")]
    radii.extend(inter)
    # Étiquette terminale arrondie au mm : le rayon d'une ellipse évalué à
    # l'angle d'esquive peut produire des décimales parasites (16.1275…).
    radii.append((r_ext, f"{round(r_ext, 1):g} cm"))
    for r, label in radii:
        px = cx + ux * r * scale
        py = cy + uy * r * scale
        ticks.append((px - vx * half, py - vy * half,
                      px + vx * half, py + vy * half,
                      px + vx * label_offset_px, py + vy * label_offset_px,
                      label))
    return RadialRulerData(axis=(p0, p_r), bark=bark, ticks=ticks)


# ----------------------------------------------------------------------
# Positions partagées Tk ↔ PIL : ticks, lettres cardinales, graduations
# ----------------------------------------------------------------------
#
# Les renderers Tk et PIL itèrent sur les 16 grades pour dessiner les
# mêmes éléments hors-tronc (tirets de graduation, lettres cardinales,
# règle). Les helpers ci-dessous centralisent les calculs de POSITION
# (en pixels écran), pour qu'une seule source soit modifiée si la règle
# évolue (par ex. quel grade est « majeur »). Les appels de dessin
# eux-mêmes (`create_line` / `d.line`) restent dans chaque renderer.

def tick_endpoints(cx: float, cy: float, scale: float,
                   R_ext: "RadiusSpec", tick_len_cm: float
                   ) -> List[Tuple[float, float, float, float, bool]]:
    """Positions des 16 tirets de graduation autour du tronc.

    Renvoie `[(x1, y1, x2, y2, is_major), ...]` : segment du tick et
    si c'est un tick majeur (grade multiple de 50). Le renderer choisit
    couleur/épaisseur selon `is_major`. `R_ext` peut être un scalaire
    (cercle) ou une fonction `grade->rayon` (ellipse) : les tirets se
    posent alors sur le contour local.
    """
    out: List[Tuple[float, float, float, float, bool]] = []
    for i, g in enumerate(GRADES):
        rext = _radius_at(R_ext, g)
        x1, y1 = polar_idx_to_xy(cx, cy, scale, rext, i)
        x2, y2 = polar_idx_to_xy(cx, cy, scale, rext + tick_len_cm, i)
        out.append((x1, y1, x2, y2, g % 50 == 0))
    return out


def cardinal_label_positions(cx: float, cy: float, scale: float,
                              R_ext: "RadiusSpec", offset_cm: float
                              ) -> List[Tuple[float, float, str]]:
    """Positions des lettres cardinales (N, NE, E, …) autour du tronc.

    Renvoie `[(x, y, label), ...]` : ne contient QUE les grades qui ont
    un libellé non vide (les inter-quadrants 25/75/125/… sont absents).
    `R_ext` scalaire (cercle) ou fonction `grade->rayon` (ellipse).
    """
    out: List[Tuple[float, float, str]] = []
    for i, g in enumerate(GRADES):
        lbl = DIRECTION_LABELS.get(g, "")
        if not lbl:
            continue
        lx, ly = polar_idx_to_xy(cx, cy, scale, _radius_at(R_ext, g) + offset_cm, i)
        out.append((lx, ly, lbl))
    return out


def cerne_radii_px(R: float, scale: float, n_cernes: int) -> List[float]:
    """Rayons en pixels des N cernes concentriques à l'intérieur du tronc.

    Régulièrement espacés entre le centre et R (exclus). Partagé entre
    les deux renderers (Tk et PIL) pour éviter de dupliquer le calcul.
    """
    radius_px = R * scale
    if radius_px <= 0 or n_cernes <= 0:
        return []
    return [radius_px * k / (n_cernes + 1) for k in range(1, n_cernes + 1)]


def brins_layout(positions_extents: List[Tuple[float, float, float]],
                 width: float, height: float,
                 margin_top: float, margin_bottom: float,
                 margin_side: float) -> Tuple[float, float, float]:
    """Cadrage global d'une cépée : place N brins dans la zone de dessin.

    `positions_extents` = `[(pos_x_cm, pos_y_cm, extent_cm), ...]` pour chaque
    brin (`extent_cm` = rayon d'encombrement, cf. `Brin.extent_cm`). Renvoie
    `(scale, origin_x, origin_y)` :

    - `scale` = facteur px/cm commun à tous les brins ;
    - `(origin_x, origin_y)` = position écran (px) de l'origine du repère cm
      (le cœur du brin[0], en (0, 0) cm).

    La position écran d'un point cm `(X, Y)` est alors
    `(origin_x + X * scale, origin_y + Y * scale)` (x → Est, y → Sud).

    Cadrage **top-aligné, centré horizontalement** : c'est le placement
    historique mono-brin (haut de la section à `margin_top`, section centrée
    en largeur). Pour un brin unique centré, il reproduit donc l'ancien cadre.
    Le `scale` mono-brin n'est PAS recalculé via ce helper (l'ordre des
    divisions diffère, au risque d'un écart d'un ULP) : les orchestrateurs
    gardent leur arithmétique mono-brin dédiée et n'appellent ce helper que
    pour une vraie cépée.
    """
    if not positions_extents:
        return 1.0, width / 2.0, margin_top
    x0 = min(px - e for px, _py, e in positions_extents)
    x1 = max(px + e for px, _py, e in positions_extents)
    y0 = min(py - e for _px, py, e in positions_extents)
    y1 = max(py + e for _px, py, e in positions_extents)
    width_cm = x1 - x0
    height_cm = y1 - y0
    available_h = max(1.0, width - 2.0 * margin_side)
    available_v = max(1.0, height - margin_top - margin_bottom)
    if width_cm <= 0 or height_cm <= 0:
        return 1.0, width / 2.0, margin_top
    scale = min(available_h / width_cm, available_v / height_cm)
    # Centrage horizontal de la bbox, top-alignement vertical.
    bbox_center_x = (x0 + x1) / 2.0
    origin_x = width / 2.0 - bbox_center_x * scale
    origin_y = margin_top - y0 * scale
    return scale, origin_x, origin_y
