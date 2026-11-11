"""
Tests du filtrage de l'URL de mise à jour (`update_checker`).

`html_url` provient d'une réponse HTTP distante et finit dans
`webbrowser.open` : elle doit être vérifiée avant, sinon une réponse
détournée fait ouvrir une URL arbitraire.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from update_checker import (  # noqa: E402
    _RELEASES_URL,
    _parse_version,
    url_de_release_sure,
)


class UrlSureTests(unittest.TestCase):
    def test_url_du_depot_acceptee(self):
        u = _RELEASES_URL
        self.assertEqual(url_de_release_sure(u), u)

    def test_url_de_tag_acceptee(self):
        u = "https://github.com/edwincolinet/p-n-trom-tre/releases/tag/v4.0.0"
        self.assertEqual(url_de_release_sure(u), u)

    def test_autre_hote_rejete(self):
        for mauvais in (
            "https://evil.example/pwn",
            "https://github.com/attaquant/depot/releases",
            "https://github.com.evil.example/edwincolinet/p-n-trom-tre/",
            "http://github.com/edwincolinet/p-n-trom-tre/releases",  # pas HTTPS
        ):
            self.assertEqual(url_de_release_sure(mauvais), _RELEASES_URL,
                             mauvais)

    def test_schemas_non_http_rejetes(self):
        for mauvais in ("file:///etc/passwd", "javascript:alert(1)",
                        "data:text/html,<script>1</script>"):
            self.assertEqual(url_de_release_sure(mauvais), _RELEASES_URL,
                             mauvais)

    def test_types_inattendus_rejetes(self):
        for mauvais in (None, 42, {"url": "x"}, [], ""):
            self.assertEqual(url_de_release_sure(mauvais), _RELEASES_URL)


class VersionTests(unittest.TestCase):
    def test_parsing(self):
        self.assertEqual(_parse_version("v3.7.1"), (3, 7, 1))
        self.assertEqual(_parse_version("3.7.1"), (3, 7, 1))
        self.assertIsNone(_parse_version("pas-une-version"))


class DossierPartageTests(unittest.TestCase):
    def _dossier(self, *noms):
        import tempfile
        from pathlib import Path
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        for n in noms:
            (Path(d.name) / n).write_bytes(b"")
        return d.name

    def test_plus_recent_trouve(self):
        from update_checker import check_for_update_folder
        d = self._dossier("Penetrometre-3.7.0-Setup.exe",
                          "Penetrometre-3.10.0-Setup.exe", "notes.txt")
        self.assertEqual(check_for_update_folder("3.7.0", d), ("v3.10.0", d))

    def test_a_jour_ou_vide(self):
        from update_checker import check_for_update_folder
        d = self._dossier("Penetrometre-3.7.0-Setup.exe")
        self.assertIsNone(check_for_update_folder("3.7.0", d))
        self.assertIsNone(check_for_update_folder("3.7.0", self._dossier()))

    def test_dossier_inaccessible_ou_non_configure(self):
        from update_checker import check_for_update_folder
        self.assertIsNone(check_for_update_folder("3.7.0", "/inexistant/xyz"))
        self.assertIsNone(check_for_update_folder("3.7.0", ""))


if __name__ == "__main__":
    unittest.main()
