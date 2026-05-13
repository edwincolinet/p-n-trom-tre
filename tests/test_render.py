"""Golden-image tests pour le rendu PIL (`render_arbre_to_pil_image`).

Quatre scénarios canoniques couvrent le pipeline de rendu :

1. `nu`             — arbre brut sans écorce ni contrefort ni dégradation.
2. `avec_ecorce`    — épaisseur d'écorce + 2 sondages opposés.
3. `contreforts`    — 2 contreforts adjacents qui doivent fusionner en
                       une seule cloche (verrou anti-encoche en V).
4. `degradation_sur_contrefort` — dégradation externe qui traverse un
                       contrefort et doit y mordre.

Les fixtures sont commitées dans `tests/fixtures/`. Pour régénérer
après un changement de rendu **intentionnel** :

    python -m tests.test_render --update

La comparaison utilise la **différence moyenne par pixel** (canal),
avec un seuil `MAX_MEAN_DIFF` permissif pour les variations subpixel
du rendu de texte selon la police disponible. Une régression
géométrique réelle (ex. cavité mal positionnée) dépasse largement le
seuil.

Skip silencieux si Pillow n'est pas installé.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Le `tests/__init__.py` ajoute la racine du projet à sys.path.
from tests._fixtures import SCENARIOS, build_arbre

try:
    from PIL import Image, ImageChops  # noqa: F401
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

# Seuil de différence moyenne par pixel/canal (0..255). 2.0 absorbe les
# variations subpixel de hinting des polices. Une régression
# géométrique réelle (ex. anneau d'écorce qui glisse de quelques cm)
# produit des différences bien au-delà.
MAX_MEAN_DIFF = 2.0

# Dimensions petites pour rendre les diffs lisibles et les fixtures
# légères. La géométrie reste correcte à toute échelle (cf. tests purs).
RENDER_W = 400
RENDER_H = 400


def _render(scenario: str):
    from pil_render import render_arbre_to_pil_image
    arbre = build_arbre(scenario)
    # `show_title=False` : pas de texte de titre dépendant des polices
    # locales. Les lettres cardinales restent (elles font partie du
    # rendu canonique) mais leur diff subpixel est absorbé par
    # `MAX_MEAN_DIFF`.
    img = render_arbre_to_pil_image(arbre, width=RENDER_W, height=RENDER_H,
                                      show_sondages=True,
                                      show_title=False,
                                      show_legend=False)
    return img.convert("RGB")  # mode stable indépendamment du backend


def _mean_diff(a, b) -> float:
    """Différence moyenne par pixel/canal, entre 0 et 255."""
    if a.size != b.size:
        raise AssertionError(f"taille différente : {a.size} vs {b.size}")
    if a.mode != b.mode:
        a = a.convert("RGB")
        b = b.convert("RGB")
    diff = ImageChops.difference(a, b)
    data = list(diff.getdata())
    if not data:
        return 0.0
    if isinstance(data[0], int):
        return sum(data) / len(data)
    return sum(sum(px) for px in data) / (len(data) * len(data[0]))


@unittest.skipUnless(HAS_PIL, "Pillow absent")
class GoldenImageTests(unittest.TestCase):
    """Vérifie que le rendu PIL n'a pas dérivé visuellement par rapport
    aux fixtures committées. Une régression géométrique (cavité
    décalée, contrefort oublié, dégradation mal positionnée) produit
    une diff bien au-dessus du seuil. Une simple variation de hinting
    de police reste en dessous."""

    def _assert_matches_fixture(self, scenario: str) -> None:
        fixture = FIXTURES_DIR / f"{scenario}.png"
        if not fixture.exists():
            self.fail(
                f"fixture absente : {fixture}\n"
                "Régénère les fixtures avec :\n"
                "    python -m tests.test_render --update")
        actual = _render(scenario)
        expected = Image.open(fixture).convert("RGB")
        diff = _mean_diff(actual, expected)
        self.assertLessEqual(
            diff, MAX_MEAN_DIFF,
            f"régression visuelle ({scenario}) : "
            f"diff moyenne {diff:.2f}/255 > seuil {MAX_MEAN_DIFF}. "
            f"Si le changement est INTENTIONNEL, régénérer "
            f"`{fixture.name}` avec `python -m tests.test_render --update`.")

    def test_arbre_nu(self):
        self._assert_matches_fixture("nu")

    def test_arbre_avec_ecorce_et_sondages(self):
        self._assert_matches_fixture("avec_ecorce")

    def test_contreforts_fusionnes(self):
        self._assert_matches_fixture("contreforts")

    def test_degradation_traverse_contrefort(self):
        self._assert_matches_fixture("degradation_sur_contrefort")


def _regenerate_fixtures() -> None:
    if not HAS_PIL:
        print("Pillow absent — impossible de générer les fixtures.",
              file=sys.stderr)
        sys.exit(1)
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    for scenario in SCENARIOS:
        img = _render(scenario)
        out = FIXTURES_DIR / f"{scenario}.png"
        img.save(out, format="PNG", optimize=True)
        print(f"  écrit : {out}")
    print(f"{len(SCENARIOS)} fixture(s) générée(s).")


if __name__ == "__main__":
    if "--update" in sys.argv:
        _regenerate_fixtures()
    else:
        unittest.main()
