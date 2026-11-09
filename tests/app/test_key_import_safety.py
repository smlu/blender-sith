"""Temporal/Pivot preflights preserve scenes; inactive NLA preserves source clips."""
import math
from pathlib import Path
import tempfile

import bpy
import mathutils

from app.support import SceneTestCase
from app.test_key import sample_key
from fixtures import TV
from sith.key import Key, KeyNode, Keyframe, KeyframeFlag
from sith.key.keyExporter import exportKey
from sith.key.keyImporter import importKey, _insert_import_samples
from sith.key.keyLoader import loadKey
from sith.key.keyUtils import getActionFCurves, getActionSlotFCurves, setSceneKeyFlags
from sith.key.keyWriter import saveKey
from sith.model.utils import kImEulerOrder, makeRotationMatrix, objPivot
from sith.types import Vector3f


def held(frame, x, yaw=0):
    value = Keyframe()
    value.frame, value.position, value.orientation = frame, Vector3f(x, 0, 0), Vector3f(0, yaw, 0)
    return value


def curve_state(action, slot):
    return [(curve.data_path, curve.array_index, curve.mute, curve.extrapolation,
             [(tuple(point.co), point.interpolation, tuple(point.handle_left), tuple(point.handle_right))
              for point in curve.keyframe_points]) for curve in getActionSlotFCurves(action, slot)]


class _ImportSafetyCase(SceneTestCase):
    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.counter = 0
        self.scene = bpy.context.scene
        self.scene.frame_start, self.scene.frame_end, self.scene.frame_step = 0, 10, 2
        self.scene.render.fps, self.scene.render.fps_base = 48, 1
        self.scene.timeline_markers.clear()
        self.scene.timeline_markers.new('existing', frame=8)
        setSceneKeyFlags(self.scene, 0x80000002)
        self.scene.sith_key_types = '81234567'
        self.root = self.joint('wrapper', -1)
        self.obj = self.joint('joint', 0, self.root)
        self.obj.location.x = 9
        for frame in (0, 10):
            self.obj.keyframe_insert(data_path='location', frame=frame)
            self.obj.keyframe_insert(data_path='rotation_euler', frame=frame)
        self.scene.frame_set(0)
        bpy.context.view_layer.objects.active = self.root
        self.root.select_set(True)

    def joint(self, name, index, parent=None):
        obj = bpy.data.objects.new(name, None)
        self.scene.collection.objects.link(obj)
        obj.parent, obj.rotation_mode = parent, kImEulerOrder
        obj.sith_model3do_hnode_idx, obj.sith_model3do_hnode_name = index, name
        return obj

    def key_file(self, entries, *, later=None, joints=1, frames=5):
        self.counter += 1
        key, node = Key(f'safety-{self.counter}.key'), KeyNode()
        key.numJoints, key.numFrames, key.fps = joints, frames, 30
        node.idx, node.meshName, node.keyframes = 0, 'joint', entries
        key.nodes = [node] + ([later] if later is not None else [])
        path = self.folder / key.name
        saveKey(key, path, '')
        return key, path

    def snapshot(self):
        objects = []
        for obj in bpy.data.objects:
            animation = obj.animation_data
            objects.append((obj.as_pointer(), tuple(obj.location), obj.rotation_mode,
                            tuple(obj.rotation_euler), tuple(obj.rotation_quaternion), tuple(obj.rotation_axis_angle),
                            animation.action.as_pointer() if animation and animation.action else None,
                            animation.action_slot.identifier if animation and animation.action_slot else None,
                            animation.use_nla if animation else None,
                            [(driver.data_path, driver.array_index, driver.mute, driver.driver.expression)
                             for driver in animation.drivers] if animation else [],
                            [(track.mute, [(strip.mute, strip.action.as_pointer() if strip.action else None)
                                           for strip in track.strips]) for track in animation.nla_tracks] if animation else []))
        actions = [(action.as_pointer(), [(slot.identifier, curve_state(action, slot)) for slot in action.slots])
                   for action in bpy.data.actions]
        return (self.scene.frame_start, self.scene.frame_end, self.scene.frame_step,
                self.scene.frame_current, self.scene.frame_subframe,
                self.scene.render.fps, self.scene.render.fps_base,
                [(marker.name, marker.frame) for marker in self.scene.timeline_markers],
                set(self.scene.sith_key_flags), self.scene.sith_key_types,
                self.scene.get('_sith_key_unknown_flags'), objects, actions)

    def reject(self, path, message, *, clear=False, operator=False):
        before, contents = self.snapshot(), path.read_bytes()
        with self.assertRaisesRegex(RuntimeError if operator else ValueError, message):
            if operator:
                bpy.ops.import_anim.sith_key(filepath=str(path), clear_scene=clear)
            else:
                importKey(path, self.scene, clear, True, False)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(path.read_bytes(), contents)

    def assert_poses(self, obj, node, frames):
        for frame in frames:
            self.scene.frame_set(math.floor(frame), subframe=frame % 1)
            actual = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
            position, rotation = sample_key(node, frame)
            with self.subTest(frame=frame):
                self.assert_vector(actual.matrix_local.translation, position)
                expected = makeRotationMatrix(*rotation)
                for row in range(3):
                    self.assert_vector(actual.matrix_local[row][:3], expected[row])

    def share_action(self):
        outsider = self.joint('other_user', -1)
        outsider.animation_data_create()
        outsider.animation_data.action = self.obj.animation_data.action
        outsider.animation_data.action_slot = self.obj.animation_data.action_slot
        # Resolve the new user's animation before comparing snapshots. A later
        # operator's normal dependency-graph update is not an import mutation.
        self.scene.frame_set(self.scene.frame_current, subframe=self.scene.frame_subframe)
        return outsider


