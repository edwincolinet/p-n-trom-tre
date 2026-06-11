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

    def test_legendes_calquees_sur_la_fiche_du_cabinet(self):
        """Verrouille la conformité du tableau XLSX (1 arbre) à la fiche
        de référence du cabinet (`Communication/export excel attendu.xlsx`) :

        - 3e entrée de légende expliquant le glyphe « — » (la colonne
          Compartimentation l'emploie : la légende doit le couvrir) ;
        - légende des classes « Classe verte/orange/rouge » colorée,
          sous le pied, expliquant le code couleur de la colonne
          proportion ;
        - légende collée au tableau (ligne juste après le dernier
          sondage, sans ligne vide intercalée).
        """
        import os
        import tempfile

        import openpyxl

        from export import export_prbs_xlsx
        from model import Arbre, Chantier, Sondage
        from palette import COULEUR_CLASSE

        a = Arbre(numero_arbre="1", essence="Platane", port_arbre="libre",
                  rayon_tronc_cm=40.0)
        for n, g in enumerate((0, 100, 200), start=1):
            a.sondages.append(Sondage(numero=n, grade=g,
                                      bois_sain_cm=20.0, bois_altere_cm=20.0))
        c = Chantier(nom="test", arbres=[a])

        with tempfile.NamedTemporaryFile(suffix=".xlsx",
                                         delete=False) as tmp:
            path = tmp.name
        try:
            export_prbs_xlsx(a, c, path, couleur_classe=COULEUR_CLASSE,
                             classer_prbs=classer_prbs)
            with open(path, "rb") as f:
                ws = openpyxl.load_workbook(f).active

            header_row = next(r for r in range(1, 30)
                              if ws.cell(row=r, column=1).value == "Sondage")
            # Légende collée : ligne juste après le dernier sondage (3).
            legend_row = header_row + 1 + len(a.sondages)
            self.assertEqual(ws.cell(row=legend_row, column=1).value,
                             "Légende :")
            # 3e entrée : glyphe — + libellé (orthographe corrigée).
            self.assertEqual(ws.cell(row=legend_row, column=6).value, "—")
            self.assertEqual(ws.cell(row=legend_row, column=7).value,
                             "Non renseignée/pas d'altération")

            # Légende des classes : 3 libellés en colonne D, chacun coloré
            # de la couleur de sa classe.
            labels = {}
            for r in range(legend_row, legend_row + 12):
                v = ws.cell(row=r, column=4).value
                if isinstance(v, str) and v.startswith("Classe "):
                    labels[v] = ws.cell(row=r, column=4).font.color.rgb
            self.assertEqual(set(labels),
                             {"Classe verte", "Classe orange", "Classe rouge"})
            # Couleur de texte = couleur de classe (suffixe hex, openpyxl
            # préfixe l'alpha "00").
            self.assertTrue(labels["Classe verte"].endswith(
                COULEUR_CLASSE["Vert"].lstrip("#")))
            self.assertTrue(labels["Classe rouge"].endswith(
                COULEUR_CLASSE["Rouge"].lstrip("#")))
        finally:
            if os.path.exists(path):
                os.unlink(path)


class HtmlExportAlignementTests(unittest.TestCase):
    """Verrouille l'alignement du tableau HTML sur le XLSX : la légende
    compartimentation à 3 entrées (✓/✗/—) et la légende des classes colorée
    doivent figurer dans le HTML comme dans le XLSX (régression : elles
    n'avaient pas été reportées du XLSX vers le HTML)."""

    def test_html_contient_legende_neutre_et_classes(self):
        import os
        import tempfile

        from export import export_prbs_html
        from model import Arbre, Chantier, Sondage
        from palette import COULEUR_CLASSE

        a = Arbre(numero_arbre="1", essence="Platane", port_arbre="libre",
                  rayon_tronc_cm=40.0)
        for n, g in enumerate((0, 100, 200), start=1):
            a.sondages.append(Sondage(numero=n, grade=g,
                                      bois_sain_cm=20.0, bois_altere_cm=20.0))
        c = Chantier(nom="test", arbres=[a])

        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tmp:
            path = tmp.name
        try:
            export_prbs_html(a, c, path, couleur_classe=COULEUR_CLASSE,
                             classer_prbs=classer_prbs)
            with open(path, encoding="utf-8") as f:
                html = f.read()
            # 3e entrée de légende compartimentation (glyphe « — »).
            self.assertIn("Non renseignée/pas d&#39;altération", html)
            # Légende des classes colorée (bloc + 3 libellés + couleurs).
            self.assertIn("classe-legend", html)
            for label in ("Classe verte", "Classe orange", "Classe rouge"):
                self.assertIn(label, html)
            for hex_ in COULEUR_CLASSE.values():
                self.assertIn(hex_, html)
        finally:
            if os.path.exists(path):
                os.unlink(path)


