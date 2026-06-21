"""
Gestion des modèles de mission (templates).

Un modèle mémorise les champs communs à un type de chantier récurrent
(essence, port, mèche, client, opérateur…) pour éviter de tout ressaisir
à chaque nouvelle mission similaire.

Les modèles vivent dans ~/.penetrometre/templates/<slug>.json.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger("penetrometre")

_TEMPLATES_DIR = Path.home() / ".penetrometre" / "templates"
_VERSION = 1


def _slug(name: str) -> str:
    """Nom de fichier sûr depuis un nom de modèle."""
    s = re.sub(r"[^\w\s-]", "", name.lower().strip())
    s = re.sub(r"[\s_-]+", "_", s)
    return (s[:40] or "modele")


def list_templates() -> list[dict[str, Any]]:
    """Retourne la liste des modèles triés par nom, du plus récent au plus
    ancien (ordre de modification). Chaque entrée : dict complet du modèle
    + clé '_path' = chemin du fichier."""
    _TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    result = []
    for p in sorted(_TEMPLATES_DIR.glob("*.json"),
                    key=lambda f: f.stat().st_mtime, reverse=True):
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            data["_path"] = str(p)
            result.append(data)
        except Exception:
            log.debug("template_store: fichier ignoré (%s)", p)
    return result


def save_template(name: str, data: dict[str, Any]) -> Path:
    """Sauvegarde un modèle. Renvoie le chemin du fichier créé."""
    _TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    slug = _slug(name)
    # Éviter les collisions de slug si le nom diffère
    candidate = _TEMPLATES_DIR / f"{slug}.json"
    if candidate.exists():
        try:
            with open(candidate, encoding="utf-8") as f:
                existing = json.load(f)
            if existing.get("nom_modele") != name:
                candidate = _TEMPLATES_DIR / f"{slug}_2.json"
        except Exception:
            pass
    payload = {"version": _VERSION, "nom_modele": name, **data}
    tmp = candidate.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    tmp.replace(candidate)
    return candidate


def delete_template(path: str) -> None:
    """Supprime un fichier modèle."""
    try:
        Path(path).unlink(missing_ok=True)
    except Exception:
        log.exception("template_store: échec suppression %s", path)


def template_from_chantier(chantier: Any) -> dict[str, Any]:
    """Extrait les champs pertinents d'un `Chantier` pour constituer un
    modèle. Les arbres (sondages, dégradations…) sont ignorés."""
    arbre_defaut: dict[str, Any] = {}
    if chantier.arbres:
        a = chantier.arbres[0]
        arbre_defaut = {
            "essence":             a.essence,
            "port_arbre":          a.port_arbre,
            "meche_cm":            a.meche_cm,
            "hauteur_sondage_cm":  a.hauteur_sondage_cm,
            "epaisseur_ecorce_cm": a.epaisseur_ecorce_cm,
            "hauteur_arbre_m":     a.hauteur_arbre_m,
        }
    return {
        "client":        chantier.client,
        "adresse":       chantier.adresse,
        "operateur":     chantier.operateur,
        "arbre_defaut":  arbre_defaut,
    }
