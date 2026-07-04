"""Build Nuitka de l'app — binaire COMPILÉ (alternative à PyInstaller).

Nuitka traduit le Python en C puis le compile : le binaire est plus rapide
au démarrage et **nettement plus dur à décompiler** qu'un bundle PyInstaller
(qui n'embarque que des `.pyc` triviaux à extraire) — utile en complément de
la vérification de licence Ed25519.

Ce driver **réplique** `penetrometre.spec` (mêmes données embarquées, mêmes
paquets, mode fenêtré, icône par plateforme). PyInstaller reste le build de
référence ; celui-ci est une option.

Prérequis : un compilateur C (gcc/clang sur Linux/macOS, MSVC ou MinGW sur
Windows — Nuitka le télécharge au besoin), `patchelf` sur Linux, et
`pip install -r requirements-dev.txt` (Nuitka).

Usage (toutes plateformes, depuis la racine du repo) :
    python build/build_icons.py       # génère build/icons/
    python build/build_nuitka.py      # → dist-nuitka/penetrometre.dist/

Options :
    --onefile   produit un exécutable unique au lieu d'un dossier autonome.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_OUT = _ROOT / "dist-nuitka"


def _version() -> str:
    src = (_ROOT / "penetrometre.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', src)
    return m.group(1) if m else "0.0.0"


def _icon_args() -> list[str]:
    """Argument d'icône selon la plateforme (icônes générées par
    build/build_icons.py). Absent = build sans icône (non bloquant)."""
    icons = _ROOT / "build" / "icons"
    if sys.platform == "win32" and (icons / "Icone.ico").exists():
        return [f"--windows-icon-from-ico={icons / 'Icone.ico'}"]
    if sys.platform == "darwin" and (icons / "Icone.icns").exists():
        return [f"--macos-app-icon={icons / 'Icone.icns'}"]
    if (icons / "Icone.png").exists():
        return [f"--linux-icon={icons / 'Icone.png'}"]
    return []


def _platform_args() -> list[str]:
    """Options spécifiques à la plateforme (console, bundle .app)."""
    if sys.platform == "win32":
        # Pas de fenêtre console (équivalent `console=False` du spec).
        return ["--windows-console-mode=disable"]
    if sys.platform == "darwin":
        return ["--macos-create-app-bundle",
                f"--macos-app-version={_version()}"]
    return []


def main() -> int:
    onefile = "--onefile" in sys.argv[1:]
    mode = "--onefile" if onefile else "--standalone"

    cmd = [
        sys.executable, "-m", "nuitka",
        mode,
        # Tkinter : embarque Tcl/Tk et ses données (rose des vents, etc.).
        "--enable-plugin=tk-inter",
        # Données embarquées — miroir des `datas` du spec PyInstaller.
        "--include-data-dir=assets=assets",
        "--include-data-dir=exemples=exemples",
        # Imports parfois chargés dynamiquement (miroir des `hiddenimports`).
        "--include-package=openpyxl",
        "--include-package=cryptography",
        # Catalogues i18n : modules Python (pas des données) importés
        # statiquement par i18n.py ; on force le package pour garantir que
        # toute langue (présente ou future) soit embarquée.
        "--include-package=translations",
        # tkinter.test pèse ~10 Mo et ne sert à rien à l'usage.
        "--nofollow-import-to=tkinter.test",
        # Métadonnées binaire.
        "--company-name=Edwin Colinet",
        "--product-name=Penetrometre Pénétromètre",
        f"--product-version={_version()}",
        "--output-filename=Penetrometre",
        f"--output-dir={_OUT}",
        # Nuitka peut télécharger sa toolchain (MinGW/depends) : on accepte.
        "--assume-yes-for-downloads",
        *_icon_args(),
        *_platform_args(),
        "penetrometre.py",
    ]

    print("→", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.call(cmd, cwd=_ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
