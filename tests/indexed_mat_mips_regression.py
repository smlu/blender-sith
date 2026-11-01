# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrei and Coda contributors
"""Focused indexed-MAT mip regression; use a fresh background process.

blender --background --factory-startup --python-exit-code 1 \
  --python tests/indexed_mat_mips_regression.py -- \
  --addon /source/blender-sith/sith --output /external/new-mat-results

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
    report = {"schema": "blender-sith-indexed-mat-mips-regression-v1",
              "blender": bpy.app.version_string,
              "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "addon_sha256": before, "tests": [],
              "scope": "Synthetic indexed MAT cels, mip payloads and material transparency"}

    def check(label, operation):
        try:
            details = operation()
            report["tests"].append({"name": label, "passed": True, "details": details})
        except Exception as exc:
            report["tests"].append({"name": label, "passed": False,
                                    "error": type(exc).__name__ + ": " + str(exc)})
            traceback.print_exc()

    try:
        name = "sith_indexed_mat_mips_regression"
        spec = importlib.util.spec_from_file_location(name, addon_path / "__init__.py",
                                                     submodule_search_locations=[str(addon_path)])
        addon = importlib.util.module_from_spec(spec)
        sys.modules[name] = addon
        spec.loader.exec_module(addon)
        matmod = importlib.import_module(name + ".material.mat")
        cmpmod = importlib.import_module(name + ".material.cmp")
        color = matmod.ColorFormat(matmod.ColorMode.Indexed, 8, *([0] * 12))
        prefix = matmod.mh_serf.pack(b"MAT ", 0x32, 2, 2, 2) + matmod.cf_serf.pack(*color)
        prefix += b"".join(matmod.mtr_serf.pack(8, 0, 0, 0, 0, 0, 0, 0, 0, index)
                           for index in range(2))
        first_cel = matmod.mmm_serf.pack(4, 4, 1, 0, 0, 2) + bytes([0, 1] * 8) + bytes([1] * 4)
        second_cel = matmod.mmm_serf.pack(2, 2, 0, 0, 0, 2) + bytes([2] * 4) + bytes([2])
        data = prefix + first_cel + second_cel
        palette = cmpmod.ColorMap()
        palette.palette = [cmpmod.CmpPaletteRGB(*(matmod.np.uint8(index) for _ in range(3)))
                           for index in range(256)]

        def read_cels(payload, supplied_palette):
            stream = io.BytesIO(payload)
            header = matmod._read_header(stream)
            matmod._read_records(stream, header)
            cels = [matmod._read_mipmap(stream, color, supplied_palette) for _ in range(2)]
            return stream, cels

        def check_cels(with_palette):
            supplied = palette if with_palette else None
            stream, cels = read_cels(data, supplied)
            assert [(cel.width, cel.height) for cel in cels] == [(4, 4), (2, 2)]
            assert stream.tell() == len(data), (stream.tell(), len(data))
            assert [cel.transparent for cel in cels] == [True, False]
            if with_palette:
                assert [len(level) for level in cels[0].pixel_data_array] == [64, 16]
                assert [len(level) for level in cels[1].pixel_data_array] == [16, 4]
                assert set(cels[0].pixel_data_array[0][3::4]) == {0.0, 1.0}
                assert set(cels[1].pixel_data_array[0][3::4]) == {1.0}
                assert max(abs(value - 2 / 255) for value in cels[1].pixel_data_array[0][0::4]) < 1e-6
            else:
                assert all(cel.pixel_data_array is None for cel in cels)
            path = output / ("indexed_palette.mat" if with_palette else "indexed_no_palette.mat")
            path.write_bytes(data)
            material = matmod.importMat(path, supplied)
            texture = material.node_tree.nodes["SithTexImage"]
            assert tuple(texture.image.size) == (4, 4)
            assert tuple(bpy.data.images[matmod._get_tex_name(1, material.name)].size) == (2, 2)
            bsdf = next(node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
            assert bsdf.inputs["Alpha"].is_linked
            assert material.surface_render_method == "BLENDED"
            return {"palette_supplied": with_palette, "cel_sizes": [[4, 4], [2, 2]],
                    "mip_levels": [2, 2], "stream_bytes_consumed": stream.tell(),
                    "transparency_preserved": True}

        def check_truncated_payloads():
            for label, payload, count in [("first_cel_final_mip", prefix + first_cel[:-1], 1),
                                          ("second_cel_final_mip", data[:-1], 2)]:
                stream = io.BytesIO(payload)
                header = matmod._read_header(stream)
                matmod._read_records(stream, header)
                try:
                    for _ in range(count):
                        matmod._read_mipmap(stream, color)
                except EOFError:
                    continue
                raise AssertionError("Truncated undecoded mip accepted: " + label)
            return {"rejected": ["first_cel_final_mip", "second_cel_final_mip"], "error": "EOFError"}

        check("indexed_cels_with_palette_control", lambda: check_cels(True))
        check("indexed_cels_without_palette", lambda: check_cels(False))
        check("truncated_undecoded_mips_rejected", check_truncated_payloads)
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
                                     for path in sorted(output.glob("*.mat"))}
        (output / "regression.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("blender", "passed", "failed", "addon_source_unchanged")}))
    return 0 if report["failed"] == 0 and report["addon_source_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
