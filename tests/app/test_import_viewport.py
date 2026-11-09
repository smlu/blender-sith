"""Optional foreground framing must not disturb selection or fail a valid import."""
import contextlib
from types import SimpleNamespace
from unittest import mock

import bpy

from app.support import SceneTestCase
from fixtures import TV
from sith import app


class ImportViewportTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        self.existing = bpy.data.objects.new('keep_active', None)
        bpy.context.scene.collection.objects.link(self.existing)
        self.existing.select_set(True)
        bpy.context.view_layer.objects.active = self.existing
        self.space = SimpleNamespace(type='VIEW_3D', shading=SimpleNamespace(), overlay=SimpleNamespace(),
                                     lock_object=self.existing, lens=35,
                                     region_3d=SimpleNamespace(view_perspective='PERSP'))
        area = SimpleNamespace(type='VIEW_3D', regions=[SimpleNamespace(type='WINDOW')], spaces=[self.space])
        self.context = SimpleNamespace(window=object(), screen=SimpleNamespace(areas=[area]), mode='OBJECT',
                                       view_layer=bpy.context.view_layer, selected_objects=[self.existing],
                                       temp_override=lambda **kwargs: contextlib.nullcontext())
        self.options = SimpleNamespace(filepath=str(TV / 'model/triangle.3do'), mat_dir='', cmp_file='',
                                       uv_absolute_3do_2_1=True, vertex_colors=True, import_radius_objects=False,
                                       preserve_order=True, clear_scene=False, allow_errors=False,
                                       set_3d_view=True, report=mock.Mock())
        self.view_ops = SimpleNamespace(**{name: mock.Mock(return_value={'FINISHED'}) for name in
                                          ('view_center_lock', 'view_axis', 'view_selected')})

    def execute(self):
        # Real Blender data and real resource import; only the unavailable
        # foreground viewport context/operators are modeled in background tests.
        def select_grouped(**kwargs):
            for obj in bpy.context.view_layer.objects.active.children_recursive:
                obj.select_set(True)
            return {'FINISHED'}

        def select_all(**kwargs):
            for obj in bpy.context.view_layer.objects:
                obj.select_set(False)
            return {'FINISHED'}

        object_ops = SimpleNamespace(select_grouped=select_grouped, select_all=select_all)
        api = SimpleNamespace(app=SimpleNamespace(background=False),
                              ops=SimpleNamespace(object=object_ops, view3d=self.view_ops))
        with mock.patch.object(app, 'bpy', api):
            return app.ImportModel3do.execute(self.options, self.context)

    def assert_selection_restored(self):
        self.assertEqual(bpy.context.view_layer.objects.active, self.existing)
        self.assertEqual(list(bpy.context.selected_objects), [self.existing])
        self.assertEqual(self.space.lock_object, self.existing)

    def test_framing_restores_selection_and_existing_view_lock(self):
        self.assertEqual(self.execute(), {'FINISHED'})
        self.assert_selection_restored()
        self.view_ops.view_axis.assert_called_once()
        self.assertEqual(sum(obj.type == 'MESH' for obj in bpy.data.objects), 1)

    def test_viewport_operator_failure_keeps_import_and_restores_selection(self):
        def fail_view_axis(**kwargs):
            self.space.region_3d.view_perspective = 'ORTHO'
            raise RuntimeError('Viewport is unavailable')
        self.view_ops.view_axis.side_effect = fail_view_axis
        self.assertEqual(self.execute(), {'FINISHED'})
        self.assert_selection_restored()
        self.assertEqual(sum(obj.type == 'MESH' for obj in bpy.data.objects), 1)
        self.assertTrue(any('WARNING' in call.args[0] for call in self.options.report.call_args_list))
        self.assertEqual(self.space.region_3d.view_perspective, 'PERSP')

    def test_non_object_mode_skips_optional_framing(self):
        self.context.mode = 'EDIT_MESH'
        self.assertEqual(self.execute(), {'FINISHED'})
        self.assert_selection_restored()
        self.view_ops.view_axis.assert_not_called()
        self.assertEqual(self.space.lens, 35)

    def test_multiple_or_empty_selections_restore_their_actual_active_object(self):
        other = bpy.data.objects.new('also_selected', None)
        bpy.context.scene.collection.objects.link(other)
        for active, selection in ((other, (self.existing, other)), (None, ()), (None, (self.existing,))):
            with self.subTest(active=active.name if active else None, selected=len(selection)):
                for obj in bpy.context.view_layer.objects:
                    obj.select_set(False)
                for obj in selection:
                    obj.select_set(True)
                bpy.context.view_layer.objects.active = active
                self.context.selected_objects = list(selection)
                self.assertEqual(self.execute(), {'FINISHED'})
                self.assertEqual(bpy.context.view_layer.objects.active, active)
                self.assertEqual(set(bpy.context.selected_objects), set(selection))
                self.assertEqual(self.space.lock_object, self.existing)

    def test_missing_viewport_parts_skip_framing_without_affecting_import(self):
        for missing in ('area', 'region', 'space', 'view'):
            with self.subTest(missing=missing):
                self.space.region_3d = None if missing == 'view' else SimpleNamespace(view_perspective='PERSP')
                area = SimpleNamespace(type='VIEW_3D',
                                       regions=[] if missing == 'region' else [SimpleNamespace(type='WINDOW')],
                                       spaces=[] if missing == 'space' else [self.space])
                self.context.screen.areas = [] if missing == 'area' else [area]
                self.assertEqual(self.execute(), {'FINISHED'})
                self.assert_selection_restored()
                self.view_ops.view_axis.assert_not_called()
                self.assertEqual(self.space.lens, 35)
