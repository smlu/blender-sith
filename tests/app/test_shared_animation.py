"""KEY merges must edit the destination, never other users of its action slot."""
from pathlib import Path
import tempfile
from types import SimpleNamespace

import bpy

from app.support import SceneTestCase
from sith.key import Key, KeyNode, Keyframe
from sith.key.keyImporter import importKey, _nla_uses_action_slot
from sith.key.keyUtils import getActionFCurves
from sith.key.keyWriter import saveKey
from sith.model.utils import kImEulerOrder
from sith.types import Vector3f


class SharedAnimationTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'shared.key'
        self.scene = bpy.context.scene
        self.scene.frame_start, self.scene.frame_end = 0, 10
        self.scene.render.fps, self.scene.render.fps_base = 30, 1
        self.scene.timeline_markers.clear()
        self.root = self.object('wrapper')
        self.a = self.object('a', self.root)
        self.b = self.object('b', self.a)
        self.a.sith_model3do_hnode_idx, self.b.sith_model3do_hnode_idx = 0, 1
        self.a.location.x = 7
        self.a.keyframe_insert(data_path='location', frame=9)
        self.action = self.a.animation_data.action
        self.slot = self.a.animation_data.action_slot
        self.key = Key('shared.key')
        self.key.numJoints, self.key.numFrames, self.key.fps = 2, 5, 30
        for index, name, position in ((0, 'a', (1, 0, 0)), (1, 'b', (0, 2, 0))):
            node, entry = KeyNode(), Keyframe()
            node.idx, node.meshName, node.keyframes = index, name, [entry]
            entry.position = Vector3f(*position)
            self.key.nodes.append(node)
        bpy.context.view_layer.objects.active = self.root

    def object(self, name, parent=None):
        obj = bpy.data.objects.new(name, None)
        self.scene.collection.objects.link(obj)
        obj.parent = parent
        obj.rotation_mode = kImEulerOrder
        return obj

    def share_slot(self, obj, slot=None):
        obj.animation_data_create()
        obj.animation_data.action = self.action
        obj.animation_data.action_slot = self.slot if slot is None else slot

    def merge(self):
        saveKey(self.key, self.path, '')
        importKey(self.path, self.scene, False, True, False)

    def test_shared_slot_joints_receive_independent_incoming_poses(self):
        self.share_slot(self.b)
        self.merge()
        for frame in (0, 1, 3, 4):
            self.scene.frame_set(frame)
            self.assert_vector(self.a.location, (1, 0, 0))
            self.assert_vector(self.b.location, (0, 2, 0))
        self.assertNotEqual(self.a.animation_data.action, self.b.animation_data.action)
        # A merge also preserves authored keys outside the incoming track.
        self.scene.frame_set(9)
        self.assert_vector(self.a.location, (7, 0, 0))
        self.assert_vector(self.b.location, (7, 0, 0))

    def test_other_object_sharing_slot_keeps_its_original_curves(self):
        outsider = self.object('unrelated')
        self.share_slot(outsider)
        before = [(c.data_path, c.array_index, [tuple(p.co) for p in c.keyframe_points])
                  for c in getActionFCurves(outsider)]
        self.merge()
        self.assertEqual(outsider.animation_data.action, self.action)
        self.assertEqual(before, [(c.data_path, c.array_index, [tuple(p.co) for p in c.keyframe_points])
                                  for c in getActionFCurves(outsider)])
        self.scene.frame_set(1)
        self.assert_vector(outsider.location, (7, 0, 0))
        self.assert_vector(self.a.location, (1, 0, 0))

    def test_nla_user_of_the_slot_keeps_its_original_curves(self):
        outsider = self.object('nla_user')
        outsider.animation_data_create()
        strip = outsider.animation_data.nla_tracks.new().strips.new('original', 0, self.action)
        strip.action_slot = self.slot
        self.assertIn(outsider, self.slot.users())
        self.merge()
        self.assertEqual(strip.action, self.action)
        self.assertNotEqual(self.a.animation_data.action, strip.action)
        curves = strip.action.layers[0].strips[0].channelbag(strip.action_slot).fcurves
        self.assertEqual({point.co[0] for curve in curves for point in curve.keyframe_points}, {9})

    def test_other_scene_user_of_the_slot_remains_untouched(self):
        other_scene = bpy.data.scenes.new('other')
        self.addCleanup(lambda: bpy.data.scenes.remove(other_scene))
        outsider = bpy.data.objects.new('other_scene_user', None)
        other_scene.collection.objects.link(outsider)
        self.share_slot(outsider)
        self.merge()
        self.assertEqual(outsider.animation_data.action, self.action)
        self.assertNotEqual(self.a.animation_data.action, self.action)

    def test_independent_slots_can_stay_in_the_same_action(self):
        slot = self.action.slots.new(id_type='OBJECT', name='b')
        self.share_slot(self.b, slot)
        self.merge()
        self.assertEqual(self.a.animation_data.action, self.action)
        self.assertEqual(self.b.animation_data.action, self.action)
        self.assertNotEqual(self.a.animation_data.action_slot, self.b.animation_data.action_slot)
        self.scene.frame_set(1)
        self.assert_vector(self.a.location, (1, 0, 0))
        self.assert_vector(self.b.location, (0, 2, 0))

    def test_single_user_action_is_not_copied(self):
        self.merge()
        self.assertEqual(self.a.animation_data.action, self.action)

    def test_same_object_nla_reference_keeps_its_original_action(self):
        animation = self.a.animation_data
        strip = animation.nla_tracks.new().strips.new('later', 20, self.action)
        strip.action_slot = self.slot
        before = [(c.data_path, c.array_index, [tuple(p.co) for p in c.keyframe_points])
                  for c in getActionFCurves(self.a)]
        # Slot users count objects, not references: the active action and NLA
        # clip still report one user and must be isolated explicitly.
        self.assertEqual(len(self.slot.users()), 1)
        self.merge()
        self.assertNotEqual(animation.action, self.action)
        self.assertEqual(strip.action, self.action)
        old_curves = strip.action.layers[0].strips[0].channelbag(strip.action_slot).fcurves
        self.assertEqual(before, [(c.data_path, c.array_index, [tuple(p.co) for p in c.keyframe_points])
                                  for c in old_curves])
        self.scene.frame_set(1)
        self.assert_vector(self.a.location, (1, 0, 0))

    def test_muted_nla_reference_keeps_its_original_action(self):
        animation = self.a.animation_data
        track = animation.nla_tracks.new()
        track.mute = True
        strip = track.strips.new('muted', 20, self.action)
        strip.action_slot, strip.mute = self.slot, True
        self.merge()
        self.assertNotEqual(animation.action, self.action)
        self.assertEqual(strip.action, self.action)
        curves = strip.action.layers[0].strips[0].channelbag(strip.action_slot).fcurves
        self.assertEqual({point.co[0] for c in curves for point in c.keyframe_points}, {9})

    def test_different_nla_slot_does_not_force_an_action_copy(self):
        animation = self.a.animation_data
        slot = self.action.slots.new(id_type='OBJECT', name='nla-only')
        strip = animation.nla_tracks.new().strips.new('independent', 20, self.action)
        strip.action_slot = slot
        self.merge()
        self.assertEqual(animation.action, self.action)
        self.assertEqual(strip.action_slot, slot)

    def test_nested_meta_clip_is_a_reference_even_when_muted(self):
        # META creation is an editor-context operator; this check isolates the
        # strip traversal while the other tests use actual Blender NLA clips.
        clip = SimpleNamespace(type='CLIP', action=self.action, action_slot=self.slot, mute=True)
        meta = SimpleNamespace(type='META', strips=[clip], mute=True)
        track = SimpleNamespace(strips=[SimpleNamespace(type='META', strips=[meta])], mute=True)
        animation = SimpleNamespace(nla_tracks=[track])
        self.assertTrue(_nla_uses_action_slot(animation, self.action, self.slot))
        self.assertFalse(_nla_uses_action_slot(animation, self.action, None))

    def test_failed_preflight_does_not_copy_or_modify_shared_actions(self):
        self.share_slot(self.b)
        self.key.nodes[1].idx = 2
        saveKey(self.key, self.path, '')
        count = len(bpy.data.actions)
        with self.assertRaises(ValueError):
            importKey(self.path, self.scene, False, True, False)
        self.assertEqual(len(bpy.data.actions), count)
        self.assertEqual(self.a.animation_data.action, self.action)
        self.assertEqual(self.b.animation_data.action, self.action)
