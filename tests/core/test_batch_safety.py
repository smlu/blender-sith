"""Report and export aliases must never turn read-only corpus checks into writes."""
import contextlib
import errno
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from batch import common
from batch.core import check
from fixtures import TV


class BatchSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root, self.output = Path(self.temp.name) / 'assets', Path(self.temp.name) / 'reports'
        self.root.mkdir()
        self.output.mkdir()
        self.source = self.root / 'model.3do'
        shutil.copyfile(TV / 'model/triangle.3do', self.source)
        self.original = self.source.read_bytes()
        self.options = SimpleNamespace(assets=[self.root], output=self.output, title='synthetic',
                                       formats=['3do'], match='*', limit=0, cmp=None, keep_exports=False)

    def link(self, destination, *, symbolic):
        try:
            if symbolic:
                destination.symlink_to(self.source)
            else:
                os.link(self.source, destination)
        except NotImplementedError as error:
            self.skipTest(f'Filesystem link creation is unavailable: {error}')
        except OSError as error:
            unavailable = error.errno in (errno.EPERM, errno.EACCES, errno.ENOSYS, errno.ENOTSUP)
            if unavailable or getattr(error, 'winerror', None) in (1, 50, 1314):
                self.skipTest(f'Filesystem link creation is unavailable: {error}')
            raise

    def test_symlinked_reports_reject_before_replacing_either_report(self):
        # Check privilege outside subtests so an unavailable feature skips this
        # test once, without leaving one case's files behind for the next case.
        probe = self.output / '.symlink-probe'
        self.link(probe, symbolic=True)
        probe.unlink()
        for name, other in (('results.jsonl', 'summary.json'), ('summary.json', 'results.jsonl')):
            with self.subTest(name=name):
                linked = self.output / name
                untouched = self.output / other
                untouched.write_bytes(b'previous report')
                self.link(linked, symbolic=True)
                with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, 'report path'):
                    common.run(self.options, check)
                self.assertEqual(self.source.read_bytes(), self.original)
                self.assertEqual(untouched.read_bytes(), b'previous report')
                self.assertTrue(linked.is_symlink())
                linked.unlink()
                untouched.unlink()

    def test_report_directories_reject_before_replacing_other_report(self):
        for name, other in (('results.jsonl', 'summary.json'), ('summary.json', 'results.jsonl')):
            with self.subTest(name=name):
                invalid = self.output / name
                invalid.mkdir()
                untouched = self.output / other
                untouched.write_bytes(b'previous report')
                with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, 'report path'):
                    common.run(self.options, check)
                self.assertEqual(self.source.read_bytes(), self.original)
                self.assertEqual(untouched.read_bytes(), b'previous report')
                self.assertTrue(invalid.is_dir())
                invalid.rmdir()
                untouched.unlink()

    def test_hardlinked_reports_are_replaced_without_touching_input_inodes(self):
        for name in ('results.jsonl', 'summary.json'):
            with self.subTest(name=name):
                for report in self.output.iterdir():
                    report.unlink()
                linked = self.output / name
                self.link(linked, symbolic=False)
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(common.run(self.options, check), 0)
                self.assertEqual(self.source.read_bytes(), self.original)
                self.assertFalse(os.path.samefile(linked, self.source))
                record = json.loads((self.output / 'results.jsonl').read_text())
                self.assertEqual(record['status'], 'pass')
                self.assertTrue(record['source_unchanged'])

    def test_exclusive_results_creation_cannot_follow_a_racing_link(self):
        path = self.output / 'results.jsonl'
        path.write_text('previous report')
        original_open = Path.open

        def insert_link_before_open(target, mode='r', *args, **kwargs):
            if target == path:
                self.assertEqual(mode, 'x')
                self.link(path, symbolic=False)
            return original_open(target, mode, *args, **kwargs)

        # Simulate a new alias appearing after validation/unlink. Exclusive open
        # must fail, not truncate the source inode through that alias.
        with mock.patch.object(Path, 'open', insert_link_before_open), self.assertRaises(FileExistsError):
            common._open_results(path)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_hardlinked_retained_export_is_rejected_before_handler_runs(self):
        target = self.output / 'exports/0/model.3do'
        target.parent.mkdir(parents=True)
        self.link(target, symbolic=False)
        self.options.keep_exports = True
        handler = mock.Mock(wraps=check)
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, 'multiply-linked export'):
            common.run(self.options, handler)
        handler.assert_not_called()
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(target.read_bytes(), self.original)

    def test_regular_reports_are_replaced_and_records_remain_incremental(self):
        for name in ('results.jsonl', 'summary.json'):
            (self.output / name).write_text('previous report')
        shutil.copyfile(self.source, self.root / 'second.3do')
        visible_records = []

        def observe_report(path, target, options):
            visible_records.append(len((self.output / 'results.jsonl').read_text().splitlines()))
            return check(path, target, options)

        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(common.run(self.options, observe_report), 0)
        self.assertEqual(visible_records, [0, 1])
        self.assertEqual(json.loads((self.output / 'summary.json').read_text())['counts'], {'pass': 2})
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual((self.root / 'second.3do').read_bytes(), self.original)

    def test_summary_replace_failure_keeps_old_report_and_removes_temporary(self):
        path = self.output / 'summary.json'
        path.write_bytes(b'previous report')
        with mock.patch.object(common.os, 'replace', side_effect=OSError('simulated replace failure')):
            with self.assertRaisesRegex(OSError, 'simulated replace failure'):
                common._write_summary(path, {'counts': {'pass': 1}})
        self.assertEqual(path.read_bytes(), b'previous report')
        self.assertEqual(list(self.output.iterdir()), [path])

    def test_summary_encoding_failure_keeps_old_report_and_removes_temporary(self):
        path = self.output / 'summary.json'
        path.write_bytes(b'previous report')
        with self.assertRaises(TypeError):
            common._write_summary(path, {'invalid': object()})
        self.assertEqual(path.read_bytes(), b'previous report')
        self.assertEqual(list(self.output.iterdir()), [path])
