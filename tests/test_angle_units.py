"""Unité d'affichage des angles (grades / degrés) — `angle_units` et ses
points d'application. Le modèle reste en grades : seuls l'affichage, la
saisie et les exports changent."""

from __future__ import annotations

import unittest

import angle_units
from dialogs_shared import (
    find_grade_choice,
    grade_choices,
    largeur_grades_saisie,
    parse_grade,
)


class _Unite(unittest.TestCase):
    def setUp(self) -> None:
        angle_units.set_unite(angle_units.GRADE)

    def tearDown(self) -> None:
        angle_units.set_unite(angle_units.GRADE)


class FormatTests(_Unite):
    def test_grades_par_defaut(self):
        self.assertEqual(angle_units.fmt(100), "100 gr")
        self.assertEqual(angle_units.nombre(25), "25")

    def test_degres(self):
        angle_units.set_unite(angle_units.DEGRE)
        self.assertEqual(angle_units.fmt(100), "90°")
        self.assertEqual(angle_units.fmt(25), "22.5°")
        self.assertEqual(angle_units.fmt(0), "0°")
        self.assertEqual(angle_units.fmt(375), "337.5°")

    def test_unite_inconnue_retombe_sur_grades(self):
        angle_units.set_unite("radian")
        self.assertEqual(angle_units.get_unite(), angle_units.GRADE)

    def test_parse_suffixe_prime_sur_unite_courante(self):
        self.assertEqual(angle_units.parse("90°"), 100.0)
        angle_units.set_unite(angle_units.DEGRE)
        self.assertEqual(angle_units.parse("100 gr"), 100.0)
        self.assertEqual(angle_units.parse("90"), 100.0)
        self.assertEqual(angle_units.parse("22,5"), 25.0)
        self.assertIsNone(angle_units.parse("abc"))


class ChoixDirectionTests(_Unite):
    def test_aller_retour_des_16_directions_dans_les_deux_unites(self):
        for unite in (angle_units.GRADE, angle_units.DEGRE):
            angle_units.set_unite(unite)
            choix = grade_choices()
            self.assertEqual(len(choix), 16)
            for g in range(0, 400, 25):
                self.assertEqual(parse_grade(find_grade_choice(choix, g)), g)

    def test_libelle_degres(self):
        angle_units.set_unite(angle_units.DEGRE)
        self.assertTrue(grade_choices()[4].startswith("90° — E"))

    def test_largeur_saisie_en_degres(self):
        angle_units.set_unite(angle_units.DEGRE)
        self.assertEqual(largeur_grades_saisie("45"), 50)
        self.assertEqual(largeur_grades_saisie(""), 25)


class ExportTests(_Unite):
    def test_valeur_et_titre_de_colonne(self):
        self.assertEqual(angle_units.valeur(100), 100)
        self.assertEqual(angle_units.titre_colonne(), "Grade (gr)")
        angle_units.set_unite(angle_units.DEGRE)
        self.assertEqual(angle_units.valeur(100), 90.0)
        self.assertEqual(angle_units.titre_colonne(), "Angle (°)")

    def test_tableau_xlsx_en_degres(self):
        try:
            import openpyxl  # noqa: F401
        except ImportError:
            self.skipTest("openpyxl absent")
        import os
        import tempfile

        from export import export_prbs_xlsx as export_xlsx
        from model import Arbre, Chantier, Sondage
        a = Arbre(numero_arbre="1")
        a.brins[0].set_rayon(20.0)
        a.brins[0].sondages.append(
            Sondage(grade=100, bois_sain_cm=8.0, bois_altere_cm=12.0))
        ch = Chantier()
        ch.arbres.append(a)
        angle_units.set_unite(angle_units.DEGRE)
        path = os.path.join(tempfile.mkdtemp(), "t.xlsx")
        from bareme import classer_prbs
        from palette import COULEUR_CLASSE
        export_xlsx(a, ch, path, COULEUR_CLASSE, classer_prbs)
        ws = openpyxl.load_workbook(path).active
        cells = [c.value for row in ws.iter_rows() for c in row]
        self.assertIn("Angle (°)", cells)
        self.assertNotIn("Grade (gr)", cells)
        self.assertIn(90.0, cells)


class SettingsTests(unittest.TestCase):
    def test_persistance_et_valeur_invalide(self):
        import tempfile
        from pathlib import Path

        from app_settings import SettingsStore
        p = Path(tempfile.mkdtemp()) / "s.json"
        st = SettingsStore(p)
        self.assertEqual(st.angle_unit, "grade")
        st.set_angle_unit("degre")
        self.assertEqual(SettingsStore(p).angle_unit, "degre")
        st.set_angle_unit("bidon")
        self.assertEqual(SettingsStore(p).angle_unit, "grade")


if __name__ == "__main__":
    unittest.main()
