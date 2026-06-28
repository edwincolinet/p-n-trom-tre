"""
Pile undo/redo pour le Pénétromètre.

Stocke des snapshots de l'état complet de la mission (Chantier sérialisé
en dict) et permet de naviguer en arrière (undo) / en avant (redo).

Usage depuis l'App :
- `push(snapshot)` avant chaque mutation discrète (add/edit/del).
- Avant le premier `undo()` d'une séquence, appeler `set_live_tip(current)`
  pour sauvegarder l'état courant non poussé (nécessaire au redo).
  `set_live_tip` est idempotent : seul le premier appel d'une séquence
  d'undos est effectif. `push()` remet automatiquement le tip à None.
- `undo()` → dict à restaurer (ou None si rien à annuler).
- `redo()` → dict à restaurer (ou None si rien à refaire).

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
    # État vivant au-delà du dernier push : nécessaire pour le redo après
    # le premier undo d'une séquence (la valeur non poussée qui serait perdue
    # sinon). Remis à None par push() — une nouvelle mutation invalide le redo.
    _live_tip: Optional[Dict[str, Any]] = field(default=None)

    def push(self, snapshot: Dict[str, Any]) -> None:
        """Sauvegarde un snapshot avant mutation.

        Tronque le futur (tout ce qui est après le curseur) — un push
        après un undo annule le redo possible. Remet également le live_tip
        à None : la nouvelle mutation devient le point de départ du prochain
        set_live_tip.
        """
        self._stack = self._stack[:self._cursor + 1]
        self._live_tip = None
        self._stack.append(snapshot)
        if len(self._stack) > self._max_depth:
            self._stack = self._stack[-self._max_depth:]
        self._cursor = len(self._stack) - 1

    def set_live_tip(self, tip: Dict[str, Any]) -> None:
        """Sauvegarde l'état vivant courant pour permettre le redo.

        À appeler une fois avant le premier `undo()` d'une séquence.
        Idempotent : les appels suivants (même séquence d'undos) sont
        des no-ops, ce qui évite de sérialiser le chantier à chaque
        pression de Ctrl+Z.
        """
        if self._live_tip is None:
            self._live_tip = tip

    def undo(self) -> Optional[Dict[str, Any]]:
        """Recule d'un pas.

        Renvoie le snapshot à restaurer, ou None si rien à annuler.
        Appeler `set_live_tip(current)` avant le premier undo d'une
        séquence pour que le redo puisse revenir à l'état courant.
        """
        if self._cursor < 0:
            return None
        result = self._stack[self._cursor]
        self._cursor -= 1
        return result

    def redo(self) -> Optional[Dict[str, Any]]:
        """Avance d'un pas. Renvoie le snapshot à restaurer, ou None."""
        if self._cursor + 1 >= len(self._stack):
            return None
        self._cursor += 1
        next_idx = self._cursor + 1
        if next_idx >= len(self._stack):
            # On vient d'atteindre le sommet de la pile explicite :
            # le snapshot suivant est le live_tip (état non poussé).
            return self._live_tip
        return self._stack[next_idx]

    def clear(self) -> None:
        """Vide la pile (après un open/new)."""
        self._stack.clear()
        self._cursor = -1
        self._live_tip = None

    @property
    def can_undo(self) -> bool:
        return self._cursor >= 0

    @property
    def can_redo(self) -> bool:
        n = len(self._stack)
        if self._live_tip is not None:
            # Le live_tip occupe la position virtuelle juste après stack[-1].
            return self._cursor + 1 < n
        return self._cursor + 2 < n
