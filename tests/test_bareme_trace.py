"""
Tests de traçabilité du barème et du CSV des sondages en cépée.

Deux angles morts corrigés ensemble parce qu'ils partagent la même
cause : une information présente dans le modèle mais absente du
livrable.

1. **Barème** — les seuils Vert/Orange/Rouge sont un réglage de POSTE
   (`~/.penetrometre/bareme.json`). Sans trace dans le fichier de
   mission ni dans les exports, deux opérateurs aux réglages différents
   produisent des classes différentes à partir des mêmes mesures, et
   rien ne permet de savoir laquelle a servi.
2. **CSV des sondages** — `Arbre.sondages` est une propriété-relais vers
   `brins[0]` : boucler dessus perdait silencieusement les brins b, c…
   d'une cépée.
"""

from __future__ import annotations

import csv
import os
import tempfile
import unittest
from unittest import mock

import bareme
from bareme import (
    SEUILS_DEFAUT,
    description_seuils,
    description_seuils_mission,
    get_seuils,
    set_seuils,
    seuils_depuis_brut,
    seuils_personnalises,
)
from geometry import GRADES
from model import Arbre, Brin, Chantier, Sondage
from persistence import chantier_from_dict, chantier_to_dict


class _SeuilsRestaures(unittest.TestCase):
    """Remet les seuils par défaut après chaque test (état global)."""

    def tearDown(self) -> None:
        set_seuils(SEUILS_DEFAUT["libre"], SEUILS_DEFAUT["strict"])


class DescriptionSeuilsTests(_SeuilsRestaures):
    def test_defaut_lisible(self):
        d = description_seuils()
        self.assertIn("30 %", d)
        self.assertIn("15 %", d)
        self.assertIn("20 %", d)
        self.assertIn("10 %", d)

    def test_reflete_les_seuils_personnalises(self):
        set_seuils((0.35, 0.18), (0.25, 0.12))
        d = description_seuils()
        self.assertIn("35 %", d)
        self.assertIn("18 %", d)
        self.assertNotIn("30 %", d)

    def test_detection_personnalisation(self):
        self.assertFalse(seuils_personnalises())
        set_seuils((0.35, 0.18), (0.20, 0.10))
        self.assertTrue(seuils_personnalises())

    def test_description_d_un_jeu_explicite(self):
        d = description_seuils({"libre": (0.5, 0.25), "strict": (0.4, 0.2)})
        self.assertIn("50 %", d)
        self.assertIn("25 %", d)


class PersistanceBaremeTests(_SeuilsRestaures):
    def test_seuils_ecrits_dans_le_json(self):
        set_seuils((0.35, 0.18), (0.25, 0.12))
        d = chantier_to_dict(Chantier(nom="M"))
        self.assertEqual(d["bareme_seuils"]["libre"], [0.35, 0.18])
        self.assertEqual(d["bareme_seuils"]["strict"], [0.25, 0.12])

    def test_roundtrip(self):
        set_seuils((0.35, 0.18), (0.25, 0.12))
        c = chantier_from_dict(chantier_to_dict(Chantier(nom="M")))
        self.assertEqual(c.bareme_seuils["libre"], (0.35, 0.18))

    def test_lecture_n_applique_pas_les_seuils(self):
        """Ouvrir une mission ne doit PAS reconfigurer le poste en douce."""
        d = chantier_to_dict(Chantier(nom="M"))
        d["bareme_seuils"] = {"libre": [0.9, 0.8], "strict": [0.7, 0.6]}
        chantier_from_dict(d)
        self.assertEqual(get_seuils(), SEUILS_DEFAUT)

    def test_mission_ancienne_sans_bareme(self):
        """Absence de la clé = « inconnu », pas d'erreur ni de migration."""
        d = chantier_to_dict(Chantier(nom="M"))
        del d["bareme_seuils"]
        c = chantier_from_dict(d)
        self.assertEqual(c.bareme_seuils, {})
        # La description retombe alors sur les seuils du poste.
        self.assertEqual(description_seuils_mission(c), description_seuils())

    def test_seuils_corrompus_tolerés(self):
        for brut in (None, "x", {"libre": "nope"}, {"libre": [1]}, {}):
            self.assertEqual(seuils_depuis_brut(brut)["libre"],
                             SEUILS_DEFAUT["libre"])

    def test_description_mission_utilise_les_seuils_du_fichier(self):
        c = Chantier(nom="M")
        c.bareme_seuils = {"libre": (0.42, 0.21), "strict": (0.3, 0.15)}
        self.assertIn("42 %", description_seuils_mission(c))

    def test_reenregistrement_ecrit_les_seuils_courants(self):
        """Un fichier doit décrire les seuils EN VIGUEUR à son écriture,
        pas recopier une valeur ancienne."""
        c = Chantier(nom="M")
        c.bareme_seuils = {"libre": (0.9, 0.8), "strict": (0.7, 0.6)}
        d = chantier_to_dict(c)
        self.assertEqual(d["bareme_seuils"]["libre"],
                         list(SEUILS_DEFAUT["libre"]))


