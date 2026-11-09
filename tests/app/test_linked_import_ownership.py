"""Read-only libraries must not be changed by MAT reload or KEY replacement."""
import hashlib
from pathlib import Path
import tempfile

import bpy

from app.test_key_import_safety import _ImportSafetyCase, curve_state, held
from app.support import SceneTestCase
from fixtures import RGB24, TV, mat_bytes
from sith.key import KeyFlag, KeyNode
from sith.key.keyImporter import importKey
from sith.key.keyLoader import loadKey
from sith.key.keyUtils import getSceneKeyFlags
from sith.material.mat import importMat, kMatCelImagePrefix
from sith.model.model3doImporter import import3do
from sith.model.model3doLoader import load3do
from sith.model.utils import kImEulerOrder
from sith.utils import clearSceneAnimData


class ReadOnlyMaterialTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory(prefix='sith-readonly-material-')
        self.addCleanup(temporary.cleanup)
        self.addCleanup(self.clear_data)
        self.folder = Path(temporary.name)
        self.path, self.library = self.folder / 'linked.mat', self.folder / 'source.blend'

    def snapshot_image(self, image):
        return (tuple(image.size), list(image.pixels), image.source,
                bytes(image.packed_file.data) if image.packed_file else None)

    def test_read_only_material_rejects_without_allocating_or_rebinding(self):
        self.path.write_bytes(mat_bytes(RGB24, [(1, 1, [b'\xff\0\0'], False, 0)]))
        material = importMat(self.path)
        bpy.data.libraries.write(str(self.library), {material})
        library_hash = hashlib.sha256(self.library.read_bytes()).hexdigest()
        self.clear_data()
        with bpy.data.libraries.load(str(self.library), link=True) as (source, destination):
            destination.materials = [self.path.name]
        material = destination.materials[0]
        self.assertFalse(material.is_editable)
        image = material[kMatCelImagePrefix + '0']
        node = material.node_tree.nodes['SithTexImage']
        before = self.snapshot_image(image)
        images, nodes = set(bpy.data.images), set(material.node_tree.nodes)
        self.path.write_bytes(mat_bytes(RGB24, [(2, 1, [b'\0\0\xff' * 2], False, 0)]))
        contents = self.path.read_bytes()

        # Both APIs must cancel before node replacement, image copies or writes.
        for operator in (False, True):
            with self.subTest(operator=operator), self.assertRaisesRegex(
                    RuntimeError if operator else ValueError, 'material.*local or editable'):
                if operator:
                    bpy.ops.import_material.sith_mat(filepath=str(self.path))
                else:
                    importMat(self.path)
            self.assertEqual(set(bpy.data.images), images)
            self.assertEqual(set(material.node_tree.nodes), nodes)
            self.assertEqual(node.image, image)
            self.assertEqual(material[kMatCelImagePrefix + '0'], image)
            self.assertEqual(self.snapshot_image(image), before)
            self.assertEqual(self.path.read_bytes(), contents)
            self.assertEqual(hashlib.sha256(self.library.read_bytes()).hexdigest(), library_hash)

        # The same input is supported once the user explicitly localizes the material.
        material = material.make_local()
        self.assertEqual(importMat(self.path), material)
        replacement = material[kMatCelImagePrefix + '0']
        self.assertIsNone(replacement.library)
        self.assertEqual(tuple(replacement.size), (2, 1))
        self.assert_vector(replacement.pixels[:4], (0, 0, 1, 1))
        self.assertEqual(self.snapshot_image(image), before)


