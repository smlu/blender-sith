# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrei and Coda contributors
"""Focused corner-normal export regressions and unchanged-channel controls.

Run in a fresh background process with explicit source and new external output:
  blender --background --factory-startup --offline-mode --disable-autoexec \
    --python-exit-code 1 --python tests/test_corner_normals.py -- \
    --addon /src/blender-sith/sith --output /external/corner_normals-001
  python -B tests/test_corner_normals.py --bpy-site /external/bpy-site \
    --addon /src/blender-sith/sith --output /external/corner_normals-002

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
import math
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
    import bmesh
    from mathutils import Vector

    if not bpy.app.background:
        parser.error('Use a fresh background process, never an interactive scene')
    addon_path, output = checked_paths(parser, args.addon, args.output)

    def hashes():
        return {p.relative_to(addon_path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(addon_path.rglob('*')) if p.suffix in ('.py', '.toml')}

    before_hashes = hashes()
    name = 'sith_corner_normals_regression'
    spec = importlib.util.spec_from_file_location(name, addon_path / '__init__.py',
                                                 submodule_search_locations=[str(addon_path)])
    addon = importlib.util.module_from_spec(spec)
    sys.modules[name] = addon
    spec.loader.exec_module(addon)
    addon.register()
    loader = importlib.import_module(name + '.model.model3doLoader')
    utils = importlib.import_module(name + '.model.utils')
    types = importlib.import_module(name + '.model.model3do')

    report = {'schema': 'blender-sith-corner_normals-regression-v1',
              'blender': bpy.app.version_string,
              'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'addon_sha256': before_hashes, 'tests': [],
              'scope': 'Synthetic 3DO 2.1 normals, UV, material, byte-color and face metadata; no game-runtime claim'}

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

    def snapshot(mesh):
        return {"vertices": [tuple(v.co) for v in mesh.vertices],
                "polygons": [tuple(p.vertices) for p in mesh.polygons],
                "corner_normals": [tuple(n.vector) for n in mesh.corner_normals],
                "uv": [tuple(d.uv) for d in mesh.uv_layers.active.data] if mesh.uv_layers.active else []}

    def roundtrip(obj, label, colors=False, absolute=False, version=None):
        filename = output / (label + ".3do")
        addon.export3do(obj, str(filename), version or loader.Model3doFileVersion.Version2_1,
                        absolute, colors, True)
        model, _ = loader.load3do(str(filename))
        return model

    def check_normals(obj, label, expected_count):
        mesh = obj.data
        before = snapshot(mesh)
        model = roundtrip(obj, label)
        exported = model.geosets[0].meshes[0]
        assert len(exported.vertices) == expected_count, (len(exported.vertices), expected_count)
        assert len(exported.faces) == len(mesh.polygons)
        worst = 0.0
        for polygon, face in zip(mesh.polygons, exported.faces):
            assert len(face.vertexIdxs) == len(polygon.loop_indices)
            for loop_index, index in zip(polygon.loop_indices, face.vertexIdxs):
                loop = mesh.loops[loop_index]
                assert (Vector(exported.vertices[index]) - mesh.vertices[loop.vertex_index].co).length < 1e-6
                error = (Vector(exported.normals[index]) - mesh.corner_normals[loop_index].vector).length
                assert math.isfinite(error), f"non-finite corner-normal error {error}"
                worst = max(worst, error)
        assert worst < 2e-6, f"worst corner-normal error {worst}"
        assert snapshot(mesh) == before, "Export changed source mesh"
        return {"source_vertices": len(mesh.vertices), "exported_vertices": expected_count,
                "checked_corners": len(mesh.loops), "max_normal_error": worst, "source_unchanged": True}

    def split_vertices():
        obj = mesh_object("split", [(0,0,0),(1,0,0),(0,1,0),(0,0,0),(0,0,1),(1,0,0)], [(0,1,2),(3,4,5)])
        return check_normals(obj, "split", 6)

    def cube(style):
        bpy.ops.mesh.primitive_cube_add()
        obj = bpy.context.object
        obj.name = "cube_" + style
        obj.sith_model3do_hnode_idx = 0
        for face in obj.data.polygons:
            face.use_smooth = style != "flat"
        if style == "sharp":
            for edge in obj.data.edges:
                edge.use_edge_sharp = True
        obj.data.update()
        return check_normals(obj, "cube_" + style, 8 if style == "smooth" else 24)

    def custom_normals():
        obj = mesh_object("custom", [(0,0,0),(1,0,0),(1,1,0),(0,1,0)], [(0,1,2),(0,2,3)])
        for p in obj.data.polygons:
            p.use_smooth = True
        obj.data.normals_split_custom_set([(0.6,0,0.8)] * 3 + [(0,0.6,0.8)] * 3)
        return check_normals(obj, "custom", 6)

    def mixed_polygons():
        # A pentagon, an isolated triangle, and a triangle whose first two
        # positions coincide with the pentagon. Distinct custom corner normals
        # make a wrong polygon/loop correspondence observable after reparse.
        obj = mesh_object("mixed", [(0,0,0),(2,0,0),(3,1,0),(1,3,0),(-1,1,0),
                                    (5,0,0),(6,0,0),(5,1,0),(0,0,0),(2,0,0),(1,3,0)],
                          [(0,1,2,3,4),(5,6,7),(8,9,10)])
        for p in obj.data.polygons:
            p.use_smooth = True
        normals = [Vector((0.03*(i+1), 0.02*(11-i), 1)).normalized()
                   for i in range(len(obj.data.loops))]
        obj.data.normals_split_custom_set(normals)
        return check_normals(obj, "mixed", 11)

    def data_channels():
        obj = mesh_object("channels", [(0,0,0),(1,0,0),(1,1,0),(0,1,0)], [(0,1,2),(0,2,3)])
        mesh = obj.data
        uv = mesh.uv_layers.new(name="UVMap")
        coords = [(0,0),(0.5,0),(0.5,0.5),(0.25,0.25),(0.75,0.75),(0.25,0.75)]
        for d, co in zip(uv.data, coords):
            d.uv = co
        for i in range(2):
            mat = bpy.data.materials.new("channel%d.mat" % i)
            mat.use_nodes = True
            node = mat.node_tree.nodes.new("ShaderNodeTexImage")
            node.image = bpy.data.images.new("channel%d" % i, width=128, height=64)
            mesh.materials.append(mat)
        mesh.polygons[1].material_index = 1
        colors = mesh.color_attributes.new(name="Color", type="BYTE_COLOR", domain="CORNER")
        for i, d in enumerate(colors.data):
            d.color = (0.25,0.25,0.25,1) if i < 3 else (0.75,0.75,0.75,1)
        bm = bmesh.new()
        try:
            bm.from_mesh(mesh)
            utils.bmMeshInit3doLayers(bm)
            for i, face in enumerate(bm.faces):
                utils.bmFaceSetType(face, bm, types.FaceType.DoubleSided)
                utils.bmFaceSetGeometryMode(face, bm, types.GeometryMode.Texture)
                utils.bmFaceSetLightMode(face, bm, types.LightMode.Gouraud)
                utils.bmFaceSetTextureMode(face, bm, types.TextureMode.Perspective)
            bm.to_mesh(mesh)
        finally:
            bm.free()
        before = snapshot(mesh)
        checks = []
        for absolute in (False, True):
            for version in (loader.Model3doFileVersion.Version2_1,):
                label = "channels_%s_%s" % (int(absolute), version.value)
                model = roundtrip(obj, label, colors=True, absolute=absolute, version=version)
                exported = model.geosets[0].meshes[0]
                assert len(exported.vertices) == 6, "Color discontinuities must remain split"
                assert model.materials == ["channel0.mat", "channel1.mat"]
                assert len(exported.faces) == len(mesh.polygons), "Exported face count changed"
                for p, face in zip(mesh.polygons, exported.faces):
                    assert len(face.vertexIdxs) == len(p.loop_indices), "Exported vertex-corner count changed"
                    assert len(face.uvIdxs) == len(p.loop_indices), "Exported UV-corner count changed"
                    assert face.materialIdx == p.material_index
                    assert (int(face.type), int(face.geometryMode), int(face.lightMode), int(face.textureMode)) == (1,4,3,1)
                    for loop_index, index, ui in zip(p.loop_indices, face.vertexIdxs, face.uvIdxs):
                        u, v = coords[loop_index]
                        expected_uv = Vector((u * (128 if absolute else 1), -v * (64 if absolute else 1)))
                        assert (Vector(exported.uvs[ui]) - expected_uv).length < 2e-6
                        # Existing exporter uses BMesh byte-color (sRGB) values.
                        expected_color = mesh.color_attributes["Color"].data[loop_index].color_srgb
                        assert max(abs(a-b) for a,b in zip(exported.vertexColors[index][:3], expected_color[:3])) < 2e-6
                checks.append(label)
        assert snapshot(mesh) == before
        # UV seams alone need separate texture indices, not duplicate geometry.
        plain = roundtrip(obj, "uv_seam", colors=False).geosets[0].meshes[0]
        assert len(plain.vertices) == 4 and len(plain.uvs) == 6
        return {"roundtrips": checks, "uv_seam_vertices": 4, "source_unchanged": True}

    try:
        check('disconnected_split_normals', split_vertices)
        for style in ('flat', 'smooth', 'sharp'):
            check('cube_' + style, lambda style=style: cube(style))
        check('custom_corner_normals', custom_normals)
        check('mixed_ngon_disconnected_faces', mixed_polygons)
        check('uv_material_color_face_channels', data_channels)
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
