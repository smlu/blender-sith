"""Native pivot authoring, legacy scenes and explicit geometry-preserving baking."""
import itertools
import math
from pathlib import Path

import bpy
import mathutils

from app.test_native_pivots import NativePivotFixture
from fixtures import TV
from sith.model.model3doExporter import makeModel3doFromObj, export3do
from sith.model.model3doLoader import load3do, Model3doFileVersion, Model3doFileFormat
from sith.model.model3doImporter import import3do
from sith.model import utils
from sith.key.keyExporter import _make_key_from_obj
from sith.types import Vector3f


class PivotWorkflowTests(NativePivotFixture):
    def export_model(self, version=Model3doFileVersion.Version2_3, sync=True, *, bake=False):
        export3do(self.root, str(self.output), version, version == Model3doFileVersion.Version2_1,
                  True, sync, bakePivots=bake)
        return load3do(self.output)[0]

    def snapshot(self):
        return {obj.name: (tuple(obj.location), tuple(obj.scale),
                           tuple(tuple(v.co) for v in obj.data.vertices) if obj.type == 'MESH' else (),
                           tuple(obj.get('3do_pivot', ())), tuple(obj.get('3do_imported_pivot', ())))
                for obj in (self.root, *self.root.children_recursive)}

    def test_import_and_numeric_authoring_use_one_neutral_property(self):
        self.import_model()
        obj = self.node_object(1)
        self.assert_vector(obj['3do_pivot'], (0.125, 0, 0))
        self.assertNotIn('3do_imported_pivot', obj)
        self.assert_vector(obj.sith_model3do_pivot, (0.125, 0, 0))
        self.assertFalse(obj.bl_rna.properties['sith_model3do_pivot'].is_animatable)
        vertices = [tuple(v.co) for v in obj.data.vertices]
        obj.sith_model3do_pivot = (2, -3, 4)
        self.assert_vector(obj['3do_pivot'], (2, -3, 4))
        self.assertEqual([tuple(v.co) for v in obj.data.vertices], vertices)
        exported = self.export_model()
        self.assert_vector(exported.meshHierarchy[1].pivot, (2, -3, 4))
        self.assert_vector(exported.geosets[0].meshes[0].vertices[0], (-1.875, 3, -4))
        self.assert_surface_matches_scene(exported)

    def test_new_mesh_and_empty_nodes_accept_numeric_pivots(self):
        for kind in ('MESH', 'EMPTY'):
            with self.subTest(kind=kind):
                self.clear_data()
                data = bpy.data.meshes.new('authored') if kind == 'MESH' else None
                if data is not None:
                    data.from_pydata([(1, 2, 3), (2, 2, 3), (1, 3, 3)], [], [(0, 1, 2)])
                obj = bpy.data.objects.new('authored', data)
                bpy.context.scene.collection.objects.link(obj)
                obj.sith_model3do_pivot = (4, 5, 6)
                before = [tuple(v.co) for v in data.vertices] if data else []
                preserved = makeModel3doFromObj('new.3do', obj)
                baked = makeModel3doFromObj('new.3do', obj, bakePivots=True)
                self.assert_vector(preserved.meshHierarchy[0].pivot, (4, 5, 6))
                self.assert_vector(baked.meshHierarchy[0].pivot, (0, 0, 0))
                if data:
                    self.assertEqual(list(map(tuple, baked.geosets[0].meshes[0].vertices)), before)
                    self.assertEqual([tuple(v.co) for v in data.vertices], before)

    def test_legacy_saved_scene_is_read_without_implicit_migration(self):
        self.import_model()
        for obj in self.root.children_recursive:
            obj['3do_imported_pivot'] = list(obj['3do_pivot'])
            del obj['3do_pivot']
        path = Path(self.directory.name) / 'legacy-pivot.blend'
        name = self.root.name
        bpy.ops.wm.save_as_mainfile(filepath=str(path))
        bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False, use_scripts=False)
        self.root = bpy.data.objects[name]
        obj = self.node_object(1)
        before = self.snapshot()
        self.assert_vector(obj.sith_model3do_pivot, (0.125, 0, 0))
        self.assert_vector(self.export_model().meshHierarchy[1].pivot, (0.125, 0, 0))
        self.assertEqual(self.snapshot(), before)
        obj.sith_model3do_pivot = (0, 0, 0)
        self.assertIn('3do_pivot', obj)
        self.assertNotIn('3do_imported_pivot', obj)
        self.assert_vector(self.export_model().meshHierarchy[1].pivot, (0, 0, 0))

    def test_explicit_neutral_zero_takes_precedence_over_legacy_value(self):
        self.import_model()
        obj = self.node_object(1)
        obj['3do_imported_pivot'] = [9, 8, 7]
        obj['3do_pivot'] = [0, 0, 0]
        before = self.snapshot()
        exported = self.export_model()
        self.assert_vector(exported.meshHierarchy[1].pivot, (0, 0, 0))
        self.assert_vector(exported.geosets[0].meshes[0].vertices[0], (0.125, 0, 0))
        self.assertEqual(self.snapshot(), before)

    def test_explicit_bake_all_text_options_preserves_surfaces_and_children(self):
        self.model.meshHierarchy[0].pivot = Vector3f(2, -3, 1)
        for version, preserve, sync in itertools.product(Model3doFileVersion, (False, True), (False, True)):
            with self.subTest(version=version, preserve=preserve, sync=sync):
                self.clear_data()
                self.import_model(version, preserveOrder=preserve)
                before = self.snapshot()
                normal = self.export_model(version, sync)
                for cycle in range(2):
                    baked = self.export_model(version, sync, bake=True)
                    for source, target in zip(normal.meshHierarchy, baked.meshHierarchy):
                        self.assert_vector(target.pivot, (0, 0, 0))
                        self.assert_vector(target.position, source.position)
                        self.assert_vector(target.rotation, source.rotation)
                    self.assert_surface_matches_scene(baked)
                    if cycle == 0:
                        self.assertEqual(self.snapshot(), before)
                    self.clear_data()
                    self.root = import3do(self.output, clearScene=False, preserveOrder=preserve)

    def test_bake_scaled_pivots_and_loose_vertices_without_mutation(self):
        self.model, _ = load3do(TV / 'model/loose_vertices.3do')
        for node in self.model.meshHierarchy:
            node.pivot = Vector3f(2, 3, 4)
        self.import_model()
        self.root.scale = (2, 2, 2)
        self.node_object(0).scale = (-2, 1.5, 8)
        before = self.snapshot()
        baked = self.export_model(bake=True)
        self.assertTrue(all(tuple(node.pivot) == (0, 0, 0) for node in baked.meshHierarchy))
        self.assert_surface_matches_scene(baked)
        self.assertEqual(self.snapshot(), before)

    def test_bake_recomputes_automatic_mesh_radius_in_emitted_coordinates(self):
        mesh = self.model.geosets[0].meshes[0]
        mesh.vertices = [Vector3f(10, 0, 0), Vector3f(11, 0, 0), Vector3f(10, 1, 0)]
        for pivot, radius in ((-9, 2), (20, 31)):
            with self.subTest(pivot=pivot):
                self.clear_data()
                self.model.meshHierarchy[1].pivot = Vector3f(pivot, 0, 0)
                self.import_model()
                preserved = self.export_model()
                baked = self.export_model(bake=True)
                self.assertAlmostEqual(preserved.geosets[0].meshes[0].radius, 11, delta=1e-6)
                self.assertAlmostEqual(baked.geosets[0].meshes[0].radius, radius, delta=1e-6)
                self.assertEqual(baked.radius, self.model.radius)
                # Float32 rotation of coordinates around 31 has several ULPs
                # more absolute error than the unit-scale fixture.
                self.assert_surface_matches_scene(baked, tolerance=1e-5)

    def test_bake_supported_legacy_constraint_without_relaxing_validation(self):
        self.model.meshHierarchy[0].rotation = Vector3f(0, 0, 0)
        self.import_model()
        obj = self.node_object(1)
        constraint = obj.constraints.new('PIVOT')
        constraint.offset = (2, 0, 0)
        constraint.use_relative_location = True
        constraint.rotation_range = 'ALWAYS_ACTIVE'
        before = self.snapshot()
        preserved = self.export_model()
        baked = self.export_model(bake=True)
        pnode, bnode = preserved.meshHierarchy[1], baked.meshHierarchy[1]
        self.assert_vector(bnode.pivot, (0, 0, 0))
        self.assert_vector(bnode.position, pnode.position)
        for original, emitted in zip(preserved.geosets[0].meshes[0].vertices,
                                     baked.geosets[0].meshes[0].vertices):
            self.assert_vector(emitted, mathutils.Vector(original) + mathutils.Vector(pnode.pivot))
        self.assertEqual(self.snapshot(), before)
        constraint.influence = 0.5
        self.output.write_bytes(b'keep previous export')
        with self.assertRaisesRegex(ValueError, 'partial Pivot'):
            self.export_model(bake=True)
        self.assertEqual(self.output.read_bytes(), b'keep previous export')

    def test_explicit_bake_ignores_unusable_stored_offsets_without_precision_loss(self):
        self.import_model()
        obj = self.node_object(1)
        for value in ([1e30, 0, 0], [math.nan, 0, 0], 'obsolete metadata'):
            with self.subTest(value=value):
                obj['3do_pivot'] = value
                if value != [1e30, 0, 0]:
                    with self.assertRaisesRegex(ValueError, '[Pp]ivot'):
                        self.export_model()
                baked = self.export_model(bake=True)
                self.assert_vector(baked.geosets[0].meshes[0].vertices[0], (0.125, 0, 0))
                self.assert_surface_matches_scene(baked)

    def test_bake_does_not_change_key_joint_channels(self):
        self.import_model()
        obj = self.node_object(1)
        obj.sith_model3do_pivot = (4, -5, 6)
        scene = bpy.context.scene
        scene.frame_start, scene.frame_end = 0, 2
        for frame, point in ((0, (0, 0, 0.5)), (2, (1, 2, 3))):
            obj.location = point
            obj.keyframe_insert(data_path='location', frame=frame)
        scene.frame_set(0)
        before = _make_key_from_obj('before.key', self.root, scene)
        self.export_model(bake=True)
        after = _make_key_from_obj('after.key', self.root, scene)
        for first, second in zip(before.nodes, after.nodes):
            self.assertEqual(first.idx, second.idx)
            self.assertEqual([tuple(k.position) for k in first.keyframes], [tuple(k.position) for k in second.keyframes])
        node = next(n for n in after.nodes if n.idx == 1)
        self.assert_vector(node.keyframes[0].position, (0, 0, 0.5))
        self.assert_vector(node.keyframes[-1].position, (1, 2, 3))

    def test_bake_is_available_through_registered_export_operator(self):
        self.import_model()
        self.assertFalse(bpy.ops.export_scene.sith_3do.get_rna_type().properties['bake_pivots'].default)
        bpy.context.view_layer.objects.active = self.root
        self.root.select_set(True)
        result = bpy.ops.export_scene.sith_3do(filepath=str(self.output), version='Version2_3', bake_pivots=True)
        self.assertEqual(result, {'FINISHED'})
        model, _ = load3do(self.output)
        self.assertTrue(all(tuple(node.pivot) == (0, 0, 0) for node in model.meshHierarchy))
        self.assert_surface_matches_scene(model)

    def test_bake_binary_round_trip_preserves_zero_pivots(self):
        self.import_model()
        baked = self.export_model(Model3doFileFormat.GrimFandango, bake=True)
        self.assertTrue(all(tuple(node.pivot) == (0, 0, 0) for node in baked.meshHierarchy))
        self.assert_surface_matches_scene(baked)

    def test_shared_mesh_datablock_has_independent_native_frames(self):
        self.import_model()
        first = self.node_object(1)
        second = first.copy()
        bpy.context.scene.collection.objects.link(second)
        second.sith_model3do_hnode_idx = 2
        second.location = (3, 4, 5)
        first.sith_model3do_pivot = (1, 2, 3)
        second.sith_model3do_pivot = (-4, 5, -6)
        self.assertIs(first.data, second.data)
        before = self.snapshot()
        for sync in (False, True):
            for bake in (False, True):
                with self.subTest(sync=sync, bake=bake):
                    model = self.export_model(sync=sync, bake=bake)
                    self.assertEqual(len(model.geosets[0].meshes), 2)
                    self.assert_surface_matches_scene(model)
                    self.assertEqual(self.snapshot(), before)
                    for index, obj in ((1, first), (2, second)):
                        expected = (0, 0, 0) if bake else obj.sith_model3do_pivot
                        self.assert_vector(model.meshHierarchy[index].pivot, expected)

    def test_explicit_radius_helpers_and_model_radius_survive_baking(self):
        self.import_model(importRadiusObj=True)
        obj = self.node_object(1)
        helper = utils.getMeshRadiusObj(None, obj)
        helper.scale = (10, 10, 10)
        bpy.context.view_layer.update()
        preserved = self.export_model()
        baked = self.export_model(bake=True)
        self.assertEqual(baked.geosets[0].meshes[0].radius,
                         preserved.geosets[0].meshes[0].radius)
        self.assertEqual(baked.radius, preserved.radius)
        self.assertEqual(tuple(helper.scale), (10, 10, 10))

    def test_legacy_malformed_offset_only_blocks_default_mode(self):
        self.import_model()
        obj = self.node_object(0)  # Empty node has no mesh extraction path.
        del obj['3do_pivot']
        obj['3do_imported_pivot'] = 'obsolete'
        self.output.write_bytes(b'old file')
        with self.assertRaisesRegex(ValueError, '[Pp]ivot'):
            self.export_model()
        self.assertEqual(self.output.read_bytes(), b'old file')
        model = self.export_model(bake=True)
        self.assert_vector(model.meshHierarchy[0].pivot, (0, 0, 0))
        self.assertEqual(obj['3do_imported_pivot'], 'obsolete')
        self.assertNotIn('3do_pivot', obj)
        with self.assertRaisesRegex(ValueError, 'complete 3DO'):
            makeModel3doFromObj('hierarchy', self.root, hierarchyOnly=True, bakePivots=True)

    def test_active_constraint_ignores_malformed_superseded_native_value(self):
        self.model.meshHierarchy[0].rotation = Vector3f(0, 0, 0)
        self.import_model()
        obj = self.node_object(1)
        constraint = obj.constraints.new('PIVOT')
        constraint.offset = (2, 0, 0)
        constraint.use_relative_location = True
        constraint.rotation_range = 'ALWAYS_ACTIVE'
        del obj['3do_pivot']
        for key in ('3do_pivot', '3do_imported_pivot'):
            with self.subTest(key=key):
                obj[key] = 'superseded value'
                model = self.export_model()
                self.assert_vector(model.meshHierarchy[1].pivot, (-2, 0, 0))
                for mute, influence in ((True, 1), (False, 0)):
                    constraint.mute, constraint.influence = mute, influence
                    with self.assertRaisesRegex(ValueError, '[Pp]ivot'):
                        self.export_model()
                constraint.mute, constraint.influence = False, 1
                del obj[key]
