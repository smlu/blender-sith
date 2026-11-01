# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise launcher subprocesses without requiring Blender or commercial assets."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest


SOURCE = Path(__file__).resolve().parents[1]
LAUNCHER = SOURCE / "scripts" / "run_regression.py"
FAKE_BPY = '''from types import SimpleNamespace as NS
app = NS(background=True, version_string="5.1.2")
scene = NS(render=NS(threads_mode="AUTO", threads=0))
data = NS(scenes=[scene])
context = NS(scene=scene)
ops = NS(wm=NS(read_factory_settings=lambda **kwargs: None))
'''
HARNESS = '''import argparse, hashlib, json, os, subprocess, sys, time
from pathlib import Path
import bpy
p=argparse.ArgumentParser()
p.add_argument("--output", type=Path, required=True)
p.add_argument("--addon", type=Path, required=True)
a=p.parse_args()
a.output.mkdir()
hashes={str(f.relative_to(a.addon)).replace(chr(92),"/"):hashlib.sha256(f.read_bytes()).hexdigest()
        for f in sorted(a.addon.rglob("*")) if f.suffix in (".py", ".toml")}
observed={"threads":bpy.context.scene.render.threads,"addon":str(a.addon),"optimize":sys.flags.optimize,
          "env":{k:os.environ[k] for k in ("BLENDER_USER_CONFIG","BLENDER_USER_SCRIPTS",
                                         "BLENDER_USER_DATAFILES","BLENDER_USER_EXTENSIONS")}}
assert all(Path(v).is_dir() for v in observed["env"].values())
(a.output/"observed.json").write_text(json.dumps(observed))
mode=os.environ.get("LAUNCHER_TEST_MODE", "success")
if mode=="timeout":
 child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"])
 (a.output/"child.pid").write_text(str(child.pid))
 time.sleep(60)
if mode=="no_report": sys.exit(0)
if mode=="bad_json":
 (a.output/"regression.json").write_text("{")
 sys.exit(0)
report={"schema":"blender-sith-agentic-regression-v1","blender":"5.1.2",
        "harness_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "addon_sha256":hashes,"tests":[{"name":"fixture","passed":True}],
        "passed":1,"failed":0,"addon_source_unchanged":True}
if mode=="failed_report":
 report.update(passed=0,failed=1)
 report["tests"][0]["passed"]=False
if mode=="inconsistent_report": report["passed"]=99
if mode=="empty_report": report.update(tests=[],passed=0,failed=0)
if mode=="wrong_hash": report["harness_sha256"]="0"*64
if mode=="source_changed": (a.addon/"__init__.py").write_text("# changed\\n")
(a.output/"regression.json").write_text(json.dumps(report))
print("fixture stdout")
print("fixture stderr", file=sys.stderr)
sys.exit(7 if mode=="exit_failure" else 0)
'''


