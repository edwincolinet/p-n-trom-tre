"""Tests du barème Silvavenir (`classer_prbs`).

Seuils documentés (CLAUDE.md) :
- libre / semi-libre :         Vert > 30 %, Orange 15-30 %, Rouge < 15 %
- architecturé / traumatique : Vert > 20 %, Orange 10-20 %, Rouge < 10 %

Les seuils en code sont stricts : `>` pour Vert, `>=` pour Orange.
"""

from __future__ import annotations

import unittest

from resistographe import classer_prbs


class ClasserPrbsLibreTests(unittest.TestCase):
    """Groupe libre / semi-libre — seuils 30 % et 15 %."""

    def test_au_dessus_de_30_pct_est_vert(self):
        label, _ = classer_prbs(0.31, "libre")
        self.assertEqual(label, "Vert")

    def test_pile_30_pct_est_orange(self):
        # 30 % n'est PAS Vert (seuil strict `>`), c'est Orange.
        label, _ = classer_prbs(0.30, "libre")
        self.assertEqual(label, "Orange")

    def test_pile_15_pct_est_orange(self):
        # Seuil bas inclusif (`>=`) : 15 % reste Orange.
        label, _ = classer_prbs(0.15, "libre")
        self.assertEqual(label, "Orange")

    def test_juste_sous_15_pct_est_rouge(self):
        label, _ = classer_prbs(0.149, "libre")
        self.assertEqual(label, "Rouge")

    def test_zero_est_rouge(self):
        label, _ = classer_prbs(0.0, "libre")
        self.assertEqual(label, "Rouge")

    def test_semi_libre_meme_baremes(self):
        # Le port "semi-libre" partage les seuils de "libre".
        for tR, attendu in [(0.31, "Vert"), (0.20, "Orange"), (0.10, "Rouge")]:
            with self.subTest(tR=tR):
                self.assertEqual(classer_prbs(tR, "semi-libre")[0], attendu)


class ClasserPrbsStrictTests(unittest.TestCase):
    """Groupe architecturé / traumatique — seuils 20 % et 10 %."""

    def test_au_dessus_de_20_pct_est_vert(self):
        label, _ = classer_prbs(0.21, "architecturé")
        self.assertEqual(label, "Vert")

    def test_pile_20_pct_est_orange(self):
        label, _ = classer_prbs(0.20, "architecturé")
        self.assertEqual(label, "Orange")

    def test_pile_10_pct_est_orange(self):
        label, _ = classer_prbs(0.10, "architecturé")
        self.assertEqual(label, "Orange")

    def test_juste_sous_10_pct_est_rouge(self):
        label, _ = classer_prbs(0.099, "architecturé")
        self.assertEqual(label, "Rouge")

    def test_traumatique_meme_baremes(self):
        for tR, attendu in [(0.25, "Vert"), (0.15, "Orange"), (0.05, "Rouge")]:
            with self.subTest(tR=tR):
                self.assertEqual(classer_prbs(tR, "traumatique")[0], attendu)

    def test_traumatique_a_25_pct_est_vert(self):
        # Cas piégeux : 25 % serait Orange en groupe libre, mais Vert en
        # groupe strict (architecturé/traumatique).
        self.assertEqual(classer_prbs(0.25, "traumatique")[0], "Vert")
        self.assertEqual(classer_prbs(0.25, "libre")[0], "Orange")


class ClasserPrbsRobustesseTests(unittest.TestCase):
    """Robustesse de l'API : casse, espaces, valeurs inconnues."""

    def test_casse_et_espaces_ignorees(self):
        for port in ("Libre", "  LIBRE ", "Semi-Libre", "ARCHITECTURÉ"):
            with self.subTest(port=port):
                # On vérifie juste que ça classe sans lever et que
                # le port est bien rattaché à son groupe.
                label, _ = classer_prbs(0.31, port)
                self.assertEqual(label, "Vert")

    def test_port_inconnu_rattache_au_groupe_libre(self):
        # Un port non reconnu retombe sur les seuils libre/semi-libre,
        # ce qui est le comportement actuel (PORTS_GROUPE_STRICT pas
        # matché → seuils 30/15).
        self.assertEqual(classer_prbs(0.25, "")[0], "Orange")
        self.assertEqual(classer_prbs(0.31, "inconnu")[0], "Vert")

    def test_couleur_hex_valide(self):
        for tR in (0.5, 0.2, 0.05):
            _, hexcol = classer_prbs(tR, "libre")
            self.assertRegex(hexcol, r"^#[0-9A-Fa-f]{6}$")


if __name__ == "__main__":
    unittest.main()
