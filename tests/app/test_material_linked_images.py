"""MAT reloads must localize linked images and preserve the source library."""
import hashlib
from pathlib import Path
import tempfile

import bpy

from app.support import SceneTestCase
from fixtures import INDEX8, RGB24, cmp_bytes, mat_bytes
from sith.material import ColorMap, importMat
from sith.material.mat import kMatCelImagePrefix


class MaterialLinkedImageTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        self.temporary = tempfile.TemporaryDirectory(prefix='sith-linked-images-')
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(self.clear_data)
        self.folder = Path(self.temporary.name)
        self.path = self.folder / 'linked.mat'
        self.library = self.folder / 'source.blend'
        palette = self.folder / 'test.cmp'
        palette.write_bytes(cmp_bytes())
        self.palette = ColorMap.load(palette)

    def snapshot_image(self, image):
        return (tuple(image.size), list(image.pixels), image.source,
                bytes(image.packed_file.data) if image.packed_file else None)

    def linked_material(self, *, legacy=False, custom_settings=False):
        # Create a genuine plugin material, link it back, then localize only
        # the material. Its images must remain linked until the reload fixes them.
        self.clear_data()
        self.path.write_bytes(mat_bytes(RGB24, [(2, 1, [b'\xff\0\0' * 2], False, 0),
                                                (1, 2, [b'\0\xff\0' * 2], False, 0)]))
        material = importMat(self.path)
        if custom_settings:
            for index in range(2):
                image = material[kMatCelImagePrefix + str(index)]
                image.colorspace_settings.name = 'Non-Color'
                image.alpha_mode = 'CHANNEL_PACKED'
                image.use_view_as_render = True
        bpy.data.libraries.write(str(self.library), {material})
        self.library_hash = hashlib.sha256(self.library.read_bytes()).hexdigest()
        self.clear_data()
        with bpy.data.libraries.load(str(self.library), link=True) as (source, destination):
            destination.materials = [self.path.name]
        material = destination.materials[0].make_local()
        material.use_fake_user = True
        self.assertIsNone(material.library)
        self.assertTrue(material.is_editable)
        originals = [material[kMatCelImagePrefix + str(index)] for index in range(2)]
        self.original_pixels = [self.snapshot_image(image) for image in originals]
        for image in originals:
            self.assertIsNotNone(image.library)
            self.assertFalse(image.is_editable)

        # A separate local material must keep seeing the original linked pixels.
        consumer = bpy.data.materials.new('linked_consumer')
        consumer.use_nodes, consumer.use_fake_user = True, True
        for index, image in enumerate(originals):
            node = consumer.node_tree.nodes.new('ShaderNodeTexImage')
            node.name = 'Original_' + str(index)
            node.image = image
        if legacy:
            del material[kMatCelImagePrefix + '0']
        return material, originals, consumer

    def reload_data(self, kind, resize=False):
        if kind == 'color':
            return mat_bytes(INDEX8, color_indices=[17, 255])
        sizes = ((1, 2), (2, 1)) if resize else ((2, 1), (1, 2))
        if kind == 'indexed':
            return mat_bytes(INDEX8, [(width, height, [bytes((index,)) * (width * height)], False, 0)
                                      for (width, height), index in zip(sizes, (17, 255))])
        return mat_bytes(RGB24, [(width, height, [color * (width * height)], False, 0)
                                for (width, height), color in zip(sizes, (b'\0\0\xff', b'\xff\xff\xff'))])

    def reload(self, data, palette=None):
        self.path.write_bytes(data)
        return importMat(self.path, palette)

    def assert_local_images(self, material, originals):
        images = [material[kMatCelImagePrefix + str(index)] for index in range(2)]
        for image, original in zip(images, originals):
            self.assertNotEqual(image, original)
            self.assertIsNone(image.library)
            self.assertTrue(image.is_editable)
        self.assertEqual(material.node_tree.nodes['SithTexImage'].image, images[0])
        return images

    def assert_originals_unchanged(self, originals, consumer):
        for index, image in enumerate(originals):
            self.assertEqual(consumer.node_tree.nodes['Original_' + str(index)].image, image)
            self.assertIsNotNone(image.library)
            self.assertEqual(self.snapshot_image(image), self.original_pixels[index])
        self.assertEqual(hashlib.sha256(self.library.read_bytes()).hexdigest(), self.library_hash)

    def test_reload_localizes_linked_cels_without_changing_other_users(self):
        for resize in (False, True):
            with self.subTest(resize=resize):
                material, originals, consumer = self.linked_material()
                self.assertEqual(self.reload(self.reload_data('rgb', resize)), material)
                images = self.assert_local_images(material, originals)
                self.assertEqual([tuple(image.size) for image in images],
                                 [(1, 2), (2, 1)] if resize else [(2, 1), (1, 2)])
                self.assert_vector(images[0].pixels[:4], (0, 0, 1, 1))
                self.assert_vector(images[1].pixels[:4], (1, 1, 1, 1))
                self.assertTrue(all(image.packed_file for image in images))
                self.assert_originals_unchanged(originals, consumer)

    def test_legacy_linked_cel_zero_is_localized_before_reload(self):
        material, originals, consumer = self.linked_material(legacy=True)
        self.reload(self.reload_data('rgb', True))
        self.assert_local_images(material, originals)
        self.assert_originals_unchanged(originals, consumer)

    def test_linked_palette_cels_support_decoding_and_missing_palette_grids(self):
        for kind in ('indexed', 'color'):
            for has_palette in (False, True):
                with self.subTest(kind=kind, palette=has_palette):
                    material, originals, consumer = self.linked_material()
                    files = set(self.folder.iterdir())
                    self.reload(self.reload_data(kind, True), self.palette if has_palette else None)
                    images = self.assert_local_images(material, originals)
                    sizes = [(32, 32)] * 2 if kind == 'color' else [(1, 2), (2, 1)]
                    for image, dimensions, color in zip(images, sizes, (17, 255)):
                        self.assertEqual(tuple(image.size), dimensions)
                        if has_palette:
                            self.assertIsNotNone(image.packed_file)
                            self.assert_vector(image.pixels[:4], (*[v / 255 for v in self.palette.palette[color]], 1))
                        else:
                            self.assertIsNone(image.packed_file)
                            self.assertEqual(image.source, 'GENERATED')
                            self.assertEqual(image.generated_type, 'UV_GRID')
                            expected = bpy.data.images.new('expected_grid', width=dimensions[0], height=dimensions[1])
                            expected.generated_type = 'UV_GRID'
                            expected.update()
                            self.assertEqual(list(image.pixels), list(expected.pixels))
                            bpy.data.images.remove(expected)
                    self.assertEqual(set(self.folder.iterdir()), files)
                    self.assert_originals_unchanged(originals, consumer)

    def test_localized_images_survive_save_and_reopen(self):
        # Reopen the actual file: appending IDs in the same Main can reuse a
        # cached linked image and hide the lost-update bug.
        for kind, resize in (('rgb', False), ('rgb', True), ('indexed', True), ('color', False)):
            with self.subTest(kind=kind, resize=resize):
                material, originals, consumer = self.linked_material()
                self.reload(self.reload_data(kind, resize), self.palette if kind == 'color' else None)
                images = [material[kMatCelImagePrefix + str(index)] for index in range(2)]
                expected = [self.snapshot_image(image) for image in images]
                saved = self.folder / 'saved.blend'
                bpy.ops.wm.save_as_mainfile(filepath=str(saved))
                bpy.ops.wm.open_mainfile(filepath=str(saved))

                # All previous RNA pointers were invalidated by opening the file.
                material = bpy.data.materials[self.path.name]
                consumer = bpy.data.materials['linked_consumer']
                originals = [consumer.node_tree.nodes['Original_' + str(index)].image for index in range(2)]
                images = [material[kMatCelImagePrefix + str(index)] for index in range(2)]
                self.assertEqual([self.snapshot_image(image) for image in images], expected)
                self.assert_local_images(material, originals)
                self.assert_originals_unchanged(originals, consumer)

    def test_failed_decode_does_not_copy_or_rebind_linked_images(self):
        material, originals, consumer = self.linked_material()
        images = set(bpy.data.images)
        node = material.node_tree.nodes['SithTexImage']
        with self.assertRaises(ImportError):
            self.reload(self.reload_data('rgb', True)[:-1])
        self.assertEqual(set(bpy.data.images), images)
        self.assertEqual([material[kMatCelImagePrefix + str(index)] for index in range(2)], originals)
        self.assertEqual(node.image, originals[0])
        self.assert_originals_unchanged(originals, consumer)

    def test_following_reload_reuses_and_updates_shared_local_copies(self):
        material, originals, consumer = self.linked_material()
        self.reload(self.reload_data('rgb'))
        images = self.assert_local_images(material, originals)
        shared = bpy.data.materials.new('local_consumer')
        shared.use_nodes = True
        node = shared.node_tree.nodes.new('ShaderNodeTexImage')
        node.image = images[0]
        self.reload(self.reload_data('rgb', True))
        self.assertEqual([material[kMatCelImagePrefix + str(index)] for index in range(2)], images)
        self.assertEqual(node.image, images[0])
        self.assertEqual(tuple(node.image.size), (1, 2))
        self.assert_vector(node.image.pixels[:4], (0, 0, 1, 1))
        self.assert_originals_unchanged(originals, consumer)

    def test_local_copy_retains_image_color_and_alpha_settings(self):
        material, originals, consumer = self.linked_material(custom_settings=True)
        self.reload(self.reload_data('rgb'))
        for image in self.assert_local_images(material, originals):
            self.assertEqual(image.colorspace_settings.name, 'Non-Color')
            self.assertEqual(image.alpha_mode, 'CHANNEL_PACKED')
            self.assertTrue(image.use_view_as_render)
        self.assert_originals_unchanged(originals, consumer)
