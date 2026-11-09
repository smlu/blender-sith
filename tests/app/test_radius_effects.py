"""Radius helpers obey geometry checks without changing authored bounds."""
from pathlib import Path
import tempfile

import bpy
import bmesh

from app.support import SceneTestCase
from fixtures import TV
from sith.key.keyExporter import exportKey
from sith.key.keyLoader import loadKey
from sith.model.model3doExporter import export3do
from sith.model.model3doImporter import import3do
from sith.model.model3doLoader import load3do, Model3doFileVersion
from sith.model.utils import (getModelRadiusObj, getMeshRadiusObj, isRadiusObj,
                              kModel3doRadius, kModel3doRadiusKind, kModelRadius)


class RadiusEffectTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def load_helper(self, kind):
        self.clear_data()
        self.root = import3do(TV / 'model/shared_mesh.3do', importRadiusObj=True, clearScene=False)
        self.owner = next(obj for obj in self.root.children_recursive if obj.type == 'MESH' and not isRadiusObj(obj))
        helper = getModelRadiusObj(self.root) if kind == 'model' else getMeshRadiusObj(None, self.owner)
        helper.hide_viewport = False
        return helper

    def export_radius(self, kind):
        path = self.folder / (kind + '.3do')
        export3do(self.root, str(path), Model3doFileVersion.Version2_3, False, False, True)
        model = load3do(path)[0]
        if kind == 'model':
            return model.radius
        node = model.meshHierarchy[self.owner.sith_model3do_hnode_idx]
        return model.geosets[0].meshes[node.meshIdx].radius

    def reject(self, helper, message):
        path = self.folder / 'rejected.3do'
        path.write_bytes(b'previous valid export')
        before = (helper[kModel3doRadius], helper.instance_type, helper.parent_type,
                  tuple(helper.scale), [tuple(vertex.co) for vertex in helper.data.vertices])
        with self.assertRaisesRegex(ValueError, message):
            export3do(self.root, str(path), Model3doFileVersion.Version2_3, False, False, True)
        self.assertEqual(path.read_bytes(), b'previous valid export')
        self.assertEqual(before, (helper[kModel3doRadius], helper.instance_type, helper.parent_type,
                                  tuple(helper.scale), [tuple(vertex.co) for vertex in helper.data.vertices]))

    def shape_key(self, helper, value=1):
        helper.shape_key_add(name='Basis')
        shape = helper.shape_key_add(name='Expanded')
        for point in shape.data:
            point.co *= 2
        shape.value = value
        return shape

    def test_active_constraints_on_model_and_mesh_helpers_require_applying(self):
        for kind in ('model', 'mesh'):
            with self.subTest(kind=kind):
                helper = self.load_helper(kind)
                control = bpy.data.objects.new('scale_control', None)
                bpy.context.scene.collection.objects.link(control)
                control.scale = (2, 2, 2)
                helper.constraints.new('COPY_SCALE').target = control
                bpy.context.view_layer.update()
                self.reject(helper, 'constraints on radius helper')

    def test_pivot_constraint_on_a_helper_is_not_mistaken_for_a_joint_pivot(self):
        helper = self.load_helper('model')
        helper.constraints.new('PIVOT').offset = (1, 0, 0)
        self.reject(helper, 'constraints on radius helper')

    def test_muted_or_zero_influence_constraints_do_not_change_authored_radius(self):
        for kind in ('model', 'mesh'):
            for mute, influence in ((True, 1), (False, 0)):
                with self.subTest(kind=kind, mute=mute, influence=influence):
                    helper = self.load_helper(kind)
                    constraint = helper.constraints.new('COPY_SCALE')
                    constraint.mute, constraint.influence = mute, influence
                    self.assertEqual(self.export_radius(kind), helper[kModel3doRadius])

    def test_visible_helper_modifiers_require_applying(self):
        for kind in ('model', 'mesh'):
            with self.subTest(kind=kind):
                helper = self.load_helper(kind)
                helper.modifiers.new('Displace', 'DISPLACE').strength = 2
                self.reject(helper, 'visible mesh modifiers')

    def test_hidden_helper_modifiers_preserve_original_bounds(self):
        for kind in ('model', 'mesh'):
            with self.subTest(kind=kind):
                helper = self.load_helper(kind)
                helper.modifiers.new('Hidden Displace', 'DISPLACE').show_viewport = False
                self.assertEqual(self.export_radius(kind), helper[kModel3doRadius])

    def test_hidden_helper_still_rejects_an_enabled_geometry_effect(self):
        helper = self.load_helper('model')
        helper.hide_viewport = True
        helper.modifiers.new('Displace', 'DISPLACE')
        self.reject(helper, 'visible mesh modifiers')

    def test_active_helper_shape_keys_require_baking(self):
        for kind in ('model', 'mesh'):
            with self.subTest(kind=kind):
                helper = self.load_helper(kind)
                self.shape_key(helper)
                self.reject(helper, 'shape-key deformation')

    def test_zero_weight_or_muted_relative_keys_are_harmless(self):
        for kind in ('model', 'mesh'):
            for mute, value in ((False, 0), (True, 1)):
                with self.subTest(kind=kind, mute=mute, value=value):
                    helper = self.load_helper(kind)
                    self.shape_key(helper, value).mute = mute
                    self.assertEqual(self.export_radius(kind), helper[kModel3doRadius])

    def test_pinned_helper_shape_key_requires_baking_even_with_zero_weight(self):
        helper = self.load_helper('model')
        self.shape_key(helper, 0)
        helper.show_only_shape_key, helper.active_shape_key_index = True, 1
        self.reject(helper, 'shape-key deformation')

    def test_absolute_helper_shape_keys_require_baking(self):
        helper = self.load_helper('mesh')
        self.shape_key(helper, 0)
        helper.data.shape_keys.use_relative = False
        self.reject(helper, 'shape-key deformation')

    def test_basis_only_helper_shape_key_is_harmless(self):
        helper = self.load_helper('model')
        helper.shape_key_add(name='Basis')
        self.assertEqual(self.export_radius('model'), helper[kModel3doRadius])

    def test_helper_instancing_is_rejected(self):
        helper = self.load_helper('model')
        helper.instance_type = 'VERTS'
        self.reject(helper, 'instancing')

    def test_vertex_parented_helper_is_rejected(self):
        helper = self.load_helper('mesh')
        helper.parent_type, helper.parent_vertices = 'VERTEX', (1, 0, 0)
        self.reject(helper, 'parenting on radius helper')

    def test_nonmesh_helper_reports_a_clear_error(self):
        helper = self.load_helper('model')
        bpy.data.objects.remove(helper, do_unlink=True)
        empty = bpy.data.objects.new('empty_bound', None)
        bpy.context.scene.collection.objects.link(empty)
        empty.parent = self.root
        empty[kModel3doRadiusKind] = kModelRadius
        path = self.folder / 'empty.3do'
        path.write_bytes(b'previous valid export')
        with self.assertRaisesRegex(ValueError, 'Radius helper.*must be a mesh'):
            export3do(self.root, str(path), Model3doFileVersion.Version2_3, False, False, True)
        self.assertEqual(path.read_bytes(), b'previous valid export')

    def test_direct_scaling_and_applied_mesh_edits_remain_supported(self):
        for kind in ('model', 'mesh'):
            for method in ('scale', 'mesh'):
                with self.subTest(kind=kind, method=method):
                    helper = self.load_helper(kind)
                    if method == 'scale':
                        helper.scale = (2, 2, 2)
                    else:
                        for vertex in helper.data.vertices:
                            vertex.co *= 2
                    self.assertAlmostEqual(self.export_radius(kind), helper[kModel3doRadius] * 2, places=5)

    def test_key_export_does_not_inspect_geometry_only_radius_effects(self):
        helper = self.load_helper('model')
        helper.constraints.new('COPY_SCALE')
        helper.modifiers.new('Displace', 'DISPLACE')
        self.shape_key(helper)
        helper.instance_type = 'VERTS'
        self.owner.keyframe_insert(data_path='location', frame=0)
        scene = bpy.context.scene
        scene.frame_start, scene.frame_end = 0, 4
        scene.render.fps, scene.render.fps_base = 30, 1
        scene.timeline_markers.clear()
        scene.sith_key_flags, scene.sith_key_types = set(), 'ffff'
        path = self.folder / 'bounds.key'
        exportKey(self.root, scene, str(path))
        key = loadKey(path)
        self.assertEqual((key.numJoints, len(key.nodes)), (3, 1))

    def test_live_edit_mode_changes_are_measured_without_leaving_edit_mode(self):
        for kind in ('model', 'mesh'):
            with self.subTest(kind=kind):
                helper = self.load_helper(kind)
                bpy.context.view_layer.update()
                for obj in bpy.context.selected_objects:
                    obj.select_set(False)
                bpy.context.view_layer.objects.active = helper
                helper.select_set(True)
                bpy.ops.object.mode_set(mode='EDIT')
                try:
                    bm = bmesh.from_edit_mesh(helper.data)
                    for vertex in bm.verts:
                        vertex.co *= 2
                    self.assertAlmostEqual(self.export_radius(kind), helper[kModel3doRadius] * 2, places=5)
                    self.assertEqual(helper.mode, 'EDIT')
                finally:
                    bpy.ops.object.mode_set(mode='OBJECT')
