"""File publication must not overwrite by default or leave partial bundles."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sith.material.matExporter import publishExportFiles, ExportRollbackError, _filename


class MatExportFileTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.staging = self.folder / 'staging'
        self.staging.mkdir()

    def prepared(self, name, data=b'new'):
        path = self.staging / name
        path.write_bytes(data)
        return path

    def test_existing_mat_is_kept_without_overwrite(self):
        target = self.folder / 'a.mat'
        target.write_bytes(b'old')
        warnings = []
        written = publishExportFiles([(target, self.prepared('a'), False)], self.staging, warnings=warnings)
        self.assertEqual(written, [])
        self.assertEqual(target.read_bytes(), b'old')
        self.assertEqual(len(warnings), 1)

    def test_new_parent_directory_and_overwrite(self):
        target = self.folder / 'mat/a.mat'
        self.assertEqual(publishExportFiles([(target, self.prepared('first'), False)], self.staging), [target])
        self.assertEqual(target.read_bytes(), b'new')
        publishExportFiles([(target, self.prepared('second', b'changed'), True)], self.staging)
        self.assertEqual(target.read_bytes(), b'changed')

    def test_exclusive_creation_race_does_not_report_a_written_file(self):
        target = self.folder / 'race.mat'
        open_file = Path.open
        def race(path, mode='r', *args, **kwargs):
            if path == target and mode == 'xb':
                with open_file(path, 'wb') as stream:
                    stream.write(b'another writer')
            return open_file(path, mode, *args, **kwargs)
        warnings = []
        with patch.object(Path, 'open', race):
            self.assertEqual(publishExportFiles([(target, self.prepared('race'), False)], self.staging,
                                              warnings=warnings), [])
        self.assertEqual(target.read_bytes(), b'another writer')
        self.assertTrue(any('created during export' in warning for warning in warnings))

    def test_later_failure_restores_replaced_files_and_model(self):
        first, second, model = [self.folder / name for name in ('a.mat', 'b.mat', 'model.3do')]
        for path in (first, second, model):
            path.write_bytes(b'original-' + path.name.encode())
        files = [(first, self.prepared('first'), True), (second, self.prepared('second'), True),
                 (model, self.prepared('model'), True)]
        import os
        replace = os.replace
        def fail_second(source, target):
            if Path(source).name == 'second':
                raise OSError('simulated disk failure')
            return replace(source, target)
        with patch('sith.material.matExporter.os.replace', side_effect=fail_second):
            with self.assertRaisesRegex(OSError, 'simulated'):
                publishExportFiles(files, self.staging)
        for path in (first, second, model):
            self.assertEqual(path.read_bytes(), b'original-' + path.name.encode())

    def test_failed_new_file_write_removes_partial_files_and_new_directory(self):
        target = self.folder / 'mat/a.mat'
        with patch('sith.material.matExporter.shutil.copyfileobj', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                publishExportFiles([(target, self.prepared('source'), False)], self.staging)
        self.assertFalse(target.exists())
        self.assertFalse(target.parent.exists())

    def test_model_failure_removes_new_textures_and_restores_model(self):
        target, model = self.folder / 'a.mat', self.folder / 'model.3do'
        model.write_bytes(b'previous model')
        missing = self.staging / 'missing'
        with self.assertRaises(OSError):
            publishExportFiles([(target, self.prepared('texture'), False), (model, missing, True)], self.staging)
        self.assertFalse(target.exists())
        self.assertEqual(model.read_bytes(), b'previous model')

    def test_unsafe_names_are_rejected_on_every_platform(self):
        for name in ('../a.mat', 'sub/a.mat', 'sub\\a.mat', 'C:a.mat', 'CON.mat', 'a.mat.', 'a\x00.mat'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                _filename(name)
        for name in ('brick.mat', 'brick.wall.mat', 'brick#red.mat'):
            _filename(name)

    def test_failed_backup_rename_leaves_original_in_place(self):
        target = self.folder / 'a.mat'
        target.write_bytes(b'original')
        with patch('sith.material.matExporter.os.replace', side_effect=OSError('rename denied')):
            with self.assertRaisesRegex(OSError, 'rename denied'):
                publishExportFiles([(target, self.prepared('new'), True)], self.staging)
        self.assertEqual(target.read_bytes(), b'original')

    def test_cross_volume_overwrite_uses_destination_local_renames(self):
        target = self.folder / 'custom/a.mat'
        target.parent.mkdir()
        target.write_bytes(b'old')
        import os
        replace = os.replace
        def local_replace(source, destination):
            self.assertEqual(Path(source).parent, Path(destination).parent)
            return replace(source, destination)
        with patch('sith.material.matExporter._same_volume', return_value=False), \
                patch('sith.material.matExporter.os.replace', side_effect=local_replace):
            publishExportFiles([(target, self.prepared('new'), True)], self.staging)
        self.assertEqual(target.read_bytes(), b'new')
        self.assertEqual(list(target.parent.glob('.sith-*')), [])

    def test_cross_volume_replacement_failure_restores_original(self):
        target = self.folder / 'custom/a.mat'
        target.parent.mkdir()
        target.write_bytes(b'old')
        import os
        replace = os.replace
        def fail_new(source, destination):
            if Path(source).name.startswith('.sith-write-'):
                raise OSError('simulated replacement failure')
            return replace(source, destination)
        with patch('sith.material.matExporter._same_volume', return_value=False), \
                patch('sith.material.matExporter.os.replace', side_effect=fail_new):
            with self.assertRaisesRegex(OSError, 'simulated'):
                publishExportFiles([(target, self.prepared('new'), True)], self.staging)
        self.assertEqual(target.read_bytes(), b'old')
        self.assertEqual(list(target.parent.glob('.sith-*')), [])

    def test_failed_restore_preserves_backup_and_reports_recovery_directory(self):
        target = self.folder / 'a.mat'
        target.write_bytes(b'original')
        import os
        replace = os.replace
        def fail_after_backup(source, destination):
            if Path(source) != target:
                raise OSError('replacement and restore denied')
            return replace(source, destination)
        with patch('sith.material.matExporter.os.replace', side_effect=fail_after_backup):
            with self.assertRaisesRegex(ExportRollbackError, 'Keep recovery files'):
                publishExportFiles([(target, self.prepared('new'), True)], self.staging)
        self.assertEqual((self.staging / 'backup-0').read_bytes(), b'original')
