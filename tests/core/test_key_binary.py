"""FYEK layout, lossless records, playback rules and rejection paths."""
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from grim_fixtures import binary_key_bytes, changed_word
from sith.key import Key, KeyFileFormat, KeyMarker, KeyNode
from sith.key.keyBinary import encodeBinaryKey, readBinaryKey, keyForPlayback, prepareGrimExport
from sith.key.keyLoader import loadKey
from sith.key.keyWriter import saveKey
from sith.key.keyValidation import validateKeyForTarget
from batch.common import arguments


class BinaryKeyTests(unittest.TestCase):
    def test_corpus_command_line_accepts_grim_target(self):
        with patch('sys.argv', ['runner', '--assets', 'source', '--output', 'report',
                                '--title', 'Grim', '--key-target', 'GRIM']):
            self.assertEqual(arguments('Binary KEY test').key_target, 'GRIM')

    def test_header_is_136_bytes_and_first_record_can_be_animated(self):
        data, offsets = binary_key_bytes(first_animated=True, duplicates=False)
        self.assertEqual(offsets['node0'], 136)
        key = readBinaryKey(data)
        self.assertEqual((key.name, key.fps, key.numFrames, key.numJoints), ('fixture.key', 15, 4, 3))
        self.assertEqual(key.nodes[0].meshName, 'root')
        self.assertEqual(len(key.nodes[0].keyframes), 2)
        self.assertEqual(key.nodes[1].keyframes[0].position, (1, 2, 3))
        self.assertEqual(key.nodes[1].keyframes[0].deltaRotation, (0, 90, 0))

    def test_exact_bytes_preserve_names_null_records_unused_slots_and_pointer_words(self):
        for first in (False, True):
            for duplicate in (False, True):
                for markers in (0, 2, 8):
                    for fps in (1.0, 15.0, 30.0, 29.970001220703125):
                        with self.subTest(first=first, duplicate=duplicate, markers=markers, fps=fps):
                            data, _ = binary_key_bytes(first_animated=first, duplicates=duplicate, markers=markers, fps=fps)
                            self.assertEqual(encodeBinaryKey(readBinaryKey(data)), data)

    def test_magic_auto_detection_and_explicit_output_format(self):
        data, _ = binary_key_bytes()
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'input.bin', Path(directory) / 'output.key'
            source.write_bytes(data)
            key = loadKey(source)
            self.assertEqual(key.fileFormat, KeyFileFormat.GrimBinary)
            saveKey(key, target, '', fileFormat=KeyFileFormat.GrimBinary)
            self.assertEqual(target.read_bytes(), data)
            self.assertEqual(source.read_bytes(), data)

    def test_every_truncated_prefix_and_trailing_data_is_rejected(self):
        data, _ = binary_key_bytes(first_animated=True)
        for length in range(len(data)):
            with self.subTest(length=length), self.assertRaises(ValueError):
                readBinaryKey(data[:length])
        with self.assertRaisesRegex(ValueError, 'trailing'):
            readBinaryKey(data + b'junk')

    def test_invalid_magic_counts_and_indices(self):
        data, offsets = binary_key_bytes()
        for offset, value in ((0, 0), (60, 0xFFFFFFFF), (68, 9),
                              (offsets['node1'] + 32, 3), (offsets['node1'] + 36, 0xFFFFFFFF)):
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                readBinaryKey(changed_word(data, offset, value))

    def test_only_truly_empty_duplicate_records_are_accepted(self):
        data, offsets = binary_key_bytes()
        for offset, value in ((offsets['node2'], 65), (offsets['node1'] + 32, 0)):
            with self.subTest(offset=offset), self.assertRaisesRegex(ValueError, 'duplicate'):
                readBinaryKey(changed_word(data, offset, value))

    def test_represented_nonfinite_values_and_nonpositive_fps_are_rejected(self):
        data, offsets = binary_key_bytes()
        for offset in (52, 72, offsets['node1_entry'], offsets['node1_entry'] + 8,
                       offsets['node1_entry'] + 20, offsets['node1_entry'] + 32, offsets['node1_entry'] + 44):
            for value in (math.nan, math.inf, -math.inf):
                with self.subTest(offset=offset, value=value), self.assertRaises(ValueError):
                    readBinaryKey(changed_word(data, offset, value, 'f'))
        with self.assertRaises(ValueError):
            readBinaryKey(changed_word(data, 52, 0.0, 'f'))

    def test_codec_preserves_finite_unordered_frames_for_application_preflight(self):
        data, offsets = binary_key_bytes()
        invalid_for_blender = changed_word(data, offsets['node1_entry'] + 56, 0.0, 'f')
        self.assertEqual(encodeBinaryKey(readBinaryKey(invalid_for_blender)), invalid_for_blender)

    def test_unknown_marker_and_entry_flags_are_retained_by_codec(self):
        data, offsets = binary_key_bytes()
        data = changed_word(data, 104, -73, 'i')
        data = changed_word(data, offsets['node1_entry'] + 4, 0x80000003)
        self.assertEqual(encodeBinaryKey(readBinaryKey(data)), data)

    def test_grim_playback_uses_global_interpolation_not_entry_change_flags(self):
        for flags, expected in ((0, 3), (256, 0)):
            data, _ = binary_key_bytes(flags=flags)
            key = readBinaryKey(data)
            runtime = keyForPlayback(key)
            self.assertEqual([node.idx for node in runtime.nodes], [1])
            self.assertTrue(all(entry.flags == expected for node in runtime.nodes for entry in node.keyframes))
            self.assertEqual(key.nodes[1].keyframes[0].flags, 0)
            self.assertEqual(encodeBinaryKey(key), data)

    def test_playback_collapses_equal_frames_without_rewriting_raw_records(self):
        data, offsets = binary_key_bytes()
        data = changed_word(data, offsets['node1_entry'] + 56, 0.0, 'f')
        key = readBinaryKey(data)
        runtime = keyForPlayback(key)
        self.assertEqual(len(runtime.nodes[0].keyframes), 1)
        self.assertEqual(runtime.nodes[0].keyframes[0].position, (2, 2, 3))
        self.assertEqual(encodeBinaryKey(key), data)

    def test_zero_duration_pose_displays_without_extrapolation(self):
        key = readBinaryKey(binary_key_bytes()[0])
        key.numFrames = 0
        runtime = keyForPlayback(key)
        self.assertEqual(runtime.numFrames, 1)
        self.assertTrue(all(entry.flags == 0 for node in runtime.nodes for entry in node.keyframes))
        self.assertEqual(key.numFrames, 0)

    def test_export_drops_ignored_deltas_and_rejects_conflicting_no_interpolation(self):
        key = readBinaryKey(binary_key_bytes()[0])
        prepared = prepareGrimExport(key)
        self.assertEqual(prepared.nodes[1].keyframes[0].deltaPosition, (0, 0, 0))
        self.assertEqual(key.nodes[1].keyframes[0].deltaPosition, (.5, 0, 0))
        key.flags = 256
        key.nodes[1].keyframes[0].flags = 3
        with self.assertRaisesRegex(ValueError, '0x100'):
            prepareGrimExport(key)

    def test_new_sparse_and_empty_resources_are_serializable(self):
        key = Key('empty.key')
        key.fps = 15
        self.assertEqual(readBinaryKey(encodeBinaryKey(key)).nodes, [])
        key.numJoints = 4
        node = KeyNode()
        node.idx, node.meshName = 3, 'last'
        key.nodes = [node]
        restored = readBinaryKey(encodeBinaryKey(key))
        self.assertEqual(restored.numJoints, 4)
        self.assertEqual(restored.nodes[-1].meshName, 'last')

    def test_physical_name_limits_do_not_use_text_identifier_restrictions(self):
        key = readBinaryKey(binary_key_bytes()[0])
        key.name = 'name with spaces#' + 'x' * 19
        key.nodes[1].meshName = 'j' * 32
        validateKeyForTarget(key, 'GRIM')
        self.assertEqual(readBinaryKey(encodeBinaryKey(key)).name, key.name)
        key.nodes[1].meshName += 'j'
        with self.assertRaisesRegex(ValueError, '32-byte'):
            validateKeyForTarget(key, 'GRIM')

    def test_invalid_metadata_names_and_marker_capacity_preserve_previous_export(self):
        for field, value in (('name', 'x' * 37), ('name', 'bad\0name'), ('name', '\u00e9'),
                             ('binaryData', 'bad'), ('binaryData', {'markerSlots': 'ff'}),
                             ('binaryData', {'records': [None]}), ('binaryData', {'records': [{'index': []}]})):
            key = readBinaryKey(binary_key_bytes()[0])
            setattr(key, field, value)
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / 'keep.key'
                target.write_bytes(b'previous')
                with self.assertRaises(ValueError):
                    saveKey(key, target, '', fileFormat=KeyFileFormat.GrimBinary)
                self.assertEqual(target.read_bytes(), b'previous')
        key = readBinaryKey(binary_key_bytes()[0])
        key.markers = [KeyMarker() for _ in range(9)]
        with self.assertRaisesRegex(ValueError, '8 markers'):
            encodeBinaryKey(key)
