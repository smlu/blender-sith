"""3DO texture bundles use real Blender images and safe opt-in publication."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest import mock

import bpy
import numpy as np

from app.support import SceneTestCase
from core.test_mat_writer import decode, expected_pixels
from fixtures import cmp_bytes
from sith import app
from sith.material import ColorMap, importMat
from sith.material.mat import kMatCelImagePrefix, kMatMissingPixels
from sith.model.model3doExporter import export3do
from sith.model.model3doLoader import load3do, Model3doFileFormat, Model3doFileVersion
from sith.model.model3doImporter import import3do
from sith.model.utils import kModel3doGeometryMode


class MatExportTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.path = self.folder / 'model.3do'
        self.palette_path = self.folder / 'test.cmp'
        self.palette_path.write_bytes(cmp_bytes())
        self.material = bpy.data.materials.new('test.mat')
        self.pixels = np.array([(0.2, 0.4, 0.6, 1), (0.7, 0.3, 0.1, 0),
                                (0, 1, 0, 0.5), (1, 0, 0, 1)], dtype=np.float32)
        self.image = self.image_cel(0, 2, 2, self.pixels)
        mesh = bpy.data.meshes.new('triangle')
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        mesh.uv_layers.new()
        for loop, uv in zip(mesh.uv_layers.active.data, ((0, 0), (1, 0), (0, 1))):
            loop.uv = uv
        mesh.materials.append(self.material)
        self.obj = bpy.data.objects.new('triangle', mesh)
        bpy.context.scene.collection.objects.link(self.obj)
        setattr(self.obj, kModel3doGeometryMode, 'Texture')
        bpy.context.view_layer.objects.active = self.obj
        self.obj.select_set(True)

    def image_cel(self, index, width, height, pixels):
        image = bpy.data.images.new(f'cel{index}', width, height, float_buffer=True)
        image.pixels.foreach_set(np.asarray(pixels, dtype=np.float32).ravel())
        image.update()
        self.material[kMatCelImagePrefix + str(index)] = image
        return image

    def export(self, **kwargs):
        options = dict(exportTextures=True)
        options.update(kwargs)
        export3do(self.obj, str(self.path), Model3doFileVersion.Version2_3, False, False, True, **options)

    def test_texture_export_is_opt_in_and_preserves_old_behavior(self):
        self.export(exportTextures=False)
        self.assertTrue(self.path.is_file())
        self.assertFalse((self.folder / 'mat').exists())
        properties = bpy.ops.export_scene.sith_3do.get_rna_type().properties
        self.assertFalse(properties['export_textures'].default)
        self.assertFalse(properties['overwrite_textures'].default)
        self.assertTrue(properties['texture_mipmaps'].default)
        self.assertEqual(properties['texture_directory'].default, 'mat')
        self.assertEqual(properties['texture_encoding'].enum_items['RGBA32'].name, 'RGBA32')

    def test_relative_and_absolute_custom_directories(self):
        for directory in ('textures/deep', str(self.folder / 'absolute-mats')):
            with self.subTest(directory=directory):
                self.export(textureDirectory=directory)
                target = Path(directory)
                if not target.is_absolute():
                    target = self.folder / target
                self.assertTrue((target / 'test.mat').is_file())
        self.assertFalse((self.folder / 'mat').exists())

    def test_operator_custom_directory_resolves_beside_the_model(self):
        target = self.folder / 'models/model.3do'
        target.parent.mkdir()
        self.assertEqual(bpy.ops.export_scene.sith_3do(filepath=str(target), export_textures=True,
                         texture_directory='../shared'), {'FINISHED'})
        self.assertTrue((self.folder / 'shared/test.mat').is_file())

    def test_cleanup_warning_does_not_fail_a_completed_export(self):
        warnings = []
        with mock.patch('sith.model.model3doExporter.shutil.rmtree', side_effect=OSError('busy')):
            self.export(warnings=warnings)
        self.assertTrue(self.path.is_file())
        self.assertTrue((self.folder / 'mat/test.mat').is_file())
        self.assertTrue(any('temporary directory' in warning for warning in warnings))

    def test_six_encoding_options_export_and_parse_real_material_pixels(self):
        cmp = ColorMap.load(self.palette_path)
        for encoding in ('RGBA32', 'RGB24', 'RGB565', 'RGBA4444', 'RGBA1555', 'INDEXED'):
            with self.subTest(encoding=encoding):
                self.export(textureEncoding=encoding, texturePalette=str(self.palette_path), overwriteTextures=True)
                output = self.folder / 'mat/test.mat'
                header, _, cels = decode(output.read_bytes(), cmp)
                self.assertEqual((cels[0].width, cels[0].height), (2, 2))
                self.assertEqual(len(cels[0].pixel_data_array), 2)
                model, _ = load3do(self.path)
                self.assertEqual(model.materials, ['test.mat'])
                self.assertEqual(header.color_info.bpp, 8 if encoding == 'INDEXED' else
                                 32 if encoding == 'RGBA32' else 24 if encoding == 'RGB24' else 16)
                np.testing.assert_allclose(np.asarray(cels[0].pixel_data_array[0]).reshape((-1, 4)),
                                           expected_pixels(self.pixels, encoding, cmp), atol=1e-12, rtol=0)
                # Reading pixels and exporting previewed materials must not bake
                # lighting, change source images, or replace material bindings.
                np.testing.assert_array_equal(np.asarray(self.image.pixels[:]).reshape((-1, 4)), self.pixels)
                self.assertEqual(self.material[kMatCelImagePrefix + '0'], self.image)

    def test_existing_mat_is_kept_by_default_and_replaced_only_when_requested(self):
        output = self.folder / 'mat/test.mat'
        output.parent.mkdir()
        output.write_bytes(b'previous material')
        warnings = []
        self.export(warnings=warnings, textureEncoding='INDEXED')
        self.assertEqual(output.read_bytes(), b'previous material')
        self.assertTrue(any('Kept existing MAT' in warning for warning in warnings))
        self.export(overwriteTextures=True)
        self.assertEqual(output.read_bytes()[:4], b'MAT ')

    def test_missing_palette_and_bad_later_cel_do_not_replace_model_or_mat(self):
        self.path.write_bytes(b'previous model')
        for options in ({'textureEncoding': 'INDEXED'}, {'textureEncoding': 'INDEXED', 'texturePalette': 'missing.cmp'}):
            with self.assertRaises((ValueError, ImportError)):
                self.export(**options)
            self.assertEqual(self.path.read_bytes(), b'previous model')
            self.assertFalse((self.folder / 'mat').exists())
        self.material[kMatCelImagePrefix + '1'] = 'not an image'
        with self.assertRaisesRegex(ValueError, 'invalid image binding'):
            self.export()
        self.assertEqual(self.path.read_bytes(), b'previous model')

    def test_all_bound_cels_are_written_in_index_order(self):
        self.image_cel(1, 4, 2, np.ones((2, 4, 4)))
        self.export()
        header, records, cels = decode((self.folder / 'mat/test.mat').read_bytes())
        self.assertEqual(header.record_count, 2)
        self.assertEqual([record.cel_idx for record in records], [0, 1])
        self.assertEqual([(cel.width, cel.height) for cel in cels], [(2, 2), (4, 2)])

    def test_missing_cel_and_normalized_name_collisions_reject_before_writing(self):
        self.image_cel(2, 1, 1, [1, 1, 1, 1])
        with self.assertRaisesRegex(ValueError, 'missing cels'):
            self.export()
        del self.material[kMatCelImagePrefix + '2']
        other = self.material.copy()
        self.obj.data.materials.append(other)
        with self.assertRaisesRegex(ValueError, 'Different Blender materials'):
            self.export()
        self.assertFalse(self.path.exists())

    def test_mipmap_switch_and_reimport_match_the_exported_base_pixels(self):
        self.export(generateMipmaps=False)
        output = self.folder / 'mat/test.mat'
        expected = decode(output.read_bytes())[2][0].pixel_data_array[0]
        self.assertEqual(len(decode(output.read_bytes())[2][0].pixel_data_array), 1)
        restored = importMat(output)
        actual = restored[kMatCelImagePrefix + '0'].pixels[:]
        np.testing.assert_allclose(actual, expected, atol=1e-6)

    def test_file_backed_png_color_values_survive_without_shader_baking(self):
        import struct
        import zlib
        def chunk(kind, data):
            return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
        source = self.folder / 'source.png'
        source.write_bytes(b'\x89PNG\r\n\x1a\n'
                           + chunk(b'IHDR', struct.pack('>2I5B', 1, 1, 8, 6, 0, 0, 0))
                           + chunk(b'IDAT', zlib.compress(bytes((0, 128, 64, 32, 255)))) + chunk(b'IEND', b''))
        image = bpy.data.images.load(str(source))
        del self.material[kMatCelImagePrefix + '0']
        self.material.use_nodes = True
        texture = self.material.node_tree.nodes.new('ShaderNodeTexImage')
        texture.image = image
        shader = next(node for node in self.material.node_tree.nodes if node.type == 'BSDF_PRINCIPLED')
        self.material.node_tree.links.new(texture.outputs['Color'], shader.inputs['Base Color'])
        self.export(generateMipmaps=False)
        pixels = decode((self.folder / 'mat/test.mat').read_bytes())[2][0].pixel_data_array[0]
        np.testing.assert_allclose(pixels, (128 / 255, 64 / 255, 32 / 255, 1), atol=1e-6)

    def test_placeholder_pixels_and_unsafe_output_names_are_not_exported(self):
        self.image[kMatMissingPixels] = True
        with self.assertRaisesRegex(ValueError, 'no exportable'):
            self.export()
        del self.image[kMatMissingPixels]
        self.material.name = '../escape.mat'
        with self.assertRaisesRegex(ValueError, 'Unsafe MAT output filename'):
            self.export()
        self.assertFalse(self.path.exists())

    def test_relative_palette_and_grim_indexed_operator_output(self):
        self.assertEqual(bpy.ops.export_scene.sith_3do(filepath=str(self.path), version='GrimFandango',
                         export_textures=True, texture_cmp_file='test.cmp'), {'FINISHED'})
        header, _, _ = decode((self.folder / 'mat/test.mat').read_bytes(), ColorMap.load(self.palette_path))
        self.assertEqual(header.type, 3)
        _, format = load3do(self.path)
        self.assertEqual(format, Model3doFileFormat.GrimFandango)

    def test_indexed_23_model_can_reload_with_explicit_cmp(self):
        self.export(textureEncoding='INDEXED', texturePalette=str(self.palette_path))
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        for material in list(bpy.data.materials):
            bpy.data.materials.remove(material)
        for image in list(bpy.data.images):
            bpy.data.images.remove(image)
        root = import3do(self.path, cmp_file=str(self.palette_path), clearScene=False)
        mesh = next(obj for obj in root.children_recursive if obj.type == 'MESH')
        image = mesh.data.materials[0][kMatCelImagePrefix + '0']
        self.assertNotIn(kMatMissingPixels, image)
        self.assertEqual(tuple(image.size), (2, 2))

    def test_export_options_are_hidden_until_enabled_and_cmp_is_indexed_only(self):
        for enabled in (False, True):
            for encoding in ('RGBA32', 'INDEXED'):
                layout = mock.Mock()
                owner = SimpleNamespace(layout=layout, version='Version2_3', export_textures=enabled, texture_encoding=encoding)
                app.ExportModel3do.draw(owner, None)
                names = [call.args[1] for call in layout.mock_calls if call[0].endswith('prop')]
                self.assertEqual('texture_encoding' in names, enabled)
                self.assertEqual('texture_directory' in names, enabled)
                self.assertEqual('texture_cmp_file' in names, enabled and encoding == 'INDEXED')
                self.assertEqual('overwrite_textures' in names, enabled)
        layout = mock.Mock()
        owner = SimpleNamespace(layout=layout, version='GrimFandango', export_textures=True, texture_encoding='INDEXED')
        app.ExportModel3do.draw(owner, None)
        names = [call.args[1] for call in layout.mock_calls if call[0].endswith('prop')]
        self.assertNotIn('texture_mipmaps', names)
