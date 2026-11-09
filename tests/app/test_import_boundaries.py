"""Unsafe input must fail before replacing the current scene or animation."""
import math
from pathlib import Path
import tempfile

import bpy
import mathutils

from app.support import SceneTestCase
from sith.key import Key, KeyNode, Keyframe, KeyframeFlag, KeyMarker, KeyMarkerType
from sith.key.keyExporter import _make_key_from_obj
from sith.key.keyImporter import importKey, _key_position_to_blender
from sith.key.keyUtils import prepareSceneFrameRate, setSceneFrameRate, getSceneFrameRate
from sith.key.keyLoader import loadKey
from sith.key.keyWriter import saveKey
from sith.model.model3doExporter import makeModel3doFromObj
from sith.model.model3doImporter import import3do
from sith.model.model3doLoader import load3do
from sith.model.model3doWriter import save3do
from sith.model.utils import kImEulerOrder, makeRotationMatrix
from sith.types import Vector3f, Vector4f, Vector2f
from sith.utils import validateFloat32, kFloat32Max

TV = Path(__file__).resolve().parents[1] / 'tv'


class ImportBoundaryTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.scene = bpy.context.scene
        self.scene.frame_start, self.scene.frame_end = 0, 4
        self.scene.render.fps, self.scene.render.fps_base = 30, 1
        self.scene.sith_key_flags, self.scene.sith_key_types = set(), 'ffff'
        self.scene.timeline_markers.clear()
        self.scene.timeline_markers.new('LeftFoot', frame=2)
        self.obj = self.joint('joint', 0)
        self.obj.keyframe_insert(data_path='location', frame=0)
        self.scene.frame_set(0)

    def joint(self, name, index, parent=None):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        obj = bpy.data.objects.new(name, mesh)
        self.scene.collection.objects.link(obj)
        obj.parent, obj.rotation_mode = parent, kImEulerOrder
        obj.sith_model3do_hnode_idx, obj.sith_model3do_hnode_name = index, name
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        return obj

    def snapshot(self):
        return (set(bpy.data.objects), self.obj.animation_data.action.as_pointer(),
                self.scene.frame_start, self.scene.frame_end, self.scene.render.fps,
                self.scene.render.fps_base, [(m.name, m.frame) for m in self.scene.timeline_markers],
                self.scene.frame_step, self.scene.frame_current, self.scene.frame_subframe,
                set(self.scene.sith_key_flags), self.scene.sith_key_types,
                tuple(self.obj.location), tuple(self.obj.rotation_euler))

    def write_key(self, entries, frames=5):
        key = Key('boundary.key')
        key.numFrames, key.numJoints, key.fps = frames, 1, 30
        node = KeyNode()
        node.idx, node.meshName, node.keyframes = 0, 'joint', entries
        key.nodes = [node]
        path = self.folder / key.name
        saveKey(key, path, '')
        return key, path

    def test_float32_limits_and_nonfinite_values(self):
        validateFloat32((0, kFloat32Max, -kFloat32Max, 1e-40), 'values')
        for value in (math.nextafter(kFloat32Max, math.inf), 1e100, -1e100, math.inf, -math.inf, math.nan):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'float32'):
                validateFloat32((value,), 'values')

    def test_overflow_vector_rejects_before_clear_in_strict_and_recovery_modes(self):
        path = TV / 'model/float32_overflow.3do'
        before, contents = self.snapshot(), path.read_bytes()
        for clear in (False, True):
            for recover in (False, True):
                with self.subTest(clear=clear, recover=recover), self.assertRaisesRegex(ValueError, 'float32'):
                    import3do(path, clearScene=clear, allowErrors=recover)
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(path.read_bytes(), contents)

    def test_every_3do_numeric_field_rejects_float32_overflow_before_clear(self):
        changes = (
            lambda m, v: setattr(m, 'radius', v),
            lambda m, v: setattr(m, 'insertOffset', Vector3f(v, 0, 0)),
            lambda m, v: setattr(m.meshHierarchy[0], 'position', Vector3f(v, 0, 0)),
            lambda m, v: setattr(m.meshHierarchy[0], 'rotation', Vector3f(v, 0, 0)),
            lambda m, v: setattr(m.meshHierarchy[1], 'pivot', Vector3f(v, 0, 0)),
            lambda m, v: setattr(m.geosets[0].meshes[0], 'radius', v),
            lambda m, v: m.geosets[0].meshes[0].vertices.__setitem__(0, Vector3f(v, 0, 0)),
            lambda m, v: m.geosets[0].meshes[0].normals.__setitem__(0, Vector3f(v, 0, 0)),
            lambda m, v: m.geosets[0].meshes[0].vertexColors.__setitem__(0, Vector4f(v, 0, 0, 1)),
            lambda m, v: m.geosets[0].meshes[0].uvs.__setitem__(0, Vector2f(v, 0)),
            lambda m, v: setattr(m.geosets[0].meshes[0].faces[0], 'normal', Vector3f(v, 0, 0)),
            lambda m, v: setattr(m.geosets[0].meshes[0].faces[0], 'color', Vector4f(v, 0, 0, 1)),
        )
        before = self.snapshot()
        for index, change in enumerate(changes):
            for value in (1e100, -1e100):
                model, version = load3do(TV / 'model/triangle.3do')
                # The writer also rejects overflow now. Serialize a valid,
                # unique sentinel, then hand-corrupt that field as an external
                # file could; do not bypass the importer's validation.
                change(model, 123.45678)
                path = self.folder / 'overflow.3do'
                save3do(model, path, version, '')
                text = path.read_text()
                self.assertEqual(text.count('123.45678'), 1)
                path.write_text(text.replace('123.45678', repr(value)))
                with self.subTest(field=index, value=value), self.assertRaisesRegex(ValueError, 'float32'):
                    import3do(path, clearScene=True)
                self.assertEqual(self.snapshot(), before)

    def test_pivot_and_hierarchy_arithmetic_overflow_is_rejected_before_clear(self):
        before = self.snapshot()
        for pivot_overflow in (False, True):
            model, version = load3do(TV / 'model/triangle.3do')
            if pivot_overflow:
                model.geosets[0].meshes[0].vertices[0] = Vector3f(3e38, 0, 0)
                model.meshHierarchy[1].pivot = Vector3f(3e38, 0, 0)
            else:
                model.meshHierarchy[0].position = model.meshHierarchy[1].position = Vector3f(3e38, 0, 0)
            path = self.folder / 'derived.3do'
            save3do(model, path, version, '')
            with self.subTest(pivot=pivot_overflow), self.assertRaisesRegex(ValueError, 'Transformed'):
                import3do(path, clearScene=True)
            self.assertEqual(self.snapshot(), before)

    def test_key_numeric_and_extrapolation_overflow_preserve_existing_animation(self):
        before = self.snapshot()
        for index, attribute in enumerate(('position', 'orientation', 'deltaPosition', 'deltaRotation')):
            # Hand-author invalid input: the production writer now rejects it
            # before opening a file, independently of the import-side check.
            values = ['0'] * 12
            values[index * 3] = '1e100'
            path = self.folder / 'overflow.key'
            path.write_text('SECTION: HEADER\nFLAGS 0\nTYPE 0\nFRAMES 5\nFPS 30\nJOINTS 1\n'
                            'SECTION: KEYFRAME NODES\nNODES 1\nNODE 0\nMESH NAME joint\nENTRIES 1\n'
                            '0: 0 0 ' + ' '.join(values[:6]) + '\n' + ' '.join(values[6:]) + '\n')
            with self.subTest(attribute=attribute), self.assertRaisesRegex(ValueError, 'float32'):
                importKey(path, self.scene, True, True, False)
            self.assertEqual(self.snapshot(), before)

        entry = Keyframe()
        entry.flags, entry.deltaPosition = KeyframeFlag.PositionChange, Vector3f(3e38, 0, 0)
        _, path = self.write_key([entry])
        with self.assertRaisesRegex(ValueError, 'KEY sample'):
            importKey(path, self.scene, True, True, False)
        self.assertEqual(self.snapshot(), before)

    def test_oversized_timeline_vector_fails_without_clearing_animation(self):
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'timeline limits'):
            importKey(TV / 'key/oversized_timeline.key', self.scene, True, True, False)
        self.assertEqual(self.snapshot(), before)

    def test_largest_supported_timeline_preserves_its_length(self):
        frames = bpy.types.Scene.bl_rna.properties['frame_end'].hard_max + 1
        _, path = self.write_key([Keyframe()], frames)
        importKey(path, self.scene, True, True, False)
        self.assertEqual(self.scene.frame_end, frames - 1)
        self.assertEqual(_make_key_from_obj('maximum.key', self.obj, self.scene).numFrames, frames)

    def test_out_of_range_marker_rejection_preserves_animation(self):
        before = self.snapshot()
        bounds = bpy.types.TimelineMarker.bl_rna.properties['frame']
        for frame in (bounds.hard_min - 1, bounds.hard_max + 1):
            key, path = self.write_key([Keyframe()])
            marker = KeyMarker()
            marker.frame, marker.type = frame, KeyMarkerType.LeftFoot
            key.markers = [marker]
            saveKey(key, path, '')
            with self.subTest(frame=frame), self.assertRaisesRegex(ValueError, 'marker limits'):
                importKey(path, self.scene, True, True, False)
            self.assertEqual(self.snapshot(), before)

    def pivot_key(self):
        first, last = Keyframe(), Keyframe()
        first.flags = KeyframeFlag.OrientationChange
        first.orientation, first.deltaRotation = Vector3f(-30, 0, 0), Vector3f(15, 0, 0)
        last.frame, last.orientation = 4, Vector3f(30, 0, 0)
        return self.write_key([first, last])

    def test_conditional_pivot_import_is_rejected_before_replace_or_merge(self):
        pivot = self.obj.constraints.new('PIVOT')
        pivot.offset = (0, 1, 0)
        _, path = self.pivot_key()
        before = self.snapshot()
        for clear in (False, True):
            with self.subTest(clear=clear), self.assertRaisesRegex(ValueError, 'conditional Pivot'):
                importKey(path, self.scene, clear, True, False)
            self.assertEqual(self.snapshot(), before)

    def test_always_active_pivot_import_matches_engine_poses_across_rotation_signs(self):
        pivot = self.obj.constraints.new('PIVOT')
        pivot.offset, pivot.rotation_range = (0, 1, 0), 'ALWAYS_ACTIVE'
        mesh_pivot = mathutils.Vector(makeModel3doFromObj('pivot.3do', self.obj).meshHierarchy[0].pivot)
        _, path = self.pivot_key()
        importKey(path, self.scene, True, True, False)
        for frame in (0, 1, 2, 3, 4):
            self.scene.frame_set(frame)
            actual = self.obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world.translation
            self.assert_vector(actual, makeRotationMatrix(-30 + frame * 15, 0, 0) @ mesh_pivot)

    def test_incoming_parent_rotation_is_rejected_before_applying_any_joint(self):
        child = self.joint('child', 1, self.obj)
        child.constraints.new('PIVOT').rotation_range = 'ALWAYS_ACTIVE'
        key, path = self.write_key([Keyframe()])
        key.numJoints = 2
        key.nodes[0].keyframes[0].orientation = Vector3f(30, 0, 0)
        node = KeyNode()
        node.idx, node.meshName, node.keyframes = 1, 'child', [Keyframe()]
        key.nodes.append(node)
        saveKey(key, path, '')
        bpy.context.view_layer.objects.active = self.obj
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'parent rotation'):
            importKey(path, self.scene, True, True, False)
        self.assertEqual(self.snapshot(), before)

    def test_disabled_pivot_does_not_block_import(self):
        pivot = self.obj.constraints.new('PIVOT')
        _, path = self.pivot_key()
        for mute, influence in ((True, 1), (False, 0)):
            pivot.mute, pivot.influence = mute, influence
            importKey(path, self.scene, True, True, False)
            self.scene.frame_set(4)
            self.assertAlmostEqual(self.obj.rotation_euler.x, math.radians(30), places=5)

    def test_fps_preparation_is_non_mutating_and_uses_rna_bounds(self):
        ranges = self.scene.render.bl_rna.properties
        minimum = ranges['fps'].hard_min / ranges['fps_base'].hard_max
        maximum = ranges['fps'].hard_max / ranges['fps_base'].hard_min
        for fps in (minimum, 1e-5, 0.5, 24, 59.94, 24000 / 1001, 144, 3600, maximum):
            with self.subTest(fps=fps):
                before = self.snapshot()
                numerator, base = prepareSceneFrameRate(self.scene, fps)
                self.assertEqual(self.snapshot(), before)
                self.assertTrue(math.isclose(numerator / base, fps, rel_tol=1e-7))
                setSceneFrameRate(self.scene, fps)
                self.assertTrue(math.isclose(getSceneFrameRate(self.scene), fps, rel_tol=1e-7))

    def test_unsupported_fps_setter_does_not_mutate_playback(self):
        before = self.snapshot()
        for fps in (0, -1, math.nan, math.inf, 1e-20, 1e20, 1e100):
            with self.subTest(fps=fps), self.assertRaisesRegex(ValueError, 'FPS'):
                setSceneFrameRate(self.scene, fps)
            self.assertEqual(self.snapshot(), before)

    def test_unsupported_fps_import_preserves_animation_and_metadata(self):
        before = self.snapshot()
        for fps in ('1e-20', '1e20', '1e100'):
            # Write the unsupported rate directly so this exercises import
            # preflight independently of export validation and formatting.
            path = self.folder / 'fps.key'
            path.write_text('SECTION: HEADER\nFLAGS 2\nTYPE 0x8008\nFRAMES 5\n'
                            f'FPS {fps}\nJOINTS 1\nSECTION: KEYFRAME NODES\nNODES 1\n'
                            'NODE 0\nMESH NAME joint\nENTRIES 1\n0: 0 0 0 0 0 0 0 0\n0 0 0 0 0 0\n')
            for clear in (False, True):
                with self.subTest(fps=fps, clear=clear), self.assertRaisesRegex(ValueError, 'FPS'):
                    importKey(path, self.scene, clear, True, False)
                self.assertEqual(self.snapshot(), before)

    def test_unsupported_export_fps_preserves_old_file_and_scene_settings(self):
        path = self.folder / 'unchanged.key'
        path.write_bytes(b'previous export')
        before = self.snapshot()
        for fps in (1e-20, 1e20):
            with self.subTest(fps=fps), self.assertRaisesRegex(RuntimeError, 'FPS'):
                bpy.ops.export_anim.sith_key(filepath=str(path), fps=fps, flags={'NoLoop'}, node_types='8008')
            self.assertEqual(path.read_bytes(), b'previous export')
            self.assertEqual(self.snapshot(), before)

    def test_low_representable_export_fps_is_not_clamped_by_the_dialog_property(self):
        path = self.folder / 'slow.key'
        self.assertEqual(bpy.ops.export_anim.sith_key(filepath=str(path), fps=1e-5), {'FINISHED'})
        self.assertAlmostEqual(loadKey(path).fps, 1e-5, delta=1e-12)
        self.assertTrue(math.isclose(getSceneFrameRate(self.scene), 1e-5, rel_tol=1e-7))

    def test_pivot_adjustment_overflow_rejects_before_replace_or_merge(self):
        pivot = self.obj.constraints.new('PIVOT')
        pivot.rotation_range = 'ALWAYS_ACTIVE'
        before = self.snapshot()
        for sign in (-1, 1):
            pivot.offset = (-sign * 3e38, 0, 0)
            entry = Keyframe()
            entry.position = Vector3f(sign * 3e38, 0, 0)
            _, path = self.write_key([entry])
            for clear in (False, True):
                with self.subTest(sign=sign, clear=clear), self.assertRaisesRegex(ValueError, 'Pivot-adjusted KEY position'):
                    importKey(path, self.scene, clear, True, False)
                self.assertEqual(self.snapshot(), before)

    def test_later_joint_adjustment_failure_preserves_all_earlier_actions(self):
        child = self.joint('child', 1, self.obj)
        child.keyframe_insert(data_path='location', frame=0)
        pivot = child.constraints.new('PIVOT')
        pivot.rotation_range, pivot.offset = 'ALWAYS_ACTIVE', (-3e38, 0, 0)
        child_action = child.animation_data.action.as_pointer()
        key, path = self.write_key([Keyframe()])
        key.numJoints = 2
        node = KeyNode()
        node.idx, node.meshName, node.keyframes = 1, 'child', [Keyframe()]
        node.keyframes[0].position = Vector3f(3e38, 0, 0)
        key.nodes.append(node)
        saveKey(key, path, '')
        bpy.context.view_layer.objects.active = self.obj
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'Pivot-adjusted KEY position'):
            importKey(path, self.scene, True, True, False)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(child.animation_data.action.as_pointer(), child_action)

    def test_adjusted_positions_preserve_float32_operand_semantics(self):
        for value in (0.1, 3e38):
            rounded = mathutils.Vector((value, 0, 0)).x
            self.assertEqual(_key_position_to_blender((value, 0, 0), (-rounded, 0, 0)), (0, 0, 0))

    def test_safe_adjustment_and_extrapolated_samples_import_correctly(self):
        pivot = self.obj.constraints.new('PIVOT')
        pivot.rotation_range, pivot.offset = 'ALWAYS_ACTIVE', (2, 0, 0)
        entry = Keyframe()
        entry.position, entry.deltaPosition = Vector3f(3, 4, 5), Vector3f(1, 0, 0)
        entry.flags = KeyframeFlag.PositionChange
        _, path = self.write_key([entry])
        importKey(path, self.scene, True, True, False)
        for frame in (0, 2, 4):
            self.scene.frame_set(frame)
            self.assert_vector(self.obj.location, (1 + frame, 4, 5))
