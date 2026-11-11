"""Profil du cabinet au premier lancement (`profil_cabinet`) — pur."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app_settings import SettingsStore
from profil_cabinet import MARQUEUR, appliquer_profil_initial


class TestProfilCabinet(unittest.TestCase):
    def setUp(self) -> None:
        self._t = TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        t = Path(self._t.name)
        self.profil = t / "profil"
        self.profil.mkdir()
        self.user = t / "user"
        self.settings = SettingsStore(self.user / "settings.json")
        self.bareme: list = []
        self.bareme_present = False

    def _ecrire_profil(self, d: dict) -> None:
        (self.profil / "profil.json").write_text(json.dumps(d),
                                                 encoding="utf-8")

    def _appliquer(self) -> bool:
        return appliquer_profil_initial(
            self.settings, self.profil, self.user,
            lambda: self.bareme_present, self.bareme.extend)

    def test_sans_profil_rien_ne_se_passe(self) -> None:
        self.assertFalse(self._appliquer())
        self.assertFalse((self.user / MARQUEUR).exists())

    def test_applique_nom_logo_dossier_une_seule_fois(self) -> None:
        (self.profil / "logo.png").write_bytes(b"\x89PNG")
        self._ecrire_profil({"cabinet_name": "Cabinet Test", "logo": "logo.png",
                             "update_folder": "S:/maj"})
        self.assertTrue(self._appliquer())
        self.assertEqual(self.settings.cabinet_name, "Cabinet Test")
        self.assertEqual(self.settings.update_folder(), "S:/maj")
        self.assertTrue(Path(self.settings.logo_path or "").is_file())
        self.settings.set_cabinet_name("Modifié")
        self.assertFalse(self._appliquer())       # marqueur : une seule fois
        self.assertEqual(self.settings.cabinet_name, "Modifié")

    def test_n_ecrase_pas_un_reglage_existant(self) -> None:
        self.settings.set_cabinet_name("Déjà là")
        self.bareme_present = True
        self._ecrire_profil({"cabinet_name": "Autre", "bareme": [],
                             "update_folder": "S:/maj"})
        self._appliquer()
        self.assertEqual(self.settings.cabinet_name, "Déjà là")
        self.assertEqual(self.bareme, [])

    def test_logo_chemin_suspect_ignore(self) -> None:
        self._ecrire_profil({"logo": "../secret.png"})
        self._appliquer()
        self.assertIsNone(self.settings.logo_path)

    def test_profil_corrompu_ne_leve_pas(self) -> None:
        (self.profil / "profil.json").write_text("{pas du json",
                                                 encoding="utf-8")
        self.assertFalse(self._appliquer())

    def test_bareme_ecrit_si_absent(self) -> None:
        self._ecrire_profil({"bareme": []})
        self.assertTrue(self._appliquer())
        self.assertTrue(self.bareme)               # défauts canonisés


if __name__ == "__main__":
    unittest.main()
