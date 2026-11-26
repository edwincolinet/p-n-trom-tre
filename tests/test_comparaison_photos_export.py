"""Le PDF d'évolution doit embarquer les photos même si la mission a été
enregistrée APRÈS la préparation de l'export (régression : `mission_dir` figé
à None, photos ignorées)."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from campagnes import archiver
from model import Arbre, Chantier, Sondage
from pane_evolution import EvolutionPane


def _arbre() -> Arbre:
    a = Arbre(numero_arbre="1", port_arbre="libre")
    a.brins[0].set_rayon(20.0)
    for g in (0, 100, 200, 300):
        a.brins[0].sondages.append(
            Sondage(grade=g, bois_sain_cm=8.0, bois_altere_cm=12.0))
    return a


class TestPhotosPdfEvolution(unittest.TestCase):
    def test_mission_enregistree_apres_la_preparation(self) -> None:
        from PIL import Image
        with TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "m_photos").mkdir()
            Image.new("RGB", (80, 60), (30, 120, 40)).save(
                d / "m_photos" / "a.jpg")
            a = _arbre()
            archiver(a, "01/06/2025")
            a.photos_comparaison_cur = ["m_photos/a.jpg"]
            chantier = Chantier(arbres=[a], date_releve="01/06/2026")
            hote = SimpleNamespace(
                chantier=chantier, current_file=None,
                var_show_sondages=SimpleNamespace(get=lambda: True),
                var_show_cernes=SimpleNamespace(get=lambda: True),
                _current_arbre=lambda: a)
            # Sans Tk : seules les méthodes d'export sont exercées.
            pane = EvolutionPane.__new__(EvolutionPane)
            pane._host, pane._arbre_id, pane._dates = hote, "", []
            construire = pane.constructeur_export(
                "pdf", cabinet_name="", logo_path=None)
            assert construire is not None
            sans = construire().page_no()
            hote.current_file = d / "m.json"
            avec = construire().page_no()
            self.assertEqual(avec, sans + 1)             # + page « Photos »


if __name__ == "__main__":
    unittest.main()
