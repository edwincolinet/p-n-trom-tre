"""Tests de l'export ODS et des exports de tableaux de toute la mission."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from xml.dom import minidom

# `tests/__init__.py` ajoute la racine du projet à sys.path.
from bareme import classer_prbs
from export import HAS_OPENPYXL, export_prbs_ods, prbs_sheet
from export_mission import (
    export_prbs_mission_html,
    export_prbs_mission_ods,
    export_prbs_mission_xlsx,
    noms_feuilles,
)
from model import Arbre, Chantier
from ods_writer import Cell, Sheet, safe_sheet_name, write_ods
from palette import COULEUR_CLASSE
from tests._fixtures import build_arbre

NS_TABLE = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"


def _chantier() -> Chantier:
    return Chantier(nom="Parc", client="Mairie", adresse="1 rue X",
                    operateur="E. C.", date_releve="01/02/2026")


def _feuilles_ods(path: str) -> "list[str]":
    with zipfile.ZipFile(path) as z:
        doc = minidom.parseString(z.read("content.xml"))
    return [t.getAttributeNS(NS_TABLE, "name")
            for t in doc.getElementsByTagNameNS(NS_TABLE, "table")]


def _textes_ods(path: str) -> "list[str]":
    with zipfile.ZipFile(path) as z:
        doc = minidom.parseString(z.read("content.xml"))
    return ["".join(n.data for n in p.childNodes if n.nodeType == 3)
            for p in doc.getElementsByTagName("text:p")]


class OdsWriterTests(unittest.TestCase):

    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "t.ods")

    def test_archive_conforme(self) -> None:
        write_ods(self.path, [Sheet("A", [[Cell("x")]])], title="t")
        with zipfile.ZipFile(self.path) as z:
            noms = z.namelist()
            self.assertEqual(noms[0], "mimetype")          # en premier
            self.assertEqual(z.getinfo("mimetype").compress_type,
                             zipfile.ZIP_STORED)           # non compressé
            self.assertEqual(z.read("mimetype"),
                             b"application/vnd.oasis.opendocument.spreadsheet")
            for n in ("content.xml", "styles.xml", "meta.xml",
                      "META-INF/manifest.xml"):
                minidom.parseString(z.read(n))             # XML bien formé

    def test_caracteres_speciaux_et_controles(self) -> None:
        write_ods(self.path, [Sheet("A", [[Cell("a <b> & \"c\" é\x01\x0b")]])])
        self.assertIn('a <b> & "c" é', _textes_ods(self.path))

    def test_valeur_formule_reste_du_texte(self) -> None:
        write_ods(self.path, [Sheet("A", [[Cell("=WEBSERVICE(\"x\")")]])])
        with zipfile.ZipFile(self.path) as z:
            contenu = z.read("content.xml").decode()
        self.assertNotIn("table:formula", contenu)
        self.assertIn('office:value-type="string"', contenu)

    def test_nombres_et_fusion(self) -> None:
        write_ods(self.path, [Sheet("A", [[Cell(12.5, span=3)],
                                          [Cell(1), Cell(2), Cell(3)]])])
        with zipfile.ZipFile(self.path) as z:
            contenu = z.read("content.xml").decode()
        self.assertIn('office:value="12.5"', contenu)
        self.assertIn('table:number-columns-spanned="3"', contenu)
        self.assertEqual(contenu.count("table:covered-table-cell"), 2)

    def test_zero_feuille_refuse(self) -> None:
        with self.assertRaises(ValueError):
            write_ods(self.path, [])

    def test_noms_de_feuilles(self) -> None:
        self.assertEqual(safe_sheet_name("Arbre 1"), "Arbre 1")
        self.assertEqual(safe_sheet_name("a/b:c*d?[e]"), "a_b_c_d__e_")
        self.assertEqual(safe_sheet_name(""), "Feuille")
        self.assertEqual(len(safe_sheet_name("x" * 80)), 31)
        self.assertEqual(safe_sheet_name("Arbre 1", ["arbre 1"]), "Arbre 1 (2)")
        long_nom = "y" * 40
        n1 = safe_sheet_name(long_nom)
        n2 = safe_sheet_name(long_nom, [n1])
        self.assertNotEqual(n1.lower(), n2.lower())
        self.assertLessEqual(len(n2), 31)


class NomsFeuillesTests(unittest.TestCase):

    def test_uniques_et_reserves(self) -> None:
        arbres = [Arbre(numero_arbre="1"), Arbre(numero_arbre="1"),
                  Arbre(numero_arbre=""), Arbre(numero_arbre="a/b")]
        noms = noms_feuilles(arbres, reserves=["Synthèse"])
        self.assertEqual(len({n.lower() for n in noms}), 4)
        self.assertNotIn("synthèse", {n.lower() for n in noms})
        for n in noms:
            self.assertLessEqual(len(n), 31)
            self.assertFalse(set("[]:*?/\\") & set(n))


class ExportPrbsOdsTests(unittest.TestCase):

    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp()
        self.ch = _chantier()

    def test_ods_un_arbre_contient_les_valeurs_du_tableau(self) -> None:
        a = build_arbre("avec_ecorce")
        out = os.path.join(self.dir, "a.ods")
        export_prbs_ods(a, self.ch, out, COULEUR_CLASSE, classer_prbs,
                        cabinet_name="Cab", bareme_desc="Vert ≥ 50 %")
        self.assertEqual(_feuilles_ods(out), ["PRBS"])
        textes = _textes_ods(out)
        self.assertTrue(any("Parc" in t for t in textes))
        self.assertTrue(any("Barème appliqué" in t for t in textes))
        self.assertTrue(any("Cab" in t for t in textes))

    @unittest.skipUnless(HAS_OPENPYXL, "openpyxl requis")
    def test_parite_ods_xlsx(self) -> None:
        """Mêmes cellules non vides, dans le même ordre, qu'en XLSX."""
        import openpyxl

        from export import export_prbs_xlsx
        for scenario in ("avec_ecorce", "ovale", "cepee"):
            a = build_arbre(scenario)
            x = os.path.join(self.dir, f"{scenario}.xlsx")
            export_prbs_xlsx(a, self.ch, x, COULEUR_CLASSE, classer_prbs,
                             "Cab", "bar")
            ws = openpyxl.load_workbook(x).active
            att = [c.value for r in ws.iter_rows() for c in r
                   if c.value is not None
                   and not str(c.value).startswith("Édité")]
            sh = prbs_sheet(a, self.ch, COULEUR_CLASSE, classer_prbs,
                            "Cab", "bar")
            got = [c.value for r in sh.rows for c in r
                   if c is not None and c.value is not None
                   and not str(c.value).startswith("Édité")]
            def norm(v: object) -> str:
                try:                    # 20 (xlsx) ≡ 20.0 (ods)
                    return f"{float(v):g}"  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    return str(v)
            self.assertEqual([norm(v) for v in got], [norm(v) for v in att],
                             scenario)


