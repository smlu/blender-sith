# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrei and Coda contributors
"""Focused 3DO material-table regression; use a fresh background process.

blender --background --factory-startup --python-exit-code 1 \
  --python tests/material_delimiter_regression.py -- \
  --addon /source/blender-sith/sith --output /external/new-material-results

An existing Python+bpy runtime may run this script directly with --bpy-site.
Synthetic fixtures only; this does not test a game engine or install an add-on.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import traceback


def main():
    if sys.flags.optimize:
        raise RuntimeError("Regression assertions require optimization to be disabled")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--addon", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bpy-site", type=Path)
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    args = parser.parse_args(argv)
    addon_path = args.addon.resolve(strict=True)
    if not (addon_path / "__init__.py").is_file():
        parser.error("--addon must name the add-on package directory")
    raw_output = args.output.absolute()
    output = raw_output.resolve()
    for candidate in (raw_output, output):
        if candidate.is_relative_to(addon_path):
            parser.error("Output must be outside the add-on source")
        if any((parent / ".git").exists() for parent in (candidate, *candidate.parents)):
            parser.error("Output must be outside Git checkouts")
    if output.exists():
        parser.error("Output must be a new directory")
    if args.bpy_site:
        sys.path.insert(0, str(args.bpy_site.resolve(strict=True)))
    sys.dont_write_bytecode = True
    import bpy
    if not bpy.app.background:
        parser.error("Use a fresh background Blender process")
    output.mkdir(parents=True, exist_ok=False)

    def hashes():
        return {path.relative_to(addon_path).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(addon_path.rglob("*"))
                if path.is_file() and path.suffix in (".py", ".toml")}

    before = hashes()
    report = {"schema": "blender-sith-material-delimiter-regression-v1",
              "blender": bpy.app.version_string,
              "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "addon_sha256": before, "tests": [],
              "scope": "Synthetic 3DO 2.1 resource rows and parser round trip"}

    def check(label, operation):
        try:
            details = operation()
            report["tests"].append({"name": label, "passed": True, "details": details})
        except Exception as exc:
            report["tests"].append({"name": label, "passed": False,
                                    "error": type(exc).__name__ + ": " + str(exc)})
            traceback.print_exc()

    try:
        name = "sith_material_delimiter_regression"
        spec = importlib.util.spec_from_file_location(name, addon_path / "__init__.py",
                                                     submodule_search_locations=[str(addon_path)])
        addon = importlib.util.module_from_spec(spec)
        sys.modules[name] = addon
        spec.loader.exec_module(addon)
        writer = importlib.import_module(name + ".model.model3doWriter")
        loader = importlib.import_module(name + ".model.model3doLoader")
        model_types = importlib.import_module(name + ".model.model3do")
        materials = ["short.mat", "a" * 11 + ".mat", "l" * 29 + ".mat"]

        def check_rows(names):
            model = model_types.Model3do("material_names")
            model.materials = names
            stream = io.StringIO()
            writer._write_section_resources(stream, model)
            rows = [line.split() for line in stream.getvalue().splitlines()
                    if line.strip() and line.strip()[0].isdigit()]
            assert rows == [[str(index) + ":", material] for index, material in enumerate(names)], rows
            return {"material_lengths": [len(item) for item in names], "rows": rows}

        def check_roundtrip():
            model = model_types.Model3do("material_names")
            model.materials = materials
            path = output / "material_names.3do"
            writer.save3do(model, path, loader.Model3doFileVersion.Version2_1,
                           "Synthetic material delimiter regression")
            loaded, _ = loader.load3do(path)
            assert loaded.materials == materials, loaded.materials
            return {"material_lengths": [len(item) for item in materials], "names_preserved": True}

        check("short_material_control", lambda: check_rows(materials[:1]))
        check("material_rows_at_and_beyond_field_width", lambda: check_rows(materials))
        check("material_names_3do21_roundtrip", check_roundtrip)
    except Exception as exc:
        report["tests"].append({"name": "harness_setup", "passed": False,
                                "error": type(exc).__name__ + ": " + str(exc)})
        traceback.print_exc()
    finally:
        after = hashes()
        report["addon_source_unchanged"] = before == after
        report["source_unchanged"] = before == after
        report["addon_sha256_after"] = after
        report["passed"] = sum(item["passed"] for item in report["tests"])
        report["failed"] = len(report["tests"]) - report["passed"]
        report["fixtures_sha256"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                     for path in sorted(output.glob("*.3do"))}
        (output / "regression.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("blender", "passed", "failed", "addon_source_unchanged")}))
    return 0 if report["failed"] == 0 and report["addon_source_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
