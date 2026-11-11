"""
Tests de traçabilité du barème et du CSV des sondages en cépée.

Deux angles morts corrigés ensemble parce qu'ils partagent la même
cause : une information présente dans le modèle mais absente du
livrable.

1. **Barème** — les seuils Vert/Orange/Rouge sont un réglage de POSTE
   (`~/.penetrometre/bareme.json`), organisé en **groupes de ports
   librement composés par l'expert** (`bareme.GroupeBareme` — un port
   individuel n'est qu'un groupe à un seul port). Sans trace dans le
   fichier de mission ni dans les exports, deux opérateurs aux réglages
   différents produisent des classes différentes à partir des mêmes
   mesures, et rien ne permet de savoir lequel a servi.
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
    CLASSE_ORANGE,
    CLASSE_VERT,
    GROUPES_DEFAUT,
    PORTS_ARBRE,
    GroupeBareme,
    classer_prbs,
    description_seuils,
    description_seuils_mission,
    get_groupes,
    groupes_vers_brut,
    set_groupes,
    seuils_depuis_brut,
    seuils_personnalises,
)
from geometry import GRADES
from model import Arbre, Brin, Chantier, Sondage
from persistence import chantier_from_dict, chantier_to_dict


def _groupes(vert_libre: float = 0.30, orange_libre: float = 0.15,
            vert_strict: float = 0.20, orange_strict: float = 0.10
            ) -> "list[GroupeBareme]":
    """Partition à 2 groupes (mêmes ports que la partition par défaut),
    seuils personnalisables — équivalent du `set_seuils(libre, strict)`
    d'avant cette fonctionnalité, pour les tests qui n'ont besoin que de
    seuils différents sans changer la composition des groupes."""
    return [
        GroupeBareme(GROUPES_DEFAUT[0].nom, GROUPES_DEFAUT[0].ports,
                     vert_libre, orange_libre),
        GroupeBareme(GROUPES_DEFAUT[1].nom, GROUPES_DEFAUT[1].ports,
                     vert_strict, orange_strict),
    ]


class _SeuilsRestaures(unittest.TestCase):
    """Remet les groupes par défaut après chaque test (état global)."""

    def tearDown(self) -> None:
        set_groupes(GROUPES_DEFAUT)


class DescriptionSeuilsTests(_SeuilsRestaures):
    def test_defaut_lisible(self):
        d = description_seuils()
        self.assertIn("30 %", d)
        self.assertIn("15 %", d)
        self.assertIn("20 %", d)
        self.assertIn("10 %", d)

    def test_reflete_les_seuils_personnalises(self):
        set_groupes(_groupes(0.35, 0.18, 0.25, 0.12))
        d = description_seuils()
        self.assertIn("35 %", d)
        self.assertIn("18 %", d)
        self.assertNotIn("30 %", d)

    def test_detection_personnalisation(self):
        self.assertFalse(seuils_personnalises())
        set_groupes(_groupes(0.35, 0.18, 0.20, 0.10))
        self.assertTrue(seuils_personnalises())

    def test_description_d_un_jeu_explicite(self):
        d = description_seuils(_groupes(0.5, 0.25, 0.4, 0.2))
        self.assertIn("50 %", d)
        self.assertIn("25 %", d)


class PersistanceBaremeTests(_SeuilsRestaures):
    def test_seuils_ecrits_dans_le_json(self):
        set_groupes(_groupes(0.35, 0.18, 0.25, 0.12))
        d = chantier_to_dict(Chantier(nom="M"))
        brut = {g["nom"]: g for g in d["bareme_seuils"]}
        self.assertEqual(brut[GROUPES_DEFAUT[0].nom]["vert"], 0.35)
        self.assertEqual(brut[GROUPES_DEFAUT[0].nom]["orange"], 0.18)
        self.assertEqual(brut[GROUPES_DEFAUT[1].nom]["vert"], 0.25)
        self.assertEqual(brut[GROUPES_DEFAUT[1].nom]["orange"], 0.12)

    def test_roundtrip(self):
        set_groupes(_groupes(0.35, 0.18, 0.25, 0.12))
        c = chantier_from_dict(chantier_to_dict(Chantier(nom="M")))
        self.assertEqual(seuils_depuis_brut(c.bareme_seuils), get_groupes())

    def test_lecture_n_applique_pas_les_seuils(self):
        """Ouvrir une mission ne doit PAS reconfigurer le poste en douce."""
        d = chantier_to_dict(Chantier(nom="M"))
        d["bareme_seuils"] = [{"nom": "X", "ports": list(PORTS_ARBRE),
                               "vert": 0.9, "orange": 0.8}]
        chantier_from_dict(d)
        self.assertEqual(get_groupes(), list(GROUPES_DEFAUT))

    def test_mission_ancienne_sans_bareme(self):
        """Absence de la clé = « inconnu », pas d'erreur ni de migration."""
        d = chantier_to_dict(Chantier(nom="M"))
        del d["bareme_seuils"]
        c = chantier_from_dict(d)
        self.assertEqual(c.bareme_seuils, [])
        # La description retombe alors sur les seuils du poste.
        self.assertEqual(description_seuils_mission(c), description_seuils())

    def test_seuils_corrompus_toleres(self):
        for brut in (None, "x", {"libre": "nope"}, {"libre": [1]}, {}, []):
            with self.subTest(brut=brut):
                self.assertEqual(seuils_depuis_brut(brut), list(GROUPES_DEFAUT))

    def test_description_mission_utilise_les_seuils_du_fichier(self):
        # Ancien format mission (2 clés) : migré au vol par
        # `description_seuils_mission` — vérifie aussi la migration.
        c = Chantier(nom="M")
        c.bareme_seuils = {"libre": (0.42, 0.21), "strict": (0.3, 0.15)}
        self.assertIn("42 %", description_seuils_mission(c))

    def test_reenregistrement_ecrit_les_seuils_courants(self):
        """Un fichier doit décrire les seuils EN VIGUEUR à son écriture,
        pas recopier une valeur ancienne."""
        c = Chantier(nom="M")
        c.bareme_seuils = {"libre": (0.9, 0.8), "strict": (0.7, 0.6)}
        d = chantier_to_dict(c)
        self.assertEqual(d["bareme_seuils"], groupes_vers_brut(GROUPES_DEFAUT))


