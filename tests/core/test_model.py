import contextlib
import copy
import io
from pathlib import Path
import tempfile
import unittest

from fixtures import TV
from sith.model.model3do import Model3do, Model3doGeoSet, Mesh3doNode
from sith.model.model3doLoader import load3do, Model3doFileVersion
from sith.model.model3doWriter import save3do


class ModelCodecTests(unittest.TestCase):
    def test_reorder_remaps_parents_before_assigning_new_indices(self):
        model = Model3do('hierarchy')
        for name, sequence, parent in (('root', 0, -1), ('child', 2, 0),
                                       ('grandchild', 1, 1), ('automatic', -1, 0)):
            node = Mesh3doNode(name)
            node.idx, node.parentIdx = sequence, parent
            node.numChildren = 99
            model.meshHierarchy.append(node)
        model.reorderNodes()
        self.assertEqual([node.name for node in model.meshHierarchy], ['root', 'grandchild', 'child', 'automatic'])
        self.assertEqual([node.parentIdx for node in model.meshHierarchy], [-1, 2, 0, 0])
        self.assertEqual([node.numChildren for node in model.meshHierarchy], [2, 0, 1, 0])
        self.assertEqual(model.meshHierarchy[0].firstChildIdx, 2)
        self.assertEqual(model.meshHierarchy[2].siblingIdx, 3)
        self.assertEqual(model.meshHierarchy[2].firstChildIdx, 1)

    def test_reorder_rejects_invalid_parent_and_cycles(self):
        for parents in ((1, 0), (0,), (2,), (-2,)):
            model = Model3do('invalid')
            for index, parent in enumerate(parents):
                node = Mesh3doNode(str(index))
                node.idx, node.parentIdx = index, parent
                model.meshHierarchy.append(node)
            with self.subTest(parents=parents), self.assertRaisesRegex(ValueError, 'parent'):
                model.reorderNodes()

    def test_reorder_empty_hierarchy(self):
        model = Model3do('empty')
        model.reorderNodes()
        self.assertEqual(model.meshHierarchy, [])

    def test_reorder_keeps_automatic_root_first(self):
        model = Model3do('automatic_root')
        for name, sequence, parent in (('root', -1, -1), ('left', 0, 0), ('right', 1, 0)):
            node = Mesh3doNode(name)
            node.idx, node.parentIdx, node.meshIdx = sequence, parent, len(model.meshHierarchy)
            model.meshHierarchy.append(node)
        model.reorderNodes()
        self.assertEqual([node.name for node in model.meshHierarchy], ['root', 'left', 'right'])
        self.assertEqual([node.idx for node in model.meshHierarchy], [0, 1, 2])
        self.assertEqual([node.meshIdx for node in model.meshHierarchy], [0, 1, 2])
        self.assertEqual([node.parentIdx for node in model.meshHierarchy], [-1, 0, 0])
        self.assertEqual(model.meshHierarchy[0].firstChildIdx, 1)
        self.assertEqual(model.meshHierarchy[0].numChildren, 2)
        self.assertEqual(model.meshHierarchy[1].siblingIdx, 2)

    def test_reorder_preserves_legacy_automatic_sibling_order(self):
        model = Model3do('automatic_siblings')
        for name, sequence, parent in (('root', -1, -1), ('automatic', -1, 0), ('numbered', 0, 0)):
            node = Mesh3doNode(name)
            node.idx, node.parentIdx = sequence, parent
            model.meshHierarchy.append(node)
        model.reorderNodes()
        self.assertEqual([node.name for node in model.meshHierarchy], ['root', 'automatic', 'numbered'])
        self.assertEqual([node.parentIdx for node in model.meshHierarchy], [-1, 0, 0])

    def test_reorder_rejects_nonroot_entry_without_mutation(self):
        model = Model3do('bad_sequence')
        for name, sequence, parent in (('root', 2, -1), ('child', 0, 0)):
            node = Mesh3doNode(name)
            node.idx, node.parentIdx = sequence, parent
            model.meshHierarchy.append(node)
        before = [(node.name, node.idx, node.parentIdx) for node in model.meshHierarchy]
        with self.assertRaisesRegex(ValueError, 'root.*node 0'):
            model.reorderNodes(requireRoot=True)
        self.assertEqual(before, [(node.name, node.idx, node.parentIdx) for node in model.meshHierarchy])

    def test_reorder_rejects_multiple_roots(self):
        model = Model3do('multiple_roots')
        model.meshHierarchy = [Mesh3doNode('first'), Mesh3doNode('second')]
        with self.assertRaisesRegex(ValueError, 'exactly one root'):
            model.reorderNodes(requireRoot=True)

    def test_reorder_allows_flat_animation_joint_lists(self):
        model = Model3do('joints')
        for name, sequence in (('second', 1), ('first', 0)):
            node = Mesh3doNode(name)
            node.idx = sequence
            model.meshHierarchy.append(node)
        model.reorderNodes()
        self.assertEqual([node.name for node in model.meshHierarchy], ['first', 'second'])
        self.assertEqual([node.parentIdx for node in model.meshHierarchy], [-1, -1])

    def load_text(self, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.3do'
            path.write_text(text, encoding='utf-8')
            return load3do(path)

    def test_hand_authored_geometry_and_hierarchy(self):
        """Check independent expected values before relying on a round trip."""
        model, version = load3do(TV / 'model' / 'triangle.3do')
        self.assertEqual(version, Model3doFileVersion.Version2_3)
        self.assertEqual(model.materials, ['checker.mat', 'unused.mat'])
        self.assertEqual(model.radius, 2)
        self.assertEqual(model.insertOffset, (0.5, -0.25, 1))
        mesh = model.geosets[0].meshes[0]
        self.assertEqual(mesh.vertices, [(0, 0, 0), (1, 0, 0), (0, 1, 0)])
        self.assertEqual(mesh.normals, [(0, 0, 1)] * 3)
        self.assertEqual(mesh.vertexColors[1], (0, 1, 0, 0.5))
        self.assertEqual(mesh.uvs, [(0, 0), (1, 0), (0, 1)])
        face = mesh.faces[0]
        self.assertEqual((face.materialIdx, int(face.type)), (0, 0x103))
        self.assertEqual((face.geometryMode, face.lightMode, face.textureMode), (4, 3, 3))
        self.assertEqual(face.color, (0.125, 0.25, 0.5, 0.75))
        self.assertEqual(face.vertexIdxs, [0, 1, 2])
        self.assertEqual(face.uvIdxs, [0, 1, 2])
        root, head = model.meshHierarchy
        self.assertEqual((root.parentIdx, root.firstChildIdx, root.numChildren), (-1, 1, 1))
        self.assertEqual((head.parentIdx, head.meshIdx, head.siblingIdx), (0, 0, -1))
        self.assertEqual((int(head.flags), int(head.type)), (0x2000, 0x8008))
        self.assertEqual(head.pivot, (0.125, 0, 0))

    def test_all_versions_round_trip(self):
        model, _ = load3do(TV / 'model' / 'triangle.3do')
        for version in Model3doFileVersion:
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'roundtrip.3do'
                save3do(model, path, version, 'Synthetic model')
                restored, actual_version = load3do(path)
                self.assertEqual(actual_version, version)
                self.assertEqual(restored.materials, model.materials)
                self.assertEqual(restored.insertOffset, model.insertOffset)
                original_mesh = model.geosets[0].meshes[0]
                mesh = restored.geosets[0].meshes[0]
                self.assertEqual(mesh.vertices, original_mesh.vertices)
                self.assertEqual(mesh.normals, original_mesh.normals)
                self.assertEqual(mesh.uvs, original_mesh.uvs)
                for original, color in zip(original_mesh.vertexColors, mesh.vertexColors):
                    if version.value == 2.1:
                        expected = (sum(original[:3]) / 3,) * 3 + (1,)
                    elif version.value == 2.2:
                        expected = tuple(original[:3]) + (1,)
                    else:
                        expected = original
                    for a, b in zip(color, expected):
                        self.assertAlmostEqual(a, b, delta=1e-6)
                for a, b in zip(restored.meshHierarchy, model.meshHierarchy):
                    for name in ('idx', 'flags', 'type', 'meshIdx', 'parentIdx',
                                 'firstChildIdx', 'siblingIdx', 'numChildren',
                                 'position', 'rotation', 'pivot', 'name'):
                        self.assertEqual(getattr(a, name), getattr(b, name), name)

    def test_legacy_color_syntax_is_independent_of_writer(self):
        original = (TV / 'model' / 'triangle.3do').read_text()
        for version, colors, face in (
                ('2.1', ('0.2', '0.4', '0.6'), '0.75'),
                ('2.2', ('0.1 0.2 0.3', '0.4 0.5 0.6', '0.7 0.8 0.9'), '0.2 0.4 0.6')):
            text = original.replace('3DO 2.3', '3DO ' + version)
            for old, new in zip(('1.0 0.0 0.0 1.0', '0.0 1.0 0.0 0.5', '0.0 0.0 1.0 0.25'), colors):
                text = text.replace(old, new)
            text = text.replace('(0.125/0.25/0.5/0.75)', face)
            with self.subTest(version=version):
                model, _ = self.load_text(text)
                mesh = model.geosets[0].meshes[0]
                self.assertEqual(mesh.vertexColors[0], (0.2, 0.2, 0.2, 1) if version == '2.1'
                                 else (0.1, 0.2, 0.3, 1))
                self.assertEqual(mesh.faces[0].color, (0.75, 0.75, 0.75, 1) if version == '2.1'
                                 else (0.2, 0.4, 0.6, 1))

    def test_multiple_geosets_and_untextured_faces(self):
        model, _ = load3do(TV / 'model' / 'triangle.3do')
        model.geosets.append(copy.deepcopy(model.geosets[0]))
        model.geosets[1].meshes[0].faces[0].materialIdx = -1
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'lod.3do'
            save3do(model, path, Model3doFileVersion.Version2_3, '')
            restored, _ = load3do(path)
        self.assertEqual(len(restored.geosets), 2)
        self.assertEqual(restored.geosets[1].meshes[0].faces[0].materialIdx, -1)

    def test_empty_model_round_trip(self):
        for geosets in ([], [Model3doGeoSet()]):
            model = Model3do('empty')
            model.geosets = geosets
            with self.subTest(geosets=len(geosets)), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'empty.3do'
                save3do(model, path, Model3doFileVersion.Version2_3, '')
                restored, _ = load3do(path)
                self.assertEqual(len(restored.geosets), len(geosets))
                self.assertEqual(restored.meshHierarchy, [])

    def test_case_comments_whitespace_and_unknown_section(self):
        text = (TV / 'model' / 'triangle.3do').read_text().lower()
        text = text.replace('section:', '\n# section comment\nSeCtIoN\t:')
        text += '\nSECTION: extension\ncustom metadata ignored\n'
        model, _ = self.load_text(text)
        self.assertEqual(len(model.geosets[0].meshes[0].faces), 1)

    def test_grim_fandango_shadow_and_light_mode(self):
        text = (TV / 'model' / 'triangle.3do').read_text()
        text = text.replace('GEOMETRYMODE 4', 'SHADOW 1\nGEOMETRYMODE 4')
        text = text.replace('LIGHTINGMODE 3', 'LIGHTINGMODE 6')
        model, _ = self.load_text(text)
        self.assertEqual(model.geosets[0].meshes[0].lightMode, 6)

    def test_index_mismatch_warns_and_still_loads(self):
        text = (TV / 'model' / 'triangle.3do').read_text().replace('0: checker.mat', '7: checker.mat')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            model, _ = self.load_text(text)
        self.assertIn('Index mismatch', output.getvalue())
        self.assertEqual(model.materials[0], 'checker.mat')

    def test_invalid_header_version_and_modes_are_rejected(self):
        original = (TV / 'model' / 'triangle.3do').read_text()
        for before, after in (('3DO 2.3', 'BAD 2.3'), ('3DO 2.3', '3DO 9.9'),
                              ('GEOMETRYMODE 4', 'GEOMETRYMODE 99'),
                              ('TEXTUREMODE 3', 'TEXTUREMODE 99'),
                              ('VERTICES 3', 'WRONG 3')):
            with self.subTest(after=after), self.assertRaises((OSError, ValueError, AssertionError)):
                self.load_text(original.replace(before, after, 1))

    def test_truncated_geometry_and_hierarchy_are_rejected(self):
        original = (TV / 'model' / 'triangle.3do').read_text()
        for end in ('VERTICES 3', 'TEXTURE VERTICES 3', 'FACES 1', 'HIERARCHY NODES 2'):
            text = original[:original.index(end) + len(end)]
            with self.subTest(end=end), self.assertRaises((TypeError, ValueError, AssertionError)):
                self.load_text(text)

    def test_missing_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(FileNotFoundError):
            load3do(Path(directory) / 'missing.3do')

    def test_writer_is_deterministic(self):
        model, _ = load3do(TV / 'model' / 'triangle.3do')
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / name for name in ('a.3do', 'b.3do')]
            for path in paths:
                save3do(model, path, Model3doFileVersion.Version2_3, 'same')
            self.assertEqual(paths[0].read_bytes(), paths[1].read_bytes())
