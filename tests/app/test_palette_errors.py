"""Malformed palettes must report controlled errors without replacing materials."""
import contextlib
from pathlib import Path
import tempfile
from types import SimpleNamespace

import bpy

from app.support import SceneTestCase
from fixtures import cmp_bytes, mat_bytes
from sith import app
from sith.material.mat import kMatCelImagePrefix


class PaletteErrorTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.source = self.folder / 'paint.mat'
        self.source.write_bytes(mat_bytes())

    def assert_controlled_error(self, palette, message):
        reports = []
        operator = SimpleNamespace(filepath=str(self.source), cmp_file=str(palette),
                                   report=lambda *args: reports.append(args))
        self.assertEqual(app.ImportMat.execute(operator, bpy.context), {'CANCELLED'})
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0][0], {'ERROR'})
        self.assertEqual(reports[0][1], 'Cannot import MAT: ' + message)

    def test_header_and_palette_failures_preserve_existing_materials(self):
        self.assertEqual(bpy.ops.import_material.sith_mat(filepath=str(self.source)), {'FINISHED'})
        material = bpy.data.materials[self.source.name]
        image = material[kMatCelImagePrefix + '0']
        nodes = [node.as_pointer() for node in material.node_tree.nodes]
        pixels = list(image.pixels)
        counts = len(bpy.data.materials), len(bpy.data.images)
        for count in (0, 4, 63, 64, 831):
            palette = self.folder / f'bad-{count}.cmp'
            palette.write_bytes(cmp_bytes()[:count])
            with self.subTest(count=count):
                label = 'header' if count < 64 else 'palette'
                self.assert_controlled_error(palette, 'Truncated CMP ' + label)
                self.assertEqual([node.as_pointer() for node in material.node_tree.nodes], nodes)
                self.assertEqual(material[kMatCelImagePrefix + '0'], image)
                self.assertEqual(list(image.pixels), pixels)
                self.assertEqual((len(bpy.data.materials), len(bpy.data.images)), counts)

    def test_registered_operator_reports_short_header_without_python_traceback(self):
        palette = self.folder / 'short.cmp'
        palette.write_bytes(cmp_bytes()[:4])
        with self.assertRaisesRegex(RuntimeError, 'Cannot import MAT: Truncated CMP header') as result:
            bpy.ops.import_material.sith_mat(filepath=str(self.source), cmp_file=str(palette))
        self.assertNotIn('Traceback', str(result.exception))
        self.assertNotIn(self.source.name, bpy.data.materials)

    def test_registered_failures_preserve_existing_and_shared_image_data(self):
        self.assertEqual(bpy.ops.import_material.sith_mat(filepath=str(self.source)), {'FINISHED'})
        material = bpy.data.materials[self.source.name]
        image = material[kMatCelImagePrefix + '0']
        shared = bpy.data.materials.new('shared')
        shared.use_nodes = True
        node = shared.node_tree.nodes.new('ShaderNodeTexImage')
        node.image = image
        pixels = list(image.pixels)
        nodes = [item.as_pointer() for item in material.node_tree.nodes]
        counts = len(bpy.data.materials), len(bpy.data.images)
        for version in (0x14, 0x1e):
            for count in (0, 1, 4, 63, 64, 831):
                path = self.folder / f'bad-{version}-{count}.cmp'
                path.write_bytes(cmp_bytes(version)[:count])
                label = 'header' if count < 64 else 'palette'
                with self.subTest(version=version, count=count):
                    with self.assertRaisesRegex(RuntimeError, 'Cannot import MAT: Truncated CMP ' + label) as result:
                        bpy.ops.import_material.sith_mat(filepath=str(self.source), cmp_file=str(path))
                    self.assertNotIn('Traceback', str(result.exception))
                    self.assertEqual([item.as_pointer() for item in material.node_tree.nodes], nodes)
                    self.assertEqual(material[kMatCelImagePrefix + '0'], image)
                    self.assertEqual(node.image, image)
                    self.assertEqual(list(image.pixels), pixels)
                    self.assertEqual((len(bpy.data.materials), len(bpy.data.images)), counts)

    def test_default_palette_uses_the_same_controlled_error_path(self):
        (self.folder / 'dflt.cmp').write_bytes(cmp_bytes()[:63])
        with contextlib.chdir(self.folder):
            self.assert_controlled_error('', 'Truncated CMP header')
        self.assertFalse(bpy.data.materials)

    def test_complete_valid_and_invalid_headers_keep_their_existing_behavior(self):
        invalid = self.folder / 'invalid.cmp'
        invalid.write_bytes(b'BAD ' + cmp_bytes()[4:])
        self.assert_controlled_error(invalid, 'Invalid CMP file')
        valid = self.folder / 'valid.cmp'
        valid.write_bytes(cmp_bytes())
        self.assertEqual(bpy.ops.import_material.sith_mat(filepath=str(self.source), cmp_file=str(valid)), {'FINISHED'})
