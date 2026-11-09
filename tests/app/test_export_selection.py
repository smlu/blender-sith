"""Public exports use the active model, never a magic collection or other scene."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest import mock

import bpy

from app.support import SceneTestCase
from sith import app
from sith.key.keyLoader import loadKey
from sith.key.keyUtils import setSceneKeyFlags
from sith.model.model3doLoader import load3do
from sith.model.utils import kImEulerOrder


class ExportSelectionTests(SceneTestCase):
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

    def collection(self, scene=None):
        collection = bpy.data.collections.new('Model3do')
        (scene or self.scene).collection.children.link(collection)
        self.addCleanup(bpy.data.collections.remove, collection)
        return collection

    def joint(self, name, collection=None, parent=None):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        obj = bpy.data.objects.new(name, mesh)
        (collection or self.scene.collection).objects.link(obj)
        obj.parent = parent
        obj.rotation_mode = kImEulerOrder
        obj.sith_model3do_hnode_name = name
        obj.keyframe_insert(data_path='location', frame=0)
        return obj

    def activate(self, obj):
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

    def path(self, suffix):
        self.counter += 1
        return self.folder / f'{self.counter:03d}-selection.{suffix}'

    def assert_exports(self, names):
        # Exercise actual registered operators and read their output back.
        model_path, key_path = self.path('3do'), self.path('key')
        self.assertEqual(bpy.ops.export_scene.sith_3do(filepath=str(model_path)), {'FINISHED'})
        model, _ = load3do(model_path)
        self.assertEqual([node.name for node in model.meshHierarchy], names)
        self.assertEqual(bpy.ops.export_anim.sith_key(filepath=str(key_path)), {'FINISHED'})
        key = loadKey(key_path)
        self.assertEqual([node.meshName for node in key.nodes], names)

    def assert_cancelled(self, message):
        for operator, suffix in ((bpy.ops.export_scene.sith_3do, '3do'),
                                 (bpy.ops.export_anim.sith_key, 'key')):
            with self.subTest(operator=suffix):
                path = self.path(suffix)
                path.write_bytes(b'previous export')
                with self.assertRaisesRegex(RuntimeError, message):
                    operator(filepath=str(path))
                self.assertEqual(path.read_bytes(), b'previous export')

    def test_selected_mesh_is_the_export_target(self):
        self.activate(self.joint('selected'))
        self.assert_exports(['selected'])

    def test_multiple_selected_models_use_only_the_active_one(self):
        other, active = self.joint('other'), self.joint('active')
        other.select_set(True)
        self.activate(active)
        self.assert_exports(['active'])

    def test_active_child_exports_its_complete_model(self):
        root = self.joint('root')
        child = self.joint('child', parent=root)
        sibling = self.joint('sibling', parent=root)
        self.activate(child)
        self.assertFalse(root.select_get())
        self.assertFalse(sibling.select_get())
        self.assert_exports(['root', 'child', 'sibling'])

    def test_single_object_magic_collection_does_not_override_selection(self):
        collection = self.collection()
        other = self.joint('other', collection)
        self.activate(self.joint('selected'))
        self.assert_exports(['selected'])
        self.assertIn(other.name, collection.objects)

    def test_multi_object_magic_collection_is_ordinary_organization(self):
        collection = self.collection()
        first, second = self.joint('first', collection), self.joint('second', collection)
        first.select_set(True)
        self.activate(second)
        self.assert_exports(['second'])
        self.assertEqual(len(collection.objects), 2)

    def test_foreign_scene_collection_cannot_supply_the_export_target(self):
        foreign = bpy.data.scenes.new('other_scene')
        self.addCleanup(bpy.data.scenes.remove, foreign)
        self.joint('foreign', self.collection(foreign))
        self.activate(self.joint('selected'))
        self.assert_exports(['selected'])

    def test_excluded_collection_cannot_supply_the_export_target(self):
        collection = self.collection()
        self.joint('excluded', collection)
        bpy.context.view_layer.layer_collection.children[collection.name].exclude = True
        self.activate(self.joint('selected'))
        self.assert_exports(['selected'])

    def test_empty_magic_collection_does_not_affect_export(self):
        self.collection()
        self.activate(self.joint('selected'))
        self.assert_exports(['selected'])

    def test_no_active_object_cancels_even_with_selected_objects(self):
        self.joint('selected').select_set(True)
        bpy.context.view_layer.objects.active = None
        self.assert_cancelled('No object selected')

    def test_deselected_active_object_cancels(self):
        obj = self.joint('deselected')
        bpy.context.view_layer.objects.active = obj
        self.assertFalse(obj.select_get())
        self.assert_cancelled('No object selected')

    def test_unsupported_active_object_does_not_fall_back_to_another_model(self):
        self.joint('selected_mesh').select_set(True)
        camera = bpy.data.cameras.new('camera')
        self.addCleanup(bpy.data.cameras.remove, camera)
        obj = bpy.data.objects.new('camera', camera)
        self.scene.collection.objects.link(obj)
        self.activate(obj)
        self.assert_cancelled('Cannot export')

    def test_foreign_active_override_is_rejected(self):
        obj = bpy.data.objects.new('foreign', None)
        context = SimpleNamespace(active_object=obj, selected_objects=[obj], view_layer=bpy.context.view_layer)
        reports = []
        self.assertIsNone(app._get_export_obj(context, lambda *args: reports.append(args), 'mesh'))
        self.assertIn('No object selected', reports[0][1])

    def test_parent_outside_the_view_layer_cancels(self):
        collection = self.collection()
        root = self.joint('excluded_parent', collection)
        child = self.joint('selected_child', parent=root)
        bpy.context.view_layer.layer_collection.children[collection.name].exclude = True
        self.activate(child)
        self.assert_cancelled('outside the active view layer')

    def test_unsupported_parent_cancels_without_losing_its_transform(self):
        curve = bpy.data.curves.new('parent', 'CURVE')
        self.addCleanup(bpy.data.curves.remove, curve)
        parent = bpy.data.objects.new('unsupported_parent', curve)
        self.scene.collection.objects.link(parent)
        self.activate(self.joint('child', parent=parent))
        self.assert_cancelled('unsupported parent')

    def test_file_browser_invocation_uses_the_same_active_model(self):
        self.joint('other', self.collection())
        obj = self.joint('selected')
        self.activate(obj)
        for operator_type, extension in ((app.ExportModel3do, '.3do'), (app.ExportKey, '.key')):
            with self.subTest(extension=extension):
                operator = mock.Mock(filename_ext=extension)
                with mock.patch.object(app.ExportHelper, 'invoke', return_value={'RUNNING_MODAL'}):
                    self.assertEqual(operator_type.invoke(operator, bpy.context, None), {'RUNNING_MODAL'})
                self.assertEqual(operator.obj, obj)
