"""Resource lookup follows asset-volume spelling, not the host home volume."""
import contextlib
import io
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sith import utils
from sith.model import utils as model_utils


class _CaseSensitiveFiles:
    """Small case-sensitive volume, including on Windows CI's native NTFS."""
    def __init__(self):
        self.root = Path(os.path.abspath('audit_volume'))
        self.directories = set()
        self.files = set()
        self.unreadable = set()
        self.blocked = set()
        self.scans = []
        self.directory(self.root)

    def key(self, path):
        return os.path.normpath(os.path.abspath(os.fspath(path)))

    def directory(self, path):
        path = Path(path)
        for parent in (path, *path.parents):
            self.directories.add(self.key(parent))

    def file(self, name):
        path = self.root / name
        self.directory(path.parent)
        self.files.add(self.key(path))
        return path

    @contextlib.contextmanager
    def scandir(self, path):
        key = self.key(path)
        self.scans.append(key)
        if key in self.blocked:
            raise PermissionError(key)
        if key not in self.directories:
            raise FileNotFoundError(key)
        children = sorted(value for value in self.files | self.directories
                          if value != key and self.key(Path(value).parent) == key)
        yield iter(SimpleNamespace(name=Path(value).name, path=str(Path(path) / Path(value).name))
                   for value in children)

    @contextlib.contextmanager
    def mounted(self):
        with patch.object(utils.os.path, 'isdir', side_effect=lambda value: self.key(value) in self.directories), \
             patch.object(utils.os.path, 'isfile', side_effect=lambda value: self.key(value) in self.files), \
             patch.object(Path, 'is_file', autospec=True, side_effect=lambda value: self.key(value) in self.files), \
             patch.object(utils.os, 'access', side_effect=lambda value, mode: self.key(value) not in self.unreadable), \
             patch.object(utils.os, 'scandir', side_effect=self.scandir):
            yield


