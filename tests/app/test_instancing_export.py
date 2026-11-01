"""Instancers must be realized instead of silently exporting missing geometry."""
from pathlib import Path
import tempfile

import bpy

from app.support import SceneTestCase
from sith.key.keyExporter import exportKey
from sith.model.model3doExporter import export3do
from sith.model.model3doLoader import load3do, Model3doFileVersion
from sith.model.utils import kImEulerOrder


class InstancingExportTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.collections = []
        self.extra_data = []
        self.addCleanup(self.remove_collections)
        self.scene = bpy.context.scene
        self.scene.frame_start, self.scene.frame_end = 0, 4
        self.scene.render.fps, self.scene.render.fps_base = 30, 1
        self.scene.timeline_markers.clear()
        self.scene.sith_key_flags, self.scene.sith_key_types = set(), 'ffff'

    def remove_collections(self):
        self.clear_data()
        for collection in self.collections:
            bpy.data.collections.remove(collection)
        for database, data in self.extra_data:
            database.remove(data)

    def object(self, name, parent=None, mesh=False):
        data = bpy.data.meshes.new(name) if mesh else None
        if data:
            data.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        obj = bpy.data.objects.new(name, data)
        self.scene.collection.objects.link(obj)
        obj.parent, obj.rotation_mode = parent, kImEulerOrder
        return obj

    def collection_instance(self, parent=None):
        collection = bpy.data.collections.new('source')
        self.collections.append(collection)
        source = self.object('source_mesh', mesh=True)
        self.scene.collection.objects.unlink(source)
        collection.objects.link(source)
        obj = self.object('instance', parent)
        obj.instance_type, obj.instance_collection = 'COLLECTION', collection
        return obj

    def assert_rejected(self, root):
        # A failed export must preserve the old file and leave instancing for the
        # user to realize, not destructively convert the scene behind their back.
        before = [(obj.as_pointer(), obj.instance_type, obj.instance_collection, obj.parent)
                  for obj in bpy.data.objects]
        for extension in ('3do', 'key'):
            path = self.folder / ('instance.' + extension)
            path.write_bytes(b'previous valid export')
            with self.subTest(format=extension), self.assertRaisesRegex(ValueError, 'instancing'):
                if extension == '3do':
                    export3do(root, str(path), Model3doFileVersion.Version2_3, False, False, True)
                else:
                    exportKey(root, self.scene, str(path))
            self.assertEqual(path.read_bytes(), b'previous valid export')
        self.assertEqual(before, [(obj.as_pointer(), obj.instance_type, obj.instance_collection, obj.parent)
                                  for obj in bpy.data.objects])

    def test_collection_instance_root_rejects_instead_of_exporting_empty_model(self):
        root = self.collection_instance()
        bpy.context.view_layer.update()
        meshes = [item for item in bpy.context.evaluated_depsgraph_get().object_instances
                  if item.is_instance and item.object.type == 'MESH']
        self.assertEqual(len(meshes), 1)
        self.assert_rejected(root)

    def test_nested_collection_instance_rejects_both_exports(self):
        root = self.object('root', mesh=True)
        self.collection_instance(root)
        self.assert_rejected(root)

    def test_instancing_wrapper_with_real_children_is_not_partially_exported(self):
        root = self.collection_instance()
        self.object('ordinary_child', root, mesh=True)
        self.assert_rejected(root)

    def test_vertex_and_face_instancing_require_real_objects(self):
        root = self.object('root', mesh=True)
        self.object('repeated_child', root, mesh=True)
        for mode in ('VERTS', 'FACES'):
            root.instance_type = mode
            with self.subTest(mode=mode):
                self.assert_rejected(root)

    def test_unsupported_leaf_cannot_hide_active_instancing(self):
        root = self.object('root', mesh=True)
        leaf = bpy.data.objects.new('light', bpy.data.lights.new('light', 'POINT'))
        self.extra_data.append((bpy.data.lights, leaf.data))
        self.scene.collection.objects.link(leaf)
        leaf.parent, leaf.instance_type = root, 'VERTS'
        self.assert_rejected(root)

    def test_nested_unsupported_branch_cannot_hide_instancing(self):
        root = self.object('root', mesh=True)
        parent = bpy.data.objects.new('camera', bpy.data.cameras.new('camera'))
        leaf = bpy.data.objects.new('light', bpy.data.lights.new('light', 'POINT'))
        self.extra_data.extend(((bpy.data.cameras, parent.data), (bpy.data.lights, leaf.data)))
        for obj in (parent, leaf):
            self.scene.collection.objects.link(obj)
        parent.parent, leaf.parent, leaf.instance_type = root, parent, 'VERTS'
        self.assert_rejected(root)

    def test_disabled_instance_mode_does_not_block_an_ordinary_hierarchy(self):
        root = self.collection_instance()
        root.instance_type = 'NONE'
        self.object('ordinary_child', root, mesh=True)
        path = self.folder / 'ordinary.3do'
        export3do(root, str(path), Model3doFileVersion.Version2_3, False, False, True)
        self.assertEqual(len(load3do(path)[0].geosets[0].meshes), 1)

    def test_shared_mesh_objects_remain_valid_without_instancing_modes(self):
        root = self.object('root', mesh=True)
        child = bpy.data.objects.new('shared', root.data)
        self.scene.collection.objects.link(child)
        child.parent = root
        root.keyframe_insert(data_path='location', frame=0)
        path = self.folder / 'shared.3do'
        export3do(root, str(path), Model3doFileVersion.Version2_3, False, False, True)
        model = load3do(path)[0]
        self.assertEqual(len(model.geosets[0].meshes), 2)
        self.assertEqual(root.data, child.data)
        exportKey(root, self.scene, str(self.folder / 'shared.key'))