class TemporalImportSafetyTests(_ImportSafetyCase):
    def test_close_held_vector_rejects_before_replace_or_merge(self):
        for clear in (False, True):
            for operator in (False, True):
                with self.subTest(clear=clear, operator=operator):
                    self.reject(TV / 'key/held_too_close.key', 'precision', clear=clear, operator=operator)

    def test_close_held_rotation_is_checked_without_position_changes(self):
        _, path = self.key_file([held(0, 0), held(1, 0, 10), held(1.00005, 0, 20)])
        self.reject(path, 'precision', clear=True)

    def test_float32_time_collision_rejects_before_action_copy(self):
        self.share_action()
        self.reject(TV / 'key/held_float32_collision.key', 'precision')

    def test_harmless_nearby_identical_poses_remain_importable(self):
        key, path = self.key_file([held(0, 1), held(0.00005, 1), held(1, 1)])
        importKey(path, self.scene, True, True, False)
        self.assert_poses(self.obj, key.nodes[0], (0, 0.000025, 0.00005, 0.5, 4))

    def test_separated_hold_vector_matches_visible_and_exported_poses(self):
        path = TV / 'key/held_separated.key'
        source = loadKey(path)
        importKey(path, self.scene, True, True, False)
        frames = (0, 0.5, 1, 1.001, 1.005, 2, 4)
        self.assert_poses(self.obj, source.nodes[0], frames)
        output = self.folder / 'separated.key'
        exportKey(self.root, self.scene, str(output))
        restored = loadKey(output)
        for frame in frames:
            self.assert_vector(sample_key(restored.nodes[0], frame)[0], sample_key(source.nodes[0], frame)[0])

    def test_fuzzy_limit_is_checked_after_float32_time_rounding(self):
        # Both requested times differ by > 0.0001, but their stored float32 gap
        # is smaller. Looking only at Python's source times would miss this.
        _, path = self.key_file([held(0, 1), held(100, 2), held(100.000101, 3)], frames=105)
        self.reject(path, 'precision', clear=True)

    def test_nearby_existing_merge_key_rejects_before_any_mutation(self):
        self.obj.location.x = 9
        self.obj.keyframe_insert(data_path='location', frame=1.00005)
        self.scene.frame_set(0)
        _, path = self.key_file([held(0, 1), held(1, 2), held(4, 2)])
        self.share_action()
        self.reject(path, 'precision')

    def test_identical_nearby_merge_values_keep_unrelated_keys(self):
        self.obj.location.x = 2
        self.obj.keyframe_insert(data_path='location', index=0, frame=1.00005)
        key, path = self.key_file([held(0, 1), held(1, 2), held(4, 2)])
        importKey(path, self.scene, False, True, False)
        self.assert_poses(self.obj, key.nodes[0], (0, 0.5, 1, 1.000025, 1.00005, 4))
        self.scene.frame_set(10)
        self.assertAlmostEqual(self.obj.location.x, 9)

    def test_direct_insertion_rejects_bad_times_without_changing_pose(self):
        samples = [held(0, 1), held(1, 2), held(1.00005, 3)]
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'precision'):
            _insert_import_samples(self.obj, samples, positions=[sample.position for sample in samples])
        self.assertEqual(self.snapshot(), before)

    def test_later_joint_precision_failure_preserves_earlier_shared_action(self):
        self.share_action()
        later = self.joint('later', 1, self.obj)
        later.keyframe_insert(data_path='location', frame=0)
        node = KeyNode()
        node.idx, node.meshName = 1, 'later'
        node.keyframes = [held(0, 1), held(1, 2), held(1.00005, 3)]
        _, path = self.key_file([held(0, 1)], later=node, joints=2)
        self.reject(path, 'precision', operator=True)


