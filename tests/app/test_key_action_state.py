"""Import and export preflight the same native action-evaluation restrictions."""
import math

import bpy

from app.test_key import sample_key
from app.test_key_import_safety import _ImportSafetyCase, held, curve_state
from sith.key import KeyNode
from sith.key.keyExporter import exportKey
from sith.key.keyImporter import importKey
from sith.key.keyLoader import loadKey
from sith.key.keyUtils import getActionFCurves
from sith.model.utils import makeRotationMatrix


class _ActionStateCase(_ImportSafetyCase):
    def snapshot(self):
        return super().snapshot(), [(obj.as_pointer(), obj.animation_data.use_tweak_mode,
                                     obj.animation_data.action_blend_type, obj.animation_data.action_influence)
                                    for obj in bpy.data.objects if obj.animation_data]

    def tearDown(self):
        for obj in bpy.data.objects:
            if obj.animation_data and obj.animation_data.use_tweak_mode:
                obj.animation_data.use_tweak_mode = False
        super().tearDown()

    def clip(self, owner=None):
        owner = self.obj if owner is None else owner
        if owner.animation_data is None:
            owner['custom'] = 0.0
            owner.keyframe_insert(data_path='["custom"]', frame=0)
        animation = owner.animation_data
        track = animation.nla_tracks.new()
        strip = track.strips.new('clip', 0, animation.action)
        strip.action_slot = animation.action_slot
        return track, strip

    def tweak(self, owner=None):
        owner = self.obj if owner is None else owner
        track, strip = self.clip(owner)
        strip.select = True
        owner.animation_data.nla_tracks.active = track
        owner.animation_data.use_tweak_mode = True
        self.assertTrue(owner.animation_data.use_tweak_mode)
        return track, strip

    def export_rejects(self, message, operator=False):
        _, path = self.key_file([held(0, 3)])
        before, contents = self.snapshot(), path.read_bytes()
        with self.assertRaisesRegex(RuntimeError if operator else ValueError, message):
            if operator:
                bpy.ops.export_anim.sith_key(filepath=str(path))
            else:
                exportKey(self.root, self.scene, str(path))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(path.read_bytes(), contents)


class ExportActionStateTests(_ActionStateCase):
    def motion(self):
        self.obj.animation_data_clear()
        self.scene.frame_end = 4
        for frame, x, yaw in ((0, 3, 0), (4, 7, 30)):
            self.obj.location.x = x
            self.obj.rotation_euler.z = math.radians(yaw)
            self.obj.keyframe_insert(data_path='location', frame=frame)
            self.obj.keyframe_insert(data_path='rotation_euler', frame=frame)
        for curve in getActionFCurves(self.obj):
            for point in curve.keyframe_points:
                point.interpolation = 'LINEAR'
        self.scene.frame_set(0)

    def test_muted_strip_blending_rejects_before_replacing_output(self):
        self.motion()
        _, strip = self.clip()
        strip.mute = True
        for mode, influence in (('REPLACE', 0.0), ('REPLACE', 0.5), ('ADD', 1.0),
                                ('ADD', 0.5), ('MULTIPLY', 1.0), ('COMBINE', 1.0)):
            animation = self.obj.animation_data
            animation.action_blend_type, animation.action_influence = mode, influence
            self.scene.frame_set(2)
            for operator in (False, True):
                with self.subTest(mode=mode, influence=influence, operator=operator):
                    self.export_rejects('active action blending', operator)

    def test_wrapper_blending_is_checked_before_export(self):
        self.motion()
        _, strip = self.clip(self.root)
        strip.mute = True
        self.root.animation_data.action_influence = 0.5
        self.export_rejects('active action blending', True)

    def test_inactive_stack_or_full_replace_matches_evaluated_motion(self):
        for gate in ('replace', 'global', 'track', 'empty'):
            self.motion()
            animation = self.obj.animation_data
            if gate == 'empty':
                animation.nla_tracks.new()
            else:
                track, strip = self.clip()
                strip.mute, track.mute = True, gate == 'track'
            animation.use_nla = gate != 'global'
            animation.action_blend_type = 'REPLACE' if gate == 'replace' else 'MULTIPLY'
            animation.action_influence = 1.0 if gate == 'replace' else 0.5
            poses = []
            for frame in (0, 0.5, 2, 4):
                self.scene.frame_set(math.floor(frame), subframe=frame % 1)
                poses.append(self.obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_local.copy())
            _, path = self.key_file([held(0, 3)])
            with self.subTest(gate=gate):
                exportKey(self.root, self.scene, str(path))
                node, = loadKey(path).nodes
                for frame, pose in zip((0, 0.5, 2, 4), poses):
                    position, rotation = sample_key(node, frame)
                    self.assert_vector(position, pose.translation)
                    expected = makeRotationMatrix(*rotation)
                    self.assert_vector([v for row in expected for v in row],
                                       [v for row in pose.to_3x3() for v in row])

    def test_tweak_mode_rejects_even_with_muted_or_disabled_nla(self):
        self.motion()
        _, strip = self.tweak()
        for disabled in (False, True):
            strip.mute = True
            self.obj.animation_data.use_nla = not disabled
            self.scene.frame_set(2)
            with self.subTest(disabled=disabled):
                self.export_rejects('NLA tweak mode', True)


class ImportTweakStateTests(_ActionStateCase):
    def test_merge_rejects_before_creating_an_orphan_action(self):
        self.tweak()
        _, path = self.key_file([held(0, 3, 30)])
        for operator in (False, True):
            with self.subTest(operator=operator):
                self.reject(path, 'NLA tweak mode', operator=operator)

    def test_later_tweaked_joint_rejects_before_earlier_action_isolation(self):
        self.share_action()
        later = self.joint('later', 1, self.obj)
        later.keyframe_insert(data_path='location', frame=0)
        self.tweak(later)
        node = KeyNode()
        node.idx, node.meshName, node.keyframes = 1, 'later', [held(0, 3)]
        _, path = self.key_file([held(0, 3)], later=node, joints=2)
        self.reject(path, 'NLA tweak mode')

    def test_replacement_import_can_remove_tweak_animation(self):
        self.tweak()
        key, path = self.key_file([held(0, 3, 30)])
        importKey(path, self.scene, True, True, False)
        self.assertFalse(self.obj.animation_data.use_tweak_mode)
        self.assertFalse(self.obj.animation_data.nla_tracks)
        self.assert_poses(self.obj, key.nodes[0], (0, 1, 4))

    def test_empty_track_does_not_touch_tweak_action(self):
        _, strip = self.tweak()
        action, slot = strip.action, strip.action_slot
        before, count = curve_state(action, slot), len(bpy.data.actions)
        _, path = self.key_file([])
        importKey(path, self.scene, False, True, False)
        self.assertTrue(self.obj.animation_data.use_tweak_mode)
        self.assertEqual(curve_state(action, slot), before)
        self.assertEqual(len(bpy.data.actions), count)
