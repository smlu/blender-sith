"""Import failure safety and paired 3DO/KEY numbering with each order option."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import bpy

from app.support import SceneTestCase
from batch.app import compare_keys
from fixtures import TV
from sith.key import Key, KeyNode, Keyframe, KeyMarker
from sith.key.keyExporter import _make_key_from_obj
from sith.key.keyImporter import importKey
from sith.key.keyLoader import loadKey
from sith.key.keyWriter import saveKey
from sith.model.model3do import Mesh3doNode
from sith.model.model3doExporter import makeModel3doFromObj
from sith.model.model3doImporter import import3do
from sith.model.model3doLoader import load3do, Model3doFileVersion
from sith.model.model3doWriter import save3do


def probe_key(model):
    """Give every joint distinct motion, including joints without meshes."""
    key = Key('probe.key')
    key.numFrames, key.numJoints, key.fps = 5, len(model.meshHierarchy), 30
    for joint in model.meshHierarchy:
        node = KeyNode()
        node.idx, node.meshName = joint.idx, joint.name
        entry = Keyframe()
        entry.position, entry.orientation = joint.position, joint.rotation
        entry.flags = 3
        entry.deltaPosition = (0.01 * (joint.idx + 1), -0.02, 0.03)
        entry.deltaRotation = (0.1, 0.2 * (joint.idx + 1), -0.3)
        node.keyframes = [entry]
        key.nodes.append(node)
    return key


class KeyImportFailureTests(SceneTestCase):
    def test_invalid_input_keeps_existing_actions_and_timeline(self):
        # Existing animation must survive errors discovered in a later track,
        # not merely syntax errors found while reading the file.
        wrapper = bpy.data.objects.new('wrapper', None)
        bpy.context.scene.collection.objects.link(wrapper)
        for index, name in enumerate(('root', 'child')):
            obj = bpy.data.objects.new(name, None)
            bpy.context.scene.collection.objects.link(obj)
            obj.parent = wrapper
            obj.sith_model3do_hnode_idx = index
            obj.sith_model3do_hnode_name = name
            obj.keyframe_insert(data_path='location', frame=25)
        bpy.context.view_layer.objects.active = wrapper
        scene = bpy.context.scene
        scene.frame_end = 40
        scene.timeline_markers.clear()
        scene.timeline_markers.new('existing', frame=20)
        original = [(obj, obj.animation_data.action) for obj in wrapper.children]

        valid = Key('invalid.key')
        valid.numFrames, valid.numJoints, valid.fps = 5, 2, 30
        for index, name in enumerate(('root', 'child')):
            node = KeyNode()
            node.idx, node.meshName = index, name
            node.keyframes = [Keyframe()]
            valid.nodes.append(node)

        cases = []
        for attribute, value in (('fps', 0), ('fps', float('nan')), ('numFrames', 0), ('numJoints', -1)):
            key = copy.deepcopy(valid)
            setattr(key, attribute, value)
            cases.append((attribute, key))
        for index in (-1, 0, 2):
            key = copy.deepcopy(valid)
            key.nodes[1].idx = index
            cases.append((f'node {index}', key))
        key = copy.deepcopy(valid)
        key.nodes[1].keyframes.append(Keyframe())
        cases.append(('later duplicate entry time', key))
        key = copy.deepcopy(valid)
        marker = KeyMarker()
        marker.frame = float('inf')
        key.markers.append(marker)
        cases.append(('marker', key))

        for label, key in cases:
            with self.subTest(case=label), mock.patch('sith.key.keyImporter.keyLoader.loadKey', return_value=key):
                with self.assertRaises(ValueError):
                    importKey('invalid.key', scene, True, True, False)
                self.assertEqual(scene.frame_end, 40)
                self.assertEqual([(m.name, m.frame) for m in scene.timeline_markers], [('existing', 20)])
                for obj, action in original:
                    self.assertIsNotNone(obj.animation_data)
                    self.assertEqual(obj.animation_data.action, action)


class KeyComparisonTests(unittest.TestCase):
    def test_comparator_rejects_missing_zero_motion_track_and_changed_name(self):
        source = Key('source.key')
        source.numFrames, source.numJoints, source.fps = 5, 1, 30
        node = KeyNode()
        node.idx, node.meshName = 0, 'joint'
        node.keyframes = [Keyframe()]
        source.nodes = [node]
        target = copy.deepcopy(source)
        self.assertFalse(compare_keys(source, target)['differences'])
        target.nodes.clear()
        self.assertTrue(compare_keys(source, target)['differences'])
        target = copy.deepcopy(source)
        target.nodes[0].meshName = 'wrong_joint'
        self.assertTrue(compare_keys(source, target)['differences'])
        target = copy.deepcopy(source)
        target.nodes.append(copy.deepcopy(target.nodes[0]))
        self.assertTrue(compare_keys(source, target)['differences'])


class ImportOrderMatrixTests(SceneTestCase):
    def test_all_import_order_and_export_sync_combinations_keep_joint_motion(self):
        # Deliberately oppose mesh names and node order, with an empty joint
        # between mesh joints. This distinguishes traversal order from node IDs.
        source, _ = load3do(TV / 'model' / 'triangle.3do')
        template = source.geosets[0].meshes[0]
        source.geosets[0].meshes = [copy.deepcopy(template), copy.deepcopy(template)]
        for index, name in enumerate(('zebra', 'alpha')):
            source.geosets[0].meshes[index].idx = index
            source.geosets[0].meshes[index].name = name
        source.meshHierarchy = []
        for index, (name, parent, mesh) in enumerate((('root', -1, -1), ('zebra', 0, 0),
                                                     ('branch', 0, -1), ('alpha', 2, 1))):
            node = Mesh3doNode(name)
            node.idx, node.parentIdx, node.meshIdx = index, parent, mesh
            source.meshHierarchy.append(node)
        source.reorderNodes(requireRoot=True)
        expected = probe_key(source)
        layouts = {}

        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            model_path, key_path = directory / 'source.3do', directory / expected.name
            save3do(source, model_path, Model3doFileVersion.Version2_3, '')
            saveKey(expected, key_path, '')
            for preserve in (True, False):
                self.clear_data()
                root = import3do(model_path, clearScene=False, preserveOrder=preserve)
                bpy.context.view_layer.objects.active = root
                importKey(key_path, bpy.context.scene, True, True, False)
                for sync in (True, False):
                    with self.subTest(preserve=preserve, sync=sync):
                        model = makeModel3doFromObj('paired.3do', root, exportVertexColors=True, sync_mesh_list=sync)
                        key = _make_key_from_obj('paired.key', root, bpy.context.scene)
                        output = directory / 'paired.3do'
                        save3do(model, output, Model3doFileVersion.Version2_3, '')
                        model, _ = load3do(output)
                        saveKey(key, directory / 'paired.key', '')
                        key = loadKey(directory / 'paired.key')
                        self.assertFalse(compare_keys(expected, key)['differences'])
                        self.assertEqual([(node.idx, node.name, node.parentIdx) for node in model.meshHierarchy],
                                         [(node.idx, node.name, node.parentIdx) for node in source.meshHierarchy])
                        for node in model.meshHierarchy:
                            if node.meshIdx >= 0:
                                self.assertEqual(model.geosets[0].meshes[node.meshIdx].name, node.name)
                        layouts[preserve, sync] = [mesh.name for mesh in model.geosets[0].meshes]
        self.assertEqual(layouts[True, False], ['zebra', 'alpha'])
        self.assertEqual(layouts[False, False], ['alpha', 'zebra'])
        self.assertEqual(layouts[False, True], layouts[True, True])
