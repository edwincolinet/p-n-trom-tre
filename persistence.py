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
import re
import shutil
import tempfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Union

from bareme import get_seuils, normaliser_port, seuils_depuis_brut
from model import (
    Arbre,
    Brin,
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
#   3 — introduction des brins (cépées) : la géométrie et les mesures
#       (rayon, diamètre, écorce, sondages, dégradations, contreforts) qui
#       vivaient au niveau `arbre` passent dans `arbre.brins[i]`. Un fichier
#       v≤2 est migré en un arbre à brin unique (cf. `chantier_from_dict`).
FORMAT_VERSION = 3


def chantier_to_dict(chantier: Chantier) -> Dict[str, Any]:
    """Sérialise un `Chantier` en dict prêt à `json.dump`.

    Écrit `format_version: FORMAT_VERSION`. La symétrie avec
    `chantier_from_dict` (qui tolère son absence) garantit qu'un round-
    trip save → load reproduit fidèlement la mission.
    """
    # Barème : on écrit les seuils EN VIGUEUR au moment de l'enregistrement,
    # pas ceux éventuellement chargés depuis le fichier. Le fichier doit
    # décrire comment ses classes ont été obtenues ; recopier une valeur
    # ancienne mentirait dès qu'on ré-enregistre après un changement de
    # réglage. Cf. `model.Chantier.bareme_seuils`.
    seuils = get_seuils()
    return {"format_version": FORMAT_VERSION,
            "nom": chantier.nom, "adresse": chantier.adresse,
            "client": chantier.client,
            "operateur": chantier.operateur,
            "date_releve": chantier.date_releve,
            "bareme_seuils": {k: [v[0], v[1]] for k, v in seuils.items()},
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


# --- Sauvegardes glissantes (anti-écrasement / anti-corruption) --------
# L'autosave (`save_recovery`) protège du CRASH ; ces backups protègent de
# l'ÉCRASEMENT volontaire ou d'un fichier devenu illisible — une mission =
# une journée entière de relevés. À chaque `action_save`, une copie
# horodatée est déposée et les anciennes purgées (on garde les N dernières
# de CETTE mission). Best-effort : un échec ici n'interrompt jamais
# l'enregistrement réel.
BACKUP_KEEP_DEFAULT = 12
_BACKUP_STAMP_RE = r"\d{8}-\d{6}"


def _backup_name(stem: str, suffix: str, when: datetime) -> str:
    return f"{stem}_{when.strftime('%Y%m%d-%H%M%S')}{suffix}"


def write_backup(source: Union[str, Path], backup_dir: Union[str, Path],
                 *, keep: int = BACKUP_KEEP_DEFAULT,
                 when: Optional[datetime] = None) -> Optional[Path]:
    """Dépose une copie horodatée de `source` dans `backup_dir`, puis purge
    pour ne conserver que les `keep` plus récentes **de cette mission**
    (mêmes `stem`+`suffix`). Renvoie le chemin de la copie, ou `None` en
    cas d'échec (loggé, jamais propagé — la sauvegarde réelle prime)."""
    try:
        src = Path(source)
        if not src.exists():
            return None
        bdir = Path(backup_dir)
        bdir.mkdir(parents=True, exist_ok=True)
        dest = bdir / _backup_name(src.stem, src.suffix,
                                   when or datetime.now())
        shutil.copy2(src, dest)
        _prune_backups(bdir, src.stem, src.suffix, keep)
        return dest
    except Exception:
        _log.exception("Échec de la sauvegarde glissante (backup)")
        return None


def list_backups(backup_dir: Union[str, Path], stem: str,
                 suffix: str) -> list[Path]:
    """Backups de la mission `stem`+`suffix`, du PLUS RÉCENT au plus ancien
    (le nom horodaté est trié lexicographiquement = chronologiquement)."""
    bdir = Path(backup_dir)
    if not bdir.is_dir():
        return []
    pat = re.compile(rf"^{re.escape(stem)}_{_BACKUP_STAMP_RE}"
                     rf"{re.escape(suffix)}$")
    matches = [p for p in bdir.iterdir() if pat.match(p.name)]
    return sorted(matches, key=lambda p: p.name, reverse=True)


def _prune_backups(backup_dir: Path, stem: str, suffix: str,
                   keep: int) -> None:
    for old in list_backups(backup_dir, stem, suffix)[max(keep, 0):]:
        try:
            old.unlink()
        except OSError:
            _log.warning("Impossible de purger le backup %s", old)


def save_recovery(chantier: Chantier, original_file: Union[str, None],
                  path: Union[str, Path]) -> None:
    """Écrit une sauvegarde de récupération (autosave) atomique.

    Enveloppe le `chantier` sérialisé dans un dict portant des
    métadonnées de récupération : horodatage et chemin du fichier
    d'origine (ou `None` si la mission n'a jamais été enregistrée). Sert
    à proposer une reprise après un crash (cf. `load_recovery`).

    Écriture atomique (`.tmp` + `os.replace`) comme `save_chantier` : un
    crash pendant l'écriture ne corrompt pas un autosave précédent.
    """
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "_recovery": True,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "original_file": str(original_file) if original_file else None,
        "chantier": chantier_to_dict(chantier),
    }
    fd, tmp = tempfile.mkstemp(dir=dest.parent, suffix=".tmp",
                               prefix=dest.stem + "_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        os.replace(tmp, dest)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_recovery(
    path: Union[str, Path]
) -> "tuple[Chantier, Union[str, None], str]":
    """Lit une sauvegarde de récupération.

    Renvoie `(chantier, original_file, saved_at)`. `original_file` peut
    être `None` (mission jamais enregistrée). Lève si le fichier est
    illisible ou n'a pas la structure attendue — au caller de gérer
    (journaliser + ignorer l'autosave corrompu).
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    chantier = chantier_from_dict(data["chantier"])
    original = data.get("original_file")
    saved_at = data.get("saved_at", "")
    return chantier, original, saved_at


def clear_recovery(path: Union[str, Path]) -> None:
    """Supprime la sauvegarde de récupération si elle existe. Silencieux
    (best-effort) : un échec de suppression ne doit jamais bloquer l'app."""
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass
    except OSError:
        _log.exception("Échec suppression autosave %s", path)


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
    # Migration des anciens niveaux d'urgence (renommage 2026-06).
    # Deux schémas antérieurs cohabitent dans les fichiers du terrain :
    # le libellé « à délai » (« Court terme (< 1 an) ») ET son ancêtre nu
    # (« Court terme »), tous deux rabattus sur les niveaux actuels de
    # `model.URGENCE_NIVEAUX` — sinon la valeur reste orpheline et le badge
    # d'urgence (fiche PDF) comme la cellule de synthèse XLSX s'affichent en
    # gris neutre au lieu de la couleur du délai.
    urgence_legacy = {
        "Court terme (< 1 an)":  "< 1 an",
        "Moyen terme (1-3 ans)": "< 2 ans",
        "Court terme":           "< 1 an",
        "Moyen terme":           "< 2 ans",
        "Surveillance":          "",
        "Sans objet":            "",
    }
    # Champs connus de chaque dataclass : permet d'ignorer
    # silencieusement un champ inconnu dans un JSON futur (ascendance
    # garantie même si on ajoute un champ côté code et qu'on revient
    # à une ancienne version de l'app, ou inversement). Sans ce
    # filtre, `Arbre(**a)` lèverait TypeError sur clé inattendue.
    arbre_fields = set(Arbre.__dataclass_fields__)
    brin_fields = set(Brin.__dataclass_fields__)
    sondage_fields = set(Sondage.__dataclass_fields__)
    deg_fields = set(DegradationExterne.__dataclass_fields__)
    cf_fields = set(Contrefort.__dataclass_fields__)

    def _brin_from_dict(bd: Dict[str, Any]) -> Brin:
        """Reconstruit un `Brin` (géométrie + mesures) à partir d'un dict.

        Sert pour les **deux** axes de compat :
        - format v3+ : `bd` est un dict de `arbre["brins"][i]` ;
        - format v≤2 : `bd` est le dict `arbre` lui-même, qui porte encore
          la géométrie et les mesures à plat (migration vers brin unique).
        Dans les deux cas, seules les clés connues de `Brin` sont retenues
        (compat descendante : un champ futur est ignoré silencieusement).
        """
        sondages = []
        for s in bd.get("sondages", []):
            s = {k: v for k, v in s.items() if k in sondage_fields}
            # Migration libellé compartimentation : "-" → "non renseignée"
            if s.get("compartimentation") == "-":
                s["compartimentation"] = "non renseignée"
            sondages.append(Sondage(**s))
        degs = [DegradationExterne(**{k: v for k, v in dg.items()
                                      if k in deg_fields})
                for dg in bd.get("degradations_externes", [])]
        # Contreforts : ajout v3.3 — anciens fichiers → liste vide
        contreforts = [Contrefort(**{k: v for k, v in c.items()
                                     if k in cf_fields})
                       for c in bd.get("contreforts", [])]
        geom = {k: v for k, v in bd.items()
                if k in brin_fields
                and k not in ("sondages", "degradations_externes",
                              "contreforts")}
        brin = Brin(**geom)
        brin.sondages = sondages
        brin.degradations_externes = degs
        brin.contreforts = contreforts
        return brin

    arbres = []
    for a in d.get("arbres", []):
        # Migration du port si ancien format. On copie le dict pour
        # appliquer la migration sans toucher à l'entrée du caller
        # (lecture non destructive).
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
        # Migration urgence (anciens libellés → nouveaux)
        if a_norm.get("urgence") in urgence_legacy:
            a_norm["urgence"] = urgence_legacy[a_norm["urgence"]]
        # Identité du genet : on exclut `brins` (reconstruit en objets
        # ci-dessous) et les anciens champs de géométrie/mesures (qui ne
        # sont plus des champs d'`Arbre` et seraient filtrés de toute façon).
        arb = Arbre(**{k: v for k, v in a_norm.items()
                       if k in arbre_fields and k != "brins"})
        if "brins" in a:
            # Format v3+ : brins explicites. Au moins un brin garanti.
            arb.brins = [_brin_from_dict(bd)
                         for bd in a.get("brins", [])] or [Brin()]
        else:
            # Format v≤2 : géométrie et mesures à plat sur l'arbre →
            # migration en un brin unique centré.
            arb.brins = [_brin_from_dict(a_norm)]
        arbres.append(arb)
    c = Chantier(nom=d.get("nom", ""), adresse=d.get("adresse", ""),
                  client=d.get("client", ""),
                  operateur=d.get("operateur", ""),
                  date_releve=d.get("date_releve", ""))
    # Barème d'origine : **relu mais pas appliqué**. Ouvrir une mission ne
    # doit pas reconfigurer le poste en douce ; en revanche l'app peut
    # signaler l'écart (cf. `App._avertir_bareme_different`) et les
    # exports peuvent citer le barème réellement utilisé.
    # Absent (missions antérieures) ⟹ dict vide = « inconnu ».
    if "bareme_seuils" in d:
        c.bareme_seuils = seuils_depuis_brut(d["bareme_seuils"])
    c.arbres = arbres
    return c
