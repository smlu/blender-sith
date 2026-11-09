"""Recovery keeps independent complete tracks, never guesses damaged motion."""
import copy
import re
from pathlib import Path
import tempfile
import unittest

from fixtures import TV
from batch.common import key_snapshot
from grim_fixtures import binary_key_bytes, changed_word
from sith.key import KeyFileFormat
from sith.key.keyBinary import encodeBinaryKey, readBinaryKey
from sith.key.keyLoader import loadKey
from sith.key.keyRecovery import recoverKey
from sith.key.keyWriter import saveKey


class KeyRecoveryTests(unittest.TestCase):
    def test_valid_text_recovery_keeps_all_data_without_warnings(self):
        warnings = []
        path = TV / 'key/fractional.key'
        self.assertEqual(key_snapshot(loadKey(path, allowErrors=True, warnings=warnings)),
                         key_snapshot(loadKey(path)))
        self.assertEqual(warnings, [])

    def test_valid_binary_recovery_is_byte_identical(self):
        for flags in (0, 256):
            data, _ = binary_key_bytes(first_animated=True, flags=flags)
            warnings = []
            key = readBinaryKey(data, allowErrors=True, warnings=warnings)
            self.assertEqual(encodeBinaryKey(key), data)
            self.assertEqual(warnings, [])

    def test_bad_binary_track_is_omitted_without_renumbering(self):
        data, offsets = binary_key_bytes(first_animated=True)
        # Corrupt a transform in joint one; joint zero must remain untouched.
        for value in (float('nan'), float('inf'), -float('inf')):
            with self.subTest(value=value):
                damaged = changed_word(data, offsets['node1_entry'] + 8, value, 'f')
                with self.assertRaisesRegex(ValueError, 'finite'):
                    readBinaryKey(damaged)
                warnings = []
                key = readBinaryKey(damaged, allowErrors=True, warnings=warnings)
                self.assertEqual(key.numJoints, 3)
                self.assertEqual([node.idx for node in key.nodes], [0])
                self.assertIn('joint 1', warnings[0])
                restored = readBinaryKey(encodeBinaryKey(key))
                self.assertEqual(key_snapshot(restored)['nodes'][0], key_snapshot(key)['nodes'][0])
                self.assertFalse(any(node.keyframes for node in restored.nodes if node.idx == 1))

    def test_recovery_rejects_no_usable_tracks_and_unsafe_binary_structure(self):
        data, offsets = binary_key_bytes()
        bad_track = changed_word(data, offsets['node1_entry'] + 8, float('nan'), 'f')
        with self.assertRaisesRegex(ValueError, 'no usable'):
            readBinaryKey(bad_track, allowErrors=True)
        for damaged in (data[:135], data[:-1], data + b'junk',
                        changed_word(data, 52, 0, 'f'), changed_word(data, 60, 1000000)):
            with self.subTest(size=len(damaged)):
                with self.assertRaises(ValueError):
                    readBinaryKey(damaged, allowErrors=True)

    def test_invalid_markers_are_omitted_and_duplicate_frames_stay_valid(self):
        data, offsets = binary_key_bytes()
        for offset, value, fmt in ((72, float('nan'), 'f'), (104, 123456, 'i')):
            warnings = []
            key = readBinaryKey(changed_word(data, offset, value, fmt), allowErrors=True, warnings=warnings)
            self.assertEqual(len(key.markers), 1)
            self.assertEqual(len(warnings), 1)
            readBinaryKey(encodeBinaryKey(key))
        warnings = []
        key = readBinaryKey(changed_word(data, offsets['node1_entry'] + 56, 0, 'f'),
                            allowErrors=True, warnings=warnings)
        self.assertEqual(warnings, [])
        self.assertEqual(len(key.nodes[1].keyframes), 2)

    def test_text_recovery_retains_only_complete_tracks(self):
        source = loadKey(TV / 'key/fractional.key')
        source.numJoints = 2
        later = copy.deepcopy(source.nodes[0])
        later.idx, later.meshName = 1, 'later'
        source.nodes.append(later)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'partial.key'
            saveKey(source, path, '')
            text = path.read_text()
            start = re.search(r'\bNODE\s+1\b', text).start()
            damaged = text[:start] + 'NODE 1\nMESH NAME later\nENTRIES 1\n0: 0 3 1 2'
            path.write_text(damaged)
            with self.assertRaises((AssertionError, TypeError, ValueError, OSError)):
                loadKey(path)
            warnings = []
            key = loadKey(path, allowErrors=True, warnings=warnings)
            self.assertEqual([node.idx for node in key.nodes], [0])
            self.assertEqual(key_snapshot(key)['nodes'][0], key_snapshot(source)['nodes'][0])
            self.assertIn('unread', warnings[0])
            self.assertEqual(path.read_text(), damaged)
            # Header damage is never treated as a recoverable tail.
            path.write_text('SECTION: HEADER\nFLAGS 0')
            with self.assertRaises((AssertionError, TypeError, ValueError, OSError)):
                loadKey(path, allowErrors=True)

    def test_recovery_drops_backward_tracks_but_keeps_late_starts(self):
        key = loadKey(TV / 'key/fractional.key')
        later = copy.deepcopy(key.nodes[0])
        later.idx = 1
        key.numJoints = 2
        key.nodes.append(later)
        key.nodes[0].keyframes[1].frame = -1
        later.keyframes[0].frame = 0.125
        warnings = []
        recoverKey(key, warnings)
        self.assertEqual(key.fileFormat, KeyFileFormat.Text)
        self.assertEqual([node.idx for node in key.nodes], [1])
        self.assertEqual(key.nodes[0].keyframes[0].frame, 0.125)
        self.assertEqual(len(warnings), 1)
