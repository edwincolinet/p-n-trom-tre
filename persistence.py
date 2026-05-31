"""
Persistance JSON des missions du Pénétromètre.

Module dédié à la sérialisation des `Chantier`. Vit hors de `model.py`
pour que le modèle métier reste centré sur ses dataclasses et sa
logique d'extrapolation : la migration de format de fichier (rare,
mais elle grossit à chaque évolution) a son propre toit.

Contenu :
- `FORMAT_VERSION`     — version du format JSON écrit.
- `chantier_to_dict`   — sérialise un `Chantier` en dict prêt à
                          `json.dump`.
- `chantier_from_dict` — reconstruit un `Chantier` à partir d'un dict.
                          Tolère les anciens formats (migration des
                          libellés de port) et un format futur (filtre
                          des clés inconnues par
                          `__dataclass_fields__` à chaque niveau).
- `save_chantier`      — écrit le fichier JSON indenté UTF-8.
- `load_chantier`      — lit un fichier JSON et délègue à
                          `chantier_from_dict`.

Compat ascendante / descendante : voir CLAUDE.md →
« Compatibilité ascendante ET descendante des fichiers ».
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Union

from bareme import normaliser_port
from model import (
    Arbre,
    Chantier,
    Contrefort,
    DegradationExterne,
    Sondage,
)

_log = logging.getLogger("penetrometre")


# Version du format JSON écrit par `chantier_to_dict`. Incrémenter
# (et ajouter une branche dans `chantier_from_dict`) quand une
# migration non triviale est nécessaire. La lecture tolère son absence
# (anciens fichiers pré-versionnés → traités comme v1).
#
# Historique :
#   1 — format initial (sondages + dégradations externes)
#   2 — ajout contreforts + port normalisé (v3.3)
FORMAT_VERSION = 2


def chantier_to_dict(chantier: Chantier) -> Dict[str, Any]:
    """Sérialise un `Chantier` en dict prêt à `json.dump`.

    Écrit `format_version: FORMAT_VERSION`. La symétrie avec
    `chantier_from_dict` (qui tolère son absence) garantit qu'un round-
    trip save → load reproduit fidèlement la mission.
    """
    return {"format_version": FORMAT_VERSION,
            "nom": chantier.nom, "adresse": chantier.adresse,
            "operateur": chantier.operateur,
            "date_releve": chantier.date_releve,
            "arbres": [asdict(a) for a in chantier.arbres]}


def save_chantier(chantier: Chantier, path: Union[str, Path]) -> None:
    """Sauvegarde la mission au format JSON indenté UTF-8.

    Le format est versionné via `format_version` (cf. `chantier_to_dict`).
    L'app garantit de pouvoir relire les anciens fichiers (cf.
    `chantier_from_dict` qui ignore les clés inconnues et migre les
    ports renommés).
    """
    dest = Path(path)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, suffix=".tmp",
                               prefix=dest.stem + "_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(chantier_to_dict(chantier), f,
                      indent=2, ensure_ascii=False)
        os.replace(tmp, dest)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_chantier(path: Union[str, Path]) -> Chantier:
    """Lit un fichier JSON de mission et reconstruit le `Chantier`
    correspondant. Délègue le filtrage / la migration à
    `chantier_from_dict` : robuste aux clés inconnues d'un format futur
    et aux anciens libellés de port.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return chantier_from_dict(data)


