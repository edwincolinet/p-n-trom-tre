"""Tests d'intégration : load → mutation → save → reload → vérification.

Couvre le câblage entre les modules (model, persistence, diagnostic) dans
un scénario réaliste : une mission JSON est chargée, mutée (ajout de
sondage, changement de rayon, ajout/suppression de dégradation), puis
round-trippée via save/load. On vérifie que le diagnostic post-reload
est identique à celui pré-save.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from diagnostic import ratio_tR_par_grade, repartition_classes
from model import Arbre, DegradationExterne, Sondage
from persistence import chantier_from_dict, load_chantier, save_chantier


class RoundTripIntegrationTests(unittest.TestCase):
    """Save → load préserve l'intégralité des données et du diagnostic."""

    def _build_mission(self) -> dict:
        return {
            "nom": "Mission test intégration",
            "adresse": "12 rue des Tilleuls",
            "operateur": "Test",
            "date_releve": "24/05/2026",
            "arbres": [{
                "numero_arbre": "1",
                "essence": "Chêne",
                "rayon_tronc_cm": 25.0,
                "epaisseur_ecorce_cm": 1.5,
                "port_arbre": "libre",
                "sondages": [
                    {"numero": 1, "grade": 0, "bois_sain_cm": 20.0,
                     "bois_altere_cm": 5.0, "compartimentation": "oui"},
                    {"numero": 2, "grade": 100, "bois_sain_cm": 15.0,
                     "bois_altere_cm": 10.0, "compartimentation": "-"},
                    {"numero": 3, "grade": 200, "bois_sain_cm": 22.0,
                     "bois_altere_cm": 3.0, "compartimentation": "non"},
                ],
                "degradations_externes": [
                    {"numero": 1, "grade_debut": 75, "grade_fin": 125,
                     "profondeur_cm": 3.0},
                ],
                "contreforts": [
                    {"numero": 1, "grade_centre": 300,
                     "largeur_grades": 75, "longueur_cm": 8.0},
                ],
            }],
        }

    def test_round_trip_preserve_diagnostic(self):
        chantier = chantier_from_dict(self._build_mission())
        arbre = chantier.arbres[0]

        snap_before = repartition_classes(arbre)

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = Path(f.name)
        try:
            save_chantier(chantier, path)
            reloaded = load_chantier(path)
        finally:
            path.unlink()

        arbre2 = reloaded.arbres[0]
        snap_after = repartition_classes(arbre2)

        self.assertEqual(snap_before.tR_moyen, snap_after.tR_moyen)
        self.assertEqual(snap_before.classe_globale, snap_after.classe_globale)
        self.assertEqual(snap_before.ratios, snap_after.ratios)

    def test_set_rayon_then_round_trip(self):
        """Changer le rayon puis sauvegarder : la PRBS est préservée."""
        chantier = chantier_from_dict(self._build_mission())
        arbre = chantier.arbres[0]

        prbs_avant = [s.prbs_cm for s in arbre.sondages]
        arbre.set_rayon(30.0)
        prbs_apres_set = [s.prbs_cm for s in arbre.sondages]
        self.assertEqual(prbs_avant, prbs_apres_set)

        for s in arbre.sondages:
            self.assertAlmostEqual(s.bois_sain_cm + s.bois_altere_cm, 30.0)

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = Path(f.name)
        try:
            save_chantier(chantier, path)
            reloaded = load_chantier(path)
        finally:
            path.unlink()

        for s_orig, s_rel in zip(arbre.sondages, reloaded.arbres[0].sondages):
            self.assertAlmostEqual(s_orig.bois_sain_cm, s_rel.bois_sain_cm)
            self.assertAlmostEqual(s_orig.bois_altere_cm, s_rel.bois_altere_cm)


class MutationIntegrationTests(unittest.TestCase):
    """Vérifie que les opérations de mutation typiques de l'UI gardent
    le modèle cohérent bout en bout."""

    def test_ajout_sondage_et_renumerotation(self):
        arbre = Arbre(rayon_tronc_cm=20.0)
        arbre.sondages.append(Sondage(grade=0, bois_sain_cm=15.0,
                                       bois_altere_cm=5.0))
        arbre.sondages.append(Sondage(grade=100, bois_sain_cm=12.0,
                                       bois_altere_cm=8.0))
        arbre.renumeroter_sondages()

        self.assertEqual(arbre.sondages[0].numero, 1)
        self.assertEqual(arbre.sondages[1].numero, 2)

        # Suppression du premier → renumérotation
        del arbre.sondages[0]
        arbre.renumeroter_sondages()
        self.assertEqual(arbre.sondages[0].numero, 1)
        self.assertEqual(arbre.sondages[0].grade, 100)

    def test_ajout_degradation_impacte_diagnostic(self):
        arbre = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        arbre.sondages.append(Sondage(grade=100, bois_sain_cm=18.0,
                                       bois_altere_cm=2.0))
        arbre.sondages.append(Sondage(grade=200, bois_sain_cm=16.0,
                                       bois_altere_cm=4.0))

        ratios_sans_deg = ratio_tR_par_grade(arbre)

        arbre.degradations_externes.append(
            DegradationExterne(grade_debut=75, grade_fin=125,
                               profondeur_cm=5.0))

        ratios_avec_deg = ratio_tR_par_grade(arbre)

        # La dégradation au grade 100 doit réduire le ratio t/R
        idx_100 = 4  # grade 100 = index 4
        self.assertLess(ratios_avec_deg[idx_100], ratios_sans_deg[idx_100])

    def test_set_rayon_borne_degradation(self):
        """set_rayon borne la profondeur des dégradations au nouveau rayon."""
        arbre = Arbre(rayon_tronc_cm=20.0)
        arbre.degradations_externes.append(
            DegradationExterne(profondeur_cm=15.0))

        arbre.set_rayon(10.0)
        self.assertEqual(arbre.degradations_externes[0].profondeur_cm, 10.0)

    def test_diagnostic_non_fiable_avec_un_seul_sondage(self):
        arbre = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        arbre.sondages.append(Sondage(grade=0, bois_sain_cm=10.0,
                                       bois_altere_cm=10.0))

        snap = repartition_classes(arbre)
        self.assertFalse(snap.diagnostic_fiable)
        self.assertIsNone(snap.diagnostic_global)

    def test_diagnostic_non_fiable_avec_deux_sondages(self):
        # Seuil métier : il faut désormais 3 directions sondées.
        arbre = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        arbre.sondages.append(Sondage(grade=0, bois_sain_cm=10.0,
                                       bois_altere_cm=10.0))
        arbre.sondages.append(Sondage(grade=200, bois_sain_cm=15.0,
                                       bois_altere_cm=5.0))

        snap = repartition_classes(arbre)
        self.assertFalse(snap.diagnostic_fiable)
        self.assertIsNone(snap.diagnostic_global)

    def test_diagnostic_fiable_avec_trois_sondages(self):
        arbre = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        arbre.sondages.append(Sondage(grade=0, bois_sain_cm=10.0,
                                       bois_altere_cm=10.0))
        arbre.sondages.append(Sondage(grade=100, bois_sain_cm=12.0,
                                       bois_altere_cm=8.0))
        arbre.sondages.append(Sondage(grade=200, bois_sain_cm=15.0,
                                       bois_altere_cm=5.0))

        snap = repartition_classes(arbre)
        self.assertTrue(snap.diagnostic_fiable)
        self.assertIsNotNone(snap.diagnostic_global)


if __name__ == "__main__":
    unittest.main()
