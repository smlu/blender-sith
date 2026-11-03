"""Batch Blender import/export comparisons; run in a separate background process."""
import bisect
import math
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bpy
import numpy as np

from batch.common import UnsupportedResource, arguments, differences, fields, run
from batch.core import check as core_check, read_material
import sith
from sith.key.keyLoader import loadKey
from sith.key.keyWriter import saveKey
from sith.key.key import KeyFileFormat
from sith.key.keyBinary import keyForPlayback
from sith.key.keyImporter import importKey
from sith.key.keyExporter import _make_key_from_obj
from sith.material.cmp import ColorMap
from sith.material.mat import importMat, kMatCelImagePrefix
from sith.model.model3doLoader import load3do
from sith.model.model3doWriter import save3do
from sith.model.model3doImporter import import3do
from sith.model.model3doExporter import makeModel3doFromObj
from sith.model.utils import makeQuaternionRotation


def clear_data():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for collection in (bpy.data.meshes, bpy.data.materials, bpy.data.images, bpy.data.actions):
        for item in list(collection):
            collection.remove(item)
    bpy.context.scene.timeline_markers.clear()
    bpy.context.scene.frame_set(0)


def rotation_error(a, b):
    relative = makeQuaternionRotation(a).conjugated() @ makeQuaternionRotation(b)
    return math.degrees(2 * math.atan2(math.sqrt(sum(v * v for v in relative[1:])), abs(relative[0])))


def compare_models(source, target):
    """Compare effective face corners, not incidental vertex/material numbering."""
    errors = differences(source.insertOffset, target.insertOffset, 'insertOffset', atol=2e-5)
    errors += differences(source.radius, target.radius, 'radius', atol=2e-5)
    if len(source.geosets) != len(target.geosets):
        errors.append(f'geosets: {len(source.geosets)} != {len(target.geosets)} (Blender import uses geoset 0)')
    errors += differences(len(source.meshHierarchy), len(target.meshHierarchy), 'joint count')
    for node, other in zip(source.meshHierarchy, target.meshHierarchy):
        prefix = f'joint[{node.idx}]'
        errors += differences(fields(node, 'idx name flags type parentIdx'), fields(other, 'idx name flags type parentIdx'), prefix)
        errors += differences(node.position, other.position, prefix + '.position', atol=2e-5)
        if rotation_error(node.rotation, other.rotation) > 0.002:
            errors.append(prefix + '.rotation changed')
        if (node.meshIdx < 0) != (other.meshIdx < 0):
            errors.append(prefix + '.mesh binding changed')
            continue
        if node.meshIdx < 0:
            continue
        a = source.geosets[0].meshes[node.meshIdx]
        b = target.geosets[0].meshes[other.meshIdx]
        errors += differences(fields(a, 'geometryMode lightMode textureMode'), fields(b, 'geometryMode lightMode textureMode'), prefix + '.mesh')
        errors += differences(a.radius, b.radius, prefix + '.mesh.radius', atol=2e-5)
        errors += differences(len(a.faces), len(b.faces), prefix + '.faces')
        for index, (face, other_face) in enumerate(zip(a.faces, b.faces)):
            label = f'{prefix}.face[{index}]'
            errors += differences(fields(face, 'type geometryMode lightMode textureMode color'),
                                  fields(other_face, 'type geometryMode lightMode textureMode color'), label, atol=2e-5)
            material = source.materials[face.materialIdx].lower() if face.materialIdx >= 0 else None
            other_material = target.materials[other_face.materialIdx].lower() if other_face.materialIdx >= 0 else None
            errors += differences(material, other_material, label + '.material')
            errors += differences(face.normal, other_face.normal, label + '.normal', atol=2e-5)
            if len(face.vertexIdxs) != len(other_face.vertexIdxs):
                errors.append(label + '.corner count changed')
                continue
            def corners(mesh, polygon, pivot):
                return [(tuple(mesh.vertices[v][i] + pivot[i] for i in range(3)),
                         mesh.normals[v], mesh.vertexColors[v],
                         mesh.uvs[uv] if 0 <= uv < len(mesh.uvs) else None)
                        for v, uv in zip(polygon.vertexIdxs, polygon.uvIdxs)]
            expected, actual = corners(a, face, node.pivot), corners(b, other_face, other.pivot)
            # A cyclic start-corner change is harmless; reversed winding is not.
            rotations = [actual[i:] + actual[:i] for i in range(len(actual))] or [actual]
            # Coincident first corners (or fully collapsed faces) cannot select
            # the alignment alone. Compare every required corner attribute;
            # only cyclic rotations are allowed, never arbitrary permutations.
            def alignment_errors(values):
                return sum(bool(differences(left[component], right[component],
                                            atol=1 / 255 + 1e-6 if component == 2 else 2e-5,
                                            limit=1))
                           for left, right in zip(expected, values) for component in range(4))
            chosen = min(rotations, key=alignment_errors) if expected else actual
            for corner, (left, right) in enumerate(zip(expected, chosen)):
                for component in (0, 1, 3):
                    errors += differences(left[component], right[component], f'{label}.corner[{corner}].{("position", "normal", "color", "uv")[component]}', atol=2e-5)
                errors += differences(left[2], right[2], f'{label}.corner[{corner}].color', atol=1 / 255 + 1e-6)
            if len(errors) >= 20:
                return errors[:20]
    return errors[:20]


