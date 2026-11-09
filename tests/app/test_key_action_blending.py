"""KEY merge channels must evaluate as imported, not blend with old NLA poses."""
import bpy

from app.test_key_import_safety import _ImportSafetyCase, held, curve_state
from sith.key import KeyframeFlag
from sith.key.keyImporter import importKey
from sith.types import Vector3f


class KeyActionBlendingTests(_ImportSafetyCase):
    def snapshot(self):
        settings = [(obj.as_pointer(), obj.animation_data.action_blend_type,
                     obj.animation_data.action_influence) for obj in bpy.data.objects if obj.animation_data]
        return super().snapshot(), settings

    def clip(self, owner=None):
        owner = self.obj if owner is None else owner
        animation = owner.animation_data
        track = animation.nla_tracks.new()
        strip = track.strips.new('existing', 0, animation.action)
        strip.action_slot = animation.action_slot
        return track, strip

    def moving_key(self):
        entry = held(0, 3, 30)
        entry.flags, entry.deltaPosition = KeyframeFlag.PositionChange, Vector3f(1, 0, 0)
        return self.key_file([entry])

    def test_partial_action_influence_rejects_before_scene_or_action_copies(self):
        self.clip()
        self.share_action()
        _, path = self.moving_key()
        for value in (0.0, 0.5):
            self.obj.animation_data.action_influence = value
            self.scene.frame_set(2)
            with self.subTest(influence=value):
                self.reject(path, 'active action blending', operator=True)

    def test_additive_action_modes_reject_at_every_current_frame(self):
        self.clip()
        _, path = self.moving_key()
        for mode in ('ADD', 'SUBTRACT', 'MULTIPLY', 'COMBINE'):
            self.obj.animation_data.action_blend_type = mode
            for frame in (0, 2, 4):
                self.scene.frame_set(frame)
                with self.subTest(mode=mode, frame=frame):
                    self.reject(path, 'active action blending')

    def test_inactive_nla_allows_blend_settings_without_changing_clip(self):
        for gate in ('global', 'track'):
            track, strip = self.clip()
            animation = self.obj.animation_data
            animation.use_nla = gate != 'global'
            track.mute, strip.mute = gate == 'track', gate == 'strip'
            animation.action_blend_type, animation.action_influence = 'ADD', 0.5
            before = curve_state(strip.action, strip.action_slot)
            key, path = self.moving_key()
            with self.subTest(gate=gate):
                importKey(path, self.scene, False, True, False)
                self.assert_poses(self.obj, key.nodes[0], (0, 1, 2, 4))
                self.assertEqual(curve_state(strip.action, strip.action_slot), before)
                self.assertEqual((animation.action_blend_type, animation.action_influence), ('ADD', 0.5))
            animation.nla_tracks.remove(track)

    def test_muted_strip_still_enables_active_action_blending(self):
        # Muting a strip suppresses that clip, not the active action's influence
        # or blend mode. Blender still evaluates the populated track's stack.
        _, strip = self.clip()
        strip.mute = True
        animation = self.obj.animation_data
        animation.action_blend_type, animation.action_influence = 'ADD', 0.5
        _, path = self.moving_key()
        self.reject(path, 'active action blending')

    def test_full_replace_action_overrides_nla_without_changing_source_clip(self):
        _, strip = self.clip()
        before = curve_state(strip.action, strip.action_slot)
        key, path = self.moving_key()
        importKey(path, self.scene, False, True, False)
        self.assert_poses(self.obj, key.nodes[0], (0, 1, 2, 4))
        self.assertEqual(curve_state(strip.action, strip.action_slot), before)

    def test_empty_nla_tracks_do_not_enable_blending(self):
        animation = self.obj.animation_data
        animation.nla_tracks.new()
        animation.action_blend_type, animation.action_influence = 'ADD', 0.5
        key, path = self.moving_key()
        importKey(path, self.scene, False, True, False)
        self.assert_poses(self.obj, key.nodes[0], (0, 1, 2, 4))

    def test_replacement_clears_incompatible_action_blending(self):
        self.clip()
        animation = self.obj.animation_data
        animation.action_blend_type, animation.action_influence = 'ADD', 0.5
        key, path = self.moving_key()
        importKey(path, self.scene, True, True, False)
        self.assert_poses(self.obj, key.nodes[0], (0, 1, 2, 4))
        animation = self.obj.animation_data
        self.assertFalse(animation.nla_tracks)
        self.assertEqual((animation.action_blend_type, animation.action_influence), ('REPLACE', 1.0))

    def test_empty_incoming_track_keeps_existing_blending_untouched(self):
        _, strip = self.clip()
        animation = self.obj.animation_data
        animation.action_blend_type, animation.action_influence = 'ADD', 0.5
        before = curve_state(strip.action, strip.action_slot)
        _, path = self.key_file([])
        importKey(path, self.scene, False, True, False)
        self.assertEqual(curve_state(strip.action, strip.action_slot), before)
        self.assertEqual((animation.action_blend_type, animation.action_influence), ('ADD', 0.5))
