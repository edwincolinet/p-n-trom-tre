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
from typing import Optional, Tuple

log = logging.getLogger("penetrometre")

_GITHUB_OWNER = "edwincolinet"
_GITHUB_REPO  = "p-n-trom-tre"
_API_URL      = (f"https://api.github.com/repos/"
                 f"{_GITHUB_OWNER}/{_GITHUB_REPO}/releases/latest")
_RELEASES_URL = (f"https://github.com/"
                 f"{_GITHUB_OWNER}/{_GITHUB_REPO}/releases/latest")


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
            data = json.loads(resp.read().decode())
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

    html_url = data.get("html_url", _RELEASES_URL)
    return tag, html_url
