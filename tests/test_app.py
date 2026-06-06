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
        self.assertEqual(self.etat(self._arbre(0.0, 5))[1], "etat_vide")

    def test_sans_sondage_est_vide(self) -> None:
        self.assertEqual(self.etat(self._arbre(20.0, 0))[1], "etat_vide")

    def test_un_ou_deux_sondages_partiel(self) -> None:
        self.assertEqual(self.etat(self._arbre(20.0, 1))[1], "etat_partiel")
        self.assertEqual(self.etat(self._arbre(20.0, 2))[1], "etat_partiel")

    def test_trois_sondages_fiable_colore_par_classe(self) -> None:
        # Seuil métier : >= 3 directions => diagnostic fiable. La couleur
        # du `●` encode alors la classe de risque globale.
        # Tronc sain (PRBS = rayon → t/R = 1.0) => classe Vert.
        self.assertEqual(self.etat(self._arbre(20.0, 3))[1], "etat_ok_vert")
        # Tronc très dégradé (PRBS = 1 cm sur 20 → t/R ≈ 5 %) => Rouge.
        self.assertEqual(
            self.etat(self._arbre(20.0, 3, sain=1.0))[1], "etat_ok_rouge")

    def test_glyphes_distincts_par_completude(self) -> None:
        # La forme (pas seulement la couleur) distingue les 3 états :
        # accessible en cas de daltonisme rouge-vert.
        self.assertEqual(self.etat(self._arbre(0.0, 0))[0], "○")
        self.assertEqual(self.etat(self._arbre(20.0, 1))[0], "◐")
        self.assertEqual(self.etat(self._arbre(20.0, 3))[0], "●")


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

    def test_dup_arbre_suffixe_bis(self) -> None:
        self.app.chantier.arbres[0].numero_arbre = "5"
        self.app.action_dup_arbre()
        self.assertEqual(len(self.app.chantier.arbres), 2)
        self.assertEqual(self.app.chantier.arbres[1].numero_arbre, "5 bis")

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


if __name__ == "__main__":
    unittest.main()
