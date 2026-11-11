"""Profil du cabinet appliqué au PREMIER lancement d'un poste.

Module pur (stdlib, sans Tk). Permet de livrer l'application déjà réglée
aux couleurs du cabinet : `assets/profil_cabinet/profil.json` (embarqué dans
l'installeur) fournit des valeurs initiales pour les réglages de poste.

Règles :
  - appliqué **une seule fois** par poste (marqueur `.profil_applique` dans
    le dossier utilisateur) ;
  - **n'écrase jamais** un réglage déjà posé (nom, logo, barème, dossier de
    mises à jour) : un poste déjà configuré reste tel quel ;
  - tolérant : profil absent / illisible / clé inconnue → ignoré, jamais
    d'exception (le démarrage ne doit pas en dépendre).

Clés reconnues de `profil.json` (toutes optionnelles) :
  `cabinet_name`  : nom affiché dans le pied de page des exports ;
  `logo`          : nom d'un fichier image placé à côté de `profil.json` ;
  `bareme`        : liste de groupes (forme brute de `bareme_store`) ;
  `update_folder` : dossier partagé des installeurs (mises à jour).
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any, Callable, Optional

from bareme import groupes_vers_brut, seuils_depuis_brut

log = logging.getLogger("penetrometre")

MARQUEUR = ".profil_applique"
_LOGO_SUFFIXES = {".png", ".jpg", ".jpeg"}


def appliquer_profil_initial(
        settings: Any,
        profil_dir: Path,
        user_dir: Path,
        bareme_existe: Callable[[], bool],
        ecrire_bareme: Callable[[list[dict[str, Any]]], None],
) -> bool:
    """Applique `profil_dir/profil.json` s'il existe et n'a pas déjà été
    appliqué. `settings` = `SettingsStore` (cabinet_name, logo_path,
    update_folder). Renvoie True si un profil a été appliqué."""
    marqueur = user_dir / MARQUEUR
    profil_json = profil_dir / "profil.json"
    try:
        if marqueur.exists() or not profil_json.is_file():
            return False
        profil = json.loads(profil_json.read_text(encoding="utf-8"))
        if not isinstance(profil, dict):
            return False
    except (OSError, ValueError):
        log.exception("Profil cabinet illisible — ignoré")
        return False

    try:
        nom = profil.get("cabinet_name")
        if isinstance(nom, str) and nom.strip() and not settings.cabinet_name:
            settings.set_cabinet_name(nom.strip())

        dossier = profil.get("update_folder")
        if isinstance(dossier, str) and dossier.strip() \
                and not settings.update_folder():
            settings.set_update_folder(dossier.strip())

        logo = _logo_a_copier(profil, profil_dir)
        if logo is not None and not settings.logo_path:
            user_dir.mkdir(parents=True, exist_ok=True)
            dest = user_dir / f"logo{logo.suffix.lower()}"
            shutil.copy2(logo, dest)
            settings.set_logo_path(str(dest))

        brut = profil.get("bareme")
        if brut is not None and not bareme_existe():
            # Validation/canonisation par le barème lui-même (tolérant : un
            # profil invalide retombe sur les groupes par défaut).
            ecrire_bareme(groupes_vers_brut(seuils_depuis_brut(brut)))

        user_dir.mkdir(parents=True, exist_ok=True)
        marqueur.write_text("1", encoding="utf-8")
    except Exception:
        log.exception("Application du profil cabinet partielle")
        return False
    log.info("Profil cabinet appliqué (premier lancement)")
    return True


def _logo_a_copier(profil: dict[str, Any], profil_dir: Path) -> Optional[Path]:
    nom = profil.get("logo")
    if not isinstance(nom, str) or not nom:
        return None
    # Nom de fichier simple uniquement : pas de sous-chemin ni de « .. ».
    if Path(nom).name != nom or Path(nom).suffix.lower() not in _LOGO_SUFFIXES:
        return None
    p = profil_dir / nom
    return p if p.is_file() else None
