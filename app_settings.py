"""
Réglages d'interface persistés.

Petit magasin autonome (composition, pas de couplage à `App`), sur le
modèle de `app_recent.RecentFilesStore`. Détient pour l'instant un seul
réglage : `ui_scale`, le facteur d'agrandissement du texte de
l'interface (accessibilité — laptops de terrain en plein soleil, écrans
HiDPI). Persisté dans `~/.penetrometre/settings.json`.

Tolérant par construction : toute erreur d'I/O (fichier absent, JSON
corrompu) est journalisée et n'interrompt jamais l'app — au pire on
repart sur les valeurs par défaut.

Module pur (JSON + dict), testable sans Tk.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("penetrometre")

# Facteur d'échelle du texte. 1.0 = taille native (DPI système). Bornes
# volontairement modestes : au-delà, les libellés débordent des cases de
# saisie à largeur fixe. Presets exposés dans le menu « Affichage ».
UI_SCALE_MIN = 0.8
UI_SCALE_MAX = 1.6
UI_SCALE_DEFAULT = 1.0


class SettingsStore:
    """Réglages d'interface persistés en JSON. Lecture/écriture tolérante."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, object] = self._load()

    @property
    def ui_scale(self) -> float:
        """Facteur d'échelle du texte, borné à [MIN, MAX]."""
        raw = self._data.get("ui_scale", UI_SCALE_DEFAULT)
        try:
            val = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return UI_SCALE_DEFAULT
        return max(UI_SCALE_MIN, min(UI_SCALE_MAX, val))

    def set_ui_scale(self, value: float) -> None:
        """Fixe et persiste le facteur d'échelle (borné)."""
        self._data["ui_scale"] = max(UI_SCALE_MIN, min(UI_SCALE_MAX, value))
        self._save()

    def _load(self) -> dict[str, object]:
        try:
            if self._path.exists():
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            log.exception("Lecture settings.json")
        return {}

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception:
            log.exception("Écriture settings.json")
