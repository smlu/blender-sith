"""Real Blender MODL import/export, authoring metadata and rejection boundaries."""
import copy
import json
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest import mock

import bpy

from app.support import SceneTestCase
from sith import app
from grim_fixtures import binary_3do_bytes, changed_word
from sith.model.model3doLoader import load3do, Model3doFileFormat, Model3doFileVersion
from sith.model.model3doWriter import save3do
from sith.model.model3doImporter import import3do
from sith.model.model3doExporter import export3do
from sith.model import utils


class BinaryModelAppTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory(prefix='grim binary ')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name).resolve()
        self.source = self.directory / 'input.3do'
        self.output = self.directory / 'output.3do'

    def import_fixture(self, **kwargs):
        data, _ = binary_3do_bytes()
        self.source.write_bytes(data)
        # A known texture size makes pixel/normalized UV checks independent of
        # optional external MAT lookup or the user's installed game resources.
        material = bpy.data.materials.new('checker.mat')
        material.use_nodes = True
        image = bpy.data.images.new('checker', width=64, height=32)
        material.node_tree.nodes.new('ShaderNodeTexImage').image = image
        return import3do(self.source, clearScene=False, importVertexColors=True, **kwargs)

    def mesh_joint(self, root):
        return next(obj for obj in root.children_recursive if obj.type == 'MESH')

    def test_import_palette_label_and_tooltips(self):
        # Draw the real operator with a recording layout; only the Blender UI is replaced.
        layout = mock.Mock()
        app.ImportModel3do.draw(SimpleNamespace(layout=layout), bpy.context)
        labels = [call.kwargs['text'] for call in layout.mock_calls
                  if call[0].endswith('label') and 'text' in call.kwargs]
        self.assertIn('ColorMap File', labels)
        self.assertFalse(any('(JKDF2 & MOTS)' in label for label in labels))

        for operator in (bpy.ops.import_scene.sith_3do, bpy.ops.import_material.sith_mat):
            description = operator.get_rna_type().properties['cmp_file'].description
            for game in ('JKDF2', 'MOTS', 'DroidWorks', 'Grim Fandango'):
                self.assertIn(game, description)

    def test_export_format_label_distinguishes_binary_from_text_version(self):
        format = bpy.ops.export_scene.sith_3do.get_rna_type().properties['version']
        self.assertEqual(format.description, '')
        self.assertTrue(all(item.description for item in format.enum_items))
        grim = format.enum_items[Model3doFileFormat.GrimFandango.name]
        self.assertEqual(grim.name, 'Grim Fandango')
        self.assertIn('binary format', grim.description)
        self.assertIn('For text export, select 2.1', grim.description)
        for detail in ('MODL', 'Little-endian', 'scalar', 'text-version field'):
            self.assertNotIn(detail, grim.description)

    def test_mesh_shadow_follows_texture_and_is_absent_for_empty_joints(self):
        # Keep real objects/properties so moving the checkbox cannot change serialization.
        root = self.import_fixture()
        for obj in (self.mesh_joint(root), root):
            with self.subTest(kind=obj.type):
                layout = mock.Mock()
                context = SimpleNamespace(object=obj, scene=bpy.context.scene)
                app.Model3doPanel.draw(SimpleNamespace(layout=layout), context)
                properties = [call.args[1] for call in layout.mock_calls
                              if call[0].endswith('prop')]
                if obj.type == 'MESH':
                    index = properties.index('sith_model3do_texture_mode')
                    self.assertEqual(properties[index + 1], utils.kModel3doShadow)
                else:
                    self.assertNotIn(utils.kModel3doShadow, properties)

        description = bpy.types.Object.bl_rna.properties[utils.kModel3doShadow].description
        self.assertIn('projected actor-shadow pass', description)
        self.assertIn('Blender shadow settings', description)

    def test_render_mode_labels_keep_saved_identifiers(self):
        # Existing .blend properties and codec values must survive clearer display names.
        lighting = bpy.types.Object.bl_rna.properties['sith_model3do_light_mode'].enum_items
        self.assertEqual(lighting['GfUnknown6'].name, 'Mesh Intensity (Grim Fandango)')
        self.assertIn('cached mesh lighting', lighting['GfUnknown6'].description)
        texture = bpy.types.Object.bl_rna.properties['sith_model3do_texture_mode'].enum_items
        self.assertEqual(texture['PerspectiveUnknown'].name, 'Unknown (2)')
        self.assertIn('not established', texture['PerspectiveUnknown'].description)

        root = self.import_fixture()
        joint = self.mesh_joint(root)
        joint.sith_model3do_texture_mode = 'PerspectiveUnknown'
        export3do(root, str(self.output), Model3doFileFormat.GrimFandango, True, True, True)
        restored, _ = load3do(self.output)
        self.assertEqual(int(restored.geosets[0].meshes[0].lightMode), 6)
        self.assertEqual(int(restored.geosets[0].meshes[0].textureMode), 2)

    def test_binary_import_builds_pose_pixel_uvs_and_opaque_source_layers(self):
        root = self.import_fixture()
        joint = self.mesh_joint(root)
        self.assert_vector(root.location, (0.5, -0.25, 1.5))
        self.assert_vector(joint.data.vertices[0].co, (0.25, 0, 0))
        self.assertTrue(getattr(joint, utils.kModel3doShadow))
        self.assertEqual(joint.sith_model3do_light_mode, 'GfUnknown6')
        self.assertEqual([item.value for item in joint.data.attributes[utils.k3doBinaryVertex].data], [1, 2, 3, 4])
        self.assertEqual([item.value for item in joint.data.attributes[utils.k3doBinaryFace].data], [1])
        self.assert_vector(joint.data.uv_layers.active.data[1].uv, (1, 0))
        self.assert_vector(joint.data.uv_layers.active.data[2].uv, (0, -1))
        metadata = utils.getModel3doBinaryData(joint.data, utils.kModel3doBinaryMesh)
        self.assertEqual(metadata['mesh']['vertexData'], [0, 0xFFFFFFFF, 0x12345678, 0x80000000])
        self.assertEqual(metadata['faces'][0]['id'], 11)
        self.assertEqual(utils.getModel3doBinaryData(root, utils.kModel3doBinaryModel)['geosetPointer'], 0x10203040)

    def test_roundtrip_preserves_binary_metadata_under_hierarchy_and_mesh_options(self):
        for preserve in (False, True):
            for sync in (False, True):
                for recovery in (False, True):
                    with self.subTest(preserve=preserve, sync=sync, recovery=recovery):
                        self.clear_data()
                        root = self.import_fixture(preserveOrder=preserve, allowErrors=recovery)
                        original, _ = load3do(self.source)
                        export3do(root, str(self.output), Model3doFileFormat.GrimFandango, True, True, sync)
                        restored, version = load3do(self.output)
                        self.assertEqual(version, Model3doFileFormat.GrimFandango)
                        self.assertEqual(restored.binaryData['footer'], original.binaryData['footer'])
                        self.assertEqual([node.name for node in restored.meshHierarchy], ['root', 'head', 'empty_joint'])
                        self.assertEqual([node.parentIdx for node in restored.meshHierarchy], [-1, 0, 0])
                        self.assertEqual(restored.meshHierarchy[1].binaryData['transform'], original.meshHierarchy[1].binaryData['transform'])
                        mesh = restored.geosets[0].meshes[0]
                        self.assertEqual(mesh.shadow, 1)
                        self.assertEqual(mesh.binaryData['bounds'], original.geosets[0].meshes[0].binaryData['bounds'])
                        self.assertEqual(mesh.binaryData['vertexData'], [0, 0xFFFFFFFF, 0x12345678, 0x80000000])
                        self.assertEqual(mesh.faces[0].binaryData, original.geosets[0].meshes[0].faces[0].binaryData)
                        self.assertEqual(mesh.uvs, [(0, 0), (64, 0), (0, 32)])
                        self.assert_vector(mesh.vertices[0], (0.25, 0, 0))
                        self.assertEqual(self.source.read_bytes(), binary_3do_bytes()[0])

    def test_wrong_absolute_uv_switch_is_detectably_different(self):
        root = self.import_fixture()
        export3do(root, str(self.output), Model3doFileFormat.GrimFandango, False, True, True)
        restored, _ = load3do(self.output)
        self.assertEqual(restored.geosets[0].meshes[0].uvs, [(0, 0), (1, 0), (0, 1)])

    def test_registered_operator_exports_binary_and_preserves_current_selection(self):
        root = self.import_fixture()
        root.select_set(True)
        bpy.context.view_layer.objects.active = root
        result = bpy.ops.export_scene.sith_3do('EXEC_DEFAULT', filepath=str(self.output),
                                             version=Model3doFileFormat.GrimFandango.name,
                                             absolute_uv=True, export_vert_colors=True)
        self.assertEqual(result, {'FINISHED'})
        self.assertTrue(self.output.read_bytes().startswith(b'LDOM'))
        self.assertIs(bpy.context.view_layer.objects.active, root)

    def test_shadow_edits_do_not_add_grim_keywords_to_sith_exports(self):
        root = self.import_fixture()
        setattr(self.mesh_joint(root), utils.kModel3doShadow, False)
        for version in (Model3doFileFormat.GrimFandango, Model3doFileVersion.Version2_1):
            with self.subTest(version=version):
                export3do(root, str(self.output), version, True, True, True)
                restored, _ = load3do(self.output)
                self.assertEqual(restored.geosets[0].meshes[0].shadow,
                                 0 if version == Model3doFileFormat.GrimFandango else None)
                if version == Model3doFileVersion.Version2_1:
                    self.assertNotIn('SHADOW', self.output.read_text())

    def test_mixed_material_and_missing_texture_records_keep_their_bindings(self):
        root = self.import_fixture()
        model, version = load3do(self.source)
        face = copy.deepcopy(model.geosets[0].meshes[0].faces[0])
        face.materialIdx = -1
        face.geometryMode = 3
        face.uvIdxs = [-1, -1, -1]
        model.geosets[0].meshes[0].faces.append(face)
        save3do(model, self.source, version, '')
        root = import3do(self.source, clearScene=False)
        export3do(root, str(self.output), version, True, True, True)
        restored, _ = load3do(self.output)
        faces = restored.geosets[0].meshes[0].faces
        self.assertEqual([face.materialIdx for face in faces], [0, -1])
        self.assertEqual(faces[1].uvIdxs, [-1, -1, -1])
        self.assertEqual(faces[1].binaryData['materialPointer'], 0)
        self.assertEqual(faces[1].binaryData['texturePointer'], 0)

    def test_invalid_binary_records_never_clear_existing_scene(self):
        data, offsets = binary_3do_bytes()
        for broken in (data[:-1], data + b'garbage', changed_word(data, offsets['vertex_index'], 99),
                       changed_word(data, offsets['node1_parent'], 1)):
            for recovery in (False, True):
                with self.subTest(recovery=recovery, size=len(broken)):
                    sentinel = bpy.data.objects.new('keep me', None)
                    bpy.context.scene.collection.objects.link(sentinel)
                    self.source.write_bytes(broken)
                    before = set(bpy.data.objects)
                    with self.assertRaises(ValueError):
                        import3do(self.source, clearScene=True, allowErrors=recovery)
                    self.assertEqual(set(bpy.data.objects), before)

    def test_damaged_blend_metadata_does_not_replace_previous_export(self):
        for target, key in (('model', utils.kModel3doBinaryModel), ('mesh', utils.kModel3doBinaryMesh),
                             ('node', utils.kModel3doBinaryNode)):
            with self.subTest(target=target):
                self.clear_data()
                root = self.import_fixture()
                joint = self.mesh_joint(root)
                owner = root if target == 'model' else joint.data if target == 'mesh' else joint
                owner[key] = 'not JSON'
                self.output.write_bytes(b'previous export')
                with self.assertRaisesRegex(ValueError, 'metadata'):
                    export3do(root, str(self.output), Model3doFileFormat.GrimFandango, True, True, True)
                self.assertEqual(self.output.read_bytes(), b'previous export')

    def test_empty_retail_skeleton_uses_finite_blender_bounds_and_restores_sentinel(self):
        self.source.write_bytes(binary_3do_bytes(empty=True)[0])
        root = import3do(self.source, clearScene=False, importRadiusObj=True)
        self.assertEqual(root[utils.kModel3doRadius], 0)
        self.assertEqual(utils.getModel3doBinaryData(root, utils.kModel3doBinaryModel)['emptyRadius'], True)
        export3do(root, str(self.output), Model3doFileFormat.GrimFandango, True, True, True)
        restored, _ = load3do(self.output)
        self.assertEqual(restored.radius, math.inf)
        self.assertEqual(restored.geosets[0].meshes[0].vertices, [])

    def test_vertex_metadata_is_not_welded_between_coincident_source_vertices(self):
        root = self.import_fixture()
        model, version = load3do(self.source)
        mesh = model.geosets[0].meshes[0]
        mesh.vertices[3] = mesh.vertices[0]
        mesh.normals[3] = mesh.normals[0]
        mesh.vertexColors[3] = mesh.vertexColors[0]
        face = copy.deepcopy(mesh.faces[0])
        face.vertexIdxs = [3, 1, 2]
        mesh.faces.append(face)
        save3do(model, self.source, version, '')
        root = import3do(self.source, clearScene=False)
        export3do(root, str(self.output), version, True, True, True)
        restored, _ = load3do(self.output)
        mesh = restored.geosets[0].meshes[0]
        self.assertEqual(len(mesh.vertices), 4)
        self.assertEqual(set(mesh.binaryData['vertexData']), {0, 0xFFFFFFFF, 0x12345678, 0x80000000})
        self.assertNotEqual(mesh.faces[0].vertexIdxs[0], mesh.faces[1].vertexIdxs[0])

    def test_authored_vertex_normals_survive_binary_import_export(self):
        root = self.import_fixture()
        model, version = load3do(self.source)
        model.geosets[0].meshes[0].normals[0] = (0.6, 0, 0.8)
        save3do(model, self.source, version, '')
        root = import3do(self.source, clearScene=False)
        self.assertTrue(self.mesh_joint(root).data.has_custom_normals)
        export3do(root, str(self.output), version, True, True, True)
        restored, _ = load3do(self.output)
        self.assert_vector(restored.geosets[0].meshes[0].normals[0], (0.6, 0, 0.8))

    def test_blender_display_suffix_does_not_overflow_binary_mesh_names(self):
        root = self.import_fixture()
        model, version = load3do(self.source)
        model.geosets[0].meshes[0].name = 'm' * 32
        save3do(model, self.source, version, '')
        first = import3do(self.source, clearScene=False)
        second = import3do(self.source, clearScene=False)
        self.assertNotEqual(self.mesh_joint(first).data.name, self.mesh_joint(second).data.name)
        export3do(second, str(self.output), version, True, True, True)
        restored, _ = load3do(self.output)
        self.assertEqual(restored.geosets[0].meshes[0].name, 'm' * 32)

    def test_normal_edits_override_the_imported_precision_snapshot(self):
        root = self.import_fixture()
        mesh = self.mesh_joint(root).data
        mesh.normals_split_custom_set([(0, 0.6, 0.8)] * len(mesh.loops))
        current = tuple(mesh.corner_normals[0].vector)
        export3do(root, str(self.output), Model3doFileFormat.GrimFandango, True, True, True)
        restored, _ = load3do(self.output)
        self.assert_vector(restored.geosets[0].meshes[0].normals[0], current)

    def test_nonpolygon_binary_record_is_rejected_before_scene_changes(self):
        root = self.import_fixture()
        model, version = load3do(self.source)
        face = model.geosets[0].meshes[0].faces[0]
        face.vertexIdxs = face.vertexIdxs[:2]
        face.uvIdxs = face.uvIdxs[:2]
        save3do(model, self.source, version, '')
        before = set(bpy.data.objects)
        with self.assertRaisesRegex(ValueError, 'fewer than three'):
            import3do(self.source, clearScene=True)
        self.assertEqual(set(bpy.data.objects), before)

    def test_nonboolean_shadow_word_survives_until_its_checkbox_changes(self):
        root = self.import_fixture()
        model, version = load3do(self.source)
        model.geosets[0].meshes[0].shadow = 0x80000001
        save3do(model, self.source, version, '')
        root = import3do(self.source, clearScene=False)
        export3do(root, str(self.output), version, True, True, True)
        restored, _ = load3do(self.output)
        self.assertEqual(restored.geosets[0].meshes[0].shadow, 0x80000001)
        setattr(self.mesh_joint(root), utils.kModel3doShadow, False)
        export3do(root, str(self.output), version, True, True, True)
        restored, _ = load3do(self.output)
        self.assertEqual(restored.geosets[0].meshes[0].shadow, 0)

    def test_binary_strings_do_not_use_text_identifier_restrictions(self):
        root = self.import_fixture()
        model, version = load3do(self.source)
        model.meshHierarchy[1].name = 'node "A"#1'
        model.geosets[0].meshes[0].name = 'mesh "plane"#1'
        model.materials[0] = 'checker "color"#1.mat'
        save3do(model, self.source, version, '')
        root = import3do(self.source, clearScene=False)
        export3do(root, str(self.output), version, True, True, True)
        restored, _ = load3do(self.output)
        self.assertEqual(restored.meshHierarchy[1].name, 'node "A"#1')
        self.assertEqual(restored.geosets[0].meshes[0].name, 'mesh "plane"#1')
        self.assertEqual(restored.materials, ['checker "color"#1.mat'])
        self.output.write_bytes(b'previous export')
        with self.assertRaises(AssertionError):
            export3do(root, str(self.output), Model3doFileVersion.Version2_1, True, True, True)
        self.assertEqual(self.output.read_bytes(), b'previous export')

    def test_malformed_normal_snapshots_fail_before_replacing_output(self):
        for value in ([1], [[0, 0]], [[0, 'bad', 1]], [[0, math.inf, 1]]):
            with self.subTest(value=value):
                self.clear_data()
                root = self.import_fixture()
                mesh = self.mesh_joint(root).data
                metadata = utils.getModel3doBinaryData(mesh, utils.kModel3doBinaryMesh)
                metadata['loopNormals'] = value
                mesh[utils.kModel3doBinaryMesh] = json.dumps(metadata)
                self.output.write_bytes(b'previous export')
                with self.assertRaisesRegex(ValueError, 'normal metadata'):
                    export3do(root, str(self.output), Model3doFileFormat.GrimFandango, True, True, True)
                self.assertEqual(self.output.read_bytes(), b'previous export')

    def test_text_models_without_grim_markers_can_preserve_authored_normals(self):
        root = self.import_fixture()
        model, _ = load3do(self.source)
        mesh = model.geosets[0].meshes[0]
        mesh.shadow, mesh.lightMode = None, 3
        mesh.normals[0] = (0.6, 0, 0.8)
        save3do(model, self.source, Model3doFileVersion.Version2_1, '')
        root = import3do(self.source, clearScene=False, importVertexNormals=True)
        export3do(root, str(self.output), Model3doFileFormat.GrimFandango, True, True, True)
        restored, _ = load3do(self.output)
        self.assert_vector(restored.geosets[0].meshes[0].normals[0], (0.6, 0, 0.8))
        self.assertFalse(bpy.ops.import_scene.sith_3do.get_rna_type().properties['vertex_normals'].default)
