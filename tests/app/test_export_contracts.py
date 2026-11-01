"""Edited-scene regressions complement the original-asset round-trip checks."""
import itertools
import math
import tempfile
from pathlib import Path

import bpy
import mathutils

from app.support import SceneTestCase
from app.test_key import sample_key
from sith.key.keyExporter import _make_key_from_obj, exportKey
from sith.key.keyImporter import _find_joint_obj_for_anim_node, _set_obj_location, importKey
from sith.key.keyLoader import loadKey
from sith.key.keyWriter import saveKey
from sith.key.keyUtils import getActionFCurves
from sith.key import Key, KeyNode, Keyframe, KeyMarker
from batch.app import compare_keys
from sith.model.model3doExporter import makeModel3doFromObj
from sith.model.model3doLoader import load3do, Model3doFileVersion
from sith.model.model3doWriter import save3do
from sith.model.utils import kImEulerOrder, getMeshRadiusObj, kMeshRadius


class ExportContractTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        self.scene = bpy.context.scene
        self.scene.timeline_markers.clear()
        self.scene.frame_start, self.scene.frame_end = 0, 4
        self.scene.sith_key_flags = set()
        self.scene.sith_key_types = '0'
        self.scene.render.fps, self.scene.render.fps_base = 30, 1
        self.root = self.object('wrapper')
        self.joint = self.object('joint', self.root, mesh=True, sequence=0)

    def object(self, name, parent=None, mesh=False, sequence=-1):
        data = bpy.data.meshes.new(name) if mesh else None
        if data is not None:
            data.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        obj = bpy.data.objects.new(name, data)
        self.scene.collection.objects.link(obj)
        obj.parent = parent
        obj.sith_model3do_hnode_idx = sequence
        obj.sith_model3do_hnode_name = name
        obj.rotation_mode = kImEulerOrder
        return obj

    def animate(self, obj=None, path='location', start=(0, 0, 0), end=(1, 0, 0)):
        obj = self.joint if obj is None else obj
        for frame, value in ((0, start), (4, end)):
            setattr(obj, path, value)
            obj.keyframe_insert(data_path=path, frame=frame)
        for curve in getActionFCurves(obj):
            for point in curve.keyframe_points:
                point.interpolation = 'LINEAR'

    def export_model(self):
        return makeModel3doFromObj('test.3do', self.root)

    def export_key(self, target='IJIM'):
        return _make_key_from_obj('test.key', self.root, self.scene, target=target)

    def test_markers_are_sorted_by_actual_fractional_time_and_keep_ties(self):
        self.animate()
        for name, frame in (('Attack', 10), ('LeftFoot', 2), ('RightFoot', 2), ('Swing@0.1', 2)):
            self.scene.timeline_markers.new(name, frame=frame)
        self.scene.frame_end = 12
        key = self.export_key()
        self.assertEqual([(marker.frame, int(marker.type)) for marker in key.markers],
                         [(2, 1), (2, 2), (2.1, 4), (10, 3)])
        delivered = []
        # The original engines stop at the first marker beyond the current frame.
        for marker in key.markers:
            if marker.frame > 2:
                break
            if marker.frame > 1:
                delivered.append(int(marker.type))
        self.assertEqual(delivered, [1, 2])

    def test_corpus_checker_requires_sorted_output_without_hiding_marker_loss(self):
        source, target = Key('source'), Key('target')
        for frame, kind in ((15, 2), (1, 1)):
            marker = KeyMarker()
            marker.frame, marker.type = frame, kind
            source.markers.append(marker)
        target.markers = list(source.markers)
        self.assertTrue(compare_keys(source, target)['differences'])
        target.markers.reverse()
        result = compare_keys(source, target)
        self.assertFalse(result['differences'])
        self.assertTrue(result['source_marker_order_corrected'])
        target.markers.pop()
        self.assertTrue(compare_keys(source, target)['differences'])

    def test_indexed_joint_wins_over_wrapper_name_on_actual_import(self):
        self.root.name = self.root.sith_model3do_hnode_name = 'joint'
        key = Key('indexed.key')
        key.numFrames, key.numJoints, key.fps = 5, 1, 30
        node = KeyNode()
        node.idx, node.meshName = 0, 'joint'
        node.keyframes = [Keyframe()]
        key.nodes = [node]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / key.name
            saveKey(key, path, '')
            bpy.context.view_layer.objects.active = self.root
            importKey(path, self.scene, True, True, False)
        self.assertIsNone(self.root.animation_data)
        self.assertIsNotNone(self.joint.animation_data.action)

    def test_joint_fallback_is_available_without_explicit_sequence(self):
        self.joint.sith_model3do_hnode_idx = -1
        node = KeyNode()
        node.idx, node.meshName = 0, 'JOINT'
        self.assertEqual(_find_joint_obj_for_anim_node(self.root, node, 1), self.joint)

    def test_authored_sequence_order_survives_key_export_and_reimport(self):
        child = self.object('child', self.joint, mesh=True, sequence=0)
        for rootNumber, childNumber in ((-1, 0), (-1, -1), (0, -1), (1, 10)):
            with self.subTest(sequence=(rootNumber, childNumber)):
                self.joint.sith_model3do_hnode_idx = rootNumber
                child.sith_model3do_hnode_idx = childNumber
                self.animate(self.joint)
                self.animate(child, end=(0, 2, 0))
                key = self.export_key()
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / 'sequence.key'
                    saveKey(key, path, '')
                    bpy.context.view_layer.objects.active = self.root
                    importKey(path, self.scene, True, True, False)
                self.scene.frame_set(2)
                self.assert_vector(self.joint.location, (0.5, 0, 0))
                self.assert_vector(child.location, (0, 1, 0))

    def test_ambiguous_indices_and_fallback_names_are_rejected(self):
        other = self.object('other', self.joint, sequence=0)
        node = KeyNode()
        node.idx, node.meshName = 0, 'joint'
        with self.assertRaisesRegex(ValueError, 'sequence'):
            _find_joint_obj_for_anim_node(self.root, node, 1)
        self.joint.sith_model3do_hnode_idx = other.sith_model3do_hnode_idx = -1
        other.sith_model3do_hnode_name = 'joint'
        with self.assertRaisesRegex(ValueError, 'name'):
            _find_joint_obj_for_anim_node(self.root, node, 1)

    def test_unapplied_parent_inverse_rejected_without_mutating_scene(self):
        self.joint.matrix_parent_inverse = mathutils.Matrix.Translation((-2, 0, 0))
        self.joint.location = (1, 0, 0)
        bpy.context.view_layer.update()
        before = (tuple(self.joint.location), self.joint.matrix_world.copy())
        for export in (self.export_model, self.export_key):
            with self.assertRaisesRegex(ValueError, 'parent inverse'):
                export()
            self.assertEqual(tuple(self.joint.location), before[0])
            self.assertEqual(self.joint.matrix_world, before[1])

    def test_delta_transforms_are_rejected_for_model_and_key(self):
        for attribute, value in (('delta_location', (3, 0, 0)), ('delta_scale', (2, 1, 1)),
                                 ('delta_rotation_euler', (0, 0, 1))):
            original = tuple(getattr(self.joint, attribute))
            setattr(self.joint, attribute, value)
            for export in (self.export_model, self.export_key):
                with self.subTest(attribute=attribute), self.assertRaisesRegex(ValueError, 'delta'):
                    export()
            setattr(self.joint, attribute, original)
        self.joint.rotation_mode = 'QUATERNION'
        self.joint.delta_rotation_quaternion = mathutils.Quaternion((0, 0, 1), 1)
        with self.assertRaisesRegex(ValueError, 'delta'):
            self.export_model()

    def test_noncommuting_parent_scale_and_wrapper_rotation_are_rejected(self):
        self.root.scale = (2, 1, 1)
        self.joint.rotation_euler.z = math.pi / 4
        for export in (self.export_model, self.export_key):
            with self.assertRaisesRegex(ValueError, 'nonuniform parent scale'):
                export()
        self.root.scale = (1, 1, 1)
        self.root.rotation_euler.z = math.pi / 4
        for export in (self.export_model, self.export_key):
            with self.assertRaisesRegex(ValueError, 'wrapper rotation'):
                export()

    def test_supported_aligned_parent_scale_and_local_scale_are_retained(self):
        self.root.scale = (2, 3, 4)
        self.joint.scale = (2, 2, 2)
        self.animate()
        model, key = self.export_model(), self.export_key()
        self.assert_vector(model.geosets[0].meshes[0].vertices[1], (4, 0, 0))
        self.assert_vector(sample_key(key.nodes[0], 2)[0], (1, 0, 0))

    def test_nonuniform_parent_scale_rejects_animated_rotation(self):
        self.root.scale = (2, 3, 4)
        self.animate(path='rotation_euler', end=(0, 0, math.pi))
        self.scene.frame_set(0)
        with self.assertRaisesRegex(ValueError, 'nonuniform parent scale'):
            self.export_key()

    def test_pivot_activation_agrees_between_model_and_key(self):
        constraint = self.joint.constraints.new('PIVOT')
        constraint.offset = (2, 0, 0)
        self.animate()
        for mute, influence, expectedPivot in ((False, 0, 0), (True, 1, 0), (False, 1, -2)):
            with self.subTest(mute=mute, influence=influence):
                constraint.mute, constraint.influence = mute, influence
                self.scene.frame_set(0)
                model, key = self.export_model(), self.export_key()
                self.assertEqual(model.meshHierarchy[0].pivot.x, expectedPivot)
                self.assert_vector(sample_key(key.nodes[0], 2)[0], (0.5 - expectedPivot, 0, 0))
                _set_obj_location(self.joint, (1, 0, 0))
                self.assert_vector(self.joint.location, (1 + expectedPivot, 0, 0))

    def test_partial_pivot_influence_is_rejected(self):
        constraint = self.joint.constraints.new('PIVOT')
        constraint.offset, constraint.influence = (2, 0, 0), 0.5
        self.animate()
        for export in (self.export_model, self.export_key):
            with self.assertRaisesRegex(ValueError, 'partial Pivot'):
                export()

    def test_linked_mesh_instances_keep_their_own_render_modes_and_helpers(self):
        other = self.object('instance', self.joint, mesh=True, sequence=1)
        other.data = self.joint.data
        self.joint.sith_model3do_light_mode = 'FullyLit'
        self.joint.sith_model3do_texture_mode = 'Affine'
        other.sith_model3do_light_mode = 'NotLit'
        other.sith_model3do_texture_mode = 'PerspectiveCorrected'
        model = self.export_model()
        self.assertEqual([(int(mesh.lightMode), int(mesh.textureMode)) for mesh in model.geosets[0].meshes],
                         [(0, 0), (1, 3)])
        helper = self.object(kMeshRadius + other.name, other, mesh=True)
        self.assertEqual(getMeshRadiusObj(model.geosets[0].meshes[1], other), helper)
        self.assertIsNone(getMeshRadiusObj(model.geosets[0].meshes[0], self.joint))

    def test_mesh_display_name_spaces_do_not_change_joint_identity(self):
        self.joint.data.name = 'example display name'
        self.animate()
        model, key = self.export_model(), self.export_key()
        self.assertEqual(model.geosets[0].meshes[0].name, 'example display name')
        self.assertEqual(model.meshHierarchy[0].name, 'joint')
        self.assertEqual((key.nodes[0].idx, key.nodes[0].meshName), (0, 'joint'))

    def test_loose_vertices_and_point_colors_survive_model_export(self):
        mesh = self.joint.data
        mesh.clear_geometry()
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0), (4, 5, 6)], [], [(0, 1, 2)])
        colors = mesh.color_attributes.new(name='PointColor', type='FLOAT_COLOR', domain='POINT')
        colors.data[3].color = (0.25, 0.5, 0.75, 1)
        model = makeModel3doFromObj('loose.3do', self.root, exportVertexColors=True)
        exported = model.geosets[0].meshes[0]
        self.assertEqual(len(exported.vertices), 4)
        self.assert_vector(exported.vertices[-1], (4, 5, 6))
        self.assert_vector(exported.vertexColors[-1], (0.25, 0.5, 0.75, 1))
        mesh.clear_geometry()
        mesh.from_pydata([(1, 2, 3), (4, 5, 6)], [], [])
        model = self.export_model()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'vertices.3do'
            save3do(model, path, Model3doFileVersion.Version2_3, '')
            restored, _ = load3do(path)
        self.assertEqual(restored.geosets[0].meshes[0].vertices, [(1, 2, 3), (4, 5, 6)])
        self.assertEqual(restored.geosets[0].meshes[0].faces, [])

    def test_repeated_face_vertices_do_not_require_adjacency_walks(self):
        # Legacy meshes may have collapsed faces; avoid BMVert.link_faces traversal.
        mesh = self.joint.data
        mesh.clear_geometry()
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0), (2, 3, 4)], [], [(0, 1, 0), (2, 2, 2)])
        exported = self.export_model().geosets[0].meshes[0]
        self.assertIn((2, 3, 4), exported.vertices)
        self.assertTrue(exported.vertices)

    def test_animated_scale_and_delta_channels_are_rejected_including_parents(self):
        for obj in (self.joint, self.root):
            for path, start, end in (('scale', (1, 1, 1), (2, 2, 2)),
                                     ('delta_location', (0, 0, 0), (1, 0, 0))):
                self.animate(obj, path, start, end)
                self.scene.frame_set(0)
                with self.subTest(obj=obj.name, path=path), self.assertRaisesRegex(ValueError, 'animated scale/delta'):
                    self.export_key()
                obj.animation_data_clear()
                setattr(obj, path, start)

    def test_scale_drivers_are_rejected(self):
        self.joint.driver_add('scale', 0)
        with self.assertRaisesRegex(ValueError, 'drivers'):
            self.export_key()

    def test_live_modifiers_are_rejected_instead_of_aliasing(self):
        self.animate()
        curve = getActionFCurves(self.joint)[0]
        modifier = curve.modifiers.new('FNGENERATOR')
        modifier.function_type, modifier.amplitude = 'SIN', 1
        modifier.phase_multiplier = 8 * math.pi
        with self.assertRaisesRegex(ValueError, 'F-curve modifiers'):
            self.export_key()
        modifier.mute = True
        self.assert_vector(sample_key(self.export_key().nodes[0], 2)[0], (0.5, 0, 0))
        modifier.mute = False
        curve.convert_to_samples(0, 4)
        curve.modifiers.remove(modifier)
        self.assertIsNotNone(self.export_key())

    def test_public_export_checks_target_before_overwriting_output(self):
        self.animate()
        for index in range(9):
            self.scene.timeline_markers.new(str(index + 1), frame=index)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'valid.key'
            path.write_bytes(b'keep')
            with self.assertRaisesRegex(ValueError, 'markers'):
                exportKey(self.root, self.scene, str(path), target='JKDF2')
            self.assertEqual(path.read_bytes(), b'keep')
            exportKey(self.root, self.scene, str(path), target='IJIM')
            self.assertEqual(len(loadKey(path).markers), 9)
        target = bpy.ops.export_anim.sith_key.get_rna_type().properties['target']
        self.assertEqual(target.default, 'IJIM')
        self.assertEqual(target.name, 'Target')
        self.assertEqual(target.enum_items['CUSTOM'].name, 'Generic')

    def test_all_paired_mesh_and_empty_node_permutations(self):
        # Independent mesh identity and KEY node checks protect both sync modes.
        with tempfile.TemporaryDirectory() as directory:
            modelPath, keyPath = Path(directory) / 'paired.3do', Path(directory) / 'paired.key'
            for sequence in itertools.permutations((1, 2, 3)):
                for mask in range(16):
                    for sync in (False, True):
                        self.clear_data()
                        root = self.object('wrapper')
                        objects = [self.object('joint0', root, mesh=bool(mask & 1), sequence=0)]
                        for index, number in enumerate(sequence, 1):
                            objects.append(self.object(f'joint{index}', objects[0] if index != 3 else objects[1],
                                                       mesh=bool(mask & (1 << index)), sequence=number))
                        for obj in objects:
                            self.animate(obj)
                        model = makeModel3doFromObj('paired.3do', root, sync_mesh_list=sync)
                        key = _make_key_from_obj('paired.key', root, self.scene)
                        save3do(model, modelPath, Model3doFileVersion.Version2_3, '')
                        saveKey(key, keyPath, '')
                        model, _ = load3do(modelPath)
                        key = loadKey(keyPath)
                        self.assertEqual([(node.idx, node.name) for node in model.meshHierarchy],
                                         [(node.idx, node.meshName) for node in key.nodes])
                        for node, obj in zip(model.meshHierarchy, sorted(objects, key=lambda value: value.sith_model3do_hnode_idx)):
                            if obj.type == 'MESH':
                                self.assertEqual(model.geosets[0].meshes[node.meshIdx].name, obj.data.name)
                            else:
                                self.assertEqual(node.meshIdx, -1)
                        indices = [node.meshIdx for node in model.meshHierarchy if node.meshIdx >= 0]
                        if sync:
                            self.assertEqual(indices, list(range(len(indices))))
