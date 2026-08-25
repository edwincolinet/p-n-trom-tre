"""
Résolution **confinée** des chemins de photos d'une mission.

Module pur (stdlib uniquement, aucune dépendance projet) : il sert à la
fois la galerie Tk (`photo_gallery`) et la fiche PDF (`fiche_pdf`), qui
doivent appliquer exactement la même règle.

Pourquoi ce module
------------------
Un `.json` de mission est une entrée **semi-fiable** : il circule entre
confrères par mail ou clé USB. Or `Arbre.photos` est une liste de
chemins libres que l'app ouvre (visionneuse système) et embarque dans le
PDF exporté. Sans garde-fou, un fichier fabriqué peut :

- **remonter l'arborescence** — `"../../../../etc/passwd"` — puisque le
  chemin relatif était résolu par une simple concaténation ;
- **désigner un fichier arbitraire du poste** par chemin absolu, qui se
  retrouve alors embarqué dans le PDF remis au client ;
- **déclencher une exécution** : `xdg-open` sur un `.desktop` ou un
  script lance le programme au lieu d'afficher une image.

Règles appliquées
-----------------
1. **Extension** : seules les extensions de `PHOTO_SUFFIXES` sont
   acceptées. C'est ce qui coupe le vecteur d'exécution — la
   visionneuse système ne reçoit jamais autre chose qu'une image
   déclarée (le contenu est vérifié en plus côté galerie, cf.
   `photo_gallery._view_photo`).
2. **Chemin relatif** : résolu depuis le dossier de la mission, et le
   résultat doit **rester sous ce dossier**. `..` est donc neutralisé.
   L'app n'a jamais écrit de relatif pointant ailleurs (les photos sont
   copiées dans `<mission>_photos/`) → aucune régression possible.
3. **Chemin absolu** : accepté, mais **signalé** (`hors_mission=True`).
   La toute première version de la galerie (juin 2026) stockait des
   chemins absolus pointant n'importe où sur le disque ; les refuser
   casserait ces missions-là. Le risque résiduel — un JSON hostile qui
   devine le chemin exact d'une image du poste pour l'embarquer dans un
   export — est borné par la règle 1 et rendu visible à l'opérateur.

Le motif de refus est renvoyé (et non simplement `None`) pour que
l'interface distingue « fichier déplacé » de « référence refusée » : un
refus silencieux ressemblerait à un bug.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple, Optional

# Extensions autorisées — doit rester aligné sur le filtre du sélecteur
# de fichiers (`photo_gallery._ACCEPTED`), qui importe cette constante.
PHOTO_SUFFIXES = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".webp",
})

# Motifs de refus (chaînes stables, testables, affichables telles quelles).
MOTIF_EXTENSION = "extension non autorisée"
MOTIF_HORS_MISSION = "hors du dossier de la mission"
MOTIF_SANS_MISSION = "mission non enregistrée"
MOTIF_INTROUVABLE = "fichier introuvable"


class PhotoResolue(NamedTuple):
    """Résultat de la résolution d'une référence photo.

    `path` est `None` dès que la référence est inutilisable ; `motif`
    dit alors pourquoi (chaîne vide si tout va bien). `hors_mission`
    signale un chemin absolu pointant en dehors du dossier de la
    mission : utilisable (compat historique) mais à afficher comme tel.
    """

    path: Optional[Path]
    motif: str = ""
    hors_mission: bool = False


def suffixe_autorise(stored: str) -> bool:
    """Vrai si la référence porte une extension d'image acceptée."""
    return Path(stored).suffix.lower() in PHOTO_SUFFIXES


def resolve_photo(stored: str,
                  mission_dir: Optional[Path]) -> PhotoResolue:
    """Résout une référence photo en chemin absolu **confiné**.

    `mission_dir` est le dossier du `.json` de mission (`None` si la
    mission n'a jamais été enregistrée — aucun relatif n'est alors
    résolvable). Voir l'en-tête du module pour les trois règles.
    """
    if not stored or not suffixe_autorise(stored):
        return PhotoResolue(None, MOTIF_EXTENSION)

    p = Path(stored)

    if p.is_absolute():
        # Compat historique : accepté, mais on signale si le fichier vit
        # hors du dossier de la mission (cf. règle 3).
        hors = True
        if mission_dir is not None:
            try:
                hors = not _est_sous(p, mission_dir)
            except OSError:
                hors = True
        if not p.exists():
            return PhotoResolue(None, MOTIF_INTROUVABLE, hors)
        return PhotoResolue(p, "", hors)

    if mission_dir is None:
        return PhotoResolue(None, MOTIF_SANS_MISSION)

    resolved = mission_dir / p
    # Confinement : `..` et liens symboliques sortants sont neutralisés
    # par la comparaison sur les chemins RÉSOLUS.
    try:
        if not _est_sous(resolved, mission_dir):
            return PhotoResolue(None, MOTIF_HORS_MISSION)
    except OSError:
        return PhotoResolue(None, MOTIF_HORS_MISSION)

    if not resolved.exists():
        return PhotoResolue(None, MOTIF_INTROUVABLE)
    return PhotoResolue(resolved, "")


def _est_sous(chemin: Path, racine: Path) -> bool:
    """Vrai si `chemin` résolu est contenu dans `racine` résolue.

    `strict=False` : on résout aussi les chemins qui n'existent pas
    encore (le `..` est normalisé de toute façon), pour que le refus
    d'un traversal ne dépende pas de l'existence du fichier visé.
    """
    c = chemin.resolve(strict=False)
    r = racine.resolve(strict=False)
    return c == r or r in c.parents
