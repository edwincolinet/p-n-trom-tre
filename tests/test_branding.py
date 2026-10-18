"""Garde-fous de marque : nom du produit et familles de polices.

Le produit s'appelle « Pénétromètre Silvavenir ». L'ancien nom ne doit plus
apparaître nulle part (code, textes affichés, identifiants techniques,
chemins), hors journal des versions.
"""

from __future__ import annotations

import pathlib
import re
import unittest

import ui_fonts

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_SKIP_DIRS = {"venv", ".venv", ".git", ".hypothesis", "__pycache__",
              "design system SILVAVENIR", "build", "dist", ".mypy_cache",
              ".ruff_cache", ".pytest_cache"}
# Seule survivance tolérée : la référence à un fichier de mémoire de l'agent.
_TOLERES = ("project_penetrometre_perso",)


class NomProduitTests(unittest.TestCase):

    def test_ancien_nom_absent_des_sources_et_textes(self):
        fautes = []
        for path in _ROOT.rglob("*"):
            if (not path.is_file() or _SKIP_DIRS & set(path.parts)
                    or path.suffix not in {".py", ".md", ".html", ".iss",
                                           ".spec", ".yml", ".ini", ".desktop",
                                           ""}):
                continue
            try:
                texte = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for t in _TOLERES:
                texte = texte.replace(t, "")
            # Le journal des versions cite l'ancien nom (historique).
            if path.name in {"test_branding.py", "CHANGELOG.md"}:
                continue
            if re.search(r"penetrometre", texte, re.IGNORECASE):
                fautes.append(str(path.relative_to(_ROOT)))
        self.assertEqual(fautes, [])


class FamillesPoliceTests(unittest.TestCase):

    def setUp(self):
        self._saved = (ui_fonts._family_title, ui_fonts._family_body)

    def tearDown(self):
        ui_fonts._family_title, ui_fonts._family_body = self._saved

    def test_noms_historiques_traduits_vers_les_familles_de_la_charte(self):
        ui_fonts._family_title, ui_fonts._family_body = "Jost", "Source Sans 3"
        self.assertEqual(ui_fonts.font("Helvetica", 10)[0], "Source Sans 3")
        self.assertEqual(ui_fonts.font("Georgia", 18, "bold")[0], "Jost")
        # Une famille explicite (monospace, etc.) n'est pas touchée.
        self.assertEqual(ui_fonts.font("Courier", 9)[0], "Courier")

    def test_resolution_sans_tk_laisse_les_familles_historiques(self):
        ui_fonts.resolve_brand_fonts(object())  # pas de Tk → no-op silencieux
        self.assertEqual(ui_fonts._family_body, self._saved[1])


if __name__ == "__main__":
    unittest.main()
