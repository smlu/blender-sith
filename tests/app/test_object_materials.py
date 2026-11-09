"""Object-linked slots must not be replaced by shared mesh material defaults."""
from pathlib import Path
import tempfile

import bpy

from app.support import SceneTestCase
from sith.model.model3doExporter import export3do
from sith.model.model3doLoader import load3do, Model3doFileVersion


class ObjectMaterialTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'materials.3do'
        mesh = bpy.data.meshes.new('triangle')
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        layer = mesh.uv_layers.new(name='UVMap')
        for loop, uv in zip(layer.data, ((0, 0), (1, 0), (0, 1))):
            loop.uv = uv
        self.obj = bpy.data.objects.new('triangle', mesh)
        bpy.context.scene.collection.objects.link(self.obj)
        self.base = self.material('base.mat', 64, 32)
        self.override = self.material('override.mat', 256, 128)
        mesh.materials.append(self.base)

    def material(self, name, width, height):
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        image = mat.node_tree.nodes.new('ShaderNodeTexImage')
        image.image = bpy.data.images.new(name, width=width, height=height)
        shader = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
        mat.node_tree.links.new(image.outputs['Color'], shader.inputs['Base Color'])
        return mat

    def export(self, root=None, absolute=True):
        version = Model3doFileVersion.Version2_1 if absolute else Model3doFileVersion.Version2_3
        export3do(self.obj if root is None else root, str(self.path), version, absolute, False, True)
        return load3do(self.path)[0]

    def test_object_override_controls_material_reference_and_pixel_uvs(self):
        slot = self.obj.material_slots[0]
        slot.link, slot.material = 'OBJECT', self.override
        model = self.export()
        self.assertEqual(model.materials, ['override.mat'])
        self.assertEqual(model.geosets[0].meshes[0].uvs, [(0, 0), (256, 0), (0, -128)])
        self.assertEqual(self.obj.data.materials[0], self.base)
        self.assertEqual((slot.link, slot.material), ('OBJECT', self.override))

    def test_shared_mesh_instances_keep_independent_effective_materials(self):
        root = bpy.data.objects.new('wrapper', None)
        bpy.context.scene.collection.objects.link(root)
        self.obj.parent = root
        second = bpy.data.objects.new('second', self.obj.data)
        bpy.context.scene.collection.objects.link(second)
        second.parent = self.obj
        second.material_slots[0].link = 'OBJECT'
        second.material_slots[0].material = self.override
        model = self.export(root)
        exported = {model.materials[mesh.faces[0].materialIdx]: mesh.uvs for mesh in model.geosets[0].meshes}
        self.assertEqual(exported, {'base.mat': [(0, 0), (64, 0), (0, -32)],
                                    'override.mat': [(0, 0), (256, 0), (0, -128)]})
        self.assertEqual(self.obj.data, second.data)
        self.assertEqual(self.obj.data.materials[0], self.base)
        self.assertEqual(self.obj.material_slots[0].material, self.base)

    def test_empty_object_override_does_not_fall_back_to_mesh_material(self):
        slot = self.obj.material_slots[0]
        slot.link, slot.material = 'OBJECT', None
        model = self.export()
        self.assertEqual(model.materials, [])
        self.assertEqual(model.geosets[0].meshes[0].faces[0].materialIdx, -1)
        self.assertEqual(self.obj.data.materials[0], self.base)

    def test_data_linked_slot_retains_existing_export_behavior(self):
        model = self.export()
        self.assertEqual(model.materials, ['base.mat'])
        self.assertEqual(model.geosets[0].meshes[0].uvs, [(0, 0), (64, 0), (0, -32)])

    def test_normalized_uv_export_still_uses_the_object_material(self):
        self.obj.material_slots[0].link = 'OBJECT'
        self.obj.material_slots[0].material = self.override
        model = self.export(absolute=False)
        self.assertEqual(model.materials, ['override.mat'])
        self.assertEqual(model.geosets[0].meshes[0].uvs, [(0, 0), (1, 0), (0, -1)])

    def test_unused_overridden_slot_keeps_face_slot_indices(self):
        self.obj.data.materials.append(self.material('unused.mat', 16, 16))
        self.obj.material_slots[1].link = 'OBJECT'
        self.obj.material_slots[1].material = self.override
        for index, name in ((0, 'base.mat'), (1, 'override.mat')):
            self.obj.data.polygons[0].material_index = index
            model = self.export()
            mesh = model.geosets[0].meshes[0]
            self.assertEqual(model.materials[mesh.faces[0].materialIdx], name)
