"""KEY syntax must be complete before codecs or corpus checks accept a resource."""
import contextlib
import io
import json
from pathlib import Path
import re
import shutil
import tempfile
from types import SimpleNamespace
import unittest

from batch.common import run
from batch.core import check
from fixtures import TV
from sith.key.keyLoader import loadKey
from sith.model.model3doLoader import load3do

HEADER = 'SECTION: HEADER\nFLAGS 0\nTYPE 0\nFRAMES 5\nFPS 30\nJOINTS 0\n'
NODES = 'SECTION: KEYFRAME NODES\nNODES 0\n'
MARKERS = 'SECTION: MARKERS\nMARKERS 0\n'
NODE = 'NODE 0\nMESH NAME joint\nENTRIES 0\n'


class KeyStructureTests(unittest.TestCase):
    def load_text(self, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.key'
            path.write_text(text)
            return loadKey(path)

    def test_missing_required_sections_reject_empty_garbage_and_partial_files(self):
        for text in ('', '# comments only\n', 'This is not a KEY resource.\n', HEADER,
                     NODES, MARKERS, 'SECTION: UNKNOWN\nignored\n'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'KEY.*section|KEY HEADER'):
                self.load_text(text)

    def test_recognized_sections_are_unique_and_in_engine_order(self):
        for text in (HEADER + HEADER + NODES, HEADER + MARKERS + MARKERS + NODES,
                     HEADER + NODES + NODES, HEADER + NODES + MARKERS,
                     MARKERS + HEADER + NODES, NODES + HEADER,
                     HEADER + NODES + HEADER):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.load_text(text)

    def test_optional_markers_empty_tracks_and_unknown_extensions(self):
        for text in (HEADER + NODES, HEADER + MARKERS + NODES,
                     HEADER + 'SECTION: EXTENSION\nignored 123\n' + NODES):
            with self.subTest(text=text):
                key = self.load_text(text)
                self.assertEqual((key.numFrames, key.numJoints, key.nodes, key.markers), (5, 0, [], []))

    def test_invalid_counts_and_joint_indices_are_rejected(self):
        joint_header = HEADER.replace('JOINTS 0', 'JOINTS 1')
        node_section = 'SECTION: KEYFRAME NODES\nNODES 1\n' + NODE
        cases = (HEADER.replace('FRAMES 5', 'FRAMES -1') + NODES,
                 HEADER.replace('JOINTS 0', 'JOINTS -1') + NODES,
                 HEADER + NODES.replace('NODES 0', 'NODES -1'),
                 HEADER + node_section,
                 HEADER + MARKERS.replace('MARKERS 0', 'MARKERS -1') + NODES,
                 joint_header + node_section.replace('NODE 0', 'NODE -1'),
                 joint_header + node_section.replace('NODE 0', 'NODE 1'),
                 joint_header + node_section.replace('ENTRIES 0', 'ENTRIES -1'),
                 joint_header.replace('JOINTS 1', 'JOINTS 2')
                 + 'SECTION: KEYFRAME NODES\nNODES 2\n' + NODE + NODE)
        for text in cases:
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.load_text(text)

    def test_corpus_reports_headerless_inputs_as_errors_and_continues(self):
        with tempfile.TemporaryDirectory() as directory:
            root, output = Path(directory) / 'assets', Path(directory) / 'reports'
            root.mkdir()
            (root / 'garbage.key').write_text('This is not a KEY resource.\n')
            shutil.copyfile(TV / 'key/fractional.key', root / 'valid.key')
            before = {path.name: path.read_bytes() for path in root.iterdir()}
            options = SimpleNamespace(assets=[root], output=output, title='synthetic', formats=['key'],
                                      match='*', limit=0, cmp=None, keep_exports=False, key_target='IJIM')
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run(options, check), 1)
            summary = json.loads((output / 'summary.json').read_text())
            self.assertEqual(summary['counts'], {'error': 1, 'pass': 1})
            self.assertTrue(summary['completed'])
            self.assertEqual({path.name: path.read_bytes() for path in root.iterdir()}, before)

    def test_engine_decimal_forms_load_in_complete_key_and_model_files(self):
        key_text = (TV / 'key/fractional.key').read_text()
        model_text = (TV / 'model/triangle.3do').read_text()
        with tempfile.TemporaryDirectory() as directory:
            key_path, model_path = Path(directory) / 'numeric.key', Path(directory) / 'numeric.3do'
            for value in ('+59.94', '59.', '59.e0', '+.5', '+5.e-1', '0.'):
                with self.subTest(value=value):
                    key_path.write_text(key_text.replace('FPS 59.94', 'FPS ' + value))
                    model_path.write_text(re.sub(r'(?m)^(RADIUS\s+)\S+', r'\g<1>' + value, model_text, count=1))
                    self.assertEqual(loadKey(key_path).fps, float(value))
                    self.assertEqual(load3do(model_path)[0].radius, float(value))
