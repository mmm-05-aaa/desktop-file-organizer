import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import organizer

class RecoveryEdges(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.base=Path(self.tmp.name)
        self.root=self.base/'desktop'; self.root.mkdir()
        self.patch=mock.patch.multiple(organizer,DESKTOP=self.root,DESTINATION=self.root,STATE_DIR=self.base/'state',LOG_FILE=self.base/'state'/'last_move.json')
        self.patch.start()
        (self.root/'note.txt').write_bytes(b'KEEP')
    def tearDown(self): self.patch.stop(); self.tmp.cleanup()
    def test_persistent_journal_failure_retains_recovery_intent(self):
        plan=organizer.scan(); write=organizer.atomic_write_json; count=0
        def fail_after_rename(path,data):
            nonlocal count
            count+=1
            if count>=3: raise OSError('synthetic full disk')
            return write(path,data)
        with mock.patch.object(organizer,'atomic_write_json',fail_after_rename):
            with self.assertRaises(RuntimeError): organizer.execute(plan)
        self.assertFalse((self.root/'note.txt').exists())
        self.assertEqual(Path(plan[0].target).read_bytes(),b'KEEP')
        data=json.loads(organizer._log_file().read_text())
        self.assertEqual(data['moves'][0]['phase'],'intent')
        self.assertEqual(organizer.undo(),(1,[]))
        self.assertEqual((self.root/'note.txt').read_bytes(),b'KEEP')
    def test_journal_write_single_failure_rolls_back(self):
        plan=organizer.scan(); write=organizer.atomic_write_json; count=0
        def transient(path,data):
            nonlocal count
            count+=1
            if count==3: raise OSError('synthetic transient')
            return write(path,data)
        with mock.patch.object(organizer,'atomic_write_json',transient):
            with self.assertRaises(RuntimeError): organizer.execute(plan)
        self.assertEqual((self.root/'note.txt').read_bytes(),b'KEEP')
        self.assertFalse(Path(plan[0].target).exists())
    def test_entire_journal_is_validated_before_any_undo(self):
        plan=organizer.scan(); organizer.execute(plan)
        data=json.loads(organizer._log_file().read_text())
        outside=self.base/'outside.txt'; outside.write_bytes(b'OUTSIDE')
        bad=dict(data['moves'][0]); bad['source']=str(outside)
        data['moves'].insert(0,bad)
        organizer._log_file().write_text(json.dumps(data))
        before=organizer._log_file().read_bytes()
        with self.assertRaises(RuntimeError): organizer.undo()
        self.assertEqual(outside.read_bytes(),b'OUTSIDE')
        self.assertFalse((self.root/'note.txt').exists())
        self.assertEqual(Path(plan[0].target).read_bytes(),b'KEEP')
        self.assertEqual(organizer._log_file().read_bytes(),before)
    def test_replaced_identical_target_is_not_original_file(self):
        plan=organizer.scan(); organizer.execute(plan)
        target=Path(plan[0].target); old=target.with_suffix('.retained')
        target.rename(old); target.write_bytes(b'KEEP')
        n,w=organizer.undo(); self.assertEqual(n,0); self.assertTrue(w)
        self.assertEqual(target.read_bytes(),b'KEEP'); self.assertEqual(old.read_bytes(),b'KEEP')
    def test_other_process_lock_blocks_execute_and_undo(self):
        script="""import pathlib,organizer,sys
with organizer._exclusive_lock(pathlib.Path(sys.argv[1])):
 print('READY',flush=True)
 sys.stdin.readline()
"""
        proc=subprocess.Popen([sys.executable,'-B','-c',script,str(organizer._log_file())],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            self.assertEqual(proc.stdout.readline().strip(),'READY')
            with self.assertRaises(RuntimeError): organizer.execute(organizer.scan())
            with self.assertRaises(RuntimeError): organizer.undo()
            self.assertEqual((self.root/'note.txt').read_bytes(),b'KEEP')
        finally:
            proc.communicate('\n',timeout=10)
        organizer.execute(organizer.scan()); self.assertEqual(organizer.undo(),(1,[]))
    def test_target_junction_refused(self):
        outside=self.base/'outside'; outside.mkdir()
        link=self.root/'文本'
        result=subprocess.run(['cmd.exe','/d','/c','mklink','/J',str(link),str(outside)],capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        try:
            with self.assertRaises(RuntimeError): organizer.execute(organizer.scan())
            self.assertEqual((self.root/'note.txt').read_bytes(),b'KEEP')
            self.assertEqual(list(outside.iterdir()),[])
        finally: link.rmdir()
    def test_interrupt_during_undo_can_be_reconciled(self):
        organizer.execute(organizer.scan())
        script="""import os,pathlib,organizer,sys
organizer.DESKTOP=pathlib.Path(sys.argv[1]); organizer.STATE_DIR=pathlib.Path(sys.argv[2])
real=os.rename
def die(src,dst):
 real(src,dst); os._exit(24)
os.rename=die
organizer.undo()
"""
        result=subprocess.run([sys.executable,'-B','-c',script,str(self.root),str(self.base/'state')],capture_output=True,timeout=15)
        self.assertEqual(result.returncode,24,result.stderr)
        self.assertEqual((self.root/'note.txt').read_bytes(),b'KEEP')
        self.assertEqual(organizer.undo(),(0,[]))
        self.assertFalse(organizer._log_file().exists())

if __name__=='__main__': unittest.main()
