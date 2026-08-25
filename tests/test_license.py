"""
Tests du durcissement de la licence offline (`license.py`).

Couvre les garde-fous ajoutés autour de la vérification Ed25519 :
recul d'horloge, licence utilisée avant émission, essai rejoué,
permissions des fichiers. La signature elle-même est testée via une
paire de clés jetable générée dans le test (jamais la clé de prod).
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )
    HAS_CRYPTO = True
except ImportError:                                   # pragma: no cover
    HAS_CRYPTO = False

import license as lic  # noqa: E402


def _emettre(priv, **payload) -> str:
    """Fabrique une clé de licence signée avec `priv` (paire jetable)."""
    import base64
    raw = json.dumps(payload, ensure_ascii=False,
                     separators=(",", ":")).encode("utf-8")

    def b64(d: bytes) -> str:
        return base64.urlsafe_b64encode(d).rstrip(b"=").decode()

    return f"{b64(priv.sign(raw))}.{b64(raw)}"


@unittest.skipUnless(HAS_CRYPTO, "cryptography requis")
class _LicenceIsolee(unittest.TestCase):
    """Redirige tout l'état de `license` vers un HOME jetable."""

    def setUp(self) -> None:
        import base64

        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            PublicFormat,
        )
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)

        self._priv = Ed25519PrivateKey.generate()
        pub = self._priv.public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw)

        self._sauve = {
            "_CONFIG_DIR": lic._CONFIG_DIR,
            "_LICENSE_PATH": lic._LICENSE_PATH,
            "_TRIAL_PATH": lic._TRIAL_PATH,
            "_STATE_PATH": lic._STATE_PATH,
            "_PUBLIC_KEY_B64": lic._PUBLIC_KEY_B64,
        }
        lic._CONFIG_DIR = root / ".penetrometre"
        lic._LICENSE_PATH = lic._CONFIG_DIR / "license.key"
        lic._TRIAL_PATH = lic._CONFIG_DIR / "trial.json"
        lic._STATE_PATH = lic._CONFIG_DIR / "state.json"
        lic._PUBLIC_KEY_B64 = base64.b64encode(pub).decode()
        self._reset_cache()

    def tearDown(self) -> None:
        for k, v in self._sauve.items():
            setattr(lic, k, v)
        self._reset_cache()
        self._tmp.cleanup()

    @staticmethod
    def _reset_cache() -> None:
        lic._state_cache = None
        lic._last_seen_ecrit = False


class VerificationTests(_LicenceIsolee):
    def test_cle_valide_acceptee(self):
        cle = _emettre(self._priv, n="Cabinet X", e="x@y.fr",
                       i=date.today().isoformat())
        ld = lic.verify_license(cle)
        self.assertIsNotNone(ld)
        self.assertEqual(ld.name, "Cabinet X")

    def test_signature_falsifiee_refusee(self):
        autre = Ed25519PrivateKey.generate()
        cle = _emettre(autre, n="Pirate", e="p@q.fr",
                       i=date.today().isoformat())
        self.assertIsNone(lic.verify_license(cle))

    def test_expiree_refusee(self):
        hier = date.today() - timedelta(days=1)
        cle = _emettre(self._priv, n="X", e="x@y.fr",
                       i=(hier - timedelta(days=400)).isoformat(),
                       x=hier.isoformat())
        self.assertIsNone(lic.verify_license(cle))

    def test_avant_emission_refusee(self):
        """Recul d'horloge sous la date d'émission — la date est signée,
        donc ce contrôle n'est pas contournable côté client."""
        demain = date.today() + timedelta(days=1)
        cle = _emettre(self._priv, n="X", e="x@y.fr", i=demain.isoformat())
        self.assertIsNone(lic.verify_license(cle, today=date.today()))

    def test_machine_id_different_refuse(self):
        cle = _emettre(self._priv, n="X", e="x@y.fr",
                       i=date.today().isoformat(), m="0" * 12)
        self.assertIsNone(lic.verify_license(cle))


class HorlogeTests(_LicenceIsolee):
    def test_recul_horloge_ne_ressuscite_pas_une_licence(self):
        # Le poste a déjà vu le 01/06/2027 ; une licence expirée fin 2026
        # ne doit pas redevenir valide en reculant l'horloge.
        lic._write_state(last_seen="2027-06-01")
        self._reset_cache()
        cle = _emettre(self._priv, n="X", e="x@y.fr",
                       i="2026-01-01", x="2026-12-31")
        self.assertIsNone(lic.verify_license(cle, today=lic.today_effectif()))

    def test_today_effectif_plancher(self):
        futur = (date.today() + timedelta(days=10)).isoformat()
        lic._write_state(last_seen=futur)
        self._reset_cache()
        self.assertEqual(lic.today_effectif().isoformat(), futur)

    def test_bond_lointain_non_memorise(self):
        """Pile CMOS morte → date aberrante : on tolère pour le calcul du
        jour mais on refuse de graver le bond, sinon la licence serait
        condamnée après remise à l'heure."""
        lic._write_state(last_seen=date.today().isoformat())
        self._reset_cache()
        lointain = date.today() + timedelta(days=lic._AVANCE_MAX_JOURS + 365)
        original = lic.date
        try:
            class _FauxDate(date):
                @classmethod
                def today(cls):
                    return lointain
            lic.date = _FauxDate
            self.assertEqual(lic.today_effectif(), lointain)
        finally:
            lic.date = original
        self._reset_cache()
        # Le repère n'a pas bougé.
        self.assertEqual(lic._read_state()["last_seen"],
                         date.today().isoformat())


