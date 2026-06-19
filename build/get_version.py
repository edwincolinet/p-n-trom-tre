"""Affiche la version de l'app sur stdout.

Usage (toutes plateformes) :
    python build/get_version.py
"""
import re
import sys
from pathlib import Path

src = Path("penetrometre.py").read_text(encoding="utf-8")
m = re.search(r'__version__\s*=\s*"([^"]+)"', src)
if m is None:
    print("Erreur : __version__ introuvable dans penetrometre.py", file=sys.stderr)
    sys.exit(1)
print(m.group(1))
