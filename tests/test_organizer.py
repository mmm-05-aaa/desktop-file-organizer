import json
import tempfile
import unittest
from pathlib import Path

import organizer


class OrganizerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old = (organizer.DESKTOP, organizer.DESTINATION, organizer.STATE_DIR, organizer.LOG_FILE)
        organizer.DESKTOP = self.root
        organizer.DESTINATION = self.root
        organizer.STATE_DIR = self.root / ".state"
        organizer.LOG_FILE = organizer.STATE_DIR / "last_move.json"

    def tearDown(self):
        organizer.DESKTOP, organizer.DESTINATION, organizer.STATE_DIR, organizer.LOG_FILE = self.old
        self.tmp.cleanup()

    def test_records_and_journal_store_only_required_file_metadata(self):
        source = self.root / "notes.txt"
        source.write_text("notes", encoding="utf-8")
        records = organizer.scan()
        self.assertTrue(records)
        self.assertEqual(set(records[0].__dict__), {"source", "target", "category", "confidence", "reason", "warning", "size", "mtime_ns"})
        journal = organizer.execute(records)
        self.assertEqual(set(journal["moves"][0]), {"source", "target", "category", "confidence", "reason", "warning", "size", "mtime_ns", "identity", "phase"})

    def test_html_is_classified_as_webpage(self):
        (self.root / "demo.html").write_text("<h1>demo</h1>", encoding="utf-8")
        record = organizer.scan()[0]
        self.assertEqual(record.category, "网页")
        self.assertEqual(record.confidence, 92)

    def test_invalid_pdf_is_retained_with_warning(self):
        (self.root / "broken.pdf").write_bytes(b"<!DOCTYPE html>")
        record = organizer.scan()[0]
        self.assertTrue(record.warning)
        self.assertEqual(record.category, "论文-待确认")

    def test_shortcuts_and_folders_are_excluded(self):
        (self.root / "tool.exe").write_bytes(b"x")
        (self.root / "shortcut.lnk").write_bytes(b"x")
        (self.root / "existing").mkdir()
        self.assertEqual(organizer.scan(), [])

    def test_execute_and_undo_round_trip(self):
        source = self.root / "notes.txt"
        source.write_text("hello", encoding="utf-8")
        record = organizer.scan()[0]
        result = organizer.execute([record])
        self.assertEqual(len(result["moves"]), 1)
        self.assertFalse(source.exists())
        self.assertTrue(Path(record.target).exists())
        restored, warnings = organizer.undo()
        self.assertEqual((restored, warnings), (1, []))
        self.assertTrue(source.exists())

    def test_changed_source_is_rejected(self):
        source = self.root / "notes.txt"
        source.write_text("hello", encoding="utf-8")
        record = organizer.scan()[0]
        source.write_text("changed", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            organizer.execute([record])
        self.assertTrue(source.exists())

    def test_existing_target_is_not_overwritten(self):
        source = self.root / "notes.txt"
        source.write_text("hello", encoding="utf-8")
        record = organizer.scan()[0]
        Path(record.target).parent.mkdir(parents=True, exist_ok=True)
        Path(record.target).write_text("existing", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            organizer.execute([record])
        self.assertEqual(Path(record.target).read_text(encoding="utf-8"), "existing")

    def test_undo_rejects_equal_length_tail_modification(self):
        source = self.root / "notes.txt"
        source.write_bytes(b"a" * 65536 + b"original-tail")
        record = organizer.scan()[0]
        organizer.execute([record])
        Path(record.target).write_bytes(b"a" * 65536 + b"MODIFIED-tail")
        restored, warnings = organizer.undo()
        self.assertEqual(restored, 0)
        self.assertTrue(warnings)

    def test_journal_exists_before_first_move_and_state_is_recoverable(self):
        source = self.root / "notes.txt"
        source.write_text("hello", encoding="utf-8")
        record = organizer.scan()[0]
        original = organizer.atomic_write_json
        seen = []
        def fail_after_journal(path, payload):
            seen.append(path)
            raise OSError("simulated journal failure")
        organizer.atomic_write_json = fail_after_journal
        try:
            with self.assertRaises(OSError):
                organizer.execute([record])
        finally:
            organizer.atomic_write_json = original
        self.assertTrue(source.exists())
        self.assertFalse(organizer._log_file().exists())
        self.assertTrue(seen)

    def test_partial_undo_removes_restored_record(self):
        first = self.root / "a.txt"; second = self.root / "b.txt"
        first.write_text("a", encoding="utf-8"); second.write_text("b", encoding="utf-8")
        records = organizer.scan(); organizer.execute(records)
        Path(records[0].target).write_text("changed", encoding="utf-8")
        restored, warnings = organizer.undo()
        self.assertEqual(restored, 1); self.assertTrue(warnings)
        data = json.loads(organizer._log_file().read_text(encoding="utf-8"))
        self.assertEqual(len(data["moves"]), 1)

    def test_undo_rejects_modified_target(self):
        source = self.root / "notes.txt"
        source.write_text("hello", encoding="utf-8")
        record = organizer.scan()[0]
        organizer.execute([record])
        Path(record.target).write_text("modified", encoding="utf-8")
        restored, warnings = organizer.undo()
        self.assertEqual(restored, 0)
        self.assertTrue(warnings)
        self.assertFalse(source.exists())


if __name__ == "__main__":
    unittest.main()