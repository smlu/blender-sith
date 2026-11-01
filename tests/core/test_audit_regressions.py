"""Malformed inputs must fail before changing a scene or a previous export."""
import copy
import io
import math
from pathlib import Path
import tempfile
import unittest

from fixtures import TV, INDEX8, mat_bytes
from sith.material import mat
from sith.model.model3doLoader import load3do
from sith.model.model3doWriter import save3do


class ResourceSafetyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'model.3do'
        self.source = (TV / 'model/triangle.3do').read_text()

    def test_missing_header_is_fatal_in_strict_and_recovery_modes(self):
        # A body must not silently select the default 2.1 schema.
        bodies = ('', 'SECTION: UNKNOWN\n',
                  self.source.replace('SECTION: HEADER\n3DO 2.3\n', ''))
        for body in bodies:
            self.path.write_text(body)
            for recover in (False, True):
                with self.subTest(body=body[:40], recover=recover):
                    with self.assertRaisesRegex(OSError, 'Missing 3DO HEADER'):
                        load3do(self.path, allowErrors=recover)

    def test_strict_mode_rejects_incomplete_polygons(self):
        for corners in ('0', '1 0,0', '2 0,0 1,1'):
            self.path.write_text(self.source.replace('3 0,0 1,1 2,2', corners))
            with self.subTest(corners=corners):
                with self.assertRaisesRegex(ValueError, 'fewer than three corners'):
                    load3do(self.path)
                warnings = []
                model, _ = load3do(self.path, allowErrors=True, warnings=warnings)
                self.assertEqual(model.geosets[0].meshes[0].faces, [])
                self.assertTrue(any('face omitted' in warning for warning in warnings))

    def test_recovery_sanitizes_referenced_and_unused_nonfinite_uvs(self):
        for referenced in (False, True):
            text = self.source.replace('TEXTURE VERTICES 3', 'TEXTURE VERTICES 4')
            text = text.replace('VERTEX NORMALS', '3: 1e999 -1e999\nVERTEX NORMALS')
            if referenced:
                text = text.replace('3 0,0 1,1 2,2', '3 0,3 1,1 2,2')
            self.path.write_text(text)
            with self.subTest(referenced=referenced):
                warnings = []
                model, version = load3do(self.path, allowErrors=True, warnings=warnings)
                mesh = model.geosets[0].meshes[0]
                self.assertEqual(mesh.uvs[:3], [(0, 0), (1, 0), (0, 1)])
                self.assertEqual(mesh.uvs[3], (0, 0))
                self.assertEqual(mesh.faces[0].uvIdxs, [4 if referenced else 0, 1, 2])
                self.assertTrue(all(math.isfinite(value) for uv in mesh.uvs for value in uv))
                self.assertTrue(any('nonfinite texture vertex 3' in warning for warning in warnings))
                # The recovered resource must remain readable after writing it.
                save3do(model, self.path, version, '')
                load3do(self.path)

    def test_writer_rejects_all_nonfinite_fields_before_opening_output(self):
        model, version = load3do(TV / 'model/triangle.3do')
        fields = ('model radius', 'insert offset', 'position', 'rotation', 'pivot',
                  'mesh radius', 'vertices', 'colors', 'normals', 'UVs', 'face normal', 'face color')
        for label in fields:
            for value in (math.nan, math.inf, -math.inf):
                candidate = copy.deepcopy(model)
                mesh = candidate.geosets[0].meshes[0]
                if label == 'model radius':
                    candidate.radius = value
                elif label == 'insert offset':
                    candidate.insertOffset = (value, 0, 0)
                elif label in ('position', 'rotation', 'pivot'):
                    setattr(candidate.meshHierarchy[0], label, (value, 0, 0))
                elif label == 'mesh radius':
                    mesh.radius = value
                elif label in ('vertices', 'normals'):
                    getattr(mesh, label)[0] = (value, 0, 0)
                elif label == 'colors':
                    mesh.vertexColors[0] = (value, 0, 0, 1)
                elif label == 'UVs':
                    mesh.uvs[0] = (value, 0)
                elif label == 'face normal':
                    mesh.faces[0].normal = (value, 0, 0)
                else:
                    mesh.faces[0].color = (value, 0, 0, 1)
                self.path.write_bytes(b'previous export')
                with self.subTest(field=label, value=value):
                    with self.assertRaisesRegex(ValueError, 'finite'):
                        save3do(candidate, self.path, version, '')
                    self.assertEqual(self.path.read_bytes(), b'previous export')

    def test_color_records_validate_every_palette_index_without_a_palette(self):
        # Check later records too, even when no CMP was supplied for preview.
        for index in (-1, 256, 0x7fffffff):
            with self.subTest(index=index):
                data = io.BytesIO(mat_bytes(INDEX8, color_indices=[0, 255, index]))
                header = mat._read_header(data)
                with self.assertRaisesRegex(ImportError, 'palette index'):
                    mat._read_records(data, header)
