"""3DO text storage must not erase small, finite engine data."""
import math
from pathlib import Path
import struct
import tempfile
import unittest

from fixtures import TV
from sith.model.model3doLoader import load3do, Model3doFileVersion
from sith.model.model3doWriter import save3do
from sith.types import Vector2f, Vector3f, Vector4f
from sith.types.vector import kFloat32Max


class ModelPrecisionTests(unittest.TestCase):
    def test_small_stored_values_survive_all_output_versions(self):
        for version in Model3doFileVersion:
            model, _ = load3do(TV / 'model/triangle.3do')
            model.radius, model.insertOffset = 4e-8, Vector3f(2e-8, -3e-8, 1e-7)
            node = model.meshHierarchy[1]
            node.position, node.rotation, node.pivot = [Vector3f(1e-8, -2e-8, 3e-8)] * 3
            mesh = model.geosets[0].meshes[0]
            mesh.radius = 4e-8
            mesh.vertices[1] = Vector3f(1e-8, 2e-8, 3e-8)
            mesh.normals[1] = Vector3f(1e-8, -2e-8, 1)
            mesh.uvs[1] = Vector2f(1e-8, -2e-8)
            mesh.vertexColors[1] = Vector4f(3e-8, 3e-8, 3e-8, 0.5)
            mesh.faces[0].normal = Vector3f(1e-8, -2e-8, 1)
            mesh.faces[0].color = Vector4f(3e-8, 3e-8, 3e-8, 0.5)
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'tiny.3do'
                save3do(model, path, version, '')
                restored, actual = load3do(path)
                self.assertEqual(actual, version)
                self.assertEqual(restored.radius, model.radius)
                self.assertEqual(restored.insertOffset, model.insertOffset)
                other = restored.meshHierarchy[1]
                for field in ('position', 'rotation', 'pivot'):
                    self.assertEqual(getattr(other, field), getattr(node, field))
                other = restored.geosets[0].meshes[0]
                self.assertEqual(other.radius, mesh.radius)
                for field in ('vertices', 'normals', 'uvs'):
                    self.assertEqual(getattr(other, field), getattr(mesh, field))
                self.assertEqual(other.faces[0].normal, mesh.faces[0].normal)
                self.assertAlmostEqual(other.vertexColors[1].x, 3e-8, delta=1e-22)
                self.assertAlmostEqual(other.faces[0].color.x, 3e-8, delta=1e-22)

    def test_float32_extremes_and_signed_zero_retain_storage(self):
        values = (-0.0, struct.unpack('<f', struct.pack('<I', 1))[0], kFloat32Max)
        for value in values:
            model, _ = load3do(TV / 'model/triangle.3do')
            model.insertOffset = Vector3f(value, value, value)
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'extreme.3do'
                save3do(model, path, Model3doFileVersion.Version2_3, '')
                restored, _ = load3do(path)
                self.assertEqual(restored.insertOffset, model.insertOffset)
                self.assertEqual(math.copysign(1, restored.insertOffset.x), math.copysign(1, value))

    def test_unrepresentable_numeric_fields_preserve_existing_output(self):
        for field in ('radius', 'insertOffset', 'vertex', 'uv', 'normal', 'color'):
            model, _ = load3do(TV / 'model/triangle.3do')
            mesh = model.geosets[0].meshes[0]
            value = kFloat32Max * 2
            if field == 'radius':
                model.radius = value
            elif field == 'insertOffset':
                model.insertOffset = Vector3f(value, 0, 0)
            elif field == 'vertex':
                mesh.vertices[0] = Vector3f(value, 0, 0)
            elif field == 'uv':
                mesh.uvs[0] = Vector2f(value, 0)
            elif field == 'normal':
                mesh.faces[0].normal = Vector3f(value, 0, 0)
            else:
                mesh.faces[0].color = Vector4f(value, 0, 0, 1)
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'keep.3do'
                path.write_bytes(b'existing export')
                with self.assertRaisesRegex(ValueError, 'float32'):
                    save3do(model, path, Model3doFileVersion.Version2_3, '')
                self.assertEqual(path.read_bytes(), b'existing export')
