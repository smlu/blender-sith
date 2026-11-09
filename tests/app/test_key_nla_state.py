"""Inactive NLA is harmless; live composition still cannot be exported as KEY."""
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace

import bpy

from app.support import SceneTestCase
from app.test_key import sample_key
from fixtures import TV
from sith.key import keyUtils
from sith.key.keyLoader import loadKey
from sith.key.keyUtils import getActionFCurves, setSceneKeyFlags
from sith.model.utils import kImEulerOrder


class KeyNlaStateTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.counter = 0
        self.scene = bpy.context.scene
        self.scene.frame_start, self.scene.frame_end = 0, 4
        self.scene.render.fps, self.scene.render.fps_base = 30, 1
        self.scene.timeline_markers.clear()
        setSceneKeyFlags(self.scene, 0)
        self.scene.sith_key_types = 'FFFF'
        self.root = bpy.data.objects.new('wrapper', None)
        self.obj = bpy.data.objects.new('joint', None)
        for obj in (self.root, self.obj):
            self.scene.collection.objects.link(obj)
        self.obj.parent, self.obj.rotation_mode = self.root, kImEulerOrder
        self.obj.sith_model3do_hnode_idx = 0
        for frame, value in ((0, 3), (4, 7)):
            self.obj.location.x = value
            self.obj.keyframe_insert(data_path='location', frame=frame)
        for curve in getActionFCurves(self.obj):
            for point in curve.keyframe_points:
                point.interpolation = 'LINEAR'
        self.scene.frame_set(0)
        bpy.context.view_layer.objects.active = self.root
        self.root.select_set(True)

    def clip(self, owner=None):
        owner = self.obj if owner is None else owner
        animation = owner.animation_data_create()
        track = animation.nla_tracks.new()
        action = self.obj.animation_data.action
        strip = track.strips.new('clip', 0, action)
        strip.action_slot = self.obj.animation_data.action_slot
        return track, strip

    def output(self):
        self.counter += 1
        path = self.folder / f'nla-{self.counter}.key'
        path.write_bytes((TV / 'key' / 'fractional.key').read_bytes())
        return path

    def assert_export_matches_visible_motion(self):
        # Compare actual dependency-graph poses to the serialized KEY, not just
        # the exporter's internal samples or successful operator return value.
        frames = (0, 0.5, 1, 2.75, 4, 4.5)
        poses = []
        for frame in frames:
            self.scene.frame_set(math.floor(frame), subframe=frame % 1)
            evaluated = self.obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
            poses.append(tuple(evaluated.matrix_local.translation))
        path = self.output()
        self.assertEqual(bpy.ops.export_anim.sith_key(filepath=str(path)), {'FINISHED'})
        key = loadKey(path)
        self.assertEqual(key.numJoints, 1)
        self.assertEqual(len(key.nodes), 1)
        for frame, expected in zip(frames, poses):
            with self.subTest(frame=frame):
                self.assert_vector(expected, (3 + min(frame, 4), 0, 0))
                self.assert_vector(sample_key(key.nodes[0], frame)[0], expected)

    def assert_rejected_without_writing(self):
        path = self.output()
        before = path.read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'Bake .*NLA'):
            bpy.ops.export_anim.sith_key(filepath=str(path))
        self.assertEqual(path.read_bytes(), before)

    def test_globally_disabled_nla_preserves_action_motion(self):
        self.clip()
        self.obj.animation_data.use_nla = False
        self.assert_export_matches_visible_motion()

    def test_muted_strips_on_an_unmuted_track_do_not_block_export(self):
        _, strip = self.clip()
        strip.mute = True
        self.assert_export_matches_visible_motion()

    def test_muted_tracks_remain_supported(self):
        track, _ = self.clip()
        track.mute = True
        self.assert_export_matches_visible_motion()

    def test_disabled_or_muted_wrapper_nla_does_not_block_joint_export(self):
        for disabled in (False, True):
            track, strip = self.clip(self.root)
            self.root.animation_data.use_nla = not disabled
            strip.mute = not disabled
            with self.subTest(globally_disabled=disabled):
                self.assert_export_matches_visible_motion()
            self.root.animation_data.nla_tracks.remove(track)

    def test_live_joint_composition_still_preserves_previous_output(self):
        muted, _ = self.clip()
        muted.mute = True
        self.clip()
        self.assert_rejected_without_writing()

    def test_live_wrapper_composition_still_preserves_previous_output(self):
        self.clip(self.root)
        self.assert_rejected_without_writing()

    def test_nla_only_animation_is_not_silently_exported_without_tracks(self):
        self.clip()
        self.obj.animation_data.action = None
        self.assert_rejected_without_writing()

    def test_empty_tracks_are_inactive(self):
        self.obj.animation_data.nla_tracks.new()
        self.assert_export_matches_visible_motion()

    def test_reactivating_nla_preserves_the_last_successful_export(self):
        for owner in (self.obj, self.root):
            for gate in ('global', 'track', 'strip'):
                track, strip = self.clip(owner)
                animation = owner.animation_data
                animation.use_nla = gate != 'global'
                track.mute, strip.mute = gate == 'track', gate == 'strip'
                action, slot = strip.action, strip.action_slot
                path = self.output()
                with self.subTest(owner=owner.name, gate=gate):
                    self.assertEqual(bpy.ops.export_anim.sith_key(filepath=str(path)), {'FINISHED'})
                    before = path.read_bytes()
                    self.assertEqual(animation.use_nla, gate != 'global')
                    self.assertEqual((track.mute, strip.mute), (gate == 'track', gate == 'strip'))
                    self.assertEqual((strip.action, strip.action_slot), (action, slot))
                    animation.use_nla, track.mute, strip.mute = True, False, False
                    with self.assertRaisesRegex(RuntimeError, 'Bake .*NLA'):
                        bpy.ops.export_anim.sith_key(filepath=str(path))
                    self.assertEqual(path.read_bytes(), before)
                animation.nla_tracks.remove(track)

    def test_meta_strip_mute_state_is_respected_recursively(self):
        # Blender has no background RNA constructor for Meta strips. Model only
        # their containers here; real clip/track/global gates run above.
        leaf = SimpleNamespace(type='CLIP', mute=True)
        nested = SimpleNamespace(type='META', mute=False, strips=[leaf])
        meta = SimpleNamespace(type='META', mute=False, strips=[nested])
        track = SimpleNamespace(mute=False, strips=[meta])
        animation = SimpleNamespace(use_nla=True, nla_tracks=[track])
        self.assertFalse(keyUtils.hasActiveNlaStrips(animation))
        leaf.mute, nested.mute = False, True
        self.assertFalse(keyUtils.hasActiveNlaStrips(animation))
        nested.mute = False
        self.assertTrue(keyUtils.hasActiveNlaStrips(animation))
        animation.use_nla = False
        self.assertFalse(keyUtils.hasActiveNlaStrips(animation))
        self.assertFalse(keyUtils.hasActiveNlaStrips(None))
