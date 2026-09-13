import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

os.environ.setdefault('DESKTOP_ORGANIZER_ROOT', str(Path(tempfile.gettempdir()).resolve()))
import organizer


class LinuxSupportTests(unittest.TestCase):
    def test_smoke_mode_opens_and_closes_application(self):
        app = mock.Mock()
        with mock.patch.object(organizer, 'App', return_value=app):
            self.assertEqual(organizer.main(['--smoke-test']), 0)
        app.after_idle.assert_called_once_with(app.destroy)
        app.mainloop.assert_called_once_with()

    def test_posix_root_ids_preserve_case(self):
        self.assertNotEqual(
            organizer._root_key('CaseRoot', platform_name='posix'),
            organizer._root_key('caseroot', platform_name='posix'))
        self.assertEqual(
            organizer._root_key('CaseRoot', platform_name='nt'),
            organizer._root_key('caseroot', platform_name='nt'))

    def test_posix_desktop_expands_xdg_home(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            desktop = home / 'Desk'
            desktop.mkdir()
            config = home / '.config'
            config.mkdir()
            (config / 'user-dirs.dirs').write_text(
                'XDG_DESKTOP_DIR="$HOME/Desk"\n', encoding='utf-8')
            self.assertEqual(
                organizer._posix_desktop({'HOME': str(home)}, home), desktop)

    def test_posix_desktop_requires_existing_directory(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            with self.assertRaises(RuntimeError):
                organizer._posix_desktop({'HOME': str(home)}, home)

    @unittest.skipUnless(os.name == 'posix', 'POSIX move semantics')
    def test_no_replace_move_preserves_competing_target(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source, target = root / 'source.txt', root / 'target.txt'
            source.write_text('source', encoding='utf-8')
            target.write_text('competitor', encoding='utf-8')
            with self.assertRaises(FileExistsError):
                organizer._rename_no_replace(source, target)
            self.assertEqual(source.read_text(encoding='utf-8'), 'source')
            self.assertEqual(target.read_text(encoding='utf-8'), 'competitor')


if __name__ == '__main__':
    unittest.main()
