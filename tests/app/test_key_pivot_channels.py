"""Whole-track and live Pivot settings are checked before imports mutate a scene."""
import bpy
import mathutils

from app.test_key_import_safety import _ImportSafetyCase, held, curve_state
from fixtures import TV
from sith.key import KeyNode, KeyframeFlag
from sith.key.keyImporter import importKey, _make_import_samples
from sith.key.keyUtils import getActionFCurves, getActionSlotFCurves
from sith.model.utils import makeRotationMatrix, objPivot
from sith.types import Vector3f


class FirstKeyImportTests(_ImportSafetyCase):
    def test_nonzero_first_vector_rejects_before_merge_or_replacement(self):
        for clear in (False, True):
            for operator in (False, True):
                with self.subTest(clear=clear, operator=operator):
                    self.reject(TV / 'key/nonzero_first.key', 'frame zero', clear=clear, operator=operator)

    def test_nonzero_first_held_entry_is_not_silently_clamped(self):
        for frame in (1e-44, 0.25, 1, 5):
            _, path = self.key_file([held(frame, 5)])
            with self.subTest(frame=frame):
                self.reject(path, 'frame zero')

    def test_zero_stored_first_frames_and_empty_tracks_remain_supported(self):
        for frame in (-0.0, 1e-50):
            value = held(frame, 5)
            value.flags, value.deltaPosition = KeyframeFlag.PositionChange, Vector3f(1, 0, 0)
            key, path = self.key_file([value])
            with self.subTest(frame=frame):
                importKey(path, self.scene, True, True, False)
                self.assert_poses(self.obj, key.nodes[0], (0, 1, 2, 4))
        self.assertEqual(_make_import_samples(KeyNode(), 5), [])

    def test_later_nonzero_first_track_preserves_an_earlier_shared_action(self):
        self.share_action()
        later = self.joint('later', 1, self.obj)
        later.keyframe_insert(data_path='location', frame=0)
        node = KeyNode()
        node.idx, node.meshName, node.keyframes = 1, 'later', [held(2, 5)]
        _, path = self.key_file([held(0, 3)], later=node, joints=2)
        self.reject(path, 'frame zero', operator=True)


