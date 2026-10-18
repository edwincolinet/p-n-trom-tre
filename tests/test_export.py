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
                if ws.cell(row=row, column=1).value == "N°")
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

    def test_diagnostic_et_legendes_du_tableau(self):
        """Verrouille la mise en page (propre au Pénétromètre Silvavenir) du tableau XLSX :

        - une ligne « Diagnostic » (t/R minimal + classe) sous le
          tableau, alignée sur la fiche PDF ;
        - une légende compartimentation couvrant les 3 glyphes ✔/✘/— ;
        - une légende des classes « Classe verte/orange/rouge » colorée
          de la couleur de chaque classe.
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

            # Toutes les valeurs de la colonne A (recherche par contenu :
            # robuste aux décalages de lignes).
            col_a = {r: ws.cell(row=r, column=1).value
                     for r in range(1, ws.max_row + 1)}

            # Ligne Diagnostic (3 sondages → diagnostic fiable publié).
            diag_row = next(r for r, v in col_a.items()
                            if isinstance(v, str) and v.startswith("Diagnostic —"))
            self.assertIn("t/R minimal", col_a[diag_row])
            self.assertIn("Classe", col_a[diag_row])
            self.assertNotIn("t/R moyen", col_a[diag_row])

            # Légende compartimentation : couvre les 3 glyphes (source unique
            # `dialogs_shared` → suit un éventuel restyle des symboles).
            from dialogs_shared import compart_glyph
            legend_row = next(r for r, v in col_a.items()
                              if isinstance(v, str)
                              and v.startswith("Compartimentation :"))
            legend = col_a[legend_row]
            for value in ("active", "absente", "non renseignée"):
                self.assertIn(compart_glyph(value), legend)
            self.assertIn("pas d'altération", legend)

            # Légende des classes : 3 cellules « ● Classe … », chacune
            # colorée de la couleur de sa classe.
            classe_row = next(r for r, v in col_a.items()
                              if isinstance(v, str) and v.startswith("● "))
            labels = {}
            for col in range(1, 4):
                cell = ws.cell(row=classe_row, column=col)
                if isinstance(cell.value, str) and cell.value.startswith("● "):
                    labels[cell.value] = cell.font.color.rgb
            self.assertEqual(
                set(labels),
                {"● Classe verte", "● Classe orange", "● Classe rouge"})
            # Couleur de texte = couleur de classe (openpyxl préfixe l'alpha).
            self.assertTrue(labels["● Classe verte"].endswith(
                COULEUR_CLASSE["Vert"].lstrip("#")))
            self.assertTrue(labels["● Classe rouge"].endswith(
                COULEUR_CLASSE["Rouge"].lstrip("#")))
        finally:
            if os.path.exists(path):
                os.unlink(path)


class HtmlExportAlignementTests(unittest.TestCase):
    """Verrouille l'alignement du tableau HTML sur le XLSX : la légende
    compartimentation à 3 entrées (✔/✘/—) et la légende des classes colorée
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
            # Colonnes propres à la refonte (parité avec le XLSX).
            for th in ("Direction", "t/R (%)", "Classe", "Compart."):
                self.assertIn(f"<th>{th}</th>", html)
            # Ligne Diagnostic (mêmes valeurs que le XLSX / la fiche PDF).
            self.assertIn('class="diagnostic"', html)
            self.assertIn("Diagnostic —", html)
            # Légende compartimentation couvrant le glyphe neutre « — ».
            self.assertIn("pas d&#39;altération", html)
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
    """La case « Afficher les sondages » gouverne le DESSIN de section
    (resté raster PIL, collé dans la fiche PDF vectorielle) : les pastilles
    y sont présentes ou absentes. On teste directement le dessin
    (`render_arbre_to_pil_image`) — l'info qu'on vérifie y vit, la page
    elle-même est désormais un PDF fpdf2 (cf. `FichePdfSmokeTests`)."""

    def setUp(self) -> None:
        from pil_render import HAS_PIL
        if not HAS_PIL:
            self.skipTest("Pillow absent")

    def test_show_sondages_false_omet_les_pastilles_du_dessin(self):
        from model import Arbre, Sondage
        from pil_render import render_arbre_to_pil_image

        a = Arbre(numero_arbre="1", essence="Chêne", rayon_tronc_cm=20.0)
        for n, g in enumerate((0, 50, 100, 150), start=1):
            a.sondages.append(Sondage(numero=n, grade=g,
                                      bois_sain_cm=8.0, bois_altere_cm=12.0))
        on = render_arbre_to_pil_image(a, 600, 600, show_sondages=True)
        off = render_arbre_to_pil_image(a, 600, 600, show_sondages=False)
        # Le dessin diffère (pastilles présentes vs absentes)…
        # `tobytes()` plutôt que `getdata()` (déprécié Pillow 12, retiré 14)
        # et stable sur toute la plage supportée (Pillow 10→12).
        self.assertNotEqual(on.tobytes(), off.tobytes())
        # …mais l'image garde la même taille demandée.
        self.assertEqual(on.size, off.size)


