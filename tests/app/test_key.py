import bisect
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import bpy
import mathutils

from sith.key import Key, KeyFlag, Keyframe, KeyframeFlag, KeyNode, KeyMarker, KeyMarkerType
from sith.key.keyExporter import _make_key_from_obj, _sample_key_node, _set_keyframe_delta
from sith.key.keyImporter import _make_import_samples, importKey
from sith.key.keyLoader import loadKey
from sith.key.keyWriter import saveKey
from sith.key.keyUtils import getActionFCurves, getSceneFrameRate, setSceneFrameRate
from sith.model.utils import kImEulerOrder, makeQuaternionRotation
from sith.types import Vector3f

TV = Path(__file__).resolve().parents[1] / 'tv' / 'key'


def sample_key(node, frame):
    """The shared KEY contract: value + stored per-frame delta until the next entry."""
    index = max(0, bisect.bisect_right([entry.frame for entry in node.keyframes], frame) - 1)
    entry = node.keyframes[index]
    elapsed = frame - entry.frame
    position = list(entry.position)
    rotation = list(entry.orientation)
    if entry.flags & KeyframeFlag.PositionChange:
        position = [value + entry.deltaPosition[i] * elapsed for i, value in enumerate(position)]
    if entry.flags & KeyframeFlag.OrientationChange:
        rotation = [value + entry.deltaRotation[i] * elapsed for i, value in enumerate(rotation)]
    return position, rotation


