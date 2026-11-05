"""Real text exporters must write the extension manifest's release version."""
from pathlib import Path
import tempfile
import tomllib

import bpy

from app.support import SceneTestCase
from sith.material.mat import kMatCelImagePrefix


ROOT = Path(__file__).resolve().parents[2]


class ExportHeaderTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        with (ROOT / 'sith/blender_manifest.toml').open('rb') as stream:
            self.manifest = tomllib.load(stream)
        bpy.ops.mesh.primitive_cube_add()
        self.obj = bpy.context.object
        self.obj.name = 'cube'
        self.obj.sith_model3do_hnode_idx = 0
        self.obj.sith_model3do_hnode_name = 'cube'

    def assert_header(self, path, prefix):
        first = path.read_text(encoding='utf-8').splitlines()[0]
        self.assertEqual(first, f"# {prefix} created with Blender Sith addon v{self.manifest['version']} "
                               f"by {self.manifest['maintainer']}")

    def test_all_text_model_versions_and_texture_bundle_use_manifest_version(self):
        material = bpy.data.materials.new('checker.mat')
        material[kMatCelImagePrefix + '0'] = bpy.data.images.new('checker', 2, 2)
        self.obj.data.materials.append(material)
        cases = [('Version2_1', False), ('Version2_2', False),
                 ('Version2_3', False), ('Version2_3', True)]
        for version, bundle in cases:
            with self.subTest(version=version, textures=bundle):
                path = self.folder / f'{version}-{bundle}.3do'
                self.assertEqual(bpy.ops.export_scene.sith_3do(
                    filepath=str(path), version=version, export_textures=bundle,
                    texture_encoding='RGBA32'), {'FINISHED'})
                self.assert_header(path, f"3DO model '{path.name}'")

    def test_all_text_animation_targets_use_manifest_version(self):
        scene = bpy.context.scene
        scene.frame_start, scene.frame_end = 0, 1
        scene.render.fps, scene.render.fps_base = 30, 1
        for frame, position in ((0, 0), (1, 1)):
            self.obj.location.x = position
            self.obj.keyframe_insert(data_path='location', index=0, frame=frame)
        for target in ('IJIM', 'JKDF2', 'MOTS', 'CUSTOM'):
            with self.subTest(target=target):
                path = self.folder / f'{target}.key'
                self.assertEqual(bpy.ops.export_anim.sith_key(filepath=str(path), target=target), {'FINISHED'})
                self.assert_header(path, f"Keyframe '{path.name}'")
