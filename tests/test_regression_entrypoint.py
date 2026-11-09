# SPDX-License-Identifier: GPL-3.0-or-later
"""Keep assertion-disabled Python from producing a false successful report."""
from pathlib import Path
import os
import subprocess
import sys
import unittest


HARNESS = Path(__file__).resolve().with_name("background_regression.py")


class EntrypointTests(unittest.TestCase):
    def test_optimized_python_is_rejected_before_loading_blender(self):
        for flag in ("-O", "-OO"):
            with self.subTest(flag=flag):
                result = subprocess.run([sys.executable, flag, "-B", str(HARNESS), "--help"],
                                        capture_output=True, text=True, timeout=15)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Regression assertions require", result.stderr)

    def test_normal_help_does_not_require_blender(self):
        env = dict(os.environ)
        env.pop("PYTHONOPTIMIZE", None)
        result = subprocess.run([sys.executable, "-B", str(HARNESS), "--help"],
                                capture_output=True, text=True, timeout=15, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--addon", result.stdout)


if __name__ == "__main__":
    unittest.main()
