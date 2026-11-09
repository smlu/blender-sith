"""Zero-area legacy faces are data to preserve, not broken-file syntax."""
import hashlib
from pathlib import Path
import tempfile
import unittest

from fixtures import TV
from vector_expectations import (DEGENERATE_VERTICES, DEGENERATE_COLORS,
                                 DEGENERATE_CORNERS, DEGENERATE_FACE_UVS)
from sith.model.model3doLoader import load3do, Model3doFileVersion
from sith.model.model3doWriter import save3do


class DegenerateFaceCodecTests(unittest.TestCase):
    def test_normal_load_keeps_original_indices_colors_and_zero_normals(self):
        path = TV / 'model/degenerate_faces.3do'
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        warnings = []
        model, _ = load3do(path, warnings=warnings)
        mesh = model.geosets[0].meshes[0]
        self.assertEqual(warnings, [])
        self.assertEqual(mesh.vertices, list(DEGENERATE_VERTICES))
        self.assertEqual(mesh.vertexColors, list(DEGENERATE_COLORS))
        self.assertEqual([tuple(face.vertexIdxs) for face in mesh.faces], list(DEGENERATE_CORNERS))
        self.assertEqual([tuple(face.uvIdxs) for face in mesh.faces], list(DEGENERATE_FACE_UVS))
        self.assertEqual([tuple(mesh.faces[i].normal) for i in (1, 2, 3, 5, 6, 7)], [(0, 0, 0)] * 6)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_all_versions_round_trip_repeated_and_collinear_corners(self):
        model, _ = load3do(TV / 'model/degenerate_faces.3do')
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'roundtrip.3do'
            for version in Model3doFileVersion:
                with self.subTest(version=version):
                    save3do(model, output, version, '')
                    restored, actualVersion = load3do(output)
                    mesh = restored.geosets[0].meshes[0]
                    self.assertEqual(actualVersion, version)
                    self.assertEqual(mesh.vertices, list(DEGENERATE_VERTICES))
                    self.assertEqual([tuple(face.vertexIdxs) for face in mesh.faces], list(DEGENERATE_CORNERS))
                    self.assertEqual([tuple(face.uvIdxs) for face in mesh.faces], list(DEGENERATE_FACE_UVS))

    def test_recovery_preserves_safe_degenerate_records_without_warnings(self):
        # Merely enabling recovery must not discard otherwise accepted records.
        warnings = []
        model, _ = load3do(TV / 'model/degenerate_faces.3do', allowErrors=True, warnings=warnings)
        mesh = model.geosets[0].meshes[0]
        self.assertEqual([tuple(face.vertexIdxs) for face in mesh.faces], list(DEGENERATE_CORNERS))
        self.assertEqual([tuple(face.uvIdxs) for face in mesh.faces], list(DEGENERATE_FACE_UVS))
        self.assertEqual(warnings, [])
