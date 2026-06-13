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
    brins_layout,
    cardinal_label_positions,
    catmull_rom_closed,
    cavity_polygon,
    contour_polygon,
    contrefort_zone_outline,
    contrefort_zones,
    degradation_externe_outline,
    ellipse_radius,
    polar_idx_to_xy,
    polar_to_xy,
    radial_ruler_data,
    radial_ruler_grade,
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
        cfB = Contrefort(grade_centre=125, largeur_grades=100, longueur_cm=15.0)
        # Au centre de B, B domine
        self.assertAlmostEqual(bell_max_at_grade(125, [cfA, cfB]), 15.0)
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


class RotationBrinTests(unittest.TestCase):
    """Rotation d'un brin (cépée) appliquée au rendu : décale l'angle de
    PLACEMENT tout en évaluant le rayon au grade local."""

    CX, CY, SCALE = 100.0, 100.0, 10.0

    def test_contour_rotation_zero_inchange(self):
        # rotation_grades=0.0 (défaut) ⟹ `g + 0.0 == g` → byte-identique.
        base = contour_polygon(5.0, self.CX, self.CY, self.SCALE)
        same = contour_polygon(5.0, self.CX, self.CY, self.SCALE,
                               rotation_grades=0.0)
        self.assertEqual(base, same)

    def test_contour_rotation_decale_le_placement(self):
        # 1er point d'un contour circulaire : g=0 (Nord) sans rotation ;
        # placé à l'Est (100 gr) avec rotation_grades=100.
        nord = contour_polygon(5.0, self.CX, self.CY, self.SCALE)[0]
        self.assertAlmostEqual(nord[0], self.CX, places=6)
        self.assertAlmostEqual(nord[1], self.CY - 5.0 * self.SCALE, places=6)
        est = contour_polygon(5.0, self.CX, self.CY, self.SCALE,
                              rotation_grades=100)[0]
        self.assertAlmostEqual(est[0], self.CX + 5.0 * self.SCALE, places=6)
        self.assertAlmostEqual(est[1], self.CY, places=6)

    def test_contour_ovale_rotation_place_le_grand_axe(self):
        # Ellipse grand axe (a=8) orienté à 0 gr (Nord-Sud). Le 1er point
        # échantillonné (g=0) est sur le grand axe, au rayon a=8. Sans
        # rotation il pointe Nord ; pivoté de 100 gr, il pointe Est, toujours
        # au rayon a (le rayon reste évalué au grade LOCAL g=0).
        a, b = 8.0, 4.0
        r_of = lambda g: ellipse_radius(a, b, 0, g)  # noqa: E731
        est = contour_polygon(r_of, self.CX, self.CY, self.SCALE,
                              rotation_grades=100)[0]
        self.assertAlmostEqual(est[0], self.CX + a * self.SCALE, places=6)
        self.assertAlmostEqual(est[1], self.CY, places=6)

    def test_cavity_rotation_zero_identique_au_chemin_indexe(self):
        alt = [3.0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        base = cavity_polygon(alt, self.CX, self.CY, self.SCALE)
        same = cavity_polygon(alt, self.CX, self.CY, self.SCALE,
                              rotation_grades=0.0)
        self.assertEqual(base, same)


class EllipseRadiusTests(unittest.TestCase):

    def test_cercle_quand_axes_egaux(self):
        # a == b → rayon constant (cercle) quelle que soit la direction.
        for g in (0, 50, 137, 300, 375):
            with self.subTest(grade=g):
                self.assertAlmostEqual(ellipse_radius(20.0, 20.0, 0, g), 20.0)

    def test_rayon_vaut_a_le_long_du_grand_axe(self):
        # Sur l'orientation du grand axe (et à 200 gr = même droite),
        # le rayon vaut le demi-grand-axe a.
        self.assertAlmostEqual(ellipse_radius(30.0, 18.0, 0, 0), 30.0)
        self.assertAlmostEqual(ellipse_radius(30.0, 18.0, 0, 200), 30.0)

    def test_rayon_vaut_b_perpendiculairement(self):
        # À 100 gr (90°) du grand axe orienté à 0 : demi-petit-axe b.
        self.assertAlmostEqual(ellipse_radius(30.0, 18.0, 0, 100), 18.0)
        self.assertAlmostEqual(ellipse_radius(30.0, 18.0, 0, 300), 18.0)

    def test_orientation_decale_le_grand_axe(self):
        # Grand axe orienté à 50 gr : rayon = a à 50 gr, = b à 150 gr.
        self.assertAlmostEqual(ellipse_radius(30.0, 18.0, 50, 50), 30.0)
        self.assertAlmostEqual(ellipse_radius(30.0, 18.0, 50, 150), 18.0)

    def test_rayon_intermediaire_borne_par_les_axes(self):
        # À 45° le rayon est strictement entre b et a.
        r = ellipse_radius(30.0, 18.0, 0, 50)
        self.assertTrue(18.0 < r < 30.0)

    def test_axe_degenere_renvoie_l_autre(self):
        # Un axe nul ne doit jamais diviser par zéro.
        self.assertAlmostEqual(ellipse_radius(30.0, 0.0, 0, 137), 30.0)
        self.assertAlmostEqual(ellipse_radius(0.0, 0.0, 0, 0), 0.0)


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

    def test_comprend_ecorce_part_de_la_surface_exterieure(self):
        # Au grade 0 (Nord), le 1er point externe est à (0, -r_out).
        # Comprend l'écorce (défaut) → r_out = R + ep (+ recouvrement
        # anti-couture ~1 px, scale=1 ici). On vérifie qu'il atteint AU
        # MOINS la surface extérieure R+ep = 22.
        deg = DegradationExterne(grade_debut=0, grade_fin=100,
                                  profondeur_cm=2.0)
        pts = degradation_externe_outline(deg, [], R=20.0, ep_cm=2.0,
                                            cx=0, cy=0, scale=1)
        self.assertLessEqual(pts[0][1], -22.0)

    def test_sous_ecorce_part_de_la_surface_du_bois(self):
        # Commence sous l'écorce → r_out ≈ R (surface du bois, + léger
        # recouvrement anti-couture) ; SANS l'épaisseur d'écorce, donc le
        # bord externe reste en deçà de R+ep = 22.
        deg = DegradationExterne(grade_debut=0, grade_fin=100,
                                  profondeur_cm=2.0, comprend_ecorce=False)
        pts = degradation_externe_outline(deg, [], R=20.0, ep_cm=2.0,
                                            cx=0, cy=0, scale=1)
        self.assertLessEqual(pts[0][1], -20.0)   # atteint au moins R
        self.assertGreater(pts[0][1], -22.0)     # mais pas l'écorce (R+ep)

    def test_suit_les_contreforts_dans_les_deux_modes(self):
        # La dégradation suit la saillie du contrefort (bell) que l'écorce
        # soit comprise ou non : le bord externe est plus loin du centre
        # avec contrefort que sans.
        from model import Contrefort
        cf = [Contrefort(grade_centre=0, largeur_grades=50, longueur_cm=5.0)]
        for comprend in (True, False):
            deg = DegradationExterne(grade_debut=0, grade_fin=50,
                                      profondeur_cm=2.0,
                                      comprend_ecorce=comprend)
            sans = degradation_externe_outline(deg, [], R=20.0, ep_cm=1.0,
                                                cx=0, cy=0, scale=1)
            avec = degradation_externe_outline(deg, cf, R=20.0, ep_cm=1.0,
                                                cx=0, cy=0, scale=1)
            with self.subTest(comprend=comprend):
                # Point externe au Nord (grade 0) : plus négatif (plus loin)
                # avec le contrefort.
                self.assertLess(avec[0][1], sans[0][1])


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


class RadialRulerGradeTests(unittest.TestCase):
    """Esquive de l'échelle radiale (`radial_ruler_grade`)."""

    def test_est_par_defaut_sans_sondage(self):
        self.assertEqual(radial_ruler_grade([]), 100.0)

    def test_est_si_sondages_ailleurs(self):
        self.assertEqual(radial_ruler_grade([0, 200, 300]), 100.0)

    def test_esquive_un_sondage_a_l_est(self):
        # Est occupé → bascule sur 125 (côté sud d'abord).
        self.assertEqual(radial_ruler_grade([100]), 125.0)

    def test_esquive_en_alternant_de_part_et_d_autre(self):
        # 100 et 125 occupés → 75 ; puis 150 ; etc.
        self.assertEqual(radial_ruler_grade([100, 125]), 75.0)
        self.assertEqual(radial_ruler_grade([100, 125, 75]), 150.0)

    def test_rotation_du_brin_prise_en_compte(self):
        # Sondage local 75 + rotation 25 → rendu à 100 (Est) → esquive.
        self.assertEqual(radial_ruler_grade([75], rotation_grades=25.0),
                         125.0)
        # Sondage local 100 + rotation 25 → rendu à 125 → Est libre.
        self.assertEqual(radial_ruler_grade([100], rotation_grades=25.0),
                         100.0)

    def test_seize_directions_sondees_retombe_sur_est(self):
        self.assertEqual(radial_ruler_grade(list(range(0, 400, 25))), 100.0)


class RadialRulerDataTests(unittest.TestCase):
    """Géométrie de l'échelle radiale (`radial_ruler_data`)."""

    def test_none_si_rayon_nul(self):
        self.assertIsNone(radial_ruler_data(0, 0, 10.0, 0.0, 0.0, 100.0,
                                            5, 8.0, 13.0))

    def test_axe_est_horizontal_du_centre_au_bois(self):
        data = radial_ruler_data(cx=200, cy=200, scale=10.0, R=20.0,
                                 ep=0.0, grade=100.0, step_cm=5,
                                 tick_len_px=8.0, label_offset_px=13.0)
        (x0, y0), (xr, yr) = data.axis
        self.assertEqual((x0, y0), (200, 200))
        self.assertAlmostEqual(xr, 400.0)   # 200 + 20 cm * 10 px/cm
        self.assertAlmostEqual(yr, 200.0)
        self.assertIsNone(data.bark)

    def test_segment_ecorce_si_epaisseur(self):
        data = radial_ruler_data(cx=200, cy=200, scale=10.0, R=20.0,
                                 ep=2.0, grade=100.0, step_cm=5,
                                 tick_len_px=8.0, label_offset_px=13.0)
        (bx0, _), (bx1, _) = data.bark
        self.assertAlmostEqual(bx0, 400.0)
        self.assertAlmostEqual(bx1, 420.0)  # + 2 cm d'écorce
        # Le terminal est au BOUT de l'écorce (R+ep), pas au bord du bois.
        self.assertEqual(data.ticks[-1][-1], "22 cm")
        # Tiret perpendiculaire à l'axe Est → vertical, à x = 420 px.
        self.assertAlmostEqual(data.ticks[-1][0], 420.0)

    def test_tirets_etiquetes_zero_et_terminal_cm(self):
        data = radial_ruler_data(cx=200, cy=200, scale=10.0, R=20.0,
                                 ep=0.0, grade=100.0, step_cm=5,
                                 tick_len_px=8.0, label_offset_px=13.0)
        labels = [t[-1] for t in data.ticks]
        self.assertEqual(labels, ["0", "5", "10", "15", "20 cm"])
        # Étiquettes décalées côté grade+100 (sous l'axe quand Est).
        _, _, _, _, _lx, ly, _ = data.ticks[0]
        self.assertAlmostEqual(ly, 200 + 13.0)

    def test_omet_le_tiret_intermediaire_qui_colle_au_terminal(self):
        # R=21, step=5 : le tiret à 20 collerait au terminal (21) → omis.
        data = radial_ruler_data(cx=0, cy=0, scale=10.0, R=21.0,
                                 ep=0.0, grade=100.0, step_cm=5,
                                 tick_len_px=8.0, label_offset_px=13.0)
        labels = [t[-1] for t in data.ticks]
        self.assertEqual(labels, ["0", "5", "10", "15", "21 cm"])

    def test_au_moins_une_graduation_mediane(self):
        # R=16, step=10 : « 10 » collerait « 16 cm » → graduation médiane
        # (8) à la place, l'échelle garde au moins un segment intermédiaire.
        data = radial_ruler_data(cx=0, cy=0, scale=10.0, R=16.0,
                                 ep=0.0, grade=100.0, step_cm=10,
                                 tick_len_px=8.0, label_offset_px=13.0)
        self.assertEqual([t[-1] for t in data.ticks], ["0", "8", "16 cm"])
        # Pas trop grand pour le rayon (step > R_ext) → même repli médian.
        data = radial_ruler_data(cx=0, cy=0, scale=2.0, R=18.0,
                                 ep=0.0, grade=100.0, step_cm=20,
                                 tick_len_px=8.0, label_offset_px=13.0)
        self.assertEqual([t[-1] for t in data.ticks], ["0", "9", "18 cm"])

    def test_etiquette_terminale_arrondie_au_mm(self):
        # Rayon d'ellipse évalué à l'angle d'esquive → décimales parasites.
        data = radial_ruler_data(cx=0, cy=0, scale=10.0, R=16.1275,
                                 ep=0.0, grade=125.0, step_cm=5,
                                 tick_len_px=8.0, label_offset_px=13.0)
        self.assertEqual(data.ticks[-1][-1], "16.1 cm")


if __name__ == "__main__":
    unittest.main()


class BrinsLayoutTests(unittest.TestCase):
    """Cadrage global d'une cépée (`brins_layout`)."""

    # Marges arbitraires de test (indépendantes des renderers).
    W, H = 1000.0, 800.0
    MT, MB, MS = 100.0, 120.0, 60.0

    def _avail(self):
        return (self.W - 2 * self.MS, self.H - self.MT - self.MB)

    def test_liste_vide_renvoie_des_defauts(self):
        scale, ox, oy = brins_layout([], self.W, self.H,
                                     self.MT, self.MB, self.MS)
        self.assertEqual(scale, 1.0)
        self.assertEqual(ox, self.W / 2)
        self.assertEqual(oy, self.MT)

    def test_brin_unique_centre_top_aligne_et_centre_horizontalement(self):
        # Un brin unique en (0,0) d'encombrement e : cadrage top-aligné,
        # centré en largeur — reproduit le placement mono-brin historique.
        e = 20.0
        scale, ox, oy = brins_layout([(0.0, 0.0, e)], self.W, self.H,
                                     self.MT, self.MB, self.MS)
        avail_h, avail_v = self._avail()
        expected_scale = min(avail_h / (2 * e), avail_v / (2 * e))
        self.assertAlmostEqual(scale, expected_scale)
        # Origine = cœur du brin : centré en largeur, haut à margin_top.
        self.assertAlmostEqual(ox, self.W / 2)
        self.assertAlmostEqual(oy, self.MT + e * scale)

    def test_deux_brins_symetriques_autour_du_centre(self):
        # Deux brins identiques de part et d'autre de l'origine : leurs
        # centres écran sont symétriques autour de W/2.
        e = 10.0
        d = 15.0
        pe = [(-d, 0.0, e), (d, 0.0, e)]
        scale, ox, oy = brins_layout(pe, self.W, self.H,
                                     self.MT, self.MB, self.MS)
        cx_left = ox + (-d) * scale
        cx_right = ox + d * scale
        self.assertAlmostEqual((cx_left + cx_right) / 2, self.W / 2)
        # bbox large de 2*(d+e) cm doit tenir dans la zone dispo.
        avail_h, _ = self._avail()
        self.assertLessEqual(2 * (d + e) * scale, avail_h + 1e-6)

    def test_scale_limite_par_la_dimension_contrainte(self):
        # Cépée très large : le scale est borné par la largeur dispo.
        e = 5.0
        pe = [(-200.0, 0.0, e), (200.0, 0.0, e)]
        scale, _ox, _oy = brins_layout(pe, self.W, self.H,
                                       self.MT, self.MB, self.MS)
        avail_h, _ = self._avail()
        width_cm = 2 * (200.0 + e)
        self.assertAlmostEqual(scale, avail_h / width_cm)
