"""Visible deformations and advisory name warnings in real export paths."""
from pathlib import Path
import tempfile
from types import SimpleNamespace

import bpy

from app.support import SceneTestCase
from sith import app
from sith.key.keyExporter import _make_key_from_obj
from sith.model.model3doExporter import export3do, makeModel3doFromObj
from sith.model.model3doLoader import load3do, Model3doFileVersion


class ShapeAndNameExportTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'export.3do'
        mesh = bpy.data.meshes.new('mesh')
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        self.obj = bpy.data.objects.new('joint', mesh)
        bpy.context.scene.collection.objects.link(self.obj)
        bpy.context.view_layer.objects.active = self.obj
        self.obj.select_set(True)
        self.obj.sith_model3do_hnode_idx = 0
        self.obj.sith_model3do_hnode_name = 'joint'
        self.obj.shape_key_add(name='Basis')
        self.shape = self.obj.shape_key_add(name='VisibleShape')
        self.shape.data[1].co.x = 10
        self.obj.data.shape_keys.use_relative = True
        self.obj.active_shape_key_index, self.obj.show_only_shape_key = 0, False
        self.shape.value, self.shape.mute = 0, False

    def export(self, warnings=None):
        export3do(self.obj, str(self.path), Model3doFileVersion.Version2_3,
                  False, False, True, warnings=warnings)

    def test_active_relative_shape_key_is_rejected_without_overwriting_output(self):
        self.shape.value = 1
        self.path.write_bytes(b'previous export')
        with self.assertRaisesRegex(ValueError, 'Bake shape-key deformation'):
            self.export()
        self.assertEqual(self.path.read_bytes(), b'previous export')
        self.assertEqual((self.shape.value, self.shape.data[1].co.x), (1, 10))

    def test_zero_weight_or_muted_shape_keys_allow_base_mesh_export(self):
        for value, mute in ((0, False), (1, True)):
            with self.subTest(value=value, mute=mute):
                self.shape.value, self.shape.mute = value, mute
                self.export()
                resource, _ = load3do(self.path)
                self.assertEqual(max(v.x for v in resource.geosets[0].meshes[0].vertices), 1)

    def test_pinned_shape_is_rejected_even_with_zero_weight(self):
        self.obj.active_shape_key_index, self.obj.show_only_shape_key = 1, True
        with self.assertRaisesRegex(ValueError, 'shape-key'):
            self.export()
        self.assertFalse(self.path.exists())

    def test_absolute_shape_keys_require_explicit_baking(self):
        self.obj.data.shape_keys.use_relative = False
        self.obj.data.shape_keys.eval_time = 50
        with self.assertRaisesRegex(ValueError, 'shape-key'):
            self.export()
        self.obj.shape_key_remove(self.shape)
        self.export()  # A basis-only datablock cannot deform the mesh.

    def test_baked_shape_geometry_is_exported(self):
        self.shape.value = 1
        bpy.ops.object.convert(target='MESH')
        self.obj = bpy.context.object
        self.assertIsNone(self.obj.data.shape_keys)
        self.export()
        resource, _ = load3do(self.path)
        self.assertEqual(max(v.x for v in resource.geosets[0].meshes[0].vertices), 10)

    def test_shape_keys_do_not_block_geometry_independent_key_export(self):
        self.shape.value = 1
        scene = bpy.context.scene
        scene.frame_end, scene.sith_key_flags, scene.sith_key_types = 4, set(), 'ffff'
        self.obj.keyframe_insert(data_path='location', frame=0)
        self.assertEqual(len(_make_key_from_obj('pose.key', self.obj, scene).nodes), 1)

    def test_long_mesh_names_are_preserved_and_warned_not_rejected(self):
        self.obj.data.name = 'mesh_' + 'a' * 75
        warnings = []
        self.export(warnings)
        resource, _ = load3do(self.path)
        self.assertEqual(resource.geosets[0].meshes[0].name, self.obj.data.name)
        self.assertEqual(len(warnings), 1)
        self.assertIn('legacy compatibility limit is 63', warnings[0])

    def test_export_operator_reports_name_warnings_and_still_finishes(self):
        self.obj.data.name = 'mesh_' + 'a' * 75
        reports = []
        operation = SimpleNamespace(filepath=str(self.path), obj=self.obj,
                                    version=Model3doFileVersion.Version2_3.name,
                                    absolute_uv=False, export_vert_colors=False, sync_mesh_list=True,
                                    report=lambda kinds, message: reports.append((kinds, message)))
        self.assertEqual(app.ExportModel3do.execute(operation, bpy.context), {'FINISHED'})
        self.assertTrue(self.path.is_file())
        self.assertTrue(any(kinds == {'WARNING'} and 'mesh name' in message for kinds, message in reports))

    def test_long_joint_names_remain_subject_to_key_target_limits(self):
        self.obj.sith_model3do_hnode_name = 'j' * 80
        scene = bpy.context.scene
        scene.frame_end, scene.sith_key_flags, scene.sith_key_types = 4, set(), 'ffff'
        self.obj.keyframe_insert(data_path='location', frame=0)
        with self.assertRaises((AssertionError, ValueError)):
            _make_key_from_obj('names.key', self.obj, scene)

    def test_illegal_identifier_characters_remain_errors_not_advisories(self):
        self.obj.sith_model3do_hnode_name = 'broken#joint'
        self.path.write_bytes(b'previous export')
        with self.assertRaises(AssertionError):
            self.export()
        self.assertEqual(self.path.read_bytes(), b'previous export')