class CurveTests(unittest.TestCase):
    def setUp(self):
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        self.scene = bpy.context.scene
        self.scene.frame_start = 0
        self.scene.frame_end = 10
        self.root = bpy.data.objects.new('root', None)
        self.obj = bpy.data.objects.new('joint', None)
        self.scene.collection.objects.link(self.root)
        self.scene.collection.objects.link(self.obj)
        self.obj.parent = self.root
        self.obj.rotation_mode = kImEulerOrder
        self.obj.sith_model3do_hnode_idx = 0
        self.obj.sith_model3do_hnode_name = 'joint'
        self.hnode = SimpleNamespace(obj=self.obj, idx=0, name='joint')

    def add_curve(self, path, axis, points, interpolation='LINEAR'):
        for frame, value in points:
            getattr(self.obj, path)[axis] = value
            self.obj.keyframe_insert(data_path=path, index=axis, frame=frame)
        curve = next(curve for curve in getActionFCurves(self.obj)
                     if curve.data_path == path and curve.array_index == axis)
        for point in curve.keyframe_points:
            point.interpolation = interpolation
        curve.update()
        return curve

    def export(self):
        return _sample_key_node(self.hnode, self.root, self.scene.frame_end)

    def assert_position(self, node, frame, expected, tolerance=2.0e-5):
        position, _ = sample_key(node, frame)
        for value, target in zip(position, expected):
            self.assertAlmostEqual(value, target, delta=tolerance)

    def assert_rotation(self, node, frame, expected, tolerance=0.002):
        _, rotation = sample_key(node, frame)
        actual = makeQuaternionRotation(rotation).to_matrix()
        target = makeQuaternionRotation(expected).to_matrix()
        for row in range(3):
            for column in range(3):
                self.assertAlmostEqual(actual[row][column], target[row][column], delta=tolerance)

    def test_zero_keys_are_values(self):
        self.add_curve('location', 0, [(0, 2), (5, 0), (10, -2)])
        node = self.export()
        self.assert_position(node, 5, (0, 0, 0))
        self.assert_position(node, 7.5, (-1, 0, 0))

    def test_muted_modifiers_allow_constant_boundaries(self):
        curve = self.add_curve('location', 0, [(0, 2), (4, 8)], 'CONSTANT')
        modifier = curve.modifiers.new('NOISE')
        modifier.mute = True
        node = self.export()
        for frame, value in ((0, 2), (2, 2), (3.99995, 2), (4, 8), (7, 8)):
            self.assert_position(node, frame, (value, 0, 0))
        modifier.mute = False
        with self.assertRaisesRegex(ValueError, 'Bake F-curve modifiers'):
            self.export()

    def test_muted_modifiers_keep_exact_nearby_linear_samples(self):
        curve = self.add_curve('location', 0, [(0, 0), (4, 1000)], 'LINEAR')
        modifier = curve.modifiers.new('NOISE')
        modifier.mute = True
        node = self.export()
        for frame in (0.00005, 1, 3.99995, 4):
            self.assert_position(node, frame, (frame * 250, 0, 0), 5e-5)

    def test_muted_modifiers_retain_exact_imported_jump_segments(self):
        self.import_jump(True)
        curve = next(c for c in getActionFCurves(self.obj) if c.data_path == 'location')
        modifier = curve.modifiers.new('NOISE')
        modifier.mute = True
        node = self.export()
        self.assert_position(node, 3.9999, (0, 0, 3.9999))
        self.assert_position(node, 4, (0, 0, 10))

    def import_jump(self, clear_scene):
        key = Key('jump')
        key.numFrames, key.numJoints, key.fps = 6, 1, 30
        node = KeyNode()
        node.idx, node.meshName = 0, 'joint'
        first, last = Keyframe(), Keyframe()
        first.flags = KeyframeFlag.AllChange
        first.deltaPosition = Vector3f(0, 0, 1)
        first.deltaRotation = Vector3f(0, 3, 0)
        last.frame = 4
        last.position = Vector3f(0, 0, 10)
        last.orientation = Vector3f(0, 60, 0)
        node.keyframes = [first, last]
        key.nodes = [node]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'jump.key'
            saveKey(key, path, '')
            bpy.context.view_layer.objects.active = self.root
            importKey(path, self.scene, clear_scene, True, False)

    def test_import_keeps_nearby_keys_for_moving_jump(self):
        # keyframe_insert merges the left-limit key with the jump despite distinct times.
        self.import_jump(True)
        node = self.export()
        for frame in (0, 1, 3, 3.5, 3.9998):
            self.assert_position(node, frame, (0, 0, frame))
            self.assert_rotation(node, frame, (0, frame * 3, 0))
        self.assert_position(node, 4, (0, 0, 10))
        self.assert_rotation(node, 4, (0, 60, 0))
        curve = next(c for c in getActionFCurves(self.obj) if c.data_path == 'location' and c.array_index == 2)
        times = [point.co[0] for point in curve.keyframe_points]
        self.assertIn(4.0, times)
        self.assertTrue(any(3.999 < frame < 4 for frame in times))

    def test_import_without_clear_keeps_unrelated_existing_keys(self):
        self.add_curve('location', 0, [(20, 7), (30, 9)])
        self.import_jump(False)
        curve = next(c for c in getActionFCurves(self.obj) if c.data_path == 'location' and c.array_index == 0)
        points = {point.co[0]: point.co[1] for point in curve.keyframe_points}
        self.assertEqual((points[20], points[30]), (7, 9))

    def test_jump_playback_before_at_and_after_boundary(self):
        self.import_jump(True)
        # Use the real evaluated object, not the exporter's mathematical sampler.
        for frame, z, yaw in ((3.999, 3.999, 11.997), (4, 10, 60), (4.001, 10, 60)):
            self.scene.frame_set(math.floor(frame), subframe=frame % 1)
            actual = self.obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
            self.assertAlmostEqual(actual.location.z, z, delta=1e-5)
            self.assertAlmostEqual(math.degrees(actual.rotation_euler.z), yaw, delta=0.001)
        for frame in (3.999, 3.9998, 3.99999):
            self.assert_position(self.export(), frame, (0, 0, frame))

    def test_edited_jump_curve_does_not_export_stale_source(self):
        self.import_jump(True)
        curve = next(c for c in getActionFCurves(self.obj) if c.data_path == 'location' and c.array_index == 2)
        next(point for point in curve.keyframe_points if point.co.x == 4).co.y = 25
        self.assert_position(self.export(), 4, (0, 0, 25))

    def test_switching_action_invalidates_imported_jump(self):
        self.import_jump(True)
        self.obj.animation_data.action = None
        self.add_curve('location', 2, [(0, 2), (5, 7)])
        self.assert_position(self.export(), 4, (0, 0, 6))

    def test_modified_interpolation_invalidates_imported_jump(self):
        self.import_jump(True)
        curve = next(c for c in getActionFCurves(self.obj) if c.data_path == 'location' and c.array_index == 2)
        curve.keyframe_points[0].interpolation = 'CONSTANT'
        self.assert_position(self.export(), 2, (0, 0, 0))

    def test_imported_jump_respects_parent_scale_on_export(self):
        self.import_jump(True)
        self.root.scale = (4, 4, 4)
        self.assert_position(self.export(), 3.9998, (0, 0, 3.9998 * 4))

    def test_imported_jump_metadata_can_be_missing_or_invalid(self):
        self.import_jump(True)
        self.obj['_sith_key_jump'] = 'not json'
        self.assert_position(self.export(), 4, (0, 0, 10))

    def test_fractional_markers_roundtrip_move_and_duplicate(self):
        for named in (False, True):
            with self.subTest(named=named), tempfile.TemporaryDirectory() as directory:
                key = Key('markers.key')
                key.numFrames, key.numJoints, key.fps = 12, 1, 30
                node = KeyNode()
                node.idx, node.meshName = 0, 'joint'
                node.keyframes = [Keyframe()]
                key.nodes = [node]
                for frame in (-0.5, 2.1, 2.75, 5.5):
                    marker = KeyMarker()
                    marker.frame, marker.type = frame, KeyMarkerType.LeftFoot
                    key.markers.append(marker)
                path = Path(directory) / key.name
                saveKey(key, path, '')
                bpy.context.view_layer.objects.active = self.root
                importKey(path, self.scene, True, True, named)
                restored = _make_key_from_obj(key.name, self.root, self.scene)
                self.assertEqual([round(marker.frame, 8) for marker in restored.markers], [-0.5, 2.1, 2.75, 5.5])
                marker = list(self.scene.timeline_markers)[1]
                marker.frame += 3
                self.scene.timeline_markers.new(marker.name, frame=8)
                restored = _make_key_from_obj(key.name, self.root, self.scene)
                self.assertEqual([round(marker.frame, 8) for marker in restored.markers],
                                 [-0.5, 2.75, 5.1, 5.5, 8.1])

    def test_invalid_fractional_marker_name_is_not_silently_retimed(self):
        self.add_curve('location', 0, [(0, 0), (10, 1)])
        self.scene.timeline_markers.clear()
        for name in ('1@nan', '1@-0.1', '1@1.0', '1@junk'):
            self.scene.timeline_markers.new(name, frame=2)
        self.assertEqual(_make_key_from_obj('markers', self.root, self.scene).markers, [])

    def test_sparse_channels_evaluate_at_union_times(self):
        self.add_curve('location', 0, [(0, 0), (10, 10)])
        self.add_curve('location', 1, [(5, 5)])
        node = self.export()
        self.assert_position(node, 5, (5, 5, 0))
        self.assert_position(node, 2.5, (2.5, 5, 0))

    def test_unkeyed_components_keep_object_values(self):
        self.obj.location.y = 7
        self.obj.location.z = -3
        self.add_curve('location', 0, [(0, 1), (10, 2)])
        self.assert_position(self.export(), 5, (1.5, 7, -3))

    def test_keyed_zero_overrides_nonzero_default(self):
        self.add_curve('location', 1, [(0, 4), (5, 0), (10, 4)])
        self.obj.location.y = 99
        self.assert_position(self.export(), 5, (0, 0, 0))

    def test_constant_and_linear_axes_keep_step(self):
        self.add_curve('location', 0, [(0, 2), (10, 8)], 'CONSTANT')
        self.add_curve('location', 1, [(0, 0), (10, 10)])
        node = self.export()
        self.assert_position(node, 9.5, (2, 9.5, 0))
        self.assert_position(node, 10, (8, 10, 0))
        self.assertEqual(node.keyframes[0].deltaPosition.x, 0)

    def test_bezier_is_baked_to_curve_values(self):
        curve = self.add_curve('location', 0, [(0, 0), (10, 10)], 'BEZIER')
        curve.keyframe_points[0].handle_right_type = 'FREE'
        curve.keyframe_points[1].handle_left_type = 'FREE'
        curve.keyframe_points[0].handle_right = (10 / 3, 0)
        curve.keyframe_points[1].handle_left = (20 / 3, 10)
        curve.update()
        node = self.export()
        self.assertGreater(len(node.keyframes), 2)
        for frame in (0.125, 1.3, 2.5, 4.7, 6.25, 8.9, 9.99):
            self.assert_position(node, frame, (curve.evaluate(frame), 0, 0), 4.0e-5)

    def test_fractional_keys_are_not_truncated(self):
        self.add_curve('location', 0, [(0, 0), (0.25, 1), (0.75, -1), (10, 0)])
        node = self.export()
        self.assertIn(0.25, [entry.frame for entry in node.keyframes])
        self.assertIn(0.75, [entry.frame for entry in node.keyframes])
        self.assert_position(node, 0.5, (0, 0, 0))

    def test_quaternion_wrap_keeps_small_rotation(self):
        self.obj.rotation_mode = 'QUATERNION'
        first = makeQuaternionRotation((0, 179, 0))
        last = makeQuaternionRotation((0, 181, 0))
        if first.dot(last) < 0:
            last.negate()
        for axis in range(4):
            self.add_curve('rotation_quaternion', axis, [(0, first[axis]), (10, last[axis])])
        node = self.export()
        self.assert_rotation(node, 5, (0, 180, 0))
        self.assertLess(abs(node.keyframes[0].deltaRotation.y), 1)

    def test_negative_quaternion_wrap(self):
        self.obj.rotation_mode = 'QUATERNION'
        first = makeQuaternionRotation((0, -179, 0))
        last = makeQuaternionRotation((0, -181, 0))
        if first.dot(last) < 0:
            last.negate()
        for axis in range(4):
            self.add_curve('rotation_quaternion', axis, [(0, first[axis]), (10, last[axis])])
        self.assert_rotation(self.export(), 5, (0, -180, 0))

    def test_native_euler_preserves_two_full_turns(self):
        self.add_curve('rotation_euler', 2, [(0, 0), (10, 4 * math.pi)])
        node = self.export()
        self.assertAlmostEqual(node.keyframes[-1].orientation.y, 720, delta=0.001)
        self.assertAlmostEqual(sample_key(node, 2.5)[1][1], 180, delta=0.001)
        self.assertAlmostEqual(sample_key(node, 7.5)[1][1], 540, delta=0.001)

    def test_native_euler_preserves_negative_turns(self):
        self.add_curve('rotation_euler', 2, [(0, 0), (10, -4 * math.pi)])
        node = self.export()
        self.assertAlmostEqual(sample_key(node, 7.5)[1][1], -540, delta=0.001)

    def test_authored_long_quaternion_path_is_not_shortened(self):
        self.obj.rotation_mode = 'QUATERNION'
        first = makeQuaternionRotation((0, 179, 0))
        last = makeQuaternionRotation((0, -179, 0))
        if first.dot(last) > 0:
            last.negate()
        for axis in range(4):
            self.add_curve('rotation_quaternion', axis, [(0, first[axis]), (10, last[axis])])
        self.assert_rotation(self.export(), 5, (0, 0, 0))

    def test_different_euler_order_preserves_turns(self):
        self.obj.rotation_mode = 'XYZ'
        self.add_curve('rotation_euler', 2, [(0, 0), (10, 4 * math.pi)])
        node = self.export()
        self.assertAlmostEqual(node.keyframes[-1].orientation.y, 720, delta=0.01)
        for frame in (1.25, 3.75, 6.25, 8.75):
            self.assert_rotation(node, frame, (0, frame * 72, 0))

    def test_euler_singularity_keeps_pose_continuous(self):
        self.obj.rotation_mode = 'QUATERNION'
        first = makeQuaternionRotation((85, 30, 10))
        last = makeQuaternionRotation((95, 30, 10))
        for axis in range(4):
            self.add_curve('rotation_quaternion', axis, [(0, first[axis]), (10, last[axis])])
        node = self.export()
        for frame in (2.5, 5, 7.5):
            self.assert_rotation(node, frame, (85 + frame, 30, 10))

    def test_axis_angle_uses_angle_and_axis(self):
        self.obj.rotation_mode = 'AXIS_ANGLE'
        self.obj.rotation_axis_angle = (0, 0, 0, 1)
        self.add_curve('rotation_axis_angle', 0, [(0, 0), (10, math.pi / 2)])
        self.assert_rotation(self.export(), 5, (0, 45, 0))

    def test_zero_quaternion_is_rejected(self):
        self.obj.rotation_mode = 'QUATERNION'
        self.obj.rotation_quaternion = (0, 0, 0, 0)
        self.add_curve('rotation_quaternion', 1, [(0, 0), (10, 0)])
        with self.assertRaisesRegex(ValueError, 'zero-length'):
            self.export()

    def test_nonzero_angle_with_zero_axis_is_rejected(self):
        self.obj.rotation_mode = 'AXIS_ANGLE'
        self.obj.rotation_axis_angle = (1, 0, 0, 0)
        self.add_curve('rotation_axis_angle', 0, [(0, 1), (10, 2)])
        with self.assertRaisesRegex(ValueError, 'zero-length axis'):
            self.export()

    def test_muted_curves_do_not_override_defaults(self):
        muted = self.add_curve('location', 0, [(0, 10), (10, 20)])
        muted.mute = True
        self.obj.location.x = 3
        self.add_curve('location', 1, [(0, 1), (10, 2)])
        self.assert_position(self.export(), 5, (3, 1.5, 0))

    def test_parent_scale_and_pivot_convention(self):
        self.root.scale = (2, 3, 4)
        self.obj.scale = (9, 9, 9)
        self.add_curve('location', 0, [(0, 1), (10, 2)])
        self.assert_position(self.export(), 5, (3, 0, 0))

    def test_pivot_offset_is_removed_from_animation_location(self):
        pivot = self.obj.constraints.new('PIVOT')
        pivot.offset = (0.25, -0.5, 1)
        self.add_curve('location', 0, [(0, 1), (10, 2)])
        self.assert_position(self.export(), 5, (1.75, -0.5, 1))

    def test_rapid_full_turns_do_not_alias(self):
        self.obj.rotation_mode = 'XYZ'
        self.add_curve('rotation_euler', 2, [(0, 0), (1, 8 * math.pi)])
        self.scene.frame_end = 1
        node = self.export()
        self.assertAlmostEqual(sample_key(node, 0.125)[1][1], 180, delta=0.01)
        self.assertAlmostEqual(sample_key(node, 0.875)[1][1], 1260, delta=0.01)

    def test_identity_axis_angle_can_have_zero_axis(self):
        self.obj.rotation_mode = 'AXIS_ANGLE'
        self.obj.rotation_axis_angle = (0, 0, 0, 0)
        self.add_curve('rotation_axis_angle', 0, [(0, 0), (10, 0)])
        self.assert_rotation(self.export(), 5, (0, 0, 0))

    def test_repeated_export_is_deterministic(self):
        self.add_curve('location', 0, [(0, 2), (5, 0), (10, 2)])
        first = self.export()
        second = self.export()
        self.assertEqual([(e.frame, e.position, e.orientation, e.deltaPosition, e.deltaRotation, e.flags) for e in first.keyframes],
                         [(e.frame, e.position, e.orientation, e.deltaPosition, e.deltaRotation, e.flags) for e in second.keyframes])

    def test_bezier_survives_serialization(self):
        curve = self.add_curve('location', 0, [(0, 0), (10, 10)], 'BEZIER')
        key = Key('curved.key')
        key.numJoints = 1
        key.numFrames = 11
        key.fps = 30
        key.nodes = [self.export()]
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / key.name
            saveKey(key, filename, '')
            node = loadKey(filename).nodes[0]
        for frame in (0.2, 2.25, 4.75, 7.3, 9.8):
            self.assert_position(node, frame, (curve.evaluate(frame), 0, 0), 4.0e-5)

    def test_frame_zero_is_generated_for_late_first_key(self):
        self.add_curve('location', 0, [(5, 2), (10, 4)])
        node = self.export()
        self.assertEqual(node.keyframes[0].frame, 0)
        self.assert_position(node, 0, (2, 0, 0))

    def test_long_linear_track_survives_serialization(self):
        self.scene.frame_end = 10000
        curve = self.add_curve('location', 0, [(0, 0), (10000, 1.23456789)])
        key = Key('long.key')
        key.numJoints, key.numFrames, key.fps = 1, 10001, 30
        key.nodes = [self.export()]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / key.name
            saveKey(key, path, '')
            node = loadKey(path).nodes[0]
        for frame in (0, 0.5, 2500, 5000, 9999.5, 10000):
            # The old fixed-decimal slope drifted past the baking tolerance.
            self.assert_position(node, frame, (curve.evaluate(frame), 0, 0), 1e-6)

    def test_export_handles_representable_slope_between_large_endpoints(self):
        self.scene.frame_end = 4
        self.scene.timeline_markers.clear()
        self.scene.sith_key_flags, self.scene.sith_key_types = set(), 'ffff'
        setSceneFrameRate(self.scene, 30)
        self.add_curve('location', 0, [(0, -3e38), (4, 3e38)])
        bpy.context.view_layer.objects.active = self.obj
        self.obj.select_set(True)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'large.key'
            path.write_bytes(b'previous valid export')
            self.assertEqual(bpy.ops.export_anim.sith_key(filepath=str(path)), {'FINISHED'})
            key = loadKey(path)

        # Their float32 difference overflows, but the per-frame slope does not.
        first, last = key.nodes[0].keyframes
        expected = (last.position.x - first.position.x) / (last.frame - first.frame)
        self.assertTrue(math.isfinite(first.deltaPosition.x))
        self.assertEqual(first.deltaPosition.x, expected)
        self.assertEqual(sample_key(key.nodes[0], 2)[0][0], 0)

    def test_unrepresentable_export_slope_preserves_existing_file_and_scene(self):
        self.scene.frame_end = 1
        self.scene.timeline_markers.clear()
        self.scene.sith_key_flags, self.scene.sith_key_types = set(), 'ffff'
        setSceneFrameRate(self.scene, 30)
        self.add_curve('location', 0, [(0, -3e38), (1, 3e38)])
        bpy.context.view_layer.objects.active = self.obj
        self.obj.select_set(True)
        # Inserting keys leaves the last assigned RNA value until evaluation.
        self.scene.frame_set(0)
        before = (tuple(self.obj.location), self.scene.frame_current, getSceneFrameRate(self.scene),
                  set(self.scene.sith_key_flags), self.scene.sith_key_types)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'safe.key'
            path.write_bytes(b'previous valid export')
            with self.assertRaisesRegex(RuntimeError, 'float32'):
                bpy.ops.export_anim.sith_key(filepath=str(path))
            self.assertEqual(path.read_bytes(), b'previous valid export')
        self.assertEqual((tuple(self.obj.location), self.scene.frame_current, getSceneFrameRate(self.scene),
                          set(self.scene.sith_key_flags), self.scene.sith_key_types), before)

    def test_unanimated_object_is_omitted(self):
        self.assertIsNone(self.export())

    def test_sampled_fcurves_are_supported(self):
        curve = self.add_curve('location', 0, [(0, 0), (10, 10)])
        curve.convert_to_samples(0, 10)
        self.assert_position(self.export(), 4.5, (4.5, 0, 0))

    def test_export_does_not_change_scene_or_object_pose(self):
        self.add_curve('location', 0, [(0, 1), (10, 3)])
        self.scene.frame_set(7, subframe=0.25)
        before = (self.scene.frame_current, self.scene.frame_subframe, tuple(self.obj.location))
        self.export()
        self.assertEqual(before, (self.scene.frame_current, self.scene.frame_subframe, tuple(self.obj.location)))

    def test_unbaked_constraints_are_rejected(self):
        self.obj.constraints.new('COPY_LOCATION')
        with self.assertRaisesRegex(ValueError, 'constraints'):
            self.export()

    def test_transform_drivers_are_rejected(self):
        self.obj.driver_add('location', 0)
        with self.assertRaisesRegex(ValueError, 'drivers'):
            self.export()

    def test_unbaked_nla_is_rejected(self):
        self.add_curve('location', 0, [(0, 0), (10, 10)])
        track = self.obj.animation_data.nla_tracks.new()
        track.strips.new('clip', 0, self.obj.animation_data.action)
        with self.assertRaisesRegex(ValueError, 'NLA'):
            self.export()

    def test_overlapping_layer_channels_are_rejected(self):
        curve = self.add_curve('location', 0, [(0, 1), (10, 2)])
        with mock.patch('sith.key.keyExporter.getActionFCurves', return_value=[curve, curve]):
            with self.assertRaisesRegex(ValueError, 'layered'):
                self.export()

    def test_rotation_path_must_match_object_mode(self):
        self.add_curve('rotation_quaternion', 0, [(0, 1), (10, 0)])
        self.assertIsNone(self.export())

    def test_serialized_key_matches_sampled_animation(self):
        self.add_curve('rotation_euler', 2, [(0, math.radians(170)), (10, math.radians(190))])
        node = self.export()
        key = Key('synthetic.key')
        key.nodes = [node]
        key.numJoints = 1
        key.numFrames = 11
        key.fps = 30000 / 1001
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / key.name
            saveKey(key, filename, 'Synthetic regression fixture')
            restored = loadKey(filename)
        self.assertAlmostEqual(restored.fps, key.fps, delta=1.0e-6)
        self.assert_rotation(restored.nodes[0], 5, (0, 180, 0))

    def test_import_preserves_winding_holds_and_linear_positions(self):
        bpy.context.view_layer.objects.active = self.obj
        importKey(TV / 'winding_and_holds.key', self.scene, True, True, True)
        self.assertEqual(self.obj.rotation_mode, kImEulerOrder)
        self.assertEqual(self.scene.sith_key_types, 'FFFF')
        for frame, x, yaw in ((5, 5, 360), (12, 10, 720), (15, 20, 720)):
            self.scene.frame_set(frame)
            self.assertAlmostEqual(self.obj.location.x, x, delta=1.0e-5)
            self.assertAlmostEqual(math.degrees(self.obj.rotation_euler.z), yaw, delta=0.001)
        self.assertAlmostEqual(getSceneFrameRate(self.scene), 30000 / 1001, delta=1.0e-5)
        node = self.export()
        self.assertAlmostEqual(sample_key(node, 5)[1][1], 360, delta=0.001)
        self.assert_position(node, 12, (10, 0, 0))
        self.assert_position(node, 15, (20, 0, 0))

    def test_full_export_keeps_joint_number_and_effective_fps(self):
        self.add_curve('location', 0, [(0, 1), (10, 2)])
        self.scene.render.fps = 30
        self.scene.render.fps_base = 1.001
        key = _make_key_from_obj('synthetic.key', self.root, self.scene)
        self.assertEqual(key.numJoints, 1)
        self.assertEqual(key.nodes[0].idx, 0)
        self.assertAlmostEqual(key.fps, getSceneFrameRate(self.scene), delta=1.0e-9)

    def test_static_joint_omission_does_not_renumber_animated_joint(self):
        other = bpy.data.objects.new('static_joint', None)
        self.scene.collection.objects.link(other)
        other.parent = self.root
        other.sith_model3do_hnode_idx = 0
        self.obj.sith_model3do_hnode_idx = 1
        self.add_curve('location', 0, [(0, 1), (10, 2)])
        key = _make_key_from_obj('joints.key', self.root, self.scene)
        self.assertEqual(key.numJoints, 2)
        self.assertEqual([node.idx for node in key.nodes], [1])

    def test_import_and_export_keep_the_final_fractional_interval(self):
        key = Key('tail.key')
        key.numJoints = 1
        key.numFrames = 11
        key.fps = 30
        node = KeyNode()
        node.meshName = 'joint'
        entry = Keyframe()
        entry.flags = KeyframeFlag.AllChange
        entry.deltaPosition = Vector3f(1, 0, 0)
        entry.deltaRotation = Vector3f(0, 9, 0)
        node.keyframes = [entry]
        key.nodes = [node]
        bpy.context.view_layer.objects.active = self.obj
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / key.name
            saveKey(key, filename, '')
            importKey(filename, self.scene, True, True, False)
        exported = self.export()
        self.assert_position(exported, 10.5, (10.5, 0, 0))
        self.assert_rotation(exported, 10.5, (0, 94.5, 0))


