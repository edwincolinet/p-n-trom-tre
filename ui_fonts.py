"""Échelle des polices de l'interface (accessibilité).

`tk scaling` (pixels par point) est **inopérant** sur certaines plateformes
(notamment plusieurs builds Tk/Linux où les métriques de police ne
dépendent pas du facteur de scaling). Le seul levier fiable est donc de
**multiplier le nombre de taille** de chaque police.

Ce module centralise un facteur d'échelle global de processus et un
helper `font(...)` qui l'applique. Il vit en bas du graphe de dépendances
(aucune dépendance) pour que toute la couche UI (app_style, panes,
dialogs, penetrometre) puisse l'importer sans cycle.

Le facteur est fixé une fois au démarrage par `App` depuis
`app_settings.SettingsStore.ui_scale`, **avant** la création des widgets.
À l'échelle 1.0, `font(...)` renvoie exactement la taille demandée — donc
aucune régression visuelle ni de golden-test par défaut.

NB : le dessin de la section (`section_canvas.py`, golden-testé, géométrie
en pixels fixes) n'utilise PAS ce helper — ses libellés sont dimensionnés
par rapport au diagramme, pas au texte de l'UI.
"""

from __future__ import annotations

from typing import Any

_scale: float = 1.0


def set_ui_scale(scale: float) -> None:
    """Fixe le facteur d'échelle global (process-wide)."""
    global _scale
    _scale = scale


def get_ui_scale() -> float:
    """Facteur d'échelle courant."""
    return _scale


def font(family: str, size: int, *options: str) -> tuple[Any, ...]:
    """Renvoie un tuple de police Tk avec la taille mise à l'échelle.

    `font("Helvetica", 10, "bold")` → `("Helvetica", 14, "bold")` à
    l'échelle 1.4. Taille plancher de 1 pt. À l'échelle 1.0, identité.

    Retour typé `tuple[Any, ...]` : la forme exacte attendue par les
    stubs tkinter (`tuple[str, int, *tuple[str, ...]]`) utilise la syntaxe
    d'unpack PEP 646, invalide pour la cible mypy `python_version = 3.9`.
    `tuple[Any, ...]` reste assignable au paramètre `font=` chez tous les
    appelants sans casser la CI 3.9.
    """
    return (family, max(1, round(size * _scale)), *options)
