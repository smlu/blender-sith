#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicitly configured, local stdio MCP tools for Blender-Sith."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import sys
import threading
import time
from typing import Any
import uuid

ROOT = Path(__file__).resolve().parents[1]
MAX_INPUT = 64 * 1024 * 1024
MAX_LOG = 1024 * 1024
MAX_REPORT = 256 * 1024


def load_helper(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = load_helper("sith_mcp_runner", ROOT / "scripts" / "run_regression.py")


def checked_path(value, *, directory=False, exists=True):
    """Reject relative paths, special files, and every link/junction in a route."""
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("Expected an absolute local path")
    supplied = Path(value)
    if not supplied.is_absolute() or ".." in supplied.parts:
        raise ValueError("Paths must be absolute and contain no '..' components")
    path = Path(os.path.abspath(supplied))
    # On Windows reject device/UNC namespaces and alternate data streams.
    if os.name == "nt" and (str(path).startswith("\\\\") or ":" in str(path)[2:]):
        raise ValueError("UNC/device paths and alternate data streams are unsupported")
    for part in (path, *path.parents):
        if os.path.lexists(part):
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                raise ValueError("Symlink/junction routes are forbidden")
    if exists:
        if directory and not path.is_dir():
            raise ValueError("Expected an existing directory")
        if not directory and not path.is_file():
            raise ValueError("Expected an existing regular file")
    return path.resolve()


def bounded_json(path):
    if not path.is_file() or path.stat().st_size > MAX_REPORT:
        raise ValueError("Missing or oversized child report")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Child report must be an object")
    return value


class Service:
    def __init__(self, config):
        allowed = {"addon", "blender", "python", "bpy_site", "read_roots", "job_root", "timeout", "threads"}
        if not isinstance(config, dict) or set(config) - allowed:
            raise ValueError("Unknown configuration fields")
        if bool(config.get("blender")) == bool(config.get("python")):
            raise ValueError("Configure exactly one of blender or python")
        self.addon = checked_path(config.get("addon", str(ROOT / "sith")), directory=True)
        checked_path(str(self.addon / "__init__.py"))
        self.route = "blender" if config.get("blender") else "python"
        self.executable = checked_path(config[self.route])
        self.bpy_site = None
        if config.get("bpy_site"):
            if self.route != "python":
                raise ValueError("bpy_site requires the python route")
            self.bpy_site = checked_path(config["bpy_site"], directory=True)
        roots = config.get("read_roots")
        if not isinstance(roots, list) or not roots:
            raise ValueError("Configure at least one explicit read root")
        self.read_roots = tuple(checked_path(p, directory=True) for p in roots)
        self.job_root = checked_path(config.get("job_root"), directory=True, exists=False)
        for candidate in (self.job_root, *self.job_root.parents):
            if os.path.lexists(candidate / ".git"):
                raise ValueError("Job root must be outside every Git checkout")
        if any(self.job_root == p or p in self.job_root.parents for p in (ROOT, self.addon)):
            raise ValueError("Job root must be outside source directories")
        if any(self.job_root == p or self.job_root in p.parents for p in (ROOT, self.addon)):
            raise ValueError("Job root must not contain source directories")
        self.timeout = config.get("timeout", 120)
        self.threads = config.get("threads", 2)
        if type(self.timeout) not in (int, float) or not math.isfinite(self.timeout) or not 1 <= self.timeout <= 1800:
            raise ValueError("timeout must be finite seconds between 1 and 1800")
        if type(self.threads) is not int or not 1 <= self.threads <= 64:
            raise ValueError("threads must be between 1 and 64")
        self.job_root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def source(self, value):
        path = checked_path(value)
        if not any(path.is_relative_to(root) for root in self.read_roots):
            raise ValueError("Input is outside configured read roots")
        if path.suffix.lower() != ".3do":
            raise ValueError("Input must be a .3do file")
        if path.stat().st_size > MAX_INPUT:
            raise ValueError("Input exceeds the 64 MiB limit")
        return path

    @contextmanager
    def job(self, operation):
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("Another job is running; retry after it completes")
        try:
            checked_path(str(self.job_root), directory=True)
            for parent in (self.job_root, *self.job_root.parents):
                if os.path.lexists(parent / ".git"):
                    raise ValueError("Job root acquired a Git ancestor")
            path = self.job_root / (operation + "-" + uuid.uuid4().hex)
            path.mkdir(exist_ok=False)
            yield path
        finally:
            self.lock.release()

    def info(self):
        return {"server": "blender-sith", "version": "1.0.0", "transport": "stdio",
                "runtime_route": self.route, "timeout_seconds": self.timeout, "threads": self.threads,
                "read_roots": [str(p) for p in self.read_roots], "job_root": str(self.job_root),
                "input_limit_bytes": MAX_INPUT, "tools": ["server_info", "inspect_3do", "convert_3do_to_blend", "run_regression", "build_extension"],
                "limits": ["Local trusted-user service, not an OS sandbox", "No interactive session or arbitrary Python tool",
                           "Geometry-only import: no implicit MAT/CMP reads; JK 2.1 UV normalization needs texture dimensions",
                           "No game-runtime compatibility claim"]}

    def environment(self, job):
        env = os.environ.copy()
        for name in ("PYTHONPATH", "PYTHONHOME", "PYTHONOPTIMIZE"):
            env.pop(name, None)
        env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1", OMP_NUM_THREADS=str(self.threads),
                   OPENBLAS_NUM_THREADS=str(self.threads), MKL_NUM_THREADS=str(self.threads))
        for suffix in ("CONFIG", "SCRIPTS", "DATAFILES", "EXTENSIONS"):
            path = job / ("prefs-" + suffix.lower())
            path.mkdir()
            env["BLENDER_USER_" + suffix] = str(path)
        return env

    def execute(self, command, job, *, timeout=None):
        """Capture bounded logs; never forward Blender stdout to the MCP wire."""
        receipt = {"status": "launch_failed", "exit_code": None}
        started = time.monotonic()
        process = None
        readers = []

        def drain(pipe, path):
            kept = 0
            with pipe, path.open("xb") as log:
                while block := pipe.read(65536):
                    if kept < MAX_LOG:
                        chunk = block[:MAX_LOG - kept]
                        log.write(chunk)
                        kept += len(chunk)

        try:
            process = subprocess.Popen(command, cwd=job, env=self.environment(job), stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=os.name != "nt")
            for stream, name in ((process.stdout, "stdout.log"), (process.stderr, "stderr.log")):
                reader = threading.Thread(target=drain, args=(stream, job / name), daemon=True)
                reader.start()
                readers.append(reader)
            receipt["exit_code"] = process.wait(timeout=timeout or self.timeout)
            receipt["status"] = "completed" if process.returncode == 0 else "process_failed"
        except subprocess.TimeoutExpired:
            receipt["status"] = "timeout"
            receipt["owned_tree_cleanup_succeeded"] = runner.terminate_tree(process)
            receipt["exit_code"] = process.returncode
        except BaseException:
            if process is not None and process.poll() is None:
                runner.terminate_tree(process)
            raise
        finally:
            for reader in readers:
                reader.join(timeout=2)
            receipt["elapsed_seconds"] = round(time.monotonic() - started, 3)
            (job / "process.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        return receipt

    def runtime_command(self, worker, request):
        if self.route == "blender":
            return [str(self.executable), "--background", "--factory-startup", "--offline-mode", "--disable-autoexec", "--threads", str(self.threads),
                    "--python-exit-code", "1", "--python", str(worker), "--", str(request)]
        return [str(self.executable), "-B", str(worker), str(request)]

    def model_job(self, path, convert):
        source = self.source(path)
        with self.job("convert" if convert else "inspect") as job:
            # Snapshot the one allowlisted input, so the importer never searches its neighbors.
            data = source.read_bytes()
            if len(data) > MAX_INPUT:
                raise ValueError("Input grew beyond the 64 MiB limit")
            snapshot = job / "input.3do"
            snapshot.write_bytes(data)
            input_hash = hashlib.sha256(data).hexdigest()
            before = runner.source_hashes(self.addon)
            request = job / "request.json"
            request.write_text(json.dumps({"addon": str(self.addon), "input": str(snapshot), "output": str(job / "model.blend") if convert else None,
                                           "report": str(job / "model.json"), "threads": self.threads,
                                           "bpy_site": str(self.bpy_site) if self.bpy_site else None}), encoding="utf-8")
            process = self.execute(self.runtime_command(ROOT / "mcp_server" / "worker.py", request), job)
            result = {"job_id": job.name, "job_directory": str(job), "input_sha256": input_hash, **process}
            result["source_unchanged"] = before == runner.source_hashes(self.addon)
            if process["status"] == "completed":
                try:
                    result["model"] = bounded_json(job / "model.json")
                    if result["model"].get("schema") != "blender-sith-mcp-model-v1":
                        raise ValueError("Wrong model report schema")
                    if convert:
                        output = checked_path(str(job / "model.blend"))
                        result["output"] = {"path": str(output), "sha256": runner.digest(output), "size": output.stat().st_size}
                    result["status"] = "passed" if result["source_unchanged"] else "source_changed"
                except (ValueError, OSError):
                    result["status"] = "invalid_report"
            (job / "receipt.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            return result

    def regression(self):
        with self.job("regression") as job:
            output = job / "regression"
            command = [sys.executable, "-B", str(ROOT / "scripts" / "run_regression.py"), "--" + self.route, str(self.executable),
                       "--addon", str(self.addon), "--output", str(output), "--timeout", str(self.timeout), "--threads", str(self.threads)]
            if self.bpy_site:
                command += ["--bpy-site", str(self.bpy_site)]
            process = self.execute(command, job, timeout=self.timeout + 45)
            result = {"job_id": job.name, "job_directory": str(job), **process}
            if process["status"] == "completed":
                try:
                    receipt = bounded_json(output / "receipt.json")
                    if receipt.get("status") != "passed" or receipt.get("source_unchanged") is not True:
                        raise ValueError("Regression did not pass")
                    result.update(status="passed", regression=receipt.get("regression"), runtime=receipt.get("runtime"))
                except (ValueError, OSError):
                    result["status"] = "invalid_report"
            return result

    def package(self):
        with self.job("package") as job:
            process = self.execute([sys.executable, "-B", str(ROOT / "scripts" / "build_extension.py"),
                                    "--source-dir", str(ROOT), "--output-dir", str(job / "package")], job)
            result = {"job_id": job.name, "job_directory": str(job), "source": "companion checkout sith directory",
                      "validator": {"status": "not_run", "reason": "Package creation did not complete"}, **process}
            if process["status"] == "completed":
                receipts = list((job / "package").glob("*.receipt.json"))
                if len(receipts) != 1:
                    result["status"] = "invalid_report"
                else:
                    receipt = bounded_json(receipts[0])
                    archive = job / "package" / receipt["archive"]["name"]
                    if archive.parent != job / "package" or runner.digest(archive) != receipt["archive"]["sha256"]:
                        result["status"] = "invalid_report"
                    else:
                        result.update(status="passed", archive={**receipt["archive"], "path": str(archive)}, receipt=str(receipts[0]))
                        if self.route != "blender":
                            result["validator"] = {"status": "not_run", "reason": "Python+bpy route has no configured Blender CLI executable"}
                        else:
                            validation_job = job / "official-validation"
                            validation_job.mkdir(exist_ok=False)
                            command = [str(self.executable), "--background", "--factory-startup", "--offline-mode",
                                       "--disable-autoexec", "--threads", str(self.threads), "--command", "extension", "validate", str(archive)]
                            try:
                                validation = self.execute(command, validation_job)
                            except OSError as exc:
                                validation = {"status": "launch_failed", "exit_code": None, "error_type": type(exc).__name__}
                            result["validator"] = {**validation, "method": "blender_builtin_extension_validate", "logs_directory": str(validation_job)}
                            if validation["status"] == "completed":
                                result["validator"]["status"] = "passed"
                            else:
                                result["status"] = "validation_failed"
            (job / "receipt.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            return result


def create_server(service):
    from mcp.server import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
    server = MCPServer("blender-sith", version="1.0.0", instructions="Operate only on explicitly authorized 3DO inputs. Outputs are new jobs. Inspect status, receipts and limitations before claiming success.")

    def invoke(fn, *args):
        try:
            return fn(*args)
        except (ValueError, OSError, RuntimeError) as exc:
            raise ToolError(str(exc)) from exc

    @server.tool()
    def server_info() -> dict[str, Any]:
        """Return configured scope and limits; does not launch Blender."""
        return service.info()

    @server.tool()
    def inspect_3do(path: str) -> dict[str, Any]:
        """Parse one allowlisted .3do in isolated Blender and return bounded geometry counts, materials and hierarchy counts. No referenced files are read."""
        return invoke(service.model_job, path, False)

    @server.tool()
    def convert_3do_to_blend(path: str) -> dict[str, Any]:
        """Convert one authorized .3do to a NEW geometry-only .blend job artifact. No textures/palette are loaded; only geoset zero is imported. Never overwrite inputs."""
        return invoke(service.model_job, path, True)

    @server.tool()
    def run_regression() -> dict[str, Any]:
        """Run the bundled synthetic 3DO/KEY/MAT regressions using the configured Blender runtime. Creates logs and machine-readable receipts."""
        return invoke(service.regression)

    @server.tool()
    def build_extension() -> dict[str, Any]:
        """Build the companion checkout's sith extension reproducibly with SHA-256 receipt. A configured Blender CLI also runs its built-in extension validator; Python+bpy explicitly reports validation not_run. Does not publish or install."""
        return invoke(service.package)

    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="Explicit local JSON configuration")
    args = parser.parse_args()
    try:
        config = bounded_json(checked_path(str(args.config)))
        service = Service(config)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    create_server(service).run(transport="stdio")


if __name__ == "__main__":
    main()