class ImportSampleTests(unittest.TestCase):
    def test_unrepresentably_close_jump_is_rejected(self):
        node = KeyNode()
        first, last = Keyframe(), Keyframe()
        first.flags = KeyframeFlag.PositionChange
        first.deltaPosition = Vector3f(1, 0, 0)
        last.frame, last.position = 0.0001, Vector3f(10, 0, 0)
        node.keyframes = [first, last]
        with self.assertRaisesRegex(ValueError, 'precision'):
            _make_import_samples(node, 1)

    def test_import_rejects_duplicate_frame_times(self):
        node = KeyNode()
        node.keyframes = [Keyframe(), Keyframe()]
        with self.assertRaisesRegex(ValueError, 'increasing'):
            _make_import_samples(node, 10)

    def test_import_rejects_negative_frame_times(self):
        node = KeyNode()
        entry = Keyframe()
        entry.frame = -1
        node.keyframes = [entry]
        with self.assertRaisesRegex(ValueError, 'nonnegative'):
            _make_import_samples(node, 10)

    def test_import_rejects_nonfinite_transforms(self):
        for value in (math.inf, math.nan):
            node = KeyNode()
            entry = Keyframe()
            entry.orientation = Vector3f(value, 0, 0)
            node.keyframes = [entry]
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'finite'):
                _make_import_samples(node, 10)

    def test_import_retains_moving_segment_before_discontinuity(self):
        node = KeyNode()
        first, last = Keyframe(), Keyframe()
        first.flags = KeyframeFlag.AllChange
        first.deltaPosition = Vector3f(1, 0, 0)
        first.deltaRotation = Vector3f(0, 10, 0)
        last.frame = 10
        last.position = Vector3f(30, 0, 0)
        last.orientation = Vector3f(0, 200, 0)
        node.keyframes = [first, last]
        samples = _make_import_samples(node, 10)
        self.assertEqual(len(samples), 3)
        self.assertAlmostEqual(samples[1].position.x, samples[1].frame)
        self.assertAlmostEqual(samples[1].orientation.y, samples[1].frame * 10)
        self.assertEqual(samples[1].flags, KeyframeFlag.NoChange)

    def test_deltas_are_per_frame_not_per_second(self):
        first, last = Keyframe(), Keyframe()
        first.frame = 0.5
        last.frame = 2.5
        last.position = Vector3f(4, 0, 0)
        _set_keyframe_delta(first, last, KeyframeFlag.PositionChange)
        self.assertEqual(first.deltaPosition.x, 2)

    def test_large_position_and_rotation_deltas_use_wide_intermediates(self):
        for flag, attribute, deltaAttribute in (
            (KeyframeFlag.PositionChange, 'position', 'deltaPosition'),
            (KeyframeFlag.OrientationChange, 'orientation', 'deltaRotation')
        ):
            with self.subTest(flag=flag):
                first, last = Keyframe(), Keyframe()
                last.frame = 4
                setattr(first, attribute, Vector3f(-3e38, 3e38, 0))
                setattr(last, attribute, Vector3f(3e38, -3e38, 0))
                _set_keyframe_delta(first, last, flag)
                self.assertEqual(getattr(first, deltaAttribute), (1.5e38, -1.5e38, 0))
                self.assertEqual(first.flags, flag)

    def test_unrepresentable_delta_is_rejected_without_changing_entry(self):
        for flag, attribute in ((KeyframeFlag.PositionChange, 'position'),
                                (KeyframeFlag.OrientationChange, 'orientation')):
            with self.subTest(flag=flag):
                first, last = Keyframe(), Keyframe()
                last.frame = 1
                setattr(first, attribute, Vector3f(-3e38, 0, 0))
                setattr(last, attribute, Vector3f(3e38, 0, 0))
                with self.assertRaisesRegex(ValueError, 'float32'):
                    _set_keyframe_delta(first, last, flag)
                self.assertEqual(first.flags, KeyframeFlag.NoChange)
                self.assertEqual(first.deltaPosition, (0, 0, 0))
                self.assertEqual(first.deltaRotation, (0, 0, 0))


class TimingTests(unittest.TestCase):
    def test_fractional_fps_values(self):
        for fps in (15, 24, 24000 / 1001, 30000 / 1001, 59.94, 60):
            with self.subTest(fps=fps):
                setSceneFrameRate(bpy.context.scene, fps)
                self.assertAlmostEqual(getSceneFrameRate(bpy.context.scene), fps, delta=1.0e-5)

    def test_invalid_fps_is_rejected(self):
        for fps in (0, -1, math.inf, math.nan):
            with self.subTest(fps=fps), self.assertRaises(ValueError):
                setSceneFrameRate(bpy.context.scene, fps)

    def test_invalid_fps_base_is_rejected(self):
        for base in (0, -1, math.inf, math.nan):
            scene = SimpleNamespace(render=SimpleNamespace(fps=30, fps_base=base))
            with self.subTest(base=base), self.assertRaises(ValueError):
                getSceneFrameRate(scene)
