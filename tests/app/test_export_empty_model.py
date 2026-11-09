"""Helper-only exports fail without damaging files; real meshless joints remain valid."""
from pathlib import Path
import tempfile

import bpy

from app.support import SceneTestCase
from fixtures import TV
from sith.key.keyExporter import exportKey
from sith.key.keyLoader import loadKey
from sith.key.keyUtils import setSceneKeyFlags
from sith.model.model3doExporter import export3do
from sith.model.model3doImporter import import3do
from sith.model.model3doLoader import load3do, Model3doFileVersion
from sith.model.utils import kImEulerOrder, kMeshRadius, kModelRadius, kModel3doRadiusKind


class EmptyModelExportTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.counter = 0
        self.scene = bpy.context.scene
        self.scene.frame_start, self.scene.frame_end = 0, 4
        self.scene.render.fps, self.scene.render.fps_base = 30, 1
        self.scene.timeline_markers.clear()
        setSceneKeyFlags(self.scene, 0)
        self.scene.sith_key_types = 'FFFF'

    def path(self, suffix):
        self.counter += 1
        return self.folder / f'{self.counter:03d}-export.{suffix}'

    def empty(self, name, parent=None):
        obj = bpy.data.objects.new(name, None)
        self.scene.collection.objects.link(obj)
        obj.parent = parent
        obj.rotation_mode = kImEulerOrder
        return obj

    def helper(self, kind, *, detach=True, legacy=False):
        self.clear_data()
        self.root = import3do(TV / 'model' / 'triangle.3do', importRadiusObj=True, clearScene=False)
        helper = next(obj for obj in self.root.children_recursive if obj.get(kModel3doRadiusKind) == kind)
        helper.hide_viewport = False
        helper.hide_set(False)
        if detach:
            helper.parent = None
        if legacy:
            del helper[kModel3doRadiusKind]
        return helper

    def activate(self, obj):
        bpy.context.view_layer.update()
        for selected in bpy.context.selected_objects:
            selected.select_set(False)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

    def assert_rejected(self, *, existing=True):
        for operator, extension, fixture in ((bpy.ops.export_scene.sith_3do, '3do', TV / 'model' / 'triangle.3do'),
                                              (bpy.ops.export_anim.sith_key, 'key', TV / 'key' / 'fractional.key')):
            with self.subTest(extension=extension):
                output = self.path(extension)
                previous = fixture.read_bytes()
                if existing:
                    output.write_bytes(previous)
                with self.assertRaisesRegex(RuntimeError, 'No exportable joints'):
                    operator(filepath=str(output))
                if existing:
                    self.assertEqual(output.read_bytes(), previous)
                else:
                    self.assertFalse(output.exists())

    def test_detached_imported_helpers_do_not_replace_exports(self):
        for kind in (kMeshRadius, kModelRadius):
            for legacy in (False, True):
                with self.subTest(kind=kind, legacy=legacy):
                    self.activate(self.helper(kind, legacy=legacy))
                    self.assert_rejected()

    def test_helper_only_selection_does_not_create_output(self):
        self.activate(self.helper(kMeshRadius))
        self.assert_rejected(existing=False)

    def test_wrapper_containing_only_helpers_is_rejected(self):
        for kind in (kMeshRadius, kModelRadius):
            with self.subTest(kind=kind):
                helper = self.helper(kind)
                wrapper = self.empty('helper_only_wrapper')
                helper.parent = wrapper
                self.activate(wrapper)
                self.assert_rejected()

    def test_helper_only_rejection_covers_all_formats_targets_and_file_states(self):
        for kind in (kMeshRadius, kModelRadius):
            self.activate(self.helper(kind))
            cases = [(bpy.ops.export_scene.sith_3do, '3do',
                      {'version': version.name, 'sync_mesh_list': sync})
                     for version in Model3doFileVersion for sync in (False, True)]
            cases += [(bpy.ops.export_anim.sith_key, 'key', {'target': target})
                      for target in ('IJIM', 'JKDF2', 'MOTS', 'CUSTOM')]
            for operator, extension, options in cases:
                for existing in (False, True):
                    with self.subTest(kind=kind, extension=extension, options=options, existing=existing):
                        path = self.path(extension)
                        fixture = TV / ('model/triangle.3do' if extension == '3do' else 'key/fractional.key')
                        before = fixture.read_bytes()
                        if existing:
                            path.write_bytes(before)
                        with self.assertRaisesRegex(RuntimeError, 'No exportable joints'):
                            operator(filepath=str(path), **options)
                        if existing:
                            self.assertEqual(path.read_bytes(), before)
                        else:
                            self.assertFalse(path.exists())

    def test_direct_export_functions_preserve_previous_files_too(self):
        helper = self.helper(kMeshRadius)
        for extension, fixture in (('3do', TV / 'model' / 'triangle.3do'),
                                   ('key', TV / 'key' / 'fractional.key')):
            with self.subTest(extension=extension):
                output = self.path(extension)
                previous = fixture.read_bytes()
                output.write_bytes(previous)
                with self.assertRaisesRegex(ValueError, 'No exportable joints'):
                    if extension == '3do':
                        export3do(helper, str(output), Model3doFileVersion.Version2_3, False, False, True)
                    else:
                        exportKey(helper, self.scene, str(output))
                self.assertEqual(output.read_bytes(), previous)

    def test_selecting_an_owned_helper_still_exports_the_real_model(self):
        helper = self.helper(kMeshRadius, detach=False)
        owner = helper.parent
        owner.keyframe_insert(data_path='location', frame=0)
        self.activate(helper)
        model_path, key_path = self.path('3do'), self.path('key')
        self.assertEqual(bpy.ops.export_scene.sith_3do(filepath=str(model_path)), {'FINISHED'})
        model, _ = load3do(model_path)
        self.assertEqual([node.name for node in model.meshHierarchy], ['root', 'head'])
        self.assertEqual(bpy.ops.export_anim.sith_key(filepath=str(key_path)), {'FINISHED'})
        key = loadKey(key_path)
        self.assertEqual(key.numJoints, 2)
        self.assertEqual([node.meshName for node in key.nodes], ['head'])

    def assert_meshless_joint_exports(self):
        model_path, key_path = self.path('3do'), self.path('key')
        self.assertEqual(bpy.ops.export_scene.sith_3do(filepath=str(model_path)), {'FINISHED'})
        model, _ = load3do(model_path)
        self.assertEqual(len(model.meshHierarchy), 1)
        self.assertEqual(model.geosets[0].meshes, [])
        self.assertEqual(bpy.ops.export_anim.sith_key(filepath=str(key_path)), {'FINISHED'})
        key = loadKey(key_path)
        self.assertEqual(key.numJoints, 1)
        self.assertEqual(key.nodes, [])

    def test_meshless_static_joint_is_not_mistaken_for_an_empty_model(self):
        self.activate(self.empty('joint'))
        self.assert_meshless_joint_exports()

    def test_meshless_joint_with_a_helper_is_valid_inside_a_model_wrapper(self):
        helper = self.helper(kMeshRadius)
        wrapper = self.empty('model_wrapper')
        joint = self.empty('joint', wrapper)
        helper.parent = joint
        self.activate(wrapper)
        self.assert_meshless_joint_exports()
