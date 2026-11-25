# SPDX-License-Identifier: GPL-3.0-or-later
"""Exported KEY entries keep the Euler triple nearest the previous sample."""
import math
from types import SimpleNamespace

import bpy

from app.support import SceneTestCase
from sith.key.keyEuler import nearestEuler
from sith.key.keyExporter import _sample_key_node
from sith.key.keyUtils import getActionFCurves
from sith.model.utils import kImEulerOrder, makeQuaternionRotation


def stored_steps(node):
    """(start, end) triples the engine interpolates: each segment, then each entry boundary."""
    entries = node.keyframes
    for previous, current in zip(entries, entries[1:]):
        start = tuple(previous.orientation)
        span = current.frame - previous.frame
        end = start
        if int(previous.flags) & 2:
            end = tuple(a + d * span for a, d in zip(start, previous.deltaRotation))
        yield start, end
        yield end, tuple(current.orientation)


class EulerContinuityTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        self.scene = bpy.context.scene
        self.scene.frame_start, self.scene.frame_end = 0, 10
        self.root = bpy.data.objects.new('root', None)
        self.obj = bpy.data.objects.new('joint', None)
        for obj in (self.root, self.obj):
            self.scene.collection.objects.link(obj)
        self.obj.parent = self.root
        self.obj.sith_model3do_hnode_idx = 0
        self.obj.sith_model3do_hnode_name = 'joint'

    def key_quaternions(self, first, last):
        self.obj.rotation_mode = 'QUATERNION'
        a, b = makeQuaternionRotation(first), makeQuaternionRotation(last)
        if a.dot(b) < 0:
            b.negate()
        for frame, value in ((0, a), (10, b)):
            self.obj.rotation_quaternion = value
            self.obj.keyframe_insert(data_path='rotation_quaternion', frame=frame)
        for curve in getActionFCurves(self.obj):
            for point in curve.keyframe_points:
                point.interpolation = 'LINEAR'
            curve.update()

    def export(self):
        return _sample_key_node(SimpleNamespace(obj=self.obj, idx=0, name='joint'), self.root,
                                self.scene.frame_end)

    def test_quaternion_into_pitch_minus_90_keeps_the_nearest_triple(self):
        # Blender converts the end pose, at pitch exactly -90, with yaw 0 and the turn in roll.
        # Before the fix the last segment swung yaw and roll by about 145 degrees each.
        self.key_quaternions((5, -115, 157), (-90, -115, -3))
        node = self.export()
        for start, end in stored_steps(node):
            nearest = nearestEuler(start, end)
            stored = max(abs(b - a) for a, b in zip(start, end))
            needed = max(abs(b - a) for a, b in zip(start, nearest))
            self.assertLessEqual(stored, needed + 1e-6, (start, end, nearest))
        for frame in (0, 2.5, 5, 7.5, 9.9, 10):
            with self.subTest(frame=frame):
                self.scene.frame_set(math.floor(frame), subframe=frame % 1)
                expected = self.obj.matrix_local.to_quaternion()
                index = max(i for i, e in enumerate(node.keyframes) if e.frame <= frame)
                entry = node.keyframes[index]
                pyr = [v + (d * (frame - entry.frame) if int(entry.flags) & 2 else 0)
                       for v, d in zip(entry.orientation, entry.deltaRotation)]
                d = expected.rotation_difference(makeQuaternionRotation(pyr))
                error = math.degrees(2 * math.atan2(math.sqrt(d.x * d.x + d.y * d.y + d.z * d.z), abs(d.w)))
                self.assertLessEqual(error, 0.055)

    def test_native_euler_keeps_an_authored_long_turn(self):
        # Euler-authored YXZ channels are written as authored, including the long way round.
        self.obj.rotation_mode = kImEulerOrder
        for frame, yaw in ((0, 170), (10, -170)):
            self.obj.rotation_euler = (0.0, 0.0, math.radians(yaw))
            self.obj.keyframe_insert(data_path='rotation_euler', index=2, frame=frame)
        for curve in getActionFCurves(self.obj):
            for point in curve.keyframe_points:
                point.interpolation = 'LINEAR'
        node = self.export()
        self.assertAlmostEqual(node.keyframes[0].orientation[1], 170.0, places=4)
        self.assertAlmostEqual(node.keyframes[0].deltaRotation[1], -34.0, places=4)