class FichePdfSondagesTests(unittest.TestCase):
    """La case « Afficher les sondages » doit gouverner le dessin de la
    fiche PDF (régression : les pastilles étaient toujours dessinées)."""

    def setUp(self) -> None:
        from pil_render import HAS_PIL
        if not HAS_PIL:
            self.skipTest("Pillow absent")

    def test_show_sondages_false_omet_les_pastilles_du_dessin(self):
        from fiche_pdf import render_fiche_arbre_to_pdf_page
        from model import Arbre, Chantier, Sondage

        a = Arbre(numero_arbre="1", essence="Chêne", rayon_tronc_cm=20.0)
        for n, g in enumerate((0, 50, 100, 150), start=1):
            a.sondages.append(Sondage(numero=n, grade=g,
                                      bois_sain_cm=8.0, bois_altere_cm=12.0))
        c = Chantier(nom="t", arbres=[a])
        on = render_fiche_arbre_to_pdf_page(a, c, show_sondages=True)
        off = render_fiche_arbre_to_pdf_page(a, c, show_sondages=False)
        # Le dessin diffère (pastilles présentes vs absentes)…
        self.assertNotEqual(list(on.getdata()), list(off.getdata()))
        # …mais la page reste de même format A4.
        self.assertEqual(on.size, off.size)


class FichePdfCepeeLayoutTests(unittest.TestCase):
    """Le dessin d'une cépée sur la fiche PDF occupe la pleine largeur
    utile de la page (le carré historique, calibré pour une section
    ronde, rendait chaque brin minuscule)."""

    def setUp(self) -> None:
        from pil_render import HAS_PIL
        if not HAS_PIL:
            self.skipTest("Pillow absent")

    def test_dessin_cepee_pleine_largeur(self):
        from fiche_pdf import render_fiche_arbre_to_pdf_page
        from model import Chantier
        from tests._fixtures import build_arbre

        a = build_arbre("cepee")
        c = Chantier(nom="t", arbres=[a])
        page = render_fiche_arbre_to_pdf_page(a, c)
        W = page.size[0]
        px = page.load()
        # Bande de la zone dessin (sous l'identité, au-dessus du tableau) :
        # le contenu non blanc (brins + boussole) doit balayer l'essentiel
        # de la largeur — un dessin carré centré plafonnerait vers 60 %.
        xs = [x for y in range(320, 880, 10) for x in range(0, W, 5)
              if px[x, y] != (255, 255, 255)]
        self.assertTrue(xs, "aucun contenu trouvé dans la zone du dessin")
        self.assertGreater(max(xs) - min(xs), 0.75 * W)


