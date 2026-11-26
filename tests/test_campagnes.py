"""Historique des relevés : identifiants stables, archivage, import d'une
ancienne mission, persistance (format v4) et plaie recouverte."""

import json
import unittest

from campagnes import archiver, importer, proposer_appariement, serie
from diagnostic import prbs_par_grade
from diagnostic_comparaison import comparaison_par_brin
from evolution import Alerte, Campagne, Conclusion, comparer_campagnes, suivre
from model import Arbre, Chantier, DegradationExterne, Sondage
from persistence import chantier_from_dict, chantier_to_dict


def _arbre(numero="1", prbs=20.0, diametre=80.0):
    a = Arbre(numero_arbre=numero, port_arbre="libre",
              hauteur_sondage_cm=100.0, rayon_tronc_cm=diametre / 2)
    a.brins[0].sondages = [
        Sondage(numero=i + 1, grade=g, bois_sain_cm=prbs,
                bois_altere_cm=diametre / 2 - prbs)
        for i, g in enumerate((0, 100, 200, 300))]
    return a


def _aller_retour(chantier):
    return chantier_from_dict(json.loads(json.dumps(chantier_to_dict(chantier))))


class IdentifiantsTests(unittest.TestCase):
    def test_uniques_sans_peser_sur_l_egalite(self):
        a, b = _arbre(), _arbre()
        self.assertNotEqual(a.id, b.id)
        self.assertNotEqual(a.brins[0].id, b.brins[0].id)
        self.assertEqual(a, b)

    def test_conserves_a_l_enregistrement(self):
        c = Chantier(arbres=[_arbre()])
        d = _aller_retour(c)
        self.assertEqual(d.arbres[0].id, c.arbres[0].id)
        self.assertEqual(d.arbres[0].brins[0].id, c.arbres[0].brins[0].id)

    def test_attribues_aux_anciens_fichiers(self):
        v3 = {"format_version": 3, "arbres": [
            {"numero_arbre": "1", "brins": [{"rayon_tronc_cm": 20}]}]}
        v2 = {"arbres": [{"numero_arbre": "1", "rayon_tronc_cm": 20},
                         {"numero_arbre": "2", "rayon_tronc_cm": 20}]}
        for source in (v3, v2):
            c = chantier_from_dict(source)
            ids = [x for a in c.arbres for x in (a.id, a.brins[0].id)]
            self.assertTrue(all(ids))
            self.assertEqual(len(set(ids)), len(ids))
            self.assertEqual(c.arbres[0].campagnes, [])

    def test_duplication_nouvelle_identite_sans_historique(self):
        a = _arbre()
        archiver(a, "01/06/2023")
        copie = a.dupliquer()
        self.assertNotEqual(copie.id, a.id)
        self.assertNotEqual(copie.brins[0].id, a.brins[0].id)
        self.assertEqual(copie.campagnes, [])
        self.assertEqual(len(a.campagnes), 1)
        self.assertEqual(copie.brins, a.brins)


