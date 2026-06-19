#!/usr/bin/env bash
# Crée un DMG macOS à partir du bundle .app produit par PyInstaller.
# Usage : bash build/create_dmg.sh
# Pré-requis :
#   - PyInstaller déjà exécuté (dist/Penetrometre.app présent)
#   - create-dmg installé : brew install create-dmg
set -euo pipefail

VERSION=$(python3 build/get_version.py)
ARCH=$(uname -m)   # arm64 ou x86_64

APP_SRC="dist/Penetrometre.app"
DMG_PATH="dist/Penetrometre-${VERSION}-macOS-${ARCH}.dmg"

if [ ! -d "$APP_SRC" ]; then
    echo "Erreur : $APP_SRC introuvable. Lancer pyinstaller penetrometre.spec d'abord." >&2
    exit 1
fi

rm -f "$DMG_PATH"

create-dmg \
    --volname "Pénétromètre ${VERSION}" \
    --window-size 540 380 \
    --icon-size 128 \
    --icon "Penetrometre.app" 130 180 \
    --app-drop-link 410 180 \
    --no-internet-enable \
    "$DMG_PATH" \
    "$APP_SRC"

echo "DMG créé : $DMG_PATH"