class MissionSynthesisRowsTests(unittest.TestCase):
    """Synthèse mission : une ligne par arbre + masquage des champs non
    fiables (< 3 sondages, ou rayon nul)."""

    @staticmethod
    def _arbre(numero, rayon, grades, sain, port="libre", essence="Platane"):
        from model import Chantier
        a = Arbre(numero_arbre=numero, essence=essence,
                  rayon_tronc_cm=rayon, port_arbre=port)
        for g in grades:
            a.sondages.append(Sondage(grade=g, bois_sain_cm=sain,
                                      bois_altere_cm=max(0.0, rayon - sain)))
        c = Chantier()
        c.arbres = [a]
        return c

    def test_une_ligne_par_arbre(self):
        from diagnostic import mission_synthesis_rows
        from model import Chantier
        c = Chantier()
        c.arbres = [Arbre(numero_arbre="1"), Arbre(numero_arbre="2")]
        self.assertEqual(len(mission_synthesis_rows(c)), 2)

    def test_arbre_fiable_publie_classe_et_tR_moyen(self):
        from diagnostic import mission_synthesis_rows
        c = self._arbre("1", 20.0, [0, 50, 100, 150, 200, 250, 300, 350],
                        sain=16.0)  # t/R = 0.8 partout → Vert
        r = mission_synthesis_rows(c)[0]
        self.assertTrue(r.fiable)
        self.assertEqual(r.classe_globale, "Vert")
        self.assertAlmostEqual(r.tR_moyen_pct, 80.0, places=1)

    def test_moins_de_3_sondages_masque_diagnostic_global(self):
        from diagnostic import mission_synthesis_rows
        c = self._arbre("3", 18.0, [0, 100], sain=10.0)
        r = mission_synthesis_rows(c)[0]
        self.assertFalse(r.fiable)
        self.assertIsNone(r.classe_globale)
        self.assertIsNone(r.tR_moyen_pct)
        # mais le nombre de sondages reste exposé
        self.assertEqual(r.n_sondees, 2)

    def test_rayon_nul_ou_sans_sondage_tout_masque(self):
        from diagnostic import mission_synthesis_rows
        from model import Chantier
        c = Chantier()
        c.arbres = [Arbre(numero_arbre="4", rayon_tronc_cm=0.0)]
        r = mission_synthesis_rows(c)[0]
        self.assertFalse(r.fiable)
        self.assertIsNone(r.classe_globale)
        self.assertIsNone(r.tR_min_pct)


class SynthesisExportSmokeTests(unittest.TestCase):
    """Smoke-tests des exports de synthèse : on vérifie que les données
    arrivent correctement au formateur (CSV lisible, XLSX ouvrable)."""

    def _chantier(self):
        from model import Chantier
        c = Chantier(nom="Mission Test", operateur="Edwin")
        a1 = Arbre(numero_arbre="1", essence="Platane", rayon_tronc_cm=20.0,
                   port_arbre="libre")
        for g in (0, 50, 100, 150):
            a1.sondages.append(Sondage(grade=g, bois_sain_cm=16.0,
                                       bois_altere_cm=4.0))
        a2 = Arbre(numero_arbre="2", essence="Tilleul", rayon_tronc_cm=0.0)
        c.arbres = [a1, a2]
        return c

    def test_csv_contient_une_ligne_par_arbre(self):
        import csv as _csv
        import os
        import tempfile

        from diagnostic import mission_synthesis_rows
        from export import export_synthesis_csv
        c = self._chantier()
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        try:
            export_synthesis_csv(mission_synthesis_rows(c), path)
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                rows = list(_csv.reader(f, delimiter=";"))
            # 1 en-tête + 2 arbres
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[0][0], "N°")
            self.assertEqual(rows[1][0], "1")
            self.assertEqual(rows[2][0], "2")
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_xlsx_ouvrable_avec_entete_synthese(self):
        try:
            import openpyxl  # noqa: F401
        except ImportError:
            self.skipTest("openpyxl absent")
        import os
        import tempfile

        from diagnostic import mission_synthesis_rows
        from export import export_synthesis_xlsx
        from palette import COULEUR_CLASSE
        c = self._chantier()
        fd, path = tempfile.mkstemp(suffix=".xlsx")
        os.close(fd)
        try:
            export_synthesis_xlsx(mission_synthesis_rows(c), c, path,
                                  couleur_classe=COULEUR_CLASSE)
            import openpyxl
            with open(path, "rb") as f:
                wb = openpyxl.load_workbook(f)
            ws = wb.active
            self.assertEqual(ws.title, "Synthèse")
            header_row = next(
                row for row in range(1, 20)
                if ws.cell(row=row, column=1).value == "N°")
            self.assertEqual(ws.cell(row=header_row + 1, column=1).value, "1")
            self.assertEqual(ws.cell(row=header_row + 2, column=1).value, "2")
        finally:
            if os.path.exists(path):
                os.unlink(path)


if __name__ == "__main__":
    unittest.main()
