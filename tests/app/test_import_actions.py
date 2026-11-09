"""Preflight incompatible rotation merges and localize linked animation safely."""
import hashlib
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest import mock

import bpy
import mathutils

from app.support import SceneTestCase
from sith.key import Key, KeyNode, Keyframe
from sith.key.keyImporter import importKey, _insert_import_samples
from sith.key.keyLoader import loadKey
from sith.key.keyUtils import getActionFCurves
from sith.key.keyWriter import saveKey
from sith.model.utils import kImEulerOrder
from sith.types import Vector3f


def curves(action, slot):
    return [(curve.data_path, curve.array_index, [(tuple(p.co), p.interpolation) for p in curve.keyframe_points])
            for layer in action.layers for strip in layer.strips
            for curve in strip.channelbag(slot).fcurves]


class ImportActionTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.scene = bpy.context.scene
        self.scene.frame_start, self.scene.frame_end = 3, 20
        self.scene.render.fps, self.scene.render.fps_base = 48, 1
        self.scene.timeline_markers.clear()
        self.scene.timeline_markers.new('existing', frame=8)
        self.root = bpy.data.objects.new('wrapper', None)
        self.obj = bpy.data.objects.new('joint', None)
        for obj in (self.root, self.obj):
            self.scene.collection.objects.link(obj)
        self.obj.parent, self.obj.rotation_mode = self.root, kImEulerOrder
        bpy.context.view_layer.objects.active = self.root
        key, node, entry = Key('incoming.key'), KeyNode(), Keyframe()
        key.numJoints, key.numFrames, key.fps = 1, 5, 30
        node.idx, node.meshName, node.keyframes = 0, 'joint', [entry]
        entry.position = Vector3f(1, 0, 0)
        key.nodes = [node]
        self.path = self.folder / key.name
        saveKey(key, self.path, '')

    def snapshot(self):
        animation = self.obj.animation_data
        return (self.obj.rotation_mode, self.scene.frame_start, self.scene.frame_end,
                self.scene.render.fps, self.scene.render.fps_base, self.scene.frame_current,
                [(m.name, m.frame) for m in self.scene.timeline_markers],
                animation.action.as_pointer() if animation and animation.action else None,
                curves(animation.action, animation.action_slot) if animation and animation.action else None,
                len(bpy.data.actions))

    def rotation_keys(self, mode):
        self.obj.rotation_mode = mode
        if mode == 'QUATERNION':
            self.obj.rotation_quaternion = mathutils.Quaternion((0, 0, 1), math.pi / 2)
            path = 'rotation_quaternion'
        elif mode == 'AXIS_ANGLE':
            self.obj.rotation_axis_angle = (math.pi / 2, 0, 0, 1)
            path = 'rotation_axis_angle'
        else:
            self.obj.rotation_euler = (0, 0, math.pi / 2)
            path = 'rotation_euler'
        for frame in (10, 20):
            self.obj.keyframe_insert(data_path=path, frame=frame)
        self.scene.frame_set(10)

    def test_incompatible_merges_reject_without_disabling_old_animation(self):
        for mode in ('QUATERNION', 'AXIS_ANGLE', 'XYZ'):
            self.obj.animation_data_clear()
            self.rotation_keys(mode)
            before, pose = self.snapshot(), self.obj.matrix_local.copy()
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'existing rotation animation'):
                importKey(self.path, self.scene, False, True, False)
            self.assertEqual(self.snapshot(), before)
            self.scene.frame_set(10)
            self.assertEqual(self.obj.matrix_local, pose)

    def test_replacement_can_import_over_non_native_rotation_animation(self):
        for mode in ('QUATERNION', 'AXIS_ANGLE', 'XYZ'):
            self.rotation_keys(mode)
            importKey(self.path, self.scene, True, True, False)
            self.assertEqual(self.obj.rotation_mode, kImEulerOrder)
            self.assert_vector(self.obj.location, (1, 0, 0))
            self.assertFalse(any(c.data_path in ('rotation_quaternion', 'rotation_axis_angle') for c in getActionFCurves(self.obj)))

    def test_native_euler_merge_preserves_pose_at_unrelated_keys(self):
        self.rotation_keys(kImEulerOrder)
        pose = self.obj.matrix_local.to_quaternion().copy()
        importKey(self.path, self.scene, False, True, False)
        self.scene.frame_set(10)
        self.assertLess(pose.rotation_difference(self.obj.matrix_local.to_quaternion()).angle, 1e-5)

    def test_static_quaternion_without_rotation_curves_can_be_replaced(self):
        self.obj.rotation_mode = 'QUATERNION'
        self.obj.keyframe_insert(data_path='location', frame=10)
        importKey(self.path, self.scene, False, True, False)
        self.assertEqual(self.obj.rotation_mode, kImEulerOrder)
        self.assert_vector(self.obj.location, (1, 0, 0))

    def test_linked_actions_become_local_without_modifying_library_channels(self):
        for complete in (False, True):
            self.obj.animation_data_clear()
            self.obj.location.x = 7
            self.obj.keyframe_insert(data_path='location', frame=9)
            if complete:
                self.obj.keyframe_insert(data_path='rotation_euler', frame=9)
            action = self.obj.animation_data.action
            name = action.name
            library = self.folder / ('action-' + str(complete) + '.blend')
            bpy.data.libraries.write(str(library), {action})
            self.obj.animation_data_clear()
            bpy.data.actions.remove(action)
            with bpy.data.libraries.load(str(library), link=True) as (source, destination):
                destination.actions = [name]
            linked = destination.actions[0]
            self.obj.animation_data_create()
            self.obj.animation_data.action = linked
            self.obj.animation_data.action_slot = linked.slots[0]
            slot = self.obj.animation_data.action_slot
            before, digest = curves(linked, slot), hashlib.sha256(library.read_bytes()).hexdigest()
            self.assertFalse(linked.is_editable)
            self.assertEqual(len(slot.users()), 1)
            with self.subTest(complete=complete):
                importKey(self.path, self.scene, False, True, False)
                self.assertTrue(self.obj.animation_data.action.is_editable)
                self.assertIsNone(self.obj.animation_data.action.library)
                self.assertNotEqual(self.obj.animation_data.action, linked)
                self.assertEqual(curves(linked, slot), before)
                self.assertEqual(hashlib.sha256(library.read_bytes()).hexdigest(), digest)
                self.assert_vector(self.obj.location, (1, 0, 0))
                self.scene.frame_set(9)
                self.assert_vector(self.obj.location, (7, 0, 0))

    def test_failed_channel_creation_has_a_clear_error(self):
        obj = SimpleNamespace(name='unwritable', location=None, rotation_euler=None, animation_data=None,
                              keyframe_insert=lambda **kwargs: False)
        entry = Keyframe()
        with mock.patch('sith.key.keyImporter.getActionFCurves', return_value=[]):
            with self.assertRaisesRegex(ValueError, 'Cannot create KEY channel location'):
                _insert_import_samples(obj, [entry], positions=[(0, 0, 0)])

    def test_non_native_rotation_driver_rejects_without_scene_changes(self):
        self.obj.rotation_mode = 'QUATERNION'
        self.obj.driver_add('rotation_quaternion', 0).driver.expression = '1.0'
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'existing rotation animation'):
            importKey(self.path, self.scene, False, True, False)
        self.assertEqual(self.snapshot(), before)

    def test_native_transform_drivers_reject_before_mutating_scene(self):
        for path in ('location', 'rotation_euler'):
            with self.subTest(path=path):
                self.obj.animation_data_clear()
                self.obj.rotation_mode = kImEulerOrder
                driver = self.obj.driver_add(path, 0)
                driver.driver.expression = '7.0'
                before = self.snapshot()
                with self.assertRaisesRegex(ValueError, 'transform drivers'):
                    importKey(self.path, self.scene, False, True, False)
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(driver.driver.expression, '7.0')

    def test_location_driver_rejects_in_each_rotation_mode(self):
        for mode in ('QUATERNION', 'AXIS_ANGLE', 'XYZ'):
            with self.subTest(mode=mode):
                self.obj.animation_data_clear()
                self.obj.rotation_mode = mode
                self.obj.driver_add('location', 0).driver.expression = '7.0'
                before = self.snapshot()
                with self.assertRaisesRegex(ValueError, 'transform drivers'):
                    importKey(self.path, self.scene, False, True, False)
                self.assertEqual(self.snapshot(), before)

    def test_muted_transform_driver_does_not_block_merge(self):
        driver = self.obj.driver_add('location', 0)
        driver.driver.expression, driver.mute = '7.0', True
        importKey(self.path, self.scene, False, True, False)
        self.assert_vector(self.obj.location, (1, 0, 0))
        self.assertTrue(driver.mute)

    def test_unrelated_driver_does_not_block_merge(self):
        self.obj['custom'] = 1.0
        driver = self.obj.driver_add('["custom"]')
        driver.driver.expression = '7.0'
        importKey(self.path, self.scene, False, True, False)
        self.assert_vector(self.obj.location, (1, 0, 0))
        self.assertEqual(driver.driver.expression, '7.0')

    def test_replacement_removes_conflicting_transform_driver(self):
        self.obj.driver_add('location', 0).driver.expression = '7.0'
        importKey(self.path, self.scene, True, True, False)
        self.assertFalse(self.obj.animation_data.drivers)
        self.scene.frame_set(1)
        self.assert_vector(self.obj.location, (1, 0, 0))

    def test_later_driven_joint_rejects_before_earlier_joint_changes(self):
        later = bpy.data.objects.new('later', None)
        self.scene.collection.objects.link(later)
        later.parent, later.rotation_mode = self.obj, kImEulerOrder
        later.driver_add('location', 0).driver.expression = '7.0'
        key = loadKey(self.path)
        key.numJoints = 2
        node, entry = KeyNode(), Keyframe()
        node.idx, node.meshName, node.keyframes = 1, 'later', [entry]
        key.nodes.append(node)
        saveKey(key, self.path, '')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'transform drivers'):
            importKey(self.path, self.scene, False, True, False)
        self.assertEqual(self.snapshot(), before)
        self.assertIsNone(self.obj.animation_data)

    def test_empty_track_does_not_reject_untouched_driver(self):
        self.obj.driver_add('location', 0).driver.expression = '7.0'
        key = loadKey(self.path)
        key.nodes[0].keyframes = []
        saveKey(key, self.path, '')
        importKey(self.path, self.scene, False, True, False)
        self.assertEqual(len(self.obj.animation_data.drivers), 1)
        self.assertFalse(getActionFCurves(self.obj))

    def test_non_native_nla_rejects_without_scene_changes(self):
        self.rotation_keys('QUATERNION')
        action = self.obj.animation_data.action
        slot = self.obj.animation_data.action_slot
        strip = self.obj.animation_data.nla_tracks.new().strips.new('old', 10, action)
        strip.action_slot = slot
        self.obj.animation_data.action = None
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'existing rotation animation'):
            importKey(self.path, self.scene, False, True, False)
        self.assertEqual(self.snapshot(), before)

    def test_linked_joint_objects_reject_before_clearing_scene_animation(self):
        self.obj.parent = None
        library = self.folder / 'object.blend'
        bpy.data.libraries.write(str(library), {self.obj})
        with bpy.data.libraries.load(str(library), link=True) as (source, destination):
            destination.objects = [self.obj.name]
        linked = destination.objects[0]
        self.scene.collection.objects.link(linked)
        bpy.context.view_layer.objects.active = linked
        before = self.snapshot()
        self.assertFalse(linked.is_editable)
        for clear in (False, True):
            with self.subTest(clear=clear), self.assertRaisesRegex(ValueError, 'local or editable'):
                importKey(self.path, self.scene, clear, True, False)
            self.assertEqual(self.snapshot(), before)

    def test_location_only_nla_does_not_block_rotation_mode_change(self):
        self.obj.rotation_mode = 'QUATERNION'
        self.obj.keyframe_insert(data_path='location', frame=10)
        animation = self.obj.animation_data
        action, slot = animation.action, animation.action_slot
        strip = animation.nla_tracks.new().strips.new('location', 10, action)
        strip.action_slot = slot
        animation.action = None
        importKey(self.path, self.scene, False, True, False)
        self.assertEqual(self.obj.rotation_mode, kImEulerOrder)
        self.assertEqual(strip.action, action)

    def test_muted_rotation_nla_does_not_block_a_merge(self):
        self.rotation_keys('QUATERNION')
        animation = self.obj.animation_data
        action, slot = animation.action, animation.action_slot
        strip = animation.nla_tracks.new().strips.new('muted', 10, action)
        strip.action_slot, strip.mute = slot, True
        animation.action = None
        importKey(self.path, self.scene, False, True, False)
        self.assertEqual(self.obj.rotation_mode, kImEulerOrder)
        self.assertTrue(strip.mute)

    def test_empty_track_does_not_disable_existing_quaternion_animation(self):
        self.rotation_keys('QUATERNION')
        key = loadKey(self.path)
        key.nodes[0].keyframes = []
        saveKey(key, self.path, '')
        action, slot = self.obj.animation_data.action, self.obj.animation_data.action_slot
        before, pose = curves(action, slot), self.obj.matrix_local.to_quaternion().copy()
        importKey(self.path, self.scene, False, True, False)
        self.assertEqual(self.obj.rotation_mode, 'QUATERNION')
        self.assertEqual(self.obj.animation_data.action, action)
        self.assertEqual(curves(action, slot), before)
        self.scene.frame_set(10)
        self.assertLess(pose.rotation_difference(self.obj.matrix_local.to_quaternion()).angle, 1e-5)
