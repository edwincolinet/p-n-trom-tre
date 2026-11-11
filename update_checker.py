"""
Vérification des mises à jour via l'API GitHub Releases.

Module pur (stdlib uniquement, sans Tkinter ni PIL). Conçu pour être
appelé dans un thread daemon depuis `App._check_for_update_async` afin
de ne pas bloquer l'UI au démarrage.

Protocole :
  - Interroge https://api.github.com/repos/<owner>/<repo>/releases/latest
  - Compare la balise de la dernière release à `current_version`.
  - Renvoie `(tag, download_url)` si une version plus récente est
    disponible, `None` sinon.
  - Tout échec réseau ou de parsing → renvoie silencieusement `None`
    (pas d'exception propagée ; l'erreur est loggée).

Prérequis côté GitHub :
  - Le dépôt doit être **public** (ou la release accessible en anonyme)
    pour que l'API réponde sans authentification.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

log = logging.getLogger("penetrometre")

_GITHUB_OWNER = "edwincolinet"
_GITHUB_REPO  = "p-n-trom-tre"
_API_URL      = (f"https://api.github.com/repos/"
                 f"{_GITHUB_OWNER}/{_GITHUB_REPO}/releases/latest")
_RELEASES_URL = (f"https://github.com/"
                 f"{_GITHUB_OWNER}/{_GITHUB_REPO}/releases/latest")
# Toute URL ouverte dans le navigateur doit commencer par ce préfixe
# (schéma + hôte + dépôt figés) — cf. `url_de_release_sure`.
_PREFIXE_SUR = f"https://github.com/{_GITHUB_OWNER}/{_GITHUB_REPO}/"


def url_de_release_sure(url: object) -> str:
    """Filtre l'URL renvoyée par l'API avant de l'ouvrir dans un navigateur.

    `html_url` vient d'une réponse HTTP distante : on ne l'ouvre qu'après
    avoir vérifié qu'elle pointe bien vers le dépôt de releases, en HTTPS.
    Sans ce filtre, une réponse détournée (proxy d'entreprise mal
    configuré, DNS empoisonné, compromission côté service) suffirait à
    faire ouvrir une URL arbitraire — y compris un schéma non-HTTP que
    le navigateur ou le bureau interprète.

    Renvoie l'URL si elle est acceptable, sinon la page de releases
    officielle (repli sûr, jamais une chaîne vide).
    """
    if isinstance(url, str) and url.startswith(_PREFIXE_SUR):
        return url
    if url:
        log.warning("URL de release inattendue, ignorée : %r", url)
    return _RELEASES_URL


def _parse_version(tag: str) -> Optional[Tuple[int, ...]]:
    """'v3.7.1' ou '3.7.1' → (3, 7, 1). Renvoie None si non analysable."""
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:[.\-].+)?", tag.strip())
    if not m:
        return None
    return tuple(int(x) for x in m.groups())


def check_for_update(
        current_version: str,
        timeout: float = 3.0,
) -> Optional[Tuple[str, str]]:
    """Interroge GitHub Releases et compare avec `current_version`.

    Retourne `(tag_name, release_url)` si une version plus récente est
    disponible, `None` sinon (aucune release, version identique, ou
    toute erreur réseau / parsing).

    `timeout` : délai maximal en secondes (résolution + lecture)."""
    current = _parse_version(current_version)
    if current is None:
        return None

    try:
        req = urllib.request.Request(
            _API_URL,
            headers={"Accept": "application/vnd.github+json",
                     "User-Agent": f"Penetrometre/{current_version}"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read(65536).decode())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # Dépôt privé ou aucune release publiée — silencieux.
            log.debug("update_checker: aucune release trouvée (%s)", e.code)
        else:
            log.debug("update_checker: HTTP %s", e.code)
        return None
    except OSError:
        # Pas de réseau, timeout, DNS — silencieux.
        log.debug("update_checker: pas de réseau ou timeout")
        return None
    except Exception:
        log.exception("update_checker: erreur inattendue")
        return None

    tag = data.get("tag_name", "")
    latest = _parse_version(tag)
    if latest is None or latest <= current:
        return None

    return tag, url_de_release_sure(data.get("html_url"))


_RE_INSTALLEUR = re.compile(r"Penetrometre-(\d+\.\d+\.\d+)-Setup\.exe", re.IGNORECASE)


def check_for_update_folder(
        current_version: str,
        folder: str,
) -> Optional[Tuple[str, str]]:
    """Cherche un installeur plus récent dans un dossier partagé du cabinet.

    Alternative à `check_for_update` quand le dépôt GitHub est privé : les
    installeurs `Penetrometre-X.Y.Z-Setup.exe` sont déposés dans un dossier
    commun. Retourne `("vX.Y.Z", dossier)` pour la version la plus récente
    strictement supérieure à `current_version`, `None` sinon (dossier
    absent/inaccessible, aucun installeur, déjà à jour). Jamais d'exception."""
    current = _parse_version(current_version)
    if current is None or not folder:
        return None
    try:
        meilleure: Optional[Tuple[int, ...]] = None
        for f in Path(folder).iterdir():
            m = _RE_INSTALLEUR.fullmatch(f.name)
            if m is None:
                continue
            v = tuple(int(x) for x in m.group(1).split("."))
            if v > current and (meilleure is None or v > meilleure):
                meilleure = v
    except OSError:
        log.debug("update_checker: dossier de mises à jour inaccessible")
        return None
    if meilleure is None:
        return None
    return "v" + ".".join(str(x) for x in meilleure), str(folder)
