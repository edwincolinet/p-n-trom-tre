"""Scénarios de ré-inspection : la croissance du tronc ne doit ni masquer
ni inventer une progression de la dégradation."""

import unittest

from comparaison_render import _degs_reference_recales, metric_rows, render_evolution_section
from diagnostic_comparaison import (
    comparaison_detaillee,
    comparaison_par_brin,
    directions_a_verifier,
    directions_en_progression,
    directions_recouvertes,
    evolution_degradation,
    verdict_evolution,
)
from model import Arbre, DegradationExterne, Sondage

GRADES_SONDES = (0, 100, 200, 300)


def _arbre(diametre, prbs, *, grades=GRADES_SONDES, hauteur=100.0, degs=()):
    a = Arbre(numero_arbre="1", port_arbre="libre", hauteur_sondage_cm=hauteur)
    rayon = diametre / 2
    a.brins[0].rayon_tronc_cm = rayon
    a.brins[0].sondages = [
        Sondage(numero=i + 1, grade=g, bois_sain_cm=prbs,
                bois_altere_cm=rayon - prbs)
        for i, g in enumerate(grades)]
    a.brins[0].degradations_externes = list(degs)
    return a


def _deg(profondeur):
    return DegradationExterne(grade_debut=0, grade_fin=50,
                              profondeur_cm=profondeur,
                              comprend_ecorce=False)


class CroissanceEtProgressionTests(unittest.TestCase):
    def _comparer(self, ref, cur):
        return comparaison_detaillee(ref, cur, annees=3.0)

    def test_croissance_seule_n_est_pas_une_evolution(self):
        d = self._comparer(_arbre(80, 20), _arbre(85, 22.5))
        self.assertEqual(evolution_degradation(d), 0)
        self.assertIn("PAS DE PROGRESSION", verdict_evolution(d))
        self.assertEqual(directions_a_verifier(d), [])

    def test_progression_masquee_par_la_croissance(self):
        # PRBS et t/R en hausse, mais la cavité gagne 1 cm de rayon.
        d = self._comparer(_arbre(80, 20), _arbre(85, 21.5))
        self.assertGreater(d.tR_min_cur, d.tR_min_ref)
        self.assertEqual(evolution_degradation(d), 1)
        self.assertEqual(len(directions_en_progression(d)), 4)
        self.assertAlmostEqual(d.pire.progression, 1.0)
        self.assertAlmostEqual(d.taux_cm_an, 1.0 / 3)

    def test_cavite_en_recul_est_a_verifier_pas_un_progres(self):
        d = self._comparer(_arbre(80, 20), _arbre(85, 25))
        self.assertIsNone(evolution_degradation(d))
        self.assertEqual(len(directions_a_verifier(d)), 4)
        self.assertIn("À VÉRIFIER", verdict_evolution(d))
        self.assertNotIn("AMÉLIORATION", verdict_evolution(d))

    def test_valeur_reconduite_malgre_la_croissance_est_signalee(self):
        d = self._comparer(_arbre(80, 20), _arbre(85, 20))
        self.assertIn("re-mesurée", verdict_evolution(d))

    def test_direction_non_resondee_ne_conclut_pas(self):
        ref = _arbre(80, 20)
        cur = _arbre(85, 22.5)
        cur.brins[0].sondages[0] = Sondage(
            numero=1, grade=50, bois_sain_cm=5.0, bois_altere_cm=37.5)
        d = self._comparer(ref, cur)
        self.assertEqual(directions_en_progression(d), [])

    def test_aucune_direction_commune(self):
        d = self._comparer(_arbre(80, 20),
                           _arbre(80, 5, grades=(50, 150, 250)))
        self.assertIsNone(evolution_degradation(d))
        self.assertIn("NON ÉVALUABLE", verdict_evolution(d))


class DegradationExterneTests(unittest.TestCase):
    def test_plaie_inchangee_sous_croissance(self):
        # Fond de plaie à la même distance du centre : 5 cm puis 7,5 cm.
        d = comparaison_detaillee(
            _arbre(80, 20, degs=[_deg(5)]),
            _arbre(85, 22.5, degs=[_deg(7.5)]), 3.0)
        self.assertEqual(evolution_degradation(d), 0)

    def test_plaie_qui_se_creuse(self):
        d = comparaison_detaillee(
            _arbre(80, 20, degs=[_deg(5)]),
            _arbre(80, 20, degs=[_deg(8)]), 3.0)
        self.assertEqual(evolution_degradation(d), 1)

    def test_plaie_recouverte_est_un_progres(self):
        d = comparaison_detaillee(
            _arbre(80, 20, degs=[_deg(5)]), _arbre(85, 22.5), 3.0)
        self.assertEqual(evolution_degradation(d), -1)
        self.assertTrue(directions_recouvertes(d))
        self.assertIn("recouverte", verdict_evolution(d))

    def test_plaie_disparue_sans_croissance_est_a_verifier(self):
        d = comparaison_detaillee(
            _arbre(80, 20, degs=[_deg(5)]), _arbre(80, 20), 3.0)
        self.assertEqual(directions_recouvertes(d), [])
        self.assertTrue(directions_a_verifier(d))

    def test_reference_recalee_dans_le_repere_fixe(self):
        ref = _arbre(80, 20, degs=[_deg(5)])
        cur = _arbre(85, 22.5)
        (deg,) = _degs_reference_recales(ref.brins[0], cur.brins[0])
        self.assertAlmostEqual(deg.profondeur_cm, 7.5)
        # La mission de référence n'est pas modifiée.
        self.assertAlmostEqual(ref.brins[0].degradations_externes[0]
                               .profondeur_cm, 5.0)


class LibellesTests(unittest.TestCase):
    def test_directions_intermediaires_nommees(self):
        d = comparaison_detaillee(
            _arbre(80, 20, degs=[_deg(5)]), _arbre(85, 22.5), 3.0)
        self.assertTrue(all(x.direction for x in d.directions))
        self.assertIn("N-NE", verdict_evolution(d))


class HauteurDeSondageTests(unittest.TestCase):
    def test_hauteurs_differentes_refus_de_conclure(self):
        ref = _arbre(80, 20, hauteur=100)
        cur = _arbre(80, 10, hauteur=130)
        d = comparaison_detaillee(ref, cur, 3.0)
        self.assertIsNone(evolution_degradation(d))
        self.assertEqual(directions_en_progression(d), [])
        self.assertIsNone(d.progression_moy)
        self.assertIsNone(d.taux_cm_an)
        self.assertIn("NON COMPARABLE", verdict_evolution(d))
        rows = metric_rows(d)
        self.assertEqual(rows[-1][0], "Hauteur de sondage")
        self.assertEqual([r for r in rows if r[0] == "t/R minimal"][0][3], "")
        # Aucune zone d'évolution peinte : pas d'orange sur le dessin.
        img = render_evolution_section(ref, cur, 300)
        zone = img.crop((60, 60, 240, 240)).getcolors(100000)
        self.assertNotIn((232, 128, 26), [c for _n, c in zone])

    def test_hauteur_non_renseignee_n_empeche_pas(self):
        d = comparaison_detaillee(
            _arbre(80, 20, hauteur=0), _arbre(80, 20, hauteur=130), 3.0)
        self.assertIsNone(d.hauteurs_incompatibles)

    def test_refus_aussi_brin_par_brin(self):
        pairs = comparaison_par_brin(
            _arbre(80, 20, hauteur=100), _arbre(80, 20, hauteur=130), 3.0)
        self.assertEqual(pairs[0][3].hauteurs_incompatibles, (100.0, 130.0))


if __name__ == "__main__":
    unittest.main()