def key_pose(node, frame):
    if node is None or not node.keyframes:
        return (0, 0, 0), (0, 0, 0)
    index = max(0, bisect.bisect_right([entry.frame for entry in node.keyframes], frame) - 1)
    entry = node.keyframes[index]
    elapsed = frame - entry.frame
    position = tuple(value + (entry.deltaPosition[i] * elapsed if entry.flags & 1 else 0) for i, value in enumerate(entry.position))
    rotation = tuple(value + (entry.deltaRotation[i] * elapsed if entry.flags & 2 else 0) for i, value in enumerate(entry.orientation))
    return position, rotation


def compare_keys(source, target):
    source, target = keyForPlayback(source), keyForPlayback(target)
    errors = differences(fields(source, 'flags nodeTypes numFrames numJoints fps'),
                         fields(target, 'flags nodeTypes numFrames numJoints fps'), 'header', atol=1e-5)
    expected_markers = [(m.frame, int(m.type)) for m in sorted(source.markers, key=lambda marker: marker.frame)]
    errors += differences(expected_markers,
                          [(m.frame, int(m.type)) for m in target.markers], 'markers')
    by_index = {node.idx: node for node in target.nodes}
    if len(by_index) != len(target.nodes):
        errors.append('Duplicate exported KEY joint indices')
    if any(not 0 <= node.idx < target.numJoints for node in target.nodes):
        errors.append('Exported KEY joint index is outside the header joint count')
    maximum_position = maximum_rotation = 0
    probes = 0
    for node in source.nodes:
        other = by_index.pop(node.idx, None)
        # A missing zero-motion track must not pass merely because key_pose(None)
        # returns zero. Verify identity independently of sampled pose equality.
        if other is None:
            errors.append(f'Missing animated joint: {node.idx}')
            continue
        errors += differences(node.meshName, other.meshName, f'joint[{node.idx}].meshName')
        times = {0.0, max(0.0, source.numFrames - 1e-5)}
        for candidate in (node, other):
            if candidate:
                times.update(entry.frame for entry in candidate.keyframes if 0 <= entry.frame < source.numFrames)
        ordered = sorted(times)
        for left, right in zip(ordered, ordered[1:]):
            # Extra full turns can coincide at every quarter of a long segment;
            # near-end probes alone may then fall below the angular tolerance.
            # Non-quarter samples expose those periodic interpolation errors.
            fractions = (0.25, 0.5, 0.75, (math.sqrt(5) - 1) / 2, 1 / math.sqrt(2))
            times.update(left + (right - left) * fraction for fraction in fractions)
            times.add(max(left, right - min(1e-4, (right - left) * 0.01)))
        for frame in sorted(times):
            pa, ra = key_pose(node, frame)
            pb, rb = key_pose(other, frame)
            position = max(abs(a - b) for a, b in zip(pa, pb))
            rotation = rotation_error(ra, rb)
            maximum_position = max(maximum_position, position)
            maximum_rotation = max(maximum_rotation, rotation)
            probes += 1
            if (position > 5e-5 or rotation > 0.01) and len(errors) < 20:
                errors.append(f'joint[{node.idx}] @ {frame:.9g}: position error {position:.6g}, rotation error {rotation:.6g} deg')
    if by_index:
        errors.append(f'Unexpected animated joints: {sorted(by_index)}')
    return {'differences': errors[:20], 'pose_probes': probes,
            'source_marker_order_corrected': [(m.frame, int(m.type)) for m in source.markers] != expected_markers,
            'max_position_error': maximum_position, 'max_rotation_error_degrees': maximum_rotation}