def _cepee(n_brins: int) -> Chantier:
    c = Chantier(nom="Cépée", date_releve="01/01/2026")
    a = Arbre(numero_arbre="7", essence="Corylus", port_arbre="libre")
    a.brins = []
    for i in range(n_brins):
        b = Brin(rayon_tronc_cm=20.0 + i, epaisseur_ecorce_cm=1.0)
        # Un seul sondage par brin suffit à détecter la perte.
        b.sondages = [Sondage(numero=1, grade=GRADES[0],
                              bois_sain_cm=5.0, bois_altere_cm=15.0 + i)]
        a.brins.append(b)
    c.arbres.append(a)
    return c


class CsvSondagesCepeeTests(_SeuilsRestaures):
    """`export_csv_mission` doit couvrir TOUS les brins."""

    def _exporter(self, chantier: Chantier) -> "list[list[str]]":
        import app_exports
        out = os.path.join(tempfile.mkdtemp(), "sondages.csv")
        parent = mock.MagicMock()
        with mock.patch("app_exports.filedialog.asksaveasfilename",
                        return_value=out):
            app_exports.export_csv_mission(parent, chantier)
        with open(out, encoding="utf-8-sig", newline="") as f:
            return list(csv.reader(f, delimiter=";"))

    def test_tous_les_brins_sont_exportes(self):
        lignes = self._exporter(_cepee(3))
        data = [r for r in lignes
                if r and r[0] == "7"]           # lignes de l'arbre n°7
        self.assertEqual(len(data), 3,
                         "des brins ont disparu du CSV")
        self.assertEqual([r[1] for r in data], ["a", "b", "c"])

    def test_rayon_propre_a_chaque_brin(self):
        lignes = self._exporter(_cepee(3))
        data = [r for r in lignes if r and r[0] == "7"]
        rayons = [float(r[3]) for r in data]
        self.assertEqual(rayons, [20.0, 21.0, 22.0],
                         "le rayon du genet a été utilisé pour tous les brins")

    def test_mono_caule_sans_label_de_brin(self):
        lignes = self._exporter(_cepee(1))
        data = [r for r in lignes if r and r[0] == "7"]
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0][1], "",
                         "colonne Brin renseignée sur un mono-caule")

    def test_bareme_en_tete_du_csv(self):
        lignes = self._exporter(_cepee(2))
        self.assertTrue(lignes[0][0].startswith("# Barème appliqué"))


class ExportsCitentLeBaremeTests(_SeuilsRestaures):
    def test_html_contient_le_bareme(self):
        from export import export_prbs_html
        from palette import COULEUR_CLASSE
        c = _cepee(1)
        out = os.path.join(tempfile.mkdtemp(), "t.html")
        export_prbs_html(c.arbres[0], c, out,
                         couleur_classe=COULEUR_CLASSE,
                         classer_prbs=bareme.classer_prbs,
                         bareme_desc=description_seuils_mission(c))
        with open(out, encoding="utf-8") as f:
            html = f.read()
        self.assertIn("Barème appliqué", html)
        self.assertIn("30 %", html)

    def test_synthese_csv_contient_le_bareme(self):
        from diagnostic import mission_synthesis_rows
        from export import export_synthesis_csv
        c = _cepee(2)
        out = os.path.join(tempfile.mkdtemp(), "s.csv")
        export_synthesis_csv(mission_synthesis_rows(c), out,
                             bareme_desc=description_seuils_mission(c))
        with open(out, encoding="utf-8-sig") as f:
            self.assertTrue(f.readline().startswith("# Barème appliqué"))


if __name__ == "__main__":
    unittest.main()
