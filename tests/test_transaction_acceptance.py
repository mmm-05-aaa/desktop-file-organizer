import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import organizer

class TransactionAcceptance(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / 'desktop'; self.root.mkdir()
        self.patch = mock.patch.multiple(organizer, DESKTOP=self.root, DESTINATION=self.root,
            STATE_DIR=self.base/'state', LOG_FILE=self.base/'state'/'last_move.json')
        self.patch.start()
    def tearDown(self):
        self.patch.stop(); self.tmp.cleanup()
    def test_second_execute_cannot_destroy_unresolved_journal(self):
        a=self.root/'a.txt'; a.write_bytes(b'A')
        first=organizer.scan(); organizer.execute(first)
        data=json.loads(organizer._log_file().read_text())
        data['status']='recovery-required'
        organizer._log_file().write_text(json.dumps(data))
        before=organizer._log_file().read_bytes()
        b=self.root/'b.txt'; b.write_bytes(b'B')
        with self.assertRaises(RuntimeError): organizer.execute(organizer.scan())
        self.assertEqual(organizer._log_file().read_bytes(),before)
        self.assertTrue(b.exists())
        self.assertEqual(organizer.undo(),(1,[])); self.assertEqual(a.read_bytes(),b'A')
    def test_successive_transactions_keep_both_undo_records(self):
        a=self.root/'a.txt'; a.write_bytes(b'A')
        organizer.execute(organizer.scan())
        b=self.root/'b.txt'; b.write_bytes(b'B')
        organizer.execute(organizer.scan())
        self.assertEqual(organizer.undo(),(1,[]))
        self.assertEqual(b.read_bytes(),b'B'); self.assertFalse(a.exists())
        self.assertEqual(organizer.undo(),(1,[]))
        self.assertEqual(a.read_bytes(),b'A')
    def test_dotdot_outside_target_rejected(self):
        s=self.root/'a.txt'; s.write_bytes(b'A'); r=organizer.scan()[0]
        r.target=str(self.root/'..'/'outside.txt')
        with self.assertRaises(RuntimeError): organizer.execute([r])
        self.assertEqual(s.read_bytes(),b'A'); self.assertFalse((self.base/'outside.txt').exists())
    def test_move_failure_rolls_back_prior_moves(self):
        for name in ['a.txt','b.txt']: (self.root/name).write_text(name)
        records=organizer.scan(); rename=organizer._rename_no_replace
        def fail_second(src,dst,*args,**kwargs):
            if Path(src)==self.root/'b.txt': raise PermissionError('synthetic locked file')
            return rename(src,dst,*args,**kwargs)
        with mock.patch.object(organizer,'_rename_no_replace',fail_second):
            with self.assertRaises(RuntimeError): organizer.execute(records)
        for name in ['a.txt','b.txt']: self.assertEqual((self.root/name).read_text(),name)
    def test_interrupted_move_is_recoverable_in_new_process(self):
        s=self.root/'a.txt'; s.write_bytes(b'A')
        script="""import os,pathlib,organizer
organizer.DESKTOP=pathlib.Path(os.environ['TEST_ROOT'])
organizer.STATE_DIR=pathlib.Path(os.environ['TEST_STATE'])
original=organizer._rename_no_replace
def interrupt(src,dst,*args,**kwargs):
 original(src,dst,*args,**kwargs)
 os._exit(23)
organizer._rename_no_replace=interrupt
organizer.execute(organizer.scan())
"""
        env=os.environ.copy(); env['TEST_ROOT']=str(self.root); env['TEST_STATE']=str(self.base/'state')
        result=subprocess.run([sys.executable,'-B','-c',script],env=env,capture_output=True,timeout=15)
        self.assertEqual(result.returncode,23,result.stderr)
        self.assertEqual(organizer.undo(),(1,[]))
        self.assertEqual(s.read_bytes(),b'A')
        # Crash released the OS-owned lock: another transaction can proceed.
        organizer.execute(organizer.scan()); self.assertEqual(organizer.undo(),(1,[]))

if __name__=='__main__': unittest.main()