class ResourceLookupTests(unittest.TestCase):
    def setUp(self):
        self.volume = _CaseSensitiveFiles()

    def find(self, name, directory=None, insensitive=True):
        directory = self.volume.root if directory is None else directory
        with self.volume.mounted():
            return utils.getFilePathInDir(name, directory, insensitive)

    def test_exact_readable_match_needs_no_directory_scan(self):
        expected = self.volume.file('MiXeD.mat')
        self.assertEqual(self.find('MiXeD.mat'), str(expected))
        self.assertEqual(self.volume.scans, [])

    def test_case_insensitive_filename_does_not_depend_on_home_volume(self):
        expected = self.volume.file('MiXeD.mat')
        with patch.object(Path, 'home', side_effect=AssertionError('Do not infer asset-volume rules from home')):
            self.assertEqual(self.find('mixed.mat'), str(expected))
            self.assertEqual(self.find('MIXED.MAT'), str(expected))

    def test_mixed_directory_and_nested_filename_components(self):
        expected = self.volume.file('MAT/SubFolder/Paint.MAT')
        self.assertEqual(self.find('subfolder/paint.mat', self.volume.root / 'mat'), str(expected))
        self.assertEqual(self.find('paint.mat', self.volume.root / 'mat/subfolder'), str(expected))

    def test_explicit_case_sensitive_lookup_has_no_fallback(self):
        expected = self.volume.file('MiXeD.mat')
        self.assertIsNone(self.find('mixed.mat', insensitive=False))
        self.assertEqual(self.find('MiXeD.mat', insensitive=False), str(expected))
        self.assertEqual(self.volume.scans, [])

    def test_exact_spelling_wins_among_case_variants(self):
        first = self.volume.file('Paint.mat')
        second = self.volume.file('paint.MAT')
        self.assertEqual(self.find('Paint.mat'), str(first))
        self.assertEqual(self.find('paint.MAT'), str(second))
        with self.assertRaisesRegex(ValueError, 'Ambiguous resource path'):
            self.find('PAINT.mat')

    def test_ambiguous_directory_requires_exact_spelling(self):
        expected = self.volume.file('MAT/Paint.mat')
        self.volume.file('mat/Paint.mat')
        self.assertEqual(self.find('Paint.mat', self.volume.root / 'MAT'), str(expected))
        with self.assertRaisesRegex(ValueError, 'Ambiguous resource path'):
            self.find('Paint.mat', self.volume.root / 'Mat')

    def test_missing_unreadable_and_directory_results_are_not_files(self):
        unreadable = self.volume.file('Blocked.mat')
        self.volume.unreadable.add(self.volume.key(unreadable))
        self.volume.directory(self.volume.root / 'Folder.mat')
        for name in ('missing.mat', 'blocked.mat', 'Blocked.mat', 'folder.mat', '', '.'):
            with self.subTest(name=name):
                self.assertIsNone(self.find(name))
        self.assertIsNone(self.find('missing.mat', self.volume.root / 'missing'))
        self.assertIsNone(self.find('missing.mat', ''))

    def test_file_directory_and_unreadable_collisions_filter_by_kind(self):
        expected = self.volume.file('Paint.mat')
        self.volume.directory(self.volume.root / 'PAINT.MAT')
        blocked = self.volume.file('paint.MAT')
        self.volume.unreadable.add(self.volume.key(blocked))
        self.assertEqual(self.find('paint.mat'), str(expected))

    def test_inaccessible_or_disappearing_search_directory_returns_none(self):
        self.volume.blocked.add(self.volume.key(self.volume.root))
        self.assertIsNone(self.find('missing.mat'))
        with self.volume.mounted(), patch.object(utils.os, 'scandir', side_effect=FileNotFoundError):
            self.assertIsNone(utils.getFilePathInDir('missing.mat', self.volume.root))

    def test_relative_paths_parent_components_and_absolute_filename(self):
        expected = self.volume.file('Paint.mat')
        self.volume.directory(self.volume.root / 'Child')
        relative = os.path.relpath(self.volume.root)
        self.assertEqual(self.find('paint.mat', relative), os.path.join(relative, 'Paint.mat'))
        self.assertEqual(self.find('../paint.mat', self.volume.root / 'Child'),
                         str(self.volume.root / 'Child/../Paint.mat'))
        self.assertEqual(self.find(str(expected)), str(expected))

    def test_palette_search_order_and_mixed_case_subdirectories(self):
        source = self.volume.root / 'Game/Models/Hero.3do'
        self.volume.directory(source.parent)
        locations = ('Game/Models/DFLT.CMP', 'Game/Models/MISC/CMP/DFLT.CMP',
                     'Game/DFLT.CMP', 'Game/Misc/Cmp/DFLT.CMP', 'MISC/CMP/DFLT.CMP')
        for location in locations:
            self.volume.file(location)
        # Each removal exposes the next candidate, preserving the original order.
        for location in locations:
            expected = self.volume.root / location
            with self.volume.mounted():
                found = utils.findCmpFileInPath('dflt.cmp', source)
            self.assertEqual(found, expected)
            self.volume.files.remove(self.volume.key(expected))

    def test_palette_lookup_uses_same_resolver_for_explicit_and_default_paths(self):
        expected = self.volume.file('Misc/CMP/DFLT.CMP')
        source = self.volume.root / 'Models/Hero.3do'
        self.volume.directory(source.parent)
        for request in ('', 'dflt.cmp', self.volume.root / 'misc/cmp/dflt.cmp'):
            with self.subTest(request=request), self.volume.mounted(), \
                 patch.object(utils.ColorMap, 'load', return_value='palette') as load:
                self.assertEqual(utils.getCmpFileOrDefault(request, source), 'palette')
                self.assertEqual(Path(load.call_args.args[0]), expected)

        current = self.volume.file(Path.cwd() / 'DFLT.CMP')
        for request in ('', 'dflt.cmp'):
            with self.subTest(current_directory=request), self.volume.mounted(), \
                 patch.object(utils.ColorMap, 'load', return_value='current') as load:
                self.assertEqual(utils.getCmpFileOrDefault(request, source), 'current')
                self.assertEqual(self.volume.key(load.call_args.args[0]), self.volume.key(current))
        with self.volume.mounted(), patch.object(utils.ColorMap, 'load') as load:
            self.assertIsNone(utils.findCmpFileInPath('', source))
            self.assertIsNone(utils.findCmpFileInPath(Path('.'), source))
            self.assertIsNone(utils.getCmpFileOrDefault(Path('.'), source))
            load.assert_not_called()

    def test_ambiguous_optional_material_warns_and_keeps_searching(self):
        for fallback in (False, True):
            results = [ValueError('Ambiguous resource path'), 'resolved.mat' if fallback else None]
            messages = io.StringIO()
            with self.subTest(fallback=fallback), contextlib.redirect_stdout(messages), \
                 patch.object(model_utils, 'getFilePathInDir', side_effect=results) as lookup, \
                 patch.object(model_utils, 'importMat') as load:
                model_utils.importMaterials(['case_lookup_sentinel.mat'], ['first', 'second'], None)
                self.assertEqual(lookup.call_count, 2)
                self.assertIn('Ambiguous resource path', messages.getvalue())
                if fallback:
                    load.assert_called_once_with('resolved.mat', None)
                else:
                    load.assert_not_called()

    def test_modeled_volume_is_independent_of_real_current_directory_files(self):
        expected = self.volume.file('Misc/CMP/DFLT.CMP')
        source = self.volume.root / 'Models/Hero.3do'
        self.volume.directory(source.parent)
        with tempfile.TemporaryDirectory() as folder, contextlib.chdir(folder):
            Path('dflt.cmp').write_bytes(b'Not part of the modeled filesystem')
            with self.volume.mounted(), patch.object(utils.ColorMap, 'load', return_value='modeled') as load:
                self.assertEqual(utils.getCmpFileOrDefault('', source), 'modeled')
                self.assertEqual(Path(load.call_args.args[0]), expected)

    def test_material_roots_include_direct_and_nested_layouts(self):
        source = self.volume.root / 'Game/Models/Hero.3do'
        extra = self.volume.root / 'Game/Assets'
        self.volume.directory(source.parent)
        for supplied in (extra, Path('../Assets')):
            folders = utils.getDefaultMatFolders(source, [supplied])
            expected = [source.parent, source.parent / 'mat', source.parent.parent / 'mat',
                        source.parent / '3do/mat', extra, extra / 'mat', extra / '3do/mat']
            self.assertEqual([self.volume.key(folder) for folder in folders],
                             [self.volume.key(folder) for folder in expected])

    def test_material_root_case_fallback_covers_all_supplied_layouts(self):
        source = self.volume.root / 'Game/Models/Hero.3do'
        self.volume.directory(source.parent)
        for layout in ('', 'MAT', '3DO/MAT'):
            expected = self.volume.file('Game/Assets/' + (layout + '/' if layout else '') + 'Paint.MAT')
            with self.volume.mounted(), patch.object(model_utils, 'importMat') as load:
                model_utils.importMaterials(['paint.mat'], utils.getDefaultMatFolders(source, ['../assets']), None)
                self.assertEqual(self.volume.key(load.call_args.args[0]), self.volume.key(expected))
            self.volume.files.remove(self.volume.key(expected))

    def test_palette_supplied_roots_resolve_relative_and_absolute_paths(self):
        source = self.volume.root / 'Game/Models/Hero.3do'
        self.volume.directory(source.parent)
        expected = self.volume.file('Game/Assets/MISC/CMAP/Chosen.CMP')
        for supplied in (self.volume.root / 'Game/Assets', Path('../assets')):
            with self.subTest(supplied=supplied), self.volume.mounted(), \
                 patch.object(utils.ColorMap, 'load', return_value='palette') as load:
                self.assertEqual(utils.getCmpFileOrDefault('chosen.cmp', source, searchPaths=[supplied]), 'palette')
                self.assertEqual(self.volume.key(load.call_args.args[0]), self.volume.key(expected))
