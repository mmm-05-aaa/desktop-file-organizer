import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import organizer

class ClassificationAndPaths(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows known-folder API')
    def test_redirected_known_folder_is_used(self):
        self.assertTrue(hasattr(organizer,'get_desktop_path'))
        with tempfile.TemporaryDirectory() as td:
            redirected=Path(td)
            with mock.patch.object(organizer,'_windows_desktop',return_value=redirected):
                self.assertEqual(organizer.get_desktop_path({}),redirected)
    def test_invalid_explicit_override_is_rejected(self):
        self.assertTrue(hasattr(organizer,'get_desktop_path'))
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(RuntimeError):
                organizer.get_desktop_path({'DESKTOP_ORGANIZER_ROOT':str(Path(td)/'missing')})
    def test_readable_generic_pdf_can_be_organized_as_document(self):
        with mock.patch.object(organizer,'pdf_text',return_value=('invoice total payment', '')):
            category,score,reason,warning=organizer.paper_category(Path('invoice.pdf'))
        self.assertEqual(category,'文档'); self.assertGreaterEqual(score,70); self.assertFalse(warning)
    def test_tied_paper_rules_are_not_high_score_executable(self):
        with mock.patch.object(organizer,'pdf_text',return_value=('peptide bioinformatics', '')):
            category,score,reason,warning=organizer.paper_category(Path('paper.pdf'))
        self.assertTrue(score<70 or bool(warning))
    def test_state_root_named_dotstate_is_still_root_isolated(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td); a=base/'a'; b=base/'b'; a.mkdir(); b.mkdir()
            with mock.patch.multiple(organizer,STATE_DIR=base/'.state',LOG_FILE=base/'.state'/'last_move.json',DESKTOP=a):
                first=organizer._log_file()
                with mock.patch.object(organizer,'DESKTOP',b): second=organizer._log_file()
                self.assertNotEqual(first,second)

if __name__=='__main__': unittest.main()
