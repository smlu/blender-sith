"""Pivot helpers show native pivots in the viewport and follow the engine's joint frames."""
import math

import bpy
import mathutils

from app.test_native_pivots import NativePivotFixture
from sith.key import Key, KeyNode, Keyframe, KeyframeFlag
from sith.key.keyImporter import importKey
from sith.key.keyExporter import _make_key_from_obj
from sith.key.keyWriter import saveKey
from sith.model import utils
from sith.types import Vector3f


def engine_rotation(pyr):
    # Sith joints rotate by yaw (Z), then pitch (X), then roll (Y).
    pitch, yaw, roll = (math.radians(value) for value in pyr)
    return (mathutils.Matrix.Rotation(yaw, 4, 'Z') @ mathutils.Matrix.Rotation(pitch, 4, 'X')
            @ mathutils.Matrix.Rotation(roll, 4, 'Y'))


def engine_joint_frames(model, poses):
    """Independent rdThing_AccumulateMatrices: parent · T(-parentPivot) · J · T(pivot)."""
    frames = {}
    for node in sorted(model.meshHierarchy, key=lambda n: n.idx):
        position, pyr = poses.get(node.idx, (node.position, node.rotation))
        joint = mathutils.Matrix.Translation(position) @ engine_rotation(pyr)
        if node.parentIdx >= 0:
            parent = model.meshHierarchy[node.parentIdx]
            placement = frames[node.parentIdx] @ mathutils.Matrix.Translation(-mathutils.Vector(parent.pivot))
        else:
            # Blender-Sith places the model wrapper at INSERT OFFSET.
            placement = mathutils.Matrix.Translation(model.insertOffset)
        frames[node.idx] = placement @ joint @ mathutils.Matrix.Translation(node.pivot)
    return frames


def key_pose(keyframes, time):
    """Engine KEY sampling: the last entry at or before time, advanced by its deltas."""
    entry = max((k for k in keyframes if k.frame <= time), key=lambda k: k.frame)
    elapsed = time - entry.frame
    position = mathutils.Vector(entry.position) + mathutils.Vector(entry.deltaPosition) * elapsed
    pyr = mathutils.Vector(entry.orientation) + mathutils.Vector(entry.deltaRotation) * elapsed
    return position, pyr


def keyframe(frame, position, orientation, dpos=(0, 0, 0), drot=(0, 0, 0)):
    value = Keyframe()
    value.flags = KeyframeFlag.AllChange
    value.frame = frame
    value.position, value.orientation = Vector3f(*position), Vector3f(*orientation)
    value.deltaPosition, value.deltaRotation = Vector3f(*dpos), Vector3f(*drot)
    return value