class ExportMissionTests(unittest.TestCase):

    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp()
        self.ch = _chantier()
        self.arbres = [build_arbre("avec_ecorce"), build_arbre("ovale"),
                       build_arbre("cepee")]
        for i, a in enumerate(self.arbres, start=1):
            a.numero_arbre = str(i)
        self.ch.arbres = list(self.arbres)

    def _synth(self):
        from diagnostic import mission_synthesis_rows
        return mission_synthesis_rows(self.ch, trier_par_urgence=True)

    def test_ods_mission_une_feuille_par_arbre_plus_synthese(self) -> None:
        out = os.path.join(self.dir, "m.ods")
        export_prbs_mission_ods(self.arbres, self.ch, out, COULEUR_CLASSE,
                                classer_prbs, synthese=self._synth())
        self.assertEqual(_feuilles_ods(out),
                         ["Synthèse", "Arbre 1", "Arbre 2", "Arbre 3"])

    def test_ods_mission_sans_synthese(self) -> None:
        out = os.path.join(self.dir, "m.ods")
        export_prbs_mission_ods(self.arbres, self.ch, out, COULEUR_CLASSE,
                                classer_prbs)
        self.assertEqual(_feuilles_ods(out),
                         ["Arbre 1", "Arbre 2", "Arbre 3"])

    @unittest.skipUnless(HAS_OPENPYXL, "openpyxl requis")
    def test_xlsx_mission_memes_feuilles_que_ods(self) -> None:
        import openpyxl
        out = os.path.join(self.dir, "m.xlsx")
        export_prbs_mission_xlsx(self.arbres, self.ch, out, COULEUR_CLASSE,
                                 classer_prbs, synthese=self._synth())
        self.assertEqual(openpyxl.load_workbook(out).sheetnames,
                         ["Synthèse", "Arbre 1", "Arbre 2", "Arbre 3"])

    @unittest.skipUnless(HAS_OPENPYXL, "openpyxl requis")
    def test_xlsx_mission_numeros_identiques(self) -> None:
        import openpyxl
        self.arbres[1].numero_arbre = "1"
        out = os.path.join(self.dir, "m.xlsx")
        export_prbs_mission_xlsx(self.arbres, self.ch, out, COULEUR_CLASSE,
                                 classer_prbs)
        noms = openpyxl.load_workbook(out).sheetnames
        self.assertEqual(len(noms), len(set(n.lower() for n in noms)))

    def test_html_mission_une_section_par_arbre(self) -> None:
        out = os.path.join(self.dir, "m.html")
        export_prbs_mission_html(self.arbres, self.ch, out, COULEUR_CLASSE,
                                 classer_prbs, "Cab", "bar")
        with open(out, encoding="utf-8") as f:
            html = f.read()
        self.assertEqual(html.count('<section class="arbre"'), 3)
        self.assertEqual(html.count("<table>"), 3)
        self.assertEqual(html.count("<h1>"), 1)       # titre mission unique
        for i in (1, 2, 3):
            self.assertIn(f'href="#arbre-{i}"', html)

    def test_aucun_arbre_refuse(self) -> None:
        for f in (export_prbs_mission_html, export_prbs_mission_ods):
            with self.assertRaises(ValueError):
                f([], self.ch, os.path.join(self.dir, "x"), COULEUR_CLASSE,
                  classer_prbs)


