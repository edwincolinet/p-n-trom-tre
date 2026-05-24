"""
Pile undo/redo pour le Pénétromètre.

Stocke des snapshots de l'état complet de la mission (Chantier sérialisé
en dict) et permet de naviguer en arrière (undo) / en avant (redo).

Usage depuis l'App :
- `push(chantier)` avant chaque mutation discrète (add/edit/del).
- `undo(chantier)` → dict à restaurer (ou None si rien à annuler).
- `redo(chantier)` → dict à restaurer (ou None si rien à refaire).

Le snapshot est un dict JSON (via `persistence.chantier_to_dict`), ce
qui garantit un round-trip fidèle via `chantier_from_dict`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class UndoStack:
    _stack: List[Dict[str, Any]] = field(default_factory=list)
    _cursor: int = -1
    _max_depth: int = 50

    def push(self, snapshot: Dict[str, Any]) -> None:
        """Sauvegarde un snapshot avant mutation.

        Tronque le futur (tout ce qui est après le curseur) — un push
        après un undo annule le redo possible.
        """
        self._stack = self._stack[:self._cursor + 1]
        self._stack.append(snapshot)
        if len(self._stack) > self._max_depth:
            self._stack = self._stack[-self._max_depth:]
        self._cursor = len(self._stack) - 1

    def undo(self, current: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Recule d'un pas. Sauvegarde l'état courant au sommet si on
        est en bout de pile (premier undo d'une séquence).

        Renvoie le snapshot à restaurer, ou None si rien à annuler.
        """
        if self._cursor < 0:
            return None
        if self._cursor == len(self._stack) - 1:
            self._stack.append(current)
        result = self._stack[self._cursor]
        self._cursor -= 1
        return result

    def redo(self) -> Optional[Dict[str, Any]]:
        """Avance d'un pas. Renvoie le snapshot à restaurer, ou None."""
        if self._cursor + 2 >= len(self._stack):
            return None
        self._cursor += 1
        return self._stack[self._cursor + 1]

    def clear(self) -> None:
        """Vide la pile (après un open/new)."""
        self._stack.clear()
        self._cursor = -1

    @property
    def can_undo(self) -> bool:
        return self._cursor >= 0

    @property
    def can_redo(self) -> bool:
        return self._cursor + 2 < len(self._stack)
