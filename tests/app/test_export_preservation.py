"""Preserve normal seams, complete hierarchies, identifiers and export defaults."""
from pathlib import Path
import math
import tempfile

import bpy
import mathutils

from app.support import SceneTestCase
from fixtures import TV
from sith.key.keyExporter import exportKey
from sith.key.keyLoader import loadKey
from sith.model.model3doExporter import export3do, makeModel3doFromObj, _scaled_normal
from sith.model.model3doImporter import import3do
from sith.model.model3doLoader import load3do, Model3doFileVersion
from sith.model.model3doWriter import save3do
from sith.model.utils import kModel3doRadiusKind, kMeshRadius


def add_object(name, data=None, parent=None):
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = parent
    return obj


def add_mesh(name, parent=None, vertices=None, faces=None):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices or [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], faces or [(0, 1, 2)])
    mesh.update()
    return add_object(name, mesh, parent)


class NormalSeamTests(SceneTestCase):
    def test_normal_scaling_preserves_direction_across_float32_scales(self):
        normal = (1.0, 2.0, 3.0)
        for exponent in (-30, -20, -12, -8, 0, 8, 12, 20, 30):
            for signs in ((1, 1, 1), (-1, 1, 1), (-1, -1, 1)):
                scale = mathutils.Vector(tuple(sign * factor * 10.0 ** exponent
                                               for sign, factor in zip(signs, (0.5, 2, 3))))
                with self.subTest(exponent=exponent, signs=signs):
                    # Independent inverse-transpose reference. Normalize before
                    # float32 storage so the reference cannot share the bug.
                    expected = tuple(value / factor for value, factor in zip(normal, scale))
                    length = math.hypot(*expected)
                    expected = tuple(value / length for value in expected)
                    actual = _scaled_normal(normal, scale)
                    self.assertTrue(all(math.isfinite(value) for value in actual))
                    self.assertAlmostEqual(math.hypot(*actual), 1, delta=2e-6)
                    self.assert_vector(actual, expected, 2e-6)

    def test_normal_scaling_keeps_degenerate_normals_and_flattened_meshes(self):
        for scale, expected in (((0, 2, 3), (1, 0, 0)), ((0, 0, 3), (0, 0, 0)),
                                ((0, 0, 0), (0, 0, 0))):
            with self.subTest(scale=scale):
                self.assert_vector(_scaled_normal((1, 2, 3), mathutils.Vector(scale)), expected)
        for magnitude in (1e-30, 1, 1e30):
            self.assertEqual(_scaled_normal((0, 0, 0), mathutils.Vector((magnitude,) * 3)), (0, 0, 0))

    def test_small_scale_exports_keep_face_and_vertex_normals(self):
        obj = add_mesh('small_scale')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'small.3do'
            for magnitude in (1e-12, 1e-9, 1e12, 1e18):
                for reflected in (False, True):
                    obj.scale = (-magnitude if reflected else magnitude, magnitude, magnitude)
                    for version in Model3doFileVersion:
                        for sync in (False, True):
                            with self.subTest(scale=magnitude, reflected=reflected, version=version, sync=sync):
                                export3do(obj, str(path), version, False, False, sync)
                                restored, _ = load3do(path)
                                mesh = restored.geosets[0].meshes[0]
                                self.assert_vector(mesh.faces[0].normal, (0, 0, 1), 2e-6)
                                for normal in mesh.normals:
                                    self.assert_vector(normal, (0, 0, 1), 2e-6)
                                expected = sorted(tuple(vertex.co[i] * obj.scale[i] for i in range(3))
                                                  for vertex in obj.data.vertices)
                                for actual, source in zip(sorted(mesh.vertices), expected):
                                    self.assertTrue(all(math.isclose(a, b, rel_tol=2e-6, abs_tol=1e-40)
                                                        for a, b in zip(actual, source)))

    def test_custom_corner_normals_survive_all_versions_scales_and_sync_modes(self):
        obj = add_mesh('custom', vertices=[(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)],
                       faces=[(0, 1, 2), (1, 3, 2)])
        for polygon in obj.data.polygons:
            polygon.use_smooth = True
        direction = mathutils.Vector((1, 0, 1)).normalized()
        obj.data.normals_split_custom_set([(0, 0, 1)] * 3 + [direction] * 3)
        obj.data.update()
        authored = [normal.vector.copy() for normal in obj.data.corner_normals]
        # The shared positions have different lighting normals on each face.
        # Export must split them instead of using Blender's vertex average.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'custom.3do'
            for version in Model3doFileVersion:
                for scale in ((1, 1, 1), (2, 3, 4), (-2, 3, 4)):
                    for sync in (False, True):
                        with self.subTest(version=version, scale=scale, sync=sync):
                            obj.scale = scale
                            export3do(obj, str(path), version, False, False, sync)
                            model, _ = load3do(path)
                            mesh = model.geosets[0].meshes[0]
                            self.assertEqual(len(mesh.vertices), 6)
                            self.assertFalse(set(mesh.faces[0].vertexIdxs) & set(mesh.faces[1].vertexIdxs))
                            for source_face, face in zip(obj.data.polygons, mesh.faces):
                                loops = list(source_face.loop_indices)
                                if scale[0] < 0:
                                    loops.reverse()
                                for loop, vertex in zip(loops, face.vertexIdxs):
                                    expected = mathutils.Vector(tuple(authored[loop][i] / scale[i] for i in range(3))).normalized()
                                    self.assert_vector(mesh.normals[vertex], expected, 2e-6)
                                self.assert_vector(face.normal, (0, 0, 1), 2e-6)

    def test_uniform_custom_normals_do_not_prevent_welding(self):
        obj = add_mesh('custom', vertices=[(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)],
                       faces=[(0, 1, 2), (1, 3, 2)])
        for polygon in obj.data.polygons:
            polygon.use_smooth = True
        obj.data.normals_split_custom_set([(0, 0, 1)] * len(obj.data.loops))
        mesh = makeModel3doFromObj('custom.3do', obj).geosets[0].meshes[0]
        self.assertEqual(len(mesh.vertices), 4)
        for normal in mesh.normals:
            self.assert_vector(normal, (0, 0, 1))

    def test_explicit_sharp_edges_keep_corner_normals_without_custom_normals(self):
        obj = add_mesh('sharp', vertices=[(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)],
                       faces=[(0, 1, 2), (0, 3, 1)])
        for polygon in obj.data.polygons:
            polygon.use_smooth = True
        for edge in obj.data.edges:
            if set(edge.vertices) == {0, 1}:
                edge.use_edge_sharp = True
        obj.data.update()
        self.assertFalse(obj.data.has_custom_normals)
        mesh = makeModel3doFromObj('sharp.3do', obj).geosets[0].meshes[0]
        self.assertEqual(len(mesh.vertices), 6)
        for face, expected in zip(mesh.faces, ((0, 0, 1), (0, 1, 0))):
            for vertex in face.vertexIdxs:
                self.assert_vector(mesh.normals[vertex], expected)

    def test_mesh_without_custom_normals_keeps_geometric_vertex_lighting(self):
        obj = add_mesh('smooth', vertices=[(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)],
                       faces=[(0, 1, 2), (0, 3, 1)])
        self.assertFalse(obj.data.has_custom_normals)
        expected = [vertex.normal.copy() for vertex in obj.data.vertices]
        mesh = makeModel3doFromObj('smooth.3do', obj).geosets[0].meshes[0]
        for polygon, face in zip(obj.data.polygons, mesh.faces):
            for source, target in zip(polygon.vertices, face.vertexIdxs):
                self.assert_vector(mesh.normals[target], expected[source])

    def test_coincident_vertices_keep_distinct_geometric_normals(self):
        vertices = [(0, 0, 0), (1, 0, 0), (0, 1, 0),
                    (0, 0, 0), (1, 0, 0), (0, 0, 1)]
        obj = add_mesh('seams', vertices=vertices, faces=[(0, 1, 2), (3, 4, 5)])
        colors = obj.data.color_attributes.new(name='colors', type='FLOAT_COLOR', domain='CORNER')
        for value in colors.data:
            value.color = (0.25, 0.5, 0.75, 1)
        obj.data.color_attributes.active_color = colors

        # The two triangles have separate, valid +Z/-Y normals. Matching colors
        # must not weld their shared positions and reuse the first face's normals.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'normals.3do'
            for version in Model3doFileVersion:
                for scale in ((1, 1, 1), (2, 3, 4), (-2, 3, 4), (1, 0, 1)):
                    for sync in (False, True):
                        for vertexColors in (False, True):
                            with self.subTest(version=version, scale=scale, sync=sync, colors=vertexColors):
                                obj.scale = scale
                                export3do(obj, str(path), version, False, vertexColors, sync)
                                resource, _ = load3do(path)
                                mesh = resource.geosets[0].meshes[0]
                                self.assertEqual(len(mesh.vertices), 6)
                                self.assertFalse(set(mesh.faces[0].vertexIdxs) & set(mesh.faces[1].vertexIdxs))
                                for face in mesh.faces:
                                    a, b, c = [mathutils.Vector(mesh.vertices[index]) for index in face.vertexIdxs]
                                    expected = (b - a).cross(c - a).normalized()
                                    for index in face.vertexIdxs:
                                        self.assert_vector(mesh.normals[index], expected, 1e-6)

    def test_equal_normals_and_colors_still_allow_vertex_welding(self):
        vertices = [(0, 0, 0), (1, 0, 0), (0, 1, 0),
                    (1, 0, 0), (1, 1, 0), (0, 1, 0)]
        obj = add_mesh('coplanar', vertices=vertices, faces=[(0, 1, 2), (3, 4, 5)])
        mesh = makeModel3doFromObj('coplanar.3do', obj).geosets[0].meshes[0]
        self.assertEqual(len(mesh.vertices), 4)
        self.assertEqual(len(set(mesh.faces[0].vertexIdxs) & set(mesh.faces[1].vertexIdxs)), 2)
        for normal in mesh.normals:
            self.assert_vector(normal, (0, 0, 1))

    def test_color_seams_still_prevent_welding_when_normals_match(self):
        vertices = [(0, 0, 0), (1, 0, 0), (0, 1, 0)] * 2
        obj = add_mesh('colors', vertices=vertices, faces=[(0, 1, 2), (3, 4, 5)])
        colors = obj.data.color_attributes.new(name='colors', type='FLOAT_COLOR', domain='CORNER')
        for index, value in enumerate(colors.data):
            value.color = (1, 0, 0, 1) if index < 3 else (0, 1, 0, 1)
        obj.data.color_attributes.active_color = colors
        mesh = makeModel3doFromObj('colors.3do', obj, exportVertexColors=True).geosets[0].meshes[0]
        self.assertEqual(len(mesh.vertices), 6)
        for face, expected in zip(mesh.faces, ((1, 0, 0, 1), (0, 1, 0, 1))):
            for index in face.vertexIdxs:
                self.assert_vector(mesh.vertexColors[index], expected)
                self.assert_vector(mesh.normals[index], (0, 0, 1))


class HierarchyBranchTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.root = add_object('wrapper')
        self.joint = add_mesh('joint', self.root)
        scene = bpy.context.scene
        scene.frame_start, scene.frame_end = 0, 4
        scene.render.fps, scene.render.fps_base = 30, 1
        scene.timeline_markers.clear()
        scene.sith_key_flags, scene.sith_key_types = set(), 'ffff'

    def controller(self, kind, parent):
        factories = {
            'CURVE': lambda: bpy.data.curves.new('curve', 'CURVE'),
            'ARMATURE': lambda: bpy.data.armatures.new('armature'),
            'CAMERA': lambda: bpy.data.cameras.new('camera'),
            'LIGHT': lambda: bpy.data.lights.new('light', 'POINT'),
        }
        return add_object('controller', factories[kind](), parent)

    def test_unsupported_intermediary_rejects_model_and_key_without_overwrite(self):
        for kind in ('CURVE', 'ARMATURE', 'CAMERA', 'LIGHT'):
            for meshJoint in (False, True):
                controller = self.controller(kind, self.joint)
                nested = add_mesh('nested', controller) if meshJoint else add_object('nested', parent=controller)
                nested.keyframe_insert(data_path='location', frame=0)
                bpy.context.scene.frame_set(0)
                before = [(obj, obj.parent, obj.matrix_basis.copy()) for obj in bpy.context.scene.objects]
                for format in ('3do', 'key'):
                    with self.subTest(kind=kind, mesh=meshJoint, format=format):
                        path = self.folder / ('safe.' + format)
                        path.write_bytes(b'previous valid export')
                        with self.assertRaisesRegex(ValueError, 'unsupported parent'):
                            if format == '3do':
                                export3do(self.root, str(path), Model3doFileVersion.Version2_3, False, False, True)
                            else:
                                exportKey(self.root, bpy.context.scene, str(path))
                        self.assertEqual(path.read_bytes(), b'previous valid export')
                        for obj, parent, matrix in before:
                            self.assertEqual(obj.parent, parent)
                            self.assertEqual(obj.matrix_basis, matrix)
                bpy.data.objects.remove(nested, do_unlink=True)
                bpy.data.objects.remove(controller, do_unlink=True)

    def test_nested_unsupported_parent_chain_cannot_hide_a_mesh(self):
        first = self.controller('CURVE', self.joint)
        second = self.controller('CAMERA', first)
        add_mesh('nested', second)
        for hierarchyOnly in (False, True):
            with self.subTest(hierarchyOnly=hierarchyOnly), self.assertRaisesRegex(ValueError, 'nested.*unsupported parent'):
                makeModel3doFromObj('test.3do', self.root, hierarchyOnly=hierarchyOnly)

    def test_nonmodel_leaves_and_branches_are_ignored(self):
        for kind in ('CURVE', 'ARMATURE', 'CAMERA', 'LIGHT'):
            controller = self.controller(kind, self.joint)
            self.controller('CAMERA', controller)
        self.joint.keyframe_insert(data_path='location', frame=0)
        resource = makeModel3doFromObj('test.3do', self.root)
        self.assertEqual([node.name for node in resource.meshHierarchy], ['joint'])
        self.assertEqual(len(resource.geosets[0].meshes), 1)
        path = self.folder / 'test.key'
        exportKey(self.root, bpy.context.scene, str(path))
        self.assertEqual([node.meshName for node in loadKey(path).nodes], ['joint'])

    def test_radius_helpers_remain_excluded_from_joint_hierarchy(self):
        helper = add_mesh('radius', self.joint)
        helper[kModel3doRadiusKind] = kMeshRadius
        add_object('helper_detail', parent=helper)
        resource = makeModel3doFromObj('test.3do', self.root)
        self.assertEqual([node.name for node in resource.meshHierarchy], ['joint'])
        self.assertEqual(len(resource.geosets[0].meshes), 1)

    def test_unsupported_root_is_rejected_by_direct_export_api(self):
        root = self.controller('ARMATURE', None)
        add_mesh('nested', root)
        for hierarchyOnly in (False, True):
            with self.subTest(hierarchyOnly=hierarchyOnly), self.assertRaisesRegex(ValueError, 'MESH or EMPTY root'):
                makeModel3doFromObj('test.3do', root, hierarchyOnly=hierarchyOnly)


