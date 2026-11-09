"""File ownership must not depend on garbage collection or the host OS."""
import builtins
import contextlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from fixtures import TV
from sith.key import keyLoader, keyWriter
from sith.material.cmp import ColorMap
from sith.model import model3doLoader, model3doWriter


class ResourceFileTests(unittest.TestCase):
    @contextlib.contextmanager
    def track_open(self, streams):
        real_open = builtins.open
        def open_file(*args, **kwargs):
            stream = real_open(*args, **kwargs)
            streams.append(stream)
            return stream
        with mock.patch('builtins.open', side_effect=open_file), mock.patch('io.open', side_effect=open_file):
            yield

    def test_readers_close_files_on_failure(self):
        cases = ((keyLoader.loadKey, b'SECTION: HEADER\nBAD 1\n', (AssertionError, OSError)),
                 (model3doLoader.load3do, b'SECTION: HEADER\nBAD 2.3\n', (AssertionError, OSError)),
                 (ColorMap.load, b'bad palette', ImportError))
        for reader, data, error_type in cases:
            with self.subTest(reader=reader.__name__), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'invalid'
                path.write_bytes(data)
                streams = []
                with self.track_open(streams), self.assertRaises(error_type):
                    reader(path)
                self.assertTrue(streams)
                self.assertTrue(all(stream.closed for stream in streams))
                path.unlink()

    def test_writers_close_files_on_mid_write_failure(self):
        model, version = model3doLoader.load3do(TV / 'model' / 'triangle.3do')
        key = keyLoader.loadKey(TV / 'key' / 'fractional.key')
        cases = ((keyWriter, '_write_section_keyframe_nodes', keyWriter.saveKey, (key,)),
                 (model3doWriter, '_write_section_geometry', model3doWriter.save3do, (model,)))
        for module, failing_step, writer, args in cases:
            with self.subTest(writer=writer.__name__), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'output'
                streams = []
                extra = (version, '') if writer is model3doWriter.save3do else ('',)
                with self.track_open(streams), mock.patch.object(
                        module, failing_step, side_effect=OSError('simulated write failure')):
                    with self.assertRaisesRegex(OSError, 'simulated'):
                        writer(*args, path, *extra)
                self.assertTrue(streams)
                self.assertTrue(all(stream.closed for stream in streams))
                path.unlink()

    def test_writers_propagate_open_failure(self):
        model, version = model3doLoader.load3do(TV / 'model' / 'triangle.3do')
        key = keyLoader.loadKey(TV / 'key' / 'fractional.key')
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(OSError):
                keyWriter.saveKey(key, Path(directory), '')
            with self.assertRaises(OSError):
                model3doWriter.save3do(model, Path(directory), version, '')
