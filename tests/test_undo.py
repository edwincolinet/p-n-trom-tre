"""Tests de la pile undo/redo."""

from __future__ import annotations

import unittest

from undo import UndoStack


class UndoStackTests(unittest.TestCase):

    def test_undo_vide_renvoie_none(self):
        stack = UndoStack()
        self.assertIsNone(stack.undo())

    def test_redo_vide_renvoie_none(self):
        stack = UndoStack()
        self.assertIsNone(stack.redo())

    def test_push_puis_undo(self):
        stack = UndoStack()
        stack.push({"state": "A"})
        stack.set_live_tip({"state": "B"})
        result = stack.undo()
        self.assertEqual(result, {"state": "A"})

    def test_undo_puis_redo(self):
        stack = UndoStack()
        stack.push({"state": "A"})
        stack.push({"state": "B"})
        # On est à l'état C, on undo → B
        stack.set_live_tip({"state": "C"})
        stack.undo()
        # Redo → C
        result = stack.redo()
        self.assertEqual(result, {"state": "C"})

    def test_push_apres_undo_tronque_redo(self):
        stack = UndoStack()
        stack.push({"state": "A"})
        stack.push({"state": "B"})
        stack.set_live_tip({"state": "C"})
        stack.undo()
        # On push un nouvel état → le redo (C) est perdu
        stack.push({"state": "D"})
        self.assertIsNone(stack.redo())

    def test_clear_vide_la_pile(self):
        stack = UndoStack()
        stack.push({"state": "A"})
        stack.push({"state": "B"})
        stack.clear()
        self.assertFalse(stack.can_undo)
        self.assertFalse(stack.can_redo)

    def test_max_depth(self):
        stack = UndoStack()
        stack._max_depth = 3
        for i in range(10):
            stack.push({"i": i})
        # La pile ne doit pas dépasser max_depth
        self.assertEqual(len(stack._stack), 3)

    def test_can_undo_redo_properties(self):
        stack = UndoStack()
        self.assertFalse(stack.can_undo)
        self.assertFalse(stack.can_redo)
        stack.push({"state": "A"})
        self.assertTrue(stack.can_undo)
        self.assertFalse(stack.can_redo)
        stack.set_live_tip({"state": "B"})
        stack.undo()
        self.assertTrue(stack.can_redo)

    def test_set_live_tip_idempotent(self):
        """set_live_tip n'écrase pas le tip déjà positionné."""
        stack = UndoStack()
        stack.push({"state": "A"})
        stack.set_live_tip({"state": "B"})
        stack.set_live_tip({"state": "OVERWRITE"})  # doit être ignoré
        stack.undo()
        self.assertEqual(stack.redo(), {"state": "B"})

    def test_push_remet_live_tip_a_none(self):
        """Un nouveau push invalide le live_tip (redo path abandonné)."""
        stack = UndoStack()
        stack.push({"state": "A"})
        stack.set_live_tip({"state": "C"})
        stack.undo()
        stack.push({"state": "B"})  # nouvelle mutation
        self.assertIsNone(stack._live_tip)
        self.assertFalse(stack.can_redo)

    def test_undo_multiples_puis_redo_complet(self):
        """Séquence complète : 2 pushes → 2 undos → 2 redos."""
        stack = UndoStack()
        stack.push({"state": "A"})
        stack.push({"state": "B"})
        stack.set_live_tip({"state": "C"})
        # Undo × 2
        r1 = stack.undo()
        self.assertEqual(r1, {"state": "B"})
        r2 = stack.undo()
        self.assertEqual(r2, {"state": "A"})
        self.assertFalse(stack.can_undo)
        # Redo × 2
        r3 = stack.redo()
        self.assertEqual(r3, {"state": "B"})
        r4 = stack.redo()
        self.assertEqual(r4, {"state": "C"})
        self.assertFalse(stack.can_redo)


class UndoIntegrationTests(unittest.TestCase):
    """Vérifie le round-trip undo via chantier_to_dict / chantier_from_dict."""

    def test_undo_restore_sondage_supprime(self):
        from model import Arbre, Chantier, Sondage
        from persistence import chantier_from_dict, chantier_to_dict

        chantier = Chantier(nom="Test")
        arbre = Arbre(rayon_tronc_cm=20.0)
        arbre.sondages.append(Sondage(grade=0, bois_sain_cm=15.0,
                                       bois_altere_cm=5.0))
        arbre.sondages.append(Sondage(grade=100, bois_sain_cm=12.0,
                                       bois_altere_cm=8.0))
        chantier.arbres.append(arbre)

        stack = UndoStack()
        stack.push(chantier_to_dict(chantier))

        # Mutation : supprimer le premier sondage
        del arbre.sondages[0]
        arbre.renumeroter_sondages()
        self.assertEqual(len(arbre.sondages), 1)

        # Undo
        stack.set_live_tip(chantier_to_dict(chantier))
        snapshot = stack.undo()
        self.assertIsNotNone(snapshot)
        restored = chantier_from_dict(snapshot)
        self.assertEqual(len(restored.arbres[0].sondages), 2)
        self.assertEqual(restored.arbres[0].sondages[0].grade, 0)
        self.assertEqual(restored.arbres[0].sondages[1].grade, 100)

    def test_undo_redo_cycle(self):
        from model import Arbre, Chantier, Sondage
        from persistence import chantier_from_dict, chantier_to_dict

        chantier = Chantier(nom="Cycle")
        arbre = Arbre(rayon_tronc_cm=25.0)
        arbre.sondages.append(Sondage(grade=0, bois_sain_cm=20.0,
                                       bois_altere_cm=5.0))
        chantier.arbres.append(arbre)

        stack = UndoStack()
        stack.push(chantier_to_dict(chantier))

        # Mutation
        arbre.sondages[0].bois_sain_cm = 10.0
        arbre.sondages[0].bois_altere_cm = 15.0

        # Undo → état avant mutation
        stack.set_live_tip(chantier_to_dict(chantier))
        before = stack.undo()
        restored = chantier_from_dict(before)
        self.assertAlmostEqual(
            restored.arbres[0].sondages[0].bois_sain_cm, 20.0)

        # Redo → état après mutation
        after = stack.redo()
        re_restored = chantier_from_dict(after)
        self.assertAlmostEqual(
            re_restored.arbres[0].sondages[0].bois_sain_cm, 10.0)


if __name__ == "__main__":
    unittest.main()
