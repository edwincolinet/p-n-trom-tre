"""Tests de la compatibilité ascendante des fichiers `.json`.

Le CLAUDE.md le dit explicitement : « l'app doit toujours pouvoir ouvrir
les anciens fichiers ». La migration silencieuse est dans
`Chantier.from_dict`. Si un de ces tests casse, c'est qu'on a perdu la
compatibilité avec un format de mission déjà enregistré sur le terrain.
"""

from __future__ import annotations

import unittest

from model import (
    Arbre,
    Chantier,
    Contrefort,
    DegradationExterne,
    Sondage,
)


class FromDictTests(unittest.TestCase):

    def test_dict_minimal(self):
        c = Chantier.from_dict({})
        self.assertEqual(c.nom, "")
        self.assertEqual(c.adresse, "")
        self.assertEqual(c.arbres, [])

    def test_arbre_sans_contreforts_donne_liste_vide(self):
        # Format antérieur à v3.3 : pas de clé "contreforts" dans l'arbre.
        # L'app actuelle doit l'ouvrir et créer une liste vide.
        d = {"arbres": [{"numero_arbre": "A1", "rayon_tronc_cm": 18.0}]}
        c = Chantier.from_dict(d)
        self.assertEqual(len(c.arbres), 1)
        self.assertEqual(c.arbres[0].contreforts, [])

    def test_arbre_sans_degradations_externes(self):
        d = {"arbres": [{"numero_arbre": "B2", "rayon_tronc_cm": 18.0}]}
        c = Chantier.from_dict(d)
        self.assertEqual(c.arbres[0].degradations_externes, [])

    def test_port_legacy_libre_semi_libre_traumatique(self):
        # Ancien libellé v3.1 : groupé "Libre, semi-libre ou traumatique"
        # → migré silencieusement vers "libre".
        d = {"arbres": [{
            "numero_arbre": "1",
            "port_arbre": "Libre, semi-libre ou traumatique",
        }]}
        c = Chantier.from_dict(d)
        self.assertEqual(c.arbres[0].port_arbre, "libre")

    def test_port_legacy_architecture_traumatique(self):
        d = {"arbres": [{
            "numero_arbre": "1",
            "port_arbre": "Architecturé ou traumatique",
        }]}
        c = Chantier.from_dict(d)
        self.assertEqual(c.arbres[0].port_arbre, "architecturé")

    def test_port_recent_preserve(self):
        for port in ("libre", "semi-libre", "architecturé", "traumatique"):
            with self.subTest(port=port):
                d = {"arbres": [{"numero_arbre": "1", "port_arbre": port}]}
                c = Chantier.from_dict(d)
                self.assertEqual(c.arbres[0].port_arbre, port)


class RoundTripTests(unittest.TestCase):
    """Sérialisation → désérialisation : le contenu doit être préservé."""

    def test_chantier_complet_roundtrip(self):
        c = Chantier(nom="Mission test", adresse="42 rue des chênes",
                     operateur="EC", date_releve="01/05/2026")
        a = Arbre(numero_arbre="1", essence="Platane",
                   rayon_tronc_cm=22.5, port_arbre="semi-libre",
                   meche_cm=40.0, epaisseur_ecorce_cm=1.5)
        a.sondages.append(Sondage(numero=1, grade=0,
                                    bois_sain_cm=18.0, bois_altere_cm=4.5,
                                    compartimentation="active"))
        a.degradations_externes.append(
            DegradationExterne(numero=1, grade_debut=50, grade_fin=100,
                                profondeur_cm=2.0,
                                commentaire="cicatrice"))
        a.contreforts.append(
            Contrefort(numero=1, grade_centre=200,
                        largeur_grades=75, longueur_cm=12.0))
        c.arbres.append(a)

        d = c.to_dict()
        c2 = Chantier.from_dict(d)

        self.assertEqual(c2.nom, c.nom)
        self.assertEqual(c2.adresse, c.adresse)
        self.assertEqual(c2.operateur, c.operateur)
        self.assertEqual(c2.date_releve, c.date_releve)
        self.assertEqual(len(c2.arbres), 1)

        a2 = c2.arbres[0]
        self.assertEqual(a2.numero_arbre, "1")
        self.assertEqual(a2.essence, "Platane")
        self.assertAlmostEqual(a2.rayon_tronc_cm, 22.5)
        self.assertEqual(a2.port_arbre, "semi-libre")
        self.assertAlmostEqual(a2.epaisseur_ecorce_cm, 1.5)

        self.assertEqual(len(a2.sondages), 1)
        self.assertEqual(a2.sondages[0].grade, 0)
        self.assertAlmostEqual(a2.sondages[0].bois_sain_cm, 18.0)
        self.assertEqual(a2.sondages[0].compartimentation, "active")

        self.assertEqual(len(a2.degradations_externes), 1)
        self.assertEqual(a2.degradations_externes[0].grade_debut, 50)
        self.assertAlmostEqual(
            a2.degradations_externes[0].profondeur_cm, 2.0)

        self.assertEqual(len(a2.contreforts), 1)
        self.assertEqual(a2.contreforts[0].grade_centre, 200)
        self.assertAlmostEqual(a2.contreforts[0].longueur_cm, 12.0)

    def test_arbres_multiples_preserves(self):
        c = Chantier(nom="Multi")
        c.arbres.append(Arbre(numero_arbre="A", rayon_tronc_cm=15.0))
        c.arbres.append(Arbre(numero_arbre="B", rayon_tronc_cm=22.0))
        c.arbres.append(Arbre(numero_arbre="C", rayon_tronc_cm=30.0))
        c2 = Chantier.from_dict(c.to_dict())
        self.assertEqual([a.numero_arbre for a in c2.arbres],
                         ["A", "B", "C"])
        self.assertAlmostEqual(c2.arbres[1].rayon_tronc_cm, 22.0)


if __name__ == "__main__":
    unittest.main()
