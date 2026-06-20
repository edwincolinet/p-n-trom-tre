"""
Persistance du barème personnalisé dans ~/.penetrometre/bareme.json.

Module pur (sans Tkinter ni PIL). Utilisé par `penetrometre.App` au
démarrage (`_apply_bareme`) et par `action_bareme_settings` après
validation du dialog.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("penetrometre")

_BAREME_PATH = Path.home() / ".penetrometre" / "bareme.json"

_DEFAULTS: dict[str, dict[str, float]] = {
    "libre":  {"vert": 0.30, "orange": 0.15},
    "strict": {"vert": 0.20, "orange": 0.10},
}


def load_bareme() -> dict[str, dict[str, float]]:
    """Charge le barème depuis ~/.penetrometre/bareme.json.

    Retourne les seuils par défaut si le fichier est absent ou corrompu.
    Les valeurs inconnues/invalides sont remplacées par les défauts
    correspondants (tolérance de migration)."""
    try:
        with open(_BAREME_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return _validated(data)
    except FileNotFoundError:
        return {k: dict(v) for k, v in _DEFAULTS.items()}
    except Exception:
        log.exception("Erreur lecture bareme.json — seuils par défaut utilisés")
        return {k: dict(v) for k, v in _DEFAULTS.items()}


def save_bareme(data: dict[str, dict[str, float]]) -> None:
    """Sauvegarde le barème. Écriture atomique (.tmp → replace)."""
    try:
        _BAREME_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _BAREME_PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp.replace(_BAREME_PATH)
    except Exception:
        log.exception("Erreur écriture bareme.json")


def get_defaults() -> dict[str, dict[str, float]]:
    """Valeurs par défaut (copie)."""
    return {k: dict(v) for k, v in _DEFAULTS.items()}


def _validated(data: object) -> dict[str, dict[str, float]]:
    """Valide et complète un dict brut. Garantit cohérence vert > orange > 0."""
    if not isinstance(data, dict):
        return {k: dict(v) for k, v in _DEFAULTS.items()}
    result: dict[str, dict[str, float]] = {}
    for grp in ("libre", "strict"):
        grp_data = data.get(grp, {}) if isinstance(data, dict) else {}
        vert = float(grp_data.get("vert", _DEFAULTS[grp]["vert"]))
        orange = float(grp_data.get("orange", _DEFAULTS[grp]["orange"]))
        vert = max(0.01, min(0.99, vert))
        orange = max(0.01, min(vert - 0.01, orange))
        result[grp] = {"vert": round(vert, 4), "orange": round(orange, 4)}
    return result
