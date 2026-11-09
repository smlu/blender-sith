from pathlib import Path
import tempfile

import bpy
import bmesh

from app.support import SceneTestCase
from fixtures import TV
from sith.model.model3doLoader import load3do, Model3doFileVersion
from sith.model.model3doWriter import save3do
from sith.model.model3doImporter import import3do
from sith.model.model3doExporter import export3do, makeModel3doFromObj
from sith.model import utils


class ModelImportExportTests(SceneTestCase):
    def import_fixture(self, **kwargs):
        return import3do(TV / 'model' / 'triangle.3do', clearScene=False, **kwargs)

    def test_import_builds_hierarchy_transforms_and_mesh(self):
        root = self.import_fixture()
        self.assert_vector(root.location, (0.5, -0.25, 1))
        joint = root.children[0]
        mesh_object = joint.children[0]
        self.assertEqual(joint.sith_model3do_hnode_name, 'root')
        self.assertEqual(mesh_object.sith_model3do_hnode_name, 'head')
        self.assertEqual((joint.sith_model3do_hnode_idx, mesh_object.sith_model3do_hnode_idx), (0, 1))
        self.assert_vector(joint.location, (0.1, 0.2, 0.3))
        self.assert_vector(mesh_object.location, (0, 0, 0.5))
        self.assertEqual(len(mesh_object.data.vertices), 3)
        self.assertEqual(len(mesh_object.data.polygons), 1)
        # Import bakes the 3DO pivot translation into mesh coordinates.
        self.assert_vector(mesh_object.data.vertices[0].co, (0.125, 0, 0))
        self.assertEqual(mesh_object.display_type, 'TEXTURED')

    def test_import_preserves_full_16_bit_node_properties(self):
        mesh_object = self.import_fixture().children[0].children[0]
        self.assertEqual(int(mesh_object.sith_model3do_hnode_flags, 16), 0x2000)
        self.assertEqual(int(mesh_object.sith_model3do_hnode_type, 16), 0x8008)

    def test_face_properties_uvs_and_vertex_colors(self):
        mesh = self.import_fixture().children[0].children[0].data
        bm = bmesh.new()
        self.addCleanup(bm.free)
        bm.from_mesh(mesh)
        bm.faces.ensure_lookup_table()
        face = bm.faces[0]
        self.assertEqual(int(utils.bmFaceGetType(face, bm)), 0x103)
        self.assertEqual(utils.bmFaceGetGeometryMode(face, bm), 4)
        self.assertEqual(utils.bmFaceGetLightMode(face, bm), 3)
        self.assertEqual(utils.bmFaceGetTextureMode(face, bm), 3)
        self.assert_vector(utils.bmFaceGetExtraLight(face, bm), (0.125, 0.25, 0.5, 0.75))
        uv = bm.loops.layers.uv.active
        colors = bm.loops.layers.float_color.active
        for loop, expected_uv, expected_color in zip(
                face.loops, [(0, 0), (1, 0), (0, -1)],
                [(1, 0, 0, 1), (0, 1, 0, 0.5), (0, 0, 1, 0.25)]):
            self.assert_vector(loop[uv].uv, expected_uv)
            self.assert_vector(loop[colors], expected_color, tolerance=1 / 255)

    def test_export_and_reparse_all_versions(self):
        root = self.import_fixture()
        for version in Model3doFileVersion:
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'roundtrip.3do'
                export3do(root, str(path), version, False, True, True)
                model, actual_version = load3do(path)
                self.assertEqual(actual_version, version)
                self.assertEqual([node.name for node in model.meshHierarchy], ['root', 'head'])
                self.assertEqual([node.parentIdx for node in model.meshHierarchy], [-1, 0])
                self.assertEqual(int(model.meshHierarchy[1].flags), 0x2000)
                self.assertEqual(int(model.meshHierarchy[1].type), 0x8008)
                self.assert_vector(model.insertOffset, (0.5, -0.25, 1))
                mesh = model.geosets[0].meshes[0]
                self.assertEqual(mesh.faces[0].vertexIdxs, [0, 1, 2])
                self.assertEqual(int(mesh.faces[0].type), 0x103)
                self.assertEqual(mesh.uvs, [(0, 0), (1, 0), (0, 1)])
                self.assert_vector(mesh.vertices[0], (0.125, 0, 0))
                if version.value == 2.1:
                    self.assert_vector(mesh.vertexColors[0], (1 / 3, 1 / 3, 1 / 3, 1), 1e-6)
                else:
                    self.assert_vector(mesh.vertexColors[0], (1, 0, 0, 1))
                expected_alpha = mesh.vertexColors[1].w
                self.assertAlmostEqual(expected_alpha, 0.5 if version.value == 2.3 else 1,
                                       delta=1 / 255)

    def test_import_without_order_prefix_or_vertex_colors(self):
        root = self.import_fixture(preserveOrder=False, importVertexColors=False)
        self.assertEqual(root.children[0].name, 'root')
        mesh_object = root.children[0].children[0]
        self.assertEqual(mesh_object.name, 'triangle')
        self.assertEqual(mesh_object.sith_model3do_hnode_name, 'head')

    def test_legacy_absolute_uvs_round_trip_using_real_image(self):
        # Legacy UV units are pixels; import divides by image size, export restores it.
        model, _ = load3do(TV / 'model' / 'triangle.3do')
        model.geosets[0].meshes[0].uvs = [(0, 0), (64, 0), (0, 32)]
        mat = bpy.data.materials.new('checker.mat')
        mat.use_nodes = True
        image = bpy.data.images.new('checker', width=64, height=32)
        mat.node_tree.nodes.new('ShaderNodeTexImage').image = image
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'legacy.3do'
            save3do(model, path, Model3doFileVersion.Version2_1, '')
            root = import3do(path, clearScene=False, uvAbsolute_2_1=True)
            mesh = root.children[0].children[0].data
            self.assert_vector(mesh.uv_layers.active.data[1].uv, (1, 0))
            self.assert_vector(mesh.uv_layers.active.data[2].uv, (0, -1))
            restored = makeModel3doFromObj('legacy', root, uvAbsolute=True, exportVertexColors=True)
            self.assertEqual(restored.geosets[0].meshes[0].uvs, [(0, 0), (64, 0), (0, 32)])

    def test_radius_helpers_are_created_and_excluded_from_export(self):
        root = self.import_fixture(importRadiusObj=True)
        self.assertTrue(any(obj.name.startswith(utils.kModelRadius) for obj in bpy.data.objects))
        self.assertTrue(any(obj.name.startswith(utils.kMeshRadius) for obj in bpy.data.objects))
        model = makeModel3doFromObj('radius', root)
        self.assertEqual(len(model.meshHierarchy), 2)
        self.assertEqual(len(model.geosets[0].meshes), 1)
        self.assertAlmostEqual(model.radius, 2, delta=1e-5)
        self.assertAlmostEqual(model.geosets[0].meshes[0].radius, 1.5, delta=1e-5)

    def test_import_rejects_invalid_mesh_reference(self):
        model, _ = load3do(TV / 'model' / 'triangle.3do')
        model.meshHierarchy[1].meshIdx = 9
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'badmesh.3do'
            save3do(model, path, Model3doFileVersion.Version2_3, '')
            with self.assertRaisesRegex(IndexError, 'out of range'):
                import3do(path, clearScene=False)

    def test_export_warns_about_long_resource_name_without_truncating_it(self):
        root = self.import_fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ('x' * 100 + '.3do')
            warnings = []
            export3do(root, str(path), Model3doFileVersion.Version2_3, False, False, True, warnings=warnings)
            self.assertTrue(path.is_file())
            self.assertEqual(len(warnings), 1)
            self.assertIn(path.name, warnings[0])
            self.assertIn('without truncation', warnings[0])

    def test_registered_import_operator(self):
        result = bpy.ops.import_scene.sith_3do(
            filepath=str(TV / 'model' / 'triangle.3do'), clear_scene=False,
            set_3d_view=False, vertex_colors=True)
        self.assertEqual(result, {'FINISHED'})
        self.assertTrue(any(obj.sith_model3do_hnode_name == 'head' for obj in bpy.data.objects))
