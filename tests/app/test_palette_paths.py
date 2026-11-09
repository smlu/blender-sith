"""Palette helpers accept filesystem paths without losing indexed MAT decoding."""
import contextlib
from pathlib import Path
import tempfile
from unittest.mock import patch

import bpy

from app.support import SceneTestCase
from fixtures import TV, INDEX8, cmp_bytes, mat_bytes
from sith.material.mat import kMatCelImagePrefix
from sith.model.model3doImporter import import3do
from sith.model.model3doLoader import load3do, Model3doFileVersion
from sith.model.model3doWriter import save3do
from sith.utils import findCmpFileInPath, getCmpFileOrDefault, getGlobalMaterial


class PalettePathTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.working = self.folder / 'cwd'
        self.working.mkdir()
        self.palette = self.folder / 'synthetic_palette.cmp'
        self.palette.write_bytes(cmp_bytes())
        self.source = self.folder / 'model.3do'

    def assert_palette(self, palette, source):
        result = getCmpFileOrDefault(palette, source)
        self.assertIsNotNone(result)
        self.assertEqual(tuple(result.palette[17]), (17, 238, 8))

    def test_absolute_palette_names_accept_strings_and_paths(self):
        for palette in (str(self.palette), self.palette):
            for source in (str(self.source), self.source):
                with self.subTest(palette_type=type(palette).__name__, source_type=type(source).__name__):
                    self.assert_palette(palette, source)

    def test_relative_palette_paths_search_beside_the_model(self):
        with contextlib.chdir(self.working):
            for palette in (self.palette.name, Path(self.palette.name)):
                for source in (str(self.source), self.source):
                    with self.subTest(palette_type=type(palette).__name__, source_type=type(source).__name__):
                        self.assert_palette(palette, source)

    def test_empty_string_still_searches_for_the_default_palette(self):
        (self.folder / 'dflt.cmp').write_bytes(cmp_bytes())
        with contextlib.chdir(self.working):
            self.assert_palette('', self.source)

    def test_missing_palette_returns_none_for_both_path_types(self):
        missing = self.folder / 'not_present.cmp'
        for value in (str(missing), missing):
            with self.subTest(path_type=type(value).__name__):
                self.assertIsNone(getCmpFileOrDefault(value, self.source))

    def test_invalid_palette_reports_the_decode_error_for_both_path_types(self):
        invalid = self.folder / 'invalid.cmp'
        invalid.write_bytes(b'BAD ' + cmp_bytes()[4:])
        for value in (str(invalid), invalid):
            with self.subTest(path_type=type(value).__name__):
                with self.assertRaisesRegex(ImportError, 'Invalid CMP file'):
                    getCmpFileOrDefault(value, self.source)

    def test_unreadable_exact_palette_does_not_silently_fall_back(self):
        with patch('sith.utils.os.access', return_value=False), \
             patch('sith.utils.ColorMap.load', side_effect=PermissionError('palette is unreadable')) as load:
            with self.assertRaisesRegex(PermissionError, 'palette is unreadable'):
                getCmpFileOrDefault(self.palette, self.source)
            load.assert_called_once_with(self.palette)
            self.assertEqual(findCmpFileInPath(self.palette.name, self.source), self.palette)

    def test_standard_fspath_protocol_is_supported(self):
        palette = self.palette

        class PalettePath:
            def __fspath__(self):
                return str(palette)

        self.assert_palette(PalettePath(), self.source)

    def test_indexed_model_import_decodes_pixels_with_a_palette_path(self):
        model, _ = load3do(TV / 'model' / 'triangle.3do')
        model.materials = ['paint.mat']
        save3do(model, self.source, Model3doFileVersion.Version2_1, '')
        (self.folder / 'paint.mat').write_bytes(mat_bytes(INDEX8, [(2, 2, [b'\x11' * 4], False, 0)]))
        for palette in (str(self.palette), self.palette):
            with self.subTest(palette_type=type(palette).__name__):
                self.clear_data()
                import3do(self.source, cmp_file=palette, clearScene=False)
                image = bpy.data.materials['paint.mat'][kMatCelImagePrefix + '0']
                self.assertIsNotNone(image.packed_file)
                self.assert_vector(image.pixels[:4], (17 / 255, 238 / 255, 8 / 255, 1))

    def test_default_palette_searches_every_folder_with_mixed_case_names(self):
        locations = ('Game/Models/DFLT.CMP', 'Game/Models/MISC/CMP/DFLT.CMP',
                     'Game/DFLT.CMP', 'Game/MISC/CMP/DFLT.CMP', 'MISC/CMP/DFLT.CMP')
        with contextlib.chdir(self.working):
            for index, location in enumerate(locations):
                base = self.folder / str(index)
                source = base / 'Game/Models/Hero.3do'
                source.parent.mkdir(parents=True)
                palette = base / location
                palette.parent.mkdir(parents=True, exist_ok=True)
                palette.write_bytes(cmp_bytes())
                with self.subTest(location=location):
                    self.assert_palette('', source)

    def test_explicit_palette_resolves_mixed_case_directory_components(self):
        palette = self.folder / 'Palettes/Alternate.CMP'
        palette.parent.mkdir()
        palette.write_bytes(cmp_bytes())
        with contextlib.chdir(self.working):
            self.assert_palette(self.folder / 'palettes/alternate.cmp', self.source)
            self.assert_palette('palettes/alternate.cmp', self.source)

    def test_mixed_case_mat_folder_and_default_palette_decode_model_pixels(self):
        source = self.folder / 'Models/Hero.3do'
        source.parent.mkdir()
        model, _ = load3do(TV / 'model/triangle.3do')
        model.materials = ['paint.mat']
        save3do(model, source, Model3doFileVersion.Version2_1, '')
        materials = self.folder / 'MAT'
        materials.mkdir()
        (materials / 'PaInT.MaT').write_bytes(mat_bytes(INDEX8, [(2, 2, [b'\x11' * 4], False, 0)]))
        palettes = self.folder / 'MISC/CMP'
        palettes.mkdir(parents=True)
        (palettes / 'DFLT.CMP').write_bytes(cmp_bytes())
        with contextlib.chdir(self.working):
            import3do(source, clearScene=False)
        material = getGlobalMaterial('paint.mat')
        image = material[kMatCelImagePrefix + '0']
        self.assertIsNotNone(image.packed_file)
        self.assert_vector(image.pixels[:4], (17 / 255, 238 / 255, 8 / 255, 1))
