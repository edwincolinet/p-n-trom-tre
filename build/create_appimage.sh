#!/usr/bin/env bash
# Crée un AppImage Linux à partir du dossier produit par PyInstaller.
# Usage : bash build/create_appimage.sh
# Pré-requis : PyInstaller déjà exécuté (dist/Penetrometre/ présent)
set -euo pipefail

VERSION=$(python3 -c "
import re
m = re.search(r'__version__\s*=\s*\"([^\"]+)\"', open('penetrometre.py').read())
print(m.group(1))
")

SRC="dist/Penetrometre"
APPDIR="dist/Penetrometre.AppDir"
APPIMAGE_OUT="dist/Penetrometre-${VERSION}-linux-x86_64.AppImage"
TOOL="/tmp/appimagetool"

if [ ! -d "$SRC" ]; then
    echo "Erreur : $SRC introuvable. Lancer pyinstaller penetrometre.spec d'abord." >&2
    exit 1
fi

# --- Structure AppDir ---
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
cp -r "$SRC"/. "$APPDIR/usr/bin/"

# AppRun : point d'entrée de l'AppImage
cat > "$APPDIR/AppRun" << 'APPRUN'
#!/bin/bash
HERE="$(dirname "$(readlink -f "${0}")")"
exec "$HERE/usr/bin/Penetrometre" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

# Fichier .desktop (requis par appimagetool)
cat > "$APPDIR/penetrometre.desktop" << DESKTOP
[Desktop Entry]
Name=Pénétromètre
Exec=Penetrometre
Icon=penetrometre
Type=Application
Categories=Science;Education;
Comment=Expertise arboricole au pénétromètre — Silvavenir
DESKTOP

# Icône (PNG 256×256 au minimum)
cp build/icons/Icone.png "$APPDIR/penetrometre.png"

# --- Télécharger appimagetool si absent ---
# Épinglé sur la release 13 (stable) au lieu de "continuous" (nightly, peut casser)
APPIMAGETOOL_VERSION="13"
if [ ! -f "$TOOL" ]; then
    echo "Téléchargement d'appimagetool ${APPIMAGETOOL_VERSION}..."
    wget -q -O "$TOOL" \
        "https://github.com/AppImage/AppImageKit/releases/download/${APPIMAGETOOL_VERSION}/appimagetool-x86_64.AppImage"
    chmod +x "$TOOL"
fi

# Désactiver l'interprétation FUSE de l'outil lui-même en mode CI
# (les runners GitHub n'ont pas FUSE par défaut)
export APPIMAGE_EXTRACT_AND_RUN=1

ARCH=x86_64 "$TOOL" "$APPDIR" "$APPIMAGE_OUT"
echo "AppImage créée : $APPIMAGE_OUT"
