"""Regression coverage for scene safety, current mesh data and UI entry points."""
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import bpy
import bmesh
import mathutils

from app.support import SceneTestCase
from app.test_key import sample_key
from fixtures import TV, INDEX8, RGB24, mat_bytes, cmp_bytes
from sith import app
from sith.key import Key, Keyframe, KeyNode, KeyMarker, KeyMarkerType
from sith.key.keyImporter import importKey
from sith.key.keyExporter import _make_key_from_obj, exportKey
from sith.key.keyLoader import loadKey
from sith.key.keyWriter import saveKey
from sith.key.keyUtils import getActionFCurves, getSceneFrameRate, setSceneFrameRate
from sith.material import ColorMap, importMat
from sith.model.model3doExporter import export3do, makeModel3doFromObj
from sith.model.model3doImporter import import3do
from sith.model.model3doLoader import load3do, Model3doFileVersion
from sith.model import utils


class ImportExportSafetyTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.folder = Path(self.directory.name)
        self.scene = bpy.context.scene
        self.scene.timeline_markers.clear()
        self.scene.frame_start = 0
        self.scene.frame_end = 9
        self.scene.render.fps, self.scene.render.fps_base = 24, 1
        self.scene.sith_key_flags = set()
        self.scene.sith_key_types = 'ffff'
        originalTexts = set(bpy.data.texts)
        self.addCleanup(self.remove_reports, originalTexts)

    @staticmethod
    def remove_reports(original):
        for text in list(bpy.data.texts):
            if text not in original:
                bpy.data.texts.remove(text)

    def joint(self, name='joint', parent=None, index=0):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        obj = bpy.data.objects.new(name, mesh)
        self.scene.collection.objects.link(obj)
        obj.parent = parent
        obj.sith_model3do_hnode_idx = index
        obj.sith_model3do_hnode_name = name
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        return obj

    def animate(self, obj):
        for frame, value in ((0, 0), (9, 1)):
            obj.location.x = value
            obj.keyframe_insert(data_path='location', frame=frame)
        self.scene.frame_set(0)

    def scene_metadata(self):
        return (self.scene.render.fps, self.scene.render.fps_base,
                set(self.scene.sith_key_flags), self.scene.sith_key_types,
                self.scene.frame_start, self.scene.frame_end,
                [(marker.name, marker.frame) for marker in self.scene.timeline_markers])

    def test_later_joint_pivot_failure_preserves_actions_and_metadata(self):
        # Prepare two valid tracks, but make the second destination unsupported.
        root = self.joint()
        child = self.joint('child', root, 1)
        self.animate(root)
        self.animate(child)
        pivot = child.constraints.new('PIVOT')
        pivot.offset, pivot.influence = (1, 0, 0), 0.5
        bpy.context.view_layer.objects.active = root
        self.scene.timeline_markers.new('keep_me', frame=8)
        before = self.scene_metadata()
        actions = [obj.animation_data.action.as_pointer() for obj in (root, child)]

        key = Key('replacement.key')
        key.numFrames, key.numJoints, key.fps = 3, 2, 59.94
        for index, name in enumerate(('joint', 'child')):
            node = KeyNode()
            node.idx, node.meshName, node.keyframes = index, name, [Keyframe()]
            key.nodes.append(node)
        marker = KeyMarker()
        marker.frame, marker.type = 1, KeyMarkerType(3)
        key.markers = [marker]
        path = self.folder / 'replacement.key'
        saveKey(key, path, '')

        # Both replacement and merge must fail before touching the first joint.
        for clear in (False, True):
            with self.subTest(clear=clear):
                with self.assertRaisesRegex(ValueError, 'partial Pivot'):
                    importKey(path, self.scene, clear, True, False)
                self.assertEqual(self.scene_metadata(), before)
                self.assertEqual([obj.animation_data.action.as_pointer() for obj in (root, child)], actions)

    def test_mat_reload_preserves_images_shared_by_other_materials(self):
        path = self.folder / 'texture.mat'
        path.write_bytes(mat_bytes())
        material = importMat(path)
        image = material.node_tree.nodes['SithTexImage'].image
        pointer = image.as_pointer()
        other = bpy.data.materials.new('other')
        other.use_nodes = True
        node = other.node_tree.nodes.new('ShaderNodeTexImage')
        node.image = image

        path.write_bytes(mat_bytes(RGB24, [(1, 1, [bytes((10, 20, 30))], False, 0)]))
        self.assertEqual(importMat(path), material)
        self.assertEqual(node.image.as_pointer(), pointer)
        self.assertEqual(material.node_tree.nodes['SithTexImage'].image.as_pointer(), pointer)
        self.assertEqual(tuple(image.size), (1, 1))
        self.assert_vector(image.pixels[:], (10 / 255, 20 / 255, 30 / 255, 1))

    def test_bad_color_mat_preserves_loaded_material_with_or_without_palette(self):
        path = self.folder / 'texture.mat'
        path.write_bytes(mat_bytes())
        material = importMat(path)
        image = material.node_tree.nodes['SithTexImage'].image
        pointer, pixels = image.as_pointer(), list(image.pixels)
        palettePath = self.folder / 'palette.cmp'
        palettePath.write_bytes(cmp_bytes())
        palette = ColorMap.load(palettePath)

        for index in (-1, 256):
            path.write_bytes(mat_bytes(INDEX8, color_indices=[0, index]))
            for colorMap in (None, palette):
                with self.subTest(index=index, palette=colorMap is not None):
                    with self.assertRaisesRegex(ImportError, 'palette index'):
                        importMat(path, colorMap)
                    self.assertEqual(material.node_tree.nodes['SithTexImage'].image.as_pointer(), pointer)
                    self.assertEqual(list(image.pixels), pixels)
                    self.assertEqual(len(material.node_tree.nodes), 3)

    def test_mat_operator_reports_invalid_color_record(self):
        path = self.folder / 'invalid.mat'
        path.write_bytes(mat_bytes(INDEX8, color_indices=[256]))
        with self.assertRaisesRegex(RuntimeError, 'Cannot import MAT: Invalid MAT palette index'):
            bpy.ops.import_material.sith_mat(filepath=str(path))
        self.assertNotIn('invalid.mat', bpy.data.materials)

    def test_export_uses_live_edit_mesh_without_leaving_edit_mode(self):
        obj = self.joint()
        bpy.ops.object.mode_set(mode='EDIT')
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bm.verts[1].co.x = 7
        bmesh.update_edit_mesh(obj.data)
        path = self.folder / 'edited.3do'

        # Exercise the registered operator as well as its geometry collector.
        self.assertEqual(bpy.ops.export_scene.sith_3do(filepath=str(path)), {'FINISHED'})
        self.assertEqual(obj.mode, 'EDIT')
        model, _ = load3do(path)
        self.assertEqual(max(vertex.x for vertex in model.geosets[0].meshes[0].vertices), 7)
        self.assertGreaterEqual(model.geosets[0].meshes[0].radius, 7)

    def test_export_synchronizes_every_mesh_in_multi_object_edit_mode(self):
        root = self.joint()
        child = self.joint('child', root, 1)
        bpy.ops.object.mode_set(mode='EDIT')
        for obj, x in ((root, 3), (child, 5)):
            bm = bmesh.from_edit_mesh(obj.data)
            bm.verts.ensure_lookup_table()
            bm.verts[1].co.x = x
        model = makeModel3doFromObj('edited.3do', root)
        self.assertEqual([max(v.x for v in mesh.vertices) for mesh in model.geosets[0].meshes], [3, 5])
        self.assertTrue(all(obj.mode == 'EDIT' for obj in (root, child)))

    def test_model_constraints_are_rejected_only_when_active(self):
        obj = self.joint()
        constraint = obj.constraints.new('COPY_LOCATION')
        path = self.folder / 'constrained.3do'
        path.write_bytes(b'previous export')
        with self.assertRaisesRegex(ValueError, 'non-pivot constraints'):
            export3do(obj, str(path), Model3doFileVersion.Version2_3, False, False, True)
        self.assertEqual(path.read_bytes(), b'previous export')
        for mute, influence in ((True, 1), (False, 0)):
            constraint.mute, constraint.influence = mute, influence
            with self.subTest(mute=mute, influence=influence):
                makeModel3doFromObj('allowed.3do', obj)

    def test_nonfinite_uv_export_preserves_previous_file(self):
        obj = self.joint()
        layer = obj.data.uv_layers.new()
        path = self.folder / 'uv.3do'
        for axis in (0, 1):
            for value in (math.nan, math.inf, -math.inf):
                layer.data[0].uv = (0, 0)
                layer.data[0].uv[axis] = value
                # Blender clamps infinity at the RNA boundary; test the values
                # that actually remain nonfinite in the underlying mesh.
                if math.isfinite(layer.data[0].uv[axis]):
                    continue
                path.write_bytes(b'previous export')
                with self.subTest(axis=axis, value=value):
                    with self.assertRaisesRegex(ValueError, 'texture coordinates must be finite'):
                        export3do(obj, str(path), Model3doFileVersion.Version2_3, False, True, True)
                    self.assertEqual(path.read_bytes(), b'previous export')

    def test_export_does_not_weld_distinct_corners_of_the_same_face(self):
        # Legacy meshes can have distinct vertex IDs at the same position. They
        # must not become repeated IDs merely because their colors also match.
        obj = self.joint()
        obj.data.vertices[2].co = obj.data.vertices[1].co
        path = self.folder / 'coincident.3do'
        export3do(obj, str(path), Model3doFileVersion.Version2_3, False, True, True)
        model, _ = load3do(path)
        mesh = model.geosets[0].meshes[0]
        self.assertEqual(len(mesh.faces), 1)
        self.assertEqual(len(set(mesh.faces[0].vertexIdxs)), 3)
        self.assertEqual(mesh.vertices[1], mesh.vertices[2])

    def test_recovered_nonfinite_uv_import_is_finite_and_exportable(self):
        text = (TV / 'model/triangle.3do').read_text()
        text = text.replace('TEXTURE VERTICES 3\n0: 0.0 0.0', 'TEXTURE VERTICES 3\n0: 1e999 0.0')
        path = self.folder / 'recovery.3do'
        path.write_text(text)
        root = import3do(path, clearScene=False, allowErrors=True)
        mesh = next(obj.data for obj in root.children_recursive if obj.type == 'MESH')
        self.assertEqual(len(mesh.polygons), 1)
        self.assertTrue(all(math.isfinite(value) for loop in mesh.uv_layers.active.data for value in loop.uv))
        report = bpy.data.texts[root[utils.kModel3doImportReport]].as_string()
        self.assertIn('using placeholder', report)
        output = self.folder / 'recovered.3do'
        export3do(root, str(output), Model3doFileVersion.Version2_3, False, True, True)
        load3do(output)

    def test_bad_header_and_topology_fail_before_clear_scene(self):
        obj = self.joint('keep_me')
        source = (TV / 'model/triangle.3do').read_text()
        cases = (
            (source.replace('SECTION: HEADER\n3DO 2.3\n', ''), OSError),
            (source.replace('3 0,0 1,1 2,2', '3 0,0 99,1 99,2'), ValueError),
            (source.replace('3 0,0 1,1 2,2', '2 0,0 1,1'), ValueError),
        )
        path = self.folder / 'invalid.3do'
        for text, exception in cases:
            path.write_text(text)
            with self.subTest(exception=exception):
                with self.assertRaises(exception):
                    import3do(path, clearScene=True)
                self.assertEqual(list(bpy.data.objects), [obj])

    def test_key_dialog_defaults_to_exact_scene_rate(self):
        obj = self.joint()
        for fps in (12, 24, 48, 48.25, 30000 / 1001, 120):
            setSceneFrameRate(self.scene, fps)
            operator = SimpleNamespace(report=lambda *args: None, filename_ext='.key')
            with self.subTest(fps=fps), patch.object(app.ExportHelper, 'invoke', return_value={'RUNNING_MODAL'}):
                self.assertEqual(app.ExportKey.invoke(operator, bpy.context, None), {'RUNNING_MODAL'})
                self.assertAlmostEqual(operator.fps, getSceneFrameRate(self.scene), delta=1e-9)
                self.assertEqual(operator.obj, obj)

    def test_direct_key_export_keeps_scene_rate_and_metadata_by_default(self):
        obj = self.joint()
        self.animate(obj)
        for fps in (48, 48.25, 30000 / 1001):
            setSceneFrameRate(self.scene, fps)
            self.scene.sith_key_flags = {'NoLoop'}
            self.scene.sith_key_types = '8008'
            before = self.scene_metadata()
            path = self.folder / 'direct.key'
            with self.subTest(fps=fps):
                self.assertEqual(bpy.ops.export_anim.sith_key(filepath=str(path)), {'FINISHED'})
                key = loadKey(path)
                self.assertAlmostEqual(key.fps, getSceneFrameRate(self.scene), delta=1e-6)
                self.assertEqual(int(key.flags), 2)
                self.assertEqual(int(key.nodeTypes), 0x8008)
                self.assertEqual(self.scene_metadata(), before)

    def test_key_export_applies_dialog_settings_only_after_success(self):
        obj = self.joint()
        self.animate(obj)
        path = self.folder / 'settings.key'
        self.assertEqual(bpy.ops.export_anim.sith_key(filepath=str(path), fps=48.25,
                                                    flags={'NoLoop'}, node_types='8008'), {'FINISHED'})
        key = loadKey(path)
        self.assertAlmostEqual(key.fps, 48.25)
        self.assertAlmostEqual(getSceneFrameRate(self.scene), 48.25, delta=1e-5)
        self.assertEqual(int(key.nodeTypes), 0x8008)
        self.assertEqual(self.scene.sith_key_flags, {'NoLoop'})
        self.assertEqual(int(self.scene.sith_key_types, 16), 0x8008)

    def test_failed_key_export_preserves_scene_settings_and_existing_file(self):
        obj = self.joint()
        self.animate(obj)
        obj.constraints.new('COPY_LOCATION')
        path = self.folder / 'failure.key'
        path.write_bytes(b'previous export')
        before = self.scene_metadata()
        with self.assertRaisesRegex(RuntimeError, 'non-pivot constraints'):
            bpy.ops.export_anim.sith_key(filepath=str(path), fps=60, flags={'NoLoop'})
        self.assertEqual(self.scene_metadata(), before)
        self.assertEqual(path.read_bytes(), b'previous export')

        # Disk errors use the same non-mutating failure path and a useful report.
        obj.constraints.clear()
        with patch.object(app, 'exportKey', side_effect=OSError('simulated disk failure')):
            with self.assertRaisesRegex(RuntimeError, 'simulated disk failure'):
                bpy.ops.export_anim.sith_key(filepath=str(path), fps=60, flags={'NoLoop'})
        self.assertEqual(self.scene_metadata(), before)
        self.assertEqual(path.read_bytes(), b'previous export')

    def test_direct_export_reports_missing_selection_without_creating_files(self):
        for operator, suffix in ((bpy.ops.export_scene.sith_3do, '.3do'),
                                 (bpy.ops.export_anim.sith_key, '.key')):
            path = self.folder / ('unselected' + suffix)
            with self.subTest(suffix=suffix):
                with self.assertRaisesRegex(RuntimeError, 'No object selected'):
                    operator(filepath=str(path))
                self.assertFalse(path.exists())

    def test_face_panel_and_callbacks_ignore_curve_edit_mode(self):
        curve = bpy.data.curves.new('curve', 'CURVE')
        obj = bpy.data.objects.new('curve', curve)
        self.scene.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        self.assertFalse(app.Mesh3doFacePanel.poll(bpy.context))
        with patch('sith.app.bmesh.from_edit_mesh', side_effect=AssertionError('Curve passed to BMesh')):
            app._apply_to_selected_faces(bpy.context, lambda *args: self.fail('Callback must not run'))

    def test_live_mesh_modifiers_fail_before_replacing_existing_output(self):
        obj = self.joint()
        modifier = obj.modifiers.new('Visible Mirror', 'MIRROR')
        path = self.folder / 'modified.3do'
        path.write_bytes(b'previous export')
        with self.assertRaisesRegex(ValueError, 'Apply visible mesh modifiers'):
            export3do(obj, str(path), Model3doFileVersion.Version2_3, False, False, True)
        self.assertEqual(path.read_bytes(), b'previous export')
        self.assertEqual(obj.modifiers[0], modifier)
        self.assertEqual(len(obj.data.polygons), 1)

        # Hiding the effect explicitly exports the original authored geometry.
        modifier.show_viewport = False
        model = makeModel3doFromObj('hidden.3do', obj)
        self.assertEqual(len(model.geosets[0].meshes[0].faces), 1)

    def test_applied_mesh_modifiers_export_the_visible_geometry(self):
        obj = self.joint()
        modifier = obj.modifiers.new('Mirror', 'MIRROR')
        bpy.ops.object.modifier_apply(modifier=modifier.name)
        model = makeModel3doFromObj('applied.3do', obj)
        self.assertEqual(len(model.geosets[0].meshes[0].faces), 2)
        self.assertEqual(len(obj.modifiers), 0)

    def test_key_export_does_not_require_applying_geometry_modifiers(self):
        obj = self.joint()
        obj.modifiers.new('Mirror', 'MIRROR')
        self.animate(obj)
        key = _make_key_from_obj('geometry_independent.key', obj, self.scene)
        self.assertEqual((key.numJoints, len(key.nodes)), (1, 1))

    def wrapper(self):
        root = bpy.data.objects.new('wrapper', None)
        self.scene.collection.objects.link(root)
        obj = self.joint(parent=root)
        self.animate(obj)
        return root, obj

    def test_animated_wrapper_fails_without_changing_settings_or_existing_output(self):
        root, obj = self.wrapper()
        path = self.folder / 'wrapper.key'
        path.write_bytes(b'previous export')
        # Every active rotation representation must be covered, not only Euler.
        for channel in ('location', 'rotation_euler', 'rotation_quaternion', 'rotation_axis_angle'):
            root.animation_data_clear()
            root.keyframe_insert(data_path=channel, frame=0)
            before = self.scene_metadata()
            with self.subTest(channel=channel), self.assertRaisesRegex(ValueError, 'animated model wrapper'):
                exportKey(root, self.scene, str(path))
            self.assertEqual(self.scene_metadata(), before)
            self.assertEqual(path.read_bytes(), b'previous export')

    def test_muted_wrapper_curves_and_nontransform_animation_remain_supported(self):
        root, obj = self.wrapper()
        root.location = (2, 3, 4)
        root.keyframe_insert(data_path='location', frame=0)
        for curve in getActionFCurves(root):
            curve.mute = True
        root['custom_value'] = 1.0
        root.keyframe_insert(data_path='["custom_value"]', frame=0)
        key = _make_key_from_obj('static_wrapper.key', root, self.scene)
        self.assertEqual((key.numJoints, len(key.nodes)), (1, 1))
        self.assert_vector(makeModel3doFromObj('static.3do', root).insertOffset, (2, 3, 4))

    def test_wrapper_transform_drivers_must_be_baked(self):
        root, obj = self.wrapper()
        driver = root.driver_add('location', 0)
        driver.driver.expression = 'frame / 10'
        with self.assertRaisesRegex(ValueError, 'wrapper transform drivers'):
            _make_key_from_obj('driven.key', root, self.scene)
        driver.mute = True
        self.assertEqual(_make_key_from_obj('muted.key', root, self.scene).numJoints, 1)

    def test_wrapper_nla_must_be_baked_unless_the_track_is_muted(self):
        root, obj = self.wrapper()
        self.animate(root)
        data = root.animation_data
        action = data.action
        track = data.nla_tracks.new()
        track.strips.new('wrapper motion', 0, action)
        data.action = None
        with self.assertRaisesRegex(ValueError, 'wrapper NLA'):
            _make_key_from_obj('nla.key', root, self.scene)
        track.mute = True
        self.assertEqual(_make_key_from_obj('muted_nla.key', root, self.scene).numJoints, 1)

    def assert_static_pivot_matches_blender(self, root, obj):
        # Compare exported vertex placement with Blender's evaluated constraint,
        # rather than checking against a second copy of the conversion formula.
        bpy.context.view_layer.update()
        actual = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world.copy()
        model = makeModel3doFromObj('pivot.3do', root)
        node = model.meshHierarchy[0]
        matrix = utils.makeRotationMatrix(*node.rotation).to_4x4()
        matrix.translation = node.position
        matrix = (mathutils.Matrix.Translation(model.insertOffset) @ matrix
                  @ mathutils.Matrix.Translation(node.pivot))
        exported = model.geosets[0].meshes[node.meshIdx]
        for vertex, source in zip(exported.vertices, obj.data.vertices):
            self.assert_vector(matrix @ mathutils.Vector(vertex), actual @ source.co)

    def test_static_pivot_targets_use_evaluated_world_coordinates(self):
        obj = self.joint()
        obj.rotation_mode = utils.kImEulerOrder
        obj.location, obj.rotation_euler.z = (3, 1, 0), math.pi / 2
        parent = bpy.data.objects.new('target_parent', None)
        target = bpy.data.objects.new('target', None)
        for item in (parent, target):
            self.scene.collection.objects.link(item)
        parent.location, target.location, target.parent = (10, 0, 0), (2, 0, 0), parent
        constraint = obj.constraints.new('PIVOT')
        constraint.rotation_range, constraint.target, constraint.offset = 'ALWAYS_ACTIVE', target, (1, 0.5, 0)
        self.assert_static_pivot_matches_blender(obj, obj)

        # Target constraints and rotation/scale in its ancestry affect its world point.
        parent.rotation_euler.z, parent.scale = math.pi / 2, (2, 2, 2)
        self.assert_static_pivot_matches_blender(obj, obj)
        target.constraints.new('COPY_LOCATION').target = parent
        self.assert_static_pivot_matches_blender(obj, obj)

    def test_static_target_pivot_converts_translated_uniformly_scaled_owner_parent(self):
        root = bpy.data.objects.new('wrapper', None)
        self.scene.collection.objects.link(root)
        root.location, root.scale = (3, 4, 0), (2, 2, 2)
        obj = self.joint(parent=root)
        obj.location, obj.rotation_euler.z = (1, 2, 0), math.pi / 2
        target = bpy.data.objects.new('target', None)
        self.scene.collection.objects.link(target)
        target.location = (12, 1, 0)
        constraint = obj.constraints.new('PIVOT')
        constraint.rotation_range, constraint.target = 'ALWAYS_ACTIVE', target
        self.assert_static_pivot_matches_blender(root, obj)

    def test_static_relative_absolute_and_conditional_pivots_match_blender(self):
        obj = self.joint()
        obj.location, obj.rotation_euler.x = (3, 1, 0), math.pi / 4
        constraint = obj.constraints.new('PIVOT')
        constraint.offset = (2, 0, 1)
        for relative in (False, True):
            for rotation_range in ('ALWAYS_ACTIVE', 'NX', 'X'):
                with self.subTest(relative=relative, rotation_range=rotation_range):
                    constraint.use_relative_location = relative
                    constraint.rotation_range = rotation_range
                    self.assert_static_pivot_matches_blender(obj, obj)

    def test_world_anchored_pivots_are_rejected_before_key_import_or_export_mutates_data(self):
        obj = self.joint()
        self.animate(obj)
        target = bpy.data.objects.new('target', None)
        self.scene.collection.objects.link(target)
        constraint = obj.constraints.new('PIVOT')
        path = self.folder / 'world_pivot.key'
        key = Key('world_pivot.key')
        key.numFrames, key.numJoints, key.fps = 3, 1, 30
        node = KeyNode()
        node.idx, node.meshName, node.keyframes = 0, 'joint', [Keyframe()]
        key.nodes = [node]
        saveKey(key, path, '')
        before_file, before_scene, action = path.read_bytes(), self.scene_metadata(), obj.animation_data.action
        for with_target in (True, False):
            constraint.target = target if with_target else None
            constraint.use_relative_location = with_target
            with self.subTest(target=with_target):
                with self.assertRaisesRegex(ValueError, 'world-anchored Pivot'):
                    exportKey(obj, self.scene, str(path))
                with self.assertRaisesRegex(ValueError, 'world-anchored Pivot'):
                    importKey(path, self.scene, True, True, False)
                self.assertEqual(path.read_bytes(), before_file)
                self.assertEqual(self.scene_metadata(), before_scene)
                self.assertEqual(obj.animation_data.action, action)

    def test_complex_pivot_stacks_and_spaces_require_baking(self):
        obj = self.joint()
        constraint = obj.constraints.new('PIVOT')
        constraint.offset = (1, 0, 0)
        constraint.owner_space = 'LOCAL'
        with self.assertRaisesRegex(ValueError, 'Pivot constraint spaces'):
            makeModel3doFromObj('local.3do', obj)
        constraint.owner_space = 'WORLD'
        extra = obj.constraints.new('PIVOT')
        with self.assertRaisesRegex(ValueError, 'multiple Pivot'):
            makeModel3doFromObj('stack.3do', obj)
        extra.mute = True
        self.assertEqual(len(makeModel3doFromObj('muted.3do', obj).meshHierarchy), 1)

    def test_conditional_pivot_rotation_requires_baking_or_an_always_active_pivot(self):
        obj = self.joint()
        constraint = obj.constraints.new('PIVOT')
        constraint.offset = (1, 0, 0)
        for frame, value in ((0, -0.5), (9, 0.5)):
            obj.rotation_euler.x = value
            obj.keyframe_insert(data_path='rotation_euler', frame=frame)
        with self.assertRaisesRegex(ValueError, 'conditional/world-space Pivot rotation'):
            _make_key_from_obj('conditional.key', obj, self.scene)
        constraint.rotation_range = 'ALWAYS_ACTIVE'
        self.assertEqual(len(_make_key_from_obj('always.key', obj, self.scene).nodes), 1)
