# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec — Pénétromètre Silvavenir
#
# Build :
#   pip install pyinstaller
#   python build/build_icons.py   # génère build/icons/
#   pyinstaller penetrometre.spec
#
# Résultat dans dist/Penetrometre/ (dossier autonome).
# L'installeur natif est ensuite produit par les scripts build/*.

import re
import sys
from pathlib import Path

_src = Path("penetrometre.py").read_text(encoding="utf-8")
_version = re.search(r'__version__\s*=\s*"([^"]+)"', _src).group(1)

# Icône selon la plateforme (générée par build/build_icons.py)
if sys.platform == "win32":
    _icon = "build/icons/Icone.ico"
elif sys.platform == "darwin":
    _icon = "build/icons/Icone.icns"
else:
    _icon = "build/icons/Icone.png"

a = Analysis(
    ["penetrometre.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("assets", "assets"),
        ("exemples", "exemples"),
        ("docs", "docs"),
        # Boutons « Licence (CLU) »/« Confidentialité » de la fenêtre
        # « À propos » (`penetrometre._open_doc`) : sans eux, ces boutons
        # affichaient « Fichier introuvable » dans l'exécutable empaqueté
        # (absent avant le 2026-09-06, repéré à l'usage).
        ("LICENSE", "."),
        ("PRIVACY.md", "."),
    ],
    hiddenimports=[
        "PIL._imaging",
        "openpyxl",
        "openpyxl.styles.stylesheet",
        # Vérification de licence offline (Ed25519)
        "cryptography",
        "cryptography.hazmat.primitives.asymmetric.ed25519",
        "cryptography.hazmat.backends",
    ],
    hookspath=[],
    runtime_hooks=[],
    # tkinter.test pèse ~10 Mo et ne sert pas à l'usage.
    excludes=["tkinter.test", "_tkinter.test"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Penetrometre",
    debug=False,
    strip=False,
    upx=False,  # UPX déclenche des faux positifs antivirus ; désactivé
    console=False,   # pas de fenêtre console
    icon=_icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Penetrometre",
)

# Bundle .app uniquement sur macOS
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Penetrometre.app",
        icon="build/icons/Icone.icns",
        bundle_identifier="fr.edwincolinet.penetrometre",
        info_plist={
            "CFBundleDisplayName": "Pénétromètre",
            "CFBundleShortVersionString": _version,
            "CFBundleVersion": _version,
            "NSHighResolutionCapable": True,
            "NSPrincipalClass": "NSApplication",
            "NSAppleScriptEnabled": False,
        },
    )
