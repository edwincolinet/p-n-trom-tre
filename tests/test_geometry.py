"""Tests des helpers géométriques (interpolation, contreforts).

Couvre :
- `catmull_rom_closed` : cas dégénérés et fermeture du contour.
- `bell_max_at_grade` : profil cosinus², hors-zone, fusion par max.
- `contrefort_zones` : fusion de zones adjacentes / chevauchantes,
  wrap-around au grade 0, contrefort plein tour.
"""

from __future__ import annotations

import unittest

from geometry import (
    bell_max_at_grade,
    cardinal_label_positions,
    catmull_rom_closed,
    cavity_polygon,
    contrefort_zone_outline,
    contrefort_zones,
    degradation_externe_outline,
    polar_idx_to_xy,
    polar_to_xy,
    ruler_graduation_positions,
    tick_endpoints,
)
from model import Contrefort, DegradationExterne


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


class PolarConversionsTests(unittest.TestCase):

    CX, CY, SCALE = 100.0, 100.0, 10.0  # 10 px/cm

    def test_grade_zero_pointe_au_nord(self):
        # Grade 0 = Nord = au-dessus du centre (y plus petit en écran).
        x, y = polar_to_xy(self.CX, self.CY, self.SCALE, r_cm=5.0, grade=0)
        self.assertAlmostEqual(x, self.CX)
        self.assertAlmostEqual(y, self.CY - 5.0 * self.SCALE)

    def test_grade_100_pointe_a_l_est(self):
        # 100 gr = E = à droite du centre.
        x, y = polar_to_xy(self.CX, self.CY, self.SCALE, r_cm=5.0, grade=100)
        self.assertAlmostEqual(x, self.CX + 5.0 * self.SCALE)
        self.assertAlmostEqual(y, self.CY, places=6)

    def test_grade_200_pointe_au_sud(self):
        x, y = polar_to_xy(self.CX, self.CY, self.SCALE, r_cm=5.0, grade=200)
        self.assertAlmostEqual(x, self.CX, places=6)
        self.assertAlmostEqual(y, self.CY + 5.0 * self.SCALE)

    def test_polar_idx_equivalent_a_polar_grade(self):
        # idx i correspond à grade = i * 25.
        for i in range(16):
            with self.subTest(idx=i):
                a = polar_idx_to_xy(self.CX, self.CY, self.SCALE, 7.0, i)
                b = polar_to_xy(self.CX, self.CY, self.SCALE, 7.0, i * 25)
                self.assertAlmostEqual(a[0], b[0], places=6)
                self.assertAlmostEqual(a[1], b[1], places=6)

    def test_rayon_zero_donne_le_centre(self):
        for grade in (0, 50, 100, 250):
            with self.subTest(grade=grade):
                x, y = polar_to_xy(self.CX, self.CY, self.SCALE, 0, grade)
                self.assertAlmostEqual(x, self.CX, places=6)
                self.assertAlmostEqual(y, self.CY, places=6)


class CavityPolygonTests(unittest.TestCase):

    def test_aucune_alteration_centre_partout(self):
        # Toutes les altérations à 0 : tous les points convergent au centre.
        alt = [0.0] * 16
        pts = cavity_polygon(alt, cx=50, cy=50, scale=10,
                              samples_per_segment=4)
        for x, y in pts:
            self.assertAlmostEqual(x, 50, places=6)
            self.assertAlmostEqual(y, 50, places=6)

    def test_renvoie_un_polygone_ferme(self):
        alt = [3.0, 5.0, 4.0, 3.5, 6.0, 4.0, 3.0, 5.0,
               4.5, 3.0, 4.0, 5.0, 3.5, 4.5, 3.0, 5.0]
        pts = cavity_polygon(alt, cx=0, cy=0, scale=1)
        # Catmull-Rom fermée : premier point == dernier point
        self.assertEqual(pts[0], pts[-1])
        # Beaucoup d'échantillons (16 segments × samples_per_segment + 1)
        self.assertGreater(len(pts), 16)


class ContrefortZoneOutlineTests(unittest.TestCase):

    def test_sans_ecorce_renvoie_seulement_wood_et_base(self):
        cf = Contrefort(grade_centre=100, largeur_grades=50, longueur_cm=10.0)
        zone = contrefort_zones([cf])[0]
        out = contrefort_zone_outline(zone, [cf], R=20.0, ep_cm=0.0,
                                       cx=0, cy=0, scale=1)
        self.assertEqual(set(out.keys()), {"wood_outer", "base"})
        self.assertEqual(len(out["wood_outer"]), len(out["base"]))

    def test_avec_ecorce_renvoie_les_4_listes(self):
        cf = Contrefort(grade_centre=100, largeur_grades=50, longueur_cm=10.0)
        zone = contrefort_zones([cf])[0]
        out = contrefort_zone_outline(zone, [cf], R=20.0, ep_cm=2.0,
                                       cx=0, cy=0, scale=1)
        self.assertEqual(set(out.keys()),
                         {"wood_outer", "base", "bark_outer", "bark_inner"})
        # Toutes les listes ont la même longueur (échantillonnage cohérent)
        n = len(out["wood_outer"])
        self.assertEqual(len(out["base"]), n)
        self.assertEqual(len(out["bark_outer"]), n)
        self.assertEqual(len(out["bark_inner"]), n)


