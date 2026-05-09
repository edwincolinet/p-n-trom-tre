"""Tests des dataclasses métier et des méthodes calculées sur `Arbre`.

Couvre :
- `Sondage.ratio_tR` (cap, rayon nul).
- `DegradationExterne.largeur_grades` / `couvre_grade` (cas normal,
  wrap-around, début == fin).
- `Contrefort.grade_debut` / `grade_fin` (wrap au grade 0).
- `Arbre.recompute_alteration_from_sondages` (extrapolation pondérée,
  cas 0/1/N, doublons → max).
- `Arbre.degradation_externe_par_grade` (max sur recouvrements).
- `Arbre.prbs_par_grade` (combinaison interne + externe + cap à 0).
- `Arbre.repartition_classes` (compteurs, t/R minimal, classe globale).
"""

from __future__ import annotations

import unittest

from geometry import GRADES
from model import (
    Arbre,
    Contrefort,
    DegradationExterne,
    Sondage,
)


class SondageTests(unittest.TestCase):

    def test_ratio_tR_rayon_zero(self):
        s = Sondage(bois_sain_cm=5.0)
        self.assertEqual(s.ratio_tR(0.0), 0.0)
        self.assertEqual(s.ratio_tR(-3.0), 0.0)

    def test_ratio_tR_normal(self):
        s = Sondage(bois_sain_cm=5.0)
        self.assertAlmostEqual(s.ratio_tR(20.0), 0.25)

    def test_ratio_tR_capped_a_1(self):
        # Si le bois sain dépasse le rayon (saisie incohérente), le
        # ratio est plafonné à 1 — pas de division aberrante.
        s = Sondage(bois_sain_cm=30.0)
        self.assertEqual(s.ratio_tR(20.0), 1.0)

    def test_prbs_alias_de_bois_sain(self):
        s = Sondage(bois_sain_cm=7.5)
        self.assertEqual(s.prbs_cm, 7.5)


class DegradationExterneTests(unittest.TestCase):

    def test_largeur_simple(self):
        deg = DegradationExterne(grade_debut=0, grade_fin=100)
        self.assertEqual(deg.largeur_grades(), 100)

    def test_largeur_wrap(self):
        # 350 → 50 dans le sens horaire = 100 gr
        deg = DegradationExterne(grade_debut=350, grade_fin=50)
        self.assertEqual(deg.largeur_grades(), 100)

    def test_largeur_debut_egal_fin_minimum_25(self):
        # Documenté : début == fin est traité comme un secteur minimal
        # de 25 gr (résolution du dessin).
        deg = DegradationExterne(grade_debut=50, grade_fin=50)
        self.assertEqual(deg.largeur_grades(), 25)

    def test_couvre_grade_couvre_les_bornes(self):
        deg = DegradationExterne(grade_debut=0, grade_fin=100)
        for g in (0, 25, 50, 75, 100):
            with self.subTest(g=g):
                self.assertTrue(deg.couvre_grade(g))

    def test_couvre_grade_exclut_l_exterieur(self):
        deg = DegradationExterne(grade_debut=0, grade_fin=100)
        for g in (125, 200, 375):
            with self.subTest(g=g):
                self.assertFalse(deg.couvre_grade(g))

    def test_couvre_grade_wrap_around(self):
        deg = DegradationExterne(grade_debut=350, grade_fin=50)
        for g in (350, 375, 0, 25, 50):
            with self.subTest(g=g):
                self.assertTrue(deg.couvre_grade(g))
        for g in (75, 325):
            with self.subTest(g=g):
                self.assertFalse(deg.couvre_grade(g))

    def test_couvre_grade_hors_resolution(self):
        # Grade non multiple de 25 → toujours False (hors grille).
        deg = DegradationExterne(grade_debut=0, grade_fin=100)
        self.assertFalse(deg.couvre_grade(30))
        self.assertFalse(deg.couvre_grade(99))

    def test_largeur_cm_proportionnelle_au_rayon(self):
        deg = DegradationExterne(grade_debut=0, grade_fin=100)  # 100 gr
        # 100 gr = π/2 rad → largeur = R × π/2
        self.assertAlmostEqual(deg.largeur_cm(20.0), 20.0 * 3.141592653589793 / 2)
        self.assertEqual(deg.largeur_cm(0.0), 0.0)


class ContrefortTests(unittest.TestCase):

    def test_grade_debut_fin_normal(self):
        c = Contrefort(grade_centre=200, largeur_grades=100)
        self.assertEqual(c.grade_debut(), 150)
        self.assertEqual(c.grade_fin(), 250)

    def test_grade_debut_fin_wrap(self):
        c = Contrefort(grade_centre=0, largeur_grades=50)
        self.assertEqual(c.grade_debut(), 375)
        self.assertEqual(c.grade_fin(), 25)

    def test_largeur_cm_proportionnelle(self):
        c = Contrefort(grade_centre=0, largeur_grades=200)  # demi-pourtour
        # 200 gr = π rad → R × π
        self.assertAlmostEqual(c.largeur_cm(10.0), 10.0 * 3.141592653589793)


