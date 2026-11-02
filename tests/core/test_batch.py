import contextlib
import copy
import io
import json
from pathlib import Path, PureWindowsPath
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import batch.common as common
from batch.common import (UnsupportedResource, differences, discover, key_snapshot,
                          model_snapshot, run, validate_paths)
from batch.core import check, read_material
from fixtures import TV, cmp_bytes, mat_bytes, packed_mat_cels, RGB565, RGBA4444, RGBA1555
from sith.key.keyLoader import loadKey
from sith.model.model3doLoader import load3do


class BatchTests(unittest.TestCase):
    def test_packed_mat_references_cover_all_cels_and_mip_levels(self):
        with tempfile.TemporaryDirectory() as directory:
            for name, fmt in (('rgb565', RGB565), ('rgba4444', RGBA4444), ('rgba1555', RGBA1555)):
                path = Path(directory) / (name + '.mat')
                path.write_bytes(mat_bytes(fmt, packed_mat_cels()))
                with self.subTest(format=name):
                    _, cels = read_material(path, None)
                    self.assertEqual(len(cels), 2)
                    self.assertEqual([len(cel[2]) for cel in cels], [3, 2])
                    self.assertEqual(list(cels[0][2][-1]), [1, 1, 1, 1])

    def test_packed_mat_batch_run_is_passing_and_preserves_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root, output = Path(directory) / 'assets', Path(directory) / 'report'
            root.mkdir()
            for name, fmt in (('rgb565', RGB565), ('rgba4444', RGBA4444), ('rgba1555', RGBA1555)):
                (root / (name + '.mat')).write_bytes(mat_bytes(fmt, packed_mat_cels()))
            before = {path.name: path.read_bytes() for path in root.iterdir()}
            options = SimpleNamespace(assets=[root], output=output, title='packed', formats=['mat'],
                                      match='*', limit=0, cmp=None, keep_exports=False)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run(options, check), 0)
            self.assertEqual(json.loads((output / 'summary.json').read_text())['counts'], {'pass': 3})
            self.assertEqual({path.name: path.read_bytes() for path in root.iterdir()}, before)

    def test_differences_detect_fields_lengths_and_nonfinite_numbers(self):
        self.assertEqual(differences({'x': [1.0]}, {'x': [1.0 + 1e-8]}), [])
        for left, right in (([1], []), ({'a': 1}, {'b': 1}), (float('nan'), float('nan')), (2, 3)):
            with self.subTest(left=left):
                self.assertTrue(differences(left, right))
        self.assertEqual(len(differences(list(range(100)), [-1] * 100)), 20)

    def test_snapshots_include_mesh_attributes_and_animation_deltas(self):
        model, _ = load3do(TV / 'model' / 'triangle.3do')
        other = copy.deepcopy(model)
        other.geosets[0].meshes[0].faces[0].textureMode = 0
        self.assertTrue(differences(model_snapshot(model), model_snapshot(other)))
        key = loadKey(TV / 'key' / 'fractional.key')
        other = copy.deepcopy(key)
        other.nodes[0].keyframes[0].deltaRotation = (0, 0, 123)
        self.assertTrue(differences(key_snapshot(key), key_snapshot(other)))

    def test_input_and_output_trees_must_not_overlap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'assets'
            root.mkdir()
            for output in (root, root / 'exports', root.parent):
                with self.subTest(output=output), self.assertRaises(ValueError):
                    validate_paths([root], output)
            with self.assertRaises(ValueError):
                validate_paths([root / 'missing'], Path(directory) / 'reports')

    def test_discovery_is_case_insensitive_and_deduplicates_overlapping_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child = root / 'sub'
            child.mkdir()
            (child / 'EXAMPLE.KEY').write_text('')
            (root / 'ignored.wav').write_text('')
            files = discover([root, child], ['key'], '*example*')
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0][1].as_posix(), 'sub/EXAMPLE.KEY')

    def test_internal_symlink_keeps_following_siblings_in_the_walk_directory(self):
        from pathlib import PurePosixPath
        root_name = '/corpus'
        target_name = root_name + '/inner/target.mat'
        regular_name = root_name + '/b_regular.mat'
        link_name = root_name + '/a_link.mat'
        for duplicate in (False, True):
            existing = {link_name, regular_name, target_name}
            if duplicate:
                existing.add(root_name + '/inner/b_regular.mat')

            class ResourcePath(PurePosixPath):
                def resolve(self): return ResourcePath(target_name) if str(self) == link_name else self
                def is_file(self): return str(self) in existing
                def stat(self): return SimpleNamespace(st_dev=7, st_ino=1 if str(self) == root_name else 2)

            root = ResourcePath(root_name)
            walk = [(root_name, ['inner'], ['b_regular.mat', 'a_link.mat']),
                    (root_name + '/inner', [], ['target.mat'] + (['b_regular.mat'] if duplicate else []))]
            for pattern in ('*', 'b_regular.mat'):
                with self.subTest(duplicate=duplicate, pattern=pattern), \
                     patch.object(common, 'Path', ResourcePath), \
                     patch.object(common.os, 'walk', return_value=walk):
                    rows = discover([root], ('mat',), pattern)
                    # Resolving an earlier alias must neither omit this sibling
                    # nor substitute a same-named resource in the target folder.
                    siblings = [str(path) for _, relative, path in rows if str(relative) == 'b_regular.mat']
                    self.assertEqual(siblings, [regular_name])
                    expected = {regular_name}
                    if pattern == '*':
                        expected.add(target_name)
                        if duplicate:
                            expected.add(root_name + '/inner/b_regular.mat')
                    self.assertEqual({str(path) for _, _, path in rows}, expected)

    def test_full_batch_inventory_checks_siblings_after_an_internal_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            # Match the canonical paths used by run() before installing the alias mock.
            directory = Path(directory).resolve()
            root, output = directory / 'assets', directory / 'report'
            inner = root / 'inner'
            inner.mkdir(parents=True)
            alias, target, sibling = root / 'a_link.mat', inner / 'target.mat', root / 'b_regular.mat'
            alias.write_bytes(b'Simulated file alias')
            target.write_bytes(mat_bytes())
            sibling.write_bytes(mat_bytes(RGB565, packed_mat_cels()))
            before = {str(path): path.read_bytes() for path in (alias, target, sibling)}
            original_resolve = Path.resolve

            def resolve(path, *args, **kwargs):
                # Exercise a real batch run and real codec checks without
                # requiring Windows symbolic-link creation privileges.
                return original_resolve(target if path == alias else path, *args, **kwargs)

            options = SimpleNamespace(assets=[root], output=output, title='internal-alias', formats=['mat'],
                                      match='*', limit=0, cmp=None, keep_exports=False)
            with patch.object(Path, 'resolve', resolve), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run(options, check), 0)
            summary = json.loads((output / 'summary.json').read_text())
            records = [json.loads(line) for line in (output / 'results.jsonl').read_text().splitlines()]
            self.assertTrue(summary['full_corpus'])
            self.assertEqual(summary['inventory'], {'mat': 2})
            self.assertEqual(summary['processed'], 2)
            self.assertEqual(summary['counts'], {'pass': 2})
            self.assertEqual({row['source'] for row in records}, {str(target.resolve()), str(sibling.resolve())})
            self.assertEqual({str(path): path.read_bytes() for path in (alias, target, sibling)}, before)

    def test_filtered_batch_matches_before_deduplicating_file_aliases(self):
        # An alias sorted before its target must not hide that target from --match.
        for pattern, expected_name in (('*target*', 'z_target.mat'), ('*alias*', 'a_alias.mat')):
            for limit in (0, 1):
                with self.subTest(pattern=pattern, limit=limit), tempfile.TemporaryDirectory() as directory:
                    # Temporary paths may contain symlinks or Windows short names.
                    directory = Path(directory).resolve()
                    root, output = directory / 'assets', directory / 'report'
                    root.mkdir()
                    alias, target = root / 'a_alias.mat', root / 'z_target.mat'
                    alias.write_bytes(b'Simulated file alias')
                    target.write_bytes(mat_bytes())
                    before = {str(path): path.read_bytes() for path in (alias, target)}
                    original_resolve = Path.resolve

                    def resolve(path, *args, **kwargs):
                        return original_resolve(target if path == alias else path, *args, **kwargs)

                    options = SimpleNamespace(assets=[root], output=output, title='filtered-alias',
                                              formats=['mat'], match=pattern, limit=limit,
                                              cmp=None, keep_exports=False)
                    with patch.object(Path, 'resolve', resolve), contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(run(options, check), 0)
                    summary = json.loads((output / 'summary.json').read_text())
                    records = [json.loads(line) for line in (output / 'results.jsonl').read_text().splitlines()]
                    self.assertEqual(summary['counts'], {'pass': 1})
                    self.assertEqual(summary['inventory'], {'mat': 1})
                    self.assertFalse(summary['full_corpus'])
                    self.assertEqual([row['relative'] for row in records], [expected_name])
                    self.assertEqual([row['source'] for row in records], [str(target.resolve())])
                    self.assertEqual({str(path): path.read_bytes() for path in (alias, target)}, before)

    def test_incomplete_discovery_aborts_before_replacing_reports(self):
        # os.walk normally suppresses these errors. Never call an incomplete
        # inventory a full corpus or overwrite a previously completed report.
        for error_type in (PermissionError, FileNotFoundError):
            with self.subTest(error=error_type.__name__), tempfile.TemporaryDirectory() as directory:
                root, output = Path(directory) / 'assets', Path(directory) / 'report'
                root.mkdir()
                output.mkdir()
                (root / 'visible.key').write_bytes(b'Synthetic sentinel')
                before = {name: b'Previous report' for name in ('results.jsonl', 'summary.json')}
                for name, contents in before.items():
                    (output / name).write_bytes(contents)

                def walk(path, *, onerror=None, **kwargs):
                    yield str(path), ['unreadable'], ['visible.key']
                    if onerror is not None:
                        onerror(error_type('Cannot index the remaining resource directory'))

                options = SimpleNamespace(assets=[root], output=output, title='incomplete', formats=['key'],
                                          match='*', limit=0, cmp=None, keep_exports=False)
                handler = Mock(return_value={})
                with patch.object(common.os, 'walk', side_effect=walk), \
                     contextlib.redirect_stdout(io.StringIO()), self.assertRaises(error_type):
                    run(options, handler)
                handler.assert_not_called()
                self.assertEqual({name: (output / name).read_bytes() for name in before}, before)

    def test_resolved_windows_containment_keeps_case_distinct_siblings(self):
        root = PureWindowsPath(r'C:\Assets\CaseRoot')
        self.assertTrue(common._is_within_resolved(root / 'file.mat', root))
        self.assertTrue(common._is_within_resolved(root, root))
        with patch.object(common.os.path, 'samefile', return_value=False):
            self.assertFalse(common._is_within_resolved(PureWindowsPath(r'C:\Assets\caseroot\file.mat'), root))
            self.assertFalse(common._is_within_resolved(PureWindowsPath(r'C:\Assets\CaseRootExtra\file.mat'), root))

    def test_discovery_keeps_case_distinct_windows_files(self):
        class ResourcePath(PureWindowsPath):
            def resolve(self): return self
            def is_file(self): return True
            def is_symlink(self): return False
            def stat(self): return SimpleNamespace(st_dev=7, st_ino=11)

        root = ResourcePath(r'C:\Assets\CaseRoot')
        with patch.object(common, 'Path', ResourcePath), \
             patch.object(common.os, 'walk', return_value=[(str(root), [], ['case.mat', 'Case.mat'])]):
            rows = discover([root, root], ('mat',))
        # Both distinct names survive, but repeating the same root adds no rows.
        self.assertEqual([row[1].name for row in rows], ['Case.mat', 'case.mat'])
        self.assertEqual(len({str(row[2]) for row in rows}), 2)

    def test_discovery_rejects_a_case_distinct_sibling_symlink_target(self):
        class ResourcePath(PureWindowsPath):
            def resolve(self):
                return ResourcePath(r'C:\Assets\caseroot\outside.mat') if self.name == 'link.mat' else self
            def is_file(self): return True
            def is_symlink(self): return self.name == 'link.mat'

        root = ResourcePath(r'C:\Assets\CaseRoot')
        with patch.object(common, 'Path', ResourcePath), \
             patch.object(common.os, 'walk', return_value=[(str(root), [], ['link.mat'])]), \
             patch.object(common.os.path, 'samefile', return_value=False):
            self.assertEqual(discover([root], ('mat',)), [])

    def test_case_distinct_windows_output_is_not_mistaken_for_source_overlap(self):
        class ResourcePath(PureWindowsPath):
            def resolve(self): return self
            def is_dir(self): return True

        root, output = ResourcePath(r'C:\Assets\CaseRoot'), ResourcePath(r'C:\Assets\caseroot')
        with patch.object(common.os.path, 'samefile', return_value=False):
            self.assertEqual(validate_paths([root], output), ([root], output))
            for unsafe in (root, root / 'exports', root.parent):
                with self.subTest(output=str(unsafe)), self.assertRaises(ValueError):
                    validate_paths([root], unsafe)

    def test_extended_windows_namespace_cannot_bypass_source_overlap(self):
        class ResourcePath(PureWindowsPath):
            def resolve(self): return self
            def is_dir(self): return True

        root = ResourcePath(r'C:\Assets\CaseRoot')
        alias = ResourcePath(r'\\?\C:\Assets\CaseRoot\report')
        def samefile(left, right):
            return str(left).removeprefix('\\\\?\\') == str(right)
        with patch.object(common.os.path, 'samefile', side_effect=samefile):
            self.assertTrue(common._is_within_resolved(alias, root))
            with self.assertRaises(ValueError):
                validate_paths([root], alias)

    def test_discovery_deduplicates_namespace_aliases_but_keeps_leaf_spellings(self):
        class ResourcePath(PureWindowsPath):
            def resolve(self): return self
            def is_file(self): return True
            def stat(self): return SimpleNamespace(st_dev=7, st_ino=11)

        roots = [ResourcePath(r'C:\Assets'), ResourcePath(r'\\?\C:\Assets')]
        def walk(root, **kwargs):
            return [(str(root), [], ['case.mat', 'Case.mat'])]
        with patch.object(common, 'Path', ResourcePath), patch.object(common.os, 'walk', side_effect=walk):
            rows = discover(roots, ('mat',))
        self.assertEqual([row[1].name for row in rows], ['Case.mat', 'case.mat'])

    def test_same_anchor_mount_alias_cannot_bypass_containment(self):
        from pathlib import PurePosixPath
        root = PurePosixPath('/source/assets')
        output = PurePosixPath('/mount/alias/report')
        def samefile(left, right):
            return str(left) == '/mount/alias' and str(right) == '/source/assets'
        with patch.object(common.os.path, 'samefile', side_effect=samefile):
            self.assertTrue(common._is_within_resolved(output, root))

    def test_full_core_corpus_run_uses_synthetic_assets_and_preserves_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root, output = Path(directory) / 'assets', Path(directory) / 'report'
            root.mkdir()
            shutil.copyfile(TV / 'model' / 'triangle.3do', root / 'triangle.3do')
            shutil.copyfile(TV / 'key' / 'fractional.key', root / 'fractional.key')
            (root / 'texture.mat').write_bytes(mat_bytes())
            (root / 'dflt.cmp').write_bytes(cmp_bytes())
            original = {path.name: path.read_bytes() for path in root.iterdir()}
            options = SimpleNamespace(assets=[root], output=output, title='synthetic',
                                      formats=['3do', 'key', 'mat', 'cmp'], match='*',
                                      limit=0, cmp=None, keep_exports=True)
            with contextlib.redirect_stdout(io.StringIO()):
                status = run(options, check)
            self.assertEqual(status, 0)
            summary = json.loads((output / 'summary.json').read_text())
            self.assertEqual(summary['counts'], {'pass': 4})
            self.assertTrue(summary['full_corpus'])
            self.assertTrue((output / 'exports' / '0' / 'triangle.3do').is_file())
            self.assertEqual({path.name: path.read_bytes() for path in root.iterdir()}, original)
            records = [json.loads(line) for line in (output / 'results.jsonl').read_text().splitlines()]
            self.assertTrue(all(record['source_unchanged'] for record in records))

    def test_error_mismatch_and_unsupported_are_not_passes(self):
        for kind in ('error', 'mismatch', 'unsupported'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root, output = Path(directory) / 'assets', Path(directory) / 'report'
                root.mkdir()
                (root / 'file.key').write_text('synthetic')
                options = SimpleNamespace(assets=[root], output=output, title='failure',
                                          formats=['key'], match='*', limit=0, cmp=None, keep_exports=False)
                def handler(path, target, options):
                    if kind == 'error':
                        raise ValueError('parse failed')
                    if kind == 'unsupported':
                        raise UnsupportedResource('not implemented')
                    return {'differences': ['changed pose']}
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(run(options, handler), 1)
                summary = json.loads((output / 'summary.json').read_text())
                self.assertEqual(summary['counts'], {kind: 1})

    def test_limit_is_explicit_and_empty_corpus_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root, output = Path(directory) / 'assets', Path(directory) / 'report'
            root.mkdir()
            options = SimpleNamespace(assets=[root], output=output, title='limited',
                                      formats=['key'], match='*', limit=1, cmp=None, keep_exports=False)
            with self.assertRaisesRegex(ValueError, 'empty run'):
                run(options, lambda *args: {})
            for name in ('a.key', 'b.key'):
                (root / name).write_text('synthetic')
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run(options, lambda *args: {}), 0)
            summary = json.loads((output / 'summary.json').read_text())
            self.assertFalse(summary['full_corpus'])
            self.assertEqual(summary['selected'], {'key': 1})
