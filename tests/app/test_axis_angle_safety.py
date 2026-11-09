"""Axis normalization must not hide rotations between ordinary bake probes."""
import math
from pathlib import Path
import tempfile

import bpy

from app.support import SceneTestCase
from batch.app import key_pose
from sith.key.keyExporter import exportKey
from sith.key.keyLoader import loadKey
from sith.key.keyUtils import getActionFCurves
from sith.model.utils import makeQuaternionRotation


class AxisAngleSafetyTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'axis.key'
        self.scene = bpy.context.scene
        self.scene.frame_start, self.scene.frame_end = 0, 1
        self.scene.render.fps, self.scene.render.fps_base = 30, 1
        self.scene.timeline_markers.clear()
        self.scene.sith_key_flags, self.scene.sith_key_types = set(), 'ffff'
        self.root = bpy.data.objects.new('wrapper', None)
        self.obj = bpy.data.objects.new('joint', None)
        for obj in (self.root, self.obj):
            self.scene.collection.objects.link(obj)
        self.obj.parent, self.obj.rotation_mode = self.root, 'AXIS_ANGLE'

    def keys(self, epsilon=1e-6, mode='LINEAR'):
        for frame, y in ((0, -0.375), (1, 0.625)):
            self.obj.rotation_axis_angle = (math.pi, epsilon, y, 0)
            self.obj.keyframe_insert(data_path='rotation_axis_angle', frame=frame)
        for curve in getActionFCurves(self.obj):
            for point in curve.keyframe_points:
                point.interpolation = mode
        self.scene.frame_set(0)
        return next(c for c in getActionFCurves(self.obj) if c.array_index == 2)

    def assert_poses(self, key, frames):
        # Compare serialized KEY poses with Blender's evaluated transform, not
        # with another implementation of axis normalization in the test.
        for frame in frames:
            with self.subTest(frame=frame):
                self.scene.frame_set(math.floor(frame), subframe=frame % 1)
                actual = self.obj.matrix_local.to_quaternion()
                _, angles = key_pose(key.nodes[0], frame)
                difference = actual.rotation_difference(makeQuaternionRotation(angles))
                error = math.degrees(2 * math.atan2(math.sqrt(sum(v * v for v in difference[1:])), abs(difference[0])))
                self.assertLessEqual(error, 0.055)

    def assert_export_or_safe_rejection(self, frames):
        self.path.write_bytes(b'previous valid export')
        try:
            exportKey(self.root, self.scene, str(self.path))
        except ValueError as error:
            self.assertRegex(str(error), 'Cannot bake animation|zero-length axis')
            self.assertEqual(self.path.read_bytes(), b'previous valid export')
            return
        self.assert_poses(loadKey(self.path), frames)

    def test_near_zero_axis_turn_is_retained_or_safely_rejected(self):
        self.keys()
        self.assert_export_or_safe_rejection((0, 0.25, 0.3749, 0.375, 0.3751, 0.5, 1))

    def test_representable_axis_turn_matches_dense_evaluated_poses(self):
        self.keys(epsilon=0.1)
        exportKey(self.root, self.scene, str(self.path))
        self.assert_poses(loadKey(self.path), [i / 200 for i in range(201)] + [0.375])

    def test_bezier_axis_crossing_is_retained_or_safely_rejected(self):
        curve = self.keys()
        a, b = curve.keyframe_points
        a.interpolation = 'BEZIER'
        a.handle_right_type, b.handle_left_type = 'FREE', 'FREE'
        a.handle_right, b.handle_left = (1 / 3, 0.625), (2 / 3, 0.625)
        curve.update()
        crossing = 1 - 0.625 ** (1 / 3)
        self.assert_export_or_safe_rejection((0, crossing - 1e-4, crossing, crossing + 1e-4, 0.5, 1))

    def test_exact_zero_axis_inside_interval_rejects_before_overwriting(self):
        self.keys(epsilon=0)
        self.path.write_bytes(b'previous valid export')
        with self.assertRaisesRegex(ValueError, 'zero-length axis'):
            exportKey(self.root, self.scene, str(self.path))
        self.assertEqual(self.path.read_bytes(), b'previous valid export')

    def test_constant_axis_sign_jump_preserves_held_poses(self):
        self.keys(epsilon=0, mode='CONSTANT')
        exportKey(self.root, self.scene, str(self.path))
        self.assert_poses(loadKey(self.path), (0, 0.375, 0.99, 1))

    def test_unsupported_axis_easing_rejects_before_overwriting(self):
        self.keys(epsilon=0.1, mode='SINE')
        self.path.write_bytes(b'previous valid export')
        with self.assertRaisesRegex(ValueError, 'Bake axis-angle easing curves'):
            exportKey(self.root, self.scene, str(self.path))
        self.assertEqual(self.path.read_bytes(), b'previous valid export')

    def test_linear_axis_extrapolation_cannot_hide_a_turn(self):
        curve = self.keys()
        for point, frame, value in zip(curve.keyframe_points, (10, 20), (9.625, 19.625)):
            point.co = (frame, value)
        curve.extrapolation = 'LINEAR'
        curve.update()
        self.assert_export_or_safe_rejection((0, 0.3749, 0.375, 0.3751, 1))

    def test_sampled_axis_curve_cannot_hide_a_turn(self):
        curve = self.keys()
        # Blender's conversion excludes the end frame, so include both samples
        # explicitly and invalidate its cached evaluation of the former keys.
        curve.convert_to_samples(start=0, end=2)
        self.obj.animation_data.action.update_tag()
        self.assertEqual(len(curve.sampled_points), 2)
        self.assert_export_or_safe_rejection((0, 0.3749, 0.375, 0.3751, 1))

    def test_zero_angle_can_pass_through_a_zero_axis(self):
        self.keys(epsilon=0)
        angle = next(c for c in getActionFCurves(self.obj) if c.array_index == 0)
        for point in angle.keyframe_points:
            point.co[1] = 0
        angle.update()
        exportKey(self.root, self.scene, str(self.path))
        self.assert_poses(loadKey(self.path), (0, 0.375, 0.5, 1))
