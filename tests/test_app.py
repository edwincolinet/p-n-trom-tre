"""Tests de la fenêtre `App` et de ses mixins / helpers.

Deux familles :

1. `RecentFilesStore` (`app_recent`) — pur (JSON + listes), testé sans
   Tk : déduplication, bornage, persistance, callback `on_change`,
   tolérance aux fichiers corrompus.

2. `App` et ses mixins (`ArbreListMixin`, `RecoveryMixin`,
   `ExportActionsMixin`) — instanciés en headless. Comble la zone aveugle
   laissée jusqu'ici : la logique d'orchestration (état des arbres,
   filtre, navigation, ajout/duplication, récupération de session) ne
   vivait que dans `App` et n'était couverte par aucun test.

Les tests Tk sont silencieusement *skipped* quand `tkinter` ou le
`DISPLAY` sont indisponibles (CI sans Xvfb), comme `test_section_canvas`.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

# `tests/__init__.py` ajoute la racine du projet à sys.path.
from app_recent import RecentFilesStore
from app_settings import UI_SCALE_DEFAULT, UI_SCALE_MAX, UI_SCALE_MIN, SettingsStore
from model import Arbre, Sondage

# --- Détection Tk (même sonde que test_section_canvas) ------------------
_TK_AVAILABLE = False
_DISPLAY_OK = False
try:
    import tkinter as tk  # noqa: F401
    _TK_AVAILABLE = True
    try:
        _probe = tk.Tk()
        _probe.destroy()
        _DISPLAY_OK = True
    except tk.TclError:
        pass
except ImportError:
    pass

_SKIP_TK = not (_TK_AVAILABLE and _DISPLAY_OK)
_SKIP_REASON = "tkinter ou DISPLAY indisponible (headless sans Xvfb)"


# ========================================================================
# normaliser_date — pur, sans Tk (import du module seul, pas de root)
# ========================================================================

class TestNormaliserDate(unittest.TestCase):
    def test_vide_renvoie_chaine_vide(self) -> None:
        from dialogs import normaliser_date
        self.assertEqual(normaliser_date(""), "")
        self.assertEqual(normaliser_date("   "), "")

    def test_format_francais_zero_pad(self) -> None:
        from dialogs import normaliser_date
        self.assertEqual(normaliser_date("4/6/2026"), "04/06/2026")
        self.assertEqual(normaliser_date("14/06/2026"), "14/06/2026")

    def test_separateurs_varies(self) -> None:
        from dialogs import normaliser_date
        for s in ("14-06-2026", "14.06.2026", "14 06 2026", "14/6/2026"):
            self.assertEqual(normaliser_date(s), "14/06/2026")

    def test_annee_deux_chiffres(self) -> None:
        from dialogs import normaliser_date
        self.assertEqual(normaliser_date("14/06/26"), "14/06/2026")

    def test_iso_annee_en_tete(self) -> None:
        from dialogs import normaliser_date
        self.assertEqual(normaliser_date("2026-06-14"), "14/06/2026")
        self.assertEqual(normaliser_date("2026/6/4"), "04/06/2026")

    def test_invalide_renvoie_none(self) -> None:
        from dialogs import normaliser_date
        for s in ("pas une date", "14/06", "14/06/2026/01",
                  "31/02/2026", "00/06/2026", "14/13/2026", "abc/de/fg"):
            self.assertIsNone(normaliser_date(s), s)


class TestAnneesEntre(unittest.TestCase):
    def test_duree_positive(self) -> None:
        from dialogs import annees_entre
        self.assertAlmostEqual(
            annees_entre("01/01/2020", "01/01/2023"), 3.0, places=1)

    def test_signe_negatif_si_inverse(self) -> None:
        from dialogs import annees_entre
        v = annees_entre("01/01/2023", "01/01/2020")
        self.assertIsNotNone(v)
        self.assertLess(v, 0)

    def test_none_si_date_manquante_ou_illisible(self) -> None:
        from dialogs import annees_entre
        self.assertIsNone(annees_entre("", "01/01/2023"))
        self.assertIsNone(annees_entre("01/01/2023", "pas une date"))


# ========================================================================
# RecentFilesStore — pur, sans Tk
# ========================================================================

class TestRecentFilesStore(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.path = Path(self._tmp.name) / "recent.json"
        self.changes = 0

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _store(self, maxlen: int = 8) -> RecentFilesStore:
        def on_change() -> None:
            self.changes += 1
        return RecentFilesStore(self.path, maxlen, on_change)

    def test_vide_au_depart(self) -> None:
        self.assertEqual(self._store().get(), [])

    def test_push_et_ordre_plus_recent_en_tete(self) -> None:
        s = self._store()
        s.push("/a.json")
        s.push("/b.json")
        # Le plus récent est en tête (chemins résolus).
        got = [Path(p).name for p in s.get()]
        self.assertEqual(got, ["b.json", "a.json"])

    def test_dedup_remonte_en_tete(self) -> None:
        s = self._store()
        s.push("/a.json")
        s.push("/b.json")
        s.push("/a.json")  # déjà présent → remonte sans doublon
        got = [Path(p).name for p in s.get()]
        self.assertEqual(got, ["a.json", "b.json"])

    def test_bornage_maxlen(self) -> None:
        s = self._store(maxlen=2)
        for n in ("a", "b", "c"):
            s.push(f"/{n}.json")
        got = [Path(p).name for p in s.get()]
        self.assertEqual(got, ["c.json", "b.json"])  # "a" évincé

    def test_remove(self) -> None:
        s = self._store()
        s.push("/a.json")
        s.push("/b.json")
        s.remove("/a.json")
        self.assertEqual([Path(p).name for p in s.get()], ["b.json"])

    def test_on_change_appele(self) -> None:
        s = self._store()
        s.push("/a.json")
        s.remove("/a.json")
        self.assertEqual(self.changes, 2)

    def test_persistance_relecture(self) -> None:
        s = self._store()
        s.push("/a.json")
        # Un nouveau store sur le même chemin relit la liste persistée.
        s2 = self._store()
        self.assertEqual(s.get(), s2.get())

    def test_json_corrompu_tolere(self) -> None:
        self.path.write_text("{pas du json", encoding="utf-8")
        # L'exception de parsing est journalisée (assertLogs la capture
        # pour ne pas polluer la sortie des tests) mais jamais propagée.
        with self.assertLogs("penetrometre", level="ERROR"):
            self.assertEqual(self._store().get(), [])

    def test_json_non_liste_ignore(self) -> None:
        self.path.write_text(json.dumps({"x": 1}), encoding="utf-8")
        self.assertEqual(self._store().get(), [])


# ========================================================================
# Helpers d'état d'arbre — testables sans instance Tk (staticmethod)
# ========================================================================
# SettingsStore — pur, sans Tk
# ========================================================================

class TestSettingsStore(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.path = Path(self._tmp.name) / "settings.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_defaut_si_absent(self) -> None:
        self.assertEqual(SettingsStore(self.path).ui_scale, UI_SCALE_DEFAULT)

    def test_set_persiste_et_recharge(self) -> None:
        SettingsStore(self.path).set_ui_scale(1.2)
        self.assertEqual(SettingsStore(self.path).ui_scale, 1.2)

    def test_bornage(self) -> None:
        s = SettingsStore(self.path)
        s.set_ui_scale(99.0)
        self.assertEqual(s.ui_scale, UI_SCALE_MAX)
        s.set_ui_scale(0.01)
        self.assertEqual(s.ui_scale, UI_SCALE_MIN)

    def test_json_corrompu_retombe_au_defaut(self) -> None:
        self.path.write_text("{pas du json", encoding="utf-8")
        self.assertEqual(SettingsStore(self.path).ui_scale, UI_SCALE_DEFAULT)

    def test_valeur_non_numerique_ignoree(self) -> None:
        self.path.write_text('{"ui_scale": "grand"}', encoding="utf-8")
        self.assertEqual(SettingsStore(self.path).ui_scale, UI_SCALE_DEFAULT)

    def test_sash_defaut_vide(self) -> None:
        self.assertEqual(SettingsStore(self.path).get_sash_positions(), [])

    def test_sash_persiste_et_recharge(self) -> None:
        SettingsStore(self.path).set_sash_positions([240, 700])
        self.assertEqual(
            SettingsStore(self.path).get_sash_positions(), [240, 700])

    def test_sash_corrompu_retombe_vide(self) -> None:
        self.path.write_text('{"sash_positions": "nope"}', encoding="utf-8")
        self.assertEqual(SettingsStore(self.path).get_sash_positions(), [])
        self.path.write_text('{"sash_positions": [1, "x"]}', encoding="utf-8")
        self.assertEqual(SettingsStore(self.path).get_sash_positions(), [])

    def test_high_contrast_defaut_false_et_persiste(self) -> None:
        self.assertFalse(SettingsStore(self.path).high_contrast)
        SettingsStore(self.path).set_high_contrast(True)
        self.assertTrue(SettingsStore(self.path).high_contrast)


# ========================================================================
# ui_fonts — échelle des polices, pur
# ========================================================================

class TestUiFonts(unittest.TestCase):

    def setUp(self) -> None:
        import ui_fonts
        self.uf = ui_fonts
        # Remise à 1.0 après le test : facteur global de processus, ne
        # doit pas fuiter vers les autres tests (App le re-fixe de toute
        # façon depuis settings au démarrage, mais on reste propre).
        self.addCleanup(self.uf.set_ui_scale, 1.0)

    def test_identite_a_1(self) -> None:
        self.uf.set_ui_scale(1.0)
        self.assertEqual(self.uf.font("Helvetica", 10), ("Helvetica", 10))
        self.assertEqual(self.uf.font("Georgia", 18, "bold"),
                         ("Georgia", 18, "bold"))

    def test_mise_a_l_echelle(self) -> None:
        self.uf.set_ui_scale(1.4)
        self.assertEqual(self.uf.font("Helvetica", 10), ("Helvetica", 14))
        # Les options (bold/italic) sont préservées après la taille.
        self.assertEqual(self.uf.font("Helvetica", 10, "bold"),
                         ("Helvetica", 14, "bold"))
        self.assertEqual(self.uf.get_ui_scale(), 1.4)

    def test_taille_plancher(self) -> None:
        self.uf.set_ui_scale(0.0)
        self.assertEqual(self.uf.font("Helvetica", 10)[1], 1)


# ========================================================================

class TestArbreEtat(unittest.TestCase):
    """`_arbre_etat` est une `@staticmethod` : testable sans fenêtre."""

    def setUp(self) -> None:
        from app_arbres import ArbreListMixin
        self.etat = ArbreListMixin._arbre_etat

    def _arbre(self, rayon: float, n_sondages: int,
               sain: float | None = None) -> Arbre:
        """Arbre de test : `n_sondages` directions, PRBS = `sain` (ou le
        rayon = tronc sain par défaut → classe Vert)."""
        bois_sain = rayon if sain is None else sain
        a = Arbre(numero_arbre="1", rayon_tronc_cm=rayon)
        for i in range(n_sondages):
            a.sondages.append(
                Sondage(numero=i + 1, grade=i * 25, bois_sain_cm=bois_sain,
                        bois_altere_cm=max(0.0, rayon - bois_sain)))
        return a

    def test_rayon_nul_est_vide(self) -> None:
        glyph, risque, tag = self.etat(self._arbre(0.0, 5))
        self.assertEqual((glyph, risque, tag), ("○", "—", "etat_vide"))

    def test_sans_sondage_est_vide(self) -> None:
        glyph, risque, tag = self.etat(self._arbre(20.0, 0))
        self.assertEqual((glyph, risque, tag), ("○", "—", "etat_vide"))

    def test_un_ou_deux_sondages_partiel(self) -> None:
        # Incomplet => glyphe ◐, risque non publié (—), ligne neutre.
        self.assertEqual(self.etat(self._arbre(20.0, 1)),
                         ("◐", "—", "etat_partiel"))
        self.assertEqual(self.etat(self._arbre(20.0, 2)),
                         ("◐", "—", "etat_partiel"))

    def test_trois_sondages_fiable_colore_par_classe(self) -> None:
        # Seuil métier : >= 3 directions => diagnostic fiable. La ligne est
        # colorée par la classe de risque ET le mot est posé en colonne
        # Risque. Tronc sain (PRBS = rayon → t/R = 1.0) => classe Vert.
        glyph, risque, tag = self.etat(self._arbre(20.0, 3))
        self.assertEqual((glyph, risque, tag), ("●", "Vert", "etat_ok_vert"))
        # Tronc très dégradé (PRBS = 1 cm sur 20 → t/R ≈ 5 %) => Rouge.
        glyph, risque, tag = self.etat(self._arbre(20.0, 3, sain=1.0))
        self.assertEqual((glyph, risque, tag), ("●", "Rouge", "etat_ok_rouge"))

    def test_glyphes_distincts_par_completude(self) -> None:
        # La forme (pas seulement la couleur) distingue les 3 états :
        # accessible en cas de daltonisme rouge-vert.
        self.assertEqual(self.etat(self._arbre(0.0, 0))[0], "○")
        self.assertEqual(self.etat(self._arbre(20.0, 1))[0], "◐")
        self.assertEqual(self.etat(self._arbre(20.0, 3))[0], "●")

    def test_cepee_etat_colore_par_le_pire_brin(self) -> None:
        # Genet à 2 brins : un sain (Vert), un très dégradé (Rouge). La
        # pastille du genet prend la classe du PIRE brin fiable.
        a = self._arbre(20.0, 3)              # brin a : sain → Vert
        rouge = self._arbre(20.0, 3, sain=1.0).brins[0]  # brin b : Rouge
        a.brins.append(rouge)
        a._relabel_brins()
        glyph, risque, tag = self.etat(a)
        self.assertEqual(glyph, "●")
        self.assertEqual(risque, "Rouge")
        self.assertEqual(tag, "etat_ok_rouge")

    def test_cepee_partiel_si_aucun_brin_fiable(self) -> None:
        # 2 brins à 2 sondages chacun : aucun n'atteint 3 → genet « en cours ».
        a = self._arbre(20.0, 2)
        a.brins.append(self._arbre(20.0, 2).brins[0])
        a._relabel_brins()
        self.assertEqual(self.etat(a)[0], "◐")


# ========================================================================
# App + mixins — headless (skipped sans display)
# ========================================================================

@unittest.skipIf(_SKIP_TK, _SKIP_REASON)
class TestAppMixins(unittest.TestCase):

    def setUp(self) -> None:
        import penetrometre
        self.app = penetrometre.App()
        self.app.update_idletasks()

    def tearDown(self) -> None:
        try:
            self.app.destroy()
        except tk.TclError:
            pass

    # --- ArbreListMixin ---

    def test_app_demarre_avec_un_arbre(self) -> None:
        self.assertEqual(len(self.app.chantier.arbres), 1)

    def test_next_numero_incremente_le_max(self) -> None:
        self.app.chantier.arbres[0].numero_arbre = "7"
        self.assertEqual(self.app._next_arbre_numero(), "8")

    def test_next_numero_tolere_non_numerique(self) -> None:
        self.app.chantier.arbres[0].numero_arbre = "12 bis"
        # Pas de n° numérique exploitable -> au moins nb_arbres + 1.
        self.assertEqual(self.app._next_arbre_numero(), "2")

    def test_add_arbre_ajoute_et_selectionne(self) -> None:
        self.app.action_add_arbre()
        self.assertEqual(len(self.app.chantier.arbres), 2)
        self.assertEqual(self.app.current_idx, 1)

    def test_add_brin_cree_une_cepee_et_undo(self) -> None:
        a = self.app.chantier.arbres[0]
        a.rayon_tronc_cm = 16.0
        self.assertEqual(len(a.brins), 1)
        self.app.add_brin()
        self.assertEqual(len(a.brins), 2)
        self.assertEqual([b.label for b in a.brins], ["a", "b"])
        # 2e brin placé à l'Est (pos_x > 0).
        self.assertGreater(a.brins[1].pos_x_cm, 0.0)
        # Undo retire le brin ajouté.
        self.app._perform_undo()
        self.assertEqual(len(self.app.chantier.arbres[0].brins), 1)

    def test_remove_last_brin_refuse_de_descendre_sous_un(self) -> None:
        a = self.app.chantier.arbres[0]
        self.app.add_brin()
        self.assertEqual(len(a.brins), 2)
        self.app.remove_last_brin()
        self.assertEqual(len(a.brins), 1)
        # Genet mono-caule : nouvel appel sans effet.
        self.app.remove_last_brin()
        self.assertEqual(len(a.brins), 1)

    # --- Brin courant / sélecteur de cépée ---

    def test_current_brin_est_brins0_pour_mono_caule(self) -> None:
        a = self.app.chantier.arbres[0]
        self.assertIs(self.app._current_brin(), a.brins[0])

    def test_set_current_brin_repointe_la_saisie(self) -> None:
        a = self.app.chantier.arbres[0]
        a.rayon_tronc_cm = 20.0
        self.app.add_brin()  # brin "b" devient courant
        self.assertEqual(self.app._current_brin_idx, 1)
        self.assertIs(self.app._current_brin(), a.brins[1])
        # Saisir un sondage via la grille écrit sur le brin courant (b),
        # pas sur brins[0].
        self.app.pane_s._rows[0]["sain"].set("12")
        self.assertEqual(len(a.brins[1].sondages), 1)
        self.assertEqual(len(a.brins[0].sondages), 0)
        # Revenir au brin a et vérifier l'isolation.
        self.app.set_current_brin(0)
        self.assertIs(self.app._current_brin(), a.brins[0])
        self.assertEqual(len(a.brins[0].sondages), 0)

    def test_changer_d_arbre_remet_le_brin_courant_a_zero(self) -> None:
        self.app.add_brin()
        self.assertEqual(self.app._current_brin_idx, 1)
        self.app.action_add_arbre()  # nouvel arbre courant
        self.assertEqual(self.app._current_brin_idx, 0)

    def test_remove_last_brin_borne_le_brin_courant(self) -> None:
        self.app.add_brin()            # idx -> 1
        self.assertEqual(self.app._current_brin_idx, 1)
        self.app.remove_last_brin()    # le brin courant n'existe plus
        self.assertEqual(self.app._current_brin_idx, 0)
        self.assertIsNotNone(self.app._current_brin())

    def test_selecteur_brin_masque_pour_mono_caule(self) -> None:
        # Genet mono-caule : la barre de sélection n'est pas affichée.
        self.assertFalse(self.app.brin_bar.winfo_ismapped())
        self.app.add_brin()
        self.app.update_idletasks()
        self.assertTrue(self.app.brin_bar.winfo_ismapped())
        self.assertEqual(len(self.app._brin_btns), 2)

    def test_edit_cepee_layout_applique_positions_rotation_et_undo(self) -> None:
        import penetrometre
        a = self.app.chantier.arbres[0]
        a.rayon_tronc_cm = 16.0
        self.app.add_brin()  # 2 brins ; brin b à l'Est
        old_b = (a.brins[1].pos_x_cm, a.brins[1].pos_y_cm,
                 a.brins[1].rotation_grades)
        # Stub du dialogue modal : nouvelles positions + rotation (a ancré).
        orig = penetrometre.ask_cepee_layout
        penetrometre.ask_cepee_layout = lambda parent, arbre: [
            (0.0, 0.0, 0), (50.0, -30.0, 75)]
        try:
            self.app.edit_cepee_layout()
        finally:
            penetrometre.ask_cepee_layout = orig
        self.assertEqual((a.brins[0].pos_x_cm, a.brins[0].pos_y_cm), (0.0, 0.0))
        self.assertEqual((a.brins[1].pos_x_cm, a.brins[1].pos_y_cm),
                         (50.0, -30.0))
        self.assertEqual(a.brins[1].rotation_grades, 75)
        # Undo restaure position ET rotation précédentes du brin b.
        self.app._perform_undo()
        b1 = self.app.chantier.arbres[0].brins[1]
        self.assertEqual((b1.pos_x_cm, b1.pos_y_cm, b1.rotation_grades), old_b)

    def test_edit_cepee_layout_noop_si_mono_caule(self) -> None:
        import penetrometre
        called = {"n": 0}

        def _spy(parent: object, arbre: object) -> None:
            called["n"] += 1
            return None

        orig = penetrometre.ask_cepee_layout
        penetrometre.ask_cepee_layout = _spy
        try:
            self.app.edit_cepee_layout()  # 1 seul brin → ne doit pas ouvrir
        finally:
            penetrometre.ask_cepee_layout = orig
        self.assertEqual(called["n"], 0)

    def test_progression_onglets_reflete_l_avancement(self) -> None:
        a = self.app.chantier.arbres[0]
        a.essence = "Platane"
        a.rayon_tronc_cm = 20.0
        for i in range(3):
            a.sondages.append(Sondage(numero=i + 1, grade=i * 25,
                                      bois_sain_cm=20.0, bois_altere_cm=0.0))
        self.app._refresh_tab_progress()
        # Étapes prêtes => `●` ; vocabulaire de glyphes des pastilles.
        self.assertTrue(
            self.app.nb.tab(self.app.pane_id, "text").startswith("●"))
        self.assertTrue(
            self.app.nb.tab(self.app.pane_s, "text").startswith("●"))
        self.assertTrue(
            self.app.nb.tab(self.app.pane_diag, "text").startswith("●"))
        # Sondages incomplets => `◐` (en cours), Diagnostic non fiable => `○`.
        a.sondages.pop()
        self.app._refresh_tab_progress()
        self.assertTrue(
            self.app.nb.tab(self.app.pane_s, "text").startswith("◐"))
        self.assertTrue(
            self.app.nb.tab(self.app.pane_diag, "text").startswith("○"))

    def test_add_arbre_inherit_reprend_identite_pas_geometrie(self) -> None:
        cur = self.app.chantier.arbres[0]
        cur.essence = "Platane"
        cur.port_arbre = "semi-libre"
        cur.meche_cm = 40.0
        cur.rayon_tronc_cm = 33.0
        cur.sondages.append(Sondage(numero=1, grade=0,
                                    bois_sain_cm=33.0, bois_altere_cm=0.0))
        self.app.action_add_arbre_inherit()
        new = self.app.chantier.arbres[-1]
        # Identité héritée…
        self.assertEqual(new.essence, "Platane")
        self.assertEqual(new.port_arbre, "semi-libre")
        self.assertEqual(new.meche_cm, 40.0)
        # …mais pas la géométrie mesurée ni les sondages.
        self.assertNotEqual(new.rayon_tronc_cm, 33.0)
        self.assertEqual(new.sondages, [])

    def test_dup_arbre_prochain_numero(self) -> None:
        # La duplication attribue le prochain numéro libre (max+1),
        # plus les suffixes "bis/ter" abandonnés.
        self.app.chantier.arbres[0].numero_arbre = "5"
        self.app.action_dup_arbre()
        self.assertEqual(len(self.app.chantier.arbres), 2)
        self.assertEqual(self.app.chantier.arbres[1].numero_arbre, "6")

    def test_filtre_par_numero(self) -> None:
        self.app.chantier.arbres[0].numero_arbre = "1"
        self.app.action_add_arbre()
        self.app.chantier.arbres[1].numero_arbre = "42"
        a0, a1 = self.app.chantier.arbres
        self.app.var_filter.set("42")
        self.assertFalse(self.app._arbre_matches_filter(a0))
        self.assertTrue(self.app._arbre_matches_filter(a1))

    def test_filtre_par_essence_insensible_casse(self) -> None:
        a = self.app.chantier.arbres[0]
        a.essence = "Platane"
        self.app.var_filter.set("plat")
        self.assertTrue(self.app._arbre_matches_filter(a))

    def test_filtre_vide_tout_passe(self) -> None:
        a = self.app.chantier.arbres[0]
        self.app.var_filter.set("")
        self.assertTrue(self.app._arbre_matches_filter(a))

    def test_filtre_risque_classe(self) -> None:
        from model import Sondage
        # Arbre fiable sain → Vert.
        vert = self.app.chantier.arbres[0]
        vert.rayon_tronc_cm = 20.0
        for i in range(3):
            vert.sondages.append(Sondage(numero=i + 1, grade=i * 25,
                                         bois_sain_cm=20.0, bois_altere_cm=0.0))
        # Arbre incomplet (0 sondage) → « Non fiable ».
        self.app.action_add_arbre()
        vide = self.app.chantier.arbres[1]
        # Filtre « Vert » : seul l'arbre fiable vert passe.
        self.app.var_risk_filter.set("Vert")
        self.assertTrue(self.app._arbre_matches_filter(vert))
        self.assertFalse(self.app._arbre_matches_filter(vide))
        # Filtre « Non fiable » : l'inverse.
        self.app.var_risk_filter.set("Non fiable")
        self.assertFalse(self.app._arbre_matches_filter(vert))
        self.assertTrue(self.app._arbre_matches_filter(vide))

    def test_filtre_risque_et_texte_se_cumulent(self) -> None:
        from model import Sondage
        a = self.app.chantier.arbres[0]
        a.essence = "Platane"
        a.rayon_tronc_cm = 20.0
        for i in range(3):
            a.sondages.append(Sondage(numero=i + 1, grade=i * 25,
                                      bois_sain_cm=20.0, bois_altere_cm=0.0))
        self.app.var_risk_filter.set("Vert")
        self.app.var_filter.set("chêne")        # essence ne concorde pas
        self.assertFalse(self.app._arbre_matches_filter(a))
        self.app.var_filter.set("plat")         # concorde + Vert
        self.assertTrue(self.app._arbre_matches_filter(a))

    def test_filtre_urgence_niveau(self) -> None:
        a0 = self.app.chantier.arbres[0]
        a0.urgence = "Immédiate"
        self.app.action_add_arbre()
        a1 = self.app.chantier.arbres[1]
        a1.urgence = "< 2 ans"
        self.app.action_add_arbre()
        a2 = self.app.chantier.arbres[2]
        a2.urgence = ""  # non renseignée

        self.app.var_urgence_filter.set("Immédiate")
        self.assertTrue(self.app._arbre_matches_filter(a0))
        self.assertFalse(self.app._arbre_matches_filter(a1))
        self.assertFalse(self.app._arbre_matches_filter(a2))

        self.app.var_urgence_filter.set("Non renseignée")
        self.assertFalse(self.app._arbre_matches_filter(a0))
        self.assertFalse(self.app._arbre_matches_filter(a1))
        self.assertTrue(self.app._arbre_matches_filter(a2))

        self.app.var_urgence_filter.set("Toutes")
        self.assertTrue(self.app._arbre_matches_filter(a0))
        self.assertTrue(self.app._arbre_matches_filter(a1))
        self.assertTrue(self.app._arbre_matches_filter(a2))

    def test_filtre_urgence_efface_a_la_creation(self) -> None:
        self.app.var_urgence_filter.set("Immédiate")
        self.app.action_add_arbre()
        self.assertEqual(self.app.var_urgence_filter.get(), "Toutes")

    def test_preconisation_edition_et_undo(self) -> None:
        pane = self.app.pane_diag
        self.app.nb.select(pane)
        pane.refresh()
        # Urgence (mutation discrète + dirty).
        pane.var_urgence.set("Immédiate")
        pane._on_urgence_changed()
        self.assertEqual(self.app.chantier.arbres[0].urgence, "Immédiate")
        self.assertTrue(self.app._dirty)
        # Texte libre (snapshot focus-in → commit focus-out).
        pane._preco_focus_in()
        pane.txt_preco.delete("1.0", "end")
        pane.txt_preco.insert("1.0", "Abattage")
        pane._on_preco_focus_out()
        self.assertEqual(self.app.chantier.arbres[0].preconisation, "Abattage")
        self.app._perform_undo()
        self.assertEqual(self.app.chantier.arbres[0].preconisation, "")

    def test_preconisation_rechargee_au_changement_d_arbre(self) -> None:
        pane = self.app.pane_diag
        self.app.nb.select(pane)
        self.app.chantier.arbres[0].urgence = "< 2 ans"
        pane.refresh()
        self.assertEqual(pane.var_urgence.get(), "< 2 ans")
        # Nouvel arbre (urgence vide) → le pane recharge, pas de fuite.
        self.app.action_add_arbre()
        pane.refresh()
        self.assertEqual(pane.var_urgence.get(), "— Non renseignée —")

    def test_navigation_relative_bornee(self) -> None:
        for _ in range(2):
            self.app.action_add_arbre()  # 3 arbres, idx=2
        self.app.action_next_arbre()  # déjà au dernier : reste borné
        self.assertEqual(self.app.current_idx, 2)
        self.app.action_prev_arbre()
        self.assertEqual(self.app.current_idx, 1)

    def test_add_arbre_vide_le_filtre(self) -> None:
        self.app.var_filter.set("zzz")
        self.app.action_add_arbre()
        self.assertEqual(self.app.var_filter.get(), "")

    # --- Grille Contreforts (saisie directe, 16 directions) ---

    def test_grille_contreforts_cree_et_supprime(self) -> None:
        a = self.app.chantier.arbres[0]
        a.rayon_tronc_cm = 20.0
        # Taper une longueur crée le contrefort sur cette direction.
        self.app.pane_cf._rows[100]["long"].set("12")
        self.assertEqual(len(a.contreforts), 1)
        c = a.contreforts[0]
        self.assertEqual(c.grade_centre, 100)
        self.assertEqual(c.longueur_cm, 12.0)
        self.assertEqual(c.largeur_grades, 75)  # largeur par défaut
        # Effacer la valeur supprime le contrefort.
        self.app.pane_cf._rows[100]["long"].set("")
        self.assertEqual(len(a.contreforts), 0)

    def test_grille_contreforts_largeur_via_combobox(self) -> None:
        a = self.app.chantier.arbres[0]
        self.app.pane_cf._rows[0]["long"].set("8")
        self.app.pane_cf._rows[0]["larg"].set("150")
        self.app.pane_cf._on_larg_changed(0)
        self.assertEqual(a.contreforts[0].largeur_grades, 150)

    def test_grille_contreforts_tries_et_renumerotes_par_grade(self) -> None:
        a = self.app.chantier.arbres[0]
        self.app.pane_cf._rows[200]["long"].set("5")
        self.app.pane_cf._rows[0]["long"].set("7")
        self.assertEqual([c.grade_centre for c in a.contreforts], [0, 200])
        self.assertEqual([c.numero for c in a.contreforts], [1, 2])

    def test_grille_contreforts_refresh_depuis_modele(self) -> None:
        from model import Contrefort
        a = self.app.chantier.arbres[0]
        a.contreforts.append(Contrefort(numero=1, grade_centre=50,
                                        largeur_grades=100,
                                        longueur_cm=9.0))
        self.app.pane_cf.refresh()
        row = self.app.pane_cf._rows[50]
        self.assertEqual(row["long"].get(), "9")
        self.assertEqual(row["larg"].get(), "100")
        self.assertEqual(str(row["combo"].cget("state")), "readonly")
        # Direction sans contrefort : ligne vide, largeur inactive.
        vide = self.app.pane_cf._rows[75]
        self.assertEqual(vide["long"].get(), "")
        self.assertEqual(str(vide["combo"].cget("state")), "disabled")

    # --- Tableau Dégradations (édition en place) ---

    def test_degradations_ajout_via_dialogue(self) -> None:
        """_on_add ouvre un dialogue avant d'ajouter : ajout si OK, rien si Annuler."""
        from unittest.mock import patch
        a = self.app.chantier.arbres[0]
        # Dialogue validé → la dégradation est ajoutée sur le premier arc libre.
        with patch("pane_degradations.edit_degradation", return_value=True):
            self.app.pane_de._on_add()
        self.assertEqual(len(a.degradations_externes), 1)
        d1 = a.degradations_externes[0]
        self.assertEqual((d1.grade_debut, d1.grade_fin), (0, 50))
        # 2e ajout (dialogue validé) : premier arc libre suivant.
        with patch("pane_degradations.edit_degradation", return_value=True):
            self.app.pane_de._on_add()
        self.assertEqual(len(a.degradations_externes), 2)
        self.assertEqual(a.degradations_externes[1].grade_debut, 50)
        # Dialogue annulé → aucun ajout supplémentaire.
        with patch("pane_degradations.edit_degradation", return_value=False):
            self.app.pane_de._on_add()
        self.assertEqual(len(a.degradations_externes), 2)

    def test_degradations_profondeur_editee_en_place(self) -> None:
        from unittest.mock import patch
        a = self.app.chantier.arbres[0]
        with patch("pane_degradations.edit_degradation", return_value=True):
            self.app.pane_de._on_add()
        row = self.app.pane_de._row_refs[0]
        row["prof"].set("4,5")  # virgule décimale acceptée
        self.assertEqual(a.degradations_externes[0].profondeur_cm, 4.5)

    def test_degradations_arc_valide_applique(self) -> None:
        from unittest.mock import patch

        from dialogs import find_grade_choice
        a = self.app.chantier.arbres[0]
        with patch("pane_degradations.edit_degradation", return_value=True):
            self.app.pane_de._on_add()  # 0 → 50
        deg = a.degradations_externes[0]
        row = self.app.pane_de._row_refs[0]
        row["fin"].set(find_grade_choice(
            self.app.pane_de._grade_choices, 100))
        self.app.pane_de._on_arc_changed(deg, row)
        self.assertEqual(deg.grade_fin, 100)

    def test_degradations_chevauchement_refuse_et_retabli(self) -> None:
        from unittest.mock import patch

        from dialogs import find_grade_choice
        from model import DegradationExterne
        a = self.app.chantier.arbres[0]
        a.degradations_externes.append(
            DegradationExterne(numero=1, grade_debut=0, grade_fin=50))
        a.degradations_externes.append(
            DegradationExterne(numero=2, grade_debut=100, grade_fin=150))
        self.app.pane_de.refresh()
        deg2 = a.degradations_externes[1]
        row = self.app.pane_de._row_refs[1]
        # Début 25 → chevaucherait la dégradation n°1 (0 → 50).
        row["deb"].set(find_grade_choice(
            self.app.pane_de._grade_choices, 25))
        with patch("pane_degradations.messagebox.showwarning") as warn:
            self.app.pane_de._on_arc_changed(deg2, row)
            warn.assert_called_once()
        # Modèle inchangé ET combobox rétablie sur la valeur du modèle.
        self.assertEqual(deg2.grade_debut, 100)
        self.assertTrue(row["deb"].get().startswith("100 gr"))

    def test_garde_fou_fusion_ecretee_pose_et_retire_les_warnings(self) -> None:
        a = self.app.chantier.arbres[0]
        a.rayon_tronc_cm = 30.0
        # Sondage au Nord : 5 cm de sain (25 d'altéré).
        self.app.pane_s._rows[0]["sain"].set("5")
        # Dégradation 0→50 (couvre le Nord), profondeur 7 : 25 + 7 > 30.
        from unittest.mock import patch as _patch
        with _patch("pane_degradations.edit_degradation", return_value=True):
            self.app.pane_de._on_add()
        self.app.pane_de._row_refs[0]["prof"].set("7")
        self.app._redraw_all()
        self.assertTrue(
            self.app.pane_s._rows[0]["alt"].get().endswith("⚠"))
        self.assertEqual(self.app.pane_de._row_refs[0]["warn"].get(), "⚠")
        # Les bandeaux explicatifs sont affichés dans les 3 onglets.
        self.assertEqual(self.app.pane_s._lbl_fusion.winfo_manager(), "pack")
        self.assertEqual(self.app.pane_de._lbl_fusion.winfo_manager(), "pack")
        self.assertEqual(
            self.app.pane_diag._lbl_fusion.winfo_manager(), "pack")
        # Le diagnostic, lui, écrête sans bloquer : PRBS 0, pas négative.
        from diagnostic import prbs_par_grade
        self.assertEqual(prbs_par_grade(a.brins[0])[0], 0.0)
        # Profondeur ramenée à 2 : la somme tient (27 ≤ 30), ⚠ retirés.
        self.app.pane_de._row_refs[0]["prof"].set("2")
        self.app._redraw_all()
        self.assertFalse(
            self.app.pane_s._rows[0]["alt"].get().endswith("⚠"))
        self.assertEqual(self.app.pane_de._row_refs[0]["warn"].get(), "")
        self.assertEqual(self.app.pane_s._lbl_fusion.winfo_manager(), "")
        self.assertEqual(self.app.pane_de._lbl_fusion.winfo_manager(), "")
        self.assertEqual(self.app.pane_diag._lbl_fusion.winfo_manager(), "")

    def test_degradations_suppression_par_ligne(self) -> None:
        from unittest.mock import patch
        a = self.app.chantier.arbres[0]
        with patch("pane_degradations.edit_degradation", return_value=True):
            self.app.pane_de._on_add()
            self.app.pane_de._on_add()
        deg1 = a.degradations_externes[0]
        self.app.pane_de._on_del(deg1)
        self.assertEqual(len(a.degradations_externes), 1)
        # Renuméroté : la survivante redevient n°1.
        self.assertEqual(a.degradations_externes[0].numero, 1)

    # --- ExportActionsMixin (présence des actions héritées) ---

    def test_actions_export_presentes(self) -> None:
        for name in ("action_export_png", "action_export_pdf_arbre",
                     "action_export_csv", "action_export_synthesis_xlsx",
                     "action_export_prbs_html"):
            self.assertTrue(callable(getattr(self.app, name)))

    # --- RecoveryMixin ---

    def test_restore_recovery_recharge_et_marque_dirty(self) -> None:
        from model import Chantier
        ch = Chantier(nom="Mission récupérée")
        ch.arbres.append(Arbre(numero_arbre="9", essence="Tilleul"))
        self.app._restore_recovery(ch, original=None)
        self.assertEqual(self.app.chantier.nom, "Mission récupérée")
        self.assertEqual(self.app.chantier.arbres[0].numero_arbre, "9")
        self.assertTrue(self.app._dirty)
        self.assertIsNone(self.app.current_file)


