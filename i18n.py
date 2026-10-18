"""
Internationalisation (i18n) du logiciel Pénétromètre Silvavenir.

Fournit `_()` pour marquer et traduire les chaînes visibles.
La langue est choisie dans les réglages (SettingsStore.language) et
appliquée au démarrage — un changement nécessite un redémarrage.

Langues : fr (source, défaut), en (English), it (Italiano).
Les traductions vivent dans translations/en.py et translations/it.py
sous forme de dicts Python {fr: traduction}. Cette approche évite de
compiler des fichiers .mo et reste lisible/éditable sans outillage
particulier. (Le package s'appelle `translations/` et non `locale/`
pour ne pas masquer le module `locale` de la stdlib — un package
`locale/` à la racine casse gettext/argparse, donc unittest et mypy.)

Pour ajouter une langue :
  1. Copier translations/en.py → translations/<code>.py.
  2. Remplir les valeurs manquantes.
  3. Ajouter le code dans LANGUAGES ci-dessous.
  4. Incrémenter settings.language.
"""

from __future__ import annotations

import logging
from typing import Dict

log = logging.getLogger("penetrometre")

# Langues disponibles : code ISO 639-1 → label affiché dans le menu
LANGUAGES: Dict[str, str] = {
    "fr": "Français",
    "en": "English",
    "it": "Italiano",
}

_current_lang: str = "fr"
_catalog: Dict[str, str] = {}


def setup_language(lang: str) -> None:
    """Charge le catalogue pour `lang`. Appelé une fois au démarrage,
    AVANT la création des widgets. Repasse à `fr` si langue inconnue."""
    global _current_lang, _catalog
    _current_lang = lang if lang in LANGUAGES else "fr"
    _catalog = {}
    if _current_lang == "fr":
        return
    try:
        if _current_lang == "en":
            from translations.en import TRANSLATIONS
        elif _current_lang == "it":
            from translations.it import TRANSLATIONS
        else:
            TRANSLATIONS = {}
        _catalog = TRANSLATIONS
    except ImportError:
        log.debug("i18n: catalogue '%s' introuvable, langue fr utilisée", lang)


def get_language() -> str:
    return _current_lang


def _(text: str) -> str:
    """Renvoie la traduction de `text` dans la langue courante.
    Repasse au texte source (français) si la traduction est absente."""
    if not _catalog:
        return text
    return _catalog.get(text, text)


def translate_values(options: "list[str]") -> "list[str]":
    """Traduit une liste de valeurs de modèle (français) pour l'affichage UI."""
    return [_(v) for v in options]


def untranslate_value(display: str, options: "list[str]") -> str:
    """Retrouve la valeur française d'une valeur affichée traduite.

    Parcourt `options` (valeurs françaises du modèle) et renvoie celle
    dont la traduction correspond à `display`. Fallback : renvoie `display`
    tel quel (langue française ou valeur inconnue).
    """
    for fr in options:
        if _(fr) == display:
            return fr
    return display
