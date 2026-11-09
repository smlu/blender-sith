"""Opt-in recovery and late-start playback/export in actual Blender actions."""
import bpy

from app.test_key_import_safety import _ImportSafetyCase, held
from grim_fixtures import binary_key_bytes, changed_word
from sith.key import KeyframeFlag
from sith.key.keyExporter import exportKey
from sith.key.keyImporter import importKey
from sith.key.keyLoader import loadKey
from sith.key.keyUtils import getActionFCurves, kKeyImportReport
from sith.types import Vector3f


class LateKeyImportTests(_ImportSafetyCase):
    def test_relaxed_import_matches_held_and_extrapolated_motion(self):
        # Exercise the negative elapsed interval as well as the stored entry and
        # the final fractional interval, for independent channel change flags.
        for flags in (0, 1, 2, 3):
            first = held(2, 5, 40)
            first.flags = KeyframeFlag(flags)
            first.deltaPosition, first.deltaRotation = Vector3f(0.5, -0.25, 0), Vector3f(0, 10, 0)
            key, path = self.key_file([first])
            with self.subTest(flags=flags):
                importKey(path, self.scene, True, True, False, requireFrameZero=False)
                self.assert_poses(self.obj, key.nodes[0], (0, 0.125, 1, 1.9, 2, 3, 4, 4.875))

    def test_generic_retains_late_source_while_game_targets_start_at_zero(self):
        first = held(2, 5, 40)
        first.flags, first.deltaPosition = KeyframeFlag.PositionChange, Vector3f(0.5, 0, 0)
        key, path = self.key_file([first])
        original = path.read_bytes()
        importKey(path, self.scene, True, True, False, requireFrameZero=False)
        for target in ('CUSTOM', 'IJIM', 'JKDF2', 'MOTS', 'GRIM'):
            destination = self.folder / 'export.key'
            exportKey(self.root, self.scene, str(destination), target=target)
            restored = loadKey(destination)
            track = next(node for node in restored.nodes if node.keyframes)
            self.assertEqual(track.keyframes[0].frame, 2 if target == 'CUSTOM' else 0)
            self.assert_poses(self.obj, track, (0, 0.5, 2, 4))
        self.assertEqual(path.read_bytes(), original)

    def test_generic_scene_start_is_not_rebased_and_edits_invalidate_source(self):
        first = held(2, 5)
        key, path = self.key_file([first])
        importKey(path, self.scene, True, True, False, requireFrameZero=False)
        curve = next(curve for curve in getActionFCurves(self.obj)
                     if curve.data_path == 'location' and curve.array_index == 0)
        curve.keyframe_points[0].co[1] = 8
        curve.update()
        destination = self.folder / 'generic.key'
        exportKey(self.root, self.scene, str(destination), target='CUSTOM')
        self.assertEqual(loadKey(destination).nodes[0].keyframes[0].position.x, 8)
        self.scene.frame_start = 1
        exportKey(self.root, self.scene, str(destination), target='CUSTOM')
        restored = loadKey(destination)
        self.assertEqual(restored.nodes[0].keyframes[0].frame, 1)
        self.assertEqual(restored.numFrames, 5)

    def test_relaxed_overflow_is_rejected_without_scene_mutation(self):
        first = held(2, 1)
        first.flags, first.deltaPosition = KeyframeFlag.PositionChange, Vector3f(3e38, 0, 0)
        _, path = self.key_file([first])
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'float32'):
            importKey(path, self.scene, True, True, False, requireFrameZero=False)
        self.assertEqual(self.snapshot(), before)

    def test_recovery_does_not_disable_frame_zero_policy(self):
        _, path = self.key_file([held(2, 5)])
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'frame zero'):
            importKey(path, self.scene, True, True, False, allowErrors=True)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(bpy.ops.import_anim.sith_key(filepath=str(path), require_frame_zero=False), {'FINISHED'})

    def test_recovery_reports_omitted_tracks_and_preserves_source(self):
        # Build two real destination joints and damage only the second track.
        self.obj.sith_model3do_hnode_name = 'root'
        self.joint('joint', 1, self.root)
        self.joint('unused', 2, self.root)
        data, offsets = binary_key_bytes(first_animated=True)
        damaged = changed_word(data, offsets['node1_entry'] + 8, float('nan'), 'f')
        path = self.folder / 'damaged.key'
        path.write_bytes(damaged)
        texts = set(bpy.data.texts)
        self.addCleanup(lambda: [bpy.data.texts.remove(text) for text in set(bpy.data.texts) - texts])
        result = bpy.ops.import_anim.sith_key(filepath=str(path), allow_errors=True)
        self.assertEqual(result, {'FINISHED'})
        self.assertIn(kKeyImportReport, self.root)
        report = bpy.data.texts[self.root[kKeyImportReport]].as_string()
        self.assertIn('Omitted KEY joint 1', report)
        self.assertTrue(getActionFCurves(self.obj))
        omitted = next(obj for obj in self.root.children if obj.sith_model3do_hnode_idx == 1)
        self.assertFalse(getActionFCurves(omitted))
        destination = self.folder / 'recovered.key'
        exportKey(self.root, self.scene, str(destination), target='GRIM')
        restored = loadKey(destination)
        self.assertEqual([node.idx for node in restored.nodes if node.keyframes], [0])
        self.assertEqual(path.read_bytes(), damaged)

    def test_failed_recovery_preserves_existing_actions_and_markers(self):
        data, offsets = binary_key_bytes()
        damaged = changed_word(data, offsets['node1_entry'] + 8, float('nan'), 'f')
        path = self.folder / 'unrecoverable.key'
        for contents in (damaged, data[:-1], data[:50]):
            path.write_bytes(contents)
            before, texts = self.snapshot(), set(bpy.data.texts)
            with self.subTest(size=len(contents)):
                with self.assertRaises(ValueError):
                    importKey(path, self.scene, True, True, False, allowErrors=True, requireFrameZero=False)
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(set(bpy.data.texts), texts)
                self.assertEqual(path.read_bytes(), contents)

    def test_clean_replacement_clears_stale_report_reference(self):
        self.root[kKeyImportReport] = 'previous report'
        _, path = self.key_file([held(0, 1)])
        importKey(path, self.scene, True, True, False)
        self.assertNotIn(kKeyImportReport, self.root)

    def test_ui_defaults_and_generic_description(self):
        properties = bpy.ops.import_anim.sith_key.get_rna_type().properties
        self.assertTrue(properties['require_frame_zero'].default)
        self.assertFalse(properties['allow_errors'].default)
        generic = bpy.ops.export_anim.sith_key.get_rna_type().properties['target'].enum_items['CUSTOM']
        self.assertIn('nonzero', generic.description)
        self.assertIn('scene start', generic.description)
        self.assertIn('safety', generic.description)
