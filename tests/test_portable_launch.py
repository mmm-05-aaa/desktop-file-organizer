import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import venv

PROJECT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(os.name=='nt','Windows BAT')
class PortableLaunchAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(); cls.base=Path(cls.tmp.name).resolve()
        cls.envroot=cls.base/'解释器 space'
        venv.EnvBuilder(with_pip=False).create(cls.envroot)
        cls.python=cls.envroot/'Scripts'/'python.exe'
    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()
    def check_launcher(self,batch,script,explicit):
        with tempfile.TemporaryDirectory(dir=self.base) as td:
            app=Path(td)/'软件 space'; app.mkdir()
            (app/batch).write_bytes((PROJECT/batch).read_bytes())
            (app/script).write_text("from pathlib import Path\nimport os,sys\np=Path(__file__).parent/'count.txt'\np.write_text((p.read_text() if p.exists() else '')+'RUN\\n')\n(Path(__file__).parent/'args.txt').write_text(repr(sys.argv))\nsys.exit(7)\n",encoding='utf-8')
            env=os.environ.copy(); env.pop('DESKTOP_ORGANIZER_PYTHON',None)
            env['PATH']=str(self.python.parent)+os.pathsep+str(Path(os.environ['SystemRoot'])/'System32')
            if explicit: env['DESKTOP_ORGANIZER_PYTHON']=str(self.python)
            result=subprocess.run([os.environ.get('COMSPEC','cmd.exe'),'/d','/c','call',str(app/batch)],env=env,capture_output=True,timeout=20)
            self.assertTrue((app/'count.txt').exists(),repr(result.stdout)+repr(result.stderr))
            self.assertEqual((app/'count.txt').read_text(),'RUN\n')
            self.assertEqual(result.returncode,7,repr(result.stdout)+repr(result.stderr))
    def test_explicit_spaced_executable_run_returns_app_failure_once(self): self.check_launcher('run_demo.bat','organizer.py',True)
    def test_explicit_spaced_executable_reset_returns_app_failure_once(self): self.check_launcher('reset_demo.bat','reset_demo.py',True)
    def test_python_without_py_launcher_has_no_minus3(self): self.check_launcher('run_demo.bat','organizer.py',False)
    def test_python_reset_without_py_launcher_has_no_minus3(self): self.check_launcher('reset_demo.bat','reset_demo.py',False)

if __name__=='__main__': unittest.main()
