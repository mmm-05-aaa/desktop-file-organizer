import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock
import organizer

@unittest.skipUnless(os.name == 'nt', 'Windows Tk application')
class GuiSafety(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); base=Path(self.tmp.name)
        self.root=base/'desktop'; self.root.mkdir(); (self.root/'notes.txt').write_bytes(b'GUI')
        self.settings=mock.patch.multiple(organizer,DESKTOP=self.root,DESTINATION=self.root,STATE_DIR=base/'state',LOG_FILE=base/'state'/'last_move.json')
        self.settings.start()
        self.dialogs=[mock.patch.object(organizer.messagebox,name,return_value=True) for name in ('showerror','showinfo','showwarning','askyesno')]
        for patch in self.dialogs: patch.start()
        self.app=organizer.App(); self.app.withdraw(); self.wait_idle()
    def wait_idle(self):
        deadline=time.monotonic()+5
        while self.app.busy and time.monotonic()<deadline:
            self.app.update(); time.sleep(.02)
        self.app.update(); self.assertFalse(self.app.busy,'GUI operation timeout')
    def tearDown(self):
        self.wait_idle(); self.app.destroy(); self.app = None
        import gc
        gc.collect()
        for patch in reversed(self.dialogs): patch.stop()
        self.settings.stop(); self.tmp.cleanup()
    def test_tree_preserves_category_branches_and_score_label(self):
        node=self.app.tree.get_children()[0]
        branches=self.app.tree.get_children(node)
        self.assertTrue(any('文本' in self.app.tree.item(b,'text') for b in branches))
        self.assertEqual(self.app.tree.heading('confidence','text'),'规则匹配分')
    def test_confirmation_cancel_never_moves(self):
        organizer.messagebox.askyesno.return_value=False
        self.app.organize(); self.wait_idle()
        self.assertTrue((self.root/'notes.txt').exists())
    def test_execute_uses_preview_snapshot_and_undo_refreshes(self):
        (self.root/'late.txt').write_bytes(b'LATE')
        self.app.organize(); self.wait_idle()
        self.assertFalse((self.root/'notes.txt').exists()); self.assertTrue((self.root/'late.txt').exists())
        self.app.restore(); self.wait_idle()
        self.assertEqual((self.root/'notes.txt').read_bytes(),b'GUI')
        self.assertEqual({Path(r.source).name for r in self.app.records},{'notes.txt','late.txt'})
    def test_scan_error_discards_stale_executable_preview(self):
        with mock.patch.object(organizer,'scan',side_effect=PermissionError('synthetic')):
            self.app.refresh(); self.wait_idle()
        self.assertEqual(self.app.records,[])
        self.assertTrue((self.root/'notes.txt').exists())

if __name__=='__main__': unittest.main()
