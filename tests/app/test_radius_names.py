"""Radius-helper identifiers must not consume ordinary model or KEY joints."""
from pathlib import Path
import tempfile

import bpy

from app.support import SceneTestCase
from app.test_key import sample_key
from fixtures import TV
from sith.key import Key, KeyNode, Keyframe, KeyframeFlag
from sith.key.keyExporter import exportKey
from sith.key.keyImporter import importKey
from sith.key.keyLoader import loadKey
from sith.key.keyUtils import setSceneKeyFlags
from sith.key.keyWriter import saveKey
from sith.model.model3doExporter import export3do
from sith.model.model3doImporter import import3do
from sith.model.model3doLoader import load3do, Model3doFileVersion
from sith.model.model3doWriter import save3do
from sith.model.utils import (getMeshRadiusObj, getModelRadiusObj, isRadiusObj,
                              kImEulerOrder, kMeshRadius, kModelRadius, kModel3doRadiusKind)
from sith.types import Vector3f


class RadiusHelperNameTests(SceneTestCase):
    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.counter = 0
        self.scene = bpy.context.scene
        self.scene.frame_start, self.scene.frame_end = 0, 4
        self.scene.render.fps, self.scene.render.fps_base = 30, 1
        self.scene.timeline_markers.clear()
        setSceneKeyFlags(self.scene, 0)
        self.scene.sith_key_types = 'FFFF'

    def path(self, suffix):
        self.counter += 1
        return self.folder / f'{self.counter:03d}-resource.{suffix}'

    def object(self, name, parent=None, data=None):
        obj = bpy.data.objects.new(name, data)
        self.scene.collection.objects.link(obj)
        obj.parent = parent
        obj.rotation_mode = kImEulerOrder
        return obj

    def find_helper(self, owner, kind):
        return getModelRadiusObj(owner) if kind == kModelRadius else getMeshRadiusObj(None, owner)

    def test_embedded_name_fragments_do_not_mark_helpers(self):
        for name in ('ordinary', 'detail_MESH_RADIUS_joint', 'detail_MODEL_RADIUS_joint',
                     'no03_detail_MESH_RADIUS_joint', 'mesh_MODEL_RADIUS_'):
            with self.subTest(name=name):
                self.assertFalse(isRadiusObj(self.object(name)))

    def test_unmarked_legacy_prefixes_match_helper_ownership(self):
        owner = self.object('owner')
        for kind in (kMeshRadius, kModelRadius):
            with self.subTest(kind=kind):
                helper = self.object(kind + 'owner', owner)
                self.assertTrue(isRadiusObj(helper))
                self.assertEqual(self.find_helper(owner, kind), helper)

    def test_explicit_helper_markers_survive_renaming(self):
        owner = self.object('owner')
        for index, kind in enumerate((kMeshRadius, kModelRadius)):
            with self.subTest(kind=kind):
                helper = self.object(f'renamed_bound_{index}', owner)
                helper[kModel3doRadiusKind] = kind
                self.assertTrue(isRadiusObj(helper))
                self.assertEqual(self.find_helper(owner, kind), helper)

    def test_explicit_kind_takes_priority_over_a_legacy_name(self):
        owner = self.object('owner')
        helper = self.object(kMeshRadius + 'owner', owner)
        helper[kModel3doRadiusKind] = kModelRadius
        self.assertTrue(isRadiusObj(helper))
        self.assertEqual(getModelRadiusObj(owner), helper)
        self.assertIsNone(getMeshRadiusObj(None, owner))

    def test_unknown_kind_does_not_fall_back_to_the_name(self):
        owner = self.object('owner')
        for kind in (kMeshRadius, kModelRadius):
            with self.subTest(kind=kind):
                obj = self.object(kind + 'ordinary', owner)
                obj[kModel3doRadiusKind] = 'ordinary_joint'
                self.assertFalse(isRadiusObj(obj))
                self.assertIsNone(self.find_helper(owner, kind))

    def test_mesh_roots_with_embedded_fragments_remain_exportable(self):
        for name in ('detail_MESH_RADIUS_joint', 'detail_MODEL_RADIUS_joint'):
            with self.subTest(name=name):
                self.clear_data()
                mesh = bpy.data.meshes.new(name)
                mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
                obj = self.object(name, data=mesh)
                obj.keyframe_insert(data_path='location', index=0, frame=0)

                model_path, key_path = self.path('3do'), self.path('key')
                export3do(obj, str(model_path), Model3doFileVersion.Version2_3, False, False, True)
                model, _ = load3do(model_path)
                self.assertEqual([node.name for node in model.meshHierarchy], [name])
                self.assertEqual(len(model.geosets[0].meshes), 1)

                exportKey(obj, self.scene, str(key_path))
                key = loadKey(key_path)
                self.assertEqual(key.numJoints, 1)
                self.assertEqual([node.meshName for node in key.nodes], [name])

    def test_named_joints_and_real_helpers_survive_all_roundtrip_modes(self):
        names = ['detail_MODEL_RADIUS_root', 'detail_MESH_RADIUS_arm']
        for version in Model3doFileVersion:
            for preserve in (False, True):
                for sync in (False, True):
                    with self.subTest(version=version, preserve=preserve, sync=sync):
                        self.clear_data()

                        # 1. Use a real two-joint model, with helper-like words in
                        # both an Empty joint and a mesh, plus actual bounds helpers.
                        model, _ = load3do(TV / 'model' / 'triangle.3do')
                        for node, name in zip(model.meshHierarchy, names):
                            node.name = name
                        model.geosets[0].meshes[0].name = names[1]
                        source = self.path('3do')
                        save3do(model, source, version, '')
                        root = import3do(source, uvAbsolute_2_1=False, importRadiusObj=True,
                                         preserveOrder=preserve, clearScene=False)
                        helpers = [obj for obj in root.children_recursive if kModel3doRadiusKind in obj]
                        joints = [obj for obj in root.children_recursive if kModel3doRadiusKind not in obj]
                        self.assertEqual(len(helpers), 2)
                        self.assertEqual(len(joints), 2)
                        self.assertTrue(all(isRadiusObj(obj) for obj in helpers))
                        self.assertTrue(all(not isRadiusObj(obj) for obj in joints))

                        # 2. Verify serialized geometry and parent links, not only
                        # the classifier. Real helpers must never become joints.
                        output = self.path('3do')
                        export3do(root, str(output), version, False, True, sync)
                        restored, _ = load3do(output)
                        self.assertEqual([node.name for node in restored.meshHierarchy], names)
                        self.assertEqual([node.parentIdx for node in restored.meshHierarchy], [-1, 0])
                        self.assertEqual(len(restored.geosets[0].meshes), 1)
                        self.assertEqual(restored.geosets[0].meshes[0].name, names[1])

                        # 3. Animate the same imported hierarchy and compare KEY
                        # poses after a complete import/export/reparse cycle.
                        key = Key('source.key')
                        key.numFrames, key.numJoints, key.fps = 5, 2, 30
                        for index, name in enumerate(names):
                            node, entry = KeyNode(), Keyframe()
                            node.idx, node.meshName, node.keyframes = index, name, [entry]
                            entry.flags = KeyframeFlag.PositionChange
                            entry.position = Vector3f(index, 0, 0)
                            entry.deltaPosition = Vector3f(0, 0.25 * (index + 1), 0)
                            key.nodes.append(node)
                        source_key, output_key = self.path('key'), self.path('key')
                        saveKey(key, source_key, '')
                        bpy.context.view_layer.objects.active = root
                        importKey(source_key, self.scene, True, True, False)
                        exportKey(root, self.scene, str(output_key))
                        restored_key = loadKey(output_key)
                        self.assertEqual(restored_key.numJoints, 2)
                        self.assertEqual([node.meshName for node in restored_key.nodes], names)
                        for expected, actual in zip(key.nodes, restored_key.nodes):
                            for frame in (0, 2, 4.875):
                                self.assert_vector(sample_key(actual, frame)[0], sample_key(expected, frame)[0])