@unittest.skipIf(_SKIP_TK, _SKIP_REASON)
class TestAideRepliable(unittest.TestCase):
    """Widget d'aide repliable : replié par défaut, toggle au clic."""

    def setUp(self) -> None:
        from aide_repliable import AideRepliable
        from app_style import apply_ttk_styles
        self.root = tk.Tk()
        apply_ttk_styles(self.root)  # définit Panel.TFrame / Muted.TLabel
        self.aide = AideRepliable(self.root, "Premier conseil.",
                                  "Second conseil.")
        self.root.update_idletasks()

    def tearDown(self) -> None:
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def test_replie_par_defaut(self) -> None:
        # Corps non géré (pack_forget) tant qu'on n'a pas déplié.
        # winfo_manager() == "" => le widget n'est pas packé (≠ ismapped,
        # qui dépend de la fenêtre réellement affichée, fragile en headless).
        self.assertEqual(self.aide._body.winfo_manager(), "")
        self.assertIn("▸", self.aide._header.cget("text"))

    def test_toggle_deplie_puis_replie(self) -> None:
        self.aide.toggle()
        self.assertEqual(self.aide._body.winfo_manager(), "pack")
        self.assertIn("▾", self.aide._header.cget("text"))
        self.aide.toggle()
        self.assertEqual(self.aide._body.winfo_manager(), "")
        self.assertIn("▸", self.aide._header.cget("text"))


