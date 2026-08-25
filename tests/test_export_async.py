"""
Tests de l'export PDF de mission **avec progression et annulation**.

Ce chemin a coûté deux tentatives ratées, d'où des tests de bout en
bout sous Tk réel plutôt qu'un test du seul rendu :

1. poster la progression par `after(0, …)` depuis un thread worker →
   « RuntimeError: main thread is not in main loop », avalé
   silencieusement par le thread daemon (export qui ne finit jamais) ;
2. même en ne faisant transiter que des données, le **GC** peut
   s'exécuter dans le worker et y finaliser un objet Tk →
   `Fatal Python error: Aborted` (crash du processus), reproduit ici
   pendant le chargement des polices fpdf2.

La forme retenue est une boucle sur le thread Tk qui rend la main entre
chaque fiche. Ces tests vérifient les trois propriétés qui comptent :
le PDF est produit, l'UI reste vivante pendant l'export, et une
annulation n'écrit aucun fichier partiel.

Silencieusement *skipped* sans `tkinter` ou sans DISPLAY, comme
`test_section_canvas` / `test_app`.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

# `tests/__init__.py` ajoute la racine du projet à sys.path.
from geometry import GRADES
from model import Arbre, Brin, Chantier, Sondage

_TK_AVAILABLE = False
_DISPLAY_OK = False
try:
    import tkinter as tk
    _TK_AVAILABLE = True
    try:
        _probe = tk.Tk()
        _probe.destroy()
        _DISPLAY_OK = True
    except tk.TclError:
        pass
except ImportError:
    pass

try:
    from fiche_pdf import HAS_FPDF
except ImportError:                                   # pragma: no cover
    HAS_FPDF = False


def _mission(n: int) -> Chantier:
    c = Chantier(nom="Test", date_releve="01/01/2026")
    for i in range(n):
        a = Arbre(numero_arbre=str(i + 1), essence="Quercus",
                  port_arbre="libre")
        b = Brin(rayon_tronc_cm=40.0, epaisseur_ecorce_cm=2.0)
        b.sondages = [Sondage(grade=g, bois_sain_cm=12.0,
                              bois_altere_cm=28.0) for g in GRADES]
        a.brins = [b]
        c.arbres.append(a)
    return c


@unittest.skipUnless(_TK_AVAILABLE and _DISPLAY_OK, "Tk/DISPLAY indisponible")
@unittest.skipUnless(HAS_FPDF, "fpdf2 requis")
class ExportPdfMissionTests(unittest.TestCase):

    def setUp(self) -> None:
        import app_style
        self.root = tk.Tk()
        self.root.withdraw()
        app_style.apply_ttk_styles(self.root)
        self.etat: dict = {}
        self.root.set_status = lambda t: self.etat.update(status=t)         # type: ignore[attr-defined]
        self.root.notify_export = lambda p, lbl: self.etat.update(ok=lbl)   # type: ignore[attr-defined]
        self.out = os.path.join(tempfile.mkdtemp(), "mission.pdf")

    def tearDown(self) -> None:
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def _exporter(self, chantier: Chantier) -> None:
        import app_exports
        with mock.patch("app_exports.filedialog.asksaveasfilename",
                        return_value=self.out), \
             mock.patch("app_exports._check_completeness", return_value=True):
            app_exports.export_pdf_mission(self.root, chantier)

    def test_export_complet_ecrit_le_pdf(self):
        self._exporter(_mission(4))
        self.assertIn("ok", self.etat, "aucune notification de succès")
        self.assertTrue(os.path.exists(self.out))
        with open(self.out, "rb") as f:
            self.assertEqual(f.read(4), b"%PDF")

    def test_ui_reste_vivante_pendant_l_export(self):
        """Le point de tout l'exercice : la boucle Tk doit continuer de
        traiter les événements pendant la génération, sinon la fenêtre
        est déclarée « ne répond pas » par l'OS."""
        tics: list[int] = []

        def _tic() -> None:
            tics.append(1)
            self.root.after(10, _tic)

        self.root.after(10, _tic)
        self._exporter(_mission(10))
        self.assertGreater(
            len(tics), 1,
            "aucun événement Tk traité pendant l'export — UI gelée")

    def test_annulation_n_ecrit_aucun_fichier(self):
        """Un PDF de mission tronqué serait pris pour un export complet :
        l'écriture n'a lieu qu'une fois toutes les fiches produites."""
        import app_exports
        vu: dict = {}
        vrai = app_exports.ProgressDialog

        def _spy(*a, **k):
            d = vrai(*a, **k)
            vu["dlg"] = d
            # Demande l'annulation dès que la boucle rend la main : le
            # clic utilisateur arrive de la même façon, via `update()`.
            self.root.after(50, d.annuler)
            return d

        with mock.patch("app_exports.filedialog.asksaveasfilename",
                        return_value=self.out), \
             mock.patch("app_exports._check_completeness", return_value=True), \
             mock.patch("app_exports.ProgressDialog", _spy):
            app_exports.export_pdf_mission(self.root, _mission(40))

        self.assertTrue(vu["dlg"].demande_annulation())
        self.assertFalse(os.path.exists(self.out),
                         "un PDF partiel a été écrit malgré l'annulation")
        self.assertNotIn("ok", self.etat,
                         "succès notifié alors que l'export a été annulé")
        self.assertIn("annulé", self.etat.get("status", ""))


if __name__ == "__main__":
    unittest.main()
