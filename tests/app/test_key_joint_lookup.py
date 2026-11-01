"""A partial KEY skeleton must never use wrappers/helpers as missing joints."""
from pathlib import Path
import tempfile

import bpy

from app.support import SceneTestCase
from sith.key import Key, KeyNode, Keyframe
from sith.key.keyImporter import importKey, _check_obj, _find_joint_obj_for_anim_node
from sith.key.keyWriter import saveKey
from sith.model.utils import kModel3doRadiusKind, kMeshRadius
from sith.types import Vector3f


class PartialJointLookupTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'partial.key'
        self.scene = bpy.context.scene
        self.scene.frame_start, self.scene.frame_end = 0, 10
        self.scene.render.fps, self.scene.render.fps_base = 48, 1
        self.scene.sith_key_flags, self.scene.sith_key_types = {'NoLoop'}, '8008'
        self.scene.timeline_markers.clear()
        self.scene.timeline_markers.new('Attack', frame=3)
        self.root = self.object('absent_joint')
        self.joint = self.object('present_joint', self.root, mesh=True)
        self.joint.sith_model3do_hnode_idx = 1
        self.joint.location.x = 7
        self.joint.keyframe_insert(data_path='location', frame=0)
        self.scene.frame_set(0)
        bpy.context.view_layer.objects.active = self.root
        self.root.select_set(True)
        self.key = Key('partial.key')
        self.key.numJoints, self.key.numFrames, self.key.fps = 2, 5, 30
        self.node, entry = KeyNode(), Keyframe()
        self.node.idx, self.node.meshName, self.node.keyframes = 0, 'absent_joint', [entry]
        entry.position = Vector3f(5, 0, 0)
        self.key.nodes = [self.node]
        saveKey(self.key, self.path, '')

    def object(self, name, parent=None, mesh=False):
        data = bpy.data.meshes.new(name) if mesh else None
        if data is not None:
            data.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        obj = bpy.data.objects.new(name, data)
        self.scene.collection.objects.link(obj)
        obj.parent = parent
        return obj

    def snapshot(self):
        return (self.joint.animation_data.action.as_pointer(), tuple(self.root.location),
                tuple(self.joint.location), self.scene.frame_start, self.scene.frame_end,
                self.scene.render.fps, self.scene.render.fps_base, self.scene.frame_current,
                set(self.scene.sith_key_flags), self.scene.sith_key_types,
                [(marker.name, marker.frame) for marker in self.scene.timeline_markers])

    def test_missing_joint_does_not_match_wrapper_or_clear_animation(self):
        before = self.snapshot()
        self.assertFalse(_check_obj(self.root, self.key.nodes, self.key.numJoints))
        self.assertIsNone(_find_joint_obj_for_anim_node(self.root, self.node, self.key.numJoints))
        for clear in (False, True):
            with self.subTest(clear=clear), self.assertRaisesRegex(ValueError, "doesn't contain all required nodes"):
                importKey(self.path, self.scene, clear, True, False)
            self.assertEqual(self.snapshot(), before)
            self.assertIsNone(self.root.animation_data)

    def test_validation_opt_out_skips_missing_joint_instead_of_animating_wrapper(self):
        action = self.joint.animation_data.action
        importKey(self.path, self.scene, False, False, False)
        self.assertIsNone(self.root.animation_data)
        self.assertEqual(self.joint.animation_data.action, action)
        self.assert_vector(self.root.location, (0, 0, 0))

    def test_radius_helpers_are_not_index_or_name_fallback_candidates(self):
        helper = self.object('absent_joint_helper', self.joint, mesh=True)
        helper[kModel3doRadiusKind] = kMeshRadius
        helper.sith_model3do_hnode_idx = 0
        helper.sith_model3do_hnode_name = self.node.meshName
        self.assertIsNone(_find_joint_obj_for_anim_node(self.root, self.node, self.key.numJoints))
        self.assertFalse(_check_obj(self.root, self.key.nodes, self.key.numJoints))

    def test_unsupported_subtrees_are_not_fallback_candidates(self):
        controller = bpy.data.objects.new('curve', bpy.data.curves.new('curve_data', 'CURVE'))
        self.scene.collection.objects.link(controller)
        controller.parent = self.joint
        nested = self.object('nested', controller, mesh=True)
        nested.sith_model3do_hnode_idx = 0
        nested.sith_model3do_hnode_name = self.node.meshName
        self.assertIsNone(_find_joint_obj_for_anim_node(self.root, self.node, self.key.numJoints))
        self.assertFalse(_check_obj(self.root, self.key.nodes, self.key.numJoints))

    def test_unsupported_root_cannot_be_treated_as_an_empty_wrapper(self):
        root = bpy.data.objects.new('camera', bpy.data.cameras.new('camera_data'))
        self.scene.collection.objects.link(root)
        nested = self.object('nested', root, mesh=True)
        nested.sith_model3do_hnode_idx = 0
        nested.sith_model3do_hnode_name = self.node.meshName
        self.assertFalse(_check_obj(root, self.key.nodes, self.key.numJoints))

    def test_real_mesh_and_leaf_empty_roots_remain_animatable(self):
        for mesh in (False, True):
            with self.subTest(mesh=mesh):
                obj = self.object('solo_' + str(mesh), mesh=mesh)
                obj.sith_model3do_hnode_idx = 0
                self.key.numJoints = 1
                self.node.meshName = obj.name
                saveKey(self.key, self.path, '')
                bpy.context.view_layer.objects.active = obj
                self.assertTrue(_check_obj(obj, self.key.nodes, 1))
                importKey(self.path, self.scene, False, True, False)
                self.assertIsNotNone(obj.animation_data.action)
                self.assert_vector(obj.location, (5, 0, 0))

    def test_headerless_key_failure_preserves_existing_work(self):
        before = self.snapshot()
        for text in ('', 'This is not a KEY resource.\n',
                     'SECTION: HEADER\nFLAGS 0\nTYPE 0\nFRAMES 5\nFPS 30\nJOINTS 0\n'):
            self.path.write_text(text)
            for clear in (False, True):
                with self.subTest(text=text, clear=clear), self.assertRaisesRegex(ValueError, 'KEY.*section'):
                    importKey(self.path, self.scene, clear, True, False)
                self.assertEqual(self.snapshot(), before)
