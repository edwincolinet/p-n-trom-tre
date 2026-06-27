"""
Outil de génération de licences Pénétromètre — USAGE INTERNE UNIQUEMENT.

NE PAS inclure dans le bundle de distribution (PyInstaller l'ignore
car il n'est pas importé par penetrometre.py).

Commandes :
  python gen_license.py keygen
      → génère la paire de clés Ed25519 (à faire UNE SEULE FOIS).
        Sauvegarde la clé privée dans private.key (à conserver hors repo).
        Affiche la clé publique à coller dans license.py (_PUBLIC_KEY_B64).

  python gen_license.py issue "Nom du cabinet" "email@example.com"
  python gen_license.py issue "Nom du cabinet" "email@example.com" --expires 2027-06-01
      → émet une clé de licence signée à envoyer au client.

  python gen_license.py verify <clé>
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
import sys
from datetime import date
from pathlib import Path

_DEFAULT_KEY_PATH = Path("private.key")


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

    key_path = Path(args.out)
    if key_path.exists():
        print(f"ERREUR : {key_path} existe déjà. Supprimez-le manuellement si vous")
        print("voulez regénérer (attention : invalide toutes les licences émises).")
        sys.exit(1)

    priv = Ed25519PrivateKey.generate()
    priv_bytes = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub_bytes = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    key_path.write_bytes(priv_bytes)

    pub_b64 = base64.b64encode(pub_bytes).decode()
    print("=" * 60)
    print("CLÉ PRIVÉE sauvegardée dans :", key_path.resolve())
    print("→ Conservez ce fichier hors du dépôt git (déjà dans .gitignore).")
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

    key_path = Path(args.key)
    if not key_path.exists():
        print(f"ERREUR : clé privée introuvable : {key_path}")
        print("Lancez d'abord : python gen_license.py keygen")
        sys.exit(1)

    priv = Ed25519PrivateKey.from_private_bytes(key_path.read_bytes())

    payload: dict = {
        "n": args.name,
        "e": args.email,
        "i": date.today().isoformat(),
    }
    if args.expires:
        payload["x"] = args.expires

    payload_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    sig = priv.sign(payload_bytes)
    key = f"{_b64url(sig)}.{_b64url(payload_bytes)}"

    print()
    print("Licence émise pour :", args.name, f"<{args.email}>")
    if args.expires:
        print("Expire le          :", args.expires)
    else:
        print("Durée              : illimitée")
    print()
    print("Clé à envoyer au client :")
    print()
    print(key)
    print()


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
    kg.add_argument("--out", default=str(_DEFAULT_KEY_PATH), help="Fichier de clé privée")

    iss = sub.add_parser("issue", help="Émettre une licence client")
    iss.add_argument("name", help="Nom du titulaire / cabinet")
    iss.add_argument("email", help="Email du titulaire")
    iss.add_argument("--expires", default=None, metavar="AAAA-MM-JJ", help="Date d'expiration (optionnelle)")
    iss.add_argument("--key", default=str(_DEFAULT_KEY_PATH), help="Fichier clé privée")

    ver = sub.add_parser("verify", help="Vérifier une clé")
    ver.add_argument("key", help="Clé à vérifier")

    args = parser.parse_args()
    if args.cmd == "keygen":
        cmd_keygen(args)
    elif args.cmd == "issue":
        cmd_issue(args)
    elif args.cmd == "verify":
        cmd_verify(args)


if __name__ == "__main__":
    main()
