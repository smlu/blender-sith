"""Unknown flags and wide masks survive Blender edits, storage and round trips."""
from pathlib import Path
import tempfile
from unittest import mock

import bpy

from app.support import SceneTestCase
from fixtures import TV
from sith import app
from sith.key import Key, KeyFlag, KeyNode, Keyframe
from sith.key.keyExporter import exportKey
from sith.key.keyImporter import importKey
from sith.key.keyLoader import loadKey
from sith.key.keyUtils import getSceneKeyFlags, kKeyUnknownFlags, setSceneKeyFlags
from sith.key.keyWriter import saveKey
from sith.model.model3do import Mesh3doNodeFlags, Mesh3doNodeType
from sith.model.model3doExporter import export3do
from sith.model.model3doImporter import import3do
from sith.model.model3doLoader import load3do, Model3doFileVersion
from sith.model.model3doWriter import save3do
from sith.model.utils import kImEulerOrder


class _MaskTestCase(SceneTestCase):
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
        self.reset_metadata()
        self.addCleanup(self.reset_metadata)

        self.obj = bpy.data.objects.new('joint', None)
        self.scene.collection.objects.link(self.obj)
        self.obj.rotation_mode = kImEulerOrder
        self.obj.sith_model3do_hnode_idx = 0
        self.obj.sith_model3do_hnode_name = 'joint'
        bpy.context.view_layer.objects.active = self.obj
        self.obj.select_set(True)

    def reset_metadata(self):
        setSceneKeyFlags(self.scene, KeyFlag(0))
        self.scene.sith_key_types = 'FFFF'

    def path(self, name):
        # Fresh filenames also avoid Windows locks on a just-written resource.
        self.counter += 1
        return self.folder / f'{self.counter:03d}-{name}'

    def import_key(self, flags=0, node_types=0xFFFF, clear=True):
        key, node = Key('source.key'), KeyNode()
        key.numFrames, key.numJoints, key.fps = 5, 1, 30
        key.flags, key.nodeTypes = KeyFlag(flags), Mesh3doNodeType(node_types)
        node.idx, node.meshName, node.keyframes = 0, 'joint', [Keyframe()]
        key.nodes = [node]
        source = self.path('source.key')
        saveKey(key, source, '')
        importKey(source, self.scene, clear, True, False)

    def export_key(self, **options):
        output = self.path('output.key')
        exportKey(self.obj, self.scene, str(output), **options)
        return loadKey(output)

    def metadata(self):
        return (set(self.scene.sith_key_flags), self.scene.get(kKeyUnknownFlags),
                self.scene.sith_key_types, self.scene.render.fps, self.scene.render.fps_base)


