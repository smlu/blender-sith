"""Optional viewport framing must not break real background import operators."""
import bpy
import unittest

from app.support import SceneTestCase
from fixtures import TV
from sith.model.utils import kModel3doImportReport


@unittest.skipUnless(bpy.app.background, 'Requires background Blender')
class BackgroundImportTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        self.existing = bpy.data.objects.new('keep_active', None)
        bpy.context.scene.collection.objects.link(self.existing)
        bpy.context.view_layer.objects.active = self.existing
        self.existing.select_set(True)

    def viewport_state(self):
        screen = bpy.context.screen
        return [(space.as_pointer(), space.lock_object, space.lens, space.region_3d.view_distance)
                for area in screen.areas for space in area.spaces
                if space.type == 'VIEW_3D' and space.region_3d] if screen else []

    def test_default_import_completes_without_touching_viewport_state(self):
        self.assertTrue(bpy.app.background)
        before = self.viewport_state()
        result = bpy.ops.import_scene.sith_3do(filepath=str(TV / 'model/triangle.3do'), clear_scene=False)
        self.assertEqual(result, {'FINISHED'})
        self.assertEqual(self.viewport_state(), before)
        self.assertEqual(bpy.context.view_layer.objects.active, self.existing)
        self.assertTrue(self.existing.select_get())
        self.assertEqual(len([obj for obj in bpy.data.objects if obj.type == 'MESH']), 1)

    def test_explicit_viewport_request_also_skips_background_framing(self):
        before = self.viewport_state()
        result = bpy.ops.import_scene.sith_3do(filepath=str(TV / 'model/triangle.3do'),
                                             clear_scene=False, set_3d_view=True)
        self.assertEqual(result, {'FINISHED'})
        self.assertEqual(self.viewport_state(), before)

    def test_recovery_warning_does_not_trigger_viewport_work(self):
        texts = set(bpy.data.texts)
        def remove_reports():
            for text in list(bpy.data.texts):
                if text not in texts:
                    bpy.data.texts.remove(text)
        self.addCleanup(remove_reports)
        result = bpy.ops.import_scene.sith_3do(filepath=str(TV / 'model/recovery/bad_uvs.3do'),
                                             clear_scene=False, allow_errors=True)
        self.assertEqual(result, {'FINISHED'})
        self.assertEqual(sum(kModel3doImportReport in obj for obj in bpy.data.objects), 1)

    def test_invalid_input_is_still_reported_as_a_failure(self):
        with self.assertRaisesRegex(RuntimeError, 'Cannot import 3DO'):
            bpy.ops.import_scene.sith_3do(filepath=str(TV / 'model/invalid/header_only.3do'), clear_scene=False)
        self.assertEqual(list(bpy.data.objects), [self.existing])