class ArchivageTests(unittest.TestCase):
    def test_releve_fige_et_independant(self):
        a = _arbre(prbs=20)
        archiver(a, "01/06/2023", "EC")
        a.brins[0].sondages[0].bois_sain_cm = 5.0
        releve = a.campagnes[0]
        self.assertEqual(releve.arbre.brins[0].sondages[0].bois_sain_cm, 20)
        self.assertEqual(releve.arbre.id, a.id)
        self.assertEqual(releve.arbre.campagnes, [])

    def test_tri_chronologique_et_date_en_double_refusee(self):
        a = _arbre()
        archiver(a, "01/06/2023")
        archiver(a, "01/06/2020")
        self.assertEqual([r.date for r in a.campagnes],
                         ["01/06/2020", "01/06/2023"])
        with self.assertRaises(ValueError):
            archiver(a, "01/06/2023")
        self.assertEqual(len(a.campagnes), 2)

    def test_persistance_de_l_historique(self):
        a = _arbre(prbs=20)
        archiver(a, "01/06/2023", "EC", [])
        a.brins[0].sondages[0].bois_sain_cm = 18.0
        relu = _aller_retour(Chantier(arbres=[a])).arbres[0]
        (releve,) = relu.campagnes
        self.assertEqual((releve.date, releve.operateur), ("01/06/2023", "EC"))
        self.assertEqual(releve.arbre.brins, a.campagnes[0].arbre.brins)
        self.assertEqual(releve.arbre.brins[0].id, relu.brins[0].id)

    def test_serie_alimente_le_suivi(self):
        a = _arbre(prbs=20)
        archiver(a, "01/06/2023")
        for s in a.brins[0].sondages:
            s.bois_sain_cm, s.bois_altere_cm = 18.0, 22.0
        suivi = suivre(serie(a, "01/06/2025"))
        self.assertEqual(suivi.intervalles[0].conclusion,
                         Conclusion.PROGRESSION)


class ImportTests(unittest.TestCase):
    def test_proposition_par_identifiant_puis_numero_unique(self):
        suivi_a, nouveau = _arbre("1"), _arbre("9")
        courante = Chantier(arbres=[suivi_a, _arbre("2"), _arbre("3"), nouveau])
        renumerote = suivi_a.dupliquer()
        renumerote.id, renumerote.numero_arbre = suivi_a.id, "40"
        ancienne = Chantier(arbres=[_arbre("2"), renumerote,
                                    _arbre("3"), _arbre("3")])
        self.assertEqual(proposer_appariement(courante, ancienne),
                         [1, 0, None, None])

    def test_import_aligne_les_identifiants(self):
        courant, ancien = _arbre(prbs=18), _arbre(prbs=20)
        importer(courant, ancien, "01/06/2023")
        releve = courant.campagnes[0]
        self.assertEqual(releve.arbre.id, courant.id)
        self.assertEqual(releve.arbre.brins[0].id, courant.brins[0].id)
        self.assertNotEqual(ancien.brins[0].id, courant.brins[0].id)

    def test_import_conserve_l_historique_ancien(self):
        courant, ancien = _arbre(), _arbre()
        archiver(ancien, "01/06/2020")
        importer(courant, ancien, "01/06/2023")
        self.assertEqual([r.date for r in courant.campagnes],
                         ["01/06/2020", "01/06/2023"])
        self.assertEqual({r.arbre.brins[0].id for r in courant.campagnes},
                         {courant.brins[0].id})

    def test_import_refuse_ne_modifie_rien(self):
        courant, ancien = _arbre(), _arbre()
        archiver(courant, "01/06/2023")
        archiver(ancien, "01/06/2020")
        with self.assertRaises(ValueError):
            importer(courant, ancien, "01/06/2023")
        self.assertEqual(len(courant.campagnes), 1)

    def test_appariement_refuse_par_l_expert(self):
        courant = _arbre()
        archiver(courant, "01/06/2020")
        ancien = courant.campagnes.pop().arbre      # mêmes identifiants
        importer(courant, ancien, "01/06/2023", appariement_brins=[None])
        self.assertNotEqual(courant.campagnes[0].arbre.brins[0].id,
                            courant.brins[0].id)


class CepeeSuivieTests(unittest.TestCase):
    def test_suppression_puis_ajout_de_brin(self):
        a = _arbre()
        a.ajouter_brin()
        a.ajouter_brin()
        for i, b in enumerate(a.brins):
            b.rayon_tronc_cm = 20.0 + i
        archiver(a, "01/06/2023")
        a.supprimer_brin(0)
        a.ajouter_brin()          # même nombre de brins qu'avant
        ancien = a.campagnes[0].arbre
        i = comparer_campagnes(Campagne("01/06/2023", ancien),
                               Campagne("01/06/2025", a))
        self.assertEqual([(b.index_ref, b.index_cur) for b in i.brins],
                         [(1, 0), (2, 1), (None, 2), (0, None)])
        # La comparaison actuelle apparie de la même façon.
        paires = comparaison_par_brin(ancien, a, 2.0)
        self.assertIs(paires[0][2], ancien.brins[1])
        self.assertIsNone(paires[2][2])