class PivotParentImportSafetyTests(_ImportSafetyCase):
    def hierarchy(self):
        parent = self.joint('parent', 1, self.root)
        child = self.joint('child', 2, parent)
        child.keyframe_insert(data_path='location', frame=8)
        pivot = child.constraints.new('PIVOT')
        pivot.rotation_range, pivot.use_relative_location, pivot.offset = 'ALWAYS_ACTIVE', True, (0, 1, 0)
        node = KeyNode()
        node.idx, node.meshName, node.keyframes = 2, 'child', [held(0, 0)]
        return parent, child, node

    def parent_clip(self, parent, *, location=False):
        path = 'location' if location else 'rotation_euler'
        for frame, value in ((0, 0), (4, math.pi / 2)):
            getattr(parent, path)[2] = value
            parent.keyframe_insert(data_path=path, frame=frame)
        for curve in getActionFCurves(parent):
            for point in curve.keyframe_points:
                point.interpolation = 'LINEAR'
        animation = parent.animation_data
        action, slot = animation.action, animation.action_slot
        track = animation.nla_tracks.new()
        strip = track.strips.new('parent_motion', 0, action)
        strip.action_slot, animation.action = slot, None
        parent.rotation_euler = (0, 0, 0)
        parent.location = (0, 0, 0)
        self.scene.frame_set(0)
        return track, strip

    def assert_pivot_poses(self, parent, child, mesh_pivot):
        for frame in (0, 1, 2, 3, 4):
            self.scene.frame_set(frame)
            graph = bpy.context.evaluated_depsgraph_get()
            actual = child.evaluated_get(graph).matrix_world.translation
            expected = parent.evaluated_get(graph).matrix_world @ mesh_pivot
            self.assert_vector(actual, expected)

    def test_driven_parent_rotation_rejects_before_earlier_joint_changes(self):
        parent, _, node = self.hierarchy()
        self.share_action()
        _, path = self.key_file([held(0, 1)], later=node, joints=3)
        for mode, channel, axis in (('YXZ', 'rotation_euler', 2),
                                    ('QUATERNION', 'rotation_quaternion', 3),
                                    ('AXIS_ANGLE', 'rotation_axis_angle', 0)):
            parent.rotation_mode = mode
            parent.rotation_axis_angle = (0, 0, 0, 1)
            parent.driver_add(channel, axis).driver.expression = 'frame * pi / 8'
            self.scene.frame_set(0)
            with self.subTest(mode=mode):
                self.reject(path, 'parent rotation', operator=True)
            parent.animation_data_clear()

    def test_nla_parent_rotation_rejects_before_earlier_action_copy(self):
        parent, _, node = self.hierarchy()
        self.parent_clip(parent)
        self.share_action()
        _, path = self.key_file([held(0, 1)], later=node, joints=3)
        self.reject(path, 'parent rotation')

    def test_driven_grandparent_rotation_is_checked_too(self):
        parent, _, node = self.hierarchy()
        grandparent = self.joint('grandparent', 3, self.root)
        parent.parent = grandparent
        grandparent.driver_add('rotation_euler', 2).driver.expression = 'frame * pi / 8'
        self.scene.frame_set(0)
        _, path = self.key_file([held(0, 1)], later=node, joints=4)
        self.reject(path, 'parent rotation')

    def test_muted_parent_driver_does_not_block_a_safe_merge(self):
        parent, child, node = self.hierarchy()
        driver = parent.driver_add('rotation_euler', 2)
        driver.driver.expression, driver.mute = 'frame * pi / 8', True
        mesh_pivot = objPivot(child, forAnimation=True).copy()
        _, path = self.key_file([held(0, 1)], later=node, joints=3)
        importKey(path, self.scene, False, True, False)
        self.assertTrue(driver.mute)
        self.assert_pivot_poses(parent, child, mesh_pivot)

    def test_inactive_parent_nla_retains_source_clips_and_correct_poses(self):
        parent, child, node = self.hierarchy()
        for gate in ('global', 'track', 'strip'):
            track, strip = self.parent_clip(parent)
            animation = parent.animation_data
            animation.use_nla = gate != 'global'
            track.mute, strip.mute = gate == 'track', gate == 'strip'
            parent.rotation_euler = (0, 0, 0)
            self.scene.frame_set(0)
            action, slot = strip.action, strip.action_slot
            before = curve_state(action, slot)
            mesh_pivot = objPivot(child, forAnimation=True).copy()
            _, path = self.key_file([held(0, 1)], later=node, joints=3)
            with self.subTest(gate=gate):
                importKey(path, self.scene, False, True, False)
                self.assertEqual(strip.action, action)
                self.assertEqual(curve_state(action, slot), before)
                self.assert_pivot_poses(parent, child, mesh_pivot)
            parent.animation_data_clear()

    def test_parent_translation_driver_remains_supported(self):
        parent, child, node = self.hierarchy()
        parent.driver_add('location', 0).driver.expression = 'frame / 10'
        self.scene.frame_set(0)
        mesh_pivot = objPivot(child, forAnimation=True).copy()
        _, path = self.key_file([held(0, 1)], later=node, joints=3)
        importKey(path, self.scene, False, True, False)
        self.assert_pivot_poses(parent, child, mesh_pivot)

    def test_replacement_can_remove_existing_parent_procedural_motion(self):
        parent, child, node = self.hierarchy()
        for source in ('driver', 'nla'):
            if source == 'driver':
                parent.driver_add('rotation_euler', 2).driver.expression = 'frame * pi / 8'
            else:
                self.parent_clip(parent)
            self.scene.frame_set(0)
            mesh_pivot = objPivot(child, forAnimation=True).copy()
            _, path = self.key_file([held(0, 1)], later=node, joints=3)
            with self.subTest(source=source):
                importKey(path, self.scene, True, True, False)
                self.assertIsNone(parent.animation_data)
                self.assert_pivot_poses(parent, child, mesh_pivot)


