"""Garde-fou icônes : l'.ico Windows doit contenir toutes les tailles.

Régression : Pillow ignore `append_images` pour l'ICO ; partir de la plus
petite image donnait un .ico à une seule taille 16×16 (icône pixélisée sous
Windows)."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from PIL import Image

_ROOT = Path(__file__).resolve().parent.parent


class TestIconeWindows(unittest.TestCase):
    def test_ico_multi_tailles_et_source_haute_resolution(self) -> None:
        self.assertGreaterEqual(Image.open(_ROOT / "assets" / "Icone.png").width, 512)
        subprocess.run([sys.executable, "build/build_icons.py"], cwd=_ROOT,
                       check=True, capture_output=True)
        with Image.open(_ROOT / "build" / "icons" / "Icone.ico") as ico:
            tailles = {s[0] for s in ico.info["sizes"]}
        self.assertTrue({16, 32, 48, 256} <= tailles, tailles)


if __name__ == "__main__":
    unittest.main()