@unittest.skipUnless(shutil.which("soffice"), "LibreOffice indisponible")
class OuvertureLibreOfficeTests(unittest.TestCase):
    """Le vrai juge d'un ODS : LibreOffice doit l'ouvrir et en lire les
    feuilles (conversion CSV, une feuille par fichier)."""

    def test_ouverture_et_contenu(self) -> None:
        d = tempfile.mkdtemp()
        ch = _chantier()
        arbres = [build_arbre("avec_ecorce"), build_arbre("ovale")]
        arbres[0].numero_arbre = "1"
        arbres[1].numero_arbre = "2"
        ch.arbres = list(arbres)
        from diagnostic import mission_synthesis_rows
        out = os.path.join(d, "m.ods")
        export_prbs_mission_ods(
            arbres, ch, out, COULEUR_CLASSE, classer_prbs,
            synthese=mission_synthesis_rows(ch, trier_par_urgence=True))
        csv_dir = os.path.join(d, "csv")
        os.makedirs(csv_dir)
        subprocess.run(
            ["soffice", "--headless", "--convert-to",
             "csv:Text - txt - csv (StarCalc):44,34,76,1,,0,false,true,"
             "false,false,false,-1", "--outdir", csv_dir, out],
            check=True, timeout=120, capture_output=True,
            env={**os.environ, "HOME": d})
        fichiers = sorted(os.listdir(csv_dir))
        self.assertEqual(len(fichiers), 3, fichiers)
        with open(os.path.join(csv_dir, [f for f in fichiers
                                         if "Arbre 1" in f][0]),
                  encoding="utf-8") as f:
            contenu = f.read()
        self.assertIn("Parc", contenu)
        self.assertIn("PRBS", contenu)


if __name__ == "__main__":
    unittest.main()