class KeyFlagMetadataTests(_MaskTestCase):
    def test_unknown_flags_survive_each_export_target(self):
        # These bits have no enum item, including the high unsigned bit.
        for flags in (0x80, 0x82, 0x10002, 0x80000002, 0xFFFFFFFF):
            for target in ('IJIM', 'JKDF2', 'MOTS', 'CUSTOM'):
                with self.subTest(flags=hex(flags), target=target):
                    self.import_key(flags)
                    self.assertEqual(int(self.export_key(target=target).flags), flags)

    def test_editing_each_known_flag_keeps_unknown_bits(self):
        unknown = 0xFFFFFF80
        self.import_key(unknown | int(KeyFlag.NoLoop))
        for flag in [KeyFlag(0), *KeyFlag]:
            with self.subTest(flag=flag):
                self.scene.sith_key_flags = {flag.name} if flag else set()
                self.assertEqual(int(self.export_key().flags), unknown | int(flag))

    def test_api_known_flag_override_keeps_unknown_bits(self):
        self.import_key(0x80000082)
        before = self.metadata()
        for flags, expected in ((set(), 0x80000080), ({'PauseOnLastFrame'}, 0x80000084)):
            with self.subTest(flags=flags):
                self.assertEqual(int(self.export_key(flags=flags).flags), expected)
                self.assertEqual(self.metadata(), before)

    def test_operator_known_flag_override_keeps_unknown_bits(self):
        self.import_key(0x80000082)
        for flags, expected in ((set(), 0x80000080), ({'PauseOnLastFrame'}, 0x80000084)):
            with self.subTest(flags=flags):
                output = self.path('operator.key')
                self.assertEqual(bpy.ops.export_anim.sith_key(filepath=str(output), flags=flags), {'FINISHED'})
                self.assertEqual(int(loadKey(output).flags), expected)
                self.assertEqual(self.scene.sith_key_flags, flags)
                self.assertEqual(self.scene[kKeyUnknownFlags], '80000080')

    def test_operator_default_keeps_all_imported_flags(self):
        self.import_key(0x80000082)
        before = self.metadata()
        output = self.path('default.key')
        self.assertEqual(bpy.ops.export_anim.sith_key(filepath=str(output)), {'FINISHED'})
        self.assertEqual(int(loadKey(output).flags), 0x80000082)
        self.assertEqual(self.metadata(), before)

    def test_replacement_import_replaces_or_clears_unknown_flags(self):
        for flags in (0x80000082, 0x10004, 2, 0):
            with self.subTest(flags=hex(flags)):
                self.import_key(flags)
                self.assertEqual(int(self.export_key().flags), flags)
                if flags < 0x80:
                    self.assertNotIn(kKeyUnknownFlags, self.scene)

    def test_merge_import_keeps_existing_scene_flags_and_priority(self):
        self.import_key(0x80000082, 0x80010001)
        before = self.metadata()
        self.import_key(0x10004, 0x10002, clear=False)
        self.assertEqual(self.metadata(), before)
        restored = self.export_key()
        self.assertEqual(int(restored.flags), 0x80000082)
        self.assertEqual(int(restored.nodeTypes), 0x80010001)

    def test_failed_import_keeps_flags_priority_and_animation(self):
        self.import_key(0x80000082, 0x80010001)
        before = self.metadata()
        action = self.obj.animation_data.action
        source = self.path('invalid.key')
        key = Key('invalid.key')
        key.numFrames, key.numJoints, key.fps = 0, 0, 30
        saveKey(key, source, '')
        with self.assertRaisesRegex(ValueError, 'positive frame count'):
            importKey(source, self.scene, True, True, False)
        self.assertEqual(self.metadata(), before)
        self.assertEqual(self.obj.animation_data.action, action)

    def test_failed_export_keeps_metadata_and_previous_file(self):
        self.import_key(0x80000082, 0x80010001)
        self.obj.constraints.new('COPY_LOCATION')
        before = self.metadata()
        output = self.path('safe.key')
        output.write_bytes(b'previous export')
        with self.assertRaisesRegex(RuntimeError, 'non-pivot constraints'):
            bpy.ops.export_anim.sith_key(filepath=str(output), flags=set(), node_types='FFFFFFFF')
        self.assertEqual(self.metadata(), before)
        self.assertEqual(output.read_bytes(), b'previous export')

    def test_reading_unset_flags_does_not_store_metadata(self):
        self.assertNotIn(kKeyUnknownFlags, self.scene)
        self.assertEqual(int(getSceneKeyFlags(self.scene)), 0)
        self.assertNotIn(kKeyUnknownFlags, self.scene)

    def test_raw_metadata_cannot_override_known_flag_controls(self):
        # Only extension bits are read from raw storage, even if a script puts
        # known bits there too. The enum remains authoritative for those bits.
        self.scene[kKeyUnknownFlags] = 'FFFFFFFF'
        self.assertEqual(int(self.export_key().flags), 0xFFFFFF80)
        self.scene.sith_key_flags = {'NoLoop'}
        self.assertEqual(int(self.export_key().flags), 0xFFFFFF82)

    def test_extension_bits_can_be_explicitly_cleared(self):
        for remove in (False, True):
            with self.subTest(remove=remove):
                self.import_key(0x80000082)
                if remove:
                    del self.scene[kKeyUnknownFlags]
                else:
                    self.scene[kKeyUnknownFlags] = '0'
                self.assertEqual(int(self.export_key().flags), 2)

    def test_flags_and_masks_survive_blend_serialization(self):
        self.import_key(0x80000082, 0x80010001)
        self.obj.sith_model3do_hnode_flags = 'FFFFFFFF'
        self.obj.sith_model3do_hnode_type = '80000008'
        library = self.path('metadata.blend')
        bpy.data.libraries.write(str(library), {self.scene})
        with bpy.data.libraries.load(str(library)) as (source, destination):
            destination.scenes = [self.scene.name]
        restored_scene = destination.scenes[0]
        self.addCleanup(bpy.data.scenes.remove, restored_scene)
        restored_joint = next(obj for obj in restored_scene.objects
                              if obj.sith_model3do_hnode_name == 'joint')
        self.assertEqual(restored_scene[kKeyUnknownFlags], '80000080')
        self.assertEqual(restored_scene.sith_key_types, '80010001')
        self.assertEqual(restored_joint.sith_model3do_hnode_flags, 'FFFFFFFF')
        self.assertEqual(restored_joint.sith_model3do_hnode_type, '80000008')
        output = self.path('reloaded.key')
        exportKey(restored_joint, restored_scene, str(output))
        restored_key = loadKey(output)
        self.assertEqual(int(restored_key.flags), 0x80000082)
        self.assertEqual(int(restored_key.nodeTypes), 0x80010001)


