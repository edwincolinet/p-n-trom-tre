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

Fichiers, tous en 0600 sous `~/.penetrometre` (dossier en 0700) :
  license.key  la clé signée du titulaire
  trial.json   date de début de la période d'essai
  state.json   repère interne : `last_seen` (date la plus avancée jamais
               observée) et `trial_started` (doublon de trial.json)

Portée de la protection — à connaître avant de s'y fier
-------------------------------------------------------
La vérification est **locale et hors-ligne** : la signature Ed25519
garantit qu'une clé n'est pas forgeable, mais rien n'empêche un
utilisateur déterminé de modifier le binaire ou d'effacer les fichiers
d'état. Ce module vise à rendre le contournement **délibéré** plutôt
qu'accidentel :

- **Recul d'horloge** : toutes les décisions de date passent par
  `today_effectif()`, plancherée par `last_seen`. Reculer la date
  système ne ressuscite ni une licence expirée ni un essai consommé. Et
  une licence n'est jamais valide avant sa date d'émission, qui est dans
  le payload signé (donc non modifiable).
- **Essai rejoué** : la date de début est écrite en double
  (`trial.json` + `state.json`) et on retient la plus ancienne ; le
  bouton « Essai gratuit » disparaît dès qu'un essai a été consommé
  (`essai_deja_consomme`).
- **Partage de clé** : c'est `gen_license.py` qui tranche, en liant la
  licence à une machine (`--machine-id`, désormais requis sauf
  `--any-machine` explicite).
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

_CONFIG_DIR   = Path.home() / ".penetrometre"
_LICENSE_PATH = _CONFIG_DIR / "license.key"
_TRIAL_PATH   = _CONFIG_DIR / "trial.json"
_STATE_PATH   = _CONFIG_DIR / "state.json"
_TRIAL_DAYS   = 30

# Garde anti-recul d'horloge : on mémorise la date la plus avancée jamais
# observée (`state.json`) et on l'utilise comme plancher. Reculer l'horloge
# système ne ressuscite donc pas une licence expirée ni un essai consommé.
#
# Plafond d'avance : si l'horloge saute très loin devant (pile CMOS morte →
# 2035), on ne grave PAS ce bond dans le repère, sinon la licence serait
# définitivement condamnée après remise à l'heure. On tolère l'avance pour
# le calcul du jour, on refuse seulement de la mémoriser.
_AVANCE_MAX_JOURS = 90

# Le repère n'est lu/écrit qu'une fois par processus (évite une écriture
# disque à chaque appel de `verify_license`).
_state_cache: "Optional[dict]" = None
_last_seen_ecrit = False

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


def masquer_email(email: str) -> str:
    """Réduit un email à une forme journalisable : `ed***@exemple.fr`.

    Le journal applicatif est explicitement destiné à être **envoyé au
    support** (« envoie-moi le contenu de penetrometre.log »). Y écrire
    l'email complet du titulaire en clair transforme ce geste d'entraide
    en transfert de donnée personnelle. Deux caractères + le domaine
    suffisent à identifier la licence côté support.
    """
    if not email or "@" not in email:
        return "—"
    local, _, domaine = email.partition("@")
    return f"{local[:2]}***@{domaine}"


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
# Écriture privée + repère de date monotone
# ---------------------------------------------------------------------------

def _secure_dir() -> Path:
    """Crée `~/.penetrometre` en 0700 et durcit un dossier préexistant.

    Ces fichiers (clé de licence, essai, repère de date) n'ont aucune
    raison d'être lisibles par les autres comptes du poste — le cadrage
    multi-poste de l'EULA suppose des installations partagées.
    """
    try:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        _CONFIG_DIR.chmod(0o700)
    except OSError:
        # Windows (chmod partiel) ou FS exotique : on n'échoue jamais là-dessus.
        log.debug("Durcissement du dossier de config impossible", exc_info=True)
    return _CONFIG_DIR


#: Fichiers du dossier de config qui doivent rester privés (0600).
#: Les autres (`bareme.json`, `recent.json`, le log…) sont couverts par le
#: 0700 du dossier : sans droit de traversée, leur mode propre importe peu.
_FICHIERS_PRIVES = ("license.key", "trial.json", "state.json")


