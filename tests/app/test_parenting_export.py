"""Non-object parenting must be baked, not silently omitted by 3DO/KEY export."""
from pathlib import Path
import tempfile

import bpy

from app.support import SceneTestCase
from sith.key.keyExporter import exportKey
from sith.model.model3doExporter import export3do
from sith.model.model3doLoader import Model3doFileVersion
from sith.model.utils import kImEulerOrder


class ParentingExportTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.scene = bpy.context.scene
        self.scene.frame_start, self.scene.frame_end = 0, 4
        self.scene.render.fps, self.scene.render.fps_base = 30, 1
        self.scene.timeline_markers.clear()
        self.scene.sith_key_flags, self.scene.sith_key_types = set(), 'ffff'
        mesh = bpy.data.meshes.new('root')
        mesh.from_pydata([(0, 0, 0), (2, 0, 0), (0, 2, 0)], [], [(0, 1, 2)])
        self.root = bpy.data.objects.new('root', mesh)
        self.child = bpy.data.objects.new('joint', None)
        for obj in (self.root, self.child):
            self.scene.collection.objects.link(obj)
            obj.rotation_mode = kImEulerOrder
        self.child.parent = self.root
        self.child.keyframe_insert(data_path='location', frame=0)

    def assert_rejected(self, root):
        bpy.context.view_layer.update()
        before = self.child.matrix_world.copy()
        parent_type = self.child.parent_type
        for extension in ('3do', 'key'):
            path = self.folder / ('parent.' + extension)
            path.write_bytes(b'previous valid export')
            with self.subTest(format=extension), self.assertRaisesRegex(ValueError, 'parenting'):
                if extension == '3do':
                    export3do(root, str(path), Model3doFileVersion.Version2_3, False, False, True)
                else:
                    exportKey(root, self.scene, str(path))
            self.assertEqual(path.read_bytes(), b'previous valid export')
        self.assertEqual(self.child.parent_type, parent_type)
        self.assertEqual(self.child.matrix_world, before)

    def test_vertex_parented_joint_rejects_model_and_key_export(self):
        self.child.parent_type, self.child.parent_vertices = 'VERTEX', (1, 0, 0)
        bpy.context.view_layer.update()
        self.assert_vector(self.child.matrix_world.translation, (2, 0, 0))
        self.assert_rejected(self.root)

    def test_triangle_parented_joint_rejects_model_and_key_export(self):
        self.child.parent_type, self.child.parent_vertices = 'VERTEX_3', (0, 1, 2)
        self.assert_rejected(self.root)

    def test_vertex_parented_wrapper_rejects_even_when_exported_directly(self):
        wrapper = bpy.data.objects.new('wrapper', None)
        self.scene.collection.objects.link(wrapper)
        wrapper.parent, wrapper.parent_type = self.root, 'VERTEX'
        wrapper.parent_vertices = (1, 0, 0)
        self.child.parent = wrapper
        self.assert_rejected(wrapper)

    def test_bone_parented_root_is_rejected_before_writing(self):
        armature = bpy.data.objects.new('armature', bpy.data.armatures.new('armature'))
        self.scene.collection.objects.link(armature)
        self.root.parent, self.root.parent_type = armature, 'BONE'
        self.assert_rejected(self.root)

    def test_ordinary_object_parenting_remains_exportable(self):
        export3do(self.root, str(self.folder / 'ordinary.3do'), Model3doFileVersion.Version2_3, False, False, True)
        exportKey(self.root, self.scene, str(self.folder / 'ordinary.key'))
        self.assertTrue((self.folder / 'ordinary.3do').is_file())
        self.assertTrue((self.folder / 'ordinary.key').is_file())
