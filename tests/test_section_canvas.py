"""Golden-fixture tests pour `SectionCanvas` (rendu Tk).

Comble la zone aveugle laissée par `test_render.py` : ce dernier ne
couvre que le rendu PIL. Une régression purement Tk (palette, marge,
item oublié, polygone décalé) passait jusqu'ici inaperçue jusqu'au
lancement de l'app.

Stratégie : on dump la LISTE des items dessinés sur le `Canvas`
(`type`, `coords`, `fill`, `outline`, `width`, `text`, `anchor`), pas
un screenshot pixel. Avantages :

- compact (~10-30 KB JSON vs 50 KB PNG par fixture) ;
- diff lisible humainement en cas de régression ;
- déterministe cross-OS : pas de glyph rendering ni de hinting de
  police à filtrer ;
- testable en CI headless via `xvfb-run`.

Skipped silencieusement quand :
- `tkinter` indisponible (rare) ;
- `DISPLAY` indisponible (CI sans Xvfb, SSH sans X11).

Pour régénérer les fixtures après un changement INTENTIONNEL du rendu
Tk (couleur, marge, géométrie partagée déplacée…) :

    xvfb-run -a python -m tests.test_section_canvas --update
    # ou, en local avec un X server :
    python -m tests.test_section_canvas --update
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

# Le `tests/__init__.py` ajoute la racine du projet à sys.path.
from tests._fixtures import SCENARIOS, build_arbre

# Détection : tkinter charge-t-il, et peut-on ouvrir un display ?
# La sonde est faite une seule fois à l'import du module ; sous Xvfb
# c'est instantané.
_TK_AVAILABLE = False
_DISPLAY_OK = False
try:
    import tkinter as tk  # noqa: F401  (utilisé plus bas)
    _TK_AVAILABLE = True
    try:
        _probe = tk.Tk()
        _probe.destroy()
        _DISPLAY_OK = True
    except tk.TclError:
        pass
except ImportError:
    pass


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

# Dimensions du canvas pour le rendu de test. Petites pour fixtures
# légères, mais assez grandes pour que toutes les zones (titre, lettres
# cardinales, règle graduée) tiennent.
CANVAS_W = 600
CANVAS_H = 700


def _canvas_dump(canvas) -> list:
    """Sérialise tous les items d'un `Canvas` Tk en liste stable.

    Pour chaque item : `type`, `coords` (arrondies à 0.1 px pour
    absorber les variations sub-pixel), et les attributs visuels
    stables (`fill`, `outline`, `width`, `text`, `anchor`) — uniquement
    quand non vides, pour limiter le bruit dans les fixtures.

    L'ordre suit `find_all()` (stacking order Tk), qui est déterministe
    tant qu'on ne touche pas à `tag_raise` / `tag_lower`.
    """
    items = []
    for iid in canvas.find_all():
        item_type = canvas.type(iid)
        coords = [round(c, 1) for c in canvas.coords(iid)]
        d = {"type": item_type, "coords": coords}
        for opt in ("fill", "outline", "width", "text", "anchor"):
            try:
                v = canvas.itemcget(iid, opt)
            except tk.TclError:
                continue
            # Filtre des valeurs par défaut : "", "0", "0.0" — pour
            # qu'une valeur explicitement à 0 ne pollue pas le diff.
            if v in ("", "0", "0.0", "center"):
                continue
            d[opt] = v
        items.append(d)
    return items


def _render_canvas(scenario: str) -> list:
    """Crée une `SectionCanvas`, y charge l'arbre du scénario, et
    retourne le dump des items dessinés."""
    import ui_fonts
    from section_canvas import SectionCanvas

    # Familles de la charte résolues selon les polices INSTALLÉES (donc
    # variables d'un poste à l'autre, et modifiées par tout test qui crée
    # une `App`) : on fige les noms historiques pour un golden reproductible.
    saved = (ui_fonts._family_title, ui_fonts._family_body)
    ui_fonts._family_title, ui_fonts._family_body = "Georgia", "Helvetica"
    root = tk.Tk()
    try:
        # Fenêtre dimensionnée explicitement pour que `winfo_width()`
        # retourne la valeur attendue après `update_idletasks()`.
        root.geometry(f"{CANVAS_W}x{CANVAS_H}+0+0")
        canvas = SectionCanvas(root, width=CANVAS_W, height=CANVAS_H)
        canvas.pack()
        root.update_idletasks()
        canvas.set_arbre(build_arbre(scenario))
        root.update_idletasks()
        items = _canvas_dump(canvas)
    finally:
        root.destroy()
        ui_fonts._family_title, ui_fonts._family_body = saved
    return items


@unittest.skipUnless(_DISPLAY_OK,
                     "DISPLAY indisponible (CI sans Xvfb, SSH sans X11)")
class SectionCanvasGoldenTests(unittest.TestCase):
    """Vérifie que `SectionCanvas.redraw()` produit la même liste
    d'items qu'à l'enregistrement de la fixture. Capture les
    régressions invisibles à l'œil mais bien réelles : couleur basculée,
    polygone décalé de quelques pixels, item oublié après un refactor."""

    def _assert_matches_fixture(self, scenario: str) -> None:
        fixture = FIXTURES_DIR / f"section_canvas_{scenario}.json"
        if not fixture.exists():
            self.fail(
                f"fixture absente : {fixture}\n"
                "Régénère avec :\n"
                "    xvfb-run -a python -m tests.test_section_canvas --update")
        actual = _render_canvas(scenario)
        with open(fixture, "r", encoding="utf-8") as f:
            expected = json.load(f)
        self.assertEqual(
            actual, expected,
            f"régression visuelle Tk ({scenario}). Si le changement est "
            "INTENTIONNEL, régénère la fixture avec :\n"
            "    xvfb-run -a python -m tests.test_section_canvas --update")

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


def _regenerate_fixtures() -> None:
    if not _DISPLAY_OK:
        print("DISPLAY indisponible — impossible de générer les fixtures.",
              file=sys.stderr)
        print("Lance sous Xvfb : xvfb-run -a python -m tests.test_section_canvas --update",
              file=sys.stderr)
        sys.exit(1)
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    for scenario in SCENARIOS:
        items = _render_canvas(scenario)
        out = FIXTURES_DIR / f"section_canvas_{scenario}.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2, ensure_ascii=False)
        print(f"  écrit : {out} ({len(items)} items)")
    print(f"{len(SCENARIOS)} fixture(s) générée(s).")


if __name__ == "__main__":
    if "--update" in sys.argv:
        _regenerate_fixtures()
    else:
        unittest.main()