class GroupesPersonnalisesTests(_SeuilsRestaures):
    """Composition libre des groupes (au-delà des 2 groupes par défaut) —
    cœur de la fonctionnalité : un port individuel n'est qu'un groupe à un
    seul port, sans distinction de code."""

    def test_trois_groupes_dont_un_port_unique(self):
        set_groupes([
            GroupeBareme("Libre seul", ("libre",), 0.35, 0.20),
            GroupeBareme("Reste souple", ("semi-libre", "délaissé"),
                        0.30, 0.15),
            GroupeBareme("Contraint", ("architecturé", "traumatique"),
                        0.20, 0.10),
        ])
        # 0.32 < 0.35 (seuil du groupe "Libre seul") ⟹ Orange.
        self.assertEqual(classer_prbs(0.32, "libre"), CLASSE_ORANGE)
        # 0.32 > 0.30 (seuil du groupe "Reste souple") ⟹ Vert.
        self.assertEqual(classer_prbs(0.32, "semi-libre"), CLASSE_VERT)
        self.assertTrue(seuils_personnalises())

    def test_seuils_personnalises_insensible_a_l_ordre_de_saisie(self):
        # Même partition que le défaut, groupes déclarés dans l'ordre
        # inverse : la canonisation doit neutraliser la différence.
        set_groupes(list(reversed(_groupes())))
        self.assertFalse(seuils_personnalises())

    def test_port_manquant_dans_config_brute_recupere_un_secours(self):
        # Config incomplète (un seul groupe déclaré, 4 ports orphelins) :
        # jamais de port sans groupe, même sur un bareme.json altéré à la
        # main.
        brut = [{"nom": "Libre", "ports": ["libre"],
                 "vert": 0.3, "orange": 0.15}]
        groupes = seuils_depuis_brut(brut)
        ports_couverts = {p for g in groupes for p in g.ports}
        self.assertEqual(ports_couverts, set(PORTS_ARBRE))

    def test_migration_ancien_format_poste(self):
        # `bareme_store.load_bareme` tolère l'ancien fichier à 2 groupes
        # fixes (tous les postes existants avant cette fonctionnalité).
        legacy = {"libre": [0.35, 0.18], "strict": [0.25, 0.12]}
        migre = seuils_depuis_brut(legacy)
        self.assertEqual(migre[0].seuil_vert, 0.35)
        self.assertEqual(migre[0].seuil_orange, 0.18)
        self.assertEqual(migre[1].seuil_vert, 0.25)
        self.assertEqual(migre[1].seuil_orange, 0.12)


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
        from export_synthesis import export_synthesis_csv
        c = _cepee(2)
        out = os.path.join(tempfile.mkdtemp(), "s.csv")
        export_synthesis_csv(mission_synthesis_rows(c), out,
                             bareme_desc=description_seuils_mission(c))
        with open(out, encoding="utf-8-sig") as f:
            self.assertTrue(f.readline().startswith("# Barème appliqué"))


