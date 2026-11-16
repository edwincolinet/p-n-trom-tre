"""Convertit assets/Icone.png en icônes natives pour chaque plateforme.

Usage :
    python build/build_icons.py

Produit dans build/icons/ :
    Icone.png   — Linux (AppImage)
    Icone.ico   — Windows (PyInstaller + Inno Setup)
    Icone.icns  — macOS  (PyInstaller + hdiutil), uniquement sur macOS
"""

import subprocess
import sys
from pathlib import Path

from PIL import Image

# La console Windows par défaut (cp1252) ne peut pas encoder ✓/— ci-dessous.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SRC = Path("assets/Icone.png")
OUT = Path("build/icons")
OUT.mkdir(parents=True, exist_ok=True)

img = Image.open(SRC).convert("RGBA")
# La source (feuille du logo) n'est pas carrée : on la centre sur un canevas
# carré transparent, sinon les redimensionnements ci-dessous la déformeraient.
_side = max(img.size)
_square = Image.new("RGBA", (_side, _side), (0, 0, 0, 0))
_square.paste(img, ((_side - img.width) // 2, (_side - img.height) // 2))
img = _square

# PNG — Linux
png_path = OUT / "Icone.png"
img.save(png_path)
print(f"  ✓ {png_path}")

# ICO — Windows (multi-résolution)
# PIEGE : Pillow ne produit que les tailles <= à celle de l'image BASE
# (`append_images` est ignoré pour l'ICO). Partir de la plus petite (16 px)
# donnait un .ico à UNE seule taille 16×16 → icône du raccourci/de l'exe
# énorme et pixélisée sous Windows. On part donc de la plus GRANDE (256 px).
ico_sizes = [16, 24, 32, 48, 64, 128, 256]
ico_path = OUT / "Icone.ico"
img.resize((256, 256), Image.LANCZOS).save(
    ico_path, format="ICO", sizes=[(s, s) for s in ico_sizes])
print(f"  ✓ {ico_path}")

# ICNS — macOS uniquement (requiert iconutil, fourni par Xcode Command Line Tools)
if sys.platform == "darwin":
    iconset = OUT / "Icone.iconset"
    iconset.mkdir(exist_ok=True)
    icns_sizes = {
        "icon_16x16.png": 16,
        "icon_16x16@2x.png": 32,
        "icon_32x32.png": 32,
        "icon_32x32@2x.png": 64,
        "icon_128x128.png": 128,
        "icon_128x128@2x.png": 256,
        "icon_256x256.png": 256,
        "icon_256x256@2x.png": 512,
        "icon_512x512.png": 512,
        "icon_512x512@2x.png": 1024,
    }
    for fname, size in icns_sizes.items():
        img.resize((size, size), Image.LANCZOS).save(iconset / fname)
    icns_path = OUT / "Icone.icns"
    subprocess.run(
        ["iconutil", "-c", "icns", str(iconset), "-o", str(icns_path)],
        check=True,
    )
    import shutil
    shutil.rmtree(iconset)
    print(f"  ✓ {icns_path}")
else:
    print("  — Icone.icns ignoré (génération possible sur macOS uniquement)")

print("Icônes générées.")
