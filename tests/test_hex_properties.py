# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrei and Coda contributors
"""Focused scripted HexProperty regressions with 3DO hierarchy and KEY round trips.

Run in a fresh background process with explicit source and new external output:
  blender --background --factory-startup --offline-mode --disable-autoexec \
    --python-exit-code 1 --python tests/test_hex_properties.py -- \
    --addon /src/blender-sith/sith --output /external/hex_properties-001
  python -B tests/test_hex_properties.py --bpy-site /external/bpy-site \
    --addon /src/blender-sith/sith --output /external/hex_properties-002

Use a parent process deadline and isolated Blender preferences in automation.
The script uses only synthetic fixtures and does not install the add-on.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import traceback


def checked_paths(parser, addon_arg, output_arg):
    if not addon_arg.is_absolute() or not output_arg.is_absolute():
        parser.error('--addon and --output require absolute paths')
    addon = addon_arg.resolve(strict=True)
    if not (addon / '__init__.py').is_file():
        parser.error('--addon must name the add-on package directory')
    for path in (output_arg, output_arg.resolve()):
        if any((parent / '.git').exists() for parent in (path, *path.parents)):
            parser.error('--output must be outside every Git checkout')
        if path == addon.parent or addon.parent in path.parents:
            parser.error('--output must be outside the source tree')
    output = output_arg.resolve()
    output.mkdir(parents=True, exist_ok=False)
    return addon, output


def main():
    if sys.flags.optimize:
        raise RuntimeError('Regression assertions require Python optimization to be disabled')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--addon', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--bpy-site', type=Path)
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    args = parser.parse_args(argv)
    if args.bpy_site:
        sys.path.insert(0, str(args.bpy_site.resolve(strict=True)))
    sys.dont_write_bytecode = True
    import bpy

    if not bpy.app.background:
        parser.error('Use a fresh background process, never an interactive scene')
    addon_path, output = checked_paths(parser, args.addon, args.output)

    def hashes():
        return {p.relative_to(addon_path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(addon_path.rglob('*')) if p.suffix in ('.py', '.toml')}

    before_hashes = hashes()
    name = 'sith_hex_properties_regression'
    spec = importlib.util.spec_from_file_location(name, addon_path / '__init__.py',
                                                 submodule_search_locations=[str(addon_path)])
    addon = importlib.util.module_from_spec(spec)
    sys.modules[name] = addon
    spec.loader.exec_module(addon)
    addon.register()
    loader = importlib.import_module(name + '.model.model3doLoader')
    keyloader = importlib.import_module(name + '.key.keyLoader')

    report = {'schema': 'blender-sith-hex_properties-regression-v1',
              'blender': bpy.app.version_string,
              'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'addon_sha256': before_hashes, 'tests': [],
              'scope': 'Synthetic registered RNA properties and serialized 3DO/KEY metadata; no game-runtime claim'}

    def reset():
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)

    def check(label, fn):
        reset()
        try:
            details = fn()
            report["tests"].append({"name": label, "passed": True, "details": details})
        except Exception as exc:
            report["tests"].append({"name": label, "passed": False,
                                    "error": type(exc).__name__ + ": " + str(exc)})
            traceback.print_exc()

    def mesh_object(label, vertices, faces):
        mesh = bpy.data.meshes.new(label)
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        obj = bpy.data.objects.new(label, mesh)
        bpy.context.scene.collection.objects.link(obj)
        obj.sith_model3do_hnode_idx = 0
        return obj

    def roundtrip(obj, label, colors=False, absolute=False, version=None):
        filename = output / (label + ".3do")
        addon.export3do(obj, str(filename), version or loader.Model3doFileVersion.Version2_1,
                        absolute, colors, True)
        model, _ = loader.load3do(str(filename))
        return model

    def hierarchy():
        root = bpy.data.objects.new("root", None)
        bpy.context.scene.collection.objects.link(root)
        root.location = (2,3,4)
        obj = mesh_object("parent", [(0,0,0),(1,0,0),(0,1,0)], [(0,1,2)])
        obj.parent = root
        obj.location = (1,2,3)
        child = mesh_object("child", [(0,0,0),(1,0,0),(0,1,0)], [(0,1,2)])
        child.parent = obj
        child.location = (0,1,0)
        child.sith_model3do_hnode_idx = 1
        model = roundtrip(root, "hierarchy")
        assert tuple(model.insertOffset) == (2,3,4)
        nodes = model.meshHierarchy
        assert [(n.idx, n.parentIdx, n.firstChildIdx, n.meshIdx) for n in nodes] == [(0,-1,1,0),(1,0,-1,1)]
        assert tuple(nodes[0].position) == (1,2,3) and tuple(nodes[1].position) == (0,1,0)
        return {"nodes": 2, "meshes": 2, "offset_and_local_positions": "preserved"}

    def metadata():
        scene = bpy.context.scene
        if "sith_key_types" in scene:
            del scene["sith_key_types"]
        default_value = scene.sith_key_types
        attempts = []
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            for value, expected in [("FFFF","FFFF"),("0xFFFF","FFFF"),("0xffff","FFFF"),("0X0001","01"),("0000","00"),
                                    ("0x0","00"),("ABCD","ABCD"),("-1","ABCD"),("10000","ABCD"),("invalid","ABCD"),("","FFFF")]:
                scene.sith_key_types = value
                actual = scene.sith_key_types
                attempts.append({"input": value, "expected": expected, "actual": actual})
        assert not errors.getvalue(), errors.getvalue()
        assert default_value == "FFFF", ("default", default_value)
        assert all(x["actual"] == x["expected"] for x in attempts), attempts
        obj = mesh_object("metadata", [(0,0,0),(1,0,0),(0,1,0)], [(0,1,2)])
        assert obj.sith_model3do_hnode_type == "01"
        obj.sith_model3do_hnode_flags = "0x8000"
        obj.sith_model3do_hnode_type = "0x0008"
        model = roundtrip(obj, "metadata")
        assert int(model.meshHierarchy[0].flags) == 0x8000 and int(model.meshHierarchy[0].type) == 8
        return {"default": default_value, "attempts": attempts, "3do_flags_and_type": "roundtripped"}

    def key_roundtrip():
        scene = bpy.context.scene
        scene.sith_key_types = "0xFFFF"
        scene.frame_start = 0
        scene.frame_end = 10
        scene.render.fps = 30
        obj = mesh_object("animated", [(0,0,0),(1,0,0),(0,1,0)], [(0,1,2)])
        for frame, location in [(0,(0,0,0)), (10,(1,2,3))]:
            obj.location = location
            obj.keyframe_insert(data_path="location", frame=frame)
            obj.rotation_euler = (0,0,0)
            obj.keyframe_insert(data_path="rotation_euler", frame=frame)
        path = output / "animation.key"
        addon.exportKey(obj, scene, str(path))
        key = keyloader.loadKey(str(path))
        assert int(key.nodeTypes) == 0xFFFF
        assert key.numJoints == 1 and len(key.nodes) == 1
        assert key.numFrames == 11 and key.fps == 30
        assert [k.frame for k in key.nodes[0].keyframes] == [0,10]
        assert tuple(key.nodes[0].keyframes[-1].position) == (1,2,3)
        return {"type": "FFFF", "joints": 1, "frames": [0,10], "last_position": [1,2,3]}

    try:
        check('hierarchy_and_offset', hierarchy)
        check('hex_metadata', metadata)
        check('animated_key_roundtrip', key_roundtrip)
    finally:
        report['addon_source_unchanged'] = before_hashes == hashes()
        report['passed'] = sum(t['passed'] for t in report['tests'])
        report['failed'] = len(report['tests']) - report['passed']
        report['fixtures_sha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                     for p in sorted(output.iterdir()) if p.suffix in ('.3do', '.key')}
        (output / 'regression.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('blender', 'passed', 'failed', 'addon_source_unchanged')}, indent=2))
    return 0 if report['failed'] == 0 and report['addon_source_unchanged'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
