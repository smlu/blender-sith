from pathlib import Path
import contextlib
import struct
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import bpy

from app.support import SceneTestCase
from fixtures import INDEX8, RGB565, RGB24, RGBA32, RGBA4444, cmp_bytes, mat_bytes
from sith.material import ColorMap, importMat
from sith.material import mat


class MaterialImportTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'synthetic.mat'
        palette_path = self.path.with_suffix('.cmp')
        palette_path.write_bytes(cmp_bytes())
        self.palette = ColorMap.load(palette_path)

    def load(self, data, palette=None):
        self.path.write_bytes(data)
        return importMat(self.path, palette)

    def image_node(self, material):
        return material.node_tree.nodes['SithTexImage']

    def test_rgba_image_pixels_and_shader_links(self):
        material = self.load(mat_bytes())
        node = self.image_node(material)
        self.assertEqual(tuple(node.image.size), (2, 2))
        self.assert_vector(node.image.pixels[:4], (0, 0, 1, 0))
        self.assertIsNotNone(node.image.packed_file)
        bsdf = next(n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
        self.assertTrue(bsdf.inputs['Base Color'].is_linked)
        self.assertTrue(bsdf.inputs['Alpha'].is_linked)
        self.assertEqual(bsdf.inputs['Specular IOR Level'].default_value, 0)
        self.assertEqual(bsdf.inputs['Roughness'].default_value, 1)

    def test_opaque_rgb_does_not_link_alpha(self):
        material = self.load(mat_bytes(RGB24, [(1, 1, [bytes((20, 40, 60))], False, 0)]))
        bsdf = next(n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
        self.assertFalse(bsdf.inputs['Alpha'].is_linked)
        self.assert_vector(self.image_node(material).image.pixels[:], (20 / 255, 40 / 255, 60 / 255, 1))

    def test_transparency_overlap_tracks_opaque_transparent_and_mixed_reloads(self):
        opaque = mat_bytes(RGB24, [(1, 1, [bytes((20, 40, 60))], False, 0)])
        transparent = mat_bytes()
        mixed = mat_bytes(INDEX8, [(1, 1, [b'\0'], False, 0), (1, 1, [b'\xff'], True, 255)])
        material = self.load(opaque)
        for data, expected in ((transparent, True), (opaque, False), (mixed, True), (opaque, False)):
            with self.subTest(transparent=expected, mixed=data == mixed):
                # Seed the opposite value so a stale reload setting cannot pass.
                material.use_transparency_overlap = not expected
                self.assertEqual(self.load(data, self.palette), material)
                self.assertEqual(material.use_transparency_overlap, expected)
                self.assertFalse(material.use_transparent_shadow)

    def test_transparency_overlap_does_not_depend_on_the_legacy_alias(self):
        for transparent in (False, True):
            material = SimpleNamespace(is_editable=True, use_transparency_overlap=not transparent, keys=lambda: ())
            fake_bpy = SimpleNamespace(data=SimpleNamespace(materials={self.path.name: material}))
            data = mat_bytes() if transparent else mat_bytes(RGB24, [(1, 1, [b'\0' * 3], False, 0)])
            with self.subTest(transparent=transparent):
                # Keep real resource decoding, but remove the deprecated Blender
                # property alias which would otherwise mask a misspelled branch.
                with patch.dict('sys.modules', {'bpy': fake_bpy}), patch.object(mat, '_mat_add_new_texture'):
                    self.assertIs(self.load(data), material)
                self.assertEqual(material.use_transparency_overlap, transparent)
                self.assertFalse(material.use_transparent_shadow)
                self.assertFalse(hasattr(material, 'show_transparent_back'))

    def test_indexed_transparency_uses_palette(self):
        material = self.load(mat_bytes(INDEX8, [(2, 1, [b'\x00\xff'], True, 255)]), self.palette)
        image = self.image_node(material).image
        self.assert_vector(image.pixels[:4], (0, 1, 0, 1))
        self.assert_vector(image.pixels[4:8], (1, 0, 127 / 255, 0))

    def test_multiple_cels_are_loaded_and_named(self):
        material = self.load(mat_bytes(INDEX8, [(1, 1, [b'\0'], False, 0),
                                               (2, 1, [b'\1\2'], True, 2)]), self.palette)
        self.assertEqual(tuple(bpy.data.images['synthetic'].size), (1, 1))
        self.assertEqual(tuple(bpy.data.images['synthetic_cel_1'].size), (2, 1))
        bsdf = next(n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
        self.assertFalse(bsdf.inputs['Alpha'].is_linked)

    def test_shorter_reload_removes_stale_bindings_but_keeps_shared_images(self):
        original = mat_bytes(RGB24, [(1, 1, [bytes((index, 20, 40))], False, 0) for index in (1, 2, 3)])
        for kind in ('texture', 'color', 'limited'):
            with self.subTest(kind=kind):
                self.clear_data()
                material = self.load(original)
                images = [material[mat.kMatCelImagePrefix + str(index)] for index in range(3)]
                pixels = [list(image.pixels) for image in images]
                material['user_property'] = 'keep'
                material[mat.kMatCelImagePrefix + 'notes'] = 'keep'
                shared = bpy.data.materials.new('shared')
                shared.use_nodes = True
                nodes = [shared.node_tree.nodes.new('ShaderNodeTexImage') for _ in images[1:]]
                for node, image in zip(nodes, images[1:]):
                    node.image = image

                incoming = (mat_bytes(INDEX8, color_indices=[17]) if kind == 'color' else
                            original if kind == 'limited' else
                            mat_bytes(RGB24, [(1, 1, [b'\0\0\xff'], False, 0)]))
                limit = patch.object(mat, '_max_cels', return_value=1) if kind == 'limited' else contextlib.nullcontext()
                with limit:
                    self.assertEqual(self.load(incoming, self.palette), material)
                self.assertEqual(material[mat.kMatCelImagePrefix + '0'], images[0])
                for index in (1, 2):
                    self.assertNotIn(mat.kMatCelImagePrefix + str(index), material)
                    self.assertEqual(nodes[index - 1].image, images[index])
                    self.assertEqual(list(images[index].pixels), pixels[index])
                self.assertEqual(material['user_property'], 'keep')
                self.assertEqual(material[mat.kMatCelImagePrefix + 'notes'], 'keep')

                # A later growth must create new cel images, not overwrite the
                # detached image IDs that another material still owns.
                self.load(original)
                for index in (1, 2):
                    self.assertNotEqual(material[mat.kMatCelImagePrefix + str(index)], images[index])
                    self.assertEqual(nodes[index - 1].image, images[index])
                    self.assertEqual(list(images[index].pixels), pixels[index])

    def test_failed_shorter_reload_retains_all_existing_cel_bindings(self):
        data = mat_bytes(RGB24, [(1, 1, [bytes((index, 20, 40))], False, 0) for index in (1, 2, 3)])
        material = self.load(data)
        bindings = {name: material[name] for name in material.keys()}
        pixels = [list(image.pixels) for image in bindings.values()]
        with self.assertRaises(ImportError):
            self.load(mat_bytes(RGB24, [(1, 1, [b'\0\0\xff'], False, 0)])[:-1])
        self.assertEqual({name: material[name] for name in material.keys()}, bindings)
        self.assertEqual([list(image.pixels) for image in bindings.values()], pixels)

    def test_missing_palette_creates_placeholders_for_all_cels(self):
        material = self.load(mat_bytes(INDEX8, [(2, 2, [b'\0' * 4], False, 0),
                                               (1, 1, [b'\0'], False, 0)]))
        self.assertEqual(tuple(self.image_node(material).image.size), (2, 2))
        self.assertEqual(tuple(bpy.data.images['synthetic_cel_1'].size), (1, 1))

    def test_cel_limit_preserves_selected_mipmap_chain(self):
        data = mat_bytes(INDEX8, [(4, 2, [b'\x01' * 8, b'\x02' * 2, b'\x03'], False, 0),
                                 (1, 1, [b'\xff'], True, 255)])
        with patch.object(mat, '_max_cels', return_value=1) as limit, \
             patch.object(mat, '_read_mipmap', wraps=mat._read_mipmap) as read_mipmap, \
             patch.object(mat, '_read_pixel_data', wraps=mat._read_pixel_data) as read_pixels:
            material = self.load(data, self.palette)
        limit.assert_called_once_with(2)
        self.assertEqual(read_mipmap.call_count, 1)
        self.assertEqual(read_pixels.call_count, 3)
        self.assertEqual(tuple(self.image_node(material).image.size), (4, 2))
        self.assertNotIn('synthetic_cel_1', bpy.data.images)
        self.assertFalse(next(n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED').inputs['Alpha'].is_linked)

    def test_missing_palette_reload_resets_packed_cels_and_keeps_shared_bindings(self):
        for solid in (False, True):
            for resize in (False, True):
                with self.subTest(solid=solid, resize=resize):
                    self.clear_data()
                    initial = (mat_bytes(INDEX8, color_indices=[17, 255]) if solid else
                               mat_bytes(INDEX8, [(2, 1, [b'\x11' * 2], False, 0),
                                                 (1, 1, [b'\xff'], False, 0)]))
                    material = self.load(initial, self.palette)
                    images = [material[mat.kMatCelImagePrefix + str(index)] for index in range(2)]
                    shared = bpy.data.materials.new('shared')
                    shared.use_nodes = True
                    nodes = [shared.node_tree.nodes.new('ShaderNodeTexImage') for _ in images]
                    for index, (image, node) in enumerate(zip(images, nodes)):
                        image.name = 'renamed_' + str(index)
                        image.filepath_raw = str(self.path.with_name(f'never_unpack_{index}.png'))
                        node.image = image

                    # Losing the palette must replace old pixels, even when the
                    # new file changes size. REMOVE must not unpack files to disk.
                    data = (mat_bytes(INDEX8, color_indices=[17, 255]) if solid else
                            mat_bytes(INDEX8, [(3 if resize else 2, 1,
                                                [b'\x11' * (3 if resize else 2)], False, 0),
                                               (1, 2 if resize else 1,
                                                [b'\xff' * (2 if resize else 1)], False, 0)]))
                    files = set(self.path.parent.iterdir())
                    self.assertEqual(self.load(data), material)
                    self.assertEqual([node.image for node in nodes], images)
                    for index, image in enumerate(images):
                        dimensions = ((32, 32) if solid else
                                      ((3 if resize else 2, 1) if index == 0 else (1, 2 if resize else 1)))
                        self.assertEqual(material[mat.kMatCelImagePrefix + str(index)], image)
                        self.assertEqual(tuple(image.size), dimensions)
                        self.assertEqual(image.source, 'GENERATED')
                        self.assertEqual(image.generated_type, 'UV_GRID')
                        self.assertIsNone(image.packed_file)
                        expected = bpy.data.images.new('expected_grid', width=dimensions[0], height=dimensions[1])
                        expected.generated_type = 'UV_GRID'
                        expected.update()
                        self.assertEqual(list(image.pixels), list(expected.pixels))
                        bpy.data.images.remove(expected)
                    self.assertEqual(set(self.path.parent.iterdir()), files)

                    # A later palette-backed reload must restore real pixels in
                    # those same datablocks, without disconnecting other users.
                    self.load(data, self.palette)
                    self.assertEqual([node.image for node in nodes], images)
                    for image, colorIndex in zip(images, (17, 255)):
                        self.assertIsNotNone(image.packed_file)
                        rgba = (*[channel / 255 for channel in self.palette.palette[colorIndex]], 1)
                        self.assert_vector(image.pixels[:4], rgba)

    def test_color_material_never_reads_texture_mipmaps(self):
        data = bytearray(mat_bytes(INDEX8, color_indices=[17, 255]))
        # A color MAT has no texture payload, irrespective of this unused field.
        struct.pack_into('<i', data, 16, 2)
        with patch.object(mat, '_read_mipmap', side_effect=AssertionError('Color MAT read texture data')) as read_mipmap:
            material = self.load(data, self.palette)
        read_mipmap.assert_not_called()
        self.assertEqual(tuple(self.image_node(material).image.size), (32, 32))
        self.assertIn('synthetic_cel_1', bpy.data.images)

    def test_default_cel_policy_loads_more_than_legacy_texture_slots(self):
        cels = [(1, 1, [bytes((index, 0, 0))], False, 0) for index in range(20)]
        self.load(mat_bytes(RGB24, cels))
        self.assertEqual(len(bpy.data.images), 20)
        for index in range(20):
            name = mat._get_tex_name(index, 'synthetic.mat')
            self.assert_vector(bpy.data.images[name].pixels[:], (index / 255, 0, 0, 1))

    def test_later_cel_failure_preserves_loaded_material(self):
        material = self.load(mat_bytes())
        address = self.image_node(material).image.as_pointer()
        data = mat_bytes(RGB24, [(1, 1, [bytes((1, 2, 3))], False, 0),
                                (1, 1, [bytes((4, 5, 6))], False, 0)])
        with self.assertRaises(ImportError):
            self.load(data[:-1])
        self.assertEqual(self.image_node(material).image.as_pointer(), address)
        self.assertEqual(len(bpy.data.materials), 1)
        self.assertNotIn('synthetic_cel_1', bpy.data.images)

    def test_palette_color_material(self):
        material = self.load(mat_bytes(INDEX8, color_indices=[17, 255]), self.palette)
        image = self.image_node(material).image
        self.assertEqual(tuple(image.size), (32, 32))
        self.assert_vector(image.pixels[:4], (17 / 255, 238 / 255, 8 / 255, 1))
        self.assertIn('synthetic_cel_1', bpy.data.images)

    def test_reload_reuses_material_and_replaces_texture_size(self):
        first = self.load(mat_bytes())
        address = first.as_pointer()
        second = self.load(mat_bytes(RGBA32, [(1, 1, [bytes((5, 10, 15, 255))], False, 0)]))
        self.assertEqual(second.as_pointer(), address)
        self.assertEqual(len(bpy.data.materials), 1)
        self.assertEqual(tuple(self.image_node(second).image.size), (1, 1))
        self.assert_vector(self.image_node(second).image.pixels[:], (5 / 255, 10 / 255, 15 / 255, 1))

    def test_invalid_file_does_not_create_material(self):
        with self.assertRaises((ImportError, ValueError)):
            self.load(b'not a material')
        self.assertEqual(len(bpy.data.materials), 0)

    def test_truncated_pixels_do_not_create_or_destroy_material(self):
        with self.assertRaises(ImportError):
            self.load(mat_bytes()[:-1])
        self.assertEqual(len(bpy.data.materials), 0)
        material = self.load(mat_bytes())
        image = self.image_node(material).image
        address = image.as_pointer()
        with self.assertRaises(ImportError):
            self.load(mat_bytes()[:-1])
        self.assertEqual(self.image_node(material).image.as_pointer(), address)
        self.assertEqual(len(bpy.data.materials), 1)

    def test_registered_import_operator(self):
        self.path.write_bytes(mat_bytes())
        result = bpy.ops.import_material.sith_mat(filepath=str(self.path))
        self.assertEqual(result, {'FINISHED'})
        self.assertIn('synthetic.mat', bpy.data.materials)

    def test_first_import_preserves_unrelated_images_with_matching_cel_names(self):
        # Both texture and palette-color MATs must allocate their own images.
        for solid in (False, True):
            with self.subTest(solid=solid):
                self.clear_data()
                images = [bpy.data.images.new(name, width=1, height=1)
                          for name in ('synthetic', 'synthetic_cel_1')]
                other = bpy.data.materials.new('unrelated')
                other.use_nodes = True
                nodes = [other.node_tree.nodes.new('ShaderNodeTexImage') for _ in images]
                for image, node in zip(images, nodes):
                    image.pixels[:] = (0.25, 0.5, 0.75, 1)
                    node.image = image
                pixels = [list(image.pixels) for image in images]

                data = (mat_bytes(INDEX8, color_indices=[17, 255]) if solid else
                        mat_bytes(RGB24, [(2, 1, [b'\xff\0\0' * 2], False, 0),
                                          (1, 1, [b'\0\xff\0'], False, 0)]))
                material = self.load(data, self.palette)

                for index, (image, node) in enumerate(zip(images, nodes)):
                    self.assertEqual(node.image, image)
                    self.assertEqual(tuple(image.size), (1, 1))
                    self.assertEqual(list(image.pixels), pixels[index])
                    self.assertNotIn(material[mat.kMatCelImagePrefix + str(index)], images)

    def test_reload_follows_renamed_cel_bindings_and_preserves_shared_users(self):
        data = mat_bytes(RGB24, [(1, 1, [b'\xff\0\0'], False, 0),
                                 (1, 1, [b'\0\xff\0'], False, 0)])
        material = self.load(data)
        images = [material[mat.kMatCelImagePrefix + str(index)] for index in range(2)]
        other = bpy.data.materials.new('shared_users')
        other.use_nodes = True
        nodes = []
        for index, image in enumerate(images):
            image.name = 'renamed_cel_' + str(index)
            node = other.node_tree.nodes.new('ShaderNodeTexImage')
            node.image = image
            nodes.append(node)

        # Reusing an old display name must not redirect the reload to a stranger.
        decoy = bpy.data.images.new('synthetic', width=1, height=1)
        decoy.pixels[:] = (1, 1, 0, 1)
        before = list(decoy.pixels)
        self.load(mat_bytes(RGB24, [(2, 1, [b'\0\0\xff' * 2], False, 0),
                                    (1, 1, [b'\xff\xff\xff'], False, 0)]))
        self.assertEqual(self.image_node(material).image, images[0])
        self.assertEqual([node.image for node in nodes], images)
        self.assertEqual(tuple(images[0].size), (2, 1))
        self.assert_vector(images[0].pixels[:4], (0, 0, 1, 1))
        self.assert_vector(images[1].pixels[:], (1, 1, 1, 1))
        self.assertEqual(list(decoy.pixels), before)

    def test_reload_adopts_legacy_cel_zero_from_its_material_node(self):
        material = self.load(mat_bytes())
        image = self.image_node(material).image
        del material[mat.kMatCelImagePrefix + '0']
        image.name = 'legacy_renamed_image'
        self.load(mat_bytes(RGB24, [(1, 1, [b'\xff\0\0'], False, 0)]))
        self.assertEqual(self.image_node(material).image, image)
        self.assertEqual(material[mat.kMatCelImagePrefix + '0'], image)
        self.assert_vector(image.pixels[:], (1, 0, 0, 1))

    def test_deleted_cel_binding_does_not_adopt_an_unrelated_replacement(self):
        material = self.load(mat_bytes())
        bpy.data.images.remove(self.image_node(material).image)
        decoy = bpy.data.images.new('synthetic', width=1, height=1)
        decoy.pixels[:] = (1, 1, 0, 1)
        before = list(decoy.pixels)
        self.load(mat_bytes())
        self.assertNotEqual(self.image_node(material).image, decoy)
        self.assertEqual(list(decoy.pixels), before)

    def test_cel_bindings_survive_blend_library_serialization(self):
        material = self.load(mat_bytes())
        path = self.path.with_suffix('.blend')
        bpy.data.libraries.write(str(path), {material})
        with bpy.data.libraries.load(str(path)) as (source, destination):
            destination.materials = [material.name]
        restored = destination.materials[0]
        self.assertEqual(restored[mat.kMatCelImagePrefix + '0'], self.image_node(restored).image)
        self.assertNotEqual(restored, material)

    def test_packed_white_and_opaque_alpha_reach_one_in_blender(self):
        for fmt in (RGB565, RGBA4444):
            with self.subTest(fmt=fmt):
                material = self.load(mat_bytes(fmt, [(1, 1, [b'\xff\xff'], False, 0)]))
                self.assert_vector(self.image_node(material).image.pixels[:], (1, 1, 1, 1))