class RecomputeAlterationTests(unittest.TestCase):

    def _new_arbre(self) -> Arbre:
        return Arbre(rayon_tronc_cm=20.0)

    def test_aucun_sondage_donne_zeros(self):
        a = self._new_arbre()
        a.recompute_alteration_from_sondages()
        self.assertEqual(a.alteration_par_grade, [0.0] * 16)

    def test_un_seul_sondage_pas_d_extrapolation(self):
        # Documenté : moins de 2 sondages → on garde la mesure ponctuelle
        # et on laisse les autres à 0 (pas assez d'info pour extrapoler).
        a = self._new_arbre()
        a.sondages.append(Sondage(grade=0, bois_sain_cm=15.0,
                                   bois_altere_cm=5.0))
        a.recompute_alteration_from_sondages()
        self.assertEqual(a.alteration_par_grade[0], 5.0)
        self.assertEqual(sum(a.alteration_par_grade[1:]), 0.0)

    def test_deux_sondages_opposes_donnent_moyenne_ponderee(self):
        # Sondage à 0 gr (idx 0) avec altéré=4, sondage à 200 gr (idx 8)
        # avec altéré=8. Au milieu (100 gr, idx 4) : équidistant des
        # deux → moyenne arithmétique 6.
        a = self._new_arbre()
        a.sondages.append(Sondage(grade=0, bois_altere_cm=4.0))
        a.sondages.append(Sondage(grade=200, bois_altere_cm=8.0))
        a.recompute_alteration_from_sondages()
        self.assertAlmostEqual(a.alteration_par_grade[0], 4.0)
        self.assertAlmostEqual(a.alteration_par_grade[8], 8.0)
        # Milieu (idx 4) entre idx 0 et idx 8 : (4+8)/2 = 6
        self.assertAlmostEqual(a.alteration_par_grade[4], 6.0)
        # idx 2 : 2 crans de 0, 6 crans de 8 → 4*0.75 + 8*0.25 = 5
        self.assertAlmostEqual(a.alteration_par_grade[2], 5.0)

    def test_doublon_au_meme_grade_le_pire_gagne(self):
        # Si plusieurs sondages au même grade, on garde la valeur
        # la plus défavorable (max d'altération).
        a = self._new_arbre()
        a.sondages.append(Sondage(grade=0, bois_altere_cm=3.0))
        a.sondages.append(Sondage(grade=0, bois_altere_cm=7.0))
        a.sondages.append(Sondage(grade=200, bois_altere_cm=2.0))
        a.recompute_alteration_from_sondages()
        self.assertAlmostEqual(a.alteration_par_grade[0], 7.0)


class DegradationExterneParGradeTests(unittest.TestCase):

    def test_aucune_degradation_donne_zeros(self):
        a = Arbre(rayon_tronc_cm=20.0)
        self.assertEqual(a.degradation_externe_par_grade(), [0.0] * 16)

    def test_une_degradation_couvre_les_grades_attendus(self):
        a = Arbre(rayon_tronc_cm=20.0)
        a.degradations_externes.append(
            DegradationExterne(grade_debut=50, grade_fin=100,
                                profondeur_cm=2.0))
        out = a.degradation_externe_par_grade()
        # 50, 75, 100 → couverts ; ailleurs → 0
        self.assertAlmostEqual(out[GRADES.index(50)], 2.0)
        self.assertAlmostEqual(out[GRADES.index(75)], 2.0)
        self.assertAlmostEqual(out[GRADES.index(100)], 2.0)
        self.assertEqual(out[GRADES.index(0)], 0.0)
        self.assertEqual(out[GRADES.index(125)], 0.0)

    def test_deux_degradations_qui_se_recouvrent_donnent_le_max(self):
        a = Arbre(rayon_tronc_cm=20.0)
        a.degradations_externes.append(
            DegradationExterne(grade_debut=0, grade_fin=100,
                                profondeur_cm=1.0))
        a.degradations_externes.append(
            DegradationExterne(grade_debut=50, grade_fin=150,
                                profondeur_cm=3.0))
        out = a.degradation_externe_par_grade()
        # Recouvrement à 50, 75, 100 → max(1, 3) = 3
        for g in (50, 75, 100):
            self.assertAlmostEqual(out[GRADES.index(g)], 3.0)
        # Hors recouvrement de la deuxième
        self.assertAlmostEqual(out[GRADES.index(0)], 1.0)
        self.assertAlmostEqual(out[GRADES.index(125)], 3.0)


