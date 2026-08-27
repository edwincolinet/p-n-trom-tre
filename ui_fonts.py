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


# ----------------------------------------------------------------------
# Échelle typographique nommée (design system)
# ----------------------------------------------------------------------
#
# Avant ces tokens, chaque style ttk / label inline fixait sa propre
# police en dur, éparpillant des variantes quasi identiques sans nom
# partagé (`("Helvetica", 10)` vs `("Helvetica", 9)` pour le même rôle de
# texte secondaire selon le fichier, etc.). Ces fonctions ne changent PAS
# les tailles de base déjà choisies (aucune régression visuelle voulue) :
# elles se contentent de leur donner UN SEUL nom par rôle récurrent, pour
# que toute évolution future se fasse à un seul endroit. Chaque appelant
# doit préférer le token le plus proche de son besoin plutôt que
# d'inventer une nouvelle variante ; un besoin réellement isolé (taille
# ponctuelle sans autre occurrence dans la base) reste un `font(...)`
# direct plutôt qu'un token à usage unique.
#
# - Familles : « Georgia » (serif) réservée aux titres de marque/section
#   (`font_title`, `font_heading`) ; « Helvetica » (sans-serif) pour tout
#   le reste (corps de texte, libellés, boutons).
# - Ce sont des FONCTIONS (pas des constantes) : `_scale` n'est fixé par
#   `App` qu'au démarrage, après l'import des modules — un tuple figé à
#   l'import serait calculé avant que l'échelle utilisateur soit connue.

def font_title() -> tuple[Any, ...]:
    """Titre de marque (« Pénétromètre » du header et de l'écran d'accueil)."""
    return font("Georgia", 18, "bold")


def font_subtitle() -> tuple[Any, ...]:
    """Sous-titre accolé au titre de marque (« Expertise arboricole »)."""
    return font("Helvetica", 10, "italic")


def font_heading() -> tuple[Any, ...]:
    """Titre de section (panneaux, en-têtes de bloc)."""
    return font("Georgia", 12, "bold")


def font_subheading() -> tuple[Any, ...]:
    """Titre de sous-bloc (écho de brin courant, en-têtes de dialogue)."""
    return font("Helvetica", 11, "bold")


def font_body() -> tuple[Any, ...]:
    """Corps de texte standard (valeur par défaut des styles ttk)."""
    return font("Helvetica", 10)


def font_body_bold() -> tuple[Any, ...]:
    """Corps de texte en avant (boutons, en-têtes de tableau)."""
    return font("Helvetica", 10, "bold")


def font_small() -> tuple[Any, ...]:
    """Texte secondaire (aide, sous-titres, barre d'état)."""
    return font("Helvetica", 9)


def font_small_bold() -> tuple[Any, ...]:
    """Texte secondaire en avant (bannières, indicateurs d'état)."""
    return font("Helvetica", 9, "bold")


def font_small_italic() -> tuple[Any, ...]:
    """Texte secondaire atténué (footer de triage, libellés de filtre)."""
    return font("Helvetica", 9, "italic")


# ----------------------------------------------------------------------
# Espacements nommés (design system)
# ----------------------------------------------------------------------
#
# Pas de retrofit systématique de tous les `padx=`/`pady=` existants
# (trop de surface pour un app hand-tuned au pixel, risque de régression
# visuelle sans gain proportionné) : ces constantes sont à disposition du
# code déjà touché par une évolution, pas une migration forcée.
SPACE_XS = 4
SPACE_S = 6
SPACE_M = 10
SPACE_L = 14
SPACE_XL = 18
