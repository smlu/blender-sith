"""KEY export must not silently ignore animated or driven constraint settings."""
import math
from pathlib import Path
import tempfile

import bpy

from app.support import SceneTestCase
from sith.key.keyExporter import exportKey
from sith.key.keyLoader import loadKey
from sith.key.keyUtils import getActionFCurves
from sith.model.utils import kImEulerOrder


class ConstraintAnimationTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'constraint.key'
        self.scene = bpy.context.scene
        self.scene.frame_start, self.scene.frame_end = 0, 4
        self.scene.render.fps, self.scene.render.fps_base = 30, 1
        self.scene.timeline_markers.clear()
        self.scene.sith_key_flags, self.scene.sith_key_types = set(), 'ffff'
        mesh = bpy.data.meshes.new('joint')
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        self.obj = bpy.data.objects.new('joint', mesh)
        self.scene.collection.objects.link(self.obj)
        self.obj.rotation_mode = kImEulerOrder
        self.obj.rotation_euler.z = math.pi / 2
        for frame in (0, 4):
            self.obj.keyframe_insert(data_path='location', frame=frame)
            self.obj.keyframe_insert(data_path='rotation_euler', frame=frame)
        self.scene.frame_set(0)

    def pivot(self, owner=None):
        owner = self.obj if owner is None else owner
        constraint = owner.constraints.new('PIVOT')
        constraint.rotation_range, constraint.use_relative_location = 'ALWAYS_ACTIVE', True
        constraint.offset = (1, 0, 0)
        return constraint

    def copy_location(self):
        control = bpy.data.objects.new('control', None)
        self.scene.collection.objects.link(control)
        control.location.x = 5
        constraint = self.obj.constraints.new('COPY_LOCATION')
        constraint.target = control
        return constraint

    def animate(self, constraint, path, first, last):
        for frame, value in ((0, first), (4, last)):
            setattr(constraint, path, value)
            constraint.keyframe_insert(data_path=path, frame=frame)
        self.scene.frame_set(0)
        bpy.context.view_layer.update()

    def reject(self, root=None):
        # A rejected export must retain the previous file and all scene timing,
        # transforms, action bindings and channel data, not just raise an error.
        self.path.write_bytes(b'previous valid export')
        before = (self.scene.frame_current, self.scene.render.fps, self.scene.render.fps_base,
                  tuple(self.obj.location), tuple(self.obj.rotation_euler),
                  [(c.data_path, [(tuple(p.co), p.interpolation) for p in c.keyframe_points])
                   for c in getActionFCurves(self.obj)], len(bpy.data.actions))
        with self.assertRaisesRegex(ValueError, 'animated or driven constraint'):
            exportKey(self.obj if root is None else root, self.scene, str(self.path))
        self.assertEqual(self.path.read_bytes(), b'previous valid export')
        self.assertEqual(before, (self.scene.frame_current, self.scene.render.fps, self.scene.render.fps_base,
                                 tuple(self.obj.location), tuple(self.obj.rotation_euler),
                                 [(c.data_path, [(tuple(p.co), p.interpolation) for p in c.keyframe_points])
                                  for c in getActionFCurves(self.obj)], len(bpy.data.actions)))

    def accept(self):
        exportKey(self.obj, self.scene, str(self.path))
        return loadKey(self.path)

    def test_animated_pivot_offset_rejects_before_writing(self):
        self.animate(self.pivot(), 'offset', (1, 0, 0), (2, 0, 0))
        self.reject()

    def test_zero_initial_influence_does_not_hide_later_constraint_motion(self):
        self.animate(self.copy_location(), 'influence', 0, 1)
        self.reject()

    def test_constraint_rejection_is_independent_of_current_frame(self):
        self.animate(self.copy_location(), 'influence', 0, 1)
        for frame in (0, 2, 4):
            self.scene.frame_set(frame)
            with self.subTest(frame=frame):
                self.reject()

    def test_driven_pivot_offset_requires_baking(self):
        self.pivot().driver_add('offset', 0).driver.expression = '1 + frame / 4'
        self.scene.frame_set(0)
        self.reject()

    def test_zero_initial_driven_influence_requires_baking(self):
        self.copy_location().driver_add('influence').driver.expression = 'frame / 4'
        self.scene.frame_set(0)
        self.reject()

    def test_animated_mute_can_activate_a_currently_disabled_constraint(self):
        self.animate(self.copy_location(), 'mute', True, False)
        self.reject()

    def test_constraint_only_animation_is_not_silently_exported_as_empty(self):
        self.obj.animation_data_clear()
        self.animate(self.pivot(), 'offset', (1, 0, 0), (2, 0, 0))
        self.reject()

    def test_wrapper_constraint_animation_requires_baking(self):
        wrapper = bpy.data.objects.new('wrapper', None)
        self.scene.collection.objects.link(wrapper)
        self.obj.parent = wrapper
        self.animate(self.pivot(wrapper), 'offset', (1, 0, 0), (2, 0, 0))
        self.reject(wrapper)

    def test_constraint_names_use_escaped_rna_paths(self):
        constraint = self.pivot()
        constraint.name = 'Pivot "quoted" [brackets]'
        self.animate(constraint, 'offset', (1, 0, 0), (2, 0, 0))
        self.reject()

    def test_permanently_muted_constraint_allows_irrelevant_offset_animation(self):
        constraint = self.pivot()
        constraint.mute = True
        self.animate(constraint, 'offset', (1, 0, 0), (2, 0, 0))
        self.assertEqual(len(self.accept().nodes), 1)

    def test_permanently_zero_influence_allows_irrelevant_offset_animation(self):
        constraint = self.pivot()
        constraint.influence = 0
        self.animate(constraint, 'offset', (1, 0, 0), (2, 0, 0))
        self.assertEqual(len(self.accept().nodes), 1)

    def test_constant_mute_gate_can_disable_animated_influence(self):
        constraint = self.copy_location()
        constraint.mute = True
        self.animate(constraint, 'influence', 0, 1)
        self.assertEqual(len(self.accept().nodes), 1)

    def test_constant_zero_influence_can_disable_animated_mute(self):
        constraint = self.copy_location()
        constraint.influence = 0
        self.animate(constraint, 'mute', True, False)
        self.assertEqual(len(self.accept().nodes), 1)

    def test_muted_constraint_channel_does_not_block_static_pivot(self):
        constraint = self.pivot()
        self.animate(constraint, 'offset', (1, 0, 0), (2, 0, 0))
        prefix = constraint.path_from_id() + '.'
        for curve in getActionFCurves(self.obj):
            if curve.data_path.startswith(prefix):
                curve.mute = True
        self.obj.animation_data.action.update_tag()
        self.assertEqual(len(self.accept().nodes), 1)

    def test_muted_constraint_driver_does_not_block_static_pivot(self):
        driver = self.pivot().driver_add('offset', 0)
        driver.driver.expression, driver.mute = '1 + frame / 4', True
        self.assertEqual(len(self.accept().nodes), 1)

    def test_static_pivot_and_unrelated_property_animation_stay_supported(self):
        self.pivot()
        self.obj['control'] = 1.0
        for frame in (0, 4):
            self.obj.keyframe_insert(data_path='["control"]', frame=frame)
        self.assertEqual(len(self.accept().nodes), 1)
