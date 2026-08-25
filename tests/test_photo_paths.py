"""
Tests du confinement des chemins de photos (`photo_paths`).

Une mission `.json` circule entre confrères : ses références photo sont
une entrée semi-fiable. Ces tests verrouillent les trois règles décrites
dans l'en-tête de `photo_paths` — extension, jail du dossier de mission,
tolérance aux chemins absolus hérités.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from photo_paths import (  # noqa: E402
    MOTIF_EXTENSION,
    MOTIF_HORS_MISSION,
    MOTIF_INTROUVABLE,
    MOTIF_SANS_MISSION,
    resolve_photo,
    suffixe_autorise,
)


class _TmpMission(unittest.TestCase):
    """Arborescence jetable : <tmp>/mission.json + <tmp>/mission_photos/."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.mission_dir = self.root / "mission"
        self.photos_dir = self.mission_dir / "mission_photos"
        self.photos_dir.mkdir(parents=True)
        self.photo = self.photos_dir / "arbre1.jpg"
        self.photo.write_bytes(b"\xff\xd8\xff")  # entête JPEG factice
        # Cible « sensible » hors du dossier de mission.
        self.dehors = self.root / "prive.png"
        self.dehors.write_bytes(b"\x89PNG")

    def tearDown(self) -> None:
        self._tmp.cleanup()


class SuffixeTests(unittest.TestCase):
    def test_extensions_images_acceptees(self):
        for nom in ("a.jpg", "a.JPEG", "a.png", "a.Tif", "a.webp"):
            self.assertTrue(suffixe_autorise(nom), nom)

    def test_extensions_dangereuses_refusees(self):
        # `.desktop` est le vecteur d'exécution via xdg-open ; les autres
        # sont les classiques du même registre.
        for nom in ("evil.desktop", "run.sh", "a.exe", "note.txt",
                    "sans_extension", "a.png.desktop"):
            self.assertFalse(suffixe_autorise(nom), nom)


class ResolutionTests(_TmpMission):
    def test_relatif_dans_le_dossier_mission_ok(self):
        res = resolve_photo("mission_photos/arbre1.jpg", self.mission_dir)
        self.assertEqual(res.path, self.photo)
        self.assertEqual(res.motif, "")
        self.assertFalse(res.hors_mission)

    def test_traversal_refuse(self):
        # Le cas d'attaque : remonter hors du dossier de la mission.
        res = resolve_photo("../prive.png", self.mission_dir)
        self.assertIsNone(res.path)
        self.assertEqual(res.motif, MOTIF_HORS_MISSION)

    def test_traversal_profond_refuse(self):
        res = resolve_photo("mission_photos/../../../../etc/hosts.png",
                            self.mission_dir)
        self.assertIsNone(res.path)
        self.assertEqual(res.motif, MOTIF_HORS_MISSION)

    def test_extension_refusee_avant_tout(self):
        # Même dans le dossier de la mission, un .desktop est refusé.
        piege = self.photos_dir / "piege.desktop"
        piege.write_text("[Desktop Entry]\nExec=rm -rf ~\n")
        res = resolve_photo("mission_photos/piege.desktop", self.mission_dir)
        self.assertIsNone(res.path)
        self.assertEqual(res.motif, MOTIF_EXTENSION)

    def test_relatif_introuvable(self):
        res = resolve_photo("mission_photos/absent.jpg", self.mission_dir)
        self.assertIsNone(res.path)
        self.assertEqual(res.motif, MOTIF_INTROUVABLE)

    def test_relatif_sans_mission_enregistree(self):
        res = resolve_photo("mission_photos/arbre1.jpg", None)
        self.assertIsNone(res.path)
        self.assertEqual(res.motif, MOTIF_SANS_MISSION)

    def test_absolu_dans_la_mission_non_signale(self):
        res = resolve_photo(str(self.photo), self.mission_dir)
        self.assertEqual(res.path, self.photo)
        self.assertFalse(res.hors_mission)

    def test_absolu_hors_mission_accepte_mais_signale(self):
        # Compat des missions de juin 2026 (chemins absolus n'importe où) :
        # utilisable, mais l'UI doit pouvoir le dire.
        res = resolve_photo(str(self.dehors), self.mission_dir)
        self.assertEqual(res.path, self.dehors)
        self.assertTrue(res.hors_mission)

    def test_absolu_hors_mission_mauvaise_extension_refuse(self):
        secret = self.root / "cle.pem"
        secret.write_text("-----BEGIN PRIVATE KEY-----")
        res = resolve_photo(str(secret), self.mission_dir)
        self.assertIsNone(res.path)
        self.assertEqual(res.motif, MOTIF_EXTENSION)

    @unittest.skipIf(sys.platform == "win32", "symlinks POSIX")
    def test_lien_symbolique_sortant_refuse(self):
        # Un relatif qui pointe, via symlink, hors du dossier de mission.
        lien = self.photos_dir / "lien.png"
        try:
            lien.symlink_to(self.dehors)
        except OSError:
            self.skipTest("symlink indisponible")
        res = resolve_photo("mission_photos/lien.png", self.mission_dir)
        self.assertIsNone(res.path)
        self.assertEqual(res.motif, MOTIF_HORS_MISSION)

    def test_reference_vide(self):
        self.assertIsNone(resolve_photo("", self.mission_dir).path)


if __name__ == "__main__":
    unittest.main()