class EssaiTests(_LicenceIsolee):
    def test_demarrage_et_duree(self):
        t = lic.start_trial()
        self.assertEqual(t.days_remaining, lic._TRIAL_DAYS)
        self.assertTrue(lic.essai_deja_consomme())

    def test_idempotent(self):
        t1 = lic.start_trial()
        t2 = lic.start_trial()
        self.assertEqual(t1.started, t2.started)

    def test_suppression_de_trial_json_ne_relance_pas(self):
        """Le geste évident pour se réoffrir 30 jours : la date est aussi
        dans state.json, on retient la plus ancienne."""
        lic.start_trial()
        lic._TRIAL_PATH.unlink()
        self._reset_cache()
        self.assertTrue(lic.essai_deja_consomme())
        info = lic.get_trial_info()
        self.assertIsNotNone(info)
        self.assertEqual(info.days_remaining, lic._TRIAL_DAYS)

    def test_essai_expire_non_relancable(self):
        vieux = (date.today() - timedelta(days=lic._TRIAL_DAYS + 5)).isoformat()
        lic._write_state(trial_started=vieux)
        self._reset_cache()
        self.assertIsNone(lic.get_trial_info())       # expiré
        self.assertTrue(lic.essai_deja_consomme())    # mais bien consommé
        self.assertEqual(lic.start_trial().days_remaining, 0)

    def test_recul_horloge_ne_rallonge_pas_l_essai(self):
        depart = (date.today() - timedelta(days=20)).isoformat()
        lic._write_state(trial_started=depart,
                         last_seen=date.today().isoformat())
        self._reset_cache()
        self.assertEqual(lic.get_trial_info().days_remaining,
                         lic._TRIAL_DAYS - 20)


@unittest.skipIf(sys.platform == "win32", "permissions POSIX")
class PermissionsTests(_LicenceIsolee):
    def test_fichiers_en_0600(self):
        cle = _emettre(self._priv, n="X", e="x@y.fr",
                       i=date.today().isoformat())
        self.assertTrue(lic.save_license(cle))
        lic.start_trial()
        for p in (lic._LICENSE_PATH, lic._TRIAL_PATH, lic._STATE_PATH):
            self.assertEqual(p.stat().st_mode & 0o777, 0o600, p.name)

    def test_dossier_en_0700(self):
        lic.start_trial()
        self.assertEqual(lic._CONFIG_DIR.stat().st_mode & 0o777, 0o700)


@unittest.skipIf(sys.platform == "win32", "permissions POSIX")
class DurcissementRetroactifTests(_LicenceIsolee):
    """Une installation antérieure au durcissement doit se corriger seule.

    Sans ça, la `license.key` d'un client resterait lisible par tous les
    comptes du poste indéfiniment : on ne réécrit une licence qu'à la
    réactivation, ce qui peut ne jamais arriver.
    """

    def _installation_ancienne(self) -> None:
        """Reproduit ce que produisait l'ancien code : dossier 0755,
        fichiers 0644."""
        lic._CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        lic._CONFIG_DIR.chmod(0o755)
        for p in (lic._LICENSE_PATH, lic._TRIAL_PATH, lic._STATE_PATH):
            p.write_text("{}", encoding="utf-8")
            p.chmod(0o644)

    def test_dossier_et_fichiers_resserres(self):
        self._installation_ancienne()
        lic.durcir_config_existante()
        self.assertEqual(lic._CONFIG_DIR.stat().st_mode & 0o777, 0o700)
        for p in (lic._LICENSE_PATH, lic._TRIAL_PATH, lic._STATE_PATH):
            self.assertEqual(p.stat().st_mode & 0o777, 0o600, p.name)

    def test_idempotent_et_sans_effet_si_deja_correct(self):
        self._installation_ancienne()
        lic.durcir_config_existante()
        avant = lic._LICENSE_PATH.stat().st_mode
        lic.durcir_config_existante()
        self.assertEqual(lic._LICENSE_PATH.stat().st_mode, avant)

    def test_premier_lancement_sans_dossier(self):
        """Aucun dossier encore créé : ne doit rien lever."""
        if lic._CONFIG_DIR.exists():
            for p in lic._CONFIG_DIR.iterdir():
                p.unlink()
            lic._CONFIG_DIR.rmdir()
        lic.durcir_config_existante()          # ne lève pas
        self.assertFalse(lic._CONFIG_DIR.exists())

    def test_ne_touche_pas_les_autres_fichiers(self):
        """`bareme.json` & co. sont couverts par le 0700 du dossier ; on
        ne va pas fouiller tout le répertoire pour autant."""
        self._installation_ancienne()
        autre = lic._CONFIG_DIR / "bareme.json"
        autre.write_text("{}", encoding="utf-8")
        autre.chmod(0o644)
        lic.durcir_config_existante()
        self.assertEqual(autre.stat().st_mode & 0o777, 0o644)
        # …mais le dossier, lui, interdit désormais la traversée.
        self.assertEqual(lic._CONFIG_DIR.stat().st_mode & 0o777, 0o700)


if __name__ == "__main__":
    unittest.main()