if __name__ == "__main__":
    unittest.main()


class SeuilsArbreEtVerdictTests(unittest.TestCase):
    def test_description_seuils_arbre_cite_les_trois_classes_sans_port(self):
        from bareme import description_seuils_arbre
        from model import Chantier
        txt = description_seuils_arbre(Chantier(), "libre")
        self.assertIn("vert >", txt)
        self.assertIn("orange ≥", txt)
        self.assertIn("rouge <", txt)
        self.assertNotIn("libre", txt.lower())

    def _detail(self, ref, cur):
        from diagnostic_comparaison import ComparaisonDetail
        return ComparaisonDetail(
            annees=None, directions=[], perte_moy_par_dir=None,
            taux_cm_an=None, pire=None, compart_aggravees=0,
            compart_changees=0, classe_ref="Vert", classe_cur="Vert",
            tR_min_ref=ref, tR_min_cur=cur)

    def test_verdict_perte_gain_stable_sur_tr_meme_classe(self):
        from diagnostic_comparaison import verdict_evolution
        self.assertIn("AGGRAVATION", verdict_evolution(self._detail(60.0, 52.0)))
        self.assertIn("AMÉLIORATION",
                      verdict_evolution(self._detail(52.0, 60.0)))
        self.assertIn("STABLE", verdict_evolution(self._detail(52.0, 52.04)))

    def test_tr_min_stable_mais_perte_ailleurs_n_est_pas_stable(self):
        from diagnostic_comparaison import DirectionDelta, evolution_globale, verdict_evolution
        d = self._detail(5.0, 5.0)
        perdues = [DirectionDelta(0, "N", 10.0, 10.0, 0.0, "", ""),
                   DirectionDelta(50, "NE", 12.0, 10.5, -1.5, "", "")]
        d = d._replace(directions=perdues)
        v = verdict_evolution(d)
        self.assertNotIn("STABLE", v)
        self.assertIn("AGGRAVATION LOCALISÉE", v)
        self.assertIn("NE", v)
        self.assertEqual(evolution_globale(d), 1)

    def test_gain_tr_avec_perte_ailleurs_est_contraste_pas_ameliore(self):
        from diagnostic_comparaison import DirectionDelta, verdict_contraste, verdict_evolution
        d = self._detail(5.0, 8.0)._replace(directions=[
            DirectionDelta(50, "NE", 12.0, 10.5, -1.5, "", "")])
        v = verdict_evolution(d)
        self.assertIn("CONTRASTÉE", v)
        self.assertNotIn("AMÉLIORATION", v)
        self.assertTrue(verdict_contraste(d))

    def test_comparaison_signale_les_directions_mesurees_aux_deux_dates(self):
        from comparaison_render import metric_rows
        from diagnostic_comparaison import comparaison_detaillee
        from model import Arbre, Sondage

        def mk(grades_sains):
            a = Arbre(numero_arbre="1", port_arbre="libre")
            a.brins[0].set_rayon(20.0)
            for g, sain in grades_sains.items():
                a.brins[0].sondages.append(
                    Sondage(grade=g, bois_sain_cm=sain,
                            bois_altere_cm=20 - sain))
            return a

        ref = mk({0: 10, 100: 10, 200: 10, 300: 10})
        cur = mk({0: 10, 100: 10, 200: 6, 350: 10})   # 200 et 350 ≠ réf
        d = comparaison_detaillee(ref, cur, 2.0)
        # Mesurées aux 2 dates : 0, 100, 200 (350 n'est sondé qu'au courant,
        # 300 qu'à la référence).
        self.assertEqual(d.n_mesurees_2_dates, 3)
        from diagnostic_comparaison import verdict_evolution
        self.assertIn("3/16", verdict_evolution(d))
        self.assertTrue(any(r[0].startswith("Directions mesurées")
                            for r in metric_rows(d)))

    def test_pire_direction_extrapolee_est_signalee(self):
        from diagnostic_comparaison import DirectionDelta, verdict_evolution
        d = self._detail(5.0, 5.0)._replace(directions=[
            DirectionDelta(50, "NE", 12.0, 10.5, -1.5, "", "",
                           mesuree_2_dates=False)])
        self.assertIn("extrapolée", verdict_evolution(d))

    def test_pas_de_ligne_prbs_moyenne(self):
        from comparaison_render import metric_rows
        libelles = [r[0] for r in metric_rows(self._detail(60.0, 52.0))]
        self.assertFalse(any("PRBS moyenne" in x for x in libelles))


