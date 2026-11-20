# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for the optional MCP companion; SDK/Blender are not required."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def python_executable():
    if Path(sys.executable).name.lower().startswith("python"):
        return sys.executable
    for name in ("python.exe", f"python{sys.version_info.major}.{sys.version_info.minor}", "python3"):
        candidate = Path(sys.prefix) / "bin" / name
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError("Standalone Python executable was not found")


server = load_module("sith_mcp_test", ROOT / "mcp_server" / "server.py")


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.python = python_executable()
        self.temp = tempfile.TemporaryDirectory(prefix="sith-mcp-test-")
        self.root = Path(self.temp.name).resolve()
        self.read = self.root / "inputs"
        self.read.mkdir()
        self.input = self.read / "sample.3do"
        self.input.write_text("not a model", encoding="utf-8")
        addon = self.root / "checkout-source" / "sith"
        addon.mkdir(parents=True)
        (addon.parent / "LICENSE").write_text("fixture")
        (addon / "blender_manifest.toml").write_text('id = "sith"\nversion = "0.0.7"\n')
        (addon / "__init__.py").write_text("# minimal trusted unit-test addon\n", encoding="utf-8")
        self.config = {"python": str(Path(self.python).resolve()), "read_roots": [str(self.read)],
                       "addon": str(addon), "job_root": str(self.root / "jobs"), "timeout": 30}
        self.service = server.Service(self.config)

    def tearDown(self):
        self.temp.cleanup()

    def test_native_surface_budget_counts_polygons_before_conversion(self):
        from types import SimpleNamespace
        worker = load_module("sith_worker", ROOT / "mcp_server" / "worker.py")
        geo = SimpleNamespace(meshes=[SimpleNamespace(faces=[
            SimpleNamespace(vertexIdxs=range(n)) for n in (2, 3, 4, 5)])])
        self.assertEqual(worker.geoset_topology(1, geo), {"index": 1, "meshes": 1, "triangles": 1, "quads": 1,
                         "ngons": 1, "fewer_than_three_corners": 1, "triangle_equivalents": 6})

    def test_info_does_not_launch_runtime(self):
        self.assertEqual(self.service.info()["transport"], "stdio")
        self.assertEqual(set(self.service.info()["tools"]),
                         {"server_info", "inspect_3do", "audit_model_key", "convert_3do_to_blend"})
        self.assertFalse(list((self.root / "jobs").iterdir()))

    def test_allowlist_accepts_exact_input(self):
        self.assertEqual(self.service.source(str(self.input)), self.input)

    def test_outside_and_prefix_neighbor_rejected(self):
        other = self.root / "inputs-neighbor"
        other.mkdir()
        path = other / "sample.3do"
        path.write_text("x")
        with self.assertRaisesRegex(ValueError, "outside"):
            self.service.source(str(path))

    def test_traversal_relative_and_wrong_type_rejected(self):
        for path in ("sample.3do", str(self.read / ".." / "inputs" / "sample.3do"), str(self.read)):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.service.source(path)
        text = self.read / "script.py"
        text.write_text("print('x')")
        with self.assertRaisesRegex(ValueError, ".3do"):
            self.service.source(str(text))

    def test_symlink_escape_rejected(self):
        link = self.read / "link.3do"
        try:
            link.symlink_to(self.input)
        except OSError as exc:
            self.skipTest("Host cannot create symlinks: " + str(exc))
        with self.assertRaisesRegex(ValueError, "Symlink"):
            self.service.source(str(link))

    def test_key_is_checked_before_job_creation(self):
        outside = self.root / "outside.key"
        outside.write_text("fixture")
        for key_path, target in ((str(outside), "JKDF2"), (str(self.input), "MOTS"), (str(self.input), "OTHER")):
            with self.subTest(key_path=key_path, target=target), self.assertRaises(ValueError):
                self.service.model_job(str(self.input), False, key_path, target)
        self.assertFalse(list(self.service.job_root.iterdir()))

    @unittest.skipUnless(os.name == "nt", "Windows App Execution Aliases")
    def test_store_exception_only_for_configured_blender_alias(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        folder = self.root / "Microsoft" / "WindowsApps"
        folder.mkdir(parents=True)
        alias = folder / "blender-launcher.exe"
        alias.touch()
        original = Path.lstat
        tag = SimpleNamespace(st_mode=0, st_file_attributes=0x400, st_reparse_tag=0x8000001B)
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.root)}):
            with patch.object(Path, "lstat", lambda p: tag if p == alias else original(p)):
                self.assertEqual(server.checked_path(str(alias), blender_alias=True), alias)
                with self.assertRaisesRegex(ValueError, "Symlink"):
                    server.checked_path(str(alias))
                tag.st_reparse_tag = 0xA000000C  # conventional symlink
                with self.assertRaisesRegex(ValueError, "Symlink"):
                    server.checked_path(str(alias), blender_alias=True)


    def test_size_limit(self):
        from unittest.mock import patch
        with patch.object(server, "MAX_INPUT", 4), self.assertRaisesRegex(ValueError, "64 MiB"):
            self.service.source(str(self.input))

    def test_configuration_rejects_unbounded_or_ambiguous_options(self):
        for updates in ({"blender": self.python}, {"timeout": float("nan")}, {"timeout": 0},
                        {"timeout": 1801}, {"threads": True}, {"threads": 65}, {"shell": "x"}, {"read_roots": []}):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                server.Service({**self.config, **updates})

    def test_job_root_git_ancestor_rejected_at_start_and_runtime(self):
        root = self.root / "checkout"
        root.mkdir()
        (root / ".git").write_text("gitdir: elsewhere")
        with self.assertRaisesRegex(ValueError, "Git"):
            server.Service({**self.config, "job_root": str(root / "outputs")})
        (self.root / "jobs" / ".git").mkdir()
        with self.assertRaisesRegex(ValueError, "Git"):
            with self.service.job("test"):
                pass

    def test_jobs_unique_and_serialized(self):
        with self.service.job("test") as first:
            with self.assertRaisesRegex(RuntimeError, "running"):
                with self.service.job("test"):
                    pass
        with self.service.job("test") as second:
            self.assertNotEqual(first, second)
            self.assertTrue(first.is_dir())

    def test_environment_isolates_and_clears_python_injection(self):
        from unittest.mock import patch
        with self.service.job("test") as job, patch.dict(os.environ, {"PYTHONPATH": "bad", "PYTHONHOME": "bad", "PYTHONOPTIMIZE": "2"}):
            env = self.service.environment(job)
        self.assertNotIn("PYTHONPATH", env)
        self.assertNotIn("PYTHONHOME", env)
        self.assertNotIn("PYTHONOPTIMIZE", env)
        self.assertEqual(env["PYTHONNOUSERSITE"], "1")
        self.assertTrue(Path(env["BLENDER_USER_CONFIG"]).is_relative_to(job))

    def test_process_output_is_bounded_and_captured(self):
        from unittest.mock import patch
        # Check truncation without benchmarking the host's external filesystem.
        with patch.object(server, "MAX_LOG", 4096), self.service.job("test") as job:
            result = self.service.execute([self.python, "-c", "import sys; sys.stdout.write('x'*8192); sys.stderr.write('err')"], job)
        self.assertEqual(result["status"], "completed")
        self.assertEqual((job / "stdout.log").stat().st_size, 4096)
        self.assertEqual((job / "stderr.log").read_text(), "err")

    def test_timeout_is_failure_with_cleanup_receipt(self):
        with self.service.job("test") as job:
            result = self.service.execute([self.python, "-c", "import time; time.sleep(60)"], job, timeout=0.2)
        self.assertEqual(result["status"], "timeout")
        self.assertIs(result["owned_tree_cleanup_succeeded"], True)
        self.assertEqual(json.loads((job / "process.json").read_text())["status"], "timeout")

    def test_nonzero_process_is_not_success(self):
        with self.service.job("test") as job:
            result = self.service.execute([self.python, "-c", "raise SystemExit(7)"], job)
        self.assertEqual(result["status"], "process_failed")
        self.assertEqual(result["exit_code"], 7)

    def test_success_exit_without_report_is_not_success(self):
        from unittest.mock import patch
        with patch.object(self.service, "runtime_command", return_value=[self.python, "-c", "pass"]):
            result = self.service.model_job(str(self.input), False)
        self.assertEqual(result["status"], "invalid_report")
        self.assertEqual(self.input.read_text(), "not a model")

    def test_blender_command_disables_autoexec(self):
        self.service.route = "blender"
        command = self.service.runtime_command(Path("worker.py"), Path("request.json"))
        self.assertIn("--factory-startup", command)
        self.assertIn("--disable-autoexec", command)
        self.assertIn("--background", command)
        self.assertIn("--offline-mode", command)





    def test_report_limit(self):
        path = self.root / "report.json"
        path.write_text("[]")
        with self.assertRaises(ValueError):
            server.bounded_json(path)
        path.write_bytes(b" " * (server.MAX_REPORT + 1))
        with self.assertRaises(ValueError):
            server.bounded_json(path)


if __name__ == "__main__":
    unittest.main()
