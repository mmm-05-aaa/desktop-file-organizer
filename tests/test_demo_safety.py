import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
RESET = PROJECT / "reset_demo.py"


class DemoResetSafetyTests(unittest.TestCase):
    def run_reset(self, root):
        return subprocess.run(
            [sys.executable, str(RESET), "--root", str(root)],
            text=True, capture_output=True, check=False,
        )

    def test_creates_known_files_and_keeps_unknown_and_modified(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "demo data"
            root.mkdir()
            (root / "unknown.txt").write_text("user file", encoding="utf-8")
            (root / "demo-page.html").write_text("user edit", encoding="utf-8")
            result = self.run_reset(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root / "unknown.txt").read_text(), "user file")
            self.assertEqual((root / "demo-page.html").read_text(), "user edit")
            self.assertIn("preserved", result.stdout.lower())
            self.assertTrue((root / "student-budget.csv").exists())

    def test_does_not_delete_unknown_directory_or_generated_subtree(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "data"
            root.mkdir()
            unknown = root / "文本"
            unknown.mkdir()
            (unknown / "user.txt").write_text("keep", encoding="utf-8")
            result = self.run_reset(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((unknown / "user.txt").read_text(), "keep")
            self.assertTrue(unknown.exists())

    def test_symlink_root_and_entry_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            outside = base / "outside"
            outside.mkdir()
            (outside / "sentinel.txt").write_text("do not touch", encoding="utf-8")
            root = base / "root"
            try:
                root.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            result = self.run_reset(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((outside / "sentinel.txt").read_text(), "do not touch")

            root.unlink()
            root.mkdir()
            outside_file = outside / "escape.txt"
            outside_file.write_text("safe", encoding="utf-8")
            (root / "demo-page.html").symlink_to(outside_file)
            result = self.run_reset(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(outside_file.read_text(), "safe")

    def test_creation_race_preserves_competing_file(self):
        spec = importlib.util.spec_from_file_location("reset_demo_isolated", RESET)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "race data"
            root.mkdir()
            original_open = Path.open
            raced = False
            def racing_open(path, *args, **kwargs):
                nonlocal raced
                if path.name == "demo-page.html" and not raced and "x" in (args[0] if args else kwargs.get("mode", "r")):
                    raced = True
                    path.write_text("competitor", encoding="utf-8")
                return original_open(path, *args, **kwargs)
            with mock.patch.object(Path, "open", racing_open):
                created, preserved = module.reset_demo(root)
            self.assertNotIn("demo-page.html", created)
            self.assertIn("demo-page.html (creation race conflict)", preserved)
            self.assertEqual((root / "demo-page.html").read_text(encoding="utf-8"), "competitor")

    @unittest.skipUnless(os.name == "nt", "junctions are Windows-only")
    def test_existing_ancestor_junction_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            outside = base / "outside"
            outside.mkdir()
            link_parent = base / "junction parent"
            result = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(link_parent), str(outside)], capture_output=True, text=True, encoding="mbcs", errors="replace")
            if result.returncode != 0:
                self.skipTest("junction creation unavailable")
            result = self.run_reset(link_parent / "child")
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((outside / "student-budget.csv").exists())
    def test_import_has_no_side_effect(self):
        with tempfile.TemporaryDirectory() as td:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(PROJECT)
            result = subprocess.run(
                [sys.executable, "-c", "import reset_demo"],
                cwd=td, env=env, text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(Path(td).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