class DegradationExterneOutlineTests(unittest.TestCase):

    def test_profondeur_zero_renvoie_liste_vide(self):
        deg = DegradationExterne(grade_debut=0, grade_fin=100,
                                  profondeur_cm=0.0)
        pts = degradation_externe_outline(deg, [], R=20.0, ep_cm=0.0,
                                            cx=0, cy=0, scale=1)
        self.assertEqual(pts, [])

    def test_rayon_zero_renvoie_liste_vide(self):
        deg = DegradationExterne(grade_debut=0, grade_fin=100,
                                  profondeur_cm=2.0)
        pts = degradation_externe_outline(deg, [], R=0.0, ep_cm=0.0,
                                            cx=0, cy=0, scale=1)
        self.assertEqual(pts, [])

    def test_polygone_pair_outer_plus_inner(self):
        # Le polygone est outer + reversed(inner), donc taille paire.
        deg = DegradationExterne(grade_debut=50, grade_fin=100,
                                  profondeur_cm=2.0)
        pts = degradation_externe_outline(deg, [], R=20.0, ep_cm=0.0,
                                            cx=0, cy=0, scale=1)
        self.assertGreater(len(pts), 0)
        self.assertEqual(len(pts) % 2, 0)


class TickEndpointsTests(unittest.TestCase):

    def test_renvoie_16_tirets(self):
        ticks = tick_endpoints(cx=100, cy=100, scale=10,
                                R_ext=10.0, tick_len_cm=1.0)
        self.assertEqual(len(ticks), 16)

    def test_majeurs_aux_multiples_de_50_grades(self):
        # 8 grades majeurs : 0, 50, 100, 150, 200, 250, 300, 350.
        ticks = tick_endpoints(cx=0, cy=0, scale=1, R_ext=10, tick_len_cm=1)
        majors = [t for t in ticks if t[4]]
        self.assertEqual(len(majors), 8)

    def test_premier_tick_pointe_vers_le_nord(self):
        # Grade 0 = Nord = (cx, cy - r * scale).
        ticks = tick_endpoints(cx=100, cy=100, scale=10,
                                R_ext=5.0, tick_len_cm=1.0)
        x1, y1, x2, y2, major = ticks[0]
        self.assertAlmostEqual(x1, 100.0)
        self.assertAlmostEqual(y1, 100 - 5 * 10)         # R_ext
        self.assertAlmostEqual(x2, 100.0)
        self.assertAlmostEqual(y2, 100 - 6 * 10)         # R_ext + tick
        self.assertTrue(major)


class CardinalLabelPositionsTests(unittest.TestCase):

    def test_8_lettres_seulement(self):
        # N, NE, E, SE, S, SO, O, NO — pas d'inter-quadrants.
        pos = cardinal_label_positions(cx=0, cy=0, scale=1,
                                        R_ext=10, offset_cm=1)
        self.assertEqual(len(pos), 8)
        labels = [lbl for _, _, lbl in pos]
        self.assertEqual(labels, ["N", "NE", "E", "SE",
                                   "S", "SO", "O", "NO"])

    def test_label_N_au_dessus_du_centre(self):
        pos = cardinal_label_positions(cx=200, cy=200, scale=10,
                                        R_ext=8.0, offset_cm=2.0)
        x_n, y_n, lbl = pos[0]
        self.assertEqual(lbl, "N")
        self.assertAlmostEqual(x_n, 200.0)
        # y = cy - (R_ext + offset) * scale = 200 - 100
        self.assertAlmostEqual(y_n, 100.0)


class RulerGraduationPositionsTests(unittest.TestCase):

    def test_renvoie_liste_vide_si_R_zero(self):
        self.assertEqual(
            ruler_graduation_positions(cx=0, scale=1, R=0, step_cm=5),
            [])

    def test_renvoie_liste_vide_si_step_zero(self):
        self.assertEqual(
            ruler_graduation_positions(cx=0, scale=1, R=20, step_cm=0),
            [])

    def test_exclut_le_centre_et_le_bord(self):
        # R=20, step=5 → graduations à 5, 10, 15 (pas 0, pas 20).
        pos = ruler_graduation_positions(cx=100, scale=10,
                                          R=20, step_cm=5)
        labels = [lbl for _, lbl in pos]
        self.assertEqual(labels, ["5", "10", "15"])

    def test_positions_x_en_pixels(self):
        # cx=100, scale=10, step=5 → x = 100+50, 100+100, 100+150.
        pos = ruler_graduation_positions(cx=100, scale=10,
                                          R=20, step_cm=5)
        xs = [x for x, _ in pos]
        self.assertEqual(xs, [150.0, 200.0, 250.0])


if __name__ == "__main__":
    unittest.main()
