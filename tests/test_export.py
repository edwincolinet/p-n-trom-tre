"""Tests de la construction des données du tableau PRBS d'un arbre.

On teste uniquement la fonction pure `prbs_table_rows_par_sondage`
(export.py). Les exports XLSX et HTML eux-mêmes sont vérifiés en
smoke-test : ce qui peut casser silencieusement, c'est la mauvaise
donnée envoyée au formateur, pas le formateur lui-même.
"""

from __future__ import annotations

import unittest

from bareme import classer_prbs
from export import prbs_table_rows_par_sondage
from model import (
    Arbre,
    DegradationExterne,
    Sondage,
)


class PrbsTableRowsParSondageTests(unittest.TestCase):

    def test_aucun_sondage_renvoie_liste_vide(self):
        a = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        rows = prbs_table_rows_par_sondage(a, classer_prbs)
        self.assertEqual(rows, [])

    def test_une_ligne_par_sondage_triee_par_numero(self):
        a = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        a.sondages.append(Sondage(numero=2, grade=100,
                                    bois_sain_cm=15.0, bois_altere_cm=5.0))
        a.sondages.append(Sondage(numero=1, grade=0,
                                    bois_sain_cm=14.0, bois_altere_cm=6.0))
        rows = prbs_table_rows_par_sondage(a, classer_prbs)
        self.assertEqual(len(rows), 2)
        self.assertEqual([r["numero"] for r in rows], [1, 2])

    def test_colonnes_fondamentales_par_sondage(self):
        a = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        a.sondages.append(Sondage(numero=7, grade=100,
                                    bois_sain_cm=15.0, bois_altere_cm=5.0,
                                    compartimentation="active"))
        a.sondages.append(Sondage(numero=8, grade=300,
                                    bois_sain_cm=14.0, bois_altere_cm=6.0))
        rows = prbs_table_rows_par_sondage(a, classer_prbs)
        ligne_7 = next(r for r in rows if r["numero"] == 7)
        self.assertEqual(ligne_7["grade"], 100)
        self.assertEqual(ligne_7["rayon_cm"], 20.0)
        self.assertEqual(ligne_7["prbs_cm"], 15.0)
        self.assertEqual(ligne_7["bois_altere_cm"], 5.0)
        self.assertEqual(ligne_7["compartimentation"], "active")
        # t/R doit être compatible avec PRBS / Rayon en l'absence de
        # dégradation externe (= 15/20 = 0.75).
        self.assertAlmostEqual(ligne_7["ratio_tR"], 0.75, places=3)

    def test_ratio_tR_ajuste_de_la_degradation_externe(self):
        # Sans dégradation externe : t/R = PRBS/R = 15/20 = 0.75.
        # Avec dégradation externe profondeur 3 cm sur ce grade :
        # t/R ajusté = (15-3)/20 = 0.60.
        a = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        a.sondages.append(Sondage(numero=1, grade=100,
                                    bois_sain_cm=15.0, bois_altere_cm=5.0))
        # 2e sondage présent pour le réalisme ; la table par-sondage est
        # calculée ligne par ligne, indépendamment du seuil de fiabilité
        # du diagnostic global.
        a.sondages.append(Sondage(numero=2, grade=300,
                                    bois_sain_cm=14.0, bois_altere_cm=6.0))
        a.degradations_externes.append(
            DegradationExterne(grade_debut=100, grade_fin=100,
                                profondeur_cm=3.0))
        rows = prbs_table_rows_par_sondage(a, classer_prbs)
        ligne = next(r for r in rows if r["numero"] == 1)
        # PRBS brute reste 15 (mesure directe du sondage).
        self.assertEqual(ligne["prbs_cm"], 15.0)
        # t/R, lui, est ajusté.
        self.assertAlmostEqual(ligne["ratio_tR"], 0.60, places=3)

    def test_classe_assignee_par_le_bareme(self):
        # Port libre : Vert > 0.30, Orange [0.15, 0.30], Rouge < 0.15.
        a = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        a.sondages.append(Sondage(numero=1, grade=0,
                                    bois_sain_cm=15.0, bois_altere_cm=5.0))
        a.sondages.append(Sondage(numero=2, grade=200,
                                    bois_sain_cm=2.0, bois_altere_cm=18.0))
        rows = prbs_table_rows_par_sondage(a, classer_prbs)
        ligne_1 = next(r for r in rows if r["numero"] == 1)
        ligne_2 = next(r for r in rows if r["numero"] == 2)
        self.assertEqual(ligne_1["classe"], "Vert")    # 0.75
        self.assertEqual(ligne_2["classe"], "Rouge")   # 0.10


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

            # Vérification structure : on retrouve l'en-tête du
            # tableau et autant de lignes que de sondages.
            #
            # Note : on passe un file handle explicite à `load_workbook`
            # plutôt que le chemin. Sur openpyxl, `Workbook.close()` ne
            # ferme pas toujours le ZipFile sous-jacent en mode lecture
            # normale → ResourceWarning à la GC. Avec un `with open(...)`,
            # le BufferedReader est garanti fermé en sortie de bloc.
            import openpyxl
            with open(path, "rb") as f:
                wb = openpyxl.load_workbook(f)
            ws = wb.active
            header_row = next(
                row for row in range(1, 30)
                if ws.cell(row=row, column=1).value == "Sondage")
            # 2 sondages → 2 lignes de données, numéros 1 et 2.
            numeros = [ws.cell(row=header_row + 1 + k, column=1).value
                       for k in range(2)]
            self.assertEqual(numeros, [1, 2])

            # Largeurs de colonnes appliquées correctement (régression
            # historique : MergedCell sur la ligne 1 cassait la boucle
            # `ws.column_dimensions[...].width = ...`).
            self.assertGreater(ws.column_dimensions["A"].width, 0)
            self.assertGreater(ws.column_dimensions["G"].width, 0)
        finally:
            if os.path.exists(path):
                os.unlink(path)


if __name__ == "__main__":
    unittest.main()