@unittest.skipIf(_SKIP_TK, _SKIP_REASON)
class TestSaisieGardeFous(unittest.TestCase):
    """Garde-fous & feedback de la grille de sondages + footer de triage
    (issus de la 2e analyse critique UX). Headless via `App`."""

    def setUp(self) -> None:
        import penetrometre
        self.app = penetrometre.App()
        self.app.update_idletasks()

    def tearDown(self) -> None:
        try:
            self.app.destroy()
        except tk.TclError:
            pass

    # --- Bandeau « rayon d'abord » ------------------------------------

    def test_bandeau_rayon_visible_si_rayon_nul(self) -> None:
        self.app._current_brin().set_rayon(0.0)
        self.app.pane_s.refresh()
        self.assertEqual(self.app.pane_s._lbl_no_radius.winfo_manager(),
                         "pack")

    def test_bandeau_rayon_masque_si_rayon_defini(self) -> None:
        self.app._current_brin().set_rayon(20.0)
        self.app.pane_s.refresh()
        self.assertEqual(self.app.pane_s._lbl_no_radius.winfo_manager(), "")

    # --- Plafonnement bois sain <= rayon (signalé) --------------------

    def test_bois_sain_plafonne_au_rayon_et_signale(self) -> None:
        b = self.app._current_brin()
        b.set_rayon(20.0)
        pane = self.app.pane_s
        pane.refresh()
        pane._on_focus_in(0)
        pane._rows[0]["sain"].set("99")          # clamp dès la frappe
        self.assertEqual(pane._find_sondage(b, 0).bois_sain_cm, 20.0)
        pane._on_focus_out(0)
        self.assertEqual(pane._rows[0]["sain"].get(), "20")  # affichage recalé
        self.assertIn("limité au rayon", self.app.lbl_status.cget("text"))

    # --- Effacement destructeur signalé + undo immédiat ---------------

    def test_effacer_sondage_avec_meta_signale_et_undo_immediat(self) -> None:
        b = self.app._current_brin()
        b.set_rayon(20.0)
        b.sondages.append(Sondage(numero=1, grade=0, bois_sain_cm=12.0,
                                  commentaire="cavité humide"))
        pane = self.app.pane_s
        pane.refresh()
        pane._on_focus_in(0)
        pane._rows[0]["sain"].set("")            # efface => supprime l'objet
        self.assertEqual(len(b.sondages), 0)
        self.assertIn("supprimé", self.app.lbl_status.cget("text"))
        # Undo poussé TOUT DE SUITE (pas au focus-out) :
        self.assertTrue(self.app._undo_stack.can_undo)
        self.app._perform_undo()
        s = pane._find_sondage(self.app._current_brin(), 0)
        self.assertIsNotNone(s)
        self.assertEqual(s.commentaire, "cavité humide")  # commentaire restauré

    def test_effacer_sondage_sans_meta_est_silencieux(self) -> None:
        b = self.app._current_brin()
        b.set_rayon(20.0)
        b.sondages.append(Sondage(numero=1, grade=0, bois_sain_cm=12.0))
        pane = self.app.pane_s
        pane.refresh()
        self.app.set_status("BASE")
        pane._on_focus_in(0)
        pane._rows[0]["sain"].set("")
        self.assertEqual(self.app.lbl_status.cget("text"), "BASE")

    # --- Écho du brin courant (cépée) ---------------------------------

    def test_echo_brin_masque_en_mono_caule(self) -> None:
        self.app._reload_current_views()
        for pane in (self.app.pane_s, self.app.pane_de, self.app.pane_cf):
            self.assertEqual(pane._brin_title.winfo_manager(), "")

    def test_echo_brin_visible_et_suit_le_brin_en_cepee(self) -> None:
        self.app._current_arbre().ajouter_brin()   # brins a, b
        self.app.set_current_brin(1)
        for pane in (self.app.pane_s, self.app.pane_de, self.app.pane_cf):
            self.assertEqual(pane._brin_title.winfo_manager(), "pack")
            self.assertIn("brin b", pane._brin_title.cget("text"))
        self.app.set_current_brin(0)
        self.assertIn("brin a", self.app.pane_s._brin_title.cget("text"))

    # --- Footer de triage ---------------------------------------------

    def test_footer_compte_par_classe_et_a_finir(self) -> None:
        from bareme import CLASSE_ORANGE, CLASSE_ROUGE, CLASSE_VERT
        ch = self.app.chantier  # contient déjà 1 arbre vierge (« à finir »)
        ch.arbres.append(self._fiable("10", 19.0))
        ch.arbres.append(self._fiable("11", 1.0))
        self.app._refresh_tree_arbres()
        txt = self.app.lbl_etat_footer.cget("text")

        # On vérifie que le footer reflète le tally produit par _arbre_etat
        # (sans présumer du classement exact de données synthétiques).
        risques = [self.app._arbre_etat(a)[1] for a in ch.arbres]
        for cls, mot in ((CLASSE_ROUGE, "rouge"), (CLASSE_ORANGE, "orange"),
                         (CLASSE_VERT, "vert")):
            self.assertIn(f"{risques.count(cls)} {mot}", txt)
        n_afinir = sum(1 for r in risques
                       if r not in (CLASSE_ROUGE, CLASSE_ORANGE, CLASSE_VERT))
        self.assertIn(f"{n_afinir} à finir", txt)
        self.assertIn(f"({len(ch.arbres)})", txt)

    # --- « Prochain arbre à finir » (triage) --------------------------

    @staticmethod
    def _fiable(num: str, sain: float = 15.0) -> Arbre:
        """Arbre au diagnostic fiable (rayon + 4 sondages)."""
        a = Arbre(numero_arbre=num, essence="Chêne", port_arbre="libre")
        a.brins[0].set_rayon(20.0)
        for i in range(4):
            a.brins[0].sondages.append(
                Sondage(numero=i + 1, grade=i * 25, bois_sain_cm=sain))
        return a

    def test_next_a_finir_saute_au_prochain_incomplet_en_bouclant(self) -> None:
        self.app.chantier.arbres = [
            Arbre(numero_arbre="0"), self._fiable("1"),
            Arbre(numero_arbre="2"), self._fiable("3")]
        self.app.current_idx = 0
        self.app._refresh_tree_arbres()
        self.app.action_next_a_finir()          # 0 → 2 (prochain incomplet)
        self.assertEqual(self.app.current_idx, 2)
        self.app.action_next_a_finir()          # 2 → 0 (bouclage)
        self.assertEqual(self.app.current_idx, 0)

    def test_next_a_finir_vide_le_filtre_pour_rendre_visible(self) -> None:
        # Filtre risque « Rouge » actif → masquerait l'arbre incomplet.
        from bareme import CLASSE_ROUGE
        self.app.chantier.arbres = [self._fiable("1"), Arbre(numero_arbre="2")]
        self.app.current_idx = 0
        self.app.var_risk_filter.set(CLASSE_ROUGE)
        self.app.action_next_a_finir()
        self.assertEqual(self.app.current_idx, 1)        # a sauté sur l'incomplet
        # Filtre vidé → l'arbre incomplet (iid a1) est de nouveau visible.
        self.assertIn("a1", self.app.tree_arbres.get_children())
        self.assertEqual(self.app.var_risk_filter.get(), "Tous")

    def test_next_a_finir_message_si_tout_fiable(self) -> None:
        self.app.chantier.arbres = [self._fiable("1"), self._fiable("2")]
        self.app.current_idx = 0
        self.app._refresh_tree_arbres()
        self.app.action_next_a_finir()
        self.assertIn("fiable", self.app.lbl_status.cget("text"))
        self.assertEqual(self.app.current_idx, 0)        # pas de saut


