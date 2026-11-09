"""Legacy UV dimensions follow MAT bindings or visible color images, not node order."""
from pathlib import Path
import tempfile
import contextlib
import io
from types import SimpleNamespace
from unittest import mock

import bpy
import mathutils

from app.support import SceneTestCase
from fixtures import TV
from sith.material.mat import kMatCelImagePrefix
from sith.model.model3doExporter import export3do, _uv_add_image_size
from sith.model.utils import getMaterialImage
from sith.model.model3doLoader import load3do, Model3doFileVersion
from sith.model.model3doImporter import import3do


class UvImageTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'images.3do'
        mesh = bpy.data.meshes.new('triangle')
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        uv = mesh.uv_layers.new(name='UVMap')
        for value, coordinates in zip(uv.data, ((0, 0), (1, 0), (0, 1))):
            value.uv = coordinates
        self.obj = bpy.data.objects.new('triangle', mesh)
        bpy.context.scene.collection.objects.link(self.obj)
        self.material = bpy.data.materials.new('visible.mat')
        self.material.use_nodes = True
        mesh.materials.append(self.material)
        self.nodes, self.links = self.material.node_tree.nodes, self.material.node_tree.links
        self.shader = next(node for node in self.nodes if node.type == 'BSDF_PRINCIPLED')

    def image(self, name, width, height, color=False):
        node = self.nodes.new('ShaderNodeTexImage')
        node.image = bpy.data.images.new(name, width=width, height=height)
        if color:
            self.links.new(node.outputs['Color'], self.shader.inputs['Base Color'])
        return node

    def export(self, absolute=True):
        version = Model3doFileVersion.Version2_1 if absolute else Model3doFileVersion.Version2_3
        export3do(self.obj, str(self.path), version, absolute, False, True)
        return load3do(self.path)[0].geosets[0].meshes[0]

    def test_unused_and_noncolor_images_do_not_change_visible_texture_dimensions(self):
        self.image('unused', 16, 32)
        roughness = self.image('roughness', 256, 256)
        self.links.new(roughness.outputs['Color'], self.shader.inputs['Roughness'])
        visible = self.image('visible', 128, 64, color=True)
        self.assertEqual(getMaterialImage(self.material), visible.image)
        self.assertEqual(self.export().uvs, [(0, 0), (128, 0), (0, -64)])
        self.assert_vector(_uv_add_image_size(mathutils.Vector((1, 1)), self.material), (128, 64))

    def test_mat_cel_zero_binding_is_authoritative(self):
        self.image('visible', 128, 64, color=True)
        bound = bpy.data.images.new('bound', width=64, height=32)
        self.material[kMatCelImagePrefix + '0'] = bound
        self.assertEqual(getMaterialImage(self.material), bound)
        self.assertEqual(self.export().uvs, [(0, 0), (64, 0), (0, -32)])

    def test_legacy_single_unconnected_image_remains_supported(self):
        image = self.image('legacy', 64, 32)
        self.assertEqual(getMaterialImage(self.material), image.image)
        self.assertEqual(self.export().uvs, [(0, 0), (64, 0), (0, -32)])

    def test_color_reroute_keeps_the_connected_image(self):
        self.image('unused', 16, 16)
        image = self.image('visible', 128, 64)
        reroute = self.nodes.new('NodeReroute')
        self.links.new(image.outputs['Color'], reroute.inputs[0])
        self.links.new(reroute.outputs[0], self.shader.inputs['Base Color'])
        self.assertEqual(self.export().uvs, [(0, 0), (128, 0), (0, -64)])

    def ambiguous_color(self):
        first, second = self.image('first', 16, 32), self.image('second', 128, 64)
        mix = self.nodes.new('ShaderNodeMixRGB')
        self.links.new(first.outputs['Color'], mix.inputs[1])
        self.links.new(second.outputs['Color'], mix.inputs[2])
        self.links.new(mix.outputs['Color'], self.shader.inputs['Base Color'])

    def test_ambiguous_color_graph_fails_without_overwriting_output(self):
        self.ambiguous_color()
        self.path.write_bytes(b'previous valid export')
        with self.assertRaisesRegex(ValueError, 'Ambiguous texture images'):
            self.export()
        self.assertEqual(self.path.read_bytes(), b'previous valid export')

    def test_unconnected_ambiguous_images_are_not_guessed(self):
        self.image('first', 16, 32)
        self.image('second', 128, 64)
        with self.assertRaisesRegex(ValueError, 'Ambiguous texture images'):
            self.export()

    def test_no_uv_conversion_does_not_require_a_simple_color_graph(self):
        self.ambiguous_color()
        self.assertEqual(self.export(absolute=False).uvs, [(0, 0), (1, 0), (0, -1)])

    def test_inactive_material_output_is_ignored(self):
        old_output = next(node for node in self.nodes if node.type == 'OUTPUT_MATERIAL')
        old_output.is_active_output = False
        old_image = self.image('inactive', 16, 32, color=True)
        shader = self.nodes.new('ShaderNodeBsdfPrincipled')
        image = self.image('visible', 128, 64)
        output = self.nodes.new('ShaderNodeOutputMaterial')
        output.is_active_output = True
        self.links.new(image.outputs['Color'], shader.inputs['Base Color'])
        self.links.new(shader.outputs[0], output.inputs['Surface'])
        self.assertNotEqual(old_image.image, image.image)
        self.assertEqual(self.export().uvs, [(0, 0), (128, 0), (0, -64)])

    def test_procedural_color_does_not_fall_back_to_an_unused_image(self):
        self.image('unused', 16, 32)
        noise = self.nodes.new('ShaderNodeTexNoise')
        self.links.new(noise.outputs['Color'], self.shader.inputs['Base Color'])
        self.path.write_bytes(b'previous valid export')
        with self.assertRaisesRegex(ValueError, 'texture image'):
            self.export()
        self.assertEqual(self.path.read_bytes(), b'previous valid export')

    def test_empty_legacy_color_node_can_use_one_later_loaded_image(self):
        empty = self.nodes.new('ShaderNodeTexImage')
        self.links.new(empty.outputs['Color'], self.shader.inputs['Base Color'])
        image = self.image('later', 64, 32)
        self.assertEqual(getMaterialImage(self.material), image.image)
        self.assertEqual(self.export().uvs, [(0, 0), (64, 0), (0, -32)])

    def test_group_shader_requires_binding_instead_of_an_unused_outer_image(self):
        unused = self.image('unused', 16, 32)
        group = bpy.data.node_groups.new('shader_group', 'ShaderNodeTree')
        self.addCleanup(lambda: bpy.data.node_groups.remove(group))
        group.interface.new_socket(name='Base Color', in_out='INPUT', socket_type='NodeSocketColor')
        group.interface.new_socket(name='Shader', in_out='OUTPUT', socket_type='NodeSocketShader')
        node = self.nodes.new('ShaderNodeGroup')
        node.node_tree = group
        output = next(node for node in self.nodes if node.type == 'OUTPUT_MATERIAL')
        self.links.new(node.outputs['Shader'], output.inputs['Surface'])
        with self.assertRaisesRegex(ValueError, 'texture image'):
            self.export()
        self.material[kMatCelImagePrefix + '0'] = unused.image
        self.assertEqual(self.export().uvs, [(0, 0), (16, 0), (0, -32)])

    def mixed_group(self, color_group=False):
        self.image('visible', 64, 32, color=True)
        group = bpy.data.node_groups.new('mixed_group', 'ShaderNodeTree')
        self.addCleanup(lambda: bpy.data.node_groups.remove(group))
        socket_type = 'NodeSocketColor' if color_group else 'NodeSocketShader'
        group.interface.new_socket(name='Result', in_out='OUTPUT', socket_type=socket_type)
        output = group.nodes.new('NodeGroupOutput')
        inner = group.nodes.new('ShaderNodeTexImage')
        inner.image = bpy.data.images.new('inside_group', width=256, height=128)
        if color_group:
            group.links.new(inner.outputs['Color'], output.inputs['Result'])
        else:
            shader = group.nodes.new('ShaderNodeBsdfPrincipled')
            group.links.new(inner.outputs['Color'], shader.inputs['Base Color'])
            group.links.new(shader.outputs['BSDF'], output.inputs['Result'])
        node = self.nodes.new('ShaderNodeGroup')
        node.node_tree = group
        if color_group:
            mix = self.nodes.new('ShaderNodeMixRGB')
            self.links.new(next(n for n in self.nodes if n.type == 'TEX_IMAGE').outputs['Color'], mix.inputs[1])
            self.links.new(node.outputs['Result'], mix.inputs[2])
            self.links.new(mix.outputs['Color'], self.shader.inputs['Base Color'])
        else:
            mix = self.nodes.new('ShaderNodeMixShader')
            self.links.new(self.shader.outputs['BSDF'], mix.inputs[1])
            self.links.new(node.outputs['Result'], mix.inputs[2])
            output = next(n for n in self.nodes if n.type == 'OUTPUT_MATERIAL')
            self.links.new(mix.outputs[0], output.inputs['Surface'])
        mix.inputs[0].default_value = 1.0
        return mix

    def test_group_branch_cannot_be_hidden_by_an_outer_color_image(self):
        mix = self.mixed_group()
        self.path.write_bytes(b'previous valid export')
        # A discovered image is not enough when a sibling shader branch is
        # unresolved. The group uses a different texture size at factor 1.
        for factor in (0.5, 1.0):
            mix.inputs[0].default_value = factor
            with self.subTest(factor=factor), self.assertRaisesRegex(ValueError, 'texture image|binding'):
                self.export()
            self.assertEqual(self.path.read_bytes(), b'previous valid export')

    def test_color_group_branch_also_requires_explicit_binding(self):
        self.mixed_group(color_group=True)
        self.path.write_bytes(b'previous valid export')
        with self.assertRaisesRegex(ValueError, 'texture image|binding'):
            self.export()
        self.assertEqual(self.path.read_bytes(), b'previous valid export')

    def test_binding_resolves_mixed_group_dimensions(self):
        self.mixed_group()
        bound = bpy.data.images['inside_group']
        self.material[kMatCelImagePrefix + '0'] = bound
        self.assertEqual(self.export().uvs, [(0, 0), (256, 0), (0, -128)])

    def test_mixed_group_is_allowed_without_uv_conversion(self):
        self.mixed_group()
        self.assertEqual(self.export(absolute=False).uvs, [(0, 0), (1, 0), (0, -1)])

    def import_legacy(self):
        self.material.name = 'legacy.mat'
        root = import3do(TV / 'model/legacy_pixels.3do', clearScene=False)
        return root, root.children[0].data

    def legacy_round_trip(self, root):
        export3do(root, str(self.path), Model3doFileVersion.Version2_1, True, False, True)
        return load3do(self.path)[0].geosets[0].meshes[0]

    def test_legacy_import_ignores_unused_image_before_visible_color_image(self):
        self.image('unused', 16, 16)
        self.image('visible', 64, 32, color=True)
        root, mesh = self.import_legacy()
        self.assertEqual([tuple(value.uv) for value in mesh.uv_layers.active.data],
                         [(0, 0), (1, 0), (0, -1)])
        self.assertEqual(self.legacy_round_trip(root).uvs, [(0, 0), (64, 0), (0, 32)])

    def test_legacy_import_respects_cel_binding_over_shader_dimensions(self):
        self.image('visible', 128, 128, color=True)
        self.material[kMatCelImagePrefix + '0'] = bpy.data.images.new('bound', width=64, height=32)
        root, mesh = self.import_legacy()
        self.assertEqual([tuple(value.uv) for value in mesh.uv_layers.active.data],
                         [(0, 0), (1, 0), (0, -1)])
        self.assertEqual(self.legacy_round_trip(root).uvs, [(0, 0), (64, 0), (0, 32)])

    def test_legacy_import_can_use_binding_without_shader_nodes(self):
        self.material[kMatCelImagePrefix + '0'] = bpy.data.images.new('bound', width=64, height=32)
        self.material.use_nodes = False
        root, mesh = self.import_legacy()
        self.assertEqual([tuple(value.uv) for value in mesh.uv_layers.active.data],
                         [(0, 0), (1, 0), (0, -1)])
        self.assertEqual(self.legacy_round_trip(root).uvs, [(0, 0), (64, 0), (0, 32)])

    def test_ambiguous_import_keeps_pixel_units_instead_of_guessing(self):
        self.ambiguous_color()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            root, mesh = self.import_legacy()
        self.assertIn('UVs remain in pixel units', output.getvalue())
        self.assertEqual([tuple(value.uv) for value in mesh.uv_layers.active.data],
                         [(0, 0), (64, 0), (0, -32)])
        self.assertEqual(self.legacy_round_trip(root).uvs, [(0, 0), (64, 0), (0, 32)])

    def test_group_import_also_keeps_original_pixel_units(self):
        self.mixed_group()
        with contextlib.redirect_stdout(io.StringIO()):
            root, mesh = self.import_legacy()
        self.assertEqual([tuple(value.uv) for value in mesh.uv_layers.active.data],
                         [(0, 0), (64, 0), (0, -32)])
        self.assertEqual(self.legacy_round_trip(root).uvs, [(0, 0), (64, 0), (0, 32)])

    def test_unresolved_import_still_rejects_later_unit_conversion(self):
        self.ambiguous_color()
        with contextlib.redirect_stdout(io.StringIO()):
            root, mesh = self.import_legacy()
        self.path.write_bytes(b'previous valid export')
        with self.assertRaisesRegex(ValueError, 'Ambiguous texture images'):
            export3do(root, str(self.path), Model3doFileVersion.Version2_3, False, False, True)
        self.assertEqual(self.path.read_bytes(), b'previous valid export')

    def test_binding_and_reimport_can_normalize_previously_unresolved_uvs(self):
        self.ambiguous_color()
        with contextlib.redirect_stdout(io.StringIO()):
            self.import_legacy()
        self.material[kMatCelImagePrefix + '0'] = bpy.data.images.new('resolved', width=64, height=32)
        root, mesh = self.import_legacy()
        self.assertEqual([tuple(value.uv) for value in mesh.uv_layers.active.data],
                         [(0, 0), (1, 0), (0, -1)])
        self.assertEqual(self.legacy_round_trip(root).uvs, [(0, 0), (64, 0), (0, 32)])

    def test_zero_sized_image_keeps_pixel_uvs_without_dividing_by_zero(self):
        self.image('visible', 64, 32, color=True)
        with mock.patch('sith.model.model3doImporter.getMaterialImage',
                        return_value=SimpleNamespace(size=(0, 0))):
            with contextlib.redirect_stdout(io.StringIO()):
                root, mesh = self.import_legacy()
        self.assertEqual([tuple(value.uv) for value in mesh.uv_layers.active.data],
                         [(0, 0), (64, 0), (0, -32)])
        self.assertEqual(self.legacy_round_trip(root).uvs, [(0, 0), (64, 0), (0, 32)])

    def test_normalized_import_does_not_require_resolving_ambiguous_images(self):
        self.ambiguous_color()
        self.material.name = 'checker.mat'
        with mock.patch('sith.model.model3doImporter.getMaterialImage',
                        side_effect=AssertionError('No UV conversion is needed')):
            root = import3do(TV / 'model/triangle.3do', clearScene=False)
        mesh = root.children[0].children[0].data
        self.assertEqual([tuple(value.uv) for value in mesh.uv_layers.active.data],
                         [(0, 0), (1, 0), (0, -1)])