class LinkedAnimationOwnershipTests(_ImportSafetyCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(self.clear_data)

    def linked_object(self, *, animated=True, driver=False):
        source = self.joint('library_object', -1)
        if animated:
            if driver:
                source.driver_add('location', 0).driver.expression = '1.0'
            else:
                for frame in (0, 5):
                    source.location.x = frame
                    source.keyframe_insert(data_path='location', frame=frame)
        library = self.folder / 'object.blend'
        bpy.data.libraries.write(str(library), {source})
        digest = hashlib.sha256(library.read_bytes()).hexdigest()
        bpy.data.objects.remove(source, do_unlink=True)
        with bpy.data.libraries.load(str(library), link=True) as (available, loaded):
            loaded.objects = ['library_object']
        linked = loaded.objects[0]
        self.scene.collection.objects.link(linked)
        bpy.context.view_layer.objects.active = self.root
        self.scene.frame_set(0)
        self.assertFalse(linked.is_editable)
        self.addCleanup(lambda: self.assertEqual(hashlib.sha256(library.read_bytes()).hexdigest(), digest))
        return linked

    def test_clear_rejects_unrelated_linked_animation_before_any_changes(self):
        linked = self.linked_object()
        _, path = self.key_file([held(0, 1)])
        for operator in (False, True):
            with self.subTest(operator=operator):
                self.reject(path, 'animated object.*local or editable', clear=True, operator=operator)
        self.assertIsNotNone(linked.animation_data)

    def test_clear_rejects_linked_driver_only_animation(self):
        linked = self.linked_object(driver=True)
        _, path = self.key_file([held(0, 1)])
        self.reject(path, 'animated object.*local or editable', clear=True)
        self.assertEqual(len(linked.animation_data.drivers), 1)

    def test_direct_clear_helper_preserves_markers_and_all_actions_on_rejection(self):
        self.linked_object()
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'animated object.*local or editable'):
            clearSceneAnimData(self.scene)
        self.assertEqual(self.snapshot(), before)

    def test_merge_preserves_unrelated_linked_animation(self):
        linked = self.linked_object()
        action, slot = linked.animation_data.action, linked.animation_data.action_slot
        before = curve_state(action, slot)
        key, path = self.key_file([held(0, 1)])
        importKey(path, self.scene, False, True, False)
        self.assertEqual(linked.animation_data.action, action)
        self.assertEqual(linked.animation_data.action_slot, slot)
        self.assertEqual(curve_state(action, slot), before)
        self.assert_poses(self.obj, key.nodes[0], (0, 1, 4))

    def test_clear_allows_unanimated_linked_objects(self):
        linked = self.linked_object(animated=False)
        key, path = self.key_file([held(0, 1)])
        importKey(path, self.scene, True, True, False)
        self.assertIsNone(linked.animation_data)
        self.assertEqual(list(self.scene.timeline_markers), [])
        self.assert_poses(self.obj, key.nodes[0], (0, 1, 4))

    def test_clear_detaches_linked_actions_from_editable_local_objects(self):
        local = self.linked_object().make_local()
        action, slot = local.animation_data.action, local.animation_data.action_slot
        self.assertTrue(local.is_editable)
        self.assertFalse(action.is_editable)
        before = curve_state(action, slot)
        key, path = self.key_file([held(0, 1)])
        importKey(path, self.scene, True, True, False)
        self.assertIsNone(local.animation_data)
        self.assertEqual(curve_state(action, slot), before)
        self.assert_poses(self.obj, key.nodes[0], (0, 1, 4))

    def linked_scene(self, *, animated=False):
        original = bpy.context.window.scene
        source = bpy.data.scenes.new('library_scene')
        source.timeline_markers.new('library_marker', frame=13)
        joint = bpy.data.objects.new('library_joint', None)
        joint.sith_model3do_hnode_idx, joint.sith_model3do_hnode_name = 0, 'joint'
        source.collection.objects.link(joint)
        if animated:
            source.frame_start, source.frame_end = 0, 4
            source.render.fps, source.render.fps_base = 30, 1
            joint.rotation_mode = kImEulerOrder
            for frame in (0, 4):
                joint.location.x = frame / 4
                joint.keyframe_insert(data_path='location', frame=frame)
        library = self.folder / 'scene.blend'
        # A complete mainfile also preserves scene-level data for link=True.
        bpy.ops.wm.save_as_mainfile(filepath=str(library), copy=True)
        digest = hashlib.sha256(library.read_bytes()).hexdigest()
        bpy.data.scenes.remove(source)
        bpy.data.objects.remove(joint, do_unlink=True)
        with bpy.data.libraries.load(str(library), link=True) as (available, loaded):
            loaded.scenes = ['library_scene']
        scene = loaded.scenes[0]
        original_pointer, linked_pointer = original.as_pointer(), scene.as_pointer()
        def restore_scene():
            # A destructive 3DO import may have intentionally removed both scenes.
            remaining = {item.as_pointer(): item for item in bpy.data.scenes}
            if original_pointer in remaining:
                bpy.context.window.scene = remaining[original_pointer]
            if linked_pointer in remaining:
                bpy.data.scenes.remove(remaining[linked_pointer])
            self.scene = bpy.context.window.scene
            self.assertEqual(hashlib.sha256(library.read_bytes()).hexdigest(), digest)
        self.addCleanup(restore_scene)
        bpy.context.window.scene = scene
        bpy.context.view_layer.objects.active = scene.objects['library_joint']
        self.scene = scene
        self.assertFalse(scene.is_editable)
        scene.frame_set(0)
        return scene

    def test_read_only_scene_rejects_even_empty_tracks_before_clearing_markers(self):
        scene = self.linked_scene()
        for entries in ([], [held(0, 1)]):
            _, path = self.key_file(entries)
            for clear in (False, True):
                for operator in (False, True):
                    with self.subTest(empty=not entries, clear=clear, operator=operator):
                        self.reject(path, 'scene.*local or editable', clear=clear, operator=operator)
        self.assertEqual([(m.name, m.frame) for m in scene.timeline_markers], [('library_marker', 13)])

    def test_direct_clear_rejects_read_only_scene_before_clearing_markers(self):
        scene = self.linked_scene()
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'scene.*local or editable'):
            clearSceneAnimData(scene)
        self.assertEqual(self.snapshot(), before)

    def test_destructive_model_import_can_discard_a_linked_scene(self):
        # 3DO Clear Scene intentionally deletes old IDs; KEY only edits animation.
        self.linked_scene()
        imported = import3do(TV / 'model/triangle.3do', clearScene=True)
        self.assertIn(imported.name, bpy.context.scene.objects)
        self.assertTrue(bpy.context.scene.is_editable)
        self.assertFalse(any(scene.library for scene in bpy.data.scenes))

    def other_scene(self):
        scene = bpy.data.scenes.new('other_scene')
        self.addCleanup(bpy.data.scenes.remove, scene)
        obj = bpy.data.objects.new('other_joint', None)
        scene.collection.objects.link(obj)
        obj.sith_model3do_hnode_idx = 0
        obj.sith_model3do_hnode_name = 'joint'
        obj.rotation_mode = kImEulerOrder
        for frame in (0, 4):
            obj.location.x = 3 + frame
            obj.keyframe_insert(data_path='location', frame=frame)
        scene.timeline_markers.new('other_marker', frame=2)
        scene.frame_set(0)
        return scene, obj

    def scene_snapshot(self, scene):
        original = self.scene
        try:
            self.scene = scene
            return self.snapshot()
        finally:
            self.scene = original

    def test_foreign_context_rejects_before_changing_either_scene(self):
        other, _ = self.other_scene()
        self.scene.frame_set(0)
        before = self.snapshot(), self.scene_snapshot(other)
        for entries in ([], [held(0, 1)]):
            _, path = self.key_file(entries)
            contents = path.read_bytes()
            for clear in (False, True):
                for validate in (False, True):
                    for active in (None, self.root):
                        bpy.context.view_layer.objects.active = active
                        with self.subTest(empty=not entries, clear=clear, validate=validate, active=active), \
                             self.assertRaisesRegex(ValueError, 'scene.*active context'):
                            importKey(path, other, clear, validate, False)
                        self.assertEqual((self.snapshot(), self.scene_snapshot(other)), before)
                        self.assertEqual(path.read_bytes(), contents)

    def test_foreign_parent_rejects_for_direct_and_registered_import(self):
        _, foreign = self.other_scene()
        foreign.sith_model3do_hnode_idx = -1
        self.root.parent = foreign
        self.scene.frame_set(0)
        _, path = self.key_file([held(0, 1)])
        for clear in (False, True):
            for operator in (False, True):
                with self.subTest(clear=clear, operator=operator):
                    self.reject(path, 'root.*outside.*scene', clear=clear, operator=operator)
        self.assertEqual(self.root.parent, foreign)

    def test_foreign_joint_rejects_even_when_not_in_the_incoming_tracks(self):
        _, foreign = self.other_scene()
        foreign.parent = self.root
        foreign.sith_model3do_hnode_idx = 1
        self.scene.frame_set(0)
        for include_foreign in (False, True):
            node = KeyNode()
            node.idx, node.meshName, node.keyframes = 1, 'other_joint', [held(0, 2)]
            _, path = self.key_file([held(0, 1)], later=node if include_foreign else None,
                                    joints=2 if include_foreign else 1)
            for clear in (False, True):
                for operator in (False, True):
                    with self.subTest(targeted=include_foreign, clear=clear, operator=operator):
                        self.reject(path, 'joint.*outside.*scene', clear=clear, operator=operator)

    def test_context_override_supports_import_into_another_local_scene(self):
        other, obj = self.other_scene()
        original_action, original_slot = self.obj.animation_data.action, self.obj.animation_data.action_slot
        original_curves = curve_state(original_action, original_slot)
        key, path = self.key_file([held(0, 1)])
        original_window_scene = bpy.context.window.scene
        other.view_layers[0].objects.active = obj
        for clear in (False, True):
            with self.subTest(clear=clear), bpy.context.temp_override(scene=other, view_layer=other.view_layers[0]):
                importKey(path, other, clear, True, False)
                self.assert_vector(obj.location, (1, 0, 0))
                self.assertEqual(other.render.fps, key.fps)
                self.assertEqual(self.scene, original_window_scene)
        # Only the requested scene's own joint/action was replaced or merged.
        self.assertEqual(self.obj.location.x, 9)
        self.assertEqual(self.obj.animation_data.action, original_action)
        self.assertEqual(curve_state(original_action, original_slot), original_curves)
        self.assertEqual(bpy.context.window.scene, original_window_scene)

    def activate_linked_joint(self, scene):
        obj = scene.objects['library_joint']
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        scene.frame_set(0)
        return obj

    def scene_export_settings(self, scene):
        # Include property presence: assigning a default still mutates a linked ID.
        return (scene.render.fps, scene.render.fps_base, int(getSceneKeyFlags(scene)),
                scene.sith_key_types, scene.is_property_set('sith_key_flags'),
                set(scene.keys()))

    def test_linked_scene_export_overrides_do_not_change_library_state(self):
        scene = self.linked_scene(animated=True)
        self.activate_linked_joint(scene)
        before = self.snapshot(), self.scene_export_settings(scene)
        for target in ('IJIM', 'JKDF2', 'MOTS', 'CUSTOM'):
            with self.subTest(target=target):
                path = self.folder / (target + '.key')
                path.write_bytes(b'previous export')
                result = bpy.ops.export_anim.sith_key(filepath=str(path), target=target, fps=60,
                                                      flags={KeyFlag.PauseOnLastFrame.name}, node_types='20')
                self.assertEqual(result, {'FINISHED'})
                key = loadKey(path)
                self.assertEqual((key.fps, int(key.flags), int(key.nodeTypes)),
                                 (60, int(KeyFlag.PauseOnLastFrame), 0x20))
                self.assertTrue(key.nodes[0].keyframes)
                self.assertEqual((self.snapshot(), self.scene_export_settings(scene)), before)

    def test_linked_scene_export_defaults_do_not_create_properties(self):
        scene = self.linked_scene(animated=True)
        self.activate_linked_joint(scene)
        before = self.scene_export_settings(scene)
        path = self.folder / 'defaults.key'
        self.assertEqual(bpy.ops.export_anim.sith_key(filepath=str(path)), {'FINISHED'})
        key = loadKey(path)
        self.assertEqual((key.fps, int(key.flags), int(key.nodeTypes)), (30, 0, 0xFFFF))
        self.assertEqual(self.scene_export_settings(scene), before)

    def test_linked_scene_export_remains_unchanged_after_save_and_reopen(self):
        original_name = self.scene.name
        scene = self.linked_scene(animated=True)
        linked_name = scene.name
        self.activate_linked_joint(scene)
        before = self.scene_export_settings(scene)
        path = self.folder / 'persistent.key'
        self.assertEqual(bpy.ops.export_anim.sith_key(filepath=str(path), fps=60,
                                                    flags={KeyFlag.PauseOnLastFrame.name}, node_types='20'), {'FINISHED'})
        self.assertEqual(self.scene_export_settings(scene), before)

        # Opening a mainfile invalidates every prior RNA pointer. Restore using
        # the saved names before the ordinary fixture cleanups run.
        def restore_reopened_scene():
            original = bpy.data.scenes.get(original_name)
            if original is not None:
                bpy.context.window.scene = original
            linked = bpy.data.scenes.get(linked_name)
            if linked is not None and linked.library:
                bpy.data.scenes.remove(linked)
            self.scene = bpy.context.window.scene
        self.addCleanup(restore_reopened_scene)
        saved = self.folder / 'saved.blend'
        bpy.ops.wm.save_as_mainfile(filepath=str(saved))
        bpy.ops.wm.open_mainfile(filepath=str(saved))
        self.scene = bpy.data.scenes[linked_name]
        self.assertFalse(self.scene.is_editable)
        self.assertEqual(self.scene_export_settings(self.scene), before)
        key = loadKey(path)
        self.assertEqual((key.fps, int(key.flags), int(key.nodeTypes)),
                         (60, int(KeyFlag.PauseOnLastFrame), 0x20))

    def test_failed_linked_scene_export_preserves_scene_and_previous_file(self):
        scene = self.linked_scene(animated=True)
        self.activate_linked_joint(scene)
        before = self.snapshot(), self.scene_export_settings(scene)
        path = self.folder / 'previous.key'
        path.write_bytes(b'previous export')
        with self.assertRaisesRegex(RuntimeError, 'FPS'):
            bpy.ops.export_anim.sith_key(filepath=str(path), fps=0)
        self.assertEqual(path.read_bytes(), b'previous export')
        self.assertEqual((self.snapshot(), self.scene_export_settings(scene)), before)

    def test_editable_scene_export_still_remembers_successful_overrides(self):
        path = self.folder / 'local.key'
        self.assertEqual(bpy.ops.export_anim.sith_key(filepath=str(path), fps=60,
                                                    flags={KeyFlag.PauseOnLastFrame.name}, node_types='20'), {'FINISHED'})
        key = loadKey(path)
        expected_flags = 0x80000000 | int(KeyFlag.PauseOnLastFrame)
        self.assertEqual((key.fps, int(key.flags), int(key.nodeTypes)), (60, expected_flags, 0x20))
        self.assertEqual(self.scene.render.fps / self.scene.render.fps_base, 60)
        self.assertEqual((int(getSceneKeyFlags(self.scene)), self.scene.sith_key_types), (expected_flags, '20'))

    def test_same_named_linked_objects_remain_valid_export_targets(self):
        # Library IDs can keep the same names as local objects. Both the active
        # joint and its parent must be identified by ID, never by name lookup.
        library = self.folder / 'same_names.blend'
        bpy.data.libraries.write(str(library), {self.root, self.obj})
        digest = hashlib.sha256(library.read_bytes()).hexdigest()
        with bpy.data.libraries.load(str(library), link=True) as (available, loaded):
            loaded.objects = [self.root.name, self.obj.name]
        root, joint = loaded.objects
        self.assertEqual((root.name, joint.name), (self.root.name, self.obj.name))
        self.assertEqual(joint.parent, root)
        for obj in (root, joint):
            self.scene.collection.objects.link(obj)
            obj.select_set(True)
        self.scene.frame_set(0)
        for active in (root, joint):
            with self.subTest(active=active.name):
                bpy.context.view_layer.objects.active = active
                model_path, key_path = self.folder / 'same_names.3do', self.folder / 'same_names.key'
                self.assertEqual(bpy.ops.export_scene.sith_3do(filepath=str(model_path)), {'FINISHED'})
                self.assertEqual(bpy.ops.export_anim.sith_key(filepath=str(key_path)), {'FINISHED'})
                model, _ = load3do(model_path)
                key = loadKey(key_path)
                self.assertEqual([node.name for node in model.meshHierarchy], ['joint'])
                self.assertEqual([node.meshName for node in key.nodes], ['joint'])
        self.assertEqual(hashlib.sha256(library.read_bytes()).hexdigest(), digest)
