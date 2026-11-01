import contextlib
import copy
import io
from pathlib import Path
import tempfile
import unittest

from fixtures import TV
from sith.model.model3do import Model3do, Vector3f
from sith.model.model3doLoader import load3do, Model3doFileVersion
from sith.model.model3doRecovery import recoverModel3do
from sith.model.model3doWriter import save3do


class ModelRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'recovery.3do'
        self.source = (TV / 'model' / 'triangle.3do').read_text()

    def recover_text(self, text):
        self.path.write_text(text, encoding='utf-8')
        warnings = []
        with contextlib.redirect_stdout(io.StringIO()):
            model, version = load3do(self.path, allowErrors=True, warnings=warnings)
        return model, version, warnings

    def assert_report_contains(self, warnings, text):
        self.assertIn(text, '\n'.join(warnings))

    def test_valid_models_are_unchanged_in_all_versions(self):
        source, _ = load3do(TV / 'model' / 'triangle.3do')
        for version in Model3doFileVersion:
            with self.subTest(version=version):
                save3do(source, self.path, version, '')
                strict, _ = load3do(self.path)
                warnings = []
                recovered, actualVersion = load3do(self.path, allowErrors=True, warnings=warnings)
                self.assertEqual(actualVersion, version)
                self.assertEqual(warnings, [])
                outputs = [Path(self.directory.name) / name for name in ('strict.3do', 'recovered.3do')]
                for model, output in zip((strict, recovered), outputs):
                    save3do(model, output, version, '')
                self.assertEqual(outputs[0].read_bytes(), outputs[1].read_bytes())

    def test_invalid_uvs_get_one_placeholder_without_hiding_later_errors(self):
        text = self.source.replace('3 0,0 1,1 2,2', '3 0,0 1,3 2,3')
        model, _, warnings = self.recover_text(text)
        mesh = model.geosets[0].meshes[0]
        self.assertEqual(mesh.faces[0].uvIdxs, [0, 3, 3])
        self.assertEqual(mesh.uvs, [(0, 0), (1, 0), (0, 1), (0, 0)])
        self.assertEqual(sum('invalid UV 3' in warning for warning in warnings), 2)
        self.assertEqual([node.parentIdx for node in model.meshHierarchy], [-1, 0])

    def test_complete_hierarchy_does_not_gain_joints_for_unused_meshes(self):
        model, _ = load3do(TV / 'model' / 'triangle.3do')
        unused = copy.deepcopy(model.geosets[0].meshes[0])
        unused.idx, unused.name = 1, 'unused'
        model.geosets[0].meshes.append(unused)
        for version in Model3doFileVersion:
            with self.subTest(version=version):
                save3do(model, self.path, version, '')
                warnings = []
                recovered, _ = load3do(self.path, allowErrors=True, warnings=warnings)
                self.assertEqual(len(recovered.geosets[0].meshes), 2)
                self.assertEqual([node.name for node in recovered.meshHierarchy], ['root', 'head'])
                self.assertEqual([node.meshIdx for node in recovered.meshHierarchy], [-1, 0])
                self.assertEqual(warnings, [])

    def test_geometry_repair_does_not_activate_intentionally_unused_meshes(self):
        model, version = load3do(TV / 'model' / 'triangle.3do')
        unused = copy.deepcopy(model.geosets[0].meshes[0])
        unused.idx, unused.name = 1, 'unused'
        model.geosets[0].meshes.append(unused)
        model.geosets[0].meshes[0].faces[0].uvIdxs[0] = 999
        save3do(model, self.path, version, '')
        warnings = []
        recovered, _ = load3do(self.path, allowErrors=True, warnings=warnings)
        self.assert_report_contains(warnings, 'invalid UV 999')
        self.assertEqual(len(recovered.meshHierarchy), 2)
        self.assertFalse(any('no recovered hierarchy node' in warning for warning in warnings))

    def test_complete_but_empty_hierarchy_still_recovers_available_meshes(self):
        text = self.source[:self.source.index('HIERARCHY NODES')] + 'HIERARCHY NODES 0\n'
        model, _, warnings = self.recover_text(text)
        self.assertEqual([(node.meshIdx, node.parentIdx) for node in model.meshHierarchy], [(-1, -1), (0, 0)])
        self.assert_report_contains(warnings, 'Hierarchy is missing')

    def test_negative_and_large_uv_indices_are_not_python_indexed(self):
        model, _, warnings = self.recover_text(
            self.source.replace('3 0,0 1,1 2,2', '3 0,-1 1,999999 2,2'))
        mesh = model.geosets[0].meshes[0]
        self.assertEqual(mesh.faces[0].uvIdxs, [3, 3, 2])
        self.assert_report_contains(warnings, 'invalid UV -1')
        self.assert_report_contains(warnings, 'invalid UV 999999')

    def test_truncated_uv_list_preserves_completed_vertices_and_uvs(self):
        text = self.source[:self.source.index('2: 0.0 1.0\nVERTEX NORMALS')] + '2: 0.0'
        model, version, warnings = self.recover_text(text)
        mesh = model.geosets[0].meshes[0]
        self.assertEqual(version, Model3doFileVersion.Version2_3)
        self.assertEqual(mesh.vertices, [(0, 0, 0), (1, 0, 0), (0, 1, 0)])
        self.assertEqual(mesh.uvs, [(0, 0), (1, 0)])
        self.assertEqual(mesh.faces, [])
        self.assertEqual(mesh.normals, [(0, 0, 0)] * 3)
        self.assertEqual([(node.meshIdx, node.parentIdx) for node in model.meshHierarchy], [(-1, -1), (0, 0)])
        self.assert_report_contains(warnings, 'Stopped parsing GEOMETRYDEF')
        self.assert_report_contains(warnings, 'Hierarchy is missing')

    def test_incomplete_vertex_record_is_not_committed(self):
        text = self.source[:self.source.index('1: 1.0 0.0 0.0 0.0 1.0 0.0 0.5')] + '1: 1 0 0 0 1'
        model, _, warnings = self.recover_text(text)
        mesh = model.geosets[0].meshes[0]
        self.assertEqual(mesh.vertices, [(0, 0, 0)])
        self.assertEqual(mesh.vertexColors, [(1, 0, 0, 1)])
        self.assert_report_contains(warnings, 'Only completed records')

    def test_completed_mesh_survives_truncation_in_a_later_mesh(self):
        model, _ = load3do(TV / 'model' / 'triangle.3do')
        second = copy.deepcopy(model.geosets[0].meshes[0])
        second.idx, second.name = 1, 'second'
        model.geosets[0].meshes.append(second)
        save3do(model, self.path, Model3doFileVersion.Version2_3, '')
        text = self.path.read_text()
        end = text.index('TEXTURE VERTICES', text.index('NAME second'))
        recovered, _, warnings = self.recover_text(text[:end] + 'TEXTURE VERTICES 3\n0:')
        first, second = recovered.geosets[0].meshes
        self.assertEqual(len(first.faces), 1)
        self.assertEqual((len(second.vertices), len(second.faces)), (3, 0))
        self.assert_report_contains(warnings, 'Only completed records')

    def test_completed_faces_survive_missing_face_normals(self):
        text = self.source[:self.source.index('FACE NORMALS')] + 'FACE NORMALS\n0:'
        model, _, warnings = self.recover_text(text)
        self.assertEqual(model.geosets[0].meshes[0].faces[0].vertexIdxs, [0, 1, 2])
        self.assert_report_contains(warnings, 'Stopped parsing GEOMETRYDEF')

    def test_incomplete_face_is_omitted_but_vertices_survive(self):
        text = self.source[:self.source.index('0: 0 0x103')] + '0: 0 0x103 4 3 3 (0/0/0/1) 3 0,0 1,1'
        model, _, warnings = self.recover_text(text)
        self.assertEqual(len(model.geosets[0].meshes[0].vertices), 3)
        self.assertEqual(model.geosets[0].meshes[0].faces, [])
        self.assert_report_contains(warnings, 'Stopped parsing')

    def test_partial_hierarchy_keeps_complete_nodes_and_reports_orphan_mesh(self):
        text = self.source[:self.source.index('1: 0x2000')] + '1: 0x2000'
        model, _, warnings = self.recover_text(text)
        self.assertEqual(model.meshHierarchy[0].name, 'root')
        self.assertEqual(model.meshHierarchy[0].position, (0.1, 0.2, 0.3))
        self.assertEqual(model.meshHierarchy[1].meshIdx, 0)
        self.assertEqual(model.meshHierarchy[1].parentIdx, -1)
        self.assert_report_contains(warnings, 'no recovered hierarchy node')

    def test_bad_vertex_reference_omits_face_not_the_mesh(self):
        model, _, warnings = self.recover_text(self.source.replace('3 0,0 1,1 2,2', '3 0,0 1,1 99,2'))
        self.assertEqual(len(model.geosets[0].meshes[0].vertices), 3)
        self.assertEqual(model.geosets[0].meshes[0].faces, [])
        self.assert_report_contains(warnings, 'face 0: invalid vertex')

    def test_invalid_material_does_not_discard_geometry(self):
        model, _, warnings = self.recover_text(self.source.replace('0: 0 0x103', '0: 999 0x103'))
        self.assertEqual(model.geosets[0].meshes[0].faces[0].materialIdx, -1)
        self.assert_report_contains(warnings, 'invalid material 999')

    def test_duplicate_and_repeated_corner_faces_survive_recovery(self):
        model, _ = load3do(TV / 'model' / 'triangle.3do')
        mesh = model.geosets[0].meshes[0]
        mesh.faces.append(copy.deepcopy(mesh.faces[0]))
        mesh.faces.append(copy.deepcopy(mesh.faces[0]))
        mesh.faces[-1].vertexIdxs = [0, 0, 1]
        warnings = []
        recoverModel3do(model, warnings)
        self.assertEqual(len(mesh.faces), 3)
        self.assertEqual(mesh.faces[-1].vertexIdxs, [0, 0, 1])
        self.assertEqual(warnings, [])

    def test_invalid_mesh_parent_and_cycles_are_recoverable(self):
        for parents in ((1, 0), (0, 100), (-2, -1)):
            with self.subTest(parents=parents):
                model, _ = load3do(TV / 'model' / 'triangle.3do')
                for node, parent in zip(model.meshHierarchy, parents):
                    node.parentIdx = parent
                model.meshHierarchy[1].meshIdx = 999
                warnings = []
                recoverModel3do(model, warnings)
                self.assertEqual(model.meshHierarchy[1].meshIdx, -1)
                for index in range(len(model.meshHierarchy)):
                    visited = set()
                    while index >= 0:
                        self.assertNotIn(index, visited)
                        visited.add(index)
                        index = model.meshHierarchy[index].parentIdx
                self.assert_report_contains(warnings, 'missing mesh 999')
                self.assert_report_contains(warnings, 'placed at the origin')

    def test_nonfinite_vertices_are_removed_and_face_indices_remapped(self):
        model, _ = load3do(TV / 'model' / 'triangle.3do')
        mesh = model.geosets[0].meshes[0]
        mesh.vertices.insert(0, Vector3f(float('inf'), 0, 0))
        mesh.vertexColors.insert(0, mesh.vertexColors[0])
        mesh.normals.insert(0, mesh.normals[0])
        mesh.faces[0].vertexIdxs = [1, 2, 3]
        warnings = []
        recoverModel3do(model, warnings)
        self.assertEqual(len(mesh.vertices), 3)
        self.assertEqual(mesh.faces[0].vertexIdxs, [0, 1, 2])
        self.assert_report_contains(warnings, 'vertex 0 is nonfinite')

    def test_unrecoverable_input_and_bad_headers_still_fail(self):
        for text in ('\x00', 'SECTION: HEADER\nBAD 2.3\n',
                     self.source.replace('3DO 2.3', '3DO 9.9'),
                     self.source[:self.source.index('0: 0.0 0.0 0.0 1.0')]):
            with self.subTest(text=text[:40]), self.assertRaises((ValueError, OSError)):
                self.recover_text(text)
        with self.assertRaises(FileNotFoundError):
            load3do(self.path.with_name('missing.3do'), allowErrors=True)

    def test_strict_mode_still_rejects_truncation(self):
        self.path.write_text(self.source[:self.source.index('VERTEX NORMALS')], encoding='utf-8')
        with self.assertRaises((TypeError, ValueError, AssertionError)):
            load3do(self.path)

    def test_recovery_does_not_rewrite_source_file(self):
        text = self.source.replace('3 0,0 1,1 2,2', '3 0,0 1,99 2,2')
        self.recover_text(text)
        self.assertEqual(self.path.read_text(), text)

    def test_empty_valid_model_is_not_given_invented_geometry(self):
        warnings = []
        model = Model3do('empty')
        recoverModel3do(model, warnings)
        self.assertEqual(model.geosets, [])
        self.assertEqual(model.meshHierarchy, [])
        self.assertEqual(warnings, [])
