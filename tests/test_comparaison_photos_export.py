"""Le PDF de comparaison doit embarquer les photos même si la mission a été
enregistrée APRÈS la sélection des arbres dans la fenêtre de comparaison
(régression : `mission_dir` figé à None, photos ignorées)."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from comparaison import _page_builder
from model import Arbre, Chantier, Sondage


def _arbre() -> Arbre:
    a = Arbre(numero_arbre="1", port_arbre="libre")
    a.brins[0].set_rayon(20.0)
    for g in (0, 100, 200, 300):
        a.brins[0].sondages.append(
            Sondage(grade=g, bois_sain_cm=8.0, bois_altere_cm=12.0))
    return a


class TestPhotosPdfComparaison(unittest.TestCase):
    def test_mission_enregistree_apres_la_selection(self) -> None:
        from PIL import Image
        with TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "m_photos").mkdir()
            Image.new("RGB", (80, 60), (30, 120, 40)).save(d / "m_photos" / "a.jpg")
            ref, cur = _arbre(), _arbre()
            cur.photos_comparaison_cur = ["m_photos/a.jpg"]
            ch = Chantier()
            ch.arbres = [cur]
            # État à la sélection : mission pas encore enregistrée.
            etat: dict = {"builder_args": (
                "Mission", ref, cur, 1.0, "2025", "2026", True,
                {"chantier": ch, "mission_dir": None,
                 "cabinet_name": "", "logo_path": None})}
            sans = _page_builder(etat, "pdf")()
            # Puis la mission est enregistrée : l'export doit la voir.
            etat["en_tete_fn"] = lambda: {
                "chantier": ch, "mission_dir": d,
                "cabinet_name": "", "logo_path": None}
            avec = _page_builder(etat, "pdf")()
            self.assertEqual(len(avec), len(sans) + 1)   # + page « Photos »


if __name__ == "__main__":
    unittest.main()
