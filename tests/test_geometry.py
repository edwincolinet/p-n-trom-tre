"""Tests des helpers géométriques (interpolation, contreforts).

Couvre :
- `catmull_rom_closed` : cas dégénérés et fermeture du contour.
- `bell_max_at_grade` : profil cosinus², hors-zone, fusion par max.
- `contrefort_zones` : fusion de zones adjacentes / chevauchantes,
  wrap-around au grade 0, contrefort plein tour.
"""

from __future__ import annotations

import math
import unittest

from resistographe import (
    Contrefort,
    bell_max_at_grade,
    catmull_rom_closed,
    contrefort_zones,
)


class CatmullRomTests(unittest.TestCase):

    def test_moins_de_3_points_renvoie_la_liste_telle_quelle(self):
        self.assertEqual(catmull_rom_closed([]), [])
        self.assertEqual(catmull_rom_closed([(1.0, 2.0)]), [(1.0, 2.0)])
        self.assertEqual(catmull_rom_closed([(0.0, 0.0), (1.0, 1.0)]),
                         [(0.0, 0.0), (1.0, 1.0)])

    def test_3_points_produit_un_contour_ferme(self):
        # Triangle : on vérifie que le dernier point boucle sur le
        # premier de l'échantillonnage (fermeture explicite).
        pts = [(0.0, 0.0), (1.0, 0.0), (0.5, 1.0)]
        out = catmull_rom_closed(pts, samples_per_segment=4)
        self.assertEqual(out[0], out[-1])

    def test_passe_par_les_points_de_controle(self):
        # À k=0 sur chaque segment, t=0 → la spline vaut p1.
        # On retrouve donc les points d'entrée parmi les échantillons.
        pts = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        out = catmull_rom_closed(pts, samples_per_segment=8)
        for p in pts:
            self.assertIn(p, out)


class BellMaxAtGradeTests(unittest.TestCase):

    def test_aucun_contrefort_renvoie_zero(self):
        self.assertEqual(bell_max_at_grade(0, []), 0.0)
        self.assertEqual(bell_max_at_grade(123, []), 0.0)

    def test_au_centre_renvoie_la_longueur_totale(self):
        cf = Contrefort(grade_centre=100, largeur_grades=50, longueur_cm=10.0)
        self.assertAlmostEqual(bell_max_at_grade(100, [cf]), 10.0)

    def test_aux_extremites_renvoie_zero(self):
        # cos(±π/2)² = 0 : la cloche redescend exactement à la base.
        cf = Contrefort(grade_centre=0, largeur_grades=50, longueur_cm=10.0)
        self.assertAlmostEqual(bell_max_at_grade(25, [cf]), 0.0, places=10)
        # Wrap : grade 375 = -25 par rapport au centre 0
        self.assertAlmostEqual(bell_max_at_grade(375, [cf]), 0.0, places=10)

    def test_a_mi_chemin_renvoie_moitie_en_cosinus_carre(self):
        # À |diff| = demi/2, profil = cos(π/4)² = 0.5
        cf = Contrefort(grade_centre=0, largeur_grades=100, longueur_cm=10.0)
        # demi=50, on évalue à diff=25
        self.assertAlmostEqual(bell_max_at_grade(25, [cf]), 5.0)
        self.assertAlmostEqual(bell_max_at_grade(375, [cf]), 5.0)

    def test_hors_zone_renvoie_zero(self):
        cf = Contrefort(grade_centre=100, largeur_grades=50, longueur_cm=8.0)
        # demi=25 → hors zone dès |diff| > 25
        self.assertEqual(bell_max_at_grade(50, [cf]), 0.0)
        self.assertEqual(bell_max_at_grade(200, [cf]), 0.0)

    def test_fusion_par_max_de_deux_contreforts(self):
        # Deux contreforts qui se chevauchent : on prend la cloche qui
        # culmine le plus haut à chaque grade. C'est ce qui supprime
        # l'encoche en V à la jonction.
        cfA = Contrefort(grade_centre=100, largeur_grades=100, longueur_cm=10.0)
        cfB = Contrefort(grade_centre=120, largeur_grades=100, longueur_cm=15.0)
        # Au centre de B, B domine
        self.assertAlmostEqual(bell_max_at_grade(120, [cfA, cfB]), 15.0)
        # Au centre de A, A domine
        self.assertAlmostEqual(bell_max_at_grade(100, [cfA, cfB]), 10.0)

    def test_contrefort_degenere_ignore(self):
        cf_long_zero = Contrefort(grade_centre=0, largeur_grades=50,
                                  longueur_cm=0.0)
        cf_larg_zero = Contrefort(grade_centre=0, largeur_grades=0,
                                  longueur_cm=10.0)
        self.assertEqual(bell_max_at_grade(0, [cf_long_zero]), 0.0)
        self.assertEqual(bell_max_at_grade(0, [cf_larg_zero]), 0.0)


