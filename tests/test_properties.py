"""Tests par propriété (property-based, via hypothesis) du cœur pur.

hypothesis génère des centaines d'entrées et cherche l'invariant qui casse
— complément des tests par cas de `test_classification` / `test_geometry`.
Ciblé sur les fonctions PURES où un bug de calcul fausserait un diagnostic
de sécurité d'arbre : le barème de classification et la géométrie polaire.

Écrit en `unittest.TestCase` (décorateurs `@given` sur les méthodes) pour
être ramassé par `python -m unittest discover tests` comme le reste de la
suite (pas besoin de basculer le runner sur pytest).
"""

from __future__ import annotations

import math
import unittest

from hypothesis import given
from hypothesis import strategies as st

from bareme import (
    CLASSE_ORANGE,
    CLASSE_ROUGE,
    CLASSE_VERT,
    PORTS_ARBRE,
    SEUILS_DEFAUT,
    classer_prbs,
    set_seuils,
)
from geometry import catmull_rom_closed, ellipse_radius

# Gravité croissante d'une classe (Vert = sûr, Rouge = danger). Permet de
# comparer deux classes ordinalement.
_GRAVITE = {CLASSE_VERT: 0, CLASSE_ORANGE: 1, CLASSE_ROUGE: 2}
_PORTS = st.sampled_from(PORTS_ARBRE)


class ClasserPrbsProperties(unittest.TestCase):
    """Invariants du barème `classer_prbs`."""

    def setUp(self) -> None:
        # Les seuils sont un état de module GLOBAL (`set_seuils`). On repart
        # des défauts pour que les propriétés soient déterministes même si
        # un autre test a personnalisé les seuils avant.
        set_seuils(SEUILS_DEFAUT["libre"], SEUILS_DEFAUT["strict"])

    @given(ratio=st.floats(min_value=-1.0, max_value=2.0), port=_PORTS)
    def test_renvoie_toujours_une_classe_valide(self, ratio: float,
                                                port: str) -> None:
        self.assertIn(classer_prbs(ratio, port), _GRAVITE)

    @given(port=_PORTS, r1=st.floats(0.0, 1.0), r2=st.floats(0.0, 1.0))
    def test_monotone_plus_de_bois_sain_jamais_plus_grave(
            self, port: str, r1: float, r2: float) -> None:
        # Plus de paroi résiduelle saine (t/R plus grand) ⟹ classe JAMAIS
        # plus grave. C'est le cœur de sûreté du barème.
        lo, hi = sorted((r1, r2))
        self.assertGreaterEqual(_GRAVITE[classer_prbs(lo, port)],
                                _GRAVITE[classer_prbs(hi, port)])

    @given(ratio=st.floats(allow_nan=False, allow_infinity=False),
           port=st.text())
    def test_robuste_a_un_port_quelconque(self, ratio: float,
                                          port: str) -> None:
        # Un port inconnu (chaîne arbitraire) ne doit pas planter : la
        # fonction retombe sur le groupe « libre ».
        self.assertIn(classer_prbs(ratio, port), _GRAVITE)


class EllipseRadiusProperties(unittest.TestCase):
    """Invariants du rayon polaire d'une ellipse."""

    _AXES = st.floats(min_value=0.1, max_value=500.0)
    _GRADE = st.floats(min_value=0.0, max_value=400.0)

    @given(a=_AXES, b=_AXES, orient=_GRADE, grade=_GRADE)
    def test_rayon_entre_les_deux_demi_axes(self, a: float, b: float,
                                            orient: float,
                                            grade: float) -> None:
        r = ellipse_radius(a, b, orient, grade)
        eps = 1e-6
        self.assertGreaterEqual(r, min(a, b) - eps)
        self.assertLessEqual(r, max(a, b) + eps)
        self.assertTrue(math.isfinite(r))

    @given(a=_AXES, b=_AXES, orient=_GRADE)
    def test_rayon_egale_l_axe_visé(self, a: float, b: float,
                                    orient: float) -> None:
        # Sur le grand axe → a ; à 90° (100 gr) de là → b.
        self.assertAlmostEqual(ellipse_radius(a, b, orient, orient), a,
                               places=5)
        self.assertAlmostEqual(ellipse_radius(a, b, orient, orient + 100), b,
                               places=5)

    @given(a=st.floats(min_value=-100.0, max_value=0.0), b=_AXES,
           orient=_GRADE, grade=_GRADE)
    def test_axe_degenere_pas_de_division_par_zero(
            self, a: float, b: float, orient: float, grade: float) -> None:
        # Axe nul/négatif : renvoie l'autre (cercle), jamais de crash.
        self.assertEqual(ellipse_radius(a, b, orient, grade),
                         max(a, b, 0.0))


class CatmullRomProperties(unittest.TestCase):
    """Invariants de la spline fermée Catmull-Rom."""

    _PT = st.tuples(st.floats(-1e4, 1e4), st.floats(-1e4, 1e4))

    @given(points=st.lists(_PT, min_size=3, max_size=20),
           sps=st.integers(min_value=1, max_value=8))
    def test_longueur_finitude_et_fermeture(self, points: list,
                                            sps: int) -> None:
        out = catmull_rom_closed(points, sps)
        # n segments × sps échantillons + le point de fermeture (out[0]
        # répété en fin → courbe fermée).
        self.assertEqual(len(out), len(points) * sps + 1)
        self.assertEqual(out[-1], out[0])
        self.assertTrue(all(math.isfinite(x) and math.isfinite(y)
                            for x, y in out))

    @given(points=st.lists(_PT, max_size=2))
    def test_moins_de_3_points_renvoie_les_points(self,
                                                  points: list) -> None:
        self.assertEqual(catmull_rom_closed(points), list(points))


if __name__ == "__main__":
    unittest.main()
