"""Cœur pur de l'évolution entre campagnes (`evolution`). Les scénarios sur
deux campagnes communs avec l'écran actuel sont dans `test_comparaison`."""

import unittest

from evolution import (
    Alerte,
    Campagne,
    Conclusion,
    appariement_par_defaut,
    comparer_campagnes,
    suivre,
)
from model import Arbre, Brin, Sondage

GRADES_SONDES = (0, 100, 200, 300)


def _brin(diametre, prbs, grades=GRADES_SONDES):
    rayon = diametre / 2
    b = Brin(rayon_tronc_cm=rayon)
    b.sondages = [Sondage(numero=i + 1, grade=g, bois_sain_cm=prbs,
                          bois_altere_cm=rayon - prbs)
                  for i, g in enumerate(grades)]
    return b


def _campagne(date, *brins, hauteur=100.0):
    a = Arbre(numero_arbre="1", port_arbre="libre", hauteur_sondage_cm=hauteur)
    a.brins = list(brins)
    return Campagne(date, a)


def _simple(date, diametre, prbs, **kw):
    return _campagne(date, _brin(diametre, prbs), **kw)


class IntervalleTests(unittest.TestCase):
    def test_progression_sans_croissance_avec_taux(self):
        i = comparer_campagnes(_simple("01/06/2023", 80, 20),
                               _simple("01/06/2025", 80, 18))
        self.assertEqual(i.conclusion, Conclusion.PROGRESSION)
        (b,) = i.brins
        self.assertAlmostEqual(b.progression_max, 2.0)
        self.assertAlmostEqual(b.progression_moy, 2.0)
        self.assertAlmostEqual(b.taux_cm_an, 1.0, places=2)
        self.assertEqual(b.alertes, ())

    def test_etat_et_degradation_restent_distincts(self):
        # t/R en hausse ET dégradation en progression.
        (b,) = comparer_campagnes(_simple("", 80, 20),
                                  _simple("", 85, 21.5)).brins
        self.assertGreater(b.etat_cur.tR_min_pct, b.etat_ref.tR_min_pct)
        self.assertEqual(b.conclusion, Conclusion.PROGRESSION)
        self.assertIsNone(b.taux_cm_an)

    def test_diametre_en_baisse_est_signale(self):
        (b,) = comparer_campagnes(_simple("", 80, 20),
                                  _simple("", 76, 18)).brins
        self.assertIn(Alerte.DIAMETRE_EN_BAISSE, b.alertes)

    def test_cavite_en_recul(self):
        i = comparer_campagnes(_simple("", 80, 20), _simple("", 85, 25))
        self.assertEqual(i.conclusion, Conclusion.A_VERIFIER)
        self.assertIn(Alerte.CAVITE_EN_RECUL, i.brins[0].alertes)

    def test_direction_non_resondee(self):
        (b,) = comparer_campagnes(
            _simple("", 80, 20),
            _campagne("", _brin(80, 20, grades=(0, 100, 200)))).brins
        self.assertIn(Alerte.DIRECTION_NON_RESONDEE, b.alertes)

    def test_hauteurs_differentes_ne_restituent_aucune_evolution(self):
        i = comparer_campagnes(_simple("", 80, 20),
                               _simple("", 80, 10, hauteur=130))
        self.assertEqual(i.conclusion, Conclusion.NON_COMPARABLE)
        self.assertEqual(i.hauteurs, (100.0, 130.0))
        (b,) = i.brins
        self.assertEqual(b.directions, [])
        self.assertIsNone(b.progression_max)
        self.assertEqual(b.alertes, (Alerte.HAUTEURS_DIFFERENTES,))
        # L'état à chaque date, lui, reste connu.
        self.assertIsNotNone(b.etat_ref.tR_min_pct)
        self.assertIsNotNone(b.etat_cur.tR_min_pct)

    def test_rayon_manquant(self):
        i = comparer_campagnes(_simple("", 80, 20),
                               _campagne("", Brin(rayon_tronc_cm=0.0)))
        self.assertEqual(i.conclusion, Conclusion.NON_COMPARABLE)
        self.assertIn(Alerte.RAYON_MANQUANT, i.brins[0].alertes)


class CepeeTests(unittest.TestCase):
    def setUp(self):
        self.ref = _campagne("", _brin(40, 10), _brin(60, 20), _brin(50, 15))
        # Le premier brin a disparu : restent les ex-b et ex-c.
        self.cur = _campagne("", _brin(60, 20), _brin(50, 15))

    def test_nombre_de_brins_different_aucun_appariement_devine(self):
        self.assertEqual(appariement_par_defaut(self.ref.arbre, self.cur.arbre),
                         [None, None])
        i = comparer_campagnes(self.ref, self.cur)
        self.assertEqual(i.conclusion, Conclusion.NON_COMPARABLE)
        self.assertEqual(len(i.brins), 5)      # 2 sans réf. + 3 disparus

    def test_appariement_fourni_et_brin_disparu(self):
        i = comparer_campagnes(self.ref, self.cur, appariement=[1, 2])
        self.assertEqual([b.conclusion for b in i.brins[:2]],
                         [Conclusion.STABLE, Conclusion.STABLE])
        disparu = i.brins[2]
        self.assertEqual((disparu.index_ref, disparu.index_cur), (0, None))
        self.assertIn(Alerte.BRIN_DISPARU, disparu.alertes)
        # Un brin disparu empêche de déclarer l'arbre entier stable.
        self.assertEqual(i.conclusion, Conclusion.NON_COMPARABLE)

    def test_la_progression_d_un_brin_prime(self):
        cur = _campagne("", _brin(40, 10), _brin(60, 17), _brin(50, 15))
        self.assertEqual(comparer_campagnes(self.ref, cur).conclusion,
                         Conclusion.PROGRESSION)

    def test_appariement_invalide_refuse(self):
        for faux in ([0], [0, 0], [0, 7], [-1, 0]):
            with self.subTest(faux=faux), self.assertRaises(ValueError):
                comparer_campagnes(self.ref, self.cur, appariement=faux)


class SuiviTests(unittest.TestCase):
    def test_trois_campagnes_ordre_chronologique(self):
        s = suivre([_simple("01/06/2026", 90, 22),
                    _simple("01/06/2020", 80, 20),
                    _simple("01/06/2023", 85, 22.5)])
        self.assertEqual([c.date for c in s.campagnes],
                         ["01/06/2020", "01/06/2023", "01/06/2026"])
        self.assertEqual([i.conclusion for i in s.intervalles],
                         [Conclusion.STABLE, Conclusion.PROGRESSION])
        self.assertEqual(s.global_.conclusion, Conclusion.PROGRESSION)
        # Cavité Ø 40 → 40 → 46 : 3 cm de rayon sur l'ensemble.
        self.assertAlmostEqual(s.global_.brins[0].progression_max, 3.0)

    def test_deux_campagnes_pas_d_intervalle_global(self):
        s = suivre([_simple("01/06/2020", 80, 20),
                    _simple("01/06/2023", 85, 22.5)])
        self.assertEqual(len(s.intervalles), 1)
        self.assertIsNone(s.global_)

    def test_date_manquante_ordre_fourni_conserve(self):
        s = suivre([_simple("01/06/2026", 90, 22), _simple("", 80, 20)])
        self.assertEqual([c.date for c in s.campagnes], ["01/06/2026", ""])
        self.assertIsNone(s.intervalles[0].annees)

    def test_une_seule_campagne(self):
        s = suivre([_simple("01/06/2020", 80, 20)])
        self.assertEqual((s.intervalles, s.global_), ([], None))


if __name__ == "__main__":
    unittest.main()
