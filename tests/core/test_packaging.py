"""Portable extension packaging must not alter sources or old output on failure."""
import importlib.util
import os
from pathlib import Path, PureWindowsPath
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/make_addon.py'
spec = importlib.util.spec_from_file_location('sith_packager_test', SCRIPT)
packager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packager)


def python_executable():
    # In Blender sys.executable is the application, not a Python CLI. Its
    # distribution also ships a standalone interpreter below sys.prefix/bin.
    if Path(sys.executable).name.lower().startswith('python'):
        return sys.executable
    for name in ('python.exe', f'python{sys.version_info.major}.{sys.version_info.minor}', 'python3'):
        candidate = Path(sys.prefix) / 'bin' / name
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError('Standalone Python executable was not found')


class PackagingTests(unittest.TestCase):
    def test_repository_manifest_tagline_fits_blender_limits(self):
        with (ROOT / 'sith/blender_manifest.toml').open('rb') as stream:
            manifest = tomllib.load(stream)
        self.assertEqual(manifest['id'], 'sith')
        self.assertTrue(0 < len(manifest['tagline']) <= 64)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sith package ')
        self.addCleanup(self.temp.cleanup)
        # The samefile mock must match the canonical paths used by the packager.
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'source with spaces'
        self.source.mkdir()
        (self.source / '__init__.py').write_text('# test extension\n')
        (self.source / 'blender_manifest.toml').write_text('id = "sith"\n')
        self.output = self.root / 'output with spaces/sith.zip'

    def test_layout_filters_and_sources_are_preserved(self):
        for name in ('nested/module.py', 'assets/sample.dat', '__pycache__/ignored.pyc', '.vs/state',
                     '.vscode/settings.json', '.pytest_cache/README.md', 'nested/.pytest_cache/cache.json',
                     'work.blend', 'work.BLEND1', '__test.py', '.directory'):
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'synthetic payload')
        before = {p.relative_to(self.source): p.read_bytes() for p in self.source.rglob('*') if p.is_file()}
        packager.create_package(self.source, self.output)
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(set(archive.namelist()), {'__init__.py', 'blender_manifest.toml',
                                                     'nested/module.py', 'assets/sample.dat'})
            self.assertIsNone(archive.testzip())
        self.assertEqual({p.relative_to(self.source): p.read_bytes() for p in self.source.rglob('*') if p.is_file()}, before)

    def test_missing_package_files_do_not_replace_previous_output(self):
        self.output.parent.mkdir()
        self.output.write_bytes(b'previous package')
        (self.source / 'blender_manifest.toml').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing regular package file'):
            packager.create_package(self.source, self.output)
        self.assertEqual(self.output.read_bytes(), b'previous package')

    def test_output_inside_source_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'outside'):
            packager.create_package(self.source, self.source / 'recursive.zip')
        self.assertFalse((self.source / 'recursive.zip').exists())

    def test_output_through_a_physical_source_alias_is_rejected(self):
        # Model a separate namespace/mount alias portably, without requiring
        # a Windows host, mount privileges or symbolic-link creation rights.
        def samefile(left, right):
            return left == self.output.parent and right == self.source

        with patch.object(packager.os.path, 'samefile', side_effect=samefile), \
             self.assertRaisesRegex(ValueError, 'outside'):
            packager.create_package(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_namespace_containment_does_not_merge_case_distinct_trees(self):
        root = PureWindowsPath(r'C:\Assets\Source')
        alias = PureWindowsPath(r'\\?\C:\Assets\Source\inside.zip')
        def samefile(left, right):
            return str(left).removeprefix('\\\\?\\') == str(right)

        with patch.object(packager.os.path, 'samefile', side_effect=samefile):
            self.assertTrue(packager._is_within_source(alias, root))
        with patch.object(packager.os.path, 'samefile', return_value=False):
            self.assertFalse(packager._is_within_source(PureWindowsPath(r'C:\Assets\source\outside.zip'), root))

    def test_mid_write_failure_keeps_old_output_and_cleans_temporary_files(self):
        self.output.parent.mkdir()
        self.output.write_bytes(b'previous package')
        with patch.object(packager.zipfile.ZipFile, 'write', side_effect=OSError('simulated write failure')):
            with self.assertRaisesRegex(OSError, 'simulated write failure'):
                packager.create_package(self.source, self.output)
        self.assertEqual(self.output.read_bytes(), b'previous package')
        self.assertEqual(list(self.output.parent.iterdir()), [self.output])

    def test_incomplete_source_scan_preserves_previous_package(self):
        self.output.parent.mkdir()
        self.output.write_bytes(b'previous package')

        def walk(path, *, onerror=None, **kwargs):
            yield str(path), ['unreadable'], ['__init__.py', 'blender_manifest.toml']
            if onerror is not None:
                onerror(PermissionError('Cannot enumerate required package modules'))

        # Model a scan that finds the manifest but cannot enumerate the rest.
        # It must fail before starting/replacing an apparently successful ZIP.
        with patch.object(packager.os, 'walk', side_effect=walk), \
             self.assertRaisesRegex(PermissionError, 'required package modules'):
            packager.create_package(self.source, self.output)
        self.assertEqual(self.output.read_bytes(), b'previous package')
        self.assertEqual(list(self.output.parent.iterdir()), [self.output])

    def test_cli_is_independent_of_working_directory(self):
        result = subprocess.run([python_executable(), '-B', str(SCRIPT), '--output', str(self.output)],
                                cwd=self.root, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with zipfile.ZipFile(self.output) as archive:
            self.assertIn('blender_manifest.toml', archive.namelist())
            self.assertIn('app.py', archive.namelist())
            self.assertIn('key/keyUtils.py', archive.namelist())
            self.assertNotIn('sith/blender_manifest.toml', archive.namelist())
            self.assertFalse(any('.pytest_cache' in Path(name).parts for name in archive.namelist()))

    @unittest.skipUnless(os.name == 'posix' and shutil.which('bash'), 'Bash wrapper requires a POSIX shell')
    def test_shell_wrapper_handles_paths_with_spaces(self):
        # Reproduce a checkout/script path with spaces, not only an output name.
        scripts = self.root / 'checkout with spaces/scripts'
        scripts.mkdir(parents=True)
        shutil.copyfile(ROOT / 'scripts/make_addon.sh', scripts / 'make_addon.sh')
        shutil.copyfile(SCRIPT, scripts / 'make_addon.py')
        shutil.copytree(self.source, scripts.parent / 'sith')
        environment = dict(os.environ, PYTHON=python_executable())
        result = subprocess.run(['bash', str(scripts / 'make_addon.sh'), '--output', str(self.output)],
                                cwd=self.root, env=environment, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(self.output.is_file())
