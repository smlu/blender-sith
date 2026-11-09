"""Face-lighting controls retain signed/HDR channels through edits and export."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest import mock

import bpy
import bmesh

from app.support import SceneTestCase
from fixtures import TV
from sith import app
from sith.model.model3doExporter import export3do
from sith.model.model3doLoader import load3do, Model3doFileVersion
from sith.model.model3doImporter import import3do
from sith.model.utils import (bmMeshInit3doLayers, bmFaceGetExtraLight,
                              bmFaceSetExtraLight, bmFaceGetType, bmFaceSetType)
from sith.types import Vector4f
from sith.types.vector import kFloat32Max


class FaceLightingUpdateTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        mesh = bpy.data.meshes.new('lighting')
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0), (2, 0, 0)], [],
                         [(0, 1, 2), (1, 3, 2), (1, 4, 3)])
        self.obj = bpy.data.objects.new('lighting', mesh)
        bpy.context.scene.collection.objects.link(self.obj)
        bpy.context.view_layer.objects.active = self.obj
        self.obj.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        self.bm = bmesh.from_edit_mesh(mesh)
        self.bm.faces.ensure_lookup_table()
        bmMeshInit3doLayers(self.bm)
        self.colors = [(-0.25, 2, 0.5, 1), (3, 0.25, -2, 0.5), (-4, 5, 6, 1)]
        for face, color in zip(self.bm.faces, self.colors):
            face.select_set(face.index == 0)
            bmFaceSetExtraLight(face, self.bm, Vector4f(*color))
            bmFaceSetType(face, self.bm, 0x80000080 | face.index)
        self.bm.faces.active = self.bm.faces[0]
        self.layer = bpy.context.window_manager.sith_mesh3do_face_layer
        self.layer.face_id = -1

    def sync_panel(self):
        # Only layout drawing is replaced; real RNA setters, BMesh data and
        # callbacks run through the actual panel synchronization method.
        panel = SimpleNamespace(layout=mock.Mock(), _get_face_id=app.Mesh3doFacePanel._get_face_id)
        app.Mesh3doFacePanel.draw(panel, bpy.context)

    def stored_colors(self):
        return [tuple(bmFaceGetExtraLight(face, self.bm)) for face in self.bm.faces]

    def test_panel_sync_retains_signed_hdr_values_without_changing_faces(self):
        self.sync_panel()
        self.assert_vector(self.layer.extra_light, self.colors[0])
        self.assertEqual(self.stored_colors(), self.colors)

    def test_editing_alpha_preserves_signed_hdr_rgb_and_unselected_faces(self):
        self.sync_panel()
        self.layer.extra_light[3] = 0.75
        self.assertEqual(self.stored_colors(), [(-0.25, 2, 0.5, 0.75), *self.colors[1:]])

    def test_editing_one_rgb_channel_keeps_the_other_channels(self):
        self.sync_panel()
        self.layer.extra_light[2] = -3
        self.assertEqual(self.stored_colors(), [(-0.25, 2, -3, 1), *self.colors[1:]])

    def test_normal_slider_range_does_not_limit_finite_storage(self):
        property = self.layer.bl_rna.properties['extra_light']
        self.assertEqual((property.soft_min, property.soft_max), (0, 1))
        self.assertLessEqual(property.hard_min, -kFloat32Max)
        self.assertGreaterEqual(property.hard_max, kFloat32Max)
        bmFaceSetExtraLight(self.bm.faces[0], self.bm, Vector4f(-kFloat32Max, kFloat32Max, 0.5, 1))
        self.sync_panel()
        self.layer.extra_light[3] = 0.75
        self.assertEqual(tuple(bmFaceGetExtraLight(self.bm.faces[0], self.bm)),
                         (-kFloat32Max, kFloat32Max, 0.5, 0.75))

    def test_other_panel_edits_do_not_change_extra_light(self):
        self.sync_panel()
        self.layer.geo_mode = 'Wireframe'
        self.layer.type = {'DoubleSided'}
        self.assertEqual(self.stored_colors(), self.colors)

    def test_multi_face_lighting_edit_keeps_flags_and_unselected_color(self):
        self.bm.faces[1].select_set(True)
        before = [int(bmFaceGetType(face, self.bm)) for face in self.bm.faces]
        self.sync_panel()
        self.layer.extra_light = (-2, 4, 0.5, 0.75)
        self.assertEqual(self.stored_colors(), [(-2, 4, 0.5, 0.75)] * 2 + [self.colors[2]])
        self.assertEqual([int(bmFaceGetType(face, self.bm)) for face in self.bm.faces], before)

    def test_edited_values_survive_each_3do_output_version(self):
        self.sync_panel()
        self.layer.extra_light[3] = 0.75
        bpy.ops.object.mode_set(mode='OBJECT')
        expected = {Model3doFileVersion.Version2_1: (0.75, 0.75, 0.75, 1),
                    Model3doFileVersion.Version2_2: (-0.25, 2, 0.5, 1),
                    Model3doFileVersion.Version2_3: (-0.25, 2, 0.5, 0.75)}
        with tempfile.TemporaryDirectory() as directory:
            for version, color in expected.items():
                with self.subTest(version=version):
                    path = Path(directory) / (version.name + '.3do')
                    export3do(self.obj, str(path), version, False, False, True)
                    model, _ = load3do(path)
                    self.assert_vector(model.geosets[0].meshes[0].faces[0].color, color)

    def test_imported_hdr_vector_survives_panel_edit_and_export(self):
        expected = {Model3doFileVersion.Version2_1: (0.75, 0.75, 0.75, 1),
                    Model3doFileVersion.Version2_2: (-0.25, 2, 0.5, 1),
                    Model3doFileVersion.Version2_3: (-0.25, 2, 0.5, 0.75)}
        with tempfile.TemporaryDirectory() as directory:
            for version, color in expected.items():
                for sync in (False, True):
                    with self.subTest(version=version, sync=sync):
                        self.clear_data()
                        root = import3do(TV / 'model/face_lighting_hdr.3do', clearScene=False, preserveOrder=sync)
                        self.obj = next(obj for obj in root.children_recursive if obj.type == 'MESH')
                        bpy.context.view_layer.objects.active = self.obj
                        self.obj.select_set(True)
                        bpy.ops.object.mode_set(mode='EDIT')
                        self.bm = bmesh.from_edit_mesh(self.obj.data)
                        self.bm.faces.ensure_lookup_table()
                        self.bm.faces.active = self.bm.faces[0]
                        self.bm.faces[0].select_set(True)
                        self.layer.face_id = -1
                        self.sync_panel()
                        self.assert_vector(self.layer.extra_light, (-0.25, 2, 0.5, 1))
                        self.layer.extra_light[3] = 0.75
                        bpy.ops.object.mode_set(mode='OBJECT')
                        path = Path(directory) / f'{version.name}-{sync}.3do'
                        export3do(root, str(path), version, False, False, sync)
                        model, _ = load3do(path)
                        face = model.geosets[0].meshes[0].faces[0]
                        self.assert_vector(face.color, color)
                        self.assertEqual(int(face.type), 0x80000081)
