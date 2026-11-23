"""Tests de l'export du dessin de section : PNG/JPEG, arbre ou mission."""

from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

# `tests/__init__.py` ajoute la racine du projet à sys.path.
from geometry import GRADES
from model import Arbre, Brin, Chantier, Sondage

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:                                   # pragma: no cover
    HAS_PIL = False

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


def _arbre(num: str, rayon: float = 30.0) -> Arbre:
    a = Arbre(numero_arbre=num, essence="Quercus", port_arbre="libre")
    b = Brin(rayon_tronc_cm=rayon, epaisseur_ecorce_cm=1.5)
    b.sondages = [Sondage(grade=g, bois_sain_cm=10.0, bois_altere_cm=20.0)
                  for g in GRADES]
    a.brins = [b]
    return a


class NomsFichiersTests(unittest.TestCase):

    def test_nom_fichier_sur(self) -> None:
        from app_exports import nom_fichier_sur
        self.assertEqual(nom_fichier_sur("12 bis"), "12_bis")
        self.assertEqual(nom_fichier_sur('a/b\\c:d*e?f"g<h>i|j'),
                         "a_b_c_d_e_f_g_h_i_j")
        self.assertEqual(nom_fichier_sur(""), "sans_num")
        self.assertEqual(nom_fichier_sur(" .. "), "sans_num")
        self.assertEqual(nom_fichier_sur("", repli="X"), "X")

    def test_noms_uniques_pour_numeros_identiques(self) -> None:
        from app_exports import noms_dessins_mission
        arbres = [_arbre("1"), _arbre("1"), _arbre("2"), _arbre("1/")]
        noms = noms_dessins_mission(arbres, ".png")
        self.assertEqual(len(noms), len(set(n.lower() for n in noms)))
        self.assertEqual(noms[0], "arbre_1.png")
        self.assertEqual(noms[1], "arbre_1_2.png")
        self.assertEqual(noms[2], "arbre_2.png")

    def test_noms_insensibles_a_la_casse(self) -> None:
        """Windows/macOS : `A.png` et `a.png` sont le même fichier."""
        from app_exports import noms_dessins_mission
        noms = noms_dessins_mission([_arbre("A"), _arbre("a")], ".jpg")
        self.assertEqual(len({n.lower() for n in noms}), 2)


@unittest.skipUnless(HAS_PIL, "Pillow requis")
class ExportDessinArbreTests(unittest.TestCase):

    def _exporter(self, fmt: str, nom: str) -> str:
        import app_exports
        out = os.path.join(tempfile.mkdtemp(), nom)
        parent = SimpleNamespace(notify_export=lambda p, lbl: None)
        with mock.patch("app_exports.filedialog.asksaveasfilename",
                        return_value=out):
            app_exports.export_dessin_arbre(parent, _arbre("7"), True, fmt)  # type: ignore[arg-type]
        return out

    def test_png(self) -> None:
        out = self._exporter("png", "d.png")
        with Image.open(out) as im:
            self.assertEqual(im.format, "PNG")
            self.assertEqual(im.size, (2400, 2400))

    def test_jpeg(self) -> None:
        out = self._exporter("jpeg", "d.jpg")
        with Image.open(out) as im:
            self.assertEqual(im.format, "JPEG")
            self.assertEqual(im.mode, "RGB")
            self.assertEqual(im.size, (2400, 2400))


@unittest.skipUnless(HAS_PIL, "Pillow requis")
@unittest.skipUnless(_TK_AVAILABLE and _DISPLAY_OK, "Tk/DISPLAY indisponible")
class ExportDessinsMissionTests(unittest.TestCase):

    def setUp(self) -> None:
        import app_style
        self.root = tk.Tk()
        self.root.withdraw()
        app_style.apply_ttk_styles(self.root)
        self.etat: dict = {}
        self.root.set_status = lambda t: self.etat.update(status=t)         # type: ignore[attr-defined]
        self.root.notify_export = lambda p, lbl: self.etat.update(ok=lbl)   # type: ignore[attr-defined]
        self.dossier = tempfile.mkdtemp()
        c = Chantier(nom="T")
        c.arbres = [_arbre("1"), _arbre("2"), _arbre("3", rayon=0.0)]
        self.chantier = c

    def tearDown(self) -> None:
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def _exporter(self, fmt: str) -> None:
        import app_exports
        with mock.patch("app_exports.filedialog.askdirectory",
                        return_value=self.dossier):
            app_exports.export_dessin_mission(self.root, self.chantier,
                                              True, fmt)

    def test_un_fichier_par_arbre_avec_rayon(self) -> None:
        self._exporter("jpeg")
        self.assertEqual(sorted(os.listdir(self.dossier)),
                         ["arbre_1.jpg", "arbre_2.jpg"])   # n°3 sans rayon
        self.assertIn("ok", self.etat)
        with Image.open(os.path.join(self.dossier, "arbre_1.jpg")) as im:
            self.assertEqual(im.format, "JPEG")

    def test_refus_d_ecraser_n_ecrit_rien(self) -> None:
        import app_exports
        existant = os.path.join(self.dossier, "arbre_1.png")
        with open(existant, "wb") as f:
            f.write(b"X")
        with mock.patch("app_exports.filedialog.askdirectory",
                        return_value=self.dossier), \
             mock.patch("app_exports.messagebox.askyesno",
                        return_value=False):
            app_exports.export_dessin_mission(self.root, self.chantier,
                                              True, "png")
        self.assertEqual(os.listdir(self.dossier), ["arbre_1.png"])
        with open(existant, "rb") as f:
            self.assertEqual(f.read(), b"X")

    def test_dossier_annule(self) -> None:
        import app_exports
        with mock.patch("app_exports.filedialog.askdirectory",
                        return_value=""):
            app_exports.export_dessin_mission(self.root, self.chantier,
                                              True, "png")
        self.assertEqual(os.listdir(self.dossier), [])
        self.assertNotIn("ok", self.etat)

    def test_annulation_signale_les_fichiers_deja_ecrits(self) -> None:
        import app_exports
        vrai = app_exports.ProgressDialog

        def _spy(*a, **k):
            d = vrai(*a, **k)
            d.annuler()           # annulation dès l'ouverture
            return d

        with mock.patch("app_exports.filedialog.askdirectory",
                        return_value=self.dossier), \
             mock.patch("app_exports.ProgressDialog", _spy):
            app_exports.export_dessin_mission(self.root, self.chantier,
                                              True, "png")
        self.assertIn("status", self.etat)
        self.assertNotIn("ok", self.etat)


if __name__ == "__main__":
    unittest.main()
