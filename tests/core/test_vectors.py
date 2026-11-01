"""Check physical resource vectors against explicit fields and recovery outcomes."""
import hashlib
import math
from pathlib import Path
import tempfile
import unittest

from fixtures import TV
from vector_expectations import VALID_MODELS, RECOVERY, INVALID_KEYS, color_for_version
from sith.key.keyLoader import loadKey
from sith.model.model3doLoader import load3do, Model3doFileVersion
from sith.model.model3doWriter import save3do


class ResourceVectorTests(unittest.TestCase):
    def assert_vector(self, actual, expected, tolerance=1e-6):
        self.assertEqual(len(actual), len(expected))
        for a, b in zip(actual, expected):
            self.assertAlmostEqual(a, b, delta=tolerance)

    def test_order_color_vector_has_independent_expected_fields(self):
        model, version = load3do(TV / 'model/order_colors.3do')
        self.assertEqual(version, Model3doFileVersion.Version2_3)
        self.assertEqual([n.name for n in model.meshHierarchy], ['root', 'zebra', 'branch', 'alpha'])
        self.assertEqual([n.parentIdx for n in model.meshHierarchy], [-1, 0, 0, 2])
        self.assertEqual([n.meshIdx for n in model.meshHierarchy], [-1, 0, -1, 1])
        self.assertEqual([n.firstChildIdx for n in model.meshHierarchy], [1, -1, 3, -1])
        self.assertEqual([n.siblingIdx for n in model.meshHierarchy], [-1, 2, -1, -1])
        self.assertEqual(int(model.meshHierarchy[1].flags), 0x2000)
        self.assertEqual(int(model.meshHierarchy[1].type), 0x8008)
        mesh = model.geosets[0].meshes[0]
        self.assertEqual(mesh.vertices, [(0, 0, 0), (1, 0, 0), (0, 1, 0), (2, 2, 0)])
        self.assertEqual(mesh.vertexColors, [(1, 0, 0, 1), (0, 1, 0, 0.5), (0, 0, 1, 0.25), (-0.25, 2, 0.125, 0)])
        self.assertEqual(mesh.uvs[-1], (7, 9))
        self.assertEqual(int(mesh.faces[0].type), 0x103)

    def test_valid_vectors_serialize_all_versions_with_explicit_color_rules(self):
        # Conversion may discard alpha or average RGB, but must not silently
        # change geometry, node references, or the number of loose vertices.
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'converted.3do'
            for name in VALID_MODELS:
                source, _ = load3do(TV / 'model' / name)
                for version in Model3doFileVersion:
                    with self.subTest(vector=name, version=version):
                        save3do(source, output, version, '')
                        actual, actual_version = load3do(output)
                        self.assertEqual(actual_version, version)
                        self.assertEqual([(n.name, n.parentIdx, n.meshIdx) for n in actual.meshHierarchy],
                                         [(n.name, n.parentIdx, n.meshIdx) for n in source.meshHierarchy])
                        self.assertEqual(len(actual.geosets), len(source.geosets))
                        for old_geo, new_geo in zip(source.geosets, actual.geosets):
                            for old, new in zip(old_geo.meshes, new_geo.meshes):
                                self.assertEqual(new.vertices, old.vertices)
                                self.assertEqual(new.uvs, old.uvs)
                                self.assertEqual([f.vertexIdxs for f in new.faces], [f.vertexIdxs for f in old.faces])
                                for a, b in zip(old.vertexColors, new.vertexColors):
                                    self.assert_vector(b, color_for_version(a, version))
                                for a, b in zip(old.faces, new.faces):
                                    self.assert_vector(b.color, color_for_version(a.color, version))

    def test_shared_loose_seam_and_legacy_vectors(self):
        shared, _ = load3do(TV / 'model/shared_mesh.3do')
        self.assertEqual([n.meshIdx for n in shared.meshHierarchy], [-1, 0, 0])
        self.assertEqual([tuple(n.pivot) for n in shared.meshHierarchy], [(0, 0, 0), (0.25, 0, 0), (-0.25, 0, 0)])
        loose, _ = load3do(TV / 'model/loose_vertices.3do')
        points = loose.geosets[0].meshes[0]
        self.assertEqual(len(points.vertices), 4)
        self.assertEqual(points.vertices[0], points.vertices[1])
        self.assertNotEqual(points.vertexColors[0], points.vertexColors[1])
        self.assertEqual(points.faces, [])
        legacy, version = load3do(TV / 'model/legacy_pixels.3do')
        self.assertEqual(version.value, 2.1)
        self.assertEqual(legacy.geosets[0].meshes[0].uvs, [(0, 0), (64, 0), (0, 32)])
        seams, _ = load3do(TV / 'model/color_seams.3do')
        mesh = seams.geosets[0].meshes[0]
        self.assertEqual(len(mesh.vertices), 6)
        self.assertEqual(mesh.vertices[0], mesh.vertices[3])
        self.assertNotEqual(mesh.vertexColors[0], mesh.vertexColors[3])
        self.assertEqual([f.vertexIdxs for f in mesh.faces], [[0, 1, 2], [3, 5, 4]])

    def test_recovery_vectors_match_retention_manifest_without_source_edits(self):
        self.assertEqual(set(RECOVERY), {p.name for p in (TV / 'model/recovery').glob('*.3do')})
        for name, expected in RECOVERY.items():
            path = TV / 'model/recovery' / name
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            with self.subTest(vector=name):
                if expected.get('unrecoverable'):
                    with self.assertRaises((ValueError, TypeError, AssertionError, OSError)):
                        load3do(path, allowErrors=True)
                else:
                    warnings = []
                    model, _ = load3do(path, allowErrors=True, warnings=warnings)
                    meshes = model.geosets[0].meshes
                    self.assertEqual([len(m.vertices) for m in meshes], expected['vertices'])
                    self.assertEqual([len(m.faces) for m in meshes], expected['faces'])
                    self.assertEqual([n.parentIdx for n in model.meshHierarchy], expected['parents'])
                    self.assertIn(expected['warning'], '\n'.join(warnings))
                    self.assertTrue(math.isfinite(model.radius))
                    self.assertTrue(all(math.isfinite(v) for v in model.insertOffset))
                    for mesh in meshes:
                        self.assertEqual(len(mesh.vertices), len(mesh.vertexColors))
                        self.assertEqual(len(mesh.vertices), len(mesh.normals))
                        self.assertTrue(all(math.isfinite(v) for p in mesh.vertices for v in p))
                        self.assertTrue(all(0 <= v < len(mesh.vertices) for f in mesh.faces for v in f.vertexIdxs))
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_recovered_uv_and_face_corner_values_are_not_only_counts(self):
        model, _ = load3do(TV / 'model/recovery/bad_uvs.3do', allowErrors=True)
        mesh = model.geosets[0].meshes[0]
        self.assertEqual(mesh.uvs, [(0, 0), (1, 0), (0, 1), (0, 0)])
        self.assertEqual(mesh.faces[0].uvIdxs, [3, 3, 3])
        model, _ = load3do(TV / 'model/recovery/bad_faces.3do', allowErrors=True)
        self.assertEqual([f.vertexIdxs for f in model.geosets[0].meshes[0].faces], [[0, 1, 2], [0, 0, 1], [2, 1, 0]])
        model, _ = load3do(TV / 'model/recovery/nonfinite.3do', allowErrors=True)
        self.assertEqual(model.geosets[0].meshes[0].vertices, [(0, 0, 0), (1, 0, 0), (0, 1, 0)])
        self.assertEqual(model.geosets[0].meshes[0].faces[0].vertexIdxs, [0, 1, 2])

    def test_paired_key_vector_has_winding_jumps_and_ignored_deltas(self):
        key = loadKey(TV / 'key/order_colors.key')
        self.assertEqual((key.numJoints, key.numFrames, key.fps), (4, 6, 29.97))
        self.assertEqual([(n.idx, n.meshName) for n in key.nodes], [(0, 'root'), (1, 'zebra'), (2, 'branch'), (3, 'alpha')])
        self.assertEqual([(m.frame, int(m.type)) for m in key.markers], [(-0.5, 1), (1.25, 3), (1.25, 4), (4.75, 5), (6, 0)])
        self.assertEqual(key.nodes[0].keyframes[0].flags, 0)
        self.assertEqual(key.nodes[0].keyframes[0].deltaPosition, (99, 99, 99))
        self.assertEqual(key.nodes[2].keyframes[1].orientation.y, 720)
        self.assertEqual(key.nodes[3].keyframes[1].position.z, 2)

    def test_invalid_key_vectors_reach_the_intended_validation_layer(self):
        for name in INVALID_KEYS:
            with self.subTest(vector=name):
                if name in ('truncated_entry.key', 'duplicate_joint.key', 'out_of_range.key'):
                    with self.assertRaises((ValueError, TypeError, AssertionError)):
                        loadKey(TV / 'key' / name)
                else:
                    key = loadKey(TV / 'key' / name)
                    if name == 'invalid_timing.key':
                        self.assertEqual(key.fps, 0)
                    else:
                        self.assertEqual([e.frame for e in key.nodes[1].keyframes], [2, 1])

    def test_import_safety_vectors_have_independent_expected_fields(self):
        for name, times in (('held_too_close.key', [0, 1, 1.00005]),
                            ('held_separated.key', [0, 1, 1.005]),
                            ('held_float32_collision.key', [0, 100000, 100000.0001])):
            with self.subTest(vector=name):
                key = loadKey(TV / 'key' / name)
                self.assertEqual((key.numJoints, key.fps), (1, 30))
                self.assertEqual([entry.frame for entry in key.nodes[0].keyframes], times)
                self.assertEqual([entry.position.x for entry in key.nodes[0].keyframes], [1, 2, 3])
                self.assertEqual([int(entry.flags) for entry in key.nodes[0].keyframes], [0, 0, 0])
        model, version = load3do(TV / 'model/face_lighting_hdr.3do')
        self.assertEqual(version, Model3doFileVersion.Version2_3)
        face = model.geosets[0].meshes[0].faces[0]
        self.assertEqual(face.color, (-0.25, 2, 0.5, 1))
        self.assertEqual(int(face.type), 0x80000081)
        self.assertEqual(face.vertexIdxs, [0, 1, 2])
        self.assertEqual([(node.name, node.meshIdx, node.parentIdx) for node in model.meshHierarchy], [('joint', 0, -1)])

    def test_nonzero_first_key_is_codec_readable_not_a_playable_track(self):
        # Keep parsing separate from runtime validation: the Blender importer
        # must reject this track before replacing or merging existing animation.
        path = TV / 'key/nonzero_first.key'
        before = path.read_bytes()
        key = loadKey(path)
        self.assertEqual((key.numJoints, key.numFrames, key.fps), (1, 6, 30))
        self.assertEqual([(node.idx, node.meshName) for node in key.nodes], [(0, 'joint')])
        entry, = key.nodes[0].keyframes
        self.assertEqual((entry.frame, int(entry.flags)), (2, 3))
        self.assertEqual((entry.position, entry.orientation), ((5, 0, 0), (0, 0, 0)))
        self.assertEqual((entry.deltaPosition, entry.deltaRotation), ((1, 0, 0), (0, 9, 0)))
        self.assertEqual(path.read_bytes(), before)
