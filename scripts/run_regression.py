#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run synthetic regressions in an isolated, bounded Blender/bpy subprocess."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time


LEXICAL_ROOT = Path(os.path.abspath(__file__)).parents[1]
ROOT = LEXICAL_ROOT.resolve()
SCHEMA = "blender-sith-agentic-regression-v1"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_hashes(addon):
    return {p.relative_to(addon).as_posix(): digest(p)
            for p in sorted(addon.rglob("*")) if p.is_file() and p.suffix in (".py", ".toml")}


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def positive_seconds(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be positive finite seconds")
    return number


def checked_output(path, addon):
    lexical = Path(os.path.abspath(path))
    resolved = lexical.resolve()
    sources = (LEXICAL_ROOT, ROOT, Path(os.path.abspath(addon)), addon.resolve())
    for candidate in (lexical, resolved):
        if any(candidate == source or candidate.is_relative_to(source) for source in sources):
            raise ValueError("output must be outside the source directory")
        if any(os.path.lexists(parent / ".git") for parent in (candidate, *candidate.parents)):
            raise ValueError("output must have no Git checkout ancestor")
    if resolved.exists():
        raise ValueError("output must be a new directory")
    return resolved


def terminate_tree(process):
    """Target only the subprocess we created and its descendants."""
    try:
        if os.name == "nt":
            taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
            result = subprocess.run([str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15, check=False)
            tree_stopped = result.returncode == 0
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            tree_stopped = True
        process.wait(timeout=10)
        return tree_stopped
    except (OSError, subprocess.TimeoutExpired):
        # Preserve a failure receipt even if the OS refuses tree cleanup.
        try:
            process.kill()
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
        return False


def safe_version(value):
    # Receipts are portable: no executable, user, machine, or checkout paths.
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9 ._()+-]{1,128}", value) else "unknown"


def validate_report(path, before, harness_hash):
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "missing_report", None
    except (OSError, UnicodeError, ValueError):
        return "invalid_report", None
    if not isinstance(report, dict):
        return "invalid_report", None
    tests = report.get("tests")
    if (report.get("schema") != SCHEMA or not isinstance(tests, list) or not tests
            or any(not isinstance(t, dict) or type(t.get("passed")) is not bool for t in tests)
            or type(report.get("passed")) is not int or type(report.get("failed")) is not int
            or report["passed"] != sum(t["passed"] for t in tests)
            or report["failed"] != sum(not t["passed"] for t in tests)
            or report.get("harness_sha256") != harness_hash
            or report.get("addon_sha256") != before):
        return "invalid_report", None
    summary = {"passed": report["passed"], "failed": report["failed"],
               "addon_source_unchanged": report.get("addon_source_unchanged") is True}
    status = "passed" if not report["failed"] and summary["addon_source_unchanged"] else "regression_failed"
    return status, summary


def bootstrap(harness, addon, results, runtime, threads, bpy_site):
    return f'''import json, runpy, sys
from pathlib import Path
sys.dont_write_bytecode = True
if {str(bpy_site) if bpy_site else None!r}:
    sys.path.insert(0, {str(bpy_site) if bpy_site else None!r})
import bpy
if not bpy.app.background:
    raise RuntimeError("Refusing an interactive Blender process")
bpy.ops.wm.read_factory_settings(use_empty=True)
for scene in bpy.data.scenes:
    scene.render.threads_mode = "FIXED"
    scene.render.threads = {threads}
Path({str(runtime)!r}).write_text(json.dumps({{
    "python": ".".join(map(str, sys.version_info[:3])),
    "blender": bpy.app.version_string}}), encoding="utf-8")
sys.argv = [{str(harness)!r}, "--addon", {str(addon)!r}, "--output", {str(results)!r}]
runpy.run_path({str(harness)!r}, run_name="__main__")
'''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    runtime_group = parser.add_mutually_exclusive_group(required=True)
    runtime_group.add_argument("--blender", help="Blender executable path or command")
    runtime_group.add_argument("--python", help="Python executable with compatible bpy")
    parser.add_argument("--bpy-site", type=Path, help="Existing bpy dependency directory (Python route)")
    parser.add_argument("--addon", type=Path, default=ROOT / "sith", help="Exact addon package directory")
    parser.add_argument("--output", type=Path, required=True, help="New directory outside every Git checkout")
    parser.add_argument("--threads", type=positive_int, default=2)
    parser.add_argument("--timeout", type=positive_seconds, default=300)
    args = parser.parse_args(argv)
    addon = args.addon.resolve()
    harness = ROOT / "tests" / "background_regression.py"
    if not (addon / "__init__.py").is_file():
        parser.error("addon must be the existing sith package directory")
    if not harness.is_file():
        parser.error("background regression harness is missing")
    if args.bpy_site and (not args.python or not args.bpy_site.is_dir()):
        parser.error("--bpy-site requires --python and an existing directory")
    try:
        output = checked_output(args.output, args.addon)
        output.mkdir(parents=True, exist_ok=False)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    before = source_hashes(addon)
    harness_hash = digest(harness)
    receipt = {"schema": "blender-sith-launcher-v1", "status": "launch_failed", "exit_code": None,
               "platform": {"system": platform.system(), "machine": platform.machine()},
               "runtime": {"route": "blender" if args.blender else "python", "python": "unknown", "blender": "unknown"},
               "threads": args.threads, "timeout_seconds": args.timeout,
               "launcher_sha256": digest(Path(__file__)), "harness_sha256": harness_hash,
               "source_before_sha256": before}
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix=".runtime-", dir=output) as temp:
        isolated = Path(temp)
        env = os.environ.copy()
        for suffix in ("CONFIG", "SCRIPTS", "DATAFILES", "EXTENSIONS"):
            directory = isolated / suffix.lower()
            directory.mkdir()
            env["BLENDER_USER_" + suffix] = str(directory)
        env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1",
                   OMP_NUM_THREADS=str(args.threads), OPENBLAS_NUM_THREADS=str(args.threads),
                   MKL_NUM_THREADS=str(args.threads))
        # Explicit --bpy-site is the dependency route, not ambient Python injection.
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        env.pop("PYTHONOPTIMIZE", None)
        runtime_path = isolated / "runtime.json"
        wrapper = isolated / "bootstrap.py"
        wrapper.write_text(bootstrap(harness, addon, output / "results", runtime_path, args.threads,
                                    args.bpy_site.resolve() if args.bpy_site else None), encoding="utf-8")
        executable = args.blender or args.python
        resolved = shutil.which(executable) or executable
        command = ([resolved, "--background", "--factory-startup", "--offline-mode", "--disable-autoexec", "--threads", str(args.threads),
                    "--python-exit-code", "1", "--python", str(wrapper)] if args.blender
                   else [resolved, "-B", str(wrapper)])
        process = None
        with (output / "stdout.log").open("wb") as stdout, (output / "stderr.log").open("wb") as stderr:
            try:
                process = subprocess.Popen(command, cwd=isolated, env=env, stdout=stdout, stderr=stderr,
                                           start_new_session=os.name != "nt")
                receipt["exit_code"] = process.wait(timeout=args.timeout)
                receipt["status"] = "completed" if process.returncode == 0 else "process_failed"
            except subprocess.TimeoutExpired:
                receipt["status"] = "timeout"
                receipt["owned_tree_cleanup_succeeded"] = terminate_tree(process)
                receipt["exit_code"] = process.returncode
            except KeyboardInterrupt:
                receipt["status"] = "interrupted"
                if process is not None:
                    receipt["owned_tree_cleanup_succeeded"] = terminate_tree(process)
                    receipt["exit_code"] = process.returncode
            except OSError as exc:
                stderr.write((type(exc).__name__ + ": " + str(exc) + "\n").encode("utf-8"))
                receipt["error_type"] = type(exc).__name__
        if runtime_path.is_file():
            try:
                runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
                receipt["runtime"].update({key: safe_version(runtime.get(key)) for key in ("python", "blender")})
            except (OSError, ValueError, AttributeError):
                pass

    after = source_hashes(addon)
    receipt["source_after_sha256"] = after
    receipt["harness_after_sha256"] = digest(harness) if harness.is_file() else None
    receipt["source_unchanged"] = before == after and receipt["harness_after_sha256"] == harness_hash
    report_status, summary = validate_report(output / "results" / "regression.json", before, harness_hash)
    receipt["report_status"] = report_status
    if summary is not None:
        receipt["regression"] = summary
    if receipt["status"] == "completed":
        receipt["status"] = report_status if receipt["source_unchanged"] else "source_changed"
    receipt["elapsed_seconds"] = round(time.monotonic() - started, 3)
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "exit_code": receipt["exit_code"]}))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
