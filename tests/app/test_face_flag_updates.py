"""UI flag edits preserve unknown bits and unrelated selected-face values."""
from pathlib import Path
import tempfile

import bpy
import bmesh

from app.support import SceneTestCase
from sith import app
from sith.model.model3do import FaceType
from sith.model.model3doExporter import export3do
from sith.model.model3doLoader import load3do, Model3doFileVersion
from sith.model.utils import bmMeshInit3doLayers, bmFaceGetType, bmFaceSetType


class FaceFlagUpdateTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        mesh = bpy.data.meshes.new('faces')
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0), (2, 0, 0)], [],
                         [(0, 1, 2), (1, 3, 2), (1, 4, 3)])
        self.obj = bpy.data.objects.new('faces', mesh)
        bpy.context.scene.collection.objects.link(self.obj)
        bpy.context.view_layer.objects.active = self.obj
        self.obj.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        self.bm = bmesh.from_edit_mesh(mesh)
        self.bm.faces.ensure_lookup_table()
        bmMeshInit3doLayers(self.bm)
        self.bm.faces.active = self.bm.faces[0]
        for face in self.bm.faces:
            face.select_set(face.index < 2)

    def set_flags(self, values):
        for face, value in zip(self.bm.faces, values):
            bmFaceSetType(face, self.bm, FaceType(value))
        # Match the panel's synchronization pass without applying changes to the
        # other faces. The next assignment exercises the actual update callback.
        flags = bmFaceGetType(self.bm.faces[0], self.bm).toSet()
        layer = bpy.context.window_manager.sith_mesh3do_face_layer
        app._face_sync_in_progress = True
        try:
            layer.type, layer.prev_type_flags = flags, ','.join(sorted(flags))
        finally:
            app._face_sync_in_progress = False
        return layer

    def flags(self):
        return [int(bmFaceGetType(face, self.bm)) for face in self.bm.faces]

    def test_disabling_known_flag_preserves_unknown_bits(self):
        layer = self.set_flags((0x10001, 0x20001, 0x40001))
        layer.type = set()
        self.assertEqual(self.flags(), [0x10000, 0x20000, 0x40001])

    def test_each_known_flag_can_be_cleared_without_losing_high_or_gap_bits(self):
        unknown = 0x80000080
        for flag in FaceType:
            if not flag:
                continue
            layer = self.set_flags((unknown | int(flag), unknown | int(flag), unknown))
            layer.type = set()
            with self.subTest(flag=flag.name):
                self.assertEqual(self.flags(), [unknown, unknown, unknown])

    def test_removing_one_flag_keeps_each_faces_other_flags(self):
        layer = self.set_flags((0x10001 | int(FaceType.IjimFogEnabled),
                                0x20001 | int(FaceType.Translucent), 0x40001))
        layer.type = {'IjimFogEnabled'}
        self.assertEqual(self.flags(), [0x10100, 0x20002, 0x40001])

    def test_adding_known_flag_keeps_unknown_and_unselected_values(self):
        layer = self.set_flags((0x10000, 0x20001, 0x40000))
        layer.type = {'Translucent'}
        self.assertEqual(self.flags(), [0x10002, 0x20003, 0x40000])

    def test_flags_survive_export_after_ui_edit(self):
        layer = self.set_flags((0x10001, 0x20001, 0x40001))
        layer.type = set()
        bpy.ops.object.mode_set(mode='OBJECT')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'flags.3do'
            export3do(self.obj, str(path), Model3doFileVersion.Version2_3, False, False, True)
            model, _ = load3do(path)
        self.assertEqual([int(face.type) for face in model.geosets[0].meshes[0].faces],
                         [0x10000, 0x20000, 0x40001])