class HierarchyNameTests(SceneTestCase):
    def test_long_imported_names_survive_every_version_order_and_sync_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / 'source.3do', Path(directory) / 'output.3do'
            for version in Model3doFileVersion:
                for length in (63, 64, 95, 127, 128, 300):
                    for preserve in (False, True):
                        for sync in (False, True):
                            with self.subTest(version=version, length=length, preserve=preserve, sync=sync):
                                resource, _ = load3do(TV / 'model/triangle.3do')
                                # The suffix is their only distinction. Truncation
                                # would collapse both joint identities to one name.
                                names = ['n' * (length - 1) + suffix for suffix in ('a', 'b')]
                                for node, name in zip(resource.meshHierarchy, names):
                                    node.name = name
                                save3do(resource, source, version, '')
                                root = import3do(source, uvAbsolute_2_1=False, preserveOrder=preserve)
                                stored = {obj.sith_model3do_hnode_idx: obj.sith_model3do_hnode_name
                                          for obj in bpy.context.scene.objects if obj.sith_model3do_hnode_idx >= 0}
                                self.assertEqual(stored, dict(enumerate(names)))
                                warnings = []
                                export3do(root, str(output), version, False, True, sync, warnings=warnings)
                                restored, _ = load3do(output)
                                self.assertEqual([node.name for node in restored.meshHierarchy], names)
                                self.assertEqual([node.parentIdx for node in restored.meshHierarchy], [-1, 0])
                                limit = 31 if version == Model3doFileVersion.Version2_1 else 127
                                self.assertEqual(sum('joint name' in warning for warning in warnings), 2 if length > limit else 0)

    def test_long_name_properties_survive_blend_serialization(self):
        obj = add_mesh('short_display_name')
        name = 'joint_' + 'x' * 300
        obj.sith_model3do_hnode_name = name
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'name.blend'
            bpy.data.libraries.write(str(path), {obj})
            with bpy.data.libraries.load(str(path)) as (source, destination):
                destination.objects = [obj.name]
            self.assertEqual(destination.objects[0].sith_model3do_hnode_name, name)

    def test_key_target_limits_still_reject_long_joint_names(self):
        obj = add_mesh('joint')
        obj.keyframe_insert(data_path='location', frame=0)
        scene = bpy.context.scene
        scene.frame_start, scene.frame_end = 0, 4
        scene.render.fps, scene.render.fps_base = 30, 1
        scene.timeline_markers.clear()
        scene.sith_key_flags, scene.sith_key_types = set(), 'ffff'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'safe.key'
            for target, length in (('IJIM', 64), ('JKDF2', 32), ('MOTS', 32), ('CUSTOM', 65)):
                with self.subTest(target=target):
                    obj.sith_model3do_hnode_name = 'j' * length
                    path.write_bytes(b'previous valid export')
                    with self.assertRaises((ValueError, AssertionError)):
                        exportKey(obj, scene, str(path), target=target)
                    self.assertEqual(path.read_bytes(), b'previous valid export')


class HexDefaultTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        self.obj = add_mesh('joint')
        self.scene = bpy.context.scene
        if 'sith_key_types' in self.scene:
            del self.scene['sith_key_types']
        self.addCleanup(lambda: self.scene.pop('sith_key_types', None))
        self.scene.frame_start, self.scene.frame_end = 0, 4
        self.scene.render.fps, self.scene.render.fps_base = 30, 1
        self.scene.timeline_markers.clear()
        self.scene.sith_key_flags = set()
        bpy.context.view_layer.objects.active = self.obj
        self.obj.select_set(True)

    def test_unset_getters_return_normalized_defaults_without_storing_them(self):
        for owner, name, expected in ((self.scene, 'sith_key_types', 'FFFF'),
                                       (self.obj, 'sith_model3do_hnode_type', '01'),
                                       (self.obj, 'sith_model3do_hnode_flags', '')):
            with self.subTest(name=name):
                self.assertNotIn(name, owner)
                self.assertEqual(getattr(owner, name), expected)
                self.assertNotIn(name, owner)
        node = makeModel3doFromObj('defaults.3do', self.obj).meshHierarchy[0]
        self.assertEqual(int(node.type), 1)
        self.assertEqual(int(node.flags), 0)

    def test_hex_normalization_and_invalid_input_preserve_existing_values(self):
        for owner, name in ((self.scene, 'sith_key_types'), (self.obj, 'sith_model3do_hnode_type')):
            for value, expected in (('1', '01'), ('0x0001', '01'), ('0', '00'),
                                    ('ffff', 'FFFF'), ('0xFFFF', 'FFFF'), ('a', '0A')):
                with self.subTest(name=name, value=value):
                    setattr(owner, name, value)
                    self.assertEqual(getattr(owner, name), expected)
            for invalid in ('not_hex', 'GG', '0x'):
                with self.subTest(name=name, invalid=invalid):
                    setattr(owner, name, invalid)
                    self.assertEqual(getattr(owner, name), '0A')
        self.scene.sith_key_types = ''
        self.obj.sith_model3do_hnode_type = ''
        self.assertEqual(self.scene.sith_key_types, 'FFFF')
        self.assertEqual(self.obj.sith_model3do_hnode_type, '01')

    def test_direct_operator_respects_scene_defaults_and_explicit_override_precedence(self):
        self.obj.keyframe_insert(data_path='location', frame=0)
        cases = ((None, {}, 0xFFFF), ('8008', {}, 0x8008), ('0', {}, 0),
                 ('8008', {'node_types': '0'}, 0), ('8008', {'node_types': 'FFFF'}, 0xFFFF),
                 ('8008', {'node_types': ''}, 0xFFFF), ('0', {'node_types': '8008'}, 0x8008))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'defaults.key'
            for sceneValue, options, expected in cases:
                with self.subTest(scene=sceneValue, options=options):
                    if sceneValue is None:
                        self.scene.pop('sith_key_types', None)
                    else:
                        self.scene.sith_key_types = sceneValue
                    self.assertEqual(bpy.ops.export_anim.sith_key(filepath=str(path), **options), {'FINISHED'})
                    self.assertEqual(int(loadKey(path).nodeTypes), expected)
                    self.assertEqual(int(self.scene.sith_key_types, 16), expected)

    def test_failed_export_does_not_store_defaults_or_replace_output(self):
        self.obj.keyframe_insert(data_path='location', frame=0)
        self.obj.constraints.new('COPY_LOCATION')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'safe.key'
            path.write_bytes(b'previous valid export')
            with self.assertRaisesRegex(RuntimeError, 'non-pivot constraints'):
                bpy.ops.export_anim.sith_key(filepath=str(path), node_types='8008')
            self.assertNotIn('sith_key_types', self.scene)
            self.assertEqual(self.scene.sith_key_types, 'FFFF')
            self.assertEqual(path.read_bytes(), b'previous valid export')
