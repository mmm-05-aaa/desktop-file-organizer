import dataclasses
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import organizer

class CoreSafety(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name) / 'root'; self.root.mkdir()
        self.patch = mock.patch.multiple(organizer, DESKTOP=self.root, DESTINATION=self.root, STATE_DIR=Path(self.tmp.name)/'state', LOG_FILE=Path(self.tmp.name)/'state'/'last_move.json'); self.patch.start()
    def tearDown(self): self.patch.stop(); self.tmp.cleanup()
    def test_outside_target_rejected(self):
        source=self.root/'a.txt'; source.write_bytes(b'a'); record=dataclasses.replace(organizer.scan()[0], target=str(Path(self.tmp.name)/'outside.txt'))
        with self.assertRaises(RuntimeError): organizer.execute([record])
        self.assertTrue(source.exists())
    def test_equal_length_tail_is_detected(self):
        source=self.root/'a.txt'; source.write_bytes(b'x'*70000+b'original'); record=organizer.scan()[0]; organizer.execute([record]); Path(record.target).write_bytes(b'x'*70000+b'MODIFIED')
        restored,warnings=organizer.undo(); self.assertEqual(restored,0); self.assertTrue(warnings)
    def test_target_collision_is_not_overwritten(self):
        source=self.root/'a.txt'; source.write_bytes(b'source'); record=organizer.scan()[0]; Path(record.target).parent.mkdir(parents=True); Path(record.target).write_bytes(b'keep')
        with self.assertRaises(RuntimeError): organizer.execute([record])
        self.assertEqual(Path(record.target).read_bytes(),b'keep')

if __name__ == '__main__': unittest.main()
