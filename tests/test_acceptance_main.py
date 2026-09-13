"""Supervisor-owned acceptance tests, always isolated from real Desktop/state."""
import dataclasses
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import organizer


class SupervisorAcceptance(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / 'desktop'
        self.root.mkdir()
        self.settings = mock.patch.multiple(
            organizer, DESKTOP=self.root, DESTINATION=self.root,
            STATE_DIR=self.base / 'appstate',
            LOG_FILE=self.base / 'appstate' / 'last_move.json')
        self.settings.start()

    def tearDown(self):
        self.settings.stop()
        self.temp.cleanup()

    def test_equal_size_tail_change_must_not_be_undone(self):
        source = self.root / 'long.txt'
        original = b'A' * 70000 + b'original'
        modified = b'A' * 70000 + b'MODIFIED'
        self.assertEqual(len(original), len(modified))
        source.write_bytes(original)
        plan = organizer.scan()
        organizer.execute(plan)
        target = Path(plan[0].target)
        target.write_bytes(modified)
        count, warnings = organizer.undo()
        self.assertEqual(count, 0)
        self.assertTrue(warnings)
        self.assertFalse(source.exists())
        self.assertEqual(target.read_bytes(), modified)

    def test_target_appearing_after_validation_is_never_overwritten(self):
        source = self.root / 'notes.txt'
        source.write_bytes(b'SOURCE')
        plan = organizer.scan()
        target = Path(plan[0].target)
        original_rename = organizer._rename_no_replace
        calls = []

        def competing_operation(src, dst):
            if Path(src) == source and Path(dst) == target:
                calls.append(True)
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    target.write_bytes(b'COMPETITOR')
            return original_rename(src, dst)

        with mock.patch.object(organizer, '_rename_no_replace', competing_operation):
            with self.assertRaises(Exception):
                organizer.execute(plan)
        self.assertTrue(calls, 'Update fault injection if the move primitive changes')
        self.assertEqual(target.read_bytes(), b'COMPETITOR')
        self.assertEqual(source.read_bytes(), b'SOURCE')

    def test_target_outside_root_is_rejected_without_side_effects(self):
        source = self.root / 'notes.txt'
        source.write_bytes(b'SOURCE')
        outside = self.base / 'outside.txt'
        record = dataclasses.replace(organizer.scan()[0], target=str(outside))
        with self.assertRaises(Exception):
            organizer.execute([record])
        self.assertFalse(outside.exists())
        self.assertEqual(source.read_bytes(), b'SOURCE')

    def test_other_root_cannot_undo_first_roots_transaction(self):
        source = self.root / 'notes.txt'
        source.write_bytes(b'SOURCE')
        plan = organizer.scan()
        organizer.execute(plan)
        other = self.base / 'other'
        other.mkdir()
        with mock.patch.multiple(organizer, DESKTOP=other, DESTINATION=other):
            count, warnings = organizer.undo()
            self.assertEqual(count, 0)
        self.assertFalse(source.exists())
        self.assertEqual(Path(plan[0].target).read_bytes(), b'SOURCE')
        count, warnings = organizer.undo()
        self.assertEqual((count, warnings), (1, []))
        self.assertEqual(source.read_bytes(), b'SOURCE')

    def test_partial_undo_can_finish_after_user_resolves_conflict(self):
        a = self.root / 'a.txt'
        b = self.root / 'b.txt'
        a.write_bytes(b'A')
        b.write_bytes(b'B')
        plan = organizer.scan()
        organizer.execute(plan)
        a.write_bytes(b'USER-CONFLICT')
        count, warnings = organizer.undo()
        self.assertEqual(count, 1)
        self.assertTrue(warnings)
        self.assertEqual(a.read_bytes(), b'USER-CONFLICT')
        self.assertEqual(b.read_bytes(), b'B')
        a.unlink()  # Synthetic user explicitly resolves their own conflict.
        count, warnings = organizer.undo()
        self.assertEqual((count, warnings), (1, []))
        self.assertEqual(a.read_bytes(), b'A')
        self.assertEqual(b.read_bytes(), b'B')


if __name__ == '__main__':
    unittest.main()