@unittest.skipIf(_SKIP_TK, _SKIP_REASON)
class TestComparaisonFenetre(unittest.TestCase):
    """Fenêtre de ré-inspection : sélecteurs **courant + référence** (avant,
    le courant était figé) et persistance des `StringVar` (régression GC :
    locales, elles vidaient le combobox à la sortie de la fonction)."""

    def setUp(self) -> None:
        import penetrometre
        self.app = penetrometre.App()
        self.app.update_idletasks()

    def tearDown(self) -> None:
        try:
            self.app.destroy()
        except tk.TclError:
            pass

    @staticmethod
    def _arbre(num: str, sain: float) -> Arbre:
        a = Arbre(numero_arbre=num, essence="Chêne", port_arbre="libre")
        a.brins[0].set_rayon(20.0)
        for i in range(6):
            a.brins[0].sondages.append(
                Sondage(numero=i + 1, grade=i * 25, bois_sain_cm=sain,
                        bois_altere_cm=20.0 - sain))
        return a

    @staticmethod
    def _combos(dlg: tk.Misc) -> list:
        out: list = []

        def walk(w: tk.Misc) -> None:
            for c in w.winfo_children():
                if c.winfo_class() == "TCombobox":
                    out.append(c)
                walk(c)
        walk(dlg)
        return out

    def test_deux_selecteurs_et_persistance_des_vars(self) -> None:
        import gc

        from comparaison import open_comparison
        from model import Chantier
        cur = Chantier(nom="2026", date_releve="01/01/2026",
                       arbres=[self._arbre("1", 10), self._arbre("2", 6)])
        ref = Chantier(nom="2024", date_releve="01/01/2024",
                       arbres=[self._arbre("1", 12), self._arbre("2", 9)])
        open_comparison(self.app, cur, ref, default_arbre=cur.arbres[1],
                        cur_date="01/01/2026", couleur_classe={},
                        export_cb=lambda *a: None, show_sondages=True)
        gc.collect()           # force le GC : les StringVar doivent survivre
        self.app.update()
        dlg = [w for w in self.app.winfo_children()
               if w.winfo_class() == "Toplevel"][-1]
        combos = self._combos(dlg)
        self.assertEqual(len(combos), 2)         # courant + référence
        # Non vides après GC → les StringVar sont bien retenues.
        self.assertIn("n° 2", combos[0].get())   # courant = défaut (n° 2)
        self.assertIn("n° 2", combos[1].get())   # référence = même n°


if __name__ == "__main__":
    unittest.main()