class PlaieRecouverteTests(unittest.TestCase):
    def _arbre_blesse(self, profondeur, recouverte=False, diametre=80.0):
        a = _arbre(prbs=diametre / 2 - 20, diametre=diametre)
        a.brins[0].degradations_externes = [DegradationExterne(
            grade_debut=0, grade_fin=50, profondeur_cm=profondeur,
            comprend_ecorce=False, recouverte=recouverte)]
        return a

    def _comparer(self, ref, cur):
        return comparer_campagnes(Campagne("", ref), Campagne("", cur))

    def test_le_bois_degrade_reste_perdu(self):
        self.assertEqual(
            prbs_par_grade(self._arbre_blesse(5, True).brins[0]),
            prbs_par_grade(self._arbre_blesse(5).brins[0]))

    def test_l_ecorce_n_est_pas_retiree_d_une_couche_sous_cal(self):
        deg = DegradationExterne(profondeur_cm=5.0, comprend_ecorce=True,
                                 recouverte=True)
        self.assertEqual(deg.profondeur_bois_cm(2.0), 5.0)

    def test_plaie_avec_ecorce_puis_recouverte_meme_bois_perdu(self):
        # Ouverte : 7 cm dont 2 d'écorce. Recouverte : 5 cm de bois dégradé.
        ref, cur = self._arbre_blesse(7), self._arbre_blesse(5, True)
        for a in (ref, cur):
            a.brins[0].epaisseur_ecorce_cm = 2.0
        ref.brins[0].degradations_externes[0].comprend_ecorce = True
        i = self._comparer(ref, cur)
        self.assertEqual(i.conclusion, Conclusion.RECOUVREMENT)
        self.assertEqual(i.brins[0].alertes, ())

    def test_cal_signale_est_un_progres_meme_sans_diametre_en_hausse(self):
        i = self._comparer(self._arbre_blesse(5), self._arbre_blesse(5, True))
        self.assertEqual(i.conclusion, Conclusion.RECOUVREMENT)

    def test_cal_et_croissance(self):
        i = self._comparer(self._arbre_blesse(5),
                           self._arbre_blesse(5, True, diametre=86))
        self.assertEqual(i.conclusion, Conclusion.RECOUVREMENT)

    def test_deja_recouverte_et_inchangee_est_stable(self):
        i = self._comparer(self._arbre_blesse(5, True),
                           self._arbre_blesse(5, True, diametre=86))
        self.assertEqual(i.conclusion, Conclusion.STABLE)

    def test_degradation_qui_s_etend_sous_le_cal(self):
        i = self._comparer(self._arbre_blesse(5, True),
                           self._arbre_blesse(7, True))
        self.assertEqual(i.conclusion, Conclusion.PROGRESSION)
        self.assertAlmostEqual(i.brins[0].progression_max, 2.0)

    def test_couche_degradee_qui_diminue_est_a_verifier(self):
        i = self._comparer(self._arbre_blesse(5), self._arbre_blesse(3, True))
        self.assertEqual(i.conclusion, Conclusion.A_VERIFIER)
        self.assertIn(Alerte.COUCHE_REDUITE, i.brins[0].alertes)

    def test_persistance_et_ancien_fichier(self):
        c = Chantier(arbres=[self._arbre_blesse(5, True)])
        deg = _aller_retour(c).arbres[0].brins[0].degradations_externes[0]
        self.assertTrue(deg.recouverte)
        self.assertFalse(DegradationExterne().recouverte)


if __name__ == "__main__":
    unittest.main()
