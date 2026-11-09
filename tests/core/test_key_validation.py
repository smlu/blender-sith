"""Target compatibility, safe identifiers and parser forward progress."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fixtures import TV
from sith.key import Key, KeyNode, KeyMarker, KeyMarkerType
from sith.key.keyLoader import loadKey
from sith.key.keyWriter import saveKey
from sith.key.keyValidation import validateKeyForTarget, kKeyTargets
from sith.model.model3doLoader import load3do, Model3doFileVersion
from sith.model.model3doWriter import save3do
from sith.text.serutils import assertName
from batch.core import check as check_core
from types import SimpleNamespace


class ExportValidationTests(unittest.TestCase):
    def test_target_label_and_custom_opt_out_policy(self):
        labels = {identifier: label for identifier, label, description in kKeyTargets}
        self.assertEqual(labels['IJIM'], 'Infernal Machine')
        self.assertEqual(labels['CUSTOM'], 'Generic')
        key = Key('x' * 64)
        key.numJoints, key.markers = 100, [KeyMarker() for _ in range(40)]
        validateKeyForTarget(key, 'CUSTOM')
        key.name += 'x'
        with self.assertRaises(AssertionError):
            validateKeyForTarget(key, 'CUSTOM')

    def test_target_joint_and_marker_boundaries(self):
        for target, markerCount in (('IJIM', 16), ('JKDF2', 8), ('MOTS', 8)):
            with self.subTest(target=target):
                key = Key('valid.key')
                key.numJoints = 64
                key.markers = [KeyMarker() for _ in range(markerCount)]
                validateKeyForTarget(key, target)
                key.numJoints = 65
                with self.assertRaisesRegex(ValueError, 'joints'):
                    validateKeyForTarget(key, target)
                key.numJoints = 64
                key.markers.append(KeyMarker())
                with self.assertRaisesRegex(ValueError, 'markers'):
                    validateKeyForTarget(key, target)

    def test_target_name_buffer_boundaries(self):
        for target, length in (('IJIM', 63), ('JKDF2', 31), ('MOTS', 31)):
            key = Key('x' * length)
            node = KeyNode()
            node.meshName = 'j' * length
            key.nodes = [node]
            with self.subTest(target=target):
                validateKeyForTarget(key, target)
                node.meshName += 'j'
                with self.assertRaisesRegex(ValueError, 'name'):
                    validateKeyForTarget(key, target)
                node.meshName = 'joint'
                key.name += 'x'
                with self.assertRaisesRegex(ValueError, 'name'):
                    validateKeyForTarget(key, target)

    def test_custom_target_is_explicit_and_unknown_target_is_rejected(self):
        key = Key('custom.key')
        key.numJoints = 100
        key.markers = [KeyMarker() for _ in range(40)]
        validateKeyForTarget(key, 'CUSTOM')
        with self.assertRaisesRegex(ValueError, 'Unknown'):
            validateKeyForTarget(key, 'typo')

    def test_unquoted_name_grammar(self):
        for name in ('left_arm', 'arm.001', '0node', 'folder/part.mat'):
            with self.subTest(name=name):
                assertName(name)
        for name in ('', 'left arm', 'left\tarm', 'left\narm', 'left\rarm', '\x00', '\x7f', 'a#b', '"arm"', '\u00e9'):
            with self.subTest(name=name), self.assertRaises(AssertionError):
                assertName(name)

    def test_invalid_name_is_rejected_before_output_is_opened(self):
        model, _ = load3do(TV / 'model' / 'triangle.3do')
        key = loadKey(TV / 'key' / 'fractional.key')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'output'
            path.write_bytes(b'existing output')
            key.nodes[0].meshName = 'left arm'
            with self.assertRaises(AssertionError):
                saveKey(key, path, '')
            self.assertEqual(path.read_bytes(), b'existing output')
            for invalid, badName in ((model.meshHierarchy[0], 'left arm'),
                                     (model.geosets[0].meshes[0], 'left\narm')):
                original = invalid.name
                invalid.name = badName
                with self.assertRaises(AssertionError):
                    save3do(model, path, Model3doFileVersion.Version2_3, '')
                self.assertEqual(path.read_bytes(), b'existing output')
                invalid.name = original

    def test_mesh_display_names_are_line_fields_not_identifier_tokens(self):
        model, _ = load3do(TV / 'model' / 'triangle.3do')
        model.geosets[0].meshes[0].name = 'example display name'
        for version in Model3doFileVersion:
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'named.3do'
                save3do(model, path, version, '')
                restored, _ = load3do(path)
                self.assertEqual(restored.geosets[0].meshes[0].name, 'example display name')
        assertName('example display name', allowSpaces=True)
        with self.assertRaises(AssertionError):
            assertName('example display name')
        with self.assertRaises(AssertionError):
            assertName('example\ndisplay name', allowSpaces=True)

    def test_writer_sorts_markers_stably_without_mutating_input(self):
        key = Key('markers.key')
        for frame, kind in ((10, KeyMarkerType.Attack), (2, KeyMarkerType.LeftFoot),
                            (2, KeyMarkerType.RightFoot), (2.1, KeyMarkerType.Swing)):
            marker = KeyMarker()
            marker.frame, marker.type = frame, kind
            key.markers.append(marker)
        before = [(marker.frame, marker.type) for marker in key.markers]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / key.name
            saveKey(key, path, '')
            restored = loadKey(path)
        self.assertEqual([(marker.frame, marker.type) for marker in key.markers], before)
        self.assertEqual([(marker.frame, marker.type) for marker in restored.markers], sorted(before, key=lambda value: value[0]))

    def test_corpus_core_records_corrected_source_order_without_changing_source(self):
        text = '''SECTION: HEADER
FLAGS 0
TYPE 0
FRAMES 20
FPS 30
JOINTS 0
SECTION: MARKERS
MARKERS 2
15 2
1 1
SECTION: KEYFRAME NODES
NODES 0
'''
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'source.key', Path(directory) / 'target.key'
            source.write_text(text)
            result = check_core(source, target, SimpleNamespace(key_target='IJIM'))
            self.assertFalse(result['differences'])
            self.assertTrue(result['source_marker_order_corrected'])
            self.assertEqual(source.read_text(), text)
            self.assertEqual([marker.frame for marker in loadKey(target).markers], [1, 15])

    def test_invalid_key_tokens_fail_in_a_bounded_subprocess(self):
        # A timeout kills/reaps a regressed infinite parser loop instead of hanging CI.
        root = Path(__file__).resolve().parents[2]
        code = f'''import sys, tempfile
from pathlib import Path
sys.path.insert(0, {str(root)!r})
from sith.key.keyLoader import loadKey
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / 'broken.key'
    for value in (b'\\x00', b'\\x01', b'SECTION: HEADER\\nFLAGS 0\\nTYPE 0\\nFRAMES 1\\nFPS 30\\nJOINTS 0\\n\\x00'):
        path.write_bytes(value)
        try:
            loadKey(path)
        except ValueError as error:
            assert 'Invalid KEY token' in str(error), str(error)
        else:
            raise AssertionError('Invalid token was accepted')
print('KEY token failures rejected')
'''
        command = ([sys.modules['bpy'].app.binary_path, '--background', '--factory-startup', '--python-exit-code', '1', '--python-expr', code]
                   if 'bpy' in sys.modules else [sys.executable, '-B', '-c', code])
        result = subprocess.run(command, capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('KEY token failures rejected', result.stdout)