class PhotosComparaisonTests(unittest.TestCase):
    def _arbre(self, sain):
        from model import Arbre, Sondage
        a = Arbre(numero_arbre="1", port_arbre="libre")
        a.brins[0].set_rayon(20.0)
        for g in (0, 100, 200, 300):
            a.brins[0].sondages.append(
                Sondage(grade=g, bois_sain_cm=sain, bois_altere_cm=20 - sain))
        return a

    def test_page_photos_ajoutee_et_roundtrip(self):
        from pathlib import Path

        from PIL import Image

        from comparaison_render import render_comparison_pages
        from model import Chantier
        from persistence import load_chantier, save_chantier
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "m_photos").mkdir()
            Image.new("RGB", (400, 300), "green").save(d / "m_photos" / "a.jpg")
            Image.new("RGB", (300, 400), "blue").save(d / "m_photos" / "b.png")
            (d / "m_photos" / "x.desktop").write_text("[Desktop Entry]")
            cur = self._arbre(5.0)
            cur.photos_comparaison_ref = ["m_photos/a.jpg",
                                          "m_photos/x.desktop",
                                          "../../etc/passwd.png",
                                          "m_photos/absente.jpg"]
            cur.photos_comparaison_cur = ["m_photos/b.png"]
            ch = Chantier()
            ch.arbres.append(cur)
            save_chantier(ch, d / "m.json")
            cur2 = load_chantier(d / "m.json").arbres[0]
            self.assertEqual(cur2.photos_comparaison_cur, ["m_photos/b.png"])
            avec = render_comparison_pages(
                "M", self._arbre(8.0), cur2, 2.0, ref_label="2024",
                cur_label="2026", chantier=ch, mission_dir=d)
            sans = render_comparison_pages(
                "M", self._arbre(8.0), cur2, 2.0, ref_label="2024",
                cur_label="2026", chantier=ch, mission_dir=None)
            self.assertEqual(len(avec), 2)   # chiffrée + photos
            self.assertEqual(len(sans), 1)   # relatifs non résolus → rien