class ContrefortZonesTests(unittest.TestCase):

    def test_liste_vide(self):
        self.assertEqual(contrefort_zones([]), [])

    def test_contreforts_degeneres_filtres(self):
        cfs = [
            Contrefort(longueur_cm=0.0, largeur_grades=50),
            Contrefort(longueur_cm=10.0, largeur_grades=0),
        ]
        self.assertEqual(contrefort_zones(cfs), [])

    def test_contrefort_unique(self):
        cf = Contrefort(grade_centre=100, largeur_grades=50, longueur_cm=10.0)
        zones = contrefort_zones([cf])
        self.assertEqual(len(zones), 1)
        a, b = zones[0]
        self.assertAlmostEqual(a, 75.0)
        self.assertAlmostEqual(b, 125.0)

    def test_deux_contreforts_disjoints(self):
        cfs = [
            Contrefort(grade_centre=100, largeur_grades=50, longueur_cm=10.0),
            Contrefort(grade_centre=300, largeur_grades=50, longueur_cm=10.0),
        ]
        zones = contrefort_zones(cfs)
        self.assertEqual(len(zones), 2)

    def test_deux_contreforts_qui_se_touchent_fusionnent(self):
        # cf1 couvre [-25, 25], cf2 couvre [25, 75] → fusion à la
        # frontière commune.
        cfs = [
            Contrefort(grade_centre=0, largeur_grades=50, longueur_cm=10.0),
            Contrefort(grade_centre=50, largeur_grades=50, longueur_cm=10.0),
        ]
        zones = contrefort_zones(cfs)
        self.assertEqual(len(zones), 1)

    def test_deux_contreforts_qui_se_chevauchent_fusionnent(self):
        cfs = [
            Contrefort(grade_centre=100, largeur_grades=100, longueur_cm=8.0),
            Contrefort(grade_centre=150, largeur_grades=100, longueur_cm=12.0),
        ]
        zones = contrefort_zones(cfs)
        self.assertEqual(len(zones), 1)

    def test_wrap_around_au_grade_zero(self):
        # cf à 0 (grades 375..25) et cf à 25 (grades 0..50) qui se
        # touchent à 25 : doivent former une seule zone qui enjambe 0.
        cfs = [
            Contrefort(grade_centre=0, largeur_grades=50, longueur_cm=10.0),
            Contrefort(grade_centre=50, largeur_grades=50, longueur_cm=10.0),
        ]
        zones = contrefort_zones(cfs)
        self.assertEqual(len(zones), 1)
        a, b = zones[0]
        # La zone enjambe 0 : a peut être négatif.
        self.assertLess(a, b)
        self.assertGreaterEqual(b - a, 100.0 - 1e-9)

    def test_couverture_complete_normalisee(self):
        # Un contrefort qui couvre 400 grades = tout le pourtour →
        # zone normalisée [0, 400].
        cf = Contrefort(grade_centre=0, largeur_grades=400, longueur_cm=10.0)
        zones = contrefort_zones([cf])
        self.assertEqual(zones, [(0.0, 400.0)])


if __name__ == "__main__":
    unittest.main()
