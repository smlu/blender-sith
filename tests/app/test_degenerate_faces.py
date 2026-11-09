"""Normal Blender import must preserve legacy zero-area geometry and its data."""
import copy
import itertools
import math
from pathlib import Path
import tempfile

import bpy
import bmesh

from app.support import SceneTestCase
from fixtures import TV
from vector_expectations import (DEGENERATE_VERTICES, DEGENERATE_COLORS, DEGENERATE_CORNERS,
                                 DEGENERATE_UVS, DEGENERATE_FACE_UVS, DEGENERATE_VERTEX_SOURCES,
                                 DEGENERATE_EXPANDED_FACES, color_for_version)
from sith.model.model3doLoader import load3do, Model3doFileVersion
from sith.model.model3doImporter import import3do, _make_mesh
from sith.model.model3doExporter import export3do
from sith.model import utils


class DegenerateFaceImportTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name) / 'roundtrip.3do'
        self.path = TV / 'model/degenerate_faces.3do'

    def import_vector(self, **options):
        warnings = []
        root = import3do(self.path, clearScene=False, warnings=warnings, **options)
        self.assertEqual(warnings, [])
        self.assertNotIn(utils.kModel3doImportReport, root)
        return root, next(obj for obj in root.children_recursive if obj.type == 'MESH')

    def test_normal_import_preserves_every_face_with_valid_blender_topology(self):
        root, obj = self.import_vector()
        mesh = obj.data
        self.assertEqual(len(root.children), 1)
        self.assertEqual(len(mesh.vertices), 12)
        self.assertEqual([tuple(face.vertices) for face in mesh.polygons], list(DEGENERATE_EXPANDED_FACES))
        for vertex, source in zip(mesh.vertices, DEGENERATE_VERTEX_SOURCES):
            self.assert_vector(vertex.co, DEGENERATE_VERTICES[source])
        for polygon in mesh.polygons:
            self.assertEqual(len(set(polygon.vertices)), len(polygon.vertices))
            self.assertTrue(all(math.isfinite(value) for value in polygon.normal))

    def test_corner_uvs_colors_and_face_properties_stay_aligned(self):
        _, obj = self.import_vector()
        mesh = obj.data
        bm = bmesh.new()
        self.addCleanup(bm.free)
        bm.from_mesh(mesh)
        bm.faces.ensure_lookup_table()
        colors = mesh.color_attributes.active_color
        for index, polygon in enumerate(mesh.polygons):
            with self.subTest(face=index):
                self.assertEqual(int(utils.bmFaceGetType(bm.faces[index], bm)), 1 << index)
                self.assert_vector(utils.bmFaceGetExtraLight(bm.faces[index], bm),
                                   (0.1 + index / 10, 0.2 + index / 10, 0.3 + index / 10, 1 - index / 10))
                for corner, loop in enumerate(polygon.loop_indices):
                    uv = DEGENERATE_UVS[DEGENERATE_FACE_UVS[index][corner]]
                    self.assert_vector(mesh.uv_layers.active.data[loop].uv, (uv[0], -uv[1]))
                    self.assert_vector(colors.data[loop].color, DEGENERATE_COLORS[DEGENERATE_CORNERS[index][corner]])

    def test_loose_point_colors_include_duplicated_corner_sources(self):
        _, obj = self.import_vector()
        pointColors = obj.data.color_attributes[utils.k3doLooseColors]
        self.assertEqual(len(pointColors.data), 12)
        for index, source in enumerate(DEGENERATE_VERTEX_SOURCES):
            self.assert_vector(pointColors.data[index].color, DEGENERATE_COLORS[source])
        self.assert_vector(pointColors.data[5].color, (2, -0.5, 0.25, 0))

    def test_mesh_construction_does_not_modify_resource_records(self):
        model, _ = load3do(self.path)
        source = model.geosets[0].meshes[0]
        before = copy.deepcopy(source.__dict__)
        mesh = _make_mesh(source, False, True, model.materials)
        self.assertEqual(len(mesh.vertices), 12)
        # Compare individual record fields; face objects use identity equality.
        self.assertEqual(source.vertices, before['v'])
        self.assertEqual(source.vertexColors, before['vc'])
        self.assertEqual(source.normals, before['vn'])
        self.assertEqual(source.uvs, before['tv'])
        self.assertEqual([tuple(face.vertexIdxs) for face in source.faces], list(DEGENERATE_CORNERS))

    def test_round_trip_all_versions_order_sync_and_color_modes(self):
        # Distinct coincident vertices are allowed to be renumbered, but face
        # count, corner order, per-corner attributes and hierarchy must survive.
        source, _ = load3do(self.path)
        for version, preserve, sync, importColors, exportColors in itertools.product(
                Model3doFileVersion, (False, True), (False, True), (False, True), (False, True)):
            self.clear_data()
            with self.subTest(version=version, preserve=preserve, sync=sync,
                              importColors=importColors, exportColors=exportColors):
                root, _ = self.import_vector(preserveOrder=preserve, importVertexColors=importColors)
                export3do(root, str(self.output), version, False, exportColors, sync)
                actual, _ = load3do(self.output)
                self.assertEqual([(node.name, node.parentIdx) for node in actual.meshHierarchy], [('joint', -1)])
                mesh = actual.geosets[0].meshes[0]
                self.assertEqual(len(mesh.faces), 9)
                for index, face in enumerate(mesh.faces):
                    self.assertEqual(len(set(face.vertexIdxs)), len(face.vertexIdxs))
                    self.assertEqual(int(face.type), 1 << index)
                    self.assert_vector(face.color, color_for_version(source.geosets[0].meshes[0].faces[index].color, version))
                    for corner, vertex in enumerate(face.vertexIdxs):
                        sourceIndex = DEGENERATE_CORNERS[index][corner]
                        color = DEGENERATE_COLORS[sourceIndex] if importColors and exportColors else (0, 0, 0, 1)
                        self.assert_vector(mesh.vertices[vertex], DEGENERATE_VERTICES[sourceIndex])
                        self.assert_vector(mesh.vertexColors[vertex], color_for_version(color, version))
                        self.assert_vector(mesh.uvs[face.uvIdxs[corner]], DEGENERATE_UVS[DEGENERATE_FACE_UVS[index][corner]])

    def test_normal_operator_import_does_not_require_recovery(self):
        self.assertEqual(bpy.ops.import_scene.sith_3do(filepath=str(self.path),
                         clear_scene=False, set_3d_view=False, vertex_colors=True), {'FINISHED'})
        self.assertFalse(any(utils.kModel3doImportReport in obj for obj in bpy.data.objects))
        mesh = next(obj.data for obj in bpy.data.objects if obj.type == 'MESH')
        self.assertEqual(len(mesh.polygons), 9)

    def test_enabling_recovery_does_not_drop_safe_degenerate_faces(self):
        _, obj = self.import_vector(allowErrors=True)
        self.assertEqual([tuple(face.vertices) for face in obj.data.polygons], list(DEGENERATE_EXPANDED_FACES))

    def test_recovery_omits_unsafe_face_without_losing_adjacent_repeated_face(self):
        warnings = []
        root = import3do(TV / 'model/recovery/bad_faces.3do', clearScene=False,
                         allowErrors=True, warnings=warnings)
        mesh = next(obj.data for obj in root.children_recursive if obj.type == 'MESH')
        self.assertEqual([tuple(face.vertices) for face in mesh.polygons],
                         [(0, 1, 2), (0, 3, 1), (2, 1, 0)])
        self.assertEqual(sum('face omitted' in warning for warning in warnings), 1)
        self.assert_vector(mesh.polygons[2].normal, (0, 0, -1))

    def test_unsafe_references_still_fail_before_clear_scene(self):
        existing = bpy.data.objects.new('keep_me', None)
        bpy.context.scene.collection.objects.link(existing)
        text = self.path.read_text()
        cases = (
            ('3 1,0 0,3 0,4', '3 1,0 99,3 0,4'),
            ('3 1,0 0,3 0,4', '3 1,0 -1,3 0,4'),
            ('3 1,0 0,3 0,4', '3 1,0 0,99 0,4'),
            ('3 1,0 0,3 0,4', '3 1,0 0,-1 0,4'),
        )
        for old, new in cases:
            self.output.write_text(text.replace(old, new))
            with self.subTest(new=new), self.assertRaisesRegex(ValueError, 'vertex'):
                import3do(self.output, clearScene=True)
            self.assertEqual(list(bpy.data.objects), [existing])
