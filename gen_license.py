"""
Outil de génération de licences Pénétromètre — USAGE INTERNE UNIQUEMENT.

NE PAS inclure dans le bundle de distribution (PyInstaller l'ignore
car il n'est pas importé par penetrometre.py).

Commandes :
  python3 gen_license.py keygen
      → génère la paire de clés Ed25519 (à faire UNE SEULE FOIS).
        Sauvegarde la clé privée dans private.key (à conserver hors repo).
        Affiche la clé publique à coller dans license.py (_PUBLIC_KEY_B64).

  python3 gen_license.py issue "Nom du cabinet" "email@example.com" --machine-id a3b4c5d6e7f8
  python3 gen_license.py issue "Nom du cabinet" "email@example.com" --machine-id a3b4c5d6e7f8 --expires 2027-06-01
      → émet une clé de licence signée à envoyer au client.
        --machine-id est REQUIS : une clé non liée fonctionne sur un nombre
        illimité de postes. L'ID est affiché dans le dialogue d'activation
        de l'app cliente (et par `gen_license.py machine-id` en local).
        Pour émettre volontairement une clé transférable : --any-machine.

  python3 gen_license.py machine-id
      → affiche l'ID machine de la machine courante (pour tests locaux).

  python3 gen_license.py verify <clé>
      → vérifie une clé (utile pour le support).

Sécurité :
  - private.key ne doit JAMAIS être committé ni partagé.
  - En cas de compromission, émettre de nouvelles clés avec un nouveau
    keypair et livrer une mise à jour de l'app (nouvelle clé publique).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from datetime import date
from pathlib import Path

# Emplacement par défaut de la clé privée : HORS de l'arbre du projet.
#
# La clé était historiquement lue dans `./private.key`, à la racine du
# dépôt. Le `.gitignore` la protégeait du commit, mais pas d'un
# `git add -f`, d'une archive `zip -r` du dossier, d'une synchro cloud
# ni d'une sauvegarde de poste. Or c'est le seul secret dont la fuite
# est **irréversible** : la clé publique est embarquée dans tous les
# binaires distribués, donc changer de paire invaliderait toutes les
# licences déjà émises.
#
# Ordre de résolution : $SILVAVENIR_LICENSE_KEY, puis ~/.silvavenir-keys/,
# puis (compat) ./private.key s'il existe encore — avec avertissement.
_ENV_KEY = "SILVAVENIR_LICENSE_KEY"
_HOME_KEY_PATH = Path.home() / ".silvavenir-keys" / "private.key"
_LEGACY_KEY_PATH = Path("private.key")


def _default_key_path() -> Path:
    env = os.environ.get(_ENV_KEY)
    if env:
        return Path(env).expanduser()
    if _HOME_KEY_PATH.exists():
        return _HOME_KEY_PATH
    if _LEGACY_KEY_PATH.exists():
        return _LEGACY_KEY_PATH
    return _HOME_KEY_PATH


def _depot_git(chemin: Path) -> "Path | None":
    """Racine du dépôt git contenant `chemin`, ou None."""
    p = chemin.resolve(strict=False)
    for cand in (p, *p.parents):
        if (cand / ".git").exists():
            return cand
    return None


def _avertir_si_dans_depot(key_path: Path) -> None:
    """Signale (sans bloquer) une clé privée stockée dans un dépôt git."""
    racine = _depot_git(key_path)
    if racine is None:
        return
    print("!" * 62, file=sys.stderr)
    print(f"ATTENTION : la clé privée est dans un dépôt git ({racine}).",
          file=sys.stderr)
    print("Un `git add -f`, une archive du dossier ou une synchro cloud",
          file=sys.stderr)
    print("la ferait fuiter — et une fuite est IRRÉVERSIBLE (la clé",
          file=sys.stderr)
    print("publique est figée dans tous les binaires déjà distribués).",
          file=sys.stderr)
    print("", file=sys.stderr)
    print("  Déplacez-la :", file=sys.stderr)
    print(f"    mkdir -p {_HOME_KEY_PATH.parent} && chmod 700 "
          f"{_HOME_KEY_PATH.parent}", file=sys.stderr)
    print(f"    mv {key_path} {_HOME_KEY_PATH} && chmod 600 {_HOME_KEY_PATH}",
          file=sys.stderr)
    print("!" * 62, file=sys.stderr)
    print("", file=sys.stderr)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def cmd_keygen(args: argparse.Namespace) -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
        PublicFormat,
    )

    key_path = Path(args.out).expanduser()
    if key_path.exists():
        print(f"ERREUR : {key_path} existe déjà. Supprimez-le manuellement si vous")
        print("voulez regénérer (attention : invalide toutes les licences émises).")
        sys.exit(1)

    # Refus par défaut d'écrire une clé neuve dans un dépôt git : autant
    # ne pas créer le problème qu'on cherche à corriger.
    racine = _depot_git(key_path)
    if racine is not None and not args.force:
        print(f"ERREUR : {key_path.resolve()} est dans le dépôt git {racine}.")
        print()
        print("Générez la clé hors du dépôt (emplacement par défaut) :")
        print("    python3 gen_license.py keygen")
        print(f"→ écrit dans {_HOME_KEY_PATH}")
        print()
        print("Passez --force pour écrire quand même dans le dépôt.")
        sys.exit(1)

    priv = Ed25519PrivateKey.generate()
    priv_bytes = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub_bytes = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    key_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        key_path.parent.chmod(0o700)
    except OSError:
        pass
    # 0600 posé AVANT l'écriture du secret : créer le fichier en 0644 puis
    # le restreindre laisse une fenêtre de lecture pour les autres comptes.
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(priv_bytes)

    pub_b64 = base64.b64encode(pub_bytes).decode()
    print("=" * 60)
    print("CLÉ PRIVÉE sauvegardée dans :", key_path.resolve())
    print("→ Sauvegardez-la hors ligne (gestionnaire de mots de passe).")
    print("→ Sa perte = plus aucune licence émissible ;")
    print("  sa fuite  = licences forgeables par n'importe qui.")
    print("=" * 60)
    print()
    print("CLÉ PUBLIQUE à coller dans license.py (_PUBLIC_KEY_B64) :")
    print()
    print(pub_b64)
    print()
    print("Collez cette valeur dans license.py :")
    print('    _PUBLIC_KEY_B64 = "' + pub_b64 + '"')


def cmd_issue(args: argparse.Namespace) -> None:

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key_path = Path(args.key).expanduser()
    if not key_path.exists():
        print(f"ERREUR : clé privée introuvable : {key_path}")
        print()
        print("Emplacements consultés, dans l'ordre :")
        print(f"  1. ${_ENV_KEY}")
        print(f"  2. {_HOME_KEY_PATH}")
        print(f"  3. {_LEGACY_KEY_PATH.resolve()} (historique)")
        print()
        print("Lancez d'abord : python3 gen_license.py keygen")
        sys.exit(1)
    _avertir_si_dans_depot(key_path)

    # Liaison machine OBLIGATOIRE sauf renoncement explicite : une clé non
    # liée est valable sur un nombre illimité de postes, ce qui vidait la
    # licence de son sens dès qu'un client la transmettait. On force donc
    # le geste conscient plutôt que le défaut permissif.
    if not args.machine_id and not args.any_machine:
        print("ERREUR : --machine-id est requis.")
        print()
        print("  Demandez au client son ID machine (affiché dans la fenêtre")
        print("  d'activation de l'app, ou via `python gen_license.py machine-id`)")
        print("  puis :")
        print(f'    python3 gen_license.py issue "{args.name}" "{args.email}"'
              " --machine-id <ID12>")
        print()
        print("  Pour émettre volontairement une clé valable sur TOUS les")
        print("  postes (site licence, poste de secours) : --any-machine")
        sys.exit(1)
    if args.machine_id and args.any_machine:
        print("ERREUR : --machine-id et --any-machine sont exclusifs.")
        sys.exit(1)

    priv = Ed25519PrivateKey.from_private_bytes(key_path.read_bytes())

    today = date.today()
    # Par défaut : expiration 1 an. Passer --no-expires pour illimité.
    expires = args.expires if args.expires else (
        None if args.no_expires else (today.replace(year=today.year + 1)).isoformat()
    )

    payload: dict = {
        "n": args.name,
        "e": args.email,
        "i": today.isoformat(),
    }
    if expires:
        payload["x"] = expires
    if args.machine_id:
        payload["m"] = args.machine_id

    payload_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    sig = priv.sign(payload_bytes)
    key = f"{_b64url(sig)}.{_b64url(payload_bytes)}"

    print()
    print("Licence émise pour :", args.name, f"<{args.email}>")
    if args.machine_id:
        print("Machine ID         :", args.machine_id)
    else:
        print("Machine            : TOUTES (non liée) — clé transférable")
    if expires:
        print("Expire le          :", expires)
    else:
        print("Durée              : illimitée")
    print()
    print("Clé à envoyer au client :")
    print()
    print(key)
    print()


def cmd_machine_id(args: argparse.Namespace) -> None:
    import license as lic
    mid = lic.get_machine_id()
    print("Machine ID (à fournir lors de la demande de licence) :")
    print()
    print(f"  {mid}")
    print()
    print("Source brute :", lic._raw_machine_id())


def cmd_verify(args: argparse.Namespace) -> None:
    # Import local pour ne pas imposer cryptography à l'import du module
    import license as lic

    # Si la clé publique n'est pas configurée dans license.py, on ne peut
    # pas vérifier. C'est normal avant la première configuration.
    result = lic.verify_license(args.key)
    if result is None:
        print("INVALIDE (ou clé publique non configurée dans license.py)")
        sys.exit(1)
    print("VALIDE")
    print(f"  Titulaire : {result.name} <{result.email}>")
    print(f"  Émise le  : {result.issued}")
    if result.expires:
        print(f"  Expire le : {result.expires}")
    else:
        print("  Durée     : illimitée")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Outil de gestion des licences Pénétromètre",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    kg = sub.add_parser("keygen", help="Générer la paire de clés (une seule fois)")
    kg.add_argument("--out", default=str(_HOME_KEY_PATH),
                    help=f"Fichier de clé privée (défaut : {_HOME_KEY_PATH})")
    kg.add_argument("--force", action="store_true",
                    help="Autoriser l'écriture de la clé dans un dépôt git")

    iss = sub.add_parser("issue", help="Émettre une licence client")
    iss.add_argument("name", help="Nom du titulaire / cabinet")
    iss.add_argument("email", help="Email du titulaire")
    iss.add_argument("--expires", default=None, metavar="AAAA-MM-JJ", help="Date d'expiration (défaut : 1 an)")
    iss.add_argument("--no-expires", action="store_true", help="Licence illimitée (sans expiration)")
    iss.add_argument("--machine-id", default=None, metavar="ID12",
                     help="Lier la licence à cette machine (12 hex chars — cf. machine-id). "
                          "REQUIS, sauf --any-machine")
    iss.add_argument("--any-machine", action="store_true",
                     help="Émettre une clé valable sur tous les postes "
                          "(transférable — à n'utiliser qu'en connaissance de cause)")
    iss.add_argument("--key", default=str(_default_key_path()),
                     help=f"Fichier clé privée (défaut : ${_ENV_KEY}, "
                          f"sinon {_HOME_KEY_PATH})")

    sub.add_parser("machine-id", help="Afficher l'ID machine de cette machine")

    ver = sub.add_parser("verify", help="Vérifier une clé")
    ver.add_argument("key", help="Clé à vérifier")

    args = parser.parse_args()
    if args.cmd == "keygen":
        cmd_keygen(args)
    elif args.cmd == "issue":
        cmd_issue(args)
    elif args.cmd == "machine-id":
        cmd_machine_id(args)
    elif args.cmd == "verify":
        cmd_verify(args)


if __name__ == "__main__":
    main()
