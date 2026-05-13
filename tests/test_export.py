"""Tests de la construction des données du tableau PRBS d'un arbre.

On teste uniquement la fonction pure `prbs_table_rows` (export.py). Les
exports XLSX et HTML eux-mêmes sont vérifiés en smoke-test manuel : ce
qui peut casser silencieusement, c'est la mauvaise donnée envoyée au
formateur, pas le formateur lui-même.
"""

from __future__ import annotations

import unittest

from bareme import classer_prbs
from export import prbs_table_rows
from model import (
    Arbre,
    DegradationExterne,
    Sondage,
)


class PrbsTableRowsTests(unittest.TestCase):

    def test_seize_lignes_meme_sans_sondage(self):
        a = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        rows = prbs_table_rows(a, classer_prbs)
        self.assertEqual(len(rows), 16)
        # Sans sondages : aucune direction n'est marquée sondée.
        self.assertTrue(all(not r["sonde"] for r in rows))
        # PRBS = R partout.
        self.assertTrue(all(abs(r["prbs_cm"] - 20.0) < 1e-9 for r in rows))

    def test_grades_dans_l_ordre(self):
        a = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        rows = prbs_table_rows(a, classer_prbs)
        self.assertEqual([r["grade"] for r in rows],
                         [i * 25 for i in range(16)])

    def test_directions_cardinales_uniquement(self):
        a = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        rows = prbs_table_rows(a, classer_prbs)
        # Cardinales aux multiples de 50 (N, NE, E, SE, S, SO, O, NO).
        cardinales = {r["grade"]: r["direction"]
                      for r in rows if r["direction"]}
        self.assertEqual(cardinales,
                         {0: "N", 50: "NE", 100: "E", 150: "SE",
                          200: "S", 250: "SO", 300: "O", 350: "NO"})

    def test_sondage_direct_marque_la_direction(self):
        a = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        a.sondages.append(Sondage(numero=7, grade=100,
                                    bois_sain_cm=15.0, bois_altere_cm=5.0,
                                    compartimentation="active"))
        # Au moins 2 sondages requis pour l'extrapolation, mais on teste
        # seulement la ligne du sondage direct ici, pas l'extrapolation.
        a.sondages.append(Sondage(numero=8, grade=300,
                                    bois_sain_cm=14.0, bois_altere_cm=6.0))
        rows = prbs_table_rows(a, classer_prbs)
        ligne_E = next(r for r in rows if r["grade"] == 100)
        self.assertTrue(ligne_E["sonde"])
        self.assertEqual(ligne_E["sondage_numeros"], [7])
        self.assertEqual(ligne_E["compartimentation"], "active")

    def test_degradation_externe_reflete_dans_la_ligne(self):
        a = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        a.sondages.append(Sondage(numero=1, grade=0, bois_altere_cm=2.0))
        a.sondages.append(Sondage(numero=2, grade=200, bois_altere_cm=2.0))
        a.degradations_externes.append(
            DegradationExterne(grade_debut=100, grade_fin=100,
                                profondeur_cm=3.0))
        rows = prbs_table_rows(a, classer_prbs)
        ligne_E = next(r for r in rows if r["grade"] == 100)
        # PRBS au grade 100 = R - alt(extrapolée) - 3 (dégradation ext.)
        # alt ext. au grade 100 = 3
        self.assertAlmostEqual(ligne_E["deg_ext_cm"], 3.0)
        # PRBS = 20 - alt_int - 3
        self.assertLess(ligne_E["prbs_cm"], 20.0 - 3.0)


class XlsxAvailabilityTests(unittest.TestCase):
    """Ces tests documentent le comportement quand openpyxl n'est pas
    présent : on doit lever un message clair, pas planter en
    AttributeError n'importe où dans le code."""

    def test_export_xlsx_sans_openpyxl_leve_runtime_error(self):
        from export import HAS_OPENPYXL, export_prbs_xlsx
        if HAS_OPENPYXL:
            self.skipTest("openpyxl est installé sur cette machine")
        from model import Arbre, Chantier
        from palette import COULEUR_CLASSE
        a = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        c = Chantier()
        with self.assertRaises(RuntimeError) as ctx:
            export_prbs_xlsx(a, c, "/tmp/should_not_be_created.xlsx",
                              couleur_classe=COULEUR_CLASSE,
                              classer_prbs=classer_prbs)
        self.assertIn("openpyxl", str(ctx.exception).lower())


class XlsxSmokeTests(unittest.TestCase):
    """Smoke test du chemin XLSX bout-en-bout, exécuté seulement si
    openpyxl est installé. Couvre une régression historique :
    l'ajustement des largeurs de colonnes ne doit PAS plomber sur les
    lignes contenant des cellules fusionnées (`MergedCell` n'a pas
    d'attribut `column_letter`).
    """

    def setUp(self):
        from export import HAS_OPENPYXL
        if not HAS_OPENPYXL:
            self.skipTest("openpyxl absent")

    def test_export_complet_ne_plante_pas(self):
        import os
        import tempfile

        from export import export_prbs_xlsx
        from model import Arbre, Chantier, DegradationExterne, Sondage
        from palette import COULEUR_CLASSE

        a = Arbre(numero_arbre="42", essence="Platane",
                   rayon_tronc_cm=20.0, port_arbre="libre",
                   epaisseur_ecorce_cm=1.5,
                   commentaire="Test smoke xlsx")
        a.sondages.append(Sondage(numero=1, grade=0,
                                    bois_sain_cm=15.0, bois_altere_cm=5.0))
        a.sondages.append(Sondage(numero=2, grade=200,
                                    bois_sain_cm=12.0, bois_altere_cm=8.0))
        a.degradations_externes.append(
            DegradationExterne(grade_debut=125, grade_fin=175,
                                profondeur_cm=2.0))
        c = Chantier(nom="Mission test", adresse="42 rue test",
                      operateur="EC", date_releve="08/05/2026")
        c.arbres.append(a)

        with tempfile.NamedTemporaryFile(suffix=".xlsx",
                                          delete=False) as tmp:
            path = tmp.name
        try:
            export_prbs_xlsx(a, c, path,
                              couleur_classe=COULEUR_CLASSE,
                              classer_prbs=classer_prbs)
            self.assertGreater(os.path.getsize(path), 1000)

            # Vérification structure : les 16 lignes de directions
            # sont écrites avec les bons grades.
            import openpyxl
            wb = openpyxl.load_workbook(path)
            ws = wb.active
            # On cherche la ligne d'en-tête puis on lit les 16 suivantes.
            header_row = next(
                row for row in range(1, 30)
                if ws.cell(row=row, column=1).value == "Grade (gr)")
            grades = [ws.cell(row=header_row + 1 + k, column=1).value
                      for k in range(16)]
            self.assertEqual(grades, [i * 25 for i in range(16)])

            # Largeurs de colonnes appliquées correctement (régression
            # historique : MergedCell sur la ligne 1 cassait la boucle
            # `ws.column_dimensions[...].width = ...`).
            self.assertGreater(ws.column_dimensions["A"].width, 0)
            self.assertGreater(ws.column_dimensions["J"].width, 0)
        finally:
            if os.path.exists(path):
                os.unlink(path)


if __name__ == "__main__":
    unittest.main()