class PrbsParGradeTests(unittest.TestCase):

    def test_arbre_sans_alteration_ni_degradation(self):
        a = Arbre(rayon_tronc_cm=20.0)
        self.assertEqual(a.prbs_par_grade(), [20.0] * 16)

    def test_alteration_interne_seule(self):
        a = Arbre(rayon_tronc_cm=20.0)
        a.sondages.append(Sondage(grade=0, bois_altere_cm=5.0))
        a.sondages.append(Sondage(grade=200, bois_altere_cm=5.0))
        out = a.prbs_par_grade()
        # Aux deux directions sondées : 20 - 5 = 15
        self.assertAlmostEqual(out[0], 15.0)
        self.assertAlmostEqual(out[8], 15.0)

    def test_degradation_externe_seule(self):
        a = Arbre(rayon_tronc_cm=20.0)
        a.degradations_externes.append(
            DegradationExterne(grade_debut=0, grade_fin=0,
                                profondeur_cm=2.0))
        out = a.prbs_par_grade()
        self.assertAlmostEqual(out[0], 18.0)

    def test_alteration_et_degradation_se_cumulent(self):
        a = Arbre(rayon_tronc_cm=20.0)
        a.sondages.append(Sondage(grade=0, bois_altere_cm=5.0))
        a.sondages.append(Sondage(grade=200, bois_altere_cm=5.0))
        a.degradations_externes.append(
            DegradationExterne(grade_debut=0, grade_fin=0,
                                profondeur_cm=2.0))
        out = a.prbs_par_grade()
        # 20 - 5 (interne) - 2 (externe) = 13 au grade 0
        self.assertAlmostEqual(out[0], 13.0)

    def test_prbs_jamais_negative(self):
        # Si interne + externe dépasse le rayon, la PRBS est plafonnée à 0
        # (pas de bois sain négatif).
        a = Arbre(rayon_tronc_cm=10.0)
        a.sondages.append(Sondage(grade=0, bois_altere_cm=8.0))
        a.sondages.append(Sondage(grade=200, bois_altere_cm=8.0))
        a.degradations_externes.append(
            DegradationExterne(grade_debut=0, grade_fin=0,
                                profondeur_cm=5.0))
        out = a.prbs_par_grade()
        self.assertEqual(out[0], 0.0)

    def test_rayon_zero_donne_zeros(self):
        a = Arbre(rayon_tronc_cm=0.0)
        self.assertEqual(a.prbs_par_grade(), [0.0] * 16)


class RepartitionClassesTests(unittest.TestCase):

    def test_arbre_sain_tout_vert(self):
        a = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        rep = a.repartition_classes()
        self.assertEqual(rep["Vert"]["n"], 16)
        self.assertEqual(rep["Orange"]["n"], 0)
        self.assertEqual(rep["Rouge"]["n"], 0)
        self.assertEqual(rep["classe_globale"], "Vert")
        self.assertEqual(rep["Vert"]["grades"], 400)
        self.assertAlmostEqual(rep["Vert"]["pct"], 100.0)

    def test_classe_globale_basee_sur_le_tR_moyen(self):
        # On crée 2 sondages opposés très altérés : le t/R moyen tombe
        # bas → classe globale Rouge même si certaines directions
        # extrapolées peuvent être Orange.
        a = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        a.sondages.append(Sondage(grade=0, bois_altere_cm=18.0))
        a.sondages.append(Sondage(grade=200, bois_altere_cm=18.0))
        rep = a.repartition_classes()
        # PRBS partout = 20 - 18 = 2 (extrapolé identique partout)
        # t/R = 0.10 < 0.15 → Rouge sur tout le pourtour
        self.assertEqual(rep["Rouge"]["n"], 16)
        self.assertEqual(rep["classe_globale"], "Rouge")
        self.assertAlmostEqual(rep["tR_moyen"], 0.10)

    def test_tR_min_localise_sur_la_pire_direction(self):
        a = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        # Direction 100 gr est la plus dégradée
        a.sondages.append(Sondage(grade=0, bois_altere_cm=2.0))
        a.sondages.append(Sondage(grade=100, bois_altere_cm=18.0))
        a.sondages.append(Sondage(grade=200, bois_altere_cm=2.0))
        rep = a.repartition_classes()
        self.assertEqual(rep["tR_min_grade"], 100)

    def test_pct_grades_n_coherent(self):
        a = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        rep = a.repartition_classes()
        total_n = sum(rep[c]["n"] for c in ("Vert", "Orange", "Rouge"))
        total_grades = sum(rep[c]["grades"] for c in ("Vert", "Orange", "Rouge"))
        total_pct = sum(rep[c]["pct"] for c in ("Vert", "Orange", "Rouge"))
        self.assertEqual(total_n, 16)
        self.assertEqual(total_grades, 400)
        self.assertAlmostEqual(total_pct, 100.0)


if __name__ == "__main__":
    unittest.main()
