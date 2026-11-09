"""Quaternion turns must be retained or rejected before replacing an export."""
import math
from pathlib import Path
import tempfile

import bpy
import mathutils

from app.support import SceneTestCase
from batch.app import key_pose
from sith.key.keyExporter import exportKey, _rotation_curve_times
from sith.key.keyLoader import loadKey
from sith.key.keyUtils import getActionFCurves
from sith.model.utils import makeQuaternionRotation


class QuaternionSafetyTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'rotation.key'
        self.scene = bpy.context.scene
        self.scene.frame_start, self.scene.frame_end = 0, 4
        self.scene.render.fps, self.scene.render.fps_base = 30, 1
        self.scene.timeline_markers.clear()
        self.scene.sith_key_flags, self.scene.sith_key_types = set(), 'ffff'
        self.root = bpy.data.objects.new('wrapper', None)
        self.obj = bpy.data.objects.new('joint', None)
        for obj in (self.root, self.obj):
            self.scene.collection.objects.link(obj)
        self.obj.parent, self.obj.rotation_mode = self.root, 'QUATERNION'

    def keys(self, first, last, mode='LINEAR'):
        for frame, value in ((0, first), (4, last)):
            self.obj.rotation_quaternion = value
            self.obj.keyframe_insert(data_path='rotation_quaternion', frame=frame)
        for curve in getActionFCurves(self.obj):
            for point in curve.keyframe_points:
                point.interpolation = mode
        self.scene.frame_set(0)
        return next(c for c in getActionFCurves(self.obj) if c.array_index == 0)

    def assert_export_or_safe_rejection(self, frames):
        # The extremely narrow turns may exceed the bounded bake depth. An
        # explicit error is valid; silently writing the old identity pose is not.
        self.path.write_bytes(b'previous valid export')
        try:
            exportKey(self.root, self.scene, str(self.path))
        except ValueError as error:
            self.assertRegex(str(error), 'Cannot bake animation|zero-length animation quaternion')
            self.assertEqual(self.path.read_bytes(), b'previous valid export')
            return
        self.assert_poses(loadKey(self.path), frames)

    def assert_poses(self, key, frames):
        for frame in frames:
            with self.subTest(frame=frame):
                self.scene.frame_set(math.floor(frame), subframe=frame % 1)
                actual = self.obj.matrix_local.to_quaternion()
                _, angles = key_pose(key.nodes[0], frame)
                difference = actual.rotation_difference(makeQuaternionRotation(angles))
                error = math.degrees(2 * math.atan2(math.sqrt(sum(v * v for v in difference[1:])), abs(difference[0])))
                self.assertLessEqual(error, 0.055)

    def test_linear_near_zero_quaternion_cannot_disappear_between_probes(self):
        self.keys((-0.125, 1e-6, 0, 0), (0.875, 1e-6, 0, 0))
        self.assert_export_or_safe_rejection((0, 0.4999, 0.5, 0.5001, 1, 4))

    def test_unit_endpoint_bezier_turn_cannot_disappear(self):
        first = mathutils.Quaternion((-1, 5e-5, 0, 0)).normalized()
        last = mathutils.Quaternion((1, 5e-5, 0, 0)).normalized()
        curve = self.keys(first, last)
        a, b = curve.keyframe_points
        a.interpolation = 'BEZIER'
        a.handle_right_type, b.handle_left_type = 'FREE', 'FREE'
        a.handle_right, b.handle_left = (4 / 3, 1), (8 / 3, 1)
        curve.update()
        critical = 4 * (1 - 0.5 ** (1 / 3))
        self.assertTrue(any(abs(frame - critical) < 1e-5 for frame in _rotation_curve_times(curve, 5)))
        self.assert_export_or_safe_rejection((0, critical - 1e-4, critical, critical + 1e-4, 1, 4))

    def test_two_crossings_inside_one_quarter_interval_are_seeded(self):
        curve = self.keys((0.02, 1e-6, 0, 0), (0.72, 1e-6, 0, 0))
        a, b = curve.keyframe_points
        a.interpolation = 'BEZIER'
        a.handle_right_type, b.handle_left_type = 'FREE', 'FREE'
        a.handle_right, b.handle_left = (4 / 3, -0.08), (8 / 3, 0.1533333333333333)
        curve.update()
        times = _rotation_curve_times(curve, 5)
        for expected in (0.4, 0.6, 0.8):
            self.assertTrue(any(abs(frame - expected) < 2e-6 for frame in times), (expected, times))
        self.assert_export_or_safe_rejection((0.4, 0.6, 0.8, 1, 4))

    def test_overlong_bezier_handles_match_blender_zero_time(self):
        curve = self.keys((-1, 0.1, 0, 0), (1, 0.1, 0, 0))
        a, b = curve.keyframe_points
        a.interpolation = 'BEZIER'
        a.handle_right_type, b.handle_left_type = 'FREE', 'FREE'
        a.handle_right, b.handle_left = (40, 4), (-36, -4)
        curve.update()
        times = _rotation_curve_times(curve, 5)
        self.assertTrue(any(abs(frame - 2) < 2e-5 for frame in times))
        self.assertAlmostEqual(curve.evaluate(2), 0, delta=2e-5)

    def test_representable_bezier_turn_preserves_dense_evaluated_poses(self):
        curve = self.keys((-1, 0.1, 0, 0), (1, 0.1, 0, 0))
        a, b = curve.keyframe_points
        a.interpolation = 'BEZIER'
        a.handle_right_type, b.handle_left_type = 'FREE', 'FREE'
        a.handle_right, b.handle_left = (4 / 3, 1), (8 / 3, 1)
        curve.update()
        exportKey(self.root, self.scene, str(self.path))
        self.assert_poses(loadKey(self.path), [i / 50 for i in range(201)] + [4 * (1 - 0.5 ** (1 / 3))])

    def test_held_quaternion_sign_change_has_no_false_zero_crossing(self):
        curve = self.keys((1, 0, 0, 0), (-1, 0, 0, 0), mode='CONSTANT')
        self.assertEqual(_rotation_curve_times(curve, 5), set())
        exportKey(self.root, self.scene, str(self.path))
        self.assert_poses(loadKey(self.path), (0, 1, 3.9, 4))

    def test_linear_extrapolation_seeds_zero_inside_exported_range(self):
        curve = self.keys((1, 0.1, 0, 0), (2, 0.1, 0, 0))
        # Move the authored keys beyond the playback window. Their linear
        # extrapolation still crosses zero at frame 1 and must be sampled.
        for point, frame, value in zip(curve.keyframe_points, (10, 20), (9, 19)):
            point.co = (frame, value)
        curve.extrapolation = 'LINEAR'
        curve.update()
        self.assertIn(1.0, _rotation_curve_times(curve, 5))

    def test_unsupported_quaternion_easing_rejects_before_overwriting_file(self):
        self.keys((1, 0, 0, 0), (0.5, 0.5, 0, 0), mode='SINE')
        self.path.write_bytes(b'previous valid export')
        with self.assertRaisesRegex(ValueError, 'Bake quaternion easing curves'):
            exportKey(self.root, self.scene, str(self.path))
        self.assertEqual(self.path.read_bytes(), b'previous valid export')
