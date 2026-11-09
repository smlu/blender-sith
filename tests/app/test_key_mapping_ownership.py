"""Distinct source tracks must never overwrite the same partial-skeleton joint."""
import bpy

from app.test_key_import_safety import _ImportSafetyCase, held
from sith.key import KeyNode
from sith.key.keyImporter import importKey, _check_obj


class KeyMappingOwnershipTests(_ImportSafetyCase):
    def aliased_key(self, name='joint'):
        later = KeyNode()
        later.idx, later.meshName, later.keyframes = 1, name, [held(0, 2)]
        return self.key_file([held(0, 1)], later=later, joints=2)

    def test_aliases_reject_before_merge_or_replacement_even_without_validation(self):
        self.obj.sith_model3do_hnode_idx = -1
        self.obj.name = 'display_name'
        for name in ('joint', 'JOINT', 'display_name'):
            key, path = self.aliased_key(name)
            self.assertFalse(_check_obj(self.root, key.nodes, key.numJoints))
            for clear in (False, True):
                for validate in (False, True):
                    for operator in (False, True):
                        before, contents = self.snapshot(), path.read_bytes()
                        message = 'required nodes' if validate else 'same joint object'
                        with self.subTest(alias=name, clear=clear, validate=validate, operator=operator):
                            with self.assertRaisesRegex(RuntimeError if operator else ValueError, message):
                                if operator:
                                    bpy.ops.import_anim.sith_key(filepath=str(path), clear_scene=clear,
                                                                 validate_active_object=validate)
                                else:
                                    importKey(path, self.scene, clear, validate, False)
                            self.assertEqual(self.snapshot(), before)
                            self.assertEqual(path.read_bytes(), contents)

    def test_complete_numbered_and_automatic_skeletons_allow_duplicate_source_names(self):
        other = self.joint('second', 1, self.root)
        key, path = self.aliased_key()
        for automatic in (False, True):
            self.obj.sith_model3do_hnode_idx = -1 if automatic else 0
            other.sith_model3do_hnode_idx = -1 if automatic else 1
            with self.subTest(automatic=automatic):
                self.assertTrue(_check_obj(self.root, key.nodes, key.numJoints))
                importKey(path, self.scene, True, True, False)
                self.assert_vector(self.obj.location, (1, 0, 0))
                self.assert_vector(other.location, (2, 0, 0))

    def test_single_track_partial_fallback_remains_supported(self):
        self.obj.sith_model3do_hnode_idx = -1
        _, path = self.key_file([held(0, 3)], joints=2)
        importKey(path, self.scene, False, True, False)
        self.assert_vector(self.obj.location, (3, 0, 0))

    def test_automatic_selection_skips_the_many_to_one_candidate(self):
        self.obj.sith_model3do_hnode_idx = -1
        original = self.obj.animation_data.action
        valid = self.joint('valid_wrapper', -1)
        first = self.joint('valid_first', 0, valid)
        second = self.joint('valid_second', 1, valid)
        _, path = self.aliased_key()
        bpy.context.view_layer.objects.active = None
        importKey(path, self.scene, False, True, False)
        self.assert_vector(first.location, (1, 0, 0))
        self.assert_vector(second.location, (2, 0, 0))
        self.assertEqual(self.obj.animation_data.action, original)
        self.assert_vector(self.obj.location, (9, 0, 0))
