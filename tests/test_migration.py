"""Tests de la compatibilité ascendante des fichiers `.json`.

Le CLAUDE.md le dit explicitement : « l'app doit toujours pouvoir ouvrir
les anciens fichiers ». La migration silencieuse est dans
`Chantier.from_dict`. Si un de ces tests casse, c'est qu'on a perdu la
compatibilité avec un format de mission déjà enregistré sur le terrain.
"""

from __future__ import annotations

import unittest

from model import (
    FORMAT_VERSION,
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

    def test_port_normalise_casse_et_espaces(self):
        # Variations de casse ou espaces : le port est normalisé à la
        # forme canonique attendue par classer_prbs.
        for raw, expected in (("LIBRE", "libre"),
                              ("  Architecturé  ", "architecturé"),
                              ("Semi-Libre", "semi-libre")):
            with self.subTest(raw=raw):
                d = {"arbres": [{"numero_arbre": "1", "port_arbre": raw}]}
                c = Chantier.from_dict(d)
                self.assertEqual(c.arbres[0].port_arbre, expected)

    def test_port_inconnu_fallback_libre(self):
        # Faute de frappe ou libellé jamais supporté : on retombe sur
        # "libre" (défaut le moins permissif) plutôt que de laisser une
        # valeur qui ferait silencieusement basculer classer_prbs sur le
        # groupe libre par défaut, sans signal. Un WARNING est émis sur
        # le logger applicatif pour que l'opérateur puisse en prendre
        # connaissance.
        d = {"arbres": [{"numero_arbre": "1", "port_arbre": "libbre"}]}
        with self.assertLogs("penetrometre", level="WARNING") as cm:
            c = Chantier.from_dict(d)
        self.assertEqual(c.arbres[0].port_arbre, "libre")
        self.assertTrue(any("libbre" in m for m in cm.output))

    def test_port_vide_fallback_libre(self):
        d = {"arbres": [{"numero_arbre": "1", "port_arbre": ""}]}
        with self.assertLogs("penetrometre", level="WARNING"):
            c = Chantier.from_dict(d)
        self.assertEqual(c.arbres[0].port_arbre, "libre")

    def test_json_sans_format_version_est_lisible(self):
        # Anciens fichiers pré-versionnés : pas de clé format_version.
        # `from_dict` doit les charger sans broncher.
        d = {"nom": "Ancien", "arbres": [
            {"numero_arbre": "1", "rayon_tronc_cm": 20.0}]}
        self.assertNotIn("format_version", d)
        c = Chantier.from_dict(d)
        self.assertEqual(c.nom, "Ancien")
        self.assertEqual(len(c.arbres), 1)


class FormatVersionTests(unittest.TestCase):
    """Le JSON écrit par to_dict porte un champ format_version."""

    def test_to_dict_inclut_format_version(self):
        c = Chantier(nom="X")
        d = c.to_dict()
        self.assertEqual(d.get("format_version"), FORMAT_VERSION)

    def test_format_futur_log_warning(self):
        # Fichier produit par une version plus récente que la nôtre :
        # le chargement reste possible (clés inconnues filtrées) mais
        # un warning est émis pour signaler que des champs récents ont
        # potentiellement été ignorés.
        d = {"format_version": FORMAT_VERSION + 5, "nom": "futur",
             "arbres": []}
        with self.assertLogs("penetrometre", level="WARNING") as cm:
            c = Chantier.from_dict(d)
        self.assertEqual(c.nom, "futur")
        self.assertTrue(any("format" in m.lower() for m in cm.output))

    def test_format_version_egale_pas_de_warning(self):
        d = {"format_version": FORMAT_VERSION, "nom": "present",
             "arbres": []}
        # Pas de warning attendu — un with assertLogs lèverait
        # AssertionError si rien n'est loggé, donc on bascule sur
        # assertNoLogs (Python 3.10+) ou inspection manuelle.
        import logging
        logger = logging.getLogger("penetrometre")
        with self.assertLogs(logger, level="WARNING") as cm:
            # On émet un warning factice pour que le context manager
            # ne lève pas, puis on vérifie qu'aucun de nos messages
            # n'est dans le buffer.
            c = Chantier.from_dict(d)
            logger.warning("sentinel")
        self.assertEqual(c.nom, "present")
        self.assertFalse(any("Fichier au format" in m for m in cm.output))


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

    def test_from_dict_ne_mute_pas_l_entree(self):
        # Verrou de non-effet-de-bord : un dict passé à from_dict doit
        # rester intact pour que le caller puisse le réutiliser
        # (sérialisation, log, comparaison, etc.). Régression possible
        # si quelqu'un remet un `a.pop(...)` dans la boucle des arbres.
        import copy
        d = {
            "nom": "Test",
            "arbres": [{
                "numero_arbre": "1",
                "rayon_tronc_cm": 18.0,
                "port_arbre": "Libre, semi-libre ou traumatique",  # legacy
                "sondages": [{"numero": 1, "grade": 0,
                              "bois_sain_cm": 5.0, "bois_altere_cm": 3.0}],
                "degradations_externes": [{"numero": 1, "grade_debut": 0,
                                            "grade_fin": 50,
                                            "profondeur_cm": 1.0}],
                "contreforts": [{"numero": 1, "grade_centre": 100,
                                  "largeur_grades": 50,
                                  "longueur_cm": 8.0}],
            }],
        }
        snapshot = copy.deepcopy(d)
        Chantier.from_dict(d)
        self.assertEqual(d, snapshot)

    def test_champs_inconnus_ignores(self):
        # Compatibilité descendante : un JSON futur peut contenir des
        # champs qu'une ancienne version de l'app ne connaît pas
        # encore. from_dict doit les ignorer silencieusement plutôt que
        # planter avec TypeError sur "unexpected keyword argument".
        d = {
            "nom": "Future",
            "_version_future": "v9.9",          # clé inconnue niveau Chantier
            "arbres": [{
                "numero_arbre": "1",
                "rayon_tronc_cm": 18.0,
                "futur_metier_inconnu": 42,    # clé inconnue niveau Arbre
                "sondages": [{
                    "numero": 1, "grade": 0,
                    "bois_sain_cm": 10.0, "bois_altere_cm": 8.0,
                    "nouveau_champ": "X",      # clé inconnue niveau Sondage
                }],
                "degradations_externes": [{
                    "numero": 1, "grade_debut": 50, "grade_fin": 100,
                    "profondeur_cm": 2.0,
                    "tag_v9": True,            # clé inconnue niveau Dégradation
                }],
                "contreforts": [{
                    "numero": 1, "grade_centre": 0,
                    "largeur_grades": 50, "longueur_cm": 10.0,
                    "stade_v9": "active",      # clé inconnue niveau Contrefort
                }],
            }],
        }
        c = Chantier.from_dict(d)  # ne doit PAS lever
        self.assertEqual(c.nom, "Future")
        self.assertEqual(len(c.arbres), 1)
        a = c.arbres[0]
        self.assertEqual(a.numero_arbre, "1")
        self.assertAlmostEqual(a.rayon_tronc_cm, 18.0)
        self.assertEqual(len(a.sondages), 1)
        self.assertEqual(len(a.degradations_externes), 1)
        self.assertEqual(len(a.contreforts), 1)


if __name__ == "__main__":
    unittest.main()
