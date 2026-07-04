"""Tests de complétude des catalogues de traduction (i18n).

`_()` retombe **silencieusement** sur le texte français quand une clé
manque : une chaîne `_("…")` sans entrée dans `translations/en.py` ou
`translations/it.py` s'affiche donc en français pour l'utilisateur
anglophone/italophone, **sans erreur**. Ce mode de défaillance est
invisible à l'œil (c'est précisément ainsi qu'une suppression de bloc a
déjà ré-orphelin la clé « Annuler »).

Ces tests rendent la dérive **bruyante** :

1. tout littéral `_("…")` du source a une entrée dans chaque catalogue ;
2. les catalogues en/it couvrent exactement les mêmes clés (pas de clé
   présente dans l'un mais pas l'autre).

On scanne le source par AST (pas par regex) pour ne récolter que les
appels `_(<littéral str>)` réels — les `_(variable)` sont ignorés (leur
contenu n'est pas connu statiquement).
"""

from __future__ import annotations

import ast
import pathlib
import unittest

# Racine du projet (le dossier parent de tests/).
_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Dossiers exclus du scan : les catalogues eux-mêmes, les tests, et tout
# ce qui n'est pas du source projet (virtualenv, artefacts de build). Sans
# ça, `rglob` fouille `venv/` et récolte les `_("…")` des dépendances
# installées (ex. Nuitka embarque des messages getopt traduits par gettext).
_SKIP_DIRS = {"translations", "tests", "venv", ".venv", "build", "dist"}


def _collect_literal_calls() -> set[str]:
    """Récolte tous les littéraux passés à `_(...)` dans le source."""
    lits: set[str] = set()
    for path in _ROOT.rglob("*.py"):
        parts = path.relative_to(_ROOT).parts
        if any(p in _SKIP_DIRS or p.startswith(".") for p in parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                lits.add(node.args[0].value)
    return lits


def _catalogs() -> dict[str, dict[str, str]]:
    from translations.en import TRANSLATIONS as en
    from translations.it import TRANSLATIONS as it

    return {"en": en, "it": it}


class I18nCompletenessTests(unittest.TestCase):

    def test_chaque_litteral_a_une_traduction(self) -> None:
        """Tout `_("…")` du source doit exister dans chaque catalogue."""
        literals = _collect_literal_calls()
        self.assertTrue(literals, "aucun littéral _() trouvé — scan cassé ?")
        for lang, catalog in _catalogs().items():
            manquants = sorted(literals - set(catalog))
            self.assertEqual(
                manquants, [],
                f"\n{len(manquants)} chaîne(s) sans traduction '{lang}' "
                f"(affichées en français) :\n" +
                "\n".join(f"  {m!r}" for m in manquants))

    def test_catalogues_alignes_entre_eux(self) -> None:
        """en et it doivent couvrir exactement les mêmes clés."""
        cats = _catalogs()
        en_keys, it_keys = set(cats["en"]), set(cats["it"])
        self.assertEqual(
            sorted(en_keys - it_keys), [],
            "clés présentes en EN mais pas IT")
        self.assertEqual(
            sorted(it_keys - en_keys), [],
            "clés présentes en IT mais pas EN")

    def test_aucune_valeur_vide(self) -> None:
        """Une valeur vide = traduction oubliée (≠ texte source affiché)."""
        for lang, catalog in _catalogs().items():
            vides = sorted(k for k, v in catalog.items() if not v.strip())
            self.assertEqual(
                vides, [], f"valeurs vides dans le catalogue '{lang}'")


if __name__ == "__main__":
    unittest.main()
