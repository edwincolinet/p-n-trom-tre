"""Garde-fou anti-écrasement multi-poste (mission sur dossier partagé).

`persistence.file_stamp` (pur) + `FichierMixin._confirmer_ecrasement` /
`action_save` : si le fichier a changé sur le disque depuis l'ouverture,
l'enregistrement demande confirmation au lieu d'écraser en silence.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from persistence import file_stamp, load_chantier
from tests.test_app import _SKIP_REASON, _SKIP_TK


class TestFileStamp(unittest.TestCase):
    def test_absent_donne_none(self) -> None:
        self.assertIsNone(file_stamp("/chemin/inexistant.json"))

    def test_change_quand_le_contenu_change(self) -> None:
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "m.json"
            p.write_text("{}", encoding="utf-8")
            a = file_stamp(p)
            self.assertIsNotNone(a)
            self.assertEqual(a, file_stamp(p))
            p.write_text('{"x": 1}', encoding="utf-8")
            self.assertNotEqual(a, file_stamp(p))


@unittest.skipIf(_SKIP_TK, _SKIP_REASON)
class TestEcrasementApp(unittest.TestCase):
    def setUp(self) -> None:
        import app_fichier
        import penetrometre
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        self.app = penetrometre.App()
        self.addCleanup(self.app.destroy)
        self.app.action_new()
        self.app._recent = mock.Mock()
        patch = mock.patch.object(app_fichier, "_BACKUP_PATH", tmp / "bk")
        patch.start()
        self.addCleanup(patch.stop)
        self.fichier = tmp / "mission.json"
        self.app.current_file = self.fichier
        self.app.action_save()           # 1er enregistrement : pas de garde
        self.assertTrue(self.fichier.exists())

    def _modifier_ailleurs(self) -> None:
        self.fichier.write_text(self.fichier.read_text(encoding="utf-8")
                                + " ", encoding="utf-8")
        st = self.fichier.stat()
        os.utime(self.fichier, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000))

    def test_sans_modification_externe_pas_de_question(self) -> None:
        with mock.patch("app_fichier.messagebox.askyesnocancel") as q:
            self.app.action_save()
        q.assert_not_called()

    def test_modifie_ailleurs_annuler_ne_touche_pas_au_fichier(self) -> None:
        self._modifier_ailleurs()
        avant = self.fichier.read_bytes()
        with mock.patch("app_fichier.messagebox.askyesnocancel",
                        return_value=None) as q:
            self.app.action_save()
        q.assert_called_once()
        self.assertEqual(self.fichier.read_bytes(), avant)

    def test_modifie_ailleurs_ecraser_sauvegarde_l_autre_version(self) -> None:
        self._modifier_ailleurs()
        with mock.patch("app_fichier.messagebox.askyesnocancel",
                        return_value=True):
            self.app.action_save()
        load_chantier(self.fichier)      # fichier valide, écrasé
        sauvegardes = list((Path(self._tmp.name) / "bk").glob("mission_*.json"))
        self.assertTrue(sauvegardes)
        # La question n'est plus posée juste après (empreinte remise à jour).
        with mock.patch("app_fichier.messagebox.askyesnocancel") as q:
            self.app.action_save()
        q.assert_not_called()

    def test_modifie_ailleurs_copie_ouvre_enregistrer_sous(self) -> None:
        self._modifier_ailleurs()
        with mock.patch("app_fichier.messagebox.askyesnocancel",
                        return_value=False), \
                mock.patch.object(self.app, "action_save_as") as sa:
            self.app.action_save()
        sa.assert_called_once()


if __name__ == "__main__":
    unittest.main()