class DormantNlaImportSafetyTests(_ImportSafetyCase):
    def rotation_clip(self, mode, gate, *, keep_active=False):
        self.obj.animation_data_clear()
        self.obj.rotation_mode = mode
        if mode == 'QUATERNION':
            self.obj.rotation_quaternion = mathutils.Quaternion((0, 0, 1), math.pi / 4)
            channel = 'rotation_quaternion'
        elif mode == 'AXIS_ANGLE':
            self.obj.rotation_axis_angle = (math.pi / 4, 0, 0, 1)
            channel = 'rotation_axis_angle'
        else:
            self.obj.rotation_euler = (0, 0, math.pi / 4)
            channel = 'rotation_euler'
        for frame in (0, 4):
            self.obj.keyframe_insert(data_path=channel, frame=frame)
        animation = self.obj.animation_data
        action, slot = animation.action, animation.action_slot
        track = animation.nla_tracks.new()
        strip = track.strips.new('old_rotation', 0, action)
        strip.action_slot = slot
        if not keep_active:
            animation.action = None
        animation.use_nla = gate != 'global'
        track.mute, strip.mute = gate == 'track', gate == 'strip'
        self.scene.frame_set(0)
        return strip

    def test_disabled_rotation_nla_allows_merge_without_editing_its_action(self):
        for mode in ('QUATERNION', 'AXIS_ANGLE', 'XYZ'):
            for gate in ('global', 'track', 'strip'):
                strip = self.rotation_clip(mode, gate)
                action, slot = strip.action, strip.action_slot
                before = curve_state(action, slot)
                flags = set(self.scene.sith_key_flags), self.scene.sith_key_types, self.scene.get('_sith_key_unknown_flags')
                key, path = self.key_file([held(0, 3)])
                with self.subTest(mode=mode, gate=gate):
                    importKey(path, self.scene, False, True, False)
                    self.assertEqual(strip.action, action)
                    self.assertEqual(curve_state(action, slot), before)
                    self.assertEqual(self.obj.animation_data.use_nla, gate != 'global')
                    self.assertEqual(self.obj.rotation_mode, kImEulerOrder)
                    self.assertNotEqual(self.obj.animation_data.action, action)
                    self.assertEqual((set(self.scene.sith_key_flags), self.scene.sith_key_types,
                                      self.scene.get('_sith_key_unknown_flags')), flags)
                    self.assert_poses(self.obj, key.nodes[0], (0, 1, 2, 4))

    def test_live_non_native_rotation_nla_still_rejects_without_mutation(self):
        _, path = self.key_file([held(0, 3)])
        for mode in ('QUATERNION', 'AXIS_ANGLE', 'XYZ'):
            self.rotation_clip(mode, 'live')
            with self.subTest(mode=mode):
                self.reject(path, 'existing rotation animation')

    def test_disabling_nla_does_not_disable_active_action_rotation_checks(self):
        self.rotation_clip('QUATERNION', 'global', keep_active=True)
        _, path = self.key_file([held(0, 3)])
        self.reject(path, 'existing rotation animation')

    def test_empty_incoming_track_does_not_change_live_rotation_nla(self):
        strip = self.rotation_clip('QUATERNION', 'live')
        action, slot = strip.action, strip.action_slot
        before = curve_state(action, slot)
        _, path = self.key_file([])
        importKey(path, self.scene, False, True, False)
        self.assertEqual(self.obj.rotation_mode, 'QUATERNION')
        self.assertIsNone(self.obj.animation_data.action)
        self.assertEqual(strip.action, action)
        self.assertEqual(curve_state(action, slot), before)