class HexMaskMetadataTests(_MaskTestCase):
    def test_all_scene_and_object_hex_fields_retain_wide_masks(self):
        fields = ((self.scene, 'sith_key_types'), (self.obj, 'sith_model3do_hnode_flags'),
                  (self.obj, 'sith_model3do_hnode_type'))
        for owner, name in fields:
            for value in ('0', 'ffff', '10000', '10001', '0x12345678', '80000000', 'FFFFFFFF'):
                with self.subTest(name=name, value=value):
                    setattr(owner, name, value)
                    stored = getattr(owner, name)
                    self.assertTrue(stored)
                    self.assertEqual(int(stored, 16), int(value, 16))
                    self.assertEqual(stored, owner[name])

    def test_invalid_hex_edit_keeps_prior_wide_value(self):
        for owner, name in ((self.scene, 'sith_key_types'), (self.obj, 'sith_model3do_hnode_flags'),
                            (self.obj, 'sith_model3do_hnode_type')):
            setattr(owner, name, '80010001')
            for invalid in ('GG', '0x', 'not_hex'):
                with self.subTest(name=name, invalid=invalid):
                    setattr(owner, name, invalid)
                    self.assertEqual(getattr(owner, name), '80010001')

    def test_clearing_hex_fields_restores_their_defaults(self):
        for owner, name, expected in ((self.scene, 'sith_key_types', 'FFFF'),
                                       (self.obj, 'sith_model3do_hnode_flags', ''),
                                       (self.obj, 'sith_model3do_hnode_type', '01')):
            with self.subTest(name=name):
                setattr(owner, name, '80010001')
                setattr(owner, name, '')
                self.assertEqual(getattr(owner, name), expected)

    def test_wide_key_priority_masks_survive_import_export(self):
        for value in (0, 0xFFFF, 0x10000, 0x10001, 0x80000000, 0xFFFFFFFF):
            with self.subTest(mask=hex(value)):
                self.import_key(node_types=value)
                self.assertEqual(int(self.scene.sith_key_types, 16), value)
                self.assertEqual(int(self.export_key().nodeTypes), value)

    def test_operator_retains_scene_masks_and_explicit_wide_overrides(self):
        self.import_key(node_types=0x80010001)
        for options, expected in (({}, 0x80010001), ({'node_types': '10000'}, 0x10000),
                                  ({'node_types': 'FFFFFFFF'}, 0xFFFFFFFF), ({'node_types': '0'}, 0)):
            with self.subTest(options=options):
                output = self.path('operator-mask.key')
                self.assertEqual(bpy.ops.export_anim.sith_key(filepath=str(output), **options), {'FINISHED'})
                self.assertEqual(int(loadKey(output).nodeTypes), expected)
                self.assertEqual(int(self.scene.sith_key_types, 16), expected)

    def test_export_dialog_copies_a_wide_priority_mask(self):
        self.scene.sith_key_types = '80010001'
        operator = mock.Mock(filename_ext='.key')
        with mock.patch.object(app.ExportHelper, 'invoke', return_value={'RUNNING_MODAL'}):
            self.assertEqual(app.ExportKey.invoke(operator, bpy.context, None), {'RUNNING_MODAL'})
        self.assertEqual(operator.node_types, '80010001')

    def test_model_joint_masks_survive_all_versions_order_and_sync_modes(self):
        expected = [(0x80010001, 0x10002), (0xFFFFFFFF, 0x80000008)]
        for version in Model3doFileVersion:
            for preserve in (False, True):
                for sync in (False, True):
                    with self.subTest(version=version, preserve=preserve, sync=sync):
                        self.clear_data()
                        model, _ = load3do(TV / 'model' / 'triangle.3do')
                        for node, (flags, node_type) in zip(model.meshHierarchy, expected):
                            node.flags, node.type = Mesh3doNodeFlags(flags), Mesh3doNodeType(node_type)
                        source, output = self.path('source.3do'), self.path('output.3do')
                        save3do(model, source, version, '')

                        # Verify the Blender properties themselves, then serialize
                        # and reparse. No matching is inferred from object names.
                        root = import3do(source, uvAbsolute_2_1=False, preserveOrder=preserve, clearScene=False)
                        joints = sorted(root.children_recursive, key=lambda obj: obj.sith_model3do_hnode_idx)
                        self.assertEqual([(int(obj.sith_model3do_hnode_flags, 16),
                                           int(obj.sith_model3do_hnode_type, 16)) for obj in joints], expected)
                        export3do(root, str(output), version, False, True, sync)
                        restored, _ = load3do(output)
                        self.assertEqual([(int(node.flags), int(node.type))
                                          for node in restored.meshHierarchy], expected)