def durcir_config_existante() -> None:
    """Re-applique 0700 sur `~/.penetrometre` et 0600 sur ses fichiers privés.

    Le durcissement posé à l'écriture (`_write_private`) ne protège que
    les fichiers **réécrits** par cette version. Une installation
    antérieure garde son dossier en 0755 et sa `license.key` en 0644 —
    lisibles par tous les comptes du poste — et resterait ainsi
    indéfiniment, puisqu'on ne réécrit une licence qu'à la réactivation.

    Appelée à chaque démarrage (`penetrometre.main`), donc le parc
    installé se corrige tout seul à la première ouverture. Best-effort et
    silencieuse : un `chmod` impossible (Windows, FAT32, montage réseau)
    ne doit jamais empêcher l'app de démarrer. On ne touche que ce qui est
    trop permissif, pour ne rien faire dans le cas courant.
    """
    try:
        if not _CONFIG_DIR.is_dir():
            return                      # rien à durcir : premier lancement
        if _CONFIG_DIR.stat().st_mode & 0o077:
            _CONFIG_DIR.chmod(0o700)
            log.info("Permissions du dossier de configuration resserrées "
                     "(0700).")
        for nom in _FICHIERS_PRIVES:
            f = _CONFIG_DIR / nom
            if f.is_file() and f.stat().st_mode & 0o177:
                f.chmod(0o600)
                log.info("Permissions de %s resserrées (0600).", nom)
    except OSError:
        log.debug("Durcissement des permissions impossible", exc_info=True)


def _write_private(path: Path, contenu: str) -> None:
    """Écrit `contenu` dans `path` en 0600, de façon atomique.

    Le `chmod` est posé sur le fichier TEMPORAIRE avant le `replace` :
    poser les droits après publication laisserait une fenêtre pendant
    laquelle la clé de licence est lisible par tous.
    """
    _secure_dir()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(contenu, encoding="utf-8")
    try:
        tmp.chmod(0o600)
    except OSError:
        log.debug("chmod 0600 impossible sur %s", tmp, exc_info=True)
    tmp.replace(path)


def _read_state() -> dict:
    global _state_cache
    if _state_cache is None:
        try:
            _state_cache = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
            if not isinstance(_state_cache, dict):
                _state_cache = {}
        except Exception:
            _state_cache = {}
    return _state_cache


def _write_state(**champs: str) -> None:
    state = dict(_read_state())
    state.update(champs)
    globals()["_state_cache"] = state
    try:
        _write_private(_STATE_PATH,
                       json.dumps(state, ensure_ascii=False))
    except Exception:
        log.debug("Écriture state.json échouée", exc_info=True)


def _parse_iso(v: object) -> Optional[date]:
    if not isinstance(v, str) or not v:
        return None
    try:
        return datetime.strptime(v, "%Y-%m-%d").date()
    except ValueError:
        return None


def today_effectif() -> date:
    """Date du jour **plancherée** par la date la plus avancée déjà vue.

    C'est la date utilisée par toutes les décisions de validité (licence
    et essai). Voir `_AVANCE_MAX_JOURS` pour le traitement d'une horloge
    partie loin devant.
    """
    global _last_seen_ecrit
    today = date.today()
    last = _parse_iso(_read_state().get("last_seen"))

    if last is None:
        if not _last_seen_ecrit:
            _last_seen_ecrit = True
            _write_state(last_seen=today.isoformat())
        return today

    if today < last:
        log.warning("Horloge système en retard sur le repère (%s < %s) — "
                    "la date du repère fait foi.", today, last)
        return last

    # Avance plausible → on fait progresser le repère (une fois par process).
    if not _last_seen_ecrit and (today - last).days <= _AVANCE_MAX_JOURS:
        _last_seen_ecrit = True
        _write_state(last_seen=today.isoformat())
    return today


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

