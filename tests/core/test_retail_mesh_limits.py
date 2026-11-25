"""Retail JK/MotS mesh limits apply to each serialized mesh independently."""
import copy
from pathlib import Path
import tempfile
import unittest

from sith.model.model3doLoader import load3do, Model3doFileFormat, Model3doFileVersion
from sith.model.model3doWriter import save3do


class RetailMeshLimitTests(unittest.TestCase):
    def setUp(self):
        fixture = Path(__file__).resolve().parents[1] / 'tv/model/triangle.3do'
        self.model, _ = load3do(fixture)
        self.mesh = self.model.geosets[0].meshes[0]
        for records, count in ((self.mesh.vertices, 512), (self.mesh.vertexColors, 512),
                               (self.mesh.normals, 512), (self.mesh.uvs, 768),
                               (self.mesh.faces, 512)):
            records.extend([records[-1]] * (count - len(records)))
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'test.3do'

    def save(self, version=Model3doFileVersion.Version2_1, **options):
        warnings = []
        save3do(self.model, self.path, version, '', warnings=warnings, **options)
        return warnings

    def test_limits_are_inclusive_and_apply_to_each_mesh(self):
        other = copy.deepcopy(self.mesh)
        other.idx, other.name = 1, 'other'
        self.model.geosets[0].meshes.append(other)
        self.assertEqual(self.save(checkRetailMeshLimits=True), [])
        other.faces.append(other.faces[-1])
        warnings = self.save(checkRetailMeshLimits=True)
        self.assertEqual(len(warnings), 1)
        self.assertIn("'other' (geoset 0, mesh 1) has 513 faces", warnings[0])

    def test_warnings_match_the_counts_written_and_preserve_the_export(self):
        for records in (self.mesh.vertices, self.mesh.vertexColors, self.mesh.normals,
                        self.mesh.uvs, self.mesh.faces):
            records.append(records[-1])
        self.assertEqual(self.save(), [])
        original = self.path.read_bytes()
        warnings = self.save(checkRetailMeshLimits=True)
        self.assertEqual(self.path.read_bytes(), original)
        restored = load3do(self.path)[0].geosets[0].meshes[0]
        self.assertEqual((len(restored.vertices), len(restored.uvs), len(restored.faces)),
                         (513, 769, 513))
        self.assertEqual(len(warnings), 3)
        for warning, counts in zip(warnings, ('513 vertices', '769 texture vertices', '513 faces')):
            self.assertIn("'triangle'", warning)
            self.assertIn(counts, warning)
            self.assertIn('768' if 'texture' in counts else '512', warning)

    def test_other_targets_ignore_the_option(self):
        self.mesh.faces.append(self.mesh.faces[-1])
        for target in (Model3doFileVersion.Version2_2, Model3doFileVersion.Version2_3,
                       Model3doFileFormat.GrimFandango):
            with self.subTest(target=target):
                self.assertEqual(self.save(target, checkRetailMeshLimits=True), [])
                self.assertEqual(len(load3do(self.path)[0].geosets[0].meshes[0].faces), 513)
