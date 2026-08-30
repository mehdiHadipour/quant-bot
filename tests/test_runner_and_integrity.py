import os
import subprocess
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class RunnerIntegrityTests(unittest.TestCase):
    def test_backtest_runner_from_root(self):
        p = subprocess.run([sys.executable, str(ROOT/'scripts'/'run_backtest.py')], cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout + '\n' + p.stderr)
        self.assertIn('=== V30 RESULT ===', p.stdout)

    def test_main_import_is_dependency_clear(self):
        p = subprocess.run([sys.executable, '-c', 'import main; print("OK")'], cwd=ROOT, capture_output=True, text=True)
        # If optional runtime deps are missing in a minimal environment, report that clearly rather than masking it.
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_android_scripts_exist(self):
        self.assertTrue((ROOT/'android'/'setup_termux.sh').exists())
        self.assertTrue((ROOT/'android'/'run_termux.sh').exists())

if __name__ == '__main__':
    unittest.main()
