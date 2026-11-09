import copy
import contextlib
import io
import json
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from app.support import SceneTestCase
from batch.app import compare_keys, compare_models, check
from batch.common import run
from fixtures import TV, cmp_bytes, mat_bytes, packed_mat_cels, INDEX8, RGB24, RGBA32, RGB565, RGBA4444, RGBA1555
from grim_fixtures import grim_mat_bytes
from sith.key import Key, KeyNode, Keyframe
from sith.key.keyLoader import loadKey
from sith.model.model3doLoader import load3do


class PackedMaterialBatchTests(SceneTestCase):
    def test_blender_batch_checks_quantized_packed_materials(self):
        with tempfile.TemporaryDirectory() as directory:
            root, output = Path(directory) / 'assets', Path(directory) / 'report'
            root.mkdir()
            for name, fmt in (('rgb565', RGB565), ('rgba4444', RGBA4444), ('rgba1555', RGBA1555)):
                (root / (name + '.mat')).write_bytes(mat_bytes(fmt, packed_mat_cels()))
            before = {path.name: path.read_bytes() for path in root.iterdir()}
            options = SimpleNamespace(assets=[root], output=output, title='packed', formats=['mat'],
                                      match='*', limit=0, cmp=None, keep_exports=False)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run(options, check), 0)
            self.assertEqual(json.loads((output / 'summary.json').read_text())['counts'], {'pass': 3})
            records = [json.loads(line) for line in (output / 'results.jsonl').read_text().splitlines()]
            self.assertEqual({record['encoding'] for record in records}, {'RGB565', 'RGBA4444', 'RGBA1555'})
            self.assertTrue(all(record['operation'] == 'import-export-import-image-reference' for record in records))
            self.assertTrue(all(record['exported_mipmap_levels'] == 5 for record in records))
            self.assertEqual({path.name: path.read_bytes() for path in root.iterdir()}, before)

    def test_batch_round_trips_all_encodings_color_records_and_grim_cels(self):
        inputs = [('rgb24', mat_bytes(RGB24, [(2, 1, [b'\x12\x34\x56\x78\x9a\xbc'], False, 0)]), 'RGB24'),
                  ('rgba32', mat_bytes(RGBA32), 'RGBA32'),
                  ('indexed', mat_bytes(INDEX8, [(2, 2, [bytes((0, 17, 70, 255))], True, 0),
                                                (1, 1, [b'\x11'], False, 0)]), 'INDEXED'),
                  ('color', mat_bytes(INDEX8, color_indices=[17, 70, 255]), 'INDEXED'),
                  ('grim-type2', mat_bytes(INDEX8, [(2, 2, [bytes((0, 17, 70, 255))], True, 0),
                                                   (1, 1, [b'\x11'], False, 0)]), 'INDEXED'),
                  ('grim', grim_mat_bytes(tag=0, cels=[(2, 2, [bytes((0, 17, 70, 255))], True),
                                                     (1, 1, [b'\x11'], False)]), 'INDEXED')]
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            palette = folder / 'test.cmp'
            palette.write_bytes(cmp_bytes())
            for name, data, encoding in inputs:
                with self.subTest(name=name):
                    source, target = folder / (name + '.mat'), folder / 'export.mat'
                    source.write_bytes(data)
                    result = check(source, target, SimpleNamespace(palette_path=palette,
                                   mat_target='GRIM' if name == 'grim-type2' else 'SOURCE'))
                    self.assertEqual(result['encoding'], encoding)
                    self.assertGreater(result['checked_pixels'], 0)
                    self.assertEqual(result['color_records_expanded'], name == 'color')
                    if name.startswith('grim'):
                        self.assertEqual(result['exported_mipmap_levels'], result['cels'])
                    self.assertEqual(source.read_bytes(), data)

    def test_batch_detects_wrong_export_pixels_and_rejects_truncated_source(self):
        from batch.material import prepareMatExports
        from sith.material.matWriter import encodeMat, MatCel
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source, target = folder / 'source.mat', folder / 'export.mat'
            source.write_bytes(mat_bytes(RGBA32))
            def wrong_pixels(*args, **kwargs):
                prepared = prepareMatExports(*args, **kwargs)
                return [(prepared[0][0], encodeMat([MatCel(2, 2, [0, 0, 0, 1] * 4)]))]
            with mock.patch('batch.material.prepareMatExports', side_effect=wrong_pixels), self.assertRaises(AssertionError):
                check(source, target, SimpleNamespace(palette_path=None))
            original = mat_bytes(RGBA32)
            for data in (b'', original[:-1], original[:4] + struct.pack('<i', 10) + original[8:]):
                with self.subTest(size=len(data)):
                    source.write_bytes(data)
                    target.write_bytes(b'previous export')
                    with self.assertRaises((ImportError, ValueError)):
                        check(source, target, SimpleNamespace(palette_path=None))
                    self.assertEqual(target.read_bytes(), b'previous export')


