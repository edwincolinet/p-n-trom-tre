"""Tests du registre des exports (type → portée → format) — pur, sans Tk."""

from __future__ import annotations

import unittest

from app_export_actions import ExportActionsMixin
from export_registry import export_types, get_export_type


class ExportRegistryTests(unittest.TestCase):

    def test_cles_de_type_uniques(self) -> None:
        cles = [t.key for t in export_types()]
        self.assertEqual(len(cles), len(set(cles)))

    def test_chaque_format_designe_une_action_existante(self) -> None:
        """Un format du registre ⟹ une méthode `action_export_*` réelle."""
        for t in export_types():
            for sc in t.scopes:
                for f in sc.formats:
                    self.assertTrue(
                        callable(getattr(ExportActionsMixin, f.action, None)),
                        f"{t.key}/{sc.key}/{f.key} → {f.action} introuvable")

    def test_pas_de_doublon_portee_format_dans_un_type(self) -> None:
        for t in export_types():
            vus = [(sc.key, f.key) for sc in t.scopes for f in sc.formats]
            self.assertEqual(len(vus), len(set(vus)), t.key)

    def test_toutes_les_actions_de_la_mixin_sont_au_registre(self) -> None:
        """Aucun export ne doit disparaître du menu en silence."""
        au_registre = {f.action for t in export_types()
                       for sc in t.scopes for f in sc.formats}
        dans_mixin = {n for n in vars(ExportActionsMixin)
                      if n.startswith("action_export_")
                      and n != "action_export_choose"}
        self.assertEqual(au_registre, dans_mixin)

    def test_needs_dialog(self) -> None:
        fiche = get_export_type("fiche")
        sondages = get_export_type("sondages")
        assert fiche is not None and sondages is not None
        self.assertTrue(fiche.needs_dialog)        # arbre / mission
        self.assertFalse(sondages.needs_dialog)    # un seul choix possible

    def test_resolution_portee_format(self) -> None:
        t = get_export_type("tableau_prbs")
        assert t is not None
        f = t.format("arbre", "html")
        assert f is not None
        self.assertEqual(f.action, "action_export_prbs_html")
        self.assertIsNone(t.format("arbre", "inconnu"))
        self.assertIsNone(t.format("inconnue", "html"))

    def test_choix_par_defaut_valide(self) -> None:
        for t in export_types():
            self.assertIsNotNone(t.format(*t.default_choice()), t.key)

    def test_comparaison_dependante_d_une_comparaison_ouverte(self) -> None:
        t = get_export_type("comparaison")
        assert t is not None
        self.assertTrue(t.needs_comparison)


if __name__ == "__main__":
    unittest.main()
