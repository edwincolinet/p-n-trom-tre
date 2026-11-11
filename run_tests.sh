#!/usr/bin/env bash
# Lance la suite de tests complète (Tk compris) sans polluer le bureau.
# Python : ./venv si présent, sinon python3. Affichage : xvfb-run si installé,
# sinon Xephyr (serveur X imbriqué), sinon le DISPLAY courant.
# Usage : ./run_tests.sh [arguments pytest…]   (défaut : tests -q)
set -euo pipefail
cd "$(dirname "$0")"

PY=python3
[ -x venv/bin/python ] && PY=venv/bin/python
[ "$#" -eq 0 ] && set -- tests -q

if command -v xvfb-run >/dev/null 2>&1; then
    exec xvfb-run -a "$PY" -m pytest "$@"
elif command -v Xephyr >/dev/null 2>&1; then
    D=":$((90 + RANDOM % 9))"
    Xephyr "$D" -screen 1400x900 -ac -nolisten tcp >/dev/null 2>&1 &
    XPID=$!
    trap 'kill "$XPID" 2>/dev/null || true' EXIT
    sleep 2
    DISPLAY="$D" "$PY" -m pytest "$@"
else
    exec "$PY" -m pytest "$@"
fi
