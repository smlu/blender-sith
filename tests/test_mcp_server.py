# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for the optional MCP companion; SDK/Blender are not required."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("sith_mcp_test", ROOT / "mcp_server" / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sith-mcp-test-")
        self.root = Path(self.temp.name).resolve()
        self.read = self.root / "inputs"
        self.read.mkdir()
        self.input = self.read / "sample.3do"
        self.input.write_text("not a model", encoding="utf-8")
        addon = self.root / "addon"
        addon.mkdir()
        (addon / "__init__.py").write_text("# minimal trusted unit-test addon\n", encoding="utf-8")
        self.config = {"python": str(Path(sys.executable).resolve()), "read_roots": [str(self.read)],
                       "addon": str(addon), "job_root": str(self.root / "jobs"), "timeout": 30}
        self.service = server.Service(self.config)

    def tearDown(self):
        self.temp.cleanup()

    def test_info_does_not_launch_runtime(self):
        self.assertEqual(self.service.info()["transport"], "stdio")
        self.assertEqual(len(self.service.info()["tools"]), 5)
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

    def test_size_limit(self):
        from unittest.mock import patch
        with patch.object(server, "MAX_INPUT", 4), self.assertRaisesRegex(ValueError, "64 MiB"):
            self.service.source(str(self.input))

    def test_configuration_rejects_unbounded_or_ambiguous_options(self):
        for updates in ({"blender": sys.executable}, {"timeout": float("nan")}, {"timeout": 0},
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
            result = self.service.execute([sys.executable, "-c", "import sys; sys.stdout.write('x'*8192); sys.stderr.write('err')"], job)
        self.assertEqual(result["status"], "completed")
        self.assertEqual((job / "stdout.log").stat().st_size, 4096)
        self.assertEqual((job / "stderr.log").read_text(), "err")

    def test_timeout_is_failure_with_cleanup_receipt(self):
        with self.service.job("test") as job:
            result = self.service.execute([sys.executable, "-c", "import time; time.sleep(60)"], job, timeout=0.2)
        self.assertEqual(result["status"], "timeout")
        self.assertIs(result["owned_tree_cleanup_succeeded"], True)
        self.assertEqual(json.loads((job / "process.json").read_text())["status"], "timeout")

    def test_nonzero_process_is_not_success(self):
        with self.service.job("test") as job:
            result = self.service.execute([sys.executable, "-c", "raise SystemExit(7)"], job)
        self.assertEqual(result["status"], "process_failed")
        self.assertEqual(result["exit_code"], 7)

    def test_success_exit_without_report_is_not_success(self):
        from unittest.mock import patch
        with patch.object(self.service, "runtime_command", return_value=[sys.executable, "-c", "pass"]):
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

    def test_regression_blender_command_uses_offline_mode(self):
        from contextlib import redirect_stdout
        import io
        from unittest.mock import Mock, patch
        process = Mock(returncode=0)
        process.wait.return_value = 0
        with patch.object(server.runner.subprocess, "Popen", return_value=process) as launch, redirect_stdout(io.StringIO()):
            code = server.runner.main(["--blender", str(Path(sys.executable).resolve()), "--addon", str(self.service.addon),
                                       "--output", str(self.root / "regression-output")])
        # Deliberately no child report: an otherwise successful exit still fails.
        self.assertEqual(code, 1)
        self.assertIn("--offline-mode", launch.call_args.args[0])

    def package_with_fake_validator(self, validation_status="completed"):
        from unittest.mock import patch
        calls = []

        def execute(command, job, **kwargs):
            calls.append((command, job))
            if "--source-dir" in command:
                output = job / "package"
                output.mkdir()
                archive = output / "sith-test.zip"
                archive.write_bytes(b"synthetic-test-archive")
                (output / "sith-test.receipt.json").write_text(json.dumps({"archive": {
                    "name": archive.name, "sha256": server.runner.digest(archive), "size": archive.stat().st_size}}))
                return {"status": "completed", "exit_code": 0}
            return {"status": validation_status, "exit_code": 0 if validation_status == "completed" else 1}

        with patch.object(self.service, "execute", side_effect=execute):
            return self.service.package(), calls

    def test_package_python_route_explicitly_skips_official_validator(self):
        result, calls = self.package_with_fake_validator()
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["validator"]["status"], "not_run")
        self.assertIn("no configured Blender CLI", result["validator"]["reason"])
        self.assertEqual(len(calls), 1)

    def test_package_blender_route_validates_exact_archive_in_isolated_job(self):
        self.service.route = "blender"
        result, calls = self.package_with_fake_validator()
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["validator"]["status"], "passed")
        self.assertEqual(len(calls), 2)
        command, validation_job = calls[1]
        self.assertEqual(command[-4:], ["--command", "extension", "validate", result["archive"]["path"]])
        self.assertIn("--offline-mode", command)
        self.assertIn("--disable-autoexec", command)
        self.assertEqual(validation_job.parent, calls[0][1])
        self.assertNotEqual(validation_job, calls[0][1])

    def test_package_validator_failure_cannot_pass(self):
        self.service.route = "blender"
        for status in ("process_failed", "timeout", "launch_failed"):
            with self.subTest(status=status):
                result, _ = self.package_with_fake_validator(status)
                self.assertEqual(result["status"], "validation_failed")
                self.assertEqual(result["validator"]["status"], status)
                self.assertIn("archive", result)

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