def chantier_from_dict(d: Dict[str, Any]) -> Chantier:
    """Reconstruit un `Chantier` à partir d'un dict JSON.

    Gère deux axes de compat :
    - **Ascendant** : migration des anciens libellés de port
      (v3.1 → v3.2) et fallback `"libre"` si le port est inconnu
      (faute de frappe dans un JSON édité à la main).
    - **Descendant** : filtre chaque dict d'entrée par
      `Class.__dataclass_fields__` avant `Class(**kwargs)` — les clés
      inconnues d'un format futur sont ignorées silencieusement, et un
      WARNING est journalisé pour signaler la situation.
    """
    # Compatibilité descendante : un fichier produit par une version
    # plus récente porte un format_version supérieur. Les clés
    # inconnues sont déjà filtrées par dataclass plus bas, mais on
    # journalise pour qu'un opérateur qui charge un fichier "trop
    # récent" puisse comprendre si quelque chose semble manquer.
    # L'absence de format_version (anciens fichiers pré-versionnés)
    # est traitée silencieusement comme v1.
    version = d.get("format_version", 1)
    if isinstance(version, int) and version > FORMAT_VERSION:
        _log.warning(
            "Fichier au format v%d — cette version de l'app gère "
            "jusqu'au v%d. Les champs récents seront ignorés.",
            version, FORMAT_VERSION)
    # Mapping de migration des anciens libellés de port (v3.1 → v3.2)
    port_legacy = {
        "Libre, semi-libre ou traumatique": "libre",
        "Architecturé ou traumatique": "architecturé",
    }
    # Champs connus de chaque dataclass : permet d'ignorer
    # silencieusement un champ inconnu dans un JSON futur (ascendance
    # garantie même si on ajoute un champ côté code et qu'on revient
    # à une ancienne version de l'app, ou inversement). Sans ce
    # filtre, `Arbre(**a)` lèverait TypeError sur clé inattendue.
    arbre_fields = set(Arbre.__dataclass_fields__)
    sondage_fields = set(Sondage.__dataclass_fields__)
    deg_fields = set(DegradationExterne.__dataclass_fields__)
    cf_fields = set(Contrefort.__dataclass_fields__)

    arbres = []
    for a in d.get("arbres", []):
        # Lecture non destructive : `get`, pas `pop`. Le filtre par
        # `__dataclass_fields__` plus bas exclut de toute façon ces
        # clés du dict passé à `Arbre(**...)`, et le caller conserve
        # son dict d'origine intact (pas d'effet de bord).
        sondages_raw = []
        for s in a.get("sondages", []):
            s = {k: v for k, v in s.items() if k in sondage_fields}
            # Migration libellé compartimentation : "-" → "non renseignée"
            if s.get("compartimentation") == "-":
                s["compartimentation"] = "non renseignée"
            sondages_raw.append(s)
        sondages = [Sondage(**s) for s in sondages_raw]
        degs = [DegradationExterne(**{k: v for k, v in dg.items()
                                       if k in deg_fields})
                for dg in a.get("degradations_externes", [])]
        # Contreforts : ajout v3.3 — anciens fichiers → liste vide
        contreforts = [Contrefort(**{k: v for k, v in c.items()
                                      if k in cf_fields})
                       for c in a.get("contreforts", [])]
        # Migration du port si ancien format. On copie le dict pour
        # appliquer la migration sans toucher à l'entrée du caller.
        a_norm = dict(a)
        if "port_arbre" in a_norm:
            raw_port = a_norm["port_arbre"]
            migrated = port_legacy.get(raw_port, raw_port)
            normalized = normaliser_port(migrated)
            if not normalized:
                # Port inconnu (faute de frappe dans un JSON édité
                # à la main, ancien libellé non couvert par la
                # migration). On retombe sur "libre" — c'est le
                # défaut le moins permissif (seuils plus tolérants
                # que strict, donc moins de faux Vert).
                _log.warning(
                    "Arbre n°%s : port_arbre inconnu %r — "
                    "remplacé par 'libre'.",
                    a_norm.get("numero_arbre", "?"), raw_port)
                normalized = "libre"
            a_norm["port_arbre"] = normalized
        arb = Arbre(**{k: v for k, v in a_norm.items()
                       if k in arbre_fields})
        arb.sondages = sondages
        arb.degradations_externes = degs
        arb.contreforts = contreforts
        arbres.append(arb)
    c = Chantier(nom=d.get("nom", ""), adresse=d.get("adresse", ""),
                  operateur=d.get("operateur", ""),
                  date_releve=d.get("date_releve", ""))
    c.arbres = arbres
    return c