class PivotHelperTests(NativePivotFixture):
    def setUp(self):
        super().setUp()
        # Pivots on both the mesh-less root and its mesh child exercise the
        # engine's parent-pivot cancellation as well as the mesh offset.
        self.model.meshHierarchy[0].pivot = Vector3f(0.05, -0.1, 0.02)
        self.model.meshHierarchy[1].pivot = Vector3f(0.125, 0.03, -0.04)
        self.model.meshHierarchy[1].rotation = Vector3f(5.0, -15.0, 25.0)

    def helper(self, index):
        return utils.getPivotHelperObj(self.node_object(index))

    def assert_matrix(self, actual, expected, tolerance=2e-5):
        for row in range(4):
            self.assert_vector(actual[row], expected[row], tolerance)

    def test_import_option_creates_one_helper_per_joint_at_its_pivot(self):
        self.import_model()
        self.assertFalse(any(utils.isPivotHelperObj(obj) for obj in bpy.data.objects))
        self.clear_data()
        self.import_model(importPivotHelpers=True)
        for node in self.model.meshHierarchy:
            helper = self.helper(node.idx)
            self.assertIsNotNone(helper)
            self.assert_vector(helper.location, node.pivot)
            self.assert_vector(self.node_object(node.idx).sith_model3do_pivot, node.pivot)

    def test_key_playback_and_attachments_match_engine_joint_frames(self):
        self.import_model(importPivotHelpers=True)
        attached = bpy.data.objects.new('attached', None)
        bpy.context.scene.collection.objects.link(attached)
        attached.parent = self.helper(1)
        attached.location = (0.2, -0.1, 0.05)

        key, tracks = Key('pivot-playback.key'), []
        key.numJoints, key.numFrames, key.fps = 2, 5, 30
        for idx, name, keyframes in (
            (0, 'root', [keyframe(0, (0.1, 0.2, 0.3), (10, 20, 30), dpos=(0.01, 0, -0.02), drot=(2, -1, 3)),
                         keyframe(3, (0.0, 0.4, 0.1), (-20, 45, 5))]),
            (1, 'head', [keyframe(0, (0.0, 0.0, 0.5), (5, -15, 25), drot=(-4, 6, 2)),
                         keyframe(2, (0.1, -0.2, 0.6), (30, 10, -40), dpos=(0.02, 0.01, 0))])):
            node = KeyNode()
            node.idx, node.meshName, node.keyframes = idx, name, keyframes
            tracks.append(node)
        key.nodes = tracks
        path = self.path.with_suffix('.key')
        saveKey(key, path, '')

        # Helpers are not joints: a two-joint KEY still maps by index.
        bpy.context.view_layer.objects.active = self.root
        importKey(str(path), bpy.context.scene, False, True, False)

        for time in range(5):
            with self.subTest(frame=time):
                bpy.context.scene.frame_set(time)
                bpy.context.view_layer.update()
                frames = engine_joint_frames(self.model, {node.idx: key_pose(node.keyframes, time) for node in key.nodes})
                for node in self.model.meshHierarchy:
                    # The helper is the engine's attachment frame for that joint.
                    self.assert_matrix(self.helper(node.idx).matrix_world, frames[node.idx])
                    if node.meshIdx >= 0:
                        obj = self.node_object(node.idx)
                        native = self.model.geosets[0].meshes[node.meshIdx].vertices
                        for vertex, source in zip(obj.data.vertices, native):
                            self.assert_vector(obj.matrix_world @ vertex.co, frames[node.idx] @ mathutils.Vector(source))
                self.assert_vector(attached.matrix_world.translation, frames[1] @ mathutils.Vector((0.2, -0.1, 0.05)))

    def test_moving_a_helper_sets_the_exported_pivot_without_adding_joints(self):
        self.import_model(importPivotHelpers=True)
        self.helper(1).location = (0.3, 0.1, -0.2)
        self.assert_vector(self.node_object(1).sith_model3do_pivot, (0.3, 0.1, -0.2))
        exported = self.export_model()
        self.assertEqual(len(exported.meshHierarchy), 2)
        self.assert_vector(exported.meshHierarchy[1].pivot, (0.3, 0.1, -0.2))
        self.assert_vector(exported.meshHierarchy[0].pivot, self.model.meshHierarchy[0].pivot)
        self.assert_surface_matches_scene(exported)

        bpy.context.scene.frame_set(0)
        animation = _make_key_from_obj('helpers.key', self.root, bpy.context.scene)
        self.assertEqual(animation.numJoints, 2)

    def test_numeric_field_and_toggle_keep_one_value(self):
        self.import_model()
        obj = self.node_object(1)
        bpy.context.view_layer.objects.active = obj
        self.assertEqual(bpy.ops.object.sith_toggle_pivot_helper(), {'FINISHED'})
        helper = utils.getPivotHelperObj(obj)
        self.assert_vector(helper.location, self.model.meshHierarchy[1].pivot)

        obj.sith_model3do_pivot = (1.0, 2.0, 3.0)
        self.assert_vector(helper.location, (1.0, 2.0, 3.0))

        # A Ctrl+P parent inverse is part of the helper's placement.
        helper.matrix_parent_inverse = mathutils.Matrix.Translation((0.5, 0.0, -0.5))
        helper.location = (0.0, 0.0, 0.0)
        self.assert_vector(obj.sith_model3do_pivot, (0.5, 0.0, -0.5))
        obj.sith_model3do_pivot = (0.25, 0.25, 0.25)
        bpy.context.view_layer.update()
        self.assert_vector((obj.matrix_world.inverted() @ helper.matrix_world).translation, (0.25, 0.25, 0.25))

        # Removing the helper keeps its current value as the stored pivot.
        helper.matrix_parent_inverse.identity()
        helper.location = (-0.75, 0.5, 0.125)
        self.assertEqual(bpy.ops.object.sith_toggle_pivot_helper(), {'FINISHED'})
        self.assertIsNone(utils.getPivotHelperObj(obj))
        self.assertFalse(any(utils.isPivotHelperObj(other) for other in bpy.data.objects))
        self.assert_vector(obj.sith_model3do_pivot, (-0.75, 0.5, 0.125))
        self.assert_vector(self.export_model().meshHierarchy[1].pivot, (-0.75, 0.5, 0.125))

    def test_invalid_helpers_are_rejected_before_export(self):
        self.import_model(importPivotHelpers=True)
        obj = self.node_object(1)
        second = bpy.data.objects.new('second', None)
        bpy.context.scene.collection.objects.link(second)
        second[utils.kModel3doPivotHelper] = True
        second.parent = obj
        with self.assertRaisesRegex(ValueError, 'Multiple pivot helpers'):
            self.export_model()
        bpy.data.objects.remove(second)

        constraint = self.helper(1).constraints.new('COPY_LOCATION')
        with self.assertRaisesRegex(ValueError, 'Apply active constraints on pivot helper'):
            self.export_model()
        constraint.mute = True
        self.export_model()
