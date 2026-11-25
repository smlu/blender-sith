"""The export dialog checks split 3DO vertices, including on staged exports."""
from contextlib import redirect_stdout
from io import StringIO
from math import cos, sin, tau
from pathlib import Path
import tempfile

import bpy

from app.support import SceneTestCase
from sith.model.model3doLoader import load3do


class RetailMeshExportTests(SceneTestCase):
    def test_sharp_corners_exceed_vertex_limit_only_after_export(self):
        vertices = [(0, 0, 0)]
        faces = []
        # All faces share the origin, but each has a different corner normal.
        for index in range(171):
            angle = index * tau / 171
            x, y = cos(angle), sin(angle)
            faces.append((0, len(vertices), len(vertices) + 1))
            vertices.extend(((x, y, 0), (x, y, 1)))
        mesh = bpy.data.meshes.new('fan')
        mesh.from_pydata(vertices, [], faces)
        for edge in mesh.edges:
            edge.use_edge_sharp = True
        obj = bpy.data.objects.new('joint', mesh)
        bpy.context.scene.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        self.assertEqual(len(mesh.vertices), 343)

        export = bpy.ops.export_scene.sith_3do
        self.assertFalse(export.get_rna_type().properties['check_retail_mesh_limits'].default)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fan.3do'
            for options, expect_warning in (({}, False), ({'check_retail_mesh_limits': True}, True),
                                            ({'check_retail_mesh_limits': True, 'export_textures': True}, True)):
                with self.subTest(options=options), redirect_stdout(StringIO()) as output:
                    self.assertEqual(export(filepath=str(path), version='Version2_1', **options), {'FINISHED'})
                    written = load3do(path)[0].geosets[0].meshes[0]
                    self.assertEqual(len(written.vertices), 513)
                    self.assertEqual("513 vertices" in output.getvalue(), expect_warning)
