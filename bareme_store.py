"""
Persistance du barème personnalisé dans ~/.penetrometre/bareme.json.

Module pur (sans Tkinter ni PIL). Utilisé par `penetrometre.App` au
démarrage (`_apply_bareme`) et par `action_bareme_settings` après
validation du dialog.

Travaille sur la forme **brute** (JSON-compatible, `List[Dict[str, float |
str | list]]`) — la validation/canonisation et la migration depuis
l'ancien format à 2 groupes fixes sont déléguées à
`bareme.seuils_depuis_brut`/`bareme.groupes_vers_brut` plutôt que
dupliquées ici.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from bareme import GROUPES_DEFAUT, groupes_vers_brut, seuils_depuis_brut

log = logging.getLogger("penetrometre")

_BAREME_PATH = Path.home() / ".penetrometre" / "bareme.json"


def load_bareme() -> List[Dict[str, Any]]:
    """Charge le barème depuis ~/.penetrometre/bareme.json.

    Retourne les groupes par défaut si le fichier est absent ou corrompu.
    Tolère aussi un fichier écrit par une version antérieure (2 groupes
    fixes nommés « libre »/« strict ») — migré silencieusement."""
    try:
        with open(_BAREME_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return groupes_vers_brut(seuils_depuis_brut(data))
    except FileNotFoundError:
        return get_defaults()
    except Exception:
        log.exception("Erreur lecture bareme.json — seuils par défaut utilisés")
        return get_defaults()


def save_bareme(data: List[Dict[str, Any]]) -> None:
    """Sauvegarde le barème. Écriture atomique (.tmp → replace)."""
    try:
        _BAREME_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _BAREME_PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp.replace(_BAREME_PATH)
    except Exception:
        log.exception("Erreur écriture bareme.json")


def get_defaults() -> List[Dict[str, Any]]:
    """Groupes par défaut (forme brute)."""
    return groupes_vers_brut(GROUPES_DEFAUT)
