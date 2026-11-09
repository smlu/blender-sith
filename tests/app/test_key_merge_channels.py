"""KEY merges preflight curve storage and effects before modifying the scene."""
from pathlib import Path
import tempfile
from unittest import mock

import bpy

from app.support import SceneTestCase
from sith.key import Key, KeyNode, Keyframe, KeyframeFlag
from sith.key.keyImporter import importKey, _insert_import_samples
from sith.key.keyUtils import getActionFCurves
from sith.key.keyWriter import saveKey
from sith.model.utils import kImEulerOrder
from sith.types import Vector3f


class KeyMergeChannelTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'merge.key'
        self.scene = bpy.context.scene
        self.scene.frame_start, self.scene.frame_end = 0, 10
        self.scene.render.fps, self.scene.render.fps_base = 48, 1
        self.scene.timeline_markers.clear()
        self.scene.timeline_markers.new('existing', frame=9)
        self.root = self.object('wrapper')
        self.obj = self.object('joint', self.root)
        for frame in (0, 10):
            self.obj.location.x = 9
            self.obj.keyframe_insert(data_path='location', frame=frame)
            self.obj.keyframe_insert(data_path='rotation_euler', frame=frame)
        self.key, self.node = Key('merge.key'), KeyNode()
        self.key.numJoints, self.key.numFrames, self.key.fps = 1, 5, 30
        self.node.idx, self.node.meshName = 0, 'joint'
        first, last = Keyframe(), Keyframe()
        first.position, first.deltaPosition = Vector3f(1, 0, 0), Vector3f(1, 0, 0)
        first.flags = KeyframeFlag.PositionChange
        last.frame, last.position = 4, Vector3f(5, 0, 0)
        self.node.keyframes = [first, last]
        self.key.nodes = [self.node]
        bpy.context.view_layer.objects.active = self.root
        self.scene.frame_set(2)

    def object(self, name, parent=None):
        obj = bpy.data.objects.new(name, None)
        self.scene.collection.objects.link(obj)
        obj.parent, obj.rotation_mode = parent, kImEulerOrder
        return obj

    def curve(self, path='location', obj=None):
        obj = self.obj if obj is None else obj
        return next(c for c in getActionFCurves(obj) if c.data_path == path and c.array_index == 0)

    def snapshot(self):
        return (self.scene.frame_start, self.scene.frame_end, self.scene.frame_current,
                self.scene.render.fps, self.scene.render.fps_base,
                [(marker.name, marker.frame) for marker in self.scene.timeline_markers],
                tuple(self.obj.location), tuple(self.obj.rotation_euler),
                self.obj.animation_data.action.as_pointer(), len(bpy.data.actions),
                [(c.data_path, c.array_index, c.mute,
                  [(tuple(p.co), p.interpolation) for p in c.keyframe_points],
                  [tuple(p.co) for p in c.sampled_points],
                  [(m.type, m.mute) for m in c.modifiers]) for c in getActionFCurves(self.obj)])

    def merge(self, clear=False):
        saveKey(self.key, self.path, '')
        importKey(self.path, self.scene, clear, True, False)

    def assert_rejected(self, message):
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, message):
            self.merge()
        self.assertEqual(self.snapshot(), before)

    def test_sampled_transform_curves_reject_before_insertion(self):
        # Never repeat the unsafe allocation in a regression test: the sentinel
        # makes a missing public preflight fail before entering native insertion.
        for path in ('location', 'rotation_euler'):
            curve = self.curve(path)
            curve.convert_to_samples(start=0, end=11)
            self.obj.animation_data.action.update_tag()
            self.scene.frame_set(2)
            with self.subTest(path=path), mock.patch(
                    'sith.key.keyImporter._insert_import_samples',
                    side_effect=AssertionError('Sampled curve reached insertion')):
                self.assert_rejected('sampled transform curves')
            curve.convert_to_keyframes(start=0, end=10)

    def test_low_level_sampled_insertion_rejects_without_touching_buffers(self):
        curve = self.curve()
        curve.convert_to_samples(start=0, end=11)
        before = self.snapshot()
        with mock.patch('sith.key.keyImporter._key_position_to_blender',
                        side_effect=AssertionError('Past preflight')):
            with self.assertRaisesRegex(ValueError, 'sampled transform curves'):
                _insert_import_samples(self.obj, self.node.keyframes)
        self.assertEqual(self.snapshot(), before)

    def test_later_sampled_joint_rejects_before_earlier_joint_or_copy_changes(self):
        outsider = self.object('other_user')
        outsider.animation_data_create()
        outsider.animation_data.action = self.obj.animation_data.action
        outsider.animation_data.action_slot = self.obj.animation_data.action_slot
        later = self.object('later', self.obj)
        later.keyframe_insert(data_path='location', frame=0)
        later.keyframe_insert(data_path='location', frame=10)
        curve = self.curve(obj=later)
        curve.convert_to_samples(start=0, end=11)
        node = KeyNode()
        node.idx, node.meshName, node.keyframes = 1, 'later', [Keyframe()]
        self.key.numJoints, self.key.nodes = 2, [self.node, node]
        before = [tuple(p.co) for p in curve.sampled_points]
        self.assert_rejected('sampled transform curves')
        self.assertEqual([tuple(p.co) for p in curve.sampled_points], before)
        self.assertEqual(outsider.animation_data.action, self.obj.animation_data.action)

    def test_active_transform_modifiers_reject_without_scene_changes(self):
        for path in ('location', 'rotation_euler'):
            curve = self.curve(path)
            modifier = curve.modifiers.new('GENERATOR')
            modifier.coefficients = (9, 0)
            with self.subTest(path=path):
                self.assert_rejected('F-curve modifiers')
            curve.modifiers.remove(modifier)

    def test_muted_transform_curve_rejects_instead_of_hiding_new_motion(self):
        self.curve().mute = True
        self.assert_rejected('Unmute transform curves')

    def test_muted_modifiers_allow_merge_and_preserve_outside_keys(self):
        modifier = self.curve().modifiers.new('GENERATOR')
        modifier.coefficients, modifier.mute = (9, 0), True
        self.merge()
        for frame, expected in ((0, 1), (2, 3), (4, 5), (10, 9)):
            self.scene.frame_set(frame)
            self.assertAlmostEqual(self.obj.location.x, expected, places=5)
        self.assertTrue(modifier.mute)

    def test_custom_property_samples_and_modifiers_are_not_destination_conflicts(self):
        self.obj['custom'] = 7.0
        for frame in (0, 10):
            self.obj.keyframe_insert(data_path='["custom"]', frame=frame)
        curve = next(c for c in getActionFCurves(self.obj) if c.data_path == '["custom"]')
        curve.convert_to_samples(start=0, end=11)
        curve.modifiers.new('GENERATOR').mute = False
        before = [tuple(p.co) for p in curve.sampled_points]
        self.merge()
        self.scene.frame_set(2)
        self.assertAlmostEqual(self.obj.location.x, 3, places=5)
        self.assertEqual([tuple(p.co) for p in curve.sampled_points], before)

    def test_empty_incoming_track_does_not_touch_sampled_storage(self):
        curve = self.curve()
        curve.convert_to_samples(start=0, end=11)
        before = [tuple(p.co) for p in curve.sampled_points]
        self.node.keyframes = []
        self.merge()
        self.assertEqual(len(curve.keyframe_points), 0)
        self.assertEqual([tuple(p.co) for p in curve.sampled_points], before)

    def test_replacement_import_can_clear_incompatible_curves(self):
        self.curve().convert_to_samples(start=0, end=11)
        rotation = self.curve('rotation_euler')
        rotation.modifiers.new('GENERATOR')
        rotation.mute = True
        self.merge(clear=True)
        for curve in getActionFCurves(self.obj):
            self.assertFalse(curve.sampled_points)
            self.assertFalse(curve.modifiers)
            self.assertFalse(curve.mute)
        self.scene.frame_set(2)
        self.assertAlmostEqual(self.obj.location.x, 3, places=5)