def check(path, target, options):
    clear_data()
    try:
        if path.suffix.lower() == '.cmp':
            return core_check(path, target, options)
        if path.suffix.lower() == '.mat':
            palette = ColorMap.load(options.palette_path) if options.palette_path else None
            _, cels = read_material(path, palette)
            material = importMat(path, palette)
            for index, (width, height, levels, transparent) in enumerate(cels):
                image = material[kMatCelImagePrefix + str(index)]
                if tuple(image.size) != (width, height):
                    raise AssertionError(f'Cel {index}: Blender image dimensions changed')
                # Generated byte images round normalized 5/6-bit components to
                # 8-bit storage; float buffers need no such quantization allowance.
                tolerance = 1e-6 if image.is_float else 0.5 / 255 + 1e-6
                np.testing.assert_allclose(np.asarray(image.pixels[:]), levels[0], atol=tolerance, rtol=0)
            return {'operation': 'import-image-reference', 'cels': len(cels),
                    'note': 'MAT export is not implemented; every imported cel is compared to source pixels'}
        if path.suffix.lower() == '.3do':
            source, version = load3do(path)
            if not source.geosets:
                raise UnsupportedResource('3DO has no geosets to import into Blender')
            root = import3do(path, mat_dirs=options.mat_dirs,
                             cmp_file=str(options.palette_path) if options.palette_path else '',
                             clearScene=False, importVertexColors=True, importRadiusObj=True,
                             importVertexNormals=getattr(options, 'import_vertex_normals', False))
            target_model = makeModel3doFromObj(path.name, root, uvAbsolute=version.value in (2.1, 'LDOM'),
                                              exportVertexColors=True, sync_mesh_list=False)
            save3do(target_model, target, version, 'Local Blender corpus verification')
            restored, _ = load3do(target)
            return {'operation': 'import-export-parse', 'differences': compare_models(source, restored),
                    'geosets': len(source.geosets), 'joints': len(source.meshHierarchy)}
        source = loadKey(path)
        scene = bpy.context.scene
        root = bpy.data.objects.new('batch_root', None)
        scene.collection.objects.link(root)
        by_index = {node.idx: node for node in source.nodes}
        for index in range(source.numJoints):
            node = by_index.get(index)
            name = node.meshName if node else f'joint{index}'
            obj = bpy.data.objects.new(name, None)
            scene.collection.objects.link(obj)
            obj.parent = root
            obj.sith_model3do_hnode_idx = index
            obj.sith_model3do_hnode_name = name
        bpy.context.view_layer.objects.active = root
        importKey(path, scene, True, True, False)
        selected = getattr(options, 'key_target', 'CUSTOM')
        if source.fileFormat == KeyFileFormat.GrimBinary and selected == 'CUSTOM':
            selected = 'GRIM'
        exported = _make_key_from_obj(path.name, root, scene, target=selected)
        saveKey(exported, target, 'Local Blender corpus verification', fileFormat=exported.fileFormat)
        result = compare_keys(source, loadKey(target))
        result['operation'] = 'import-export-pose-comparison'
        result['note'] = 'Uses an indexed synthetic skeleton, not a title-specific model or in-game animation blending'
        return result
    finally:
        clear_data()


if __name__ == '__main__':
    if not bpy.app.background or bpy.app.version < (5, 0, 0):
        raise RuntimeError('Use Blender 5.0+ with --background --factory-startup')
    options = arguments(__doc__)
    sith.register()
    try:
        status = run(options, check)
    finally:
        sith.unregister()
    if status:
        raise RuntimeError('Corpus verification found errors, mismatches or unsupported resources; see summary.json')