def pid_alive(pid):
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = ctypes.c_ulong()
        try:
            kernel.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code))
            return code.value == 259
        finally:
            kernel.CloseHandle(ctypes.c_void_p(handle))
    status = Path(f"/proc/{pid}/stat")
    if status.exists() and status.read_text().split()[2] == "Z":
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="blender launcher test ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.checkout = self.root / "source with spaces"
        (self.checkout / "scripts").mkdir(parents=True)
        (self.checkout / "tests").mkdir()
        (self.checkout / "sith").mkdir()
        (self.checkout / ".git").mkdir()
        (self.checkout / "sith" / "__init__.py").write_text("# fixture addon\n")
        (self.checkout / "tests" / "background_regression.py").write_text(HARNESS)
        self.bpy_site = self.root / "bpy site with spaces"
        self.bpy_site.mkdir()
        (self.bpy_site / "bpy.py").write_text(FAKE_BPY)
        self.output = self.root / "output with spaces"

    def invoke(self, mode="success", extra=(), output=None, executable=None, entry=None, env_update=None):
        self.assertTrue(LAUNCHER.is_file(), "Headless regression launcher is not implemented")
        launcher = self.checkout / "scripts" / LAUNCHER.name
        shutil.copyfile(LAUNCHER, launcher)
        env = dict(os.environ, LAUNCHER_TEST_MODE=mode, PYTHONDONTWRITEBYTECODE="1")
        env.update(env_update or {})
        command = [sys.executable, str(launcher)]
        if entry:
            wrapper = self.checkout / "scripts" / entry
            shutil.copyfile(SOURCE / "scripts" / entry, wrapper)
            command = (["sh", str(wrapper)] if entry.endswith(".sh") else
                       [shutil.which("pwsh") or shutil.which("powershell"), "-NoProfile", "-File", str(wrapper)])
        command += ["--python", executable or sys.executable,
                   "--bpy-site", str(self.bpy_site), "--output", str(output or self.output), *extra]
        return subprocess.run(command, env=env, capture_output=True, text=True, timeout=20)

    def receipt(self):
        return json.loads((self.output / "receipt.json").read_text())

    def test_success_spaces_isolation_and_receipt(self):
        result = self.invoke(extra=("--threads", "3"))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        receipt = self.receipt()
        self.assertEqual(receipt["status"], "passed")
        self.assertEqual(receipt["exit_code"], 0)
        self.assertEqual(receipt["runtime"]["blender"], "5.1.2")
        self.assertNotIn(str(self.root), json.dumps(receipt))
        self.assertEqual(receipt["source_before_sha256"], receipt["source_after_sha256"])
        expected_hash = hashlib.sha256((self.checkout / "tests" / "background_regression.py").read_bytes()).hexdigest()
        self.assertEqual(receipt["harness_sha256"], expected_hash)
        observed = json.loads((self.output / "results" / "observed.json").read_text())
        self.assertEqual(observed["threads"], 3)
        self.assertEqual(len(set(observed["env"].values())), 4)
        self.assertTrue(all(not Path(p).exists() for p in observed["env"].values()))
        self.assertIn("fixture stdout", (self.output / "stdout.log").read_text())
        self.assertIn("fixture stderr", (self.output / "stderr.log").read_text())

    def test_process_failure_cannot_pass(self):
        result = self.invoke("exit_failure")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.receipt()["exit_code"], 7)
        self.assertEqual(self.receipt()["status"], "process_failed")

    def test_report_validation(self):
        for mode in ("no_report", "bad_json", "failed_report", "inconsistent_report", "empty_report", "wrong_hash"):
            with self.subTest(mode=mode):
                self.output = self.root / mode
                result = self.invoke(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotEqual(self.receipt()["status"], "passed")

    def test_independent_source_change_detection(self):
        result = self.invoke("source_changed")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.receipt()["status"], "source_changed")

    def test_missing_executable_has_receipt(self):
        result = self.invoke(executable=str(self.root / "missing python"))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.receipt()["status"], "launch_failed")

    def test_reject_output_in_source_or_any_git_ancestor(self):
        other_git = self.root / "another checkout"
        other_git.mkdir()
        (other_git / ".git").write_text("gitdir: elsewhere")
        for path in (self.checkout / "generated", other_git / "nested" / "output"):
            with self.subTest(path=path):
                result = self.invoke(output=path)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(path.exists())

    def test_reject_lexical_checkout_junction_to_external_output(self):
        external = self.root / "external target"
        external.mkdir()
        link = self.checkout / "linked external"
        if os.name == "nt":
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(external)],
                                    capture_output=True, text=True, timeout=10)
            if result.returncode:
                self.skipTest("Junction fixture unavailable on this volume: " + result.stderr.strip())
        else:
            link.symlink_to(external, target_is_directory=True)
        result = self.invoke(output=link / "generated")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((external / "generated").exists())

    def test_python_optimization_cannot_disable_regression_assertions(self):
        for optimize in ("1", "2"):
            with self.subTest(optimize=optimize):
                self.output = self.root / ("optimization " + optimize)
                result = self.invoke(env_update={"PYTHONOPTIMIZE": optimize})
                self.assertEqual(result.returncode, 0, result.stderr)
                observed = json.loads((self.output / "results" / "observed.json").read_text())
                self.assertEqual(observed["optimize"], 0)

    def test_reject_existing_output_and_invalid_limits(self):
        self.output.mkdir()
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(self.output.iterdir()), [])
        for flag, value in (("--threads", "0"), ("--timeout", "0"), ("--timeout", "nan")):
            with self.subTest(flag=flag, value=value):
                result = self.invoke(extra=(flag, value), output=self.root / (flag[2:] + value))
                self.assertNotEqual(result.returncode, 0)

    def test_timeout_kills_owned_child_tree(self):
        start = time.monotonic()
        result = self.invoke("timeout", extra=("--timeout", "1.5"))
        self.assertNotEqual(result.returncode, 0)
        self.assertLess(time.monotonic() - start, 12)
        self.assertEqual(self.receipt()["status"], "timeout")
        child = int((self.output / "results" / "child.pid").read_text())
        try:
            deadline = time.monotonic() + 3
            while pid_alive(child) and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertFalse(pid_alive(child), "Owned child survived launcher timeout")
        finally:
            if pid_alive(child):
                os.kill(child, signal.SIGTERM)

    def test_external_addon_path(self):
        addon = self.root / "extracted addon" / "sith"
        addon.mkdir(parents=True)
        (addon / "__init__.py").write_text("# extracted\n")
        result = self.invoke(extra=("--addon", str(addon)))
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads((self.output / "results" / "observed.json").read_text())
        self.assertEqual(Path(observed["addon"]), addon)

    @unittest.skipUnless(shutil.which("pwsh") or shutil.which("powershell"), "PowerShell unavailable")
    def test_powershell_entrypoint_preserves_spaces(self):
        result = self.invoke(entry="run_regression.ps1")
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(os.name != "nt" and shutil.which("sh"), "POSIX shell test requires POSIX host")
    def test_shell_entrypoint_preserves_spaces(self):
        result = self.invoke(entry="run_regression.sh")
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
