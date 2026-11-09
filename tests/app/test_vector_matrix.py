"""Physical vectors cover option interactions, retained data and recovery limits."""
import hashlib
import itertools
import math
from pathlib import Path
import tempfile

import bpy
import mathutils

from app.support import SceneTestCase
from batch.app import compare_keys
from fixtures import TV
from vector_expectations import RECOVERY, INVALID_KEYS, color_for_version
from sith.key.keyExporter import _make_key_from_obj
from sith.key.keyImporter import importKey
from sith.key.keyLoader import loadKey
from sith.key.keyWriter import saveKey
from sith.key.keyUtils import getSceneFrameRate
from sith.model.model3doExporter import export3do, makeModel3doFromObj
from sith.model.model3doImporter import import3do
from sith.model.model3doLoader import load3do, Model3doFileVersion
from sith.model.model3doWriter import save3do
from sith.model import utils


class ResourceVectorMatrixTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name) / 'output.3do'
        self.original_texts = set(bpy.data.texts)
        self.addCleanup(self.remove_reports)

    def remove_reports(self):
        for report in list(bpy.data.texts):
            if report not in self.original_texts:
                bpy.data.texts.remove(report)

    def reset(self):
        self.clear_data()
        self.remove_reports()

    def image_material(self, name):
        material = bpy.data.materials.new(name)
        material.use_nodes = True
        image = bpy.data.images.new(name + '_image', width=64, height=32)
        material.node_tree.nodes.new('ShaderNodeTexImage').image = image

    def assert_model_data(self, source, target, version, colors):
        # Match by joint binding, not incidental mesh-table order or Blender's
        # suffix for a second mesh datablock imported from a shared source mesh.
        self.assertEqual([(n.idx, n.name, n.parentIdx, int(n.flags), int(n.type)) for n in target.meshHierarchy],
                         [(n.idx, n.name, n.parentIdx, int(n.flags), int(n.type)) for n in source.meshHierarchy])
        for before, after in zip(source.meshHierarchy, target.meshHierarchy):
            self.assertEqual(before.meshIdx < 0, after.meshIdx < 0)
            self.assert_vector(after.position, before.position)
            if before.meshIdx < 0:
                continue
            old = source.geosets[0].meshes[before.meshIdx]
            new = target.geosets[0].meshes[after.meshIdx]
            self.assertEqual(len(new.faces), len(old.faces))
            self.assertEqual((int(new.geometryMode), int(new.lightMode), int(new.textureMode)),
                             (int(old.geometryMode), int(old.lightMode), int(old.textureMode)))

            # Check every vertex/color pair, including unused and coincident
            # vertices. Face-corner-only comparisons would miss those losses.
            for position, color in zip(old.vertices, old.vertexColors):
                expected_position = tuple(position[i] + before.pivot[i] for i in range(3))
                expected_color = color_for_version(color if colors else (0, 0, 0, 1), version)
                self.assertTrue(any(
                    max(abs(a - b) for a, b in zip(p, expected_position)) < 2e-6
                    and max(abs(a - b) for a, b in zip(c, expected_color)) < 2e-6
                    for p, c in zip(new.vertices, new.vertexColors)
                ), (before.name, expected_position, expected_color))
            for face, other in zip(old.faces, new.faces):
                self.assertEqual(int(face.type), int(other.type))
                self.assert_vector(other.color, color_for_version(face.color, version))

    def export_reparse(self, root, version, sync, colors):
        model = makeModel3doFromObj('output.3do', root, uvAbsolute=version.value == 2.1,
                                   exportVertexColors=colors, sync_mesh_list=sync)
        save3do(model, self.output, version, '')
        result, actual_version = load3do(self.output)
        self.assertEqual(actual_version, version)
        return result

    def test_order_sync_import_and_export_colors_all_versions(self):
        source, _ = load3do(TV / 'model/order_colors.3do')
        for preserve, import_colors in itertools.product((True, False), repeat=2):
            self.reset()
            self.image_material('grid.mat')
            root = import3do(TV / 'model/order_colors.3do', clearScene=False,
                             preserveOrder=preserve, importVertexColors=import_colors)
            for sync, export_colors, version in itertools.product((True, False), (True, False), Model3doFileVersion):
                with self.subTest(preserve=preserve, sync=sync, import_colors=import_colors, export_colors=export_colors, version=version):
                    model = self.export_reparse(root, version, sync, export_colors)
                    self.assert_model_data(source, model, version, import_colors and export_colors)
                    self.assertEqual([m.name for m in model.geosets[0].meshes],
                                     ['zebra', 'alpha'] if preserve or sync else ['alpha', 'zebra'])
                    mesh = model.geosets[0].meshes[model.meshHierarchy[1].meshIdx]
                    expected_uv = [(0, 0), (64, 0), (0, 32)] if version.value == 2.1 else [(0, 0), (1, 0), (0, 1)]
                    self.assertEqual([mesh.uvs[i] for i in mesh.faces[0].uvIdxs], expected_uv)

    def test_loose_vertices_and_color_seams_survive_every_option(self):
        for name, preserve, import_colors in itertools.product(('loose_vertices.3do', 'color_seams.3do'), (True, False), (True, False)):
            self.reset()
            source, _ = load3do(TV / 'model' / name)
            root = import3do(TV / 'model' / name, clearScene=False, preserveOrder=preserve, importVertexColors=import_colors)
            for sync, export_colors, version in itertools.product((True, False), (True, False), Model3doFileVersion):
                with self.subTest(vector=name, preserve=preserve, sync=sync, import_colors=import_colors, export_colors=export_colors, version=version):
                    model = self.export_reparse(root, version, sync, export_colors)
                    self.assert_model_data(source, model, version, import_colors and export_colors)
                    if name == 'loose_vertices.3do':
                        self.assertEqual(len(model.geosets[0].meshes[0].vertices), 4)
                    elif import_colors and export_colors:
                        self.assertEqual(len(model.geosets[0].meshes[0].vertices), 6)

    def test_shared_mesh_bindings_and_pivots_remain_independent(self):
        source, _ = load3do(TV / 'model/shared_mesh.3do')
        for preserve in (True, False):
            self.reset()
            root = import3do(TV / 'model/shared_mesh.3do', clearScene=False, preserveOrder=preserve)
            for sync, colors, version in itertools.product((True, False), (True, False), Model3doFileVersion):
                with self.subTest(preserve=preserve, sync=sync, colors=colors, version=version):
                    model = self.export_reparse(root, version, sync, colors)
                    self.assert_model_data(source, model, version, colors)
                    self.assert_vector(model.meshHierarchy[1].position, (1, 0, 0))
                    self.assert_vector(model.meshHierarchy[2].position, (-1, 0, 0))

    def test_legacy_pixel_uvs_with_and_without_texture_image(self):
        for preserve, image_available in itertools.product((True, False), repeat=2):
            self.reset()
            if image_available:
                self.image_material('legacy.mat')
            root = import3do(TV / 'model/legacy_pixels.3do', clearScene=False, preserveOrder=preserve)
            for sync, colors in itertools.product((True, False), repeat=2):
                with self.subTest(preserve=preserve, image=image_available, sync=sync, colors=colors):
                    model = self.export_reparse(root, Model3doFileVersion.Version2_1, sync, colors)
                    self.assertEqual(model.geosets[0].meshes[0].uvs, [(0, 0), (64, 0), (0, 32)])
                    if image_available:
                        model = self.export_reparse(root, Model3doFileVersion.Version2_3, sync, colors)
                        self.assertEqual(model.geosets[0].meshes[0].uvs, [(0, 0), (1, 0), (0, 1)])
                    else:
                        with self.assertRaisesRegex(ValueError, 'texture image'):
                            self.export_reparse(root, Model3doFileVersion.Version2_3, sync, colors)

    def test_paired_key_all_modes_matches_explicit_playback_and_export(self):
        expected = loadKey(TV / 'key/order_colors.key')
        for preserve, sync, colors in itertools.product((True, False), repeat=3):
            with self.subTest(preserve=preserve, sync=sync, colors=colors):
                self.reset()
                root = import3do(TV / 'model/order_colors.3do', clearScene=False, preserveOrder=preserve)
                bpy.context.view_layer.objects.active = root
                importKey(TV / 'key/order_colors.key', bpy.context.scene, True, True, False)
                by_index = {obj.sith_model3do_hnode_idx: obj for obj in root.children_recursive}

                # Independently known local poses: a held channel ignores its
                # stale delta; the empty branch completes a deliberate full turn.
                bpy.context.scene.frame_set(2)
                self.assert_vector(by_index[0].location, (0, 0, 0))
                self.assert_vector(by_index[1].location, (0.35, 0, 0))
                self.assertAlmostEqual(math.degrees(by_index[2].rotation_euler.z), 360, delta=0.001)
                self.assert_vector(by_index[3].location, (0, 0, 0.95))
                bpy.context.scene.frame_set(4)
                self.assert_vector(by_index[0].location, (1, 0, 0))
                self.assert_vector(by_index[3].location, (0, 0, 2))
                self.assertAlmostEqual(getSceneFrameRate(bpy.context.scene), 29.97, delta=1e-5)
                bpy.context.scene.frame_set(0)

                model = self.export_reparse(root, Model3doFileVersion.Version2_3, sync, colors)
                key = _make_key_from_obj('paired.key', root, bpy.context.scene)
                path = Path(self.directory.name) / 'paired.key'
                saveKey(key, path, '')
                key = loadKey(path)
                self.assertFalse(compare_keys(expected, key)['differences'])
                self.assertEqual([(n.idx, n.name) for n in model.meshHierarchy], [(n.idx, n.meshName) for n in key.nodes])

    def test_physical_bad_keys_preserve_existing_animation(self):
        for name in INVALID_KEYS:
            with self.subTest(vector=name):
                self.reset()
                root = import3do(TV / 'model/order_colors.3do', clearScene=False)
                bpy.context.view_layer.objects.active = root
                importKey(TV / 'key/order_colors.key', bpy.context.scene, True, True, False)
                actions = [(obj, obj.animation_data.action) for obj in root.children_recursive]
                markers = [(m.name, m.frame) for m in bpy.context.scene.timeline_markers]
                with self.assertRaises((ValueError, TypeError, AssertionError)):
                    importKey(TV / 'key' / name, bpy.context.scene, True, True, False)
                self.assertEqual(bpy.context.scene.frame_end, 5)
                self.assertEqual([(m.name, m.frame) for m in bpy.context.scene.timeline_markers], markers)
                for obj, action in actions:
                    self.assertEqual(obj.animation_data.action, action)

    def test_recovery_color_order_sync_matrix(self):
        for name, expected in RECOVERY.items():
            if expected.get('unrecoverable'):
                continue
            path = TV / 'model/recovery' / name
            source, _ = load3do(path, allowErrors=True)
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            for preserve, import_colors in itertools.product((True, False), repeat=2):
                self.reset()
                if name == 'bad_uvs.3do':
                    self.image_material('missing.mat')
                warnings = []
                root = import3do(path, clearScene=False, preserveOrder=preserve,
                                 importVertexColors=import_colors, allowErrors=True, warnings=warnings)
                self.assertIn(expected['warning'], '\n'.join(warnings))
                report = bpy.data.texts[root[utils.kModel3doImportReport]]
                self.assertTrue(report.use_fake_user)
                for sync, colors, version in itertools.product((True, False), (True, False), Model3doFileVersion):
                    with self.subTest(vector=name, preserve=preserve, sync=sync, import_colors=import_colors, colors=colors, version=version):
                        if expected['exportable']:
                            model = self.export_reparse(root, version, sync, colors)
                            self.assert_model_data(source, model, version, import_colors and colors)
                            # Repeated corners retain their faces using coincident
                            # Blender vertices; raw resource indices stay unchanged.
                            vertices = expected.get('export_vertices', expected['vertices'])
                            self.assertEqual(sum(len(m.vertices) for m in model.geosets[0].meshes), sum(vertices))
                        else:
                            # Inspection recovery does not invent a single root
                            # or unknown attachment transforms just to export.
                            self.output.write_bytes(b'keep existing output')
                            with self.assertRaisesRegex(ValueError, 'exactly one root'):
                                export3do(root, str(self.output), version, False, colors, sync)
                            self.assertEqual(self.output.read_bytes(), b'keep existing output')
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_broken_vectors_do_not_clear_scene_in_strict_mode(self):
        for name in RECOVERY:
            with self.subTest(vector=name):
                self.reset()
                existing = bpy.data.objects.new('keep_existing', None)
                bpy.context.scene.collection.objects.link(existing)
                with self.assertRaises((ValueError, TypeError, AssertionError, IndexError, OSError)):
                    import3do(TV / 'model/recovery' / name, clearScene=True)
                self.assertIn(existing, list(bpy.context.scene.objects))

    def test_unrecoverable_and_empty_vectors_do_not_clear_scene(self):
        for name in ('bad_header.3do', 'no_geometry.3do'):
            self.reset()
            existing = bpy.data.objects.new('keep_existing', None)
            bpy.context.scene.collection.objects.link(existing)
            with self.assertRaises((ValueError, TypeError, AssertionError, OSError)):
                import3do(TV / 'model/recovery' / name, clearScene=True, allowErrors=True)
            self.assertIn(existing, list(bpy.context.scene.objects))
        for recovery in (False, True):
            self.assertIsNone(import3do(TV / 'model/empty.3do', clearScene=True, allowErrors=recovery))
            self.assertIn(existing, list(bpy.context.scene.objects))

    def test_loose_point_colors_are_editable_and_survive_blend_storage(self):
        root = import3do(TV / 'model/order_colors.3do', clearScene=False)
        obj = next(obj for obj in root.children_recursive if obj.sith_model3do_hnode_idx == 1)
        mesh = obj.data
        point = mesh.color_attributes[utils.k3doLooseColors]
        self.assertEqual(point.domain, 'POINT')
        self.assertEqual(mesh.color_attributes.active_color.domain, 'CORNER')
        self.assert_vector(point.data[3].color, (-0.25, 2, 0.125, 0))

        # Editing the ordinary POINT layer must override the source companion;
        # no hidden immutable snapshot may replace the user's current colors.
        point.data.foreach_set('color', [-2, 4, 0.5, 0.25] * len(point.data))
        mesh.color_attributes.active_color = point
        exported = self.export_reparse(root, Model3doFileVersion.Version2_3, False, True)
        for color in exported.geosets[0].meshes[exported.meshHierarchy[1].meshIdx].vertexColors:
            self.assert_vector(color, (-2, 4, 0.5, 0.25))

        path = Path(self.directory.name) / 'colors.blend'
        bpy.data.libraries.write(str(path), {mesh})
        with bpy.data.libraries.load(str(path)) as (source, target):
            target.meshes = [mesh.name]
        self.assert_vector(target.meshes[0].color_attributes[utils.k3doLooseColors].data[3].color,
                           (-2, 4, 0.5, 0.25))

    def test_color_import_off_has_no_empty_active_color_layer(self):
        for name in ('order_colors.3do', 'loose_vertices.3do', 'color_seams.3do'):
            self.reset()
            root = import3do(TV / 'model' / name, clearScene=False, importVertexColors=False)
            for obj in root.children_recursive:
                if obj.type == 'MESH':
                    self.assertEqual(len(obj.data.color_attributes), 0)
                    self.assertIsNone(obj.data.color_attributes.active_color)

    def test_corner_edits_keep_loose_colors_and_bad_companion_domain_is_safe(self):
        root = import3do(TV / 'model/order_colors.3do', clearScene=False)
        obj = next(obj for obj in root.children_recursive if obj.sith_model3do_hnode_idx == 1)
        mesh = obj.data
        for color in mesh.color_attributes.active_color.data:
            color.color = (0.25, 0.5, 1, 0.75)
        model = self.export_reparse(root, Model3doFileVersion.Version2_3, True, True)
        result = model.geosets[0].meshes[model.meshHierarchy[1].meshIdx]
        self.assert_vector(result.vertexColors[-1], (-0.25, 2, 0.125, 0))
        for index in result.faces[0].vertexIdxs:
            self.assert_vector(result.vertexColors[index], (0.25, 0.5, 1, 0.75))

        # A user-created attribute with the reserved name but wrong domain has
        # no loose-vertex values. Export must not index its shorter corner array.
        corner_name = mesh.color_attributes.active_color.name
        mesh.color_attributes.remove(mesh.color_attributes[utils.k3doLooseColors])
        mesh.color_attributes.new(utils.k3doLooseColors, 'FLOAT_COLOR', 'CORNER')
        mesh.color_attributes.active_color = mesh.color_attributes[corner_name]
        model = self.export_reparse(root, Model3doFileVersion.Version2_3, False, True)
        self.assert_vector(model.geosets[0].meshes[model.meshHierarchy[1].meshIdx].vertexColors[-1], (0, 0, 0, 1))

    def test_mirrored_corners_keep_uv_color_pairs_and_loose_vertex_color(self):
        root = import3do(TV / 'model/order_colors.3do', clearScene=False)
        obj = next(obj for obj in root.children_recursive if obj.sith_model3do_hnode_idx == 1)
        obj.scale = (-1, 1, 1)
        for sync in (True, False):
            model = self.export_reparse(root, Model3doFileVersion.Version2_3, sync, True)
            mesh = model.geosets[0].meshes[model.meshHierarchy[1].meshIdx]
            face = mesh.faces[0]
            points = [mathutils.Vector(mesh.vertices[index]) for index in face.vertexIdxs]
            geometric = (points[1] - points[0]).cross(points[2] - points[0]).normalized()
            self.assertGreater(geometric.dot(mathutils.Vector(face.normal)), 0.9999)
            self.assertEqual([mesh.uvs[index] for index in face.uvIdxs], [(0, 1), (1, 0), (0, 0)])
            self.assertEqual([tuple(mesh.vertexColors[index]) for index in face.vertexIdxs],
                             [(0, 0, 1, 0.25), (0, 1, 0, 0.5), (1, 0, 0, 1)])
            self.assert_vector(mesh.vertices[-1], (-2, 2, 0))
            self.assert_vector(mesh.vertexColors[-1], (-0.25, 2, 0.125, 0))

    def test_all_nonfinite_field_groups_fail_before_clear_scene(self):
        text = (TV / 'model/order_colors.3do').read_text()
        changes = (
            ('RADIUS 8', 'RADIUS -1'),
            ('INSERT OFFSET 0.5 -0.25 1', 'INSERT OFFSET 1e999 -0.25 1'),
            ('RADIUS 3', 'RADIUS 1e999'),
            ('3: 2 2 0 -0.25 2 0.125 0', '3: 1e999 2 0 -0.25 2 0.125 0'),
            ('3: 2 2 0 -0.25 2 0.125 0', '3: 2 2 0 1e999 2 0.125 0'),
            ('3: 7 9', '3: 1e999 9'),
            ('0: 0 0 1\n1: 0 0 1', '0: 1e999 0 1\n1: 0 0 1'),
            ('(0.125/0.25/0.5/0.75)', '(1e999/0.25/0.5/0.75)'),
            ('0.25 0 0 0 0 0 0 0 0 zebra', '1e999 0 0 0 0 0 0 0 0 zebra'),
        )
        path = Path(self.directory.name) / 'nonfinite.3do'
        for old, new in changes:
            with self.subTest(field=old):
                self.reset()
                self.assertIn(old, text)
                path.write_text(text.replace(old, new, 1))
                existing = bpy.data.objects.new('keep_existing', None)
                bpy.context.scene.collection.objects.link(existing)
                with self.assertRaisesRegex(ValueError, 'finite|nonnegative'):
                    import3do(path, clearScene=True)
                self.assertIn(existing, list(bpy.context.scene.objects))

    def test_rgb22_input_all_order_and_color_options(self):
        source, _ = load3do(TV / 'model/rgb22.3do')
        for preserve, import_colors in itertools.product((True, False), repeat=2):
            self.reset()
            root = import3do(TV / 'model/rgb22.3do', clearScene=False,
                             preserveOrder=preserve, importVertexColors=import_colors)
            for sync, colors, version in itertools.product((True, False), (True, False), Model3doFileVersion):
                with self.subTest(preserve=preserve, import_colors=import_colors, sync=sync, colors=colors, version=version):
                    model = self.export_reparse(root, version, sync, colors)
                    self.assert_model_data(source, model, version, import_colors and colors)
