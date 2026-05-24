"""Tests de la pile undo/redo."""

from __future__ import annotations

import unittest

from undo import UndoStack


class UndoStackTests(unittest.TestCase):

    def test_undo_vide_renvoie_none(self):
        stack = UndoStack()
        self.assertIsNone(stack.undo({"current": True}))

    def test_redo_vide_renvoie_none(self):
        stack = UndoStack()
        self.assertIsNone(stack.redo())

    def test_push_puis_undo(self):
        stack = UndoStack()
        stack.push({"state": "A"})
        result = stack.undo({"state": "B"})
        self.assertEqual(result, {"state": "A"})

    def test_undo_puis_redo(self):
        stack = UndoStack()
        stack.push({"state": "A"})
        stack.push({"state": "B"})
        # On est à l'état C, on undo → B
        stack.undo({"state": "C"})
        # Redo → C
        result = stack.redo()
        self.assertEqual(result, {"state": "C"})

    def test_push_apres_undo_tronque_redo(self):
        stack = UndoStack()
        stack.push({"state": "A"})
        stack.push({"state": "B"})
        stack.undo({"state": "C"})
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
        stack.undo({"state": "B"})
        self.assertTrue(stack.can_redo)


if __name__ == "__main__":
    unittest.main()
