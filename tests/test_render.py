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
    # `tobytes()` plutôt que `getdata()` (déprécié Pillow 12, retiré 14) :
    # stable sur toute la plage supportée, et donne directement la suite
    # des octets par canal (1/pixel en « L », 3/pixel en « RGB »). La
    # moyenne par octet = la moyenne par pixel·canal recherchée.
    data = diff.tobytes()
    if not data:
        return 0.0
    return sum(data) / len(data)


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

    def test_cepee_multi_brins(self):
        self._assert_matches_fixture("cepee")

    def test_cepee_rotation(self):
        self._assert_matches_fixture("cepee_rotation")


@unittest.skipUnless(HAS_PIL, "Pillow absent")
class CepeeExportLayoutTests(unittest.TestCase):
    """L'export PNG d'une cépée doit remplir la zone basse (brins centrés
    verticalement + légende), au lieu de laisser ~40 % de blanc en bas
    (régression du cadrage top-aligné)."""

    def test_cepee_remplit_la_zone_basse(self):
        from pil_render import render_arbre_to_pil_image
        from tests._fixtures import build_arbre
        a = build_arbre("cepee")
        H = 2400
        img = render_arbre_to_pil_image(a, 2400, H, show_sondages=True,
                                        show_legend=True)
        px = img.load()
        bg = px[0, 0]
        last = max((y for y in range(H)
                    if any(px[x, y] != bg for x in range(0, img.size[0], 7))),
                   default=0)
        # Le contenu (jusqu'à la légende) descend bien au-delà des 3/4 de la
        # hauteur — avant le correctif il s'arrêtait vers 60 %.
        self.assertGreater(last, 0.75 * H)


@unittest.skipUnless(HAS_PIL, "Pillow absent")
class ComparaisonExportPagesTests(unittest.TestCase):
    """Export de la ré-inspection : une page par brin pour une cépée (PDF
    multi-pages / PNG empilé), une page genet pour un mono-caule."""

    @staticmethod
    def _arbre(n_brins: int, sain: float):
        from model import Arbre, Sondage
        a = Arbre(numero_arbre="1", port_arbre="libre")
        a.brins[0].set_rayon(20.0)
        for g in (0, 100, 200, 300):
            a.brins[0].sondages.append(
                Sondage(grade=g, bois_sain_cm=sain,
                        bois_altere_cm=20.0 - sain))
        for _ in range(n_brins - 1):
            a.ajouter_brin()
        return a

    def test_une_page_pour_mono_caule(self):
        from comparaison_render import render_comparison_pages
        pages = render_comparison_pages(
            "M", self._arbre(1, 8.0), self._arbre(1, 5.0), 2.0,
            ref_label="2024", cur_label="2026")
        self.assertEqual(len(pages), 1)

    def test_une_page_par_brin_pour_cepee(self):
        # Réf 1 brin, courant 3 brins → 3 pages (brins b, c orphelins).
        from comparaison_render import render_comparison_pages
        pages = render_comparison_pages(
            "M", self._arbre(1, 8.0), self._arbre(3, 5.0), 2.0,
            ref_label="2024", cur_label="2026")
        self.assertEqual(len(pages), 3)

    def test_show_sondages_false_masque_les_fleches(self):
        # La case « Afficher sondages » doit être respectée dans l'export :
        # avec sondages, les flèches ajoutent des pixels → rendu différent.
        from PIL import ImageChops

        from comparaison_render import render_comparison_pages
        ref, cur = self._arbre(1, 8.0), self._arbre(1, 5.0)
        on = render_comparison_pages("M", ref, cur, 2.0, ref_label="r",
                                     cur_label="c", show_sondages=True)[0]
        off = render_comparison_pages("M", ref, cur, 2.0, ref_label="r",
                                      cur_label="c", show_sondages=False)[0]
        self.assertIsNotNone(ImageChops.difference(on, off).getbbox())

    def test_png_empile_les_pages_d_une_cepee(self):
        import os
        import tempfile

        from PIL import Image

        from comparaison_render import (
            _PAGE_H,
            render_comparison_pages,
            save_comparison_png,
        )
        pages = render_comparison_pages(
            "M", self._arbre(1, 8.0), self._arbre(2, 5.0), 2.0,
            ref_label="2024", cur_label="2026")
        path = os.path.join(tempfile.mkdtemp(), "c.png")
        save_comparison_png(pages, path)
        self.assertEqual(Image.open(path).height, 2 * _PAGE_H)


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