def verify_license(key_str: str, *,
                   today: Optional[date] = None) -> Optional[LicenseData]:
    """Vérifie la signature Ed25519 et renvoie LicenseData ou None.

    `today` : date de référence des contrôles temporels. Par défaut
    `today_effectif()` — c'est-à-dire la date système **plancherée** par
    le repère monotone, pour qu'un recul d'horloge ne ressuscite pas une
    licence expirée. Le paramètre existe pour les tests.
    """
    ref = today if today is not None else today_effectif()
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

        issued = datetime.strptime(data["i"], "%Y-%m-%d").date()
        # Une licence ne peut pas être utilisée AVANT sa date d'émission :
        # c'est le contrôle qui coûte le moins cher et que le porteur ne
        # peut pas contourner en reculant l'horloge (la date d'émission
        # est dans le payload signé).
        if ref < issued:
            log.info("Licence non encore valide (émise le %s, référence %s)",
                     issued, ref)
            return None

        expires: Optional[date] = None
        if data.get("x"):
            exp_date = datetime.strptime(data["x"], "%Y-%m-%d").date()
            if exp_date < ref:
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
    # 0600 : la clé identifie nommément le titulaire (nom + email) et vaut
    # droit d'usage — elle n'a rien à faire en lecture pour les autres
    # comptes du poste.
    _write_private(_LICENSE_PATH, key_str.strip())
    return True


# ---------------------------------------------------------------------------
# Mode essai (trial 30 jours)
# ---------------------------------------------------------------------------

def _debut_essai() -> Optional[date]:
    """Date de début d'essai la PLUS ANCIENNE connue du poste.

    L'information est écrite en **deux endroits** (`trial.json` et le
    champ `trial_started` de `state.json`) et on retient la plus
    ancienne. Supprimer `trial.json` — le geste évident pour se
    réoffrir 30 jours — ne suffit donc plus.

    Rien de tout cela n'est inviolable : la vérification est locale, un
    utilisateur déterminé effacera les deux fichiers. L'objectif est de
    rendre le contournement délibéré plutôt qu'accidentel.
    """
    candidats = []
    try:
        if _TRIAL_PATH.exists():
            data = json.loads(_TRIAL_PATH.read_text(encoding="utf-8"))
            d = _parse_iso(data.get("started"))
            if d is not None:
                candidats.append(d)
    except Exception:
        log.debug("Lecture trial.json échouée", exc_info=True)
    d = _parse_iso(_read_state().get("trial_started"))
    if d is not None:
        candidats.append(d)
    return min(candidats) if candidats else None


def essai_deja_consomme() -> bool:
    """Vrai si un essai a déjà été démarré sur ce poste, **même expiré**.

    À utiliser pour décider d'afficher ou non le bouton « Essai gratuit »
    : `get_trial_info()` renvoie `None` aussi bien quand aucun essai n'a
    commencé que quand il est terminé, et confondre les deux offrait un
    essai neuf à chaque expiration.
    """
    return _debut_essai() is not None


def get_trial_info() -> Optional[TrialInfo]:
    """Renvoie TrialInfo si un essai est actif et non expiré, None sinon."""
    started = _debut_essai()
    if started is None:
        return None
    # `today_effectif` et non `date.today` : reculer l'horloge ne rallonge
    # pas l'essai.
    elapsed = (today_effectif() - started).days
    remaining = _TRIAL_DAYS - elapsed
    if remaining <= 0:
        log.info("Mode essai expiré (démarré le %s)", started)
        return None
    return TrialInfo(started=started, days_remaining=remaining)


def start_trial() -> TrialInfo:
    """Démarre le mode essai. Idempotent : ne réinitialise pas si déjà en cours."""
    existing = get_trial_info()
    if existing is not None:
        return existing
    # Un essai déjà consommé ne se relance pas : `_debut_essai` trouve
    # encore la date d'origine même si `get_trial_info` a renvoyé None
    # pour cause d'expiration.
    deja = _debut_essai()
    if deja is not None:
        log.info("Essai déjà consommé (démarré le %s) — pas de relance", deja)
        return TrialInfo(started=deja, days_remaining=0)

    today = today_effectif()
    _write_private(_TRIAL_PATH,
                   json.dumps({"started": today.isoformat()},
                              ensure_ascii=False))
    _write_state(trial_started=today.isoformat())
    log.info("Mode essai démarré le %s (%d jours)", today, _TRIAL_DAYS)
    return TrialInfo(started=today, days_remaining=_TRIAL_DAYS)
