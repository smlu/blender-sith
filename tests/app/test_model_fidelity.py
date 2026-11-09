"""Rendering invariants: valid normals/bounds and lossless editable mesh data."""
import math
from pathlib import Path
import tempfile

import bpy
import bmesh
import mathutils

from app.support import SceneTestCase
from fixtures import TV
from sith.model.model3do import GeometryMode
from sith.model.model3doLoader import load3do, Model3doFileVersion
from sith.model.model3doWriter import save3do
from sith.model.model3doImporter import import3do
from sith.model.model3doExporter import makeModel3doFromObj, _get_mat_name
from sith.model import utils
from sith.key.keyExporter import _make_key_from_obj


class ModelFidelityTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'model.3do'
        self.model, _ = load3do(TV / 'model/triangle.3do')

    def import_model(self, version=Model3doFileVersion.Version2_3, **options):
        save3do(self.model, self.path, version, '')
        self.root = import3do(self.path, clearScene=False, **options)
        self.obj = next(obj for obj in bpy.data.objects if obj.sith_model3do_hnode_idx == 1)
        return self.root

    def export_model(self, **options):
        return makeModel3doFromObj('model.3do', self.root, exportVertexColors=True, **options)

    def authored_hierarchy(self, sequences):
        self.root = bpy.data.objects.new('model', None)
        bpy.context.scene.collection.objects.link(self.root)
        objects = []
        for name, sequence in zip(('root', 'left', 'right'), sequences):
            mesh = bpy.data.meshes.new(name)
            mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
            obj = bpy.data.objects.new(name, mesh)
            obj.sith_model3do_hnode_idx = sequence
            obj.sith_model3do_hnode_name = name
            obj.parent = objects[0] if objects else self.root
            bpy.context.scene.collection.objects.link(obj)
            objects.append(obj)
        return objects

    def assert_rotation_matches_blender(self, node, obj):
        actual = utils.makeRotationMatrix(*node.rotation)
        expected = obj.matrix_basis.to_3x3()
        for row in range(3):
            self.assert_vector(actual[row], expected[row])

    def test_axis_angle_quarter_turn_round_trip(self):
        obj = self.authored_hierarchy((0, 1, 2))[0]
        obj.rotation_mode = 'AXIS_ANGLE'
        obj.rotation_axis_angle = (math.pi / 2, 0, 0, 1)
        bpy.context.view_layer.update()

        # Passing (angle, x, y, z) as quaternion components turned 90 into 64.96 degrees.
        save3do(self.export_model(), self.path, Model3doFileVersion.Version2_3, '')
        restored, _ = load3do(self.path)
        self.assert_vector(restored.meshHierarchy[0].rotation, (0, 90, 0), 1e-4)
        self.assert_rotation_matches_blender(restored.meshHierarchy[0], obj)

    def test_axis_angle_matches_blender(self):
        obj = self.authored_hierarchy((0, 1, 2))[0]
        obj.rotation_mode = 'AXIS_ANGLE'
        for axis in ((1, 0, 0), (0, 1, 0), (0, 0, 1), (0.2, 0.7, -0.3), (2, 7, -3)):
            for angle in (0, -0.7, math.pi / 2, math.pi - 1e-4, math.pi, 2 * math.pi, 2 * math.pi + 0.3, -4 * math.pi - 0.2):
                with self.subTest(axis=axis, angle=angle):
                    obj.rotation_axis_angle = (angle, *axis)
                    bpy.context.view_layer.update()
                    self.assert_rotation_matches_blender(self.export_model().meshHierarchy[0], obj)

    def test_axis_angle_identity_allows_zero_axis(self):
        obj = self.authored_hierarchy((0, 1, 2))[0]
        obj.rotation_mode = 'AXIS_ANGLE'
        obj.rotation_axis_angle = (0, 0, 0, 0)
        bpy.context.view_layer.update()
        node = self.export_model().meshHierarchy[0]
        self.assert_vector(node.rotation, (0, 0, 0))
        self.assert_rotation_matches_blender(node, obj)

    def test_axis_angle_rejects_nonzero_angle_without_axis(self):
        obj = self.authored_hierarchy((0, 1, 2))[0]
        obj.rotation_mode = 'AXIS_ANGLE'
        for angle in (0.5, -math.pi):
            with self.subTest(angle=angle):
                obj.rotation_axis_angle = (angle, 0, 0, 0)
                with self.assertRaisesRegex(ValueError, 'zero-length axis'):
                    self.export_model()

    def test_axis_angle_rejects_nonfinite_values(self):
        obj = self.authored_hierarchy((0, 1, 2))[0]
        obj.rotation_mode = 'AXIS_ANGLE'
        # RNA clamps infinities to finite float limits, but NaN remains nonfinite.
        for component in range(4):
            with self.subTest(component=component):
                rotation = [0.8, 0.2, 0.7, -0.3]
                rotation[component] = math.nan
                obj.rotation_axis_angle = rotation
                with self.assertRaisesRegex(ValueError, 'finite'):
                    self.export_model()

    def test_axis_angle_preserves_child_world_transform(self):
        parent, child, _ = self.authored_hierarchy((0, 1, 2))
        parent.rotation_mode = child.rotation_mode = 'AXIS_ANGLE'
        parent.rotation_axis_angle = (0.8, 0.2, 0.7, -0.3)
        parent.location = (0.1, 0.2, -0.3)
        child.rotation_axis_angle = (-0.6, 0.4, -0.2, 0.5)
        child.location = (0.4, -0.2, 0.7)
        bpy.context.view_layer.update()
        model = self.export_model()
        self.assertEqual(model.meshHierarchy[1].parentIdx, 0)

        # Rebuild the exported hierarchy and compare against Blender's live world matrix.
        matrices = []
        for node in model.meshHierarchy[:2]:
            matrix = utils.makeRotationMatrix(*node.rotation).to_4x4()
            matrix.translation = node.position
            matrices.append(matrix)
        actual = matrices[0] @ matrices[1]
        for row in range(4):
            self.assert_vector(actual[row], child.matrix_world[row])

    def test_other_rotation_modes_match_blender(self):
        obj = self.authored_hierarchy((0, 1, 2))[0]
        for mode in ('XYZ', 'XZY', 'YXZ', 'YZX', 'ZXY', 'ZYX', 'QUATERNION'):
            with self.subTest(mode=mode):
                obj.rotation_mode = mode
                if mode == 'QUATERNION':
                    obj.rotation_quaternion = mathutils.Quaternion((0.2, 0.7, -0.3), 0.8)
                else:
                    obj.rotation_euler = (0.3, -0.7, 1.1)
                bpy.context.view_layer.update()
                self.assert_rotation_matches_blender(self.export_model().meshHierarchy[0], obj)

    def test_numbered_node_and_mesh_ids_with_both_sync_modes(self):
        self.authored_hierarchy((0, 2, 1))
        for sync in (False, True):
            with self.subTest(sync=sync):
                model = self.export_model(sync_mesh_list=sync)
                self.assertEqual([node.name for node in model.meshHierarchy], ['root', 'right', 'left'])
                self.assertEqual([node.idx for node in model.meshHierarchy], [0, 1, 2])
                self.assertEqual([node.parentIdx for node in model.meshHierarchy], [-1, 0, 0])
                self.assertEqual([node.meshIdx for node in model.meshHierarchy], [0, 1, 2] if sync else [0, 2, 1])
                self.assertEqual([mesh.name for mesh in model.geosets[0].meshes], ['root', 'right', 'left'] if sync else ['root', 'left', 'right'])

    def test_automatic_root_keeps_original_node_and_mesh_ids(self):
        self.authored_hierarchy((-1, 0, 1))
        for sync in (False, True):
            with self.subTest(sync=sync):
                model = self.export_model(sync_mesh_list=sync)
                self.assertEqual([node.name for node in model.meshHierarchy], ['root', 'left', 'right'])
                self.assertEqual([node.meshIdx for node in model.meshHierarchy], [0, 1, 2])
                self.assertEqual([node.parentIdx for node in model.meshHierarchy], [-1, 0, 0])
                self.assertEqual(model.meshHierarchy[0].numChildren, 2)
                self.assertEqual(model.meshHierarchy[0].firstChildIdx, 1)
                self.assertEqual(model.meshHierarchy[1].siblingIdx, 2)

    def test_automatic_root_keeps_animation_joint_numbers(self):
        objects = self.authored_hierarchy((-1, 0, 1))
        objects[2].keyframe_insert('location', frame=0)
        objects[2].location.x = 2
        objects[2].keyframe_insert('location', frame=5)
        bpy.context.scene.frame_end = 5
        key = _make_key_from_obj('numbering.key', self.root, bpy.context.scene)
        self.assertEqual(key.numJoints, 3)
        self.assertEqual([(node.idx, node.meshName) for node in key.nodes], [(2, 'right')])

    def test_model_export_rejects_multiple_roots(self):
        objects = self.authored_hierarchy((0, 1, 2))
        objects[2].parent = self.root
        with self.assertRaisesRegex(ValueError, 'exactly one root'):
            self.export_model()

    def test_material_names_keep_internal_dots_and_blender_suffixes(self):
        for name, expected in (('rock_.5mblend_frnt.mat', 'rock_.5mblend_frnt.mat'),
                               ('panel.v2.mat.001', 'panel.v2.mat'),
                               ('panel.v2', 'panel.v2.mat')):
            material = bpy.data.materials.new(name)
            self.assertEqual(_get_mat_name(material), expected)
        self.model.materials[0] = 'rock_.5mblend_frnt.mat'
        self.import_model()
        exported = self.export_model()
        self.assertEqual(exported.materials[exported.geosets[0].meshes[0].faces[0].materialIdx], 'rock_.5mblend_frnt.mat')

    def test_missing_image_keeps_legacy_material_and_pixel_uvs(self):
        self.model.geosets[0].meshes[0].uvs = [(0, 0), (64, 0), (0, 32)]
        self.import_model(Model3doFileVersion.Version2_1)
        exported = self.export_model(uvAbsolute=True)
        mesh = exported.geosets[0].meshes[0]
        self.assertEqual(mesh.uvs, [(0, 0), (64, 0), (0, 32)])
        self.assertEqual(exported.materials[mesh.faces[0].materialIdx], 'checker.mat')
        with self.assertRaisesRegex(ValueError, 'texture image'):
            self.export_model(uvAbsolute=False)

    def test_missing_image_does_not_guess_normalized_to_pixel_units(self):
        self.import_model()
        with self.assertRaisesRegex(ValueError, 'texture image'):
            self.export_model(uvAbsolute=True)

    def test_later_image_does_not_rescale_already_pixel_sized_uvs(self):
        self.model.geosets[0].meshes[0].uvs = [(0, 0), (64, 0), (0, 32)]
        self.import_model(Model3doFileVersion.Version2_1)
        material = self.obj.data.materials[0]
        material.use_nodes = True
        material.node_tree.nodes.new('ShaderNodeTexImage').image = bpy.data.images.new('checker', width=64, height=32)
        absolute = self.export_model(uvAbsolute=True).geosets[0].meshes[0]
        relative = self.export_model(uvAbsolute=False).geosets[0].meshes[0]
        self.assertEqual(absolute.uvs, [(0, 0), (64, 0), (0, 32)])
        self.assertEqual(relative.uvs, [(0, 0), (1, 0), (0, 1)])

    def test_signed_hdr_colors_survive_import_and_export(self):
        expected = [(-3, 6, 0.25, 1), (8, -0.5, 2, 0.5), (0.125, 0.25, 0.5, 0.25)]
        self.model.geosets[0].meshes[0].vertexColors = expected
        self.import_model()
        self.assertEqual(self.obj.data.color_attributes.active_color.data_type, 'FLOAT_COLOR')
        actual = self.export_model().geosets[0].meshes[0].vertexColors
        for left, right in zip(actual, expected):
            self.assert_vector(left, right)

    def test_active_point_float_color_is_exported(self):
        self.import_model()
        colors = self.obj.data.color_attributes.new('point_color', 'FLOAT_COLOR', 'POINT')
        # Scalar RNA color assignment clamps negative components; bulk storage
        # accepts the signed float data that the engine and importer support.
        colors.data.foreach_set('color', [-2, 4, 0.5, 1] * len(colors.data))
        self.obj.data.color_attributes.active_color = colors
        for color in self.export_model().geosets[0].meshes[0].vertexColors:
            self.assert_vector(color, (-2, 4, 0.5, 1))

    def test_active_byte_corner_color_remains_supported(self):
        self.import_model()
        colors = self.obj.data.color_attributes.new('byte_color', 'BYTE_COLOR', 'CORNER')
        for color in colors.data:
            color.color = (0.25, 0.5, 1, 1)
        self.obj.data.color_attributes.active_color = colors
        for color in self.export_model().geosets[0].meshes[0].vertexColors:
            self.assert_vector(color, (0.25, 0.5, 1, 1), 0.005)

    def test_all_mesh_geometry_modes_are_independent_of_viewport(self):
        self.import_model()
        for mode in GeometryMode:
            with self.subTest(mode=mode):
                setattr(self.obj, utils.kModel3doGeometryMode, mode.name)
                self.obj.display_type = 'BOUNDS'
                self.assertEqual(self.export_model().geosets[0].meshes[0].geometryMode, mode)

    def test_vertex_only_import_does_not_become_wireframe(self):
        self.model.geosets[0].meshes[0].geometryMode = GeometryMode.VertexOnly
        self.import_model()
        self.assertEqual(self.obj.display_type, 'WIRE')
        self.assertEqual(self.export_model().geosets[0].meshes[0].geometryMode, GeometryMode.VertexOnly)

    def test_invalid_uvs_are_rejected_not_replaced_with_fabricated_data(self):
        for index in (-1, 3, 999):
            self.model.geosets[0].meshes[0].faces[0].uvIdxs[0] = index
            with self.subTest(index=index), self.assertRaisesRegex(ValueError, 'Invalid texture vertex'):
                self.import_model()
            self.clear_data()

    def test_correct_geometric_normals_replace_bad_source_normals(self):
        mesh = self.model.geosets[0].meshes[0]
        mesh.faces[0].normal = (1, 0, 0)
        mesh.faces[0].type = 0
        mesh.normals = [(1, 0, 0)] * 3
        self.import_model()
        exported = self.export_model().geosets[0].meshes[0]
        normal = mathutils.Vector(exported.faces[0].normal)
        self.assert_vector(normal, (0, 0, 1))
        camera_direction = mathutils.Vector((0, 0, 1))
        # rdModel3's single-sided culling must accept this front-facing triangle.
        self.assertLessEqual(mathutils.Vector(mesh.faces[0].normal).dot(camera_direction), 0)
        self.assertGreater(normal.dot(camera_direction), 0)

    def test_nonuniform_and_mirrored_scale_keep_normals_and_winding_consistent(self):
        self.model.geosets[0].meshes[0].vertices = [(0, 0, 0), (1, 0, 1), (0, 1, 0)]
        self.import_model()
        for scale in ((1, 1, 1), (2, 2, 2), (-2, -2, -2), (2, 3, 0.5), (-2, 3, 0.5), (2, 3, 0), (-2, 3, 0)):
            with self.subTest(scale=scale):
                self.obj.scale = scale
                mesh = self.export_model().geosets[0].meshes[0]
                face = mesh.faces[0]
                points = [mathutils.Vector(mesh.vertices[index]) for index in face.vertexIdxs]
                geometric = (points[1] - points[0]).cross(points[2] - points[0]).normalized()
                self.assert_vector(face.normal, geometric)
                for normal in mesh.normals:
                    self.assert_vector(normal, geometric)

    def test_valid_exact_radius_is_retained_without_sphere_rounding(self):
        self.model.radius = self.model.geosets[0].meshes[0].radius = 35.551701
        self.import_model(importRadiusObj=True)
        exported = self.export_model()
        self.assertEqual(exported.radius, 35.551701)
        self.assertEqual(exported.geosets[0].meshes[0].radius, 35.551701)

    def test_radius_helpers_follow_scale_and_vertex_edits(self):
        self.model.radius = self.model.geosets[0].meshes[0].radius = 10
        self.import_model(importRadiusObj=True)
        helper = utils.getModelRadiusObj(self.root)
        helper.scale = (2, 1, 1)
        self.assertEqual(self.export_model().radius, 20)
        helper.scale = (1, 1, 1)
        helper.data.vertices[0].co = (30, 0, 0)
        self.assertGreaterEqual(self.export_model().radius, 30)

    def test_small_model_radius_is_preserved_while_mesh_bound_is_repaired(self):
        self.model.radius = self.model.geosets[0].meshes[0].radius = 0.001
        self.import_model(importRadiusObj=True)
        exported = self.export_model()
        mesh = exported.geosets[0].meshes[0]
        required = max(mathutils.Vector(vertex).length for vertex in mesh.vertices)
        self.assertGreaterEqual(mesh.radius + 1e-6, required)
        # Model RADIUS supplies collision defaults; it is not the visual bound.
        self.assertEqual(exported.radius, 0.001)

    def test_authored_model_radius_with_and_without_helpers(self):
        for value in (0.0, 0.001, 35.551701):
            for helpers in (False, True):
                with self.subTest(radius=value, helpers=helpers):
                    self.clear_data()
                    self.model.radius = value
                    self.import_model(importRadiusObj=helpers)
                    self.assertEqual(self.export_model().radius, value)
                    self.root.scale = (-4, -4, -4)
                    self.assertAlmostEqual(self.export_model().radius, value * 4, delta=1e-9)

    def test_radius_helpers_support_every_rotation_mode(self):
        self.import_model(importRadiusObj=True)
        helper = utils.getModelRadiusObj(self.root)
        helper.data.clear_geometry()
        helper.data.from_pydata([(3, 0, 0)], [], [])
        self.root.scale = (10, 1, 1)
        for mode in ('XYZ', 'YXZ', 'QUATERNION', 'AXIS_ANGLE'):
            with self.subTest(mode=mode):
                helper.rotation_mode = mode
                if mode == 'QUATERNION':
                    helper.rotation_quaternion = mathutils.Quaternion((0, 0, 1), math.pi / 2)
                elif mode == 'AXIS_ANGLE':
                    helper.rotation_axis_angle = (math.pi / 2, 0, 0, 1)
                else:
                    helper.rotation_euler = (0, 0, math.pi / 2)
                self.assertAlmostEqual(utils.radiusHelperValue(helper, self.root.scale), 3, delta=1e-5)

    def test_original_sphere_handles_rotated_nonuniform_scales(self):
        self.model.radius = 10
        self.import_model(importRadiusObj=True)
        helper = utils.getModelRadiusObj(self.root)
        helper.scale = (10, 1, 1)
        helper.rotation_mode = 'AXIS_ANGLE'
        helper.rotation_axis_angle = (math.pi / 2, 0, 0, 1)
        self.root.scale = (1, 10, 1)
        self.assertAlmostEqual(utils.radiusHelperValue(helper, self.root.scale), 1000, delta=1e-3)

    def test_cached_model_radius_rejects_invalid_values(self):
        self.import_model()
        for value in (-1, math.inf, math.nan):
            self.root[utils.kModel3doRadius] = value
            with self.subTest(radius=value), self.assertRaisesRegex(ValueError, 'radius'):
                self.export_model()

    def test_radius_helpers_reject_delta_and_parent_inverse_translation(self):
        self.import_model(importRadiusObj=True)
        helper = utils.getModelRadiusObj(self.root)
        helper.delta_location = (1, 0, 0)
        with self.assertRaisesRegex(ValueError, 'centered'):
            self.export_model()
        helper.delta_location = (0, 0, 0)
        helper.matrix_parent_inverse = mathutils.Matrix.Translation((1, 0, 0))
        with self.assertRaisesRegex(ValueError, 'centered'):
            self.export_model()

    def test_edited_radius_helper_rejects_nonfinite_vertices(self):
        self.import_model(importRadiusObj=True)
        utils.getModelRadiusObj(self.root).data.vertices[0].co.x = math.nan
        with self.assertRaisesRegex(ValueError, 'finite'):
            self.export_model()

    def test_authored_model_radius_survives_mesh_edit_and_helper_delete(self):
        self.import_model(importRadiusObj=True)
        self.obj.data.vertices[0].co = (100, 0, 0)
        bpy.data.objects.remove(utils.getModelRadiusObj(self.root), do_unlink=True)
        exported = self.export_model()
        self.assertEqual(exported.radius, self.model.radius)
        self.assertGreaterEqual(exported.geosets[0].meshes[0].radius, 100)

    def test_model_bound_contains_nested_scaled_sibling_meshes(self):
        self.import_model()
        # An authored collision radius is retained; only new models need an estimate.
        del self.root[utils.kModel3doRadius]
        sibling = self.obj.copy()
        sibling.data = self.obj.data.copy()
        sibling.sith_model3do_hnode_idx = -1
        sibling.parent = self.obj.parent
        sibling.location = (10, -5, 3)
        sibling.scale = (2, 1, 3)
        bpy.context.scene.collection.objects.link(sibling)
        self.root.scale = (2, 2, 2)
        bpy.context.view_layer.update()
        required = max((obj.matrix_world @ vertex.co - self.root.location).length
                       for obj in (self.obj, sibling) for vertex in obj.data.vertices)
        self.assertGreaterEqual(self.export_model().radius + 1e-5, required)

    def test_invalid_radius_and_offcenter_helpers_are_rejected(self):
        for value in (-1, math.inf, math.nan):
            self.model.radius = value
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                self.import_model(importRadiusObj=True)
            self.clear_data()
        self.model.radius = 2
        self.import_model(importRadiusObj=True)
        utils.getModelRadiusObj(self.root).location.x = 1
        with self.assertRaisesRegex(ValueError, 'centered'):
            self.export_model()

    def test_animation_export_does_not_require_texture_conversion(self):
        self.model.geosets[0].meshes[0].uvs = [(0, 0), (64, 0), (0, 32)]
        self.import_model(Model3doFileVersion.Version2_1)
        self.obj.keyframe_insert('location', frame=0)
        self.obj.location.x += 1
        self.obj.keyframe_insert('location', frame=5)
        bpy.context.scene.frame_end = 5
        exported = _make_key_from_obj('animation.key', self.root, bpy.context.scene)
        self.assertEqual(exported.numJoints, 2)
        self.assertEqual(len(exported.nodes), 1)