class BatchComparisonTests(unittest.TestCase):
    def test_identical_resources_match(self):
        model, _ = load3do(TV / 'model' / 'triangle.3do')
        self.assertEqual(compare_models(model, copy.deepcopy(model)), [])
        key = loadKey(TV / 'key' / 'fractional.key')
        self.assertEqual(compare_keys(key, copy.deepcopy(key))['differences'], [])

    def test_pivot_baking_and_vertex_reindexing_are_not_data_loss(self):
        source, _ = load3do(TV / 'model' / 'triangle.3do')
        target = copy.deepcopy(source)
        mesh = target.geosets[0].meshes[0]
        pivot = target.meshHierarchy[1].pivot
        mesh.vertices = [tuple(vertex[i] + pivot[i] for i in range(3)) for vertex in mesh.vertices]
        target.meshHierarchy[1].pivot = (0, 0, 0)
        order = [2, 0, 1]
        for name in ('vertices', 'vertexColors', 'normals', 'uvs'):
            old = getattr(mesh, name)
            setattr(mesh, name, [old[i] for i in order])
        mesh.faces[0].vertexIdxs = [order.index(i) for i in mesh.faces[0].vertexIdxs]
        mesh.faces[0].uvIdxs = [order.index(i) for i in mesh.faces[0].uvIdxs]
        self.assertEqual(compare_models(source, target), [])

    def test_lost_lods_and_changed_uvs_are_reported(self):
        source, _ = load3do(TV / 'model' / 'triangle.3do')
        target = copy.deepcopy(source)
        target.geosets[0].meshes[0].uvs[1] = (0.5, 0.5)
        self.assertTrue(compare_models(source, target))
        target = copy.deepcopy(source)
        source.geosets.append(copy.deepcopy(source.geosets[0]))
        self.assertTrue(any('geosets' in error for error in compare_models(source, target)))

    def test_cyclic_corner_alignment_handles_coincident_vertices(self):
        for collapsed in (False, True):
            source, _ = load3do(TV / 'model/triangle.3do')
            mesh = source.geosets[0].meshes[0]
            mesh.vertices[1] = mesh.vertices[0]
            if collapsed:
                mesh.vertices[2] = mesh.vertices[0]
            target = copy.deepcopy(source)
            face = target.geosets[0].meshes[0].faces[0]
            face.vertexIdxs = face.vertexIdxs[1:] + face.vertexIdxs[:1]
            face.uvIdxs = face.uvIdxs[1:] + face.uvIdxs[:1]
            with self.subTest(collapsed=collapsed):
                self.assertEqual(compare_models(source, target), [])
                # Alignment must not hide an actual per-corner UV mutation.
                target.geosets[0].meshes[0].uvs[1] = (0.25, 0.75)
                self.assertTrue(compare_models(source, target))

    def test_wrong_rotation_path_is_detected_between_endpoints(self):
        source = loadKey(TV / 'key' / 'fractional.key')
        target = copy.deepcopy(source)
        entry = target.nodes[0].keyframes[0]
        # One extra revolution per interval can have identical endpoint poses.
        span = target.nodes[0].keyframes[1].frame - entry.frame
        entry.flags = 3
        entry.deltaRotation = (entry.deltaRotation.x, entry.deltaRotation.y + 360 / span, entry.deltaRotation.z)
        result = compare_keys(source, target)
        self.assertTrue(result['differences'])
        self.assertGreater(result['max_rotation_error_degrees'], 90)

    def test_multiple_turns_do_not_alias_quarter_interval_probes(self):
        source = Key('long.key')
        source.numFrames, source.numJoints = 10000, 1
        node = KeyNode()
        node.idx, node.meshName, node.keyframes = 0, 'joint', [Keyframe()]
        source.nodes = [node]
        self.assertFalse(compare_keys(source, copy.deepcopy(source))['differences'])
        for turns in (4, 8, 16):
            target = copy.deepcopy(source)
            entry = target.nodes[0].keyframes[0]
            entry.flags, entry.deltaRotation = 2, (0, turns * 360 / source.numFrames, 0)
            with self.subTest(turns=turns):
                result = compare_keys(source, target)
                self.assertTrue(result['differences'])
                self.assertGreater(result['max_rotation_error_degrees'], 90)
