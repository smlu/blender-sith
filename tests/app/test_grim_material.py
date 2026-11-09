"""Real Grim MAT image creation and resource lookup during model import."""
import contextlib
from pathlib import Path
import tempfile

import bpy

from app.support import SceneTestCase
from fixtures import cmp_bytes
from grim_fixtures import binary_3do_bytes, grim_mat_bytes
from sith.material import ColorMap, importMat
from sith.material.mat import kMatCelImagePrefix
from sith.model.model3doBinary import encodeBinary3do, readBinary3do
from sith.model.model3doImporter import import3do
from sith.utils import getCmpFileOrDefault, getGlobalMaterial


class GrimMaterialImportTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.working = self.folder / 'working'
        self.working.mkdir()

    def make_model(self, path):
        data, _ = binary_3do_bytes()
        model = readBinary3do(data)
        model.materials = ['paint.mat']
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encodeBinary3do(model))

    def assert_loaded_texture(self, index=70):
        material = bpy.data.materials['paint.mat']
        image = material[kMatCelImagePrefix + '0']
        self.assertEqual(tuple(image.size), (2, 2))
        self.assertIsNotNone(image.packed_file)
        self.assert_vector(image.pixels[:4], (index / 255, (255 - index) / 255, (index // 2) / 255, 1))

    def test_full_and_compact_materials_create_packed_images_for_all_cels(self):
        palette_path = self.folder / 'palette.cmp'
        palette_path.write_bytes(cmp_bytes())
        palette = ColorMap.load(palette_path)
        path = self.folder / 'paint.mat'
        for tag in (0, 8):
            with self.subTest(tag=tag):
                self.clear_data()
                cels = [(2, 2, [bytes((0, 17, 70, 255))], True), (1, 1, [b'\x11'], False)]
                path.write_bytes(grim_mat_bytes(tag=tag, cels=cels))
                material = importMat(path, palette)
                self.assert_loaded_texture()
                self.assertIsNotNone(material[kMatCelImagePrefix + '1'].packed_file)
                self.assert_vector(material[kMatCelImagePrefix + '1'].pixels[:], (17 / 255, 238 / 255, 8 / 255, 1))
                bsdf = next(node for node in material.node_tree.nodes if node.type == 'BSDF_PRINCIPLED')
                self.assertTrue(bsdf.inputs['Alpha'].is_linked)

    def test_invalid_compact_material_does_not_replace_existing_blender_data(self):
        path = self.folder / 'paint.mat'
        path.write_bytes(grim_mat_bytes())
        material = importMat(path)
        image = material[kMatCelImagePrefix + '0']
        path.write_bytes(grim_mat_bytes(tag=0)[:-1])
        with self.assertRaises(ImportError):
            importMat(path)
        self.assertEqual(material[kMatCelImagePrefix + '0'], image)
        self.assertEqual(tuple(image.size), (2, 2))

    def test_binary_import_loads_mat_and_grim_default_cmp_beside_model(self):
        source = self.folder / 'hero.3do'
        self.make_model(source)
        (self.folder / 'paint.mat').write_bytes(grim_mat_bytes())
        (self.folder / 'dfltcmp.cmp').write_bytes(cmp_bytes())
        with contextlib.chdir(self.working):
            import3do(source, clearScene=False)
        self.assert_loaded_texture()

    def test_model_filename_in_current_working_directory_is_a_valid_search_root(self):
        source = self.folder / 'hero.3do'
        self.make_model(source)
        (self.folder / 'paint.mat').write_bytes(grim_mat_bytes(tag=0))
        (self.folder / 'dflt.cmp').write_bytes(cmp_bytes())
        with contextlib.chdir(self.folder):
            import3do('hero.3do', clearScene=False)
        self.assert_loaded_texture()

    def test_relative_and_absolute_roots_search_direct_mat_and_nested_layouts(self):
        source = self.folder / 'models/hero.3do'
        self.make_model(source)
        for absolute in (False, True):
            for layout in ('', 'MAT', '3DO/MAT'):
                with self.subTest(absolute=absolute, layout=layout):
                    self.clear_data()
                    root = self.folder / ('resources_' + str(absolute) + '_' + layout.replace('/', '_'))
                    materials = root / layout
                    materials.mkdir(parents=True)
                    (materials / 'PaInT.MaT').write_bytes(grim_mat_bytes())
                    palettes = root / 'MISC/CMP'
                    palettes.mkdir(parents=True)
                    (palettes / 'DFLTCMP.CMP').write_bytes(cmp_bytes())
                    supplied = root if absolute else Path('..') / root.name
                    with contextlib.chdir(self.working):
                        import3do(source, mat_dirs=[supplied], clearScene=False)
                    # Case-insensitive filesystems can retain the requested
                    # spelling; case-sensitive ones return the disk spelling.
                    material = getGlobalMaterial('paint.mat')
                    self.assertIsNotNone(material)
                    image = material[kMatCelImagePrefix + '0']
                    self.assertIsNotNone(image.packed_file)
                    self.assert_vector(image.pixels[:4], (70 / 255, 185 / 255, 35 / 255, 1))

    def test_palette_next_to_explicit_mat_directory_uses_parent_layout(self):
        source = self.folder / 'models/hero.3do'
        self.make_model(source)
        root = self.folder / 'resources'
        materials = root / 'mat'
        materials.mkdir(parents=True)
        (materials / 'paint.mat').write_bytes(grim_mat_bytes())
        palettes = root / 'misc/cmap'
        palettes.mkdir(parents=True)
        (palettes / 'chosen.cmp').write_bytes(cmp_bytes())
        with contextlib.chdir(self.working):
            import3do(source, mat_dirs=[materials], cmp_file='chosen.cmp', clearScene=False)
        self.assert_loaded_texture()

    def test_model_local_nested_mat_layout_is_also_searched(self):
        source = self.folder / 'hero.3do'
        self.make_model(source)
        materials = self.folder / '3do/mat'
        materials.mkdir(parents=True)
        (materials / 'paint.mat').write_bytes(grim_mat_bytes())
        (self.folder / 'dflt.cmp').write_bytes(cmp_bytes())
        with contextlib.chdir(self.working):
            import3do(source, clearScene=False)
        self.assert_loaded_texture()

    def test_model_filename_still_searches_parent_material_and_palette_folders(self):
        source = self.folder / 'models/hero.3do'
        self.make_model(source)
        materials = self.folder / 'mat'
        materials.mkdir()
        (materials / 'paint.mat').write_bytes(grim_mat_bytes())
        palettes = self.folder / 'misc/cmp'
        palettes.mkdir(parents=True)
        (palettes / 'dflt.cmp').write_bytes(cmp_bytes())
        with contextlib.chdir(source.parent):
            import3do('hero.3do', clearScene=False)
        self.assert_loaded_texture()

    def test_default_palette_priority_and_explicit_missing_names_do_not_guess(self):
        source = self.folder / 'hero.3do'
        grim = self.folder / 'dfltcmp.cmp'
        grim.write_bytes(cmp_bytes())
        standard = self.folder / 'dflt.cmp'
        data = bytearray(cmp_bytes())
        data[64:67] = b'\x01\x02\x03'
        standard.write_bytes(data)
        with contextlib.chdir(self.working):
            self.assertEqual(tuple(getCmpFileOrDefault('', source).palette[0]), (1, 2, 3))
            self.assertIsNone(getCmpFileOrDefault('missing.cmp', source))
            standard.unlink()
            self.assertEqual(tuple(getCmpFileOrDefault('', source).palette[0]), (0, 255, 0))
