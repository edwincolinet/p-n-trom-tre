"""Garde-fou de la surface de couplage `App` ↔ mixins.

Chaque mixin déclare, dans un bloc `if TYPE_CHECKING:`, les attributs et
méthodes qu'il attend de `App` (ou d'un autre mixin). mypy refuse déjà tout
accès **non déclaré**, mais il ne peut pas vérifier l'inverse : `App` hérite
de ces déclarations, donc mypy la croit toujours conforme — même si plus rien
ne l'implémente (renommage, suppression). L'erreur n'apparaît alors qu'à
l'exécution, sur l'action concernée.

Ce test ferme le trou : le bloc `TYPE_CHECKING` n'existe pas au runtime, donc
tout nom déclaré qui est présent sur une `App` réellement instanciée est
fourni pour de vrai. Parties :

1. extraction statique (AST, sans Tk) des surfaces déclarées ;
2. chaque nom déclaré existe sur l'`App` instanciée (headless, skipped sans
   display comme `test_app`) ;
3. une méthode déclarée l'est avec un nombre d'arguments compatible avec
   l'implémentation réelle (dérive typique : on change la signature, on
   oublie la déclaration).
"""

from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent

# (module, classe) de chaque mixin d'`App`.
MIXINS: List[Tuple[str, str]] = [
    ("app_arbres", "ArbreListMixin"),
    ("app_recovery", "RecoveryMixin"),
    ("app_export_actions", "ExportActionsMixin"),
    ("app_fichier", "FichierMixin"),
    ("app_layout", "LayoutMixin"),
    ("app_reglages", "ReglagesMixin"),
]

# Déclarations (nom -> nb de paramètres hors self, ou None pour un attribut).
Surface = Dict[str, "int | None"]


def surface_declaree(module: str, classe: str) -> Surface:
    """Noms déclarés dans le `if TYPE_CHECKING:` du corps de `classe`."""
    tree = ast.parse((ROOT / f"{module}.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == classe:
            break
    else:  # pragma: no cover - garde de maintenance
        raise AssertionError(f"{classe} introuvable dans {module}.py")
    out: Surface = {}
    for stmt in node.body:
        if not (isinstance(stmt, ast.If)
                and isinstance(stmt.test, ast.Name)
                and stmt.test.id == "TYPE_CHECKING"):
            continue
        for decl in stmt.body:
            if isinstance(decl, ast.AnnAssign) and isinstance(decl.target, ast.Name):
                out[decl.target.id] = None
            elif isinstance(decl, (ast.FunctionDef, ast.AsyncFunctionDef)):
                a = decl.args
                n = len(a.posonlyargs) + len(a.args) - 1  # sans `self`
                out[decl.name] = n
    return out


class TestExtractionSurfaces(unittest.TestCase):
    """Sans Tk : le parseur voit bien une surface non vide par mixin."""

    def test_chaque_mixin_declare_une_surface(self) -> None:
        for module, classe in MIXINS:
            with self.subTest(mixin=classe):
                self.assertTrue(
                    surface_declaree(module, classe),
                    f"{classe} ne déclare aucune surface TYPE_CHECKING : "
                    "le garde-fou ne vérifierait rien.")


# --- Détection Tk (même sonde que test_app) -----------------------------
_SKIP_TK = True
try:
    import tkinter as tk
    try:
        tk.Tk().destroy()
        _SKIP_TK = False
    except tk.TclError:
        pass
except ImportError:
    pass


@unittest.skipIf(_SKIP_TK, "tkinter ou DISPLAY indisponible (headless sans Xvfb)")
class TestSurfacesFourniesParApp(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        import penetrometre
        cls.app = penetrometre.App()
        cls.app.action_new()
        cls.app.update_idletasks()

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.app.destroy()
        except tk.TclError:
            pass

    def test_tout_nom_declare_est_fourni(self) -> None:
        manquants: List[str] = []
        for module, classe in MIXINS:
            for nom in surface_declaree(module, classe):
                if not hasattr(self.app, nom):
                    manquants.append(f"{classe}.{nom}")
        self.assertEqual(
            manquants, [],
            "Déclaré dans un bloc TYPE_CHECKING mais fourni par aucune classe "
            "d'App : déclaration périmée, ou implémentation disparue.")

    def test_methodes_declarees_sont_appelables_avec_la_meme_arite(self) -> None:
        derives: List[str] = []
        for module, classe in MIXINS:
            for nom, arite in surface_declaree(module, classe).items():
                if arite is None or not hasattr(self.app, nom):
                    continue
                reel = getattr(self.app, nom)
                if not callable(reel):
                    derives.append(f"{classe}.{nom}: déclarée méthode, "
                                   f"réelle non appelable")
                    continue
                try:
                    sig = inspect.signature(reel)
                except (TypeError, ValueError):  # builtin / Tk C-level
                    continue
                params = list(sig.parameters.values())
                if any(p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
                       for p in params):
                    continue
                obligatoires = sum(
                    1 for p in params
                    if p.default is p.empty and p.kind in (
                        p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD))
                total = sum(
                    1 for p in params
                    if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD))
                if not (obligatoires <= arite <= total):
                    derives.append(
                        f"{classe}.{nom}: déclarée à {arite} argument(s), "
                        f"réelle {obligatoires}..{total}")
        self.assertEqual(derives, [], "Signature déclarée ≠ signature réelle.")


if __name__ == "__main__":
    unittest.main()
