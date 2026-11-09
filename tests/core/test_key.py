import contextlib
import copy
import io
import math
from pathlib import Path
import tempfile
import unittest

from fixtures import TV
from sith.key import Key, KeyFlag, Keyframe, KeyframeFlag, KeyNode, KeyMarker, KeyMarkerType
from sith.key.keyLoader import loadKey
from sith.key.keyWriter import saveKey
from sith.types import Vector3f
from sith.types.vector import kFloat32Max


class KeyCodecTests(unittest.TestCase):
    def roundtrip(self, key):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'roundtrip.key'
            saveKey(key, path, 'Synthetic test')
            return loadKey(path)

    def load_text(self, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.key'
            path.write_text(text, encoding='utf-8')
            return loadKey(path)

    def test_hand_authored_fractional_frames(self):
        key = loadKey(TV / 'key' / 'fractional.key')
        self.assertEqual([entry.frame for entry in key.nodes[0].keyframes], [0, 0.25, 1.75])
        self.assertEqual(key.markers[0].frame, 1.25)
        restored = self.roundtrip(key)
        self.assertEqual([entry.frame for entry in restored.nodes[0].keyframes], [0, 0.25, 1.75])
        self.assertEqual(restored.markers[0].frame, 1.25)
        self.assertEqual(restored.nodeTypes, key.nodeTypes)
        self.assertAlmostEqual(restored.fps, key.fps)

    def test_every_key_flag_and_combination(self):
        for flag in [KeyFlag(0), *KeyFlag, KeyFlag(0x7f)]:
            key = loadKey(TV / 'key' / 'fractional.key')
            key.flags = flag
            with self.subTest(flag=flag):
                self.assertEqual(self.roundtrip(key).flags, flag)

    def test_every_marker_type_and_fractional_time(self):
        key = loadKey(TV / 'key' / 'fractional.key')
        key.markers = []
        for i, kind in enumerate(KeyMarkerType):
            marker = KeyMarker()
            marker.frame, marker.type = i + 0.125, kind
            key.markers.append(marker)
        restored = self.roundtrip(key)
        self.assertEqual([(m.frame, m.type) for m in restored.markers],
                         [(m.frame, m.type) for m in key.markers])

    def test_every_entry_flag_and_signed_deltas(self):
        key = loadKey(TV / 'key' / 'fractional.key')
        for flags in KeyframeFlag:
            key.nodes[0].keyframes[0].flags = flags
            with self.subTest(flags=flags):
                restored = self.roundtrip(key)
                for a, b in zip(restored.nodes[0].keyframes, key.nodes[0].keyframes):
                    for name in ('frame', 'flags', 'position', 'orientation', 'deltaPosition', 'deltaRotation'):
                        self.assertEqual(getattr(a, name), getattr(b, name), name)

    def test_exponent_frame_times_and_fractional_fps(self):
        key = loadKey(TV / 'key' / 'fractional.key')
        key.nodes[0].keyframes[1].frame = 0.0000125
        key.fps = 24000 / 1001
        restored = self.roundtrip(key)
        self.assertAlmostEqual(restored.nodes[0].keyframes[1].frame, 0.0000125, delta=1e-12)
        self.assertAlmostEqual(restored.fps, key.fps, delta=1e-6)

    def test_empty_nodes_markers_and_sparse_joint_indices(self):
        key = Key('empty')
        restored = self.roundtrip(key)
        self.assertEqual(restored.nodes, [])
        self.assertEqual(restored.markers, [])
        key = loadKey(TV / 'key' / 'fractional.key')
        key.numJoints = 17
        key.nodes[0].idx = 16
        restored = self.roundtrip(key)
        self.assertEqual((restored.numJoints, restored.nodes[0].idx), (17, 16))

    def test_floating_fields_roundtrip_without_decimal_truncation(self):
        key = loadKey(TV / 'key' / 'fractional.key')
        key.fps = 24000 / 1001
        key.markers[0].frame = 0.12345678901234567
        key.nodes[0].keyframes[1].frame = 0.23456789012345678

        # Cover small motion, float32 endpoints and signed zero independently of
        # Blender. Re-parsing must not round an accepted value above float32 max.
        for value in (0.0, -0.0, 4e-9, -1e-30, math.nextafter(1.0, 2.0),
                      float.fromhex('0x1p-149'), kFloat32Max, -kFloat32Max):
            with self.subTest(value=value):
                entry = key.nodes[0].keyframes[0]
                for attribute in ('position', 'orientation', 'deltaPosition', 'deltaRotation'):
                    setattr(entry, attribute, Vector3f(value, value, value))
                restored = self.roundtrip(key)
                self.assertEqual(restored.fps, key.fps)
                self.assertEqual(restored.markers[0].frame, key.markers[0].frame)
                self.assertEqual(restored.nodes[0].keyframes[1].frame, key.nodes[0].keyframes[1].frame)
                for attribute in ('position', 'orientation', 'deltaPosition', 'deltaRotation'):
                    actual = getattr(restored.nodes[0].keyframes[0], attribute)
                    self.assertEqual(actual, (value,) * 3)
                    self.assertEqual(math.copysign(1.0, actual.x), math.copysign(1.0, value))

    def test_small_deltas_keep_motion_over_long_segments(self):
        key = Key('slow.key')
        key.fps, key.numFrames, key.numJoints = 30, 1000001, 1
        node, first, last = KeyNode(), Keyframe(), Keyframe()
        node.idx, node.meshName = 0, 'joint'
        first.flags = KeyframeFlag.AllChange
        first.deltaPosition = Vector3f(4e-9, -3e-9, 1e-12)
        first.deltaRotation = Vector3f(-4e-9, 3e-9, -1e-12)
        last.frame = 1000000
        node.keyframes, key.nodes = [first, last], [node]
        restored = self.roundtrip(key).nodes[0].keyframes[0]
        self.assertEqual(restored.deltaPosition, first.deltaPosition)
        self.assertEqual(restored.deltaRotation, first.deltaRotation)
        self.assertEqual(restored.deltaPosition.x * 500000, 0.002)

    def test_invalid_numeric_fields_are_rejected_before_opening_output(self):
        original = loadKey(TV / 'key' / 'fractional.key')
        fields = [((), name) for name in ('fps', 'numFrames', 'numJoints', 'flags', 'nodeTypes')]
        fields += [(('markers', 0), name) for name in ('frame', 'type')]
        fields += [(('nodes', 0), 'idx')]
        fields += [(('nodes', 0, 'keyframes', 0), name) for name in ('frame', 'flags')]
        fields += [(('nodes', 0, 'keyframes', 0), (name, component))
                   for name in ('position', 'orientation', 'deltaPosition', 'deltaRotation')
                   for component in ('x', 'y', 'z')]
        values = (math.nan, math.inf, -math.inf, 1e100, -1e100,
                  math.nextafter(kFloat32Max, math.inf))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'safe.key'
            for route, attribute in fields:
                for value in values:
                    with self.subTest(route=route, attribute=attribute, value=value):
                        key = copy.deepcopy(original)
                        destination = key
                        for step in route:
                            destination = destination[step] if isinstance(step, int) else getattr(destination, step)
                        if isinstance(attribute, tuple):
                            name, component = attribute
                            setattr(destination, name, getattr(destination, name)._replace(**{component: value}))
                        else:
                            setattr(destination, attribute, value)
                        for existing in (False, True):
                            if existing:
                                path.write_bytes(b'existing valid export')
                            with self.assertRaisesRegex(ValueError, 'float32'):
                                saveKey(key, path, '')
                            self.assertEqual(path.exists(), existing)
                            if existing:
                                self.assertEqual(path.read_bytes(), b'existing valid export')
                                path.unlink()

    def test_unknown_marker_warns_and_skips(self):
        text = (TV / 'key' / 'fractional.key').read_text()
        import re
        text = re.sub(r'(1\.25\s+)\d+', r'\g<1>999', text, count=1)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            key = self.load_text(text)
        self.assertIn('Unknown marker', output.getvalue())
        self.assertEqual(key.markers, [])

    def test_truncated_entries_and_wrong_labels(self):
        original = (TV / 'key' / 'fractional.key').read_text()
        for text in (original.replace('FLAGS', 'WRONG', 1), original[:-15]):
            with self.subTest(text=text[-30:]), self.assertRaises((TypeError, ValueError, AssertionError)):
                self.load_text(text)

    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(FileNotFoundError):
            loadKey(Path(directory) / 'missing.key')

    def test_deterministic_writer(self):
        key = loadKey(TV / 'key' / 'fractional.key')
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / name for name in ('a.key', 'b.key')]
            for path in paths:
                saveKey(key, path, 'same')
            self.assertEqual(paths[0].read_bytes(), paths[1].read_bytes())
