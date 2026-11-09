"""Real Blender FYEK import/export, interpolation and safe rejection."""
import copy
from pathlib import Path
import tempfile

import bpy

from app.support import SceneTestCase
from batch.app import compare_keys
from grim_fixtures import binary_key_bytes, changed_word
from sith.key import KeyFileFormat
from sith.key.keyBinary import encodeBinaryKey, readBinaryKey
from sith.key.keyExporter import exportKey
from sith.key.keyImporter import importKey
from sith.key.keyLoader import loadKey
from sith.key.keyUtils import getSceneFrameRate, kKeyBinaryData
from sith.model.utils import kImEulerOrder


class BinaryKeyImportTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.path = self.folder / 'fixture.key'
        self.root = bpy.data.objects.new('model', None)
        bpy.context.scene.collection.objects.link(self.root)
        self.joints = []
        for index, name in enumerate(('root', 'joint', 'unused')):
            obj = bpy.data.objects.new(name, None)
            bpy.context.scene.collection.objects.link(obj)
            obj.parent = self.root
            obj.rotation_mode = kImEulerOrder
            obj.sith_model3do_hnode_idx = index
            obj.sith_model3do_hnode_name = name
            self.joints.append(obj)
        bpy.context.view_layer.objects.active = self.root
        self.root.select_set(True)

    def load(self, **options):
        data, _ = binary_key_bytes(**options)
        self.path.write_bytes(data)
        importKey(self.path, bpy.context.scene, True, True, False)
        return readBinaryKey(data)

    def test_binary_import_animates_the_first_record_and_uses_global_deltas(self):
        self.load(first_animated=True, duplicates=False)
        bpy.context.scene.frame_set(1)
        self.assert_vector(self.joints[0].location, (1.5, 2, 3))
        self.assert_vector(self.joints[1].location, (1.5, 2, 3))
        self.assertAlmostEqual(getSceneFrameRate(bpy.context.scene), 15)
        self.assertIn(kKeyBinaryData, self.root)

    def test_global_no_interpolation_holds_until_next_entry(self):
        self.load(flags=256)
        for frame, expected in ((0, (1, 2, 3)), (1, (1, 2, 3)), (2, (2, 2, 3))):
            bpy.context.scene.frame_set(frame)
            self.assert_vector(self.joints[1].location, expected)

    def test_public_export_preserves_pose_and_opaque_fields_for_both_flag_modes(self):
        for flags in (0, 256):
            with self.subTest(flags=flags):
                source = self.load(flags=flags, fps=30)
                target = self.folder / 'output.key'
                exportKey(self.root, bpy.context.scene, str(target), target='GRIM')
                self.assertEqual(target.read_bytes()[:4], b'FYEK')
                restored = loadKey(target)
                result = compare_keys(source, restored)
                self.assertEqual(result['differences'], [])
                self.assertEqual(restored.binaryData['unknown'], source.binaryData['unknown'])
                self.assertEqual(restored.binaryData['markerSlots'], source.binaryData['markerSlots'])
                animated = next(node for node in restored.nodes if node.idx == 1)
                self.assertEqual(animated.binaryData['unknown'], source.nodes[1].binaryData['unknown'])
                self.assertAlmostEqual(restored.fps, 30)

    def test_generic_export_remains_text_after_binary_import(self):
        self.load()
        target = self.folder / 'text.key'
        exportKey(self.root, bpy.context.scene, str(target), target='CUSTOM')
        self.assertEqual(loadKey(target).fileFormat, KeyFileFormat.Text)

    def test_malformed_binary_and_unsupported_markers_do_not_clear_existing_animation(self):
        self.load()
        action = self.joints[1].animation_data.action
        before = bpy.context.scene.frame_end
        data, _ = binary_key_bytes()
        for invalid in (data[:-1], changed_word(data, 104, 99, 'i')):
            with self.subTest(size=len(invalid)):
                self.path.write_bytes(invalid)
                with self.assertRaises(ValueError):
                    importKey(self.path, bpy.context.scene, True, True, False)
                self.assertEqual(self.joints[1].animation_data.action, action)
                self.assertEqual(bpy.context.scene.frame_end, before)

    def test_duplicate_frame_uses_grim_last_entry_semantics(self):
        self.load()
        data, offsets = binary_key_bytes()
        self.path.write_bytes(changed_word(data, offsets['node1_entry'] + 56, 0, 'f'))
        importKey(self.path, bpy.context.scene, True, True, False)
        bpy.context.scene.frame_set(0)
        self.assert_vector(self.joints[1].location, (2, 2, 3))

    def test_backwards_frame_preflight_does_not_clear_existing_animation(self):
        self.load()
        action = self.joints[1].animation_data.action
        key = loadKey(self.path)
        entry = copy.deepcopy(key.nodes[1].keyframes[-1])
        entry.frame = 1
        key.nodes[1].keyframes.append(entry)
        self.path.write_bytes(encodeBinaryKey(key))
        with self.assertRaisesRegex(ValueError, 'increasing'):
            importKey(self.path, bpy.context.scene, True, True, False)
        self.assertEqual(self.joints[1].animation_data.action, action)

    def test_zero_duration_pose_uses_one_display_frame_and_exports_zero_duration(self):
        data, _ = binary_key_bytes()
        key = readBinaryKey(data)
        key.numFrames = 0
        key.nodes[1].keyframes = key.nodes[1].keyframes[:1]
        self.path.write_bytes(encodeBinaryKey(key))
        importKey(self.path, bpy.context.scene, True, True, False)
        self.assertEqual(bpy.context.scene.frame_end, 0)
        bpy.context.scene.frame_set(0)
        self.assert_vector(self.joints[1].location, (1, 2, 3))
        target = self.folder / 'pose.key'
        exportKey(self.root, bpy.context.scene, str(target), target='GRIM')
        self.assertEqual(loadKey(target).numFrames, 0)

    def test_damaged_binary_metadata_does_not_replace_output(self):
        self.load()
        self.root[kKeyBinaryData] = '{"header": "bad", "nodes": {}}'
        target = self.folder / 'previous.key'
        target.write_bytes(b'previous')
        with self.assertRaisesRegex(ValueError, 'metadata'):
            exportKey(self.root, bpy.context.scene, str(target), target='GRIM')
        self.assertEqual(target.read_bytes(), b'previous')

    def test_merge_discards_single_source_binary_metadata(self):
        self.load()
        importKey(self.path, bpy.context.scene, False, True, False)
        self.assertNotIn(kKeyBinaryData, self.root)

    def test_uv_labels_and_grim_target_are_registered(self):
        importer = bpy.ops.import_scene.sith_3do.get_rna_type()
        exporter = bpy.ops.export_scene.sith_3do.get_rna_type()
        for prop in (importer.properties['uv_absolute_3do_2_1'], exporter.properties['absolute_uv']):
            self.assertEqual(prop.name, 'v2.1 Absolute UV')
            for name in ('Jedi Knight', 'Mysteries of the Sith', 'Grim Fandango', 'DroidWorks'):
                self.assertIn(name, prop.description)
        target = bpy.ops.export_anim.sith_key.get_rna_type().properties['target']
        grim = target.enum_items['GRIM']
        self.assertEqual(grim.name, 'Grim Fandango')
        for wording in ('Binary format', '8 markers', '36-character resource names',
                        '32-character joint names'):
            self.assertIn(wording, grim.description)
        self.assertNotIn('FYEK', grim.description)
        self.assertNotIn('byte', grim.description)
        self.assertNotIn('ASCII', grim.description)
