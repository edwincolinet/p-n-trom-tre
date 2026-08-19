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
from geometry import GRADES, catmull_rom_closed
from model import Brin

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


class RayonAGradeProperties(unittest.TestCase):
    """Invariants du rayon local par direction (`Brin.rayon_a_grade`) :
    diamètre général + diamètres locaux mesurés à certaines directions
    (INDÉPENDANTS de tout sondage), interpolés en LISSANT (cosinus) entre
    les directions mesurées voisines — borné comme un linéaire, mais sans
    angle vif."""

    _RAYON = st.floats(min_value=0.1, max_value=500.0)
    _DIAMS = st.lists(
        st.one_of(st.just(0.0), st.floats(min_value=0.2, max_value=1000.0)),
        min_size=16, max_size=16)
    _GRADE = st.floats(min_value=0.0, max_value=400.0)

    def _build(self, rayon: float, diams: list[float]) -> Brin:
        b = Brin(rayon_tronc_cm=rayon)
        for g, d in zip(GRADES, diams):
            if d > 0:
                b.diametres_locaux[g] = d
        return b

    @given(rayon=_RAYON, diams=_DIAMS)
    def test_exact_aux_grades_canoniques(self, rayon: float,
                                         diams: list[float]) -> None:
        b = self._build(rayon, diams)
        for g, d in zip(GRADES, diams):
            attendu = d / 2.0 if d > 0 else rayon
            self.assertAlmostEqual(b.rayon_a_grade(g), attendu, places=6)

    @given(rayon=_RAYON, diams=_DIAMS, grade=_GRADE)
    def test_borne_par_les_deux_directions_voisines(
            self, rayon: float, diams: list[float], grade: float) -> None:
        b = self._build(rayon, diams)
        table = {g: (d / 2.0 if d > 0 else rayon)
                for g, d in zip(GRADES, diams)}
        g = grade % 400.0
        g_lo = (int(g // 25) * 25) % 400
        g_hi = (g_lo + 25) % 400
        lo, hi = table[g_lo], table[g_hi]
        r = b.rayon_a_grade(grade)
        eps = 1e-6
        self.assertGreaterEqual(r, min(lo, hi) - eps)
        self.assertLessEqual(r, max(lo, hi) + eps)
        self.assertTrue(math.isfinite(r))

    @given(rayon=_RAYON, grade=_GRADE)
    def test_sans_sondage_rayon_constant(self, rayon: float,
                                         grade: float) -> None:
        # Aucun diamètre local mesuré ⟹ rayon général partout (chemin
        # historique, section circulaire).
        b = Brin(rayon_tronc_cm=rayon)
        self.assertAlmostEqual(b.rayon_a_grade(grade), rayon, places=6)


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
