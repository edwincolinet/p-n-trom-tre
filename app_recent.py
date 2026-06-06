"""
Historique des fichiers récents.

Petit magasin autonome (composition, pas de couplage à `App`) : il
détient la liste des derniers fichiers de mission ouverts/enregistrés,
la persiste dans `~/.penetrometre/recent.json` et notifie l'hôte via un
callback `on_change` (typiquement pour reconstruire le sous-menu
« Ouvrir récent »).

Tolérant par construction : toute erreur d'I/O (fichier absent, JSON
corrompu, permission) est journalisée et n'interrompt jamais l'app —
au pire l'historique repart vide.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable

log = logging.getLogger("penetrometre")


class RecentFilesStore:
    """Liste ordonnée (plus récent en tête) de chemins, dédupliquée et
    bornée à `maxlen`, persistée en JSON. `on_change` est appelé après
    chaque mutation persistée."""

    def __init__(self, path: Path, maxlen: int,
                 on_change: Callable[[], None]) -> None:
        self._path = path
        self._max = maxlen
        self._on_change = on_change
        self._items: list[str] = self._load()

    def get(self) -> list[str]:
        """Copie de l'historique (lecture pure pour le menu)."""
        return list(self._items)

    def push(self, path: str) -> None:
        """Pousse un chemin en tête (déduplication par chemin résolu),
        persiste, puis notifie l'hôte."""
        resolved = str(Path(path).resolve())
        self._items = [resolved] + [p for p in self._items if p != resolved]
        self._items = self._items[:self._max]
        self._save()
        self._on_change()

    def remove(self, path: str) -> None:
        """Retire un chemin (ex. fichier devenu introuvable), persiste,
        puis notifie l'hôte. Compare au chemin résolu ET au chemin brut
        (le fichier peut avoir disparu → `resolve()` ne le canonise pas)."""
        resolved = str(Path(path).resolve()) if Path(path).exists() else path
        self._items = [p for p in self._items
                       if p != resolved and p != path]
        self._save()
        self._on_change()

    def _load(self) -> list[str]:
        try:
            if self._path.exists():
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    return [str(x) for x in data
                            if isinstance(x, str)][:self._max]
        except Exception:
            log.exception("Lecture recent.json")
        return []

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._items, f, ensure_ascii=False, indent=2)
        except Exception:
            log.exception("Écriture recent.json")