class PivotChannelImportTests(_ImportSafetyCase):
    def snapshot(self):
        # Rejected imports must also leave the constraint settings themselves
        # untouched, not only actions, drivers, markers and playback metadata.
        pivots = [(obj.as_pointer(), [(constraint.name, tuple(constraint.offset),
                                     constraint.mute, constraint.influence,
                                     constraint.rotation_range, constraint.use_relative_location)
                                    for constraint in obj.constraints if constraint.type == 'PIVOT'])
                  for obj in bpy.data.objects]
        return super().snapshot(), pivots

    def pivot(self, owner=None, name='Pivot'):
        owner = self.obj if owner is None else owner
        constraint = owner.constraints.new('PIVOT')
        constraint.name = name
        constraint.rotation_range, constraint.use_relative_location = 'ALWAYS_ACTIVE', True
        constraint.offset = (1, 0, 0)
        return constraint

    def animate(self, constraint, path, first, last):
        for frame, value in ((0, first), (4, last)):
            setattr(constraint, path, value)
            constraint.keyframe_insert(data_path=path, frame=frame)
        self.scene.frame_set(0)

    def constraint_curves(self, constraint, action=None, slot=None):
        animation = self.obj.animation_data
        action = animation.action if action is None else action
        slot = animation.action_slot if slot is None else slot
        prefix = constraint.path_from_id() + '.'
        return [state for state in curve_state(action, slot) if state[0].startswith(prefix)]

    def pivot_clip(self, constraint):
        # Separate the constraint-only clip from the active transform action so
        # this regression cannot pass by detecting active-action channels alone.
        self.animate(constraint, 'offset', (1, 0, 0), (2, 0, 0))
        animation = self.obj.animation_data
        action, slot = animation.action, animation.action_slot
        clip_action = action.copy()
        clip_slot = clip_action.slots[slot.identifier]
        prefix = constraint.path_from_id() + '.'
        bag = action.layers[0].strips[0].channelbag(slot)
        for curve in list(getActionSlotFCurves(action, slot)):
            if curve.data_path.startswith(prefix):
                bag.fcurves.remove(curve)
        bag = clip_action.layers[0].strips[0].channelbag(clip_slot)
        for curve in list(getActionSlotFCurves(clip_action, clip_slot)):
            if not curve.data_path.startswith(prefix):
                bag.fcurves.remove(curve)
        constraint.offset = (1, 0, 0)
        track = animation.nla_tracks.new()
        strip = track.strips.new('pivot_settings', 0, clip_action)
        strip.action_slot = clip_slot
        self.scene.frame_set(0)
        return track, strip

    def assert_pivot_poses(self, mesh_pivot):
        for frame in (0, 1, 2, 4):
            self.scene.frame_set(frame)
            actual = self.obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_local.translation
            expected = makeRotationMatrix(0, 30, 0) @ mesh_pivot + mathutils.Vector((3, 0, 0))
            self.assert_vector(actual, expected)

    def test_keyed_offset_rejects_before_copying_a_shared_action(self):
        constraint = self.pivot()
        self.animate(constraint, 'offset', (1, 0, 0), (2, 0, 0))
        self.share_action()
        _, path = self.key_file([held(0, 3, 30)])
        self.reject(path, 'animated or driven constraint')

    def test_zero_initial_influence_does_not_hide_later_pivot_motion(self):
        constraint = self.pivot()
        self.animate(constraint, 'influence', 0, 1)
        _, path = self.key_file([held(0, 3, 30)])
        self.reject(path, 'animated or driven constraint')

    def test_animated_mute_is_checked_at_every_import_frame(self):
        constraint = self.pivot()
        self.animate(constraint, 'mute', True, False)
        _, path = self.key_file([held(0, 3, 30)])
        for frame in (0, 2, 4):
            self.scene.frame_set(frame)
            with self.subTest(frame=frame):
                self.reject(path, 'animated or driven constraint')

    def test_live_drivers_on_pivot_settings_require_baking(self):
        _, path = self.key_file([held(0, 3, 30)])
        for channel, index, expression in (('offset', 0, '1 + frame / 4'),
                                            ('influence', None, 'frame / 4'),
                                            ('mute', None, 'frame < 2')):
            constraint = self.pivot(name='Pivot_' + channel)
            driver = constraint.driver_add(channel) if index is None else constraint.driver_add(channel, index)
            driver.driver.expression = expression
            self.scene.frame_set(0)
            with self.subTest(channel=channel):
                self.reject(path, 'animated or driven constraint')
            self.obj.constraints.remove(constraint)

    def test_constraint_only_nla_is_checked_before_merge(self):
        constraint = self.pivot()
        self.pivot_clip(constraint)
        _, path = self.key_file([held(0, 3, 30)])
        self.reject(path, 'animated or driven constraint', operator=True)

    def test_inactive_nla_keeps_source_settings_and_correct_imported_poses(self):
        for gate in ('global', 'track', 'strip'):
            constraint = self.pivot(name='Pivot_' + gate)
            track, strip = self.pivot_clip(constraint)
            animation = self.obj.animation_data
            animation.use_nla = gate != 'global'
            track.mute, strip.mute = gate == 'track', gate == 'strip'
            self.scene.frame_set(0)
            mesh_pivot = objPivot(self.obj, forAnimation=True).copy()
            source = curve_state(strip.action, strip.action_slot)
            _, path = self.key_file([held(0, 3, 30)])
            with self.subTest(gate=gate):
                importKey(path, self.scene, False, True, False)
                self.assertEqual(curve_state(strip.action, strip.action_slot), source)
                self.assertEqual(animation.use_nla, gate != 'global')
                self.assert_pivot_poses(mesh_pivot)
            animation.nla_tracks.remove(track)
            self.obj.constraints.remove(constraint)

    def test_fixed_disabled_gates_allow_irrelevant_keyed_settings(self):
        for gate in ('mute', 'influence'):
            constraint = self.pivot(name='Pivot_' + gate)
            if gate == 'mute':
                constraint.mute = True
            else:
                constraint.influence = 0
            self.animate(constraint, 'offset', (1, 0, 0), (2, 0, 0))
            before = self.constraint_curves(constraint)
            key, path = self.key_file([held(0, 3, 30)])
            with self.subTest(gate=gate):
                importKey(path, self.scene, False, True, False)
                self.assertEqual(self.constraint_curves(constraint), before)
                self.assert_poses(self.obj, key.nodes[0], (0, 1, 2, 4))
            self.obj.constraints.remove(constraint)

    def test_muted_channels_and_drivers_do_not_block_static_pivots(self):
        constraint = self.pivot()
        self.animate(constraint, 'offset', (1, 0, 0), (2, 0, 0))
        for curve in getActionFCurves(self.obj):
            if curve.data_path.startswith(constraint.path_from_id() + '.'):
                curve.mute = True
        constraint.driver_add('offset', 1).mute = True
        constraint.offset = (1, 0, 0)
        self.scene.frame_set(0)
        mesh_pivot = objPivot(self.obj, forAnimation=True).copy()
        _, path = self.key_file([held(0, 3, 30)])
        importKey(path, self.scene, False, True, False)
        self.assert_pivot_poses(mesh_pivot)

    def test_empty_incoming_track_leaves_live_pivot_channels_untouched(self):
        constraint = self.pivot()
        self.animate(constraint, 'offset', (1, 0, 0), (2, 0, 0))
        before = self.constraint_curves(constraint)
        _, path = self.key_file([])
        importKey(path, self.scene, False, True, False)
        self.assertEqual(self.constraint_curves(constraint), before)

    def test_replacement_removes_live_constraint_animation(self):
        for source in ('keys', 'driver', 'nla'):
            constraint = self.pivot(name='Pivot_' + source)
            if source == 'keys':
                self.animate(constraint, 'offset', (1, 0, 0), (2, 0, 0))
            elif source == 'driver':
                constraint.driver_add('offset', 0).driver.expression = '1 + frame / 4'
            else:
                self.pivot_clip(constraint)
            self.scene.frame_set(0)
            mesh_pivot = objPivot(self.obj, forAnimation=True).copy()
            _, path = self.key_file([held(0, 3, 30)])
            with self.subTest(source=source):
                importKey(path, self.scene, True, True, False)
                self.assertFalse(self.obj.animation_data.drivers)
                self.assertFalse(self.obj.animation_data.nla_tracks)
                self.assertFalse(self.constraint_curves(constraint))
                self.assert_pivot_poses(mesh_pivot)
            self.obj.constraints.remove(constraint)

    def test_later_joint_and_escaped_names_are_preflighted_before_shared_actions(self):
        self.share_action()
        later = self.joint('later', 1, self.obj)
        constraint = self.pivot(later, 'Pivot "quoted" [brackets]')
        self.animate(constraint, 'offset', (1, 0, 0), (2, 0, 0))
        node = KeyNode()
        node.idx, node.meshName, node.keyframes = 1, 'later', [held(0, 3, 30)]
        _, path = self.key_file([held(0, 3)], later=node, joints=2)
        self.reject(path, 'animated or driven constraint')