class FichePdfCepeeLayoutTests(unittest.TestCase):
    """Le dessin d'une cépée occupe la pleine largeur utile (le carré
    historique, calibré pour une section ronde, rendait chaque brin
    minuscule). Le dessin étant collé tel quel dans la fiche PDF, on teste
    directement l'image PIL en pleine largeur."""

    def setUp(self) -> None:
        from pil_render import HAS_PIL
        if not HAS_PIL:
            self.skipTest("Pillow absent")

    def test_dessin_cepee_pleine_largeur(self):
        from pil_render import render_arbre_to_pil_image
        from tests._fixtures import build_arbre

        a = build_arbre("cepee")
        # Pleine largeur utile de la fiche (W - 2*marge = 1240 - 120).
        Wd, Hd = 1120, 700
        img = render_arbre_to_pil_image(a, Wd, Hd, show_title=False,
                                        show_legend=False).convert("RGB")
        px = img.load()
        xs = [x for y in range(0, Hd, 10) for x in range(0, Wd, 5)
              if px[x, y] != (255, 255, 255)]
        self.assertTrue(xs, "aucun contenu trouvé dans la zone du dessin")
        self.assertGreater(max(xs) - min(xs), 0.75 * Wd)


class FichePdfSmokeTests(unittest.TestCase):
    """La fiche PDF vectorielle (fpdf2) produit un document valide."""

    def setUp(self) -> None:
        from pil_render import HAS_PIL
        if not HAS_PIL:
            self.skipTest("Pillow absent")

    def test_produit_un_pdf_valide(self):
        from fiche_pdf import _new_pdf, render_fiche_arbre
        from model import Arbre, Chantier, Sondage

        a = Arbre(numero_arbre="1", essence="Chêne", rayon_tronc_cm=20.0,
                  port_arbre="libre")
        for n, g in enumerate((0, 50, 100, 150), start=1):
            a.sondages.append(Sondage(numero=n, grade=g,
                                      bois_sain_cm=8.0, bois_altere_cm=12.0))
        c = Chantier(nom="Mission test", arbres=[a], operateur="Op")
        pdf = _new_pdf()
        render_fiche_arbre(pdf, a, c)
        data = bytes(pdf.output())
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertGreater(len(data), 1000)
        # Une seule page sans photos.
        self.assertEqual(len(pdf.pages), 1)

    def test_mission_concatene_les_fiches(self):
        from fiche_pdf import _new_pdf, render_fiche_arbre
        from model import Arbre, Chantier, Sondage

        arbres = []
        for num in ("1", "2"):
            a = Arbre(numero_arbre=num, essence="Chêne", rayon_tronc_cm=20.0)
            a.sondages.append(Sondage(numero=1, grade=0,
                                      bois_sain_cm=8.0, bois_altere_cm=12.0))
            arbres.append(a)
        c = Chantier(nom="m", arbres=arbres)
        pdf = _new_pdf()
        for a in arbres:
            render_fiche_arbre(pdf, a, c)
        self.assertEqual(len(pdf.pages), 2)
        self.assertTrue(bytes(pdf.output()).startswith(b"%PDF"))


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

    def test_arbre_fiable_publie_classe_et_tR_min(self):
        from diagnostic import mission_synthesis_rows
        c = self._arbre("1", 20.0, [0, 50, 100, 150, 200, 250, 300, 350],
                        sain=16.0)  # t/R = 0.8 partout → Vert
        r = mission_synthesis_rows(c)[0]
        self.assertTrue(r.fiable)
        self.assertEqual(r.classe_globale, "Vert")
        self.assertAlmostEqual(r.tR_min_pct, 80.0, places=1)

    def test_moins_de_3_sondages_masque_diagnostic_global(self):
        from diagnostic import mission_synthesis_rows
        c = self._arbre("3", 18.0, [0, 100], sain=10.0)
        r = mission_synthesis_rows(c)[0]
        self.assertFalse(r.fiable)
        self.assertIsNone(r.classe_globale)
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

    def test_trier_par_urgence_ordonne_les_groupes(self):
        from diagnostic import mission_synthesis_rows
        from model import Chantier
        grades_fiables = list(range(0, 400, 25))  # 16 sondages
        c = Chantier()
        # a1 : urgence basse (< 2 ans), classe Rouge
        a1 = Arbre(numero_arbre="1", port_arbre="libre",
                   rayon_tronc_cm=20.0, urgence="< 2 ans")
        for g in grades_fiables:
            a1.sondages.append(Sondage(grade=g, bois_sain_cm=2.0,
                                       bois_altere_cm=18.0))
        # a2 : urgence haute (Immédiate), classe Vert
        a2 = Arbre(numero_arbre="2", port_arbre="libre",
                   rayon_tronc_cm=20.0, urgence="Immédiate")
        for g in grades_fiables:
            a2.sondages.append(Sondage(grade=g, bois_sain_cm=18.0,
                                       bois_altere_cm=2.0))
        # a3 : urgence non renseignée
        a3 = Arbre(numero_arbre="3", urgence="")
        c.arbres = [a1, a2, a3]
        rows = mission_synthesis_rows(c, trier_par_urgence=True)
        numeros = [r.numero for r in rows if not r.brin_label]
        # Immédiate < < 2 ans < non renseignée
        self.assertEqual(numeros, ["2", "1", "3"])

    def test_trier_par_urgence_egale_rouge_avant_vert(self):
        from diagnostic import mission_synthesis_rows
        from model import Chantier
        grades_fiables = list(range(0, 400, 25))
        c = Chantier()
        # a1 : Immédiate + Vert
        a1 = Arbre(numero_arbre="1", port_arbre="libre",
                   rayon_tronc_cm=20.0, urgence="Immédiate")
        for g in grades_fiables:
            a1.sondages.append(Sondage(grade=g, bois_sain_cm=18.0,
                                       bois_altere_cm=2.0))
        # a2 : Immédiate + Rouge
        a2 = Arbre(numero_arbre="2", port_arbre="libre",
                   rayon_tronc_cm=20.0, urgence="Immédiate")
        for g in grades_fiables:
            a2.sondages.append(Sondage(grade=g, bois_sain_cm=2.0,
                                       bois_altere_cm=18.0))
        c.arbres = [a1, a2]
        rows = mission_synthesis_rows(c, trier_par_urgence=True)
        numeros = [r.numero for r in rows]
        # même urgence : Rouge avant Vert
        self.assertEqual(numeros, ["2", "1"])

    def test_trier_par_urgence_false_conserve_ordre_saisie(self):
        from diagnostic import mission_synthesis_rows
        from model import Chantier
        c = Chantier()
        c.arbres = [
            Arbre(numero_arbre="1", urgence="< 2 ans"),
            Arbre(numero_arbre="2", urgence="Immédiate"),
        ]
        rows = mission_synthesis_rows(c, trier_par_urgence=False)
        self.assertEqual([r.numero for r in rows], ["1", "2"])


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
        from export_synthesis import export_synthesis_csv
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
        from export_synthesis import export_synthesis_xlsx
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
