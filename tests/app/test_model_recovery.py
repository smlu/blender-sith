import copy
from pathlib import Path
import tempfile
from unittest.mock import patch

import bpy

from app.support import SceneTestCase
from fixtures import TV
from sith.model.model3doImporter import import3do
from sith.model.model3doLoader import load3do, Model3doFileVersion
from sith.model.model3doWriter import save3do
from sith.model import utils


class ModelRecoveryImportTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'recovery.3do'
        self.source = (TV / 'model' / 'triangle.3do').read_text()
        originalTexts = set(bpy.data.texts)
        self.addCleanup(self.remove_reports, originalTexts)

    @staticmethod
    def remove_reports(original):
        for text in list(bpy.data.texts):
            if text not in original:
                bpy.data.texts.remove(text)

    def import_text(self, text, **options):
        self.path.write_text(text, encoding='utf-8')
        return import3do(self.path, clearScene=False, **options)

    def test_recovery_is_disabled_by_default(self):
        option = bpy.ops.import_scene.sith_3do.get_rna_type().properties['allow_errors']
        self.assertFalse(option.default)
        self.assertEqual(option.name, 'Try Recover Broken File')
        with self.assertRaisesRegex(ValueError, 'texture vertex'):
            self.import_text(self.source.replace('3 0,0 1,1 2,2', '3 0,0 1,3 2,2'))
        self.assertEqual(len(bpy.data.objects), 0)
        self.assertEqual(len(bpy.data.meshes), 0)

    def test_recovered_uvs_preserve_geometry_and_valid_corners(self):
        warnings = []
        root = self.import_text(self.source.replace('3 0,0 1,1 2,2', '3 0,0 1,3 2,2'),
                                allowErrors=True, warnings=warnings)
        mesh = root.children[0].children[0].data
        self.assertEqual((len(mesh.vertices), len(mesh.polygons)), (3, 1))
        self.assert_vector(mesh.uv_layers.active.data[0].uv, (0, 0))
        self.assert_vector(mesh.uv_layers.active.data[1].uv, (0, 0))
        self.assert_vector(mesh.uv_layers.active.data[2].uv, (0, -1))
        self.assertEqual(len(warnings), 1)
        report = bpy.data.texts[root[utils.kModel3doImportReport]]
        self.assertTrue(report.use_fake_user)
        self.assertIn("face 0, corner 1: invalid UV 3", report.as_string())
        self.assertIn('Recovery is not a repair', report.as_string())

    def test_truncated_model_imports_as_vertices_only_with_report(self):
        text = self.source[:self.source.index('2: 0.0 1.0\nVERTEX NORMALS')] + '2: 0.0'
        root = self.import_text(text, allowErrors=True)
        meshObj = root.children[0].children[0]
        self.assertEqual((len(meshObj.data.vertices), len(meshObj.data.polygons)), (3, 0))
        self.assert_vector(meshObj.location, (0, 0, 0))
        # No source hierarchy exists: the original pivot must not be invented.
        self.assert_vector(meshObj.data.vertices[0].co, (0, 0, 0))
        report = bpy.data.texts[root[utils.kModel3doImportReport]].as_string()
        self.assertIn('Hierarchy is missing', report)
        self.assertIn('Stopped parsing', report)

    def test_missing_face_normals_do_not_discard_completed_surface(self):
        root = self.import_text(self.source[:self.source.index('FACE NORMALS')], allowErrors=True)
        mesh = root.children[0].children[0].data
        self.assertEqual(len(mesh.polygons), 1)
        self.assert_vector(mesh.polygons[0].normal, (0, 0, 1))

    def test_invalid_face_can_leave_a_vertices_only_mesh(self):
        root = self.import_text(self.source.replace('3 0,0 1,1 2,2', '3 0,0 1,1 99,2'), allowErrors=True)
        mesh = root.children[0].children[0].data
        self.assertEqual((len(mesh.vertices), len(mesh.polygons)), (3, 0))
        self.assertIn('face omitted', bpy.data.texts[root[utils.kModel3doImportReport]].as_string())

    def test_duplicate_surfaces_preserve_winding_and_uv_corners(self):
        model, _ = load3do(TV / 'model' / 'triangle.3do')
        mesh = model.geosets[0].meshes[0]
        face = copy.deepcopy(mesh.faces[0])
        face.vertexIdxs, face.uvIdxs = [2, 1, 0], [2, 1, 0]
        mesh.faces.append(face)
        save3do(model, self.path, Model3doFileVersion.Version2_3, '')
        root = import3do(self.path, clearScene=False, allowErrors=True)
        imported = root.children[0].children[0].data
        self.assertEqual(len(imported.polygons), 2)
        self.assertEqual(list(imported.polygons[1].vertices), [2, 1, 0])
        for loop, uv in zip(imported.polygons[1].loop_indices, ((0, -1), (1, 0), (0, 0))):
            self.assert_vector(imported.uv_layers.active.data[loop].uv, uv)
        self.assertNotIn(utils.kModel3doImportReport, root)

    def test_partial_hierarchy_attaches_all_recovered_roots(self):
        root = self.import_text(self.source[:self.source.index('1: 0x2000')] + '1:', allowErrors=True)
        self.assertEqual(len(root.children), 2)
        self.assertTrue(all(obj.parent == root for obj in root.children))
        self.assertEqual(sum(len(obj.data.polygons) for obj in root.children if obj.type == 'MESH'), 1)

    def test_failed_import_preserves_existing_scene_before_clear(self):
        existing = bpy.data.objects.new('keep_me', None)
        bpy.context.scene.collection.objects.link(existing)
        self.path.write_text('SECTION: HEADER\n3DO 2.3\nSECTION: GEOMETRYDEF\nRADIUS', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'No recoverable'):
            import3do(self.path, clearScene=True, allowErrors=True)
        self.assertIn(existing, list(bpy.context.scene.objects))
        # Reference validation also happens before Clear Scene in strict mode.
        self.path.write_text(self.source.replace('3 0,0 1,1 2,2', '3 0,0 1,99 2,2'), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'texture vertex'):
            import3do(self.path, clearScene=True)
        self.assertIn(existing, list(bpy.context.scene.objects))

    def test_operator_reports_recovery_as_success_with_warnings(self):
        self.path.write_text(self.source.replace('3 0,0 1,1 2,2', '3 0,0 1,3 2,2'), encoding='utf-8')
        result = bpy.ops.import_scene.sith_3do(filepath=str(self.path), allow_errors=True,
                                            clear_scene=False, set_3d_view=False)
        self.assertEqual(result, {'FINISHED'})
        self.assertEqual(sum(utils.kModel3doImportReport in obj for obj in bpy.data.objects), 1)

    def test_operator_rejects_unrecoverable_input_without_partial_objects(self):
        self.path.write_text('SECTION: HEADER\nBAD 2.3\n', encoding='utf-8')
        # Blender raises RuntimeError for an ERROR report from a cancelled operator.
        with self.assertRaisesRegex(RuntimeError, 'Cannot import 3DO'):
            bpy.ops.import_scene.sith_3do(filepath=str(self.path), allow_errors=True,
                                         clear_scene=False, set_3d_view=False)
        self.assertEqual(len(bpy.data.objects), 0)
        self.assertEqual(len(bpy.data.meshes), 0)

    def test_valid_recovery_import_has_no_warning_marker(self):
        warnings = []
        root = self.import_text(self.source, allowErrors=True, warnings=warnings)
        self.assertEqual(warnings, [])
        self.assertNotIn(utils.kModel3doImportReport, root)

    def test_failed_object_build_removes_only_new_datablocks(self):
        existing = bpy.data.objects.new('keep_me', None)
        bpy.context.scene.collection.objects.link(existing)
        material = bpy.data.materials.new('keep_material')
        with patch('sith.model.model3doImporter._set_obj_rotation', side_effect=RuntimeError('build failed')):
            with self.assertRaisesRegex(RuntimeError, 'build failed'):
                self.import_text(self.source, allowErrors=True)
        self.assertEqual(list(bpy.data.objects), [existing])
        self.assertEqual(list(bpy.data.materials), [material])
        self.assertEqual(len(bpy.data.meshes), 0)

    def test_warning_report_survives_blend_save_and_reload(self):
        root = self.import_text(self.source.replace('3 0,0 1,1 2,2', '3 0,0 1,3 2,2'), allowErrors=True)
        name, reportName = root.name, root[utils.kModel3doImportReport]
        path = Path(self.directory.name) / 'recovered.blend'
        # A library reload verifies saved datablocks without replacing the test scene.
        bpy.data.libraries.write(str(path), {root, bpy.data.texts[reportName]})
        with bpy.data.libraries.load(str(path)) as (source, target):
            self.assertIn(reportName, source.texts)
            target.objects = [name]
            target.texts = [reportName]
        self.assertEqual(target.objects[0][utils.kModel3doImportReport], reportName)
        self.assertIn('invalid UV 3', target.texts[0].as_string())

    def test_missing_report_is_reported_without_creating_windows(self):
        windows = list(bpy.context.window_manager.windows)
        with self.assertRaisesRegex(RuntimeError, 'no longer available'):
            bpy.ops.wm.sith_view_3do_import_report(report_name='missing report')
        self.assertEqual(list(bpy.context.window_manager.windows), windows)

    def test_report_viewer_handles_background_mode_without_modifying_report(self):
        report = bpy.data.texts.new('background report')
        report.write('Recovery diagnostics\n')
        windows = list(bpy.context.window_manager.windows)
        self.assertEqual(bpy.ops.wm.sith_view_3do_import_report(report_name=report.name), {'CANCELLED'})
        self.assertEqual(report.as_string(), 'Recovery diagnostics\n')
        self.assertEqual(list(bpy.context.window_manager.windows), windows)
