"""Native mesh frames survive import/export without moving editable surfaces."""
import itertools
import math
from pathlib import Path
import tempfile

import bpy
import mathutils

from app.support import SceneTestCase
from fixtures import TV
from sith.model.model3doLoader import load3do, Model3doFileVersion
from sith.model.model3doWriter import save3do
from sith.model.model3doImporter import import3do
from sith.model.model3doExporter import export3do, makeModel3doFromObj
from sith.model import utils
from sith.types import Vector3f
from sith.key.keyExporter import _make_key_from_obj


class NativePivotTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'input.3do'
        self.output = Path(self.directory.name) / 'output.3do'
        self.model, _ = load3do(TV / 'model/triangle.3do')

    def import_model(self, version=Model3doFileVersion.Version2_3, **options):
        save3do(self.model, self.path, version, '')
        self.root = import3do(self.path, clearScene=False, **options)
        return self.root

    def node_object(self, index):
        return next(obj for obj in self.root.children_recursive
                    if obj.sith_model3do_hnode_idx == index)

    def export_model(self, version=Model3doFileVersion.Version2_3, sync=True):
        export3do(self.root, str(self.output), version, version.value == 2.1, True, sync)
        return load3do(self.output)[0]

    def assert_surface_matches_scene(self, model):
        # The scene uses baked mesh coordinates; the native file uses its pivot.
        # Compare each exported point against the independently evaluated scene.
        bpy.context.view_layer.update()
        matrices = {}
        for node in model.meshHierarchy:
            local = utils.makeRotationMatrix(*node.rotation).to_4x4()
            local.translation = node.position
            parent = matrices[node.parentIdx] if node.parentIdx >= 0 else mathutils.Matrix.Translation(model.insertOffset)
            matrices[node.idx] = parent @ local
            if node.meshIdx < 0:
                continue
            obj = self.node_object(node.idx)
            visible = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]
            exported = [matrices[node.idx] @ (mathutils.Vector(vertex) + mathutils.Vector(node.pivot))
                        for vertex in model.geosets[0].meshes[node.meshIdx].vertices]
            for point in exported:
                self.assertLess(min((point - other).length for other in visible), 3e-6)
            for point in visible:
                self.assertLess(min((point - other).length for other in exported), 3e-6)

    def test_native_pivots_and_vertices_survive_two_cycles_all_text_options(self):
        # Losing the pivot still renders correctly, but changes attached models'
        # mesh frame. Assert both native representation and equivalent surfaces.
        for version, preserve, sync in itertools.product(Model3doFileVersion, (False, True), (False, True)):
            with self.subTest(version=version, preserve=preserve, sync=sync):
                self.clear_data()
                self.import_model(version, preserveOrder=preserve)
                for cycle in range(2):
                    exported = self.export_model(version, sync)
                    self.assert_vector(exported.meshHierarchy[1].pivot, (0.125, 0, 0))
                    self.assert_vector(exported.meshHierarchy[1].position, (0, 0, 0.5))
                    self.assert_vector(exported.geosets[0].meshes[0].vertices[0], (0, 0, 0))
                    self.assert_surface_matches_scene(exported)
                    self.clear_data()
                    self.root = import3do(self.output, clearScene=False, preserveOrder=preserve)

    def test_empty_parent_pivot_preserves_attachment_frame_not_child_pose(self):
        self.model.meshHierarchy[0].position = Vector3f(3, 4, 0)
        self.model.meshHierarchy[0].rotation = Vector3f(0, 90, 0)
        self.model.meshHierarchy[0].pivot = Vector3f(2, 0, 0)
        self.model.meshHierarchy[1].position = Vector3f(2, 0, 0)
        self.model.meshHierarchy[1].pivot = Vector3f(0, 3, 0)
        self.import_model()
        exported = self.export_model()
        parent, child = exported.meshHierarchy
        self.assert_vector(parent.pivot, (2, 0, 0))
        self.assert_vector(child.pivot, (0, 3, 0))
        # Hand-calculated native origins without INSERT OFFSET: (3,6,0) and
        # (0,6,0). Parent pivot shifts its own frame, never the child's joint.
        self.assert_vector((parent.position.x - parent.pivot.y,
                            parent.position.y + parent.pivot.x, 0), (3, 6, 0))
        self.assert_vector((parent.position.x - child.position.y - child.pivot.y,
                            parent.position.y + child.position.x + child.pivot.x, 0), (0, 6, 0))
        self.assert_surface_matches_scene(exported)

    def test_native_pivot_compensation_scales_once_and_does_not_mutate_mesh(self):
        self.model.meshHierarchy[0].pivot = Vector3f(2, 0, 0)
        self.import_model()
        self.root.scale = (2, 2, 2)
        self.node_object(0).scale = (2, 3, 4)
        obj = self.node_object(1)
        obj.scale = (-1, 0.5, 2)
        before = [tuple(vertex.co) for vertex in obj.data.vertices]
        exported = self.export_model()
        self.assert_vector(exported.meshHierarchy[0].pivot, (8, 0, 0))
        self.assert_vector(exported.meshHierarchy[1].pivot, (-0.5, 0, 0))
        self.assert_vector(exported.meshHierarchy[1].position, (0, 0, 4))
        self.assertEqual([tuple(vertex.co) for vertex in obj.data.vertices], before)
        self.assert_surface_matches_scene(exported)

    def test_restored_native_vertices_define_automatic_mesh_radius(self):
        mesh = self.model.geosets[0].meshes[0]
        mesh.vertices = [Vector3f(10, 0, 0), Vector3f(11, 0, 0), Vector3f(10, 1, 0)]
        for pivot in (-9, 20):
            with self.subTest(pivot=pivot):
                self.clear_data()
                self.model.meshHierarchy[1].pivot = Vector3f(pivot, 0, 0)
                self.import_model()
                exported = self.export_model()
                self.assertAlmostEqual(exported.geosets[0].meshes[0].radius, 11, delta=1e-6)
                self.assertEqual(exported.radius, self.model.radius)

    def test_loose_vertices_are_compensated_as_well_as_face_corners(self):
        self.model, _ = load3do(TV / 'model/loose_vertices.3do')
        for node in self.model.meshHierarchy:
            if node.meshIdx >= 0:
                node.pivot = Vector3f(2, 3, 4)
        self.import_model()
        exported = self.export_model()
        for source, target in zip(self.model.meshHierarchy, exported.meshHierarchy):
            if source.meshIdx >= 0:
                before = self.model.geosets[0].meshes[source.meshIdx]
                after = exported.geosets[0].meshes[target.meshIdx]
                self.assertEqual(sorted(map(tuple, before.vertices)), sorted(map(tuple, after.vertices)))
        self.assert_surface_matches_scene(exported)

    def test_active_authored_constraint_overrides_native_metadata(self):
        self.model.meshHierarchy[0].rotation = Vector3f(0, 0, 0)
        self.import_model()
        obj = self.node_object(1)
        constraint = obj.constraints.new('PIVOT')
        constraint.offset = (2, 0, 0)
        constraint.use_relative_location = True
        constraint.rotation_range = 'ALWAYS_ACTIVE'
        before = [tuple(vertex.co) for vertex in obj.data.vertices]
        exported = self.export_model()
        self.assert_vector(exported.meshHierarchy[1].pivot, (-2, 0, 0))
        self.assert_vector(exported.meshHierarchy[1].position, (2, 0, 0.5))
        self.assert_vector(exported.geosets[0].meshes[0].vertices[0], (0.125, 0, 0))
        constraint.offset = (0, 0, 0)
        zero = self.export_model()
        self.assert_vector(zero.meshHierarchy[1].pivot, (0, 0, 0))
        self.assert_vector(zero.geosets[0].meshes[0].vertices[0], (0.125, 0, 0))
        for mute, influence in ((True, 1), (False, 0)):
            constraint.mute, constraint.influence = mute, influence
            restored = self.export_model()
            self.assert_vector(restored.meshHierarchy[1].pivot, (0.125, 0, 0))
            self.assert_vector(restored.geosets[0].meshes[0].vertices[0], (0, 0, 0))
        self.assertEqual([tuple(vertex.co) for vertex in obj.data.vertices], before)

    def test_invalid_metadata_rejects_before_replacing_output(self):
        self.import_model()
        for node_index, value in itertools.product((0, 1), ('bad', 3.0, [1.0, 2.0], [1.0, 2.0, math.nan], [1.0, math.inf, 0.0], [1e39, 0.0, 0.0])):
            with self.subTest(node=node_index, value=value):
                obj = self.node_object(node_index)
                obj['3do_imported_pivot'] = value
                self.output.write_bytes(b'previous valid export')
                with self.assertRaisesRegex(ValueError, '[Pp]ivot'):
                    self.export_model()
                self.assertEqual(self.output.read_bytes(), b'previous valid export')
                obj['3do_imported_pivot'] = list(self.model.meshHierarchy[node_index].pivot)

    def test_older_scene_without_metadata_keeps_zero_pivot_export(self):
        self.import_model()
        for obj in self.root.children_recursive:
            if '3do_imported_pivot' in obj:
                del obj['3do_imported_pivot']
        exported = self.export_model()
        self.assert_vector(exported.meshHierarchy[1].pivot, (0, 0, 0))
        self.assert_vector(exported.geosets[0].meshes[0].vertices[0], (0.125, 0, 0))
        self.assert_surface_matches_scene(exported)

    def test_saved_blend_preserves_pivots_without_changing_key_positions(self):
        self.import_model()
        blend = Path(self.directory.name) / 'native-pivot.blend'
        name = self.root.name
        bpy.ops.wm.save_as_mainfile(filepath=str(blend))
        bpy.ops.wm.open_mainfile(filepath=str(blend), load_ui=False, use_scripts=False)
        self.root = bpy.data.objects[name]
        exported = self.export_model()
        self.assert_vector(exported.meshHierarchy[1].pivot, (0.125, 0, 0))
        obj = self.node_object(1)
        self.assert_vector(utils.objPivot(obj, forAnimation=True), (0, 0, 0))
        scene = bpy.context.scene
        scene.frame_start, scene.frame_end = 0, 2
        for frame, point in ((0, (0, 0, 0.5)), (2, (1, 2, 3))):
            obj.location = point
            obj.keyframe_insert(data_path='location', frame=frame)
        scene.frame_set(0)
        key = _make_key_from_obj('native-pivot.key', self.root, scene)
        node = next(node for node in key.nodes if node.idx == 1)
        self.assert_vector(node.keyframes[0].position, (0, 0, 0.5))
        self.assert_vector(node.keyframes[-1].position, (1, 2, 3))

