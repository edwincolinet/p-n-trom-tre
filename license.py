"""
Vérification de licence offline — Ed25519.

La clé privée n'est JAMAIS ici. Seule la clé publique est embarquée.
Format de clé : base64url(signature).base64url(payload_json)
"""
from __future__ import annotations

import base64
import json
import logging
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger("penetrometre")

_LICENSE_PATH = Path.home() / ".penetrometre" / "license.key"

# Clé publique Ed25519 (32 octets, base64 standard).
# Générée une fois avec gen_license.py keygen — ne jamais changer
# après le premier déploiement (invaliderait toutes les licences émises).
_PUBLIC_KEY_B64 = "+89DH3Ul63dMrUadDc40BHUfYWvJtySqcHPSd6MswQA="


@dataclass
class LicenseData:
    name: str
    email: str
    issued: date
    expires: Optional[date] = None  # None = pas d'expiration


def is_bundled() -> bool:
    """True si l'app tourne depuis un bundle PyInstaller (production)."""
    return getattr(sys, "frozen", False)


def _b64url_decode(s: str) -> bytes:
    pad = (4 - len(s) % 4) % 4
    return base64.urlsafe_b64decode(s + "=" * pad)


def verify_license(key_str: str) -> Optional[LicenseData]:
    """Vérifie la signature Ed25519 et renvoie LicenseData ou None."""
    if not _PUBLIC_KEY_B64:
        log.warning("Clé publique non configurée dans license.py")
        return None
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        key_str = key_str.strip()
        if "." not in key_str:
            return None

        sig_b64, payload_b64 = key_str.split(".", 1)
        sig = _b64url_decode(sig_b64)
        payload_bytes = _b64url_decode(payload_b64)

        pub_bytes = base64.b64decode(_PUBLIC_KEY_B64)
        pub_key = Ed25519PublicKey.from_public_bytes(pub_bytes)
        try:
            pub_key.verify(sig, payload_bytes)
        except InvalidSignature:
            return None

        data: dict = json.loads(payload_bytes.decode("utf-8"))

        expires: Optional[date] = None
        if data.get("x"):
            exp_date = datetime.strptime(data["x"], "%Y-%m-%d").date()
            if exp_date < date.today():
                log.info("Licence expirée le %s", exp_date)
                return None
            expires = exp_date

        issued = datetime.strptime(data["i"], "%Y-%m-%d").date()
        return LicenseData(
            name=data["n"],
            email=data.get("e", ""),
            issued=issued,
            expires=expires,
        )
    except Exception:
        log.debug("Vérification de licence échouée", exc_info=True)
        return None


def load_license() -> Optional[LicenseData]:
    """Charge et vérifie la licence depuis ~/.penetrometre/license.key."""
    try:
        if not _LICENSE_PATH.exists():
            return None
        key_str = _LICENSE_PATH.read_text(encoding="utf-8").strip()
        return verify_license(key_str)
    except Exception:
        log.debug("Chargement licence échoué", exc_info=True)
        return None


def save_license(key_str: str) -> bool:
    """Sauvegarde la clé si valide. Retourne True si valide."""
    ld = verify_license(key_str)
    if ld is None:
        return False
    _LICENSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _LICENSE_PATH.with_suffix(".tmp")
    tmp.write_text(key_str.strip(), encoding="utf-8")
    tmp.replace(_LICENSE_PATH)
    return True
