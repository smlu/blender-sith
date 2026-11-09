"""3DO legacy name limits are advisory; grammar validation remains strict."""
from pathlib import Path
import tempfile
import unittest

from sith.model.model3doLoader import load3do, Model3doFileVersion
from sith.model.model3doWriter import save3do

TV = Path(__file__).resolve().parents[1] / 'tv/model/triangle.3do'


class ModelNameWarningTests(unittest.TestCase):
    def test_mesh_name_boundaries_for_all_text_versions(self):
        for version in Model3doFileVersion:
            limit = 31 if version == Model3doFileVersion.Version2_1 else 63
            for length in (limit, limit + 1, 100):
                with self.subTest(version=version, length=length), tempfile.TemporaryDirectory() as directory:
                    model, _ = load3do(TV)
                    model.geosets[0].meshes[0].name = 'm' * length
                    path = Path(directory) / 'names.3do'
                    warnings = []
                    save3do(model, path, version, '', warnings=warnings)
                    restored, _ = load3do(path)
                    self.assertEqual(restored.geosets[0].meshes[0].name, 'm' * length)
                    self.assertEqual(len(warnings), int(length > limit))

    def test_joint_name_limits_use_the_actual_engine_field_size(self):
        for version, limit in ((Model3doFileVersion.Version2_1, 31),
                               (Model3doFileVersion.Version2_2, 127),
                               (Model3doFileVersion.Version2_3, 127)):
            for length in (limit, limit + 1):
                with self.subTest(version=version, length=length), tempfile.TemporaryDirectory() as directory:
                    model, _ = load3do(TV)
                    model.meshHierarchy[0].name = 'j' * length
                    warnings = []
                    path = Path(directory) / 'names.3do'
                    save3do(model, path, version, '', warnings=warnings)
                    restored, _ = load3do(path)
                    self.assertEqual(restored.meshHierarchy[0].name, 'j' * length)
                    self.assertEqual(len(warnings), int(length > limit))

    def test_long_material_names_are_preserved_including_their_extension(self):
        model, _ = load3do(TV)
        model.materials[0] = 'material_' + 'a' * 75 + '.mat'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'names.3do'
            warnings = []
            save3do(model, path, Model3doFileVersion.Version2_3, '', warnings=warnings)
            restored, _ = load3do(path)
            self.assertEqual(restored.materials[0], model.materials[0])
            self.assertEqual(len(warnings), 1)
            self.assertIn('material name', warnings[0])
