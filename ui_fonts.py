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

# Familles de la charte SILVAVENIR : géométrique pour les titres, humaniste
# pour le texte courant et l'interface. Web : Jost / Source Sans 3 ;
# bureautique : Century Gothic / Segoe UI. Ni l'une ni l'autre n'est
# garantie sur le poste (Linux, macOS) : on prend la première INSTALLÉE de
# chaque liste de préférence, avec en dernier recours les familles
# historiques de l'app (« Georgia » titres → remplacée par Helvetica, qui
# existe partout). Tant que `resolve_brand_fonts` n'a pas été appelé (tests
# sans Tk), les familles historiques restent en vigueur.
_TITLE_PREFS = ("Jost", "Century Gothic")
_BODY_PREFS = ("Source Sans 3", "Segoe UI")
_LEGACY_TITLE = "Georgia"
_LEGACY_BODY = "Helvetica"
_family_title: str = _LEGACY_TITLE
_family_body: str = _LEGACY_BODY


def resolve_brand_fonts(root: Any) -> None:
    """Choisit les familles de titre/corps parmi celles installées.

    À appeler une fois, après la création de la racine Tk et avant celle
    des widgets. Sans Jost/Century Gothic, les titres retombent sur la
    famille du corps (sans empattement) plutôt que sur l'ancien Georgia :
    un titre à empattements jurerait avec le reste de la charte.
    """
    global _family_title, _family_body
    try:
        from tkinter import font as tkfont
        installed = {f.casefold(): f for f in tkfont.families(root)}
    except Exception:
        return
    body = next((installed[p.casefold()] for p in _BODY_PREFS
                 if p.casefold() in installed), _LEGACY_BODY)
    title = next((installed[p.casefold()] for p in _TITLE_PREFS
                  if p.casefold() in installed), body)
    _family_body, _family_title = body, title


def set_ui_scale(scale: float) -> None:
    """Fixe le facteur d'échelle global (process-wide)."""
    global _scale
    _scale = scale


def get_ui_scale() -> float:
    """Facteur d'échelle courant."""
    return _scale


def family_title() -> str:
    """Famille « titres » résolue (non mise à l'échelle) — pour le dessin
    de section, dont les polices ne suivent pas `ui_scale`."""
    return _family_title


def family_body() -> str:
    """Famille « corps » résolue (non mise à l'échelle)."""
    return _family_body


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
    # Les noms historiques (« Helvetica » corps, « Georgia » titres) sont des
    # RÔLES : ils sont traduits vers les familles de la charte résolues au
    # démarrage (cf. `resolve_brand_fonts`).
    if family == _LEGACY_BODY:
        family = _family_body
    elif family == _LEGACY_TITLE:
        family = _family_title
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
# - Familles : rôle « titre » (`font_title`, `font_heading`, nom historique
#   « Georgia ») = Jost / Century Gothic ; rôle « corps » (nom historique
#   « Helvetica ») = Source Sans 3 / Segoe UI pour tout le reste (corps de
#   texte, libellés, boutons). Cf. `resolve_brand_fonts`.
# - Ce sont des FONCTIONS (pas des constantes) : `_scale` n'est fixé par
#   `App` qu'au démarrage, après l'import des modules — un tuple figé à
#   l'import serait calculé avant que l'échelle utilisateur soit connue.

def font_title() -> tuple[Any, ...]:
    """Titre de marque (« Pénétromètre Silvavenir » du header et de l'écran d'accueil)."""
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
