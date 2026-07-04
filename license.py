"""
Vérification de licence offline — Ed25519.

La clé privée n'est JAMAIS ici. Seule la clé publique est embarquée.
Format de clé : base64url(signature).base64url(payload_json)

Payload JSON :
  n  = nom du titulaire
  e  = email du titulaire
  i  = date d'émission (AAAA-MM-JJ)
  x  = date d'expiration (AAAA-MM-JJ) — absent = illimité
  m  = machine ID (12 hex chars, SHA-256 tronqué) — absent = toutes machines
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import platform
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger("penetrometre")

_LICENSE_PATH = Path.home() / ".penetrometre" / "license.key"
_TRIAL_PATH   = Path.home() / ".penetrometre" / "trial.json"
_TRIAL_DAYS   = 30

# Clé publique Ed25519 (32 octets, base64 standard).
# Générée une fois avec gen_license.py keygen — ne jamais changer
# après le premier déploiement (invaliderait toutes les licences émises).
_PUBLIC_KEY_B64 = "+89DH3Ul63dMrUadDc40BHUfYWvJtySqcHPSd6MswQA="


@dataclass
class LicenseData:
    name: str
    email: str
    issued: date
    expires: Optional[date] = None    # None = pas d'expiration
    machine_id: Optional[str] = None  # None = toutes machines autorisées


@dataclass
class TrialInfo:
    started: date
    days_remaining: int  # 0 = expiré (ne devrait pas être renvoyé par get_trial_info)


def is_bundled() -> bool:
    """True si l'app tourne depuis un binaire de production (PyInstaller
    OU Nuitka), False en développement (`python penetrometre.py`).

    PyInstaller pose `sys.frozen` ; Nuitka pose `__compiled__` dans les
    globals de chaque module compilé (dont celui-ci). Sans le second test,
    le binaire Nuitka sauterait la vérification de licence — or c'est
    précisément pour durcir cette protection qu'on propose un build Nuitka.
    """
    return getattr(sys, "frozen", False) or "__compiled__" in globals()


def _b64url_decode(s: str) -> bytes:
    pad = (4 - len(s) % 4) % 4
    return base64.urlsafe_b64decode(s + "=" * pad)


# ---------------------------------------------------------------------------
# Machine ID
# ---------------------------------------------------------------------------

def get_machine_id() -> str:
    """Renvoie un identifiant stable par machine (12 hex chars, SHA-256 tronqué).

    Sources :
    - Linux  : /etc/machine-id (systemd UUID persistant)
    - macOS  : IOPlatformUUID (ioreg)
    - Windows: HKLM\\SOFTWARE\\Microsoft\\Cryptography\\MachineGuid
    - Fallback : nom d'hôte (moins unique, utilisé si toutes les sources échouent)
    """
    raw = _raw_machine_id()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _raw_machine_id() -> str:
    try:
        if sys.platform == "linux":
            for p in (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id")):
                if p.exists():
                    v = p.read_text(encoding="utf-8").strip()
                    if v:
                        return v
        elif sys.platform == "darwin":
            result = subprocess.run(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                if "IOPlatformUUID" in line:
                    parts = line.split('"')
                    if len(parts) >= 4:
                        return parts[-2]
        elif sys.platform == "win32":
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
            )
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
            return str(value)
    except Exception:
        log.debug("Machine ID : source plateforme échouée, fallback hostname",
                  exc_info=True)
    return platform.node() or "unknown"


# ---------------------------------------------------------------------------
# Vérification de licence
# ---------------------------------------------------------------------------

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

        # Vérification machine (optionnelle : absent = toutes machines OK)
        machine_id: Optional[str] = data.get("m")
        if machine_id is not None:
            current = get_machine_id()
            if machine_id != current:
                log.info("Licence invalide : machine ID %s ≠ %s", machine_id, current)
                return None

        issued = datetime.strptime(data["i"], "%Y-%m-%d").date()
        return LicenseData(
            name=data["n"],
            email=data.get("e", ""),
            issued=issued,
            expires=expires,
            machine_id=machine_id,
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


# ---------------------------------------------------------------------------
# Mode essai (trial 30 jours)
# ---------------------------------------------------------------------------

def get_trial_info() -> Optional[TrialInfo]:
    """Renvoie TrialInfo si un essai est actif et non expiré, None sinon."""
    try:
        if not _TRIAL_PATH.exists():
            return None
        data: dict = json.loads(_TRIAL_PATH.read_text(encoding="utf-8"))
        started = datetime.strptime(data["started"], "%Y-%m-%d").date()
        elapsed = (date.today() - started).days
        remaining = _TRIAL_DAYS - elapsed
        if remaining <= 0:
            log.info("Mode essai expiré (démarré le %s)", started)
            return None
        return TrialInfo(started=started, days_remaining=remaining)
    except Exception:
        log.debug("Lecture trial.json échouée", exc_info=True)
        return None


def start_trial() -> TrialInfo:
    """Démarre le mode essai. Idempotent : ne réinitialise pas si déjà en cours."""
    existing = get_trial_info()
    if existing is not None:
        return existing
    today = date.today()
    _TRIAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"started": today.isoformat()}, ensure_ascii=False)
    tmp = _TRIAL_PATH.with_suffix(".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(_TRIAL_PATH)
    log.info("Mode essai démarré le %s (%d jours)", today, _TRIAL_DAYS)
    return TrialInfo(started=today, days_remaining=_TRIAL_DAYS)
