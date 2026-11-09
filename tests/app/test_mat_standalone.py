"""Standalone MAT export keeps the selected datablock across menu/file contexts."""
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
from unittest import mock

import bpy
import numpy as np

from app.support import SceneTestCase
from core.test_mat_writer import decode, expected_pixels
from fixtures import cmp_bytes
from sith import app
from sith.material import ColorMap, exportMat, importMat
from sith.material.mat import kMatCelImagePrefix, kMatMissingPixels


class StandaloneMatTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.palette_path = self.folder / 'palette.cmp'
        self.palette_path.write_bytes(cmp_bytes())
        self.palette = ColorMap.load(self.palette_path)
        self.pixels = np.array([(1, 0, 0, 1), (0, 1, 0, 0),
                               (0, 0, 1, 0.5), (1, 1, 1, 1)], dtype=np.float32)
        self.image = self.make_image('texture.png', 2, 2, self.pixels)
        self.other = self.make_image('other', 1, 1, [(0, 1, 0, 1)])
        self.material = bpy.data.materials.new('multi.mat')
        self.material[kMatCelImagePrefix + '0'] = self.image
        self.material[kMatCelImagePrefix + '1'] = self.other

    def make_image(self, name, width, height, pixels):
        image = bpy.data.images.new(name, width, height, float_buffer=True)
        image.pixels.foreach_set(np.asarray(pixels, dtype=np.float32).ravel())
        image.update()
        return image

    def operator(self, source, destination, **options):
        with bpy.context.temp_override(sith_mat_export_source=source):
            return bpy.ops.export_material.sith_mat(filepath=str(destination), **options)

    def owner(self):
        return SimpleNamespace(_source=None, filepath='', filename_ext='.mat',
                               overwrite_existing=False, check_existing=False, encoding='RGBA32',
                               cmp_file='', generate_mipmaps=True, target='SITH', report=mock.Mock())

    def capture(self, source):
        owner = self.owner()
        with mock.patch.object(app.ExportHelper, 'invoke', return_value={'RUNNING_MODAL'}):
            self.assertEqual(app.ExportMat.invoke(owner, SimpleNamespace(sith_mat_export_source=source), None),
                             {'RUNNING_MODAL'})
        return owner

    def assert_menu(self, draw, context, source):
        layout = mock.Mock()
        draw(SimpleNamespace(layout=layout), context)
        row = layout.row.return_value
        row.context_pointer_set.assert_called_once_with('sith_mat_export_source', source)
        row.operator.assert_called_once_with(app.ExportMat.bl_idname, text='Export to MAT...', icon='EXPORT')
        self.assertEqual(row.operator_context, 'INVOKE_DEFAULT')

    def test_registered_operator_exports_images_and_all_material_cels_in_every_encoding(self):
        for source, count in ((self.image, 1), (self.material, 2)):
            for encoding in ('RGBA32', 'RGB24', 'RGB565', 'RGBA4444', 'RGBA1555', 'INDEXED'):
                with self.subTest(source=source.name, encoding=encoding):
                    target = self.folder / f'{count}-{encoding}.mat'
                    self.assertEqual(self.operator(source, target, encoding=encoding,
                                     cmp_file=str(self.palette_path)), {'FINISHED'})
                    header, records, cels = decode(target.read_bytes(), self.palette)
                    self.assertEqual(header.texture_count, count)
                    self.assertEqual([record.cel_idx for record in records], list(range(count)))
                    self.assertEqual((cels[0].width, cels[0].height), (2, 2))
                    for cel, image in zip(cels, (self.image, self.other)):
                        pixels = np.asarray(image.pixels[:]).reshape((cel.height, cel.width, 4))
                        np.testing.assert_allclose(np.asarray(cel.pixel_data_array[0]).reshape(pixels.shape),
                                                   expected_pixels(pixels, encoding, self.palette),
                                                   atol=1e-12, rtol=0)
        np.testing.assert_array_equal(np.asarray(self.image.pixels[:]).reshape(-1, 4), self.pixels)
        self.assertEqual(self.material[kMatCelImagePrefix + '0'], self.image)
        self.assertEqual(self.material[kMatCelImagePrefix + '1'], self.other)

    def test_every_encoding_reimports_all_cels_with_expected_colors_and_alpha(self):
        # Exercise Blender -> MAT -> Blender, not just the matching binary
        # reader. Unequal channels expose RGB/alpha swaps in either adapter.
        pixels = np.array([(0.2, 0.4, 0.6, 0.3), (0.7, 0.3, 0.1, 0),
                           (0.1, 0.8, 0.4, 0.5), (0.9, 0.2, 0.7, 1)], dtype=np.float32)
        self.image.pixels.foreach_set(pixels.ravel())
        self.image.update()
        for encoding in ('RGBA32', 'RGB24', 'RGB565', 'RGBA4444', 'RGBA1555', 'INDEXED'):
            with self.subTest(encoding=encoding):
                target = self.folder / f'reimport-{encoding}.mat'
                self.assertEqual(self.operator(self.material, target, encoding=encoding,
                                               cmp_file=str(self.palette_path)), {'FINISHED'})
                restored = importMat(target, self.palette)
                for index, image in enumerate((self.image, self.other)):
                    actual = restored[kMatCelImagePrefix + str(index)]
                    self.assertEqual(tuple(actual.size), tuple(image.size))
                    expected = expected_pixels(np.asarray(image.pixels[:]).reshape((-1, 4)),
                                               encoding, self.palette)
                    # Byte-backed Blender images add an 8-bit storage step
                    # after decoding the MAT's 5/6-bit normalized channels.
                    if not actual.is_float:
                        expected = np.floor(expected * 255 + 0.5) / 255
                    np.testing.assert_allclose(np.asarray(actual.pixels[:]).reshape((-1, 4)), expected,
                                               atol=1e-6, rtol=0)
        np.testing.assert_array_equal(np.asarray(self.image.pixels[:]).reshape((-1, 4)), pixels)

    def test_material_without_cel_bindings_uses_its_resolved_color_image(self):
        material = bpy.data.materials.new('ordinary')
        material.use_nodes = True
        shader = next(node for node in material.node_tree.nodes if node.type == 'BSDF_PRINCIPLED')
        texture = material.node_tree.nodes.new('ShaderNodeTexImage')
        texture.image = self.image
        material.node_tree.links.new(texture.outputs['Color'], shader.inputs['Base Color'])
        target = self.folder / 'ordinary.mat'
        self.assertTrue(exportMat(material, target))
        self.assertEqual(decode(target.read_bytes())[0].texture_count, 1)

    def test_image_selection_never_expands_to_a_material_that_uses_it(self):
        target = self.folder / 'image.mat'
        self.assertTrue(exportMat(self.image, target, generateMipmaps=False))
        _, _, cels = decode(target.read_bytes())
        self.assertEqual(len(cels), 1)
        self.assertEqual(len(cels[0].pixel_data_array), 1)

    def test_outliner_menu_uses_active_id_not_other_selected_ids_or_active_material(self):
        space = SimpleNamespace(type='OUTLINER', display_mode='LIBRARIES')
        for source in (self.image, self.material):
            context = SimpleNamespace(space_data=space, area=SimpleNamespace(type='OUTLINER'),
                                      id=source, selected_ids=[self.other, source], material=self.other)
            self.assert_menu(app.menu_export_mat_outliner, context, source)
            self.assertIs(app._get_mat_export_source(context), source)

    def test_outliner_menu_hides_for_non_exportable_ids(self):
        for mode, source in (('LIBRARIES', None), ('LIBRARIES', bpy.context.scene),
                             ('VIEW_LAYER', bpy.context.scene), ('DATA_API', bpy.context.scene)):
            layout = mock.Mock()
            context = SimpleNamespace(space_data=SimpleNamespace(type='OUTLINER', display_mode=mode), id=source)
            app.menu_export_mat_outliner(SimpleNamespace(layout=layout), context)
            layout.row.assert_not_called()
        context = SimpleNamespace(area=SimpleNamespace(type='OUTLINER'), id=None, material=self.material)
        self.assertIsNone(app._get_mat_export_source(context))

    def test_outliner_valid_datablocks_work_in_other_display_modes(self):
        for mode in ('LIBRARIES', 'VIEW_LAYER', 'ORPHAN_DATA', 'DATA_API'):
            for source in (self.material, self.image):
                context = SimpleNamespace(space_data=SimpleNamespace(type='OUTLINER', display_mode=mode),
                                          area=SimpleNamespace(type='OUTLINER'), id=source)
                self.assert_menu(app.menu_export_mat_outliner, context, source)
                self.assertIs(app._get_mat_export_source(context), source)

    def test_outliner_without_active_id_accepts_only_one_unambiguous_selected_id(self):
        for source in (self.material, self.image):
            context = SimpleNamespace(space_data=SimpleNamespace(type='OUTLINER'),
                                      area=SimpleNamespace(type='OUTLINER'), selected_ids=(source,))
            self.assert_menu(app.menu_export_mat_outliner, context, source)
            self.assertIs(app._get_mat_export_source(context), source)
        for selected in (None, (), (self.image, self.material), (self.material, bpy.context.scene)):
            context = SimpleNamespace(space_data=SimpleNamespace(type='OUTLINER'),
                                      area=SimpleNamespace(type='OUTLINER'), id=None, selected_ids=selected)
            layout = mock.Mock()
            app.menu_export_mat_outliner(SimpleNamespace(layout=layout), context)
            layout.row.assert_not_called()
            self.assertIsNone(app._get_mat_export_source(context))

    def test_outliner_active_non_material_does_not_fall_back_to_a_selected_material(self):
        context = SimpleNamespace(space_data=SimpleNamespace(type='OUTLINER'),
                                  area=SimpleNamespace(type='OUTLINER'), id=bpy.context.scene,
                                  selected_ids=[self.material], material=self.material)
        self.assertIsNone(app._get_mat_export_source(context))
        layout = mock.Mock()
        app.menu_export_mat_outliner(SimpleNamespace(layout=layout), context)
        layout.row.assert_not_called()

    def test_material_slot_rmb_uses_clicked_row_not_active_material(self):
        active = bpy.data.materials.new('different active material')
        context = SimpleNamespace(ui_list=SimpleNamespace(bl_idname='MATERIAL_UL_matslots'),
                                  id=self.material, material=active,
                                  material_slot=SimpleNamespace(material=self.material))
        self.assert_menu(app.menu_export_mat_material_slot, context, self.material)

    def test_material_slot_rmb_uses_row_slot_if_id_is_missing(self):
        context = SimpleNamespace(ui_list=SimpleNamespace(bl_idname='MATERIAL_UL_matslots'),
                                  material_slot=SimpleNamespace(material=self.material))
        self.assert_menu(app.menu_export_mat_material_slot, context, self.material)

    def test_material_slot_rmb_hides_for_empty_rows_and_unrelated_lists(self):
        for kind, source, slot in (('MATERIAL_UL_matslots', None, None),
                                   ('MATERIAL_UL_matslots', self.image, self.material),
                                   ('UI_UL_list', self.material, self.material),
                                   (None, self.material, self.material)):
            context = SimpleNamespace(ui_list=SimpleNamespace(bl_idname=kind), id=source,
                                      material_slot=SimpleNamespace(material=slot), material=self.material)
            layout = mock.Mock()
            app.menu_export_mat_material_slot(SimpleNamespace(layout=layout), context)
            layout.row.assert_not_called()

    def test_image_and_material_menus_bind_their_own_datablocks(self):
        self.assert_menu(app.menu_export_mat_image,
                         SimpleNamespace(space_data=SimpleNamespace(image=self.image)), self.image)
        self.assert_menu(app.menu_export_mat_material, SimpleNamespace(material=self.material), self.material)
        for draw, context in ((app.menu_export_mat_image, SimpleNamespace(space_data=SimpleNamespace(image=None))),
                              (app.menu_export_mat_material, SimpleNamespace(material=None))):
            layout = mock.Mock()
            draw(SimpleNamespace(layout=layout), context)
            layout.row.assert_not_called()

    def test_real_image_editor_and_material_contexts_execute_without_an_object(self):
        area = bpy.context.screen.areas[0]
        previous = area.type
        try:
            area.type = 'IMAGE_EDITOR'
            area.spaces.active.image = self.image
            with bpy.context.temp_override(area=area):
                self.assertIs(app._get_mat_export_source(bpy.context), self.image)
                self.assertEqual(bpy.ops.export_material.sith_mat(filepath=str(self.folder / 'editor.mat')), {'FINISHED'})
            area.spaces.active.image = None
            with bpy.context.temp_override(area=area, material=self.material):
                self.assertIsNone(app._get_mat_export_source(bpy.context))
        finally:
            area.type = previous
        with bpy.context.temp_override(material=self.material):
            self.assertEqual(bpy.ops.export_material.sith_mat(filepath=str(self.folder / 'slots.mat')), {'FINISHED'})
        self.assertEqual(decode((self.folder / 'slots.mat').read_bytes())[0].texture_count, 2)

    def test_file_browser_retains_identity_after_rename_and_context_change(self):
        for source, expected_cels in ((self.image, 1), (self.material, 2)):
            owner = self.capture(source)
            self.assertIs(owner._source, source)
            self.assertTrue(owner.filepath.endswith('.mat'))
            self.assertNotIn('.png', owner.filepath)
            source.name = 'renamed while choosing output'
            owner.filepath = str(self.folder / f'captured-{expected_cels}.mat')
            context = SimpleNamespace(sith_mat_export_source=self.other)
            self.assertEqual(app.ExportMat.execute(owner, context), {'FINISHED'})
            self.assertEqual(decode(Path(owner.filepath).read_bytes())[0].texture_count, expected_cels)

    def test_two_operator_instances_do_not_share_captured_sources(self):
        first, second = self.capture(self.image), self.capture(self.material)
        self.assertIs(first._source, self.image)
        self.assertIs(second._source, self.material)
        for owner, count in ((first, 1), (second, 2)):
            owner.filepath = str(self.folder / f'instance-{count}.mat')
            self.assertEqual(app.ExportMat.execute(owner, SimpleNamespace()), {'FINISHED'})
            self.assertEqual(decode(Path(owner.filepath).read_bytes())[0].texture_count, count)

    def test_deleted_captured_source_cancels_without_falling_back(self):
        owner = self.capture(self.image)
        owner.filepath = str(self.folder / 'deleted.mat')
        bpy.data.images.remove(self.image)
        self.assertEqual(app.ExportMat.execute(owner, SimpleNamespace(sith_mat_export_source=self.other)), {'CANCELLED'})
        self.assertFalse(Path(owner.filepath).exists())
        self.assertEqual(owner.report.call_args.args[0], {'ERROR'})

    def test_missing_source_and_path_cancel_before_writing(self):
        owner = self.owner()
        self.assertEqual(app.ExportMat.invoke(owner, SimpleNamespace(), None), {'CANCELLED'})
        self.assertEqual(app.ExportMat.execute(owner, SimpleNamespace()), {'CANCELLED'})
        owner._source = self.image
        self.assertEqual(app.ExportMat.execute(owner, SimpleNamespace()), {'CANCELLED'})
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), ['palette.cmp'])

    def test_existing_file_is_kept_and_overwrite_requires_explicit_opt_in(self):
        target = self.folder / 'existing.mat'
        target.write_bytes(b'previous material')
        self.assertEqual(self.operator(self.image, target, encoding='INDEXED'), {'CANCELLED'})
        self.assertEqual(target.read_bytes(), b'previous material')
        self.assertEqual(self.operator(self.image, target, overwrite_existing=True), {'FINISHED'})
        self.assertEqual(decode(target.read_bytes())[0].texture_count, 1)

    def test_invalid_pixels_palette_and_later_cel_keep_previous_output(self):
        target = self.folder / 'protected.mat'
        target.write_bytes(b'previous material')
        with self.assertRaisesRegex(RuntimeError, 'CMP palette'):
            self.operator(self.image, target, encoding='INDEXED', overwrite_existing=True)
        self.assertEqual(target.read_bytes(), b'previous material')
        self.image[kMatMissingPixels] = True
        with self.assertRaisesRegex(ValueError, 'no exportable'):
            exportMat(self.image, target, overwrite=True)
        del self.image[kMatMissingPixels]
        self.material[kMatCelImagePrefix + '1'] = 'invalid image'
        with self.assertRaisesRegex(ValueError, 'invalid image binding'):
            exportMat(self.material, target, overwrite=True)
        self.assertEqual(target.read_bytes(), b'previous material')

    def test_relative_cmp_nested_output_and_grim_target(self):
        target = self.folder / 'grim.mat'
        self.assertEqual(self.operator(self.material, target, target='GRIM', cmp_file='palette.cmp'), {'FINISHED'})
        header, _, cels = decode(target.read_bytes(), self.palette)
        self.assertEqual((header.type, header.color_info.bpp, len(cels)), (3, 8, 2))
        self.assertEqual([len(cel.pixel_data_array) for cel in cels], [1, 1])
        self.assertTrue(exportMat(self.image, self.folder / 'new/folders/image.mat'))
        self.assertTrue((self.folder / 'new/folders/image.mat').is_file())

    def test_plain_shader_material_and_invalid_destination_fail_safely(self):
        material = bpy.data.materials.new('no image')
        material.use_nodes = True
        target = self.folder / 'safe.mat'
        with self.assertRaisesRegex(ValueError, 'no exportable texture'):
            exportMat(material, target)
        with self.assertRaisesRegex(ValueError, 'end with .mat'):
            exportMat(self.image, self.folder / 'not-a-mat.png')
        with self.assertRaisesRegex(ValueError, 'Select a material or image'):
            exportMat(bpy.context.scene, target)
        self.assertFalse(target.exists())

    def test_defaults_conditional_options_and_overwrite_confirmation(self):
        props = bpy.ops.export_material.sith_mat.get_rna_type().properties
        self.assertEqual(props['encoding'].default, 'RGBA32')
        self.assertFalse(props['overwrite_existing'].default)
        self.assertFalse(props['check_existing'].default)
        for target, encoding in (('SITH', 'RGBA32'), ('SITH', 'INDEXED'), ('GRIM', 'INDEXED')):
            layout = mock.Mock()
            owner = SimpleNamespace(layout=layout, target=target, encoding=encoding)
            app.ExportMat.draw(owner, None)
            names = [call.args[1] for call in layout.mock_calls if call[0].endswith('prop')]
            self.assertEqual('cmp_file' in names, encoding == 'INDEXED')
            self.assertEqual('generate_mipmaps' in names, target != 'GRIM')
            self.assertEqual(layout.row.return_value.enabled, target != 'GRIM')
        owner = self.owner()
        owner.target = 'GRIM'
        app._on_mat_target_update(owner, None)
        self.assertEqual(owner.encoding, 'INDEXED')
        for overwrite in (True, False):
            owner.overwrite_existing = overwrite
            app._on_mat_overwrite_update(owner, None)
            self.assertEqual(owner.check_existing, overwrite)

    def test_linked_material_is_read_only_input_and_library_is_unchanged(self):
        library = self.folder / 'linked.blend'
        self.image.pack()
        self.other.pack()
        bpy.data.libraries.write(str(library), {self.material})
        before = library.read_bytes()
        with bpy.data.libraries.load(str(library), link=True) as (_, destination):
            destination.materials = [self.material.name]
        material = destination.materials[0]
        self.assertIsNotNone(material.library)
        self.assertTrue(exportMat(material, self.folder / 'linked.mat'))
        header, _, cels = decode((self.folder / 'linked.mat').read_bytes())
        self.assertEqual(header.texture_count, 2)
        np.testing.assert_allclose(cels[0].pixel_data_array[0][:4], (1, 0, 0, 1), atol=1e-7)
        self.assertEqual(library.read_bytes(), before)

    def test_cleanup_warning_does_not_turn_success_into_failure(self):
        warnings = []
        with mock.patch('sith.material.matExporter.shutil.rmtree', side_effect=OSError('busy')) as cleanup:
            self.assertTrue(exportMat(self.image, self.folder / 'cleanup.mat', warnings=warnings))
        self.addCleanup(shutil.rmtree, cleanup.call_args.args[0], ignore_errors=True)
        self.assertTrue(any('temporary directory' in warning for warning in warnings))

    def test_write_failure_restores_previous_file_and_cleans_staging(self):
        from sith.material import matExporter
        target = self.folder / 'io.mat'
        target.write_bytes(b'previous material')
        replace = matExporter.os.replace
        def fail_new(source, destination):
            if Path(source).name == 'texture' or Path(source).name.startswith('.sith-write-'):
                raise OSError('simulated write failure')
            return replace(source, destination)
        with mock.patch('sith.material.matExporter.os.replace', side_effect=fail_new):
            with self.assertRaisesRegex(OSError, 'simulated'):
                exportMat(self.image, target, overwrite=True)
        self.assertEqual(target.read_bytes(), b'previous material')

    def test_failed_rollback_keeps_recovery_files(self):
        from sith.material.matExporter import ExportRollbackError
        staging = self.folder / 'recovery'
        staging.mkdir()
        with mock.patch('sith.material.matExporter.tempfile.mkdtemp', return_value=str(staging)), \
                mock.patch('sith.material.matExporter.publishExportFiles', side_effect=ExportRollbackError('keep recovery')):
            with self.assertRaisesRegex(ExportRollbackError, 'keep recovery'):
                exportMat(self.image, self.folder / 'recovery.mat')
        self.assertTrue((staging / 'texture').is_file())

    def test_all_menu_callbacks_are_registered_once(self):
        for menu, callback in ((bpy.types.OUTLINER_MT_context_menu, app.menu_export_mat_outliner),
                               (bpy.types.IMAGE_MT_image, app.menu_export_mat_image),
                               (bpy.types.MATERIAL_MT_context_menu, app.menu_export_mat_material),
                               (bpy.types.UI_MT_list_item_context_menu, app.menu_export_mat_material_slot)):
            self.assertEqual(menu.draw._draw_funcs.count(callback), 1)
