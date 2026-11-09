"""Grim MODL layout, exact serialization, optional records and safety checks."""
import math
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from fixtures import TV
from grim_fixtures import binary_3do_bytes, changed_word
from sith.model.model3doBinary import encodeBinary3do, readBinary3do
from sith.model.model3do import Model3do, Mesh3doNode
from sith.model.model3doLoader import load3do, Model3doFileFormat, Model3doFileVersion
from sith.model.model3doWriter import save3do


class BinaryModelTests(unittest.TestCase):
    def test_independent_layout_and_fields(self):
        data, _ = binary_3do_bytes()
        model = readBinary3do(data)
        self.assertEqual(model.name, 'binary_test.3do')
        self.assertEqual(model.materials, ['checker.mat'])
        self.assertEqual(model.radius, 3.5)
        self.assertEqual(model.insertOffset, (0.5, -0.25, 1.5))
        self.assertNotEqual(model.insertOffset, (91, 92, 93))
        mesh = model.geosets[0].meshes[0]
        self.assertEqual((int(mesh.geometryMode), int(mesh.lightMode), int(mesh.textureMode)), (4, 6, 3))
        self.assertEqual(mesh.vertices, [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)])
        self.assertEqual(mesh.uvs, [(0, 0), (64, 0), (0, 32)])
        self.assertEqual(mesh.vertexColors, [(-0.5, -0.5, -0.5, 1), (0.25, 0.25, 0.25, 1),
                                             (2, 2, 2, 1), (0.75, 0.75, 0.75, 1)])
        self.assertEqual(mesh.binaryData['vertexData'], [0, 0xFFFFFFFF, 0x12345678, 0x80000000])
        self.assertEqual(mesh.shadow, 1)
        face = mesh.faces[0]
        self.assertEqual(face.binaryData['id'], 11)
        self.assertEqual(int(face.type), 0x80000103)
        self.assertEqual(face.materialIdx, 0)
        self.assertEqual(face.vertexIdxs, [0, 1, 2])
        self.assertEqual(face.uvIdxs, [0, 1, 2])
        self.assertEqual(face.normal, (0, 0, 1))
        self.assertEqual(face.color, (0.125, 0.125, 0.125, 1))
        self.assertEqual([node.parentIdx for node in model.meshHierarchy], [-1, 0, 0])
        self.assertEqual([node.meshIdx for node in model.meshHierarchy], [-1, 0, -1])
        self.assertEqual([node.firstChildIdx for node in model.meshHierarchy], [1, -1, -1])
        self.assertEqual([node.siblingIdx for node in model.meshHierarchy], [-1, 2, -1])
        self.assertEqual(model.meshHierarchy[0].rotation, (10, -20, 30))
        self.assertEqual(model.meshHierarchy[1].pivot, (0.25, 0, 0))

    def test_exact_bytes_include_opaque_fields_padding_and_multiple_geosets(self):
        for geosets in (1, 2, 3):
            for textured in (False, True):
                for material in (False, True):
                    with self.subTest(geosets=geosets, textured=textured, material=material):
                        data, _ = binary_3do_bytes(geosets=geosets, textured=textured, material=material)
                        model = readBinary3do(data)
                        self.assertEqual(len(model.geosets), geosets)
                        self.assertEqual(encodeBinary3do(model), data)

    def test_auto_detection_does_not_depend_on_extension_or_recovery_switch(self):
        data, _ = binary_3do_bytes()
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / 'input.bin', Path(directory) / 'output.3do'
            source.write_bytes(data)
            for recovery in (False, True):
                with self.subTest(recovery=recovery):
                    warnings = []
                    model, version = load3do(source, allowErrors=recovery, warnings=warnings)
                    self.assertEqual(version, Model3doFileFormat.GrimFandango)
                    self.assertEqual(warnings, [])
                    save3do(model, output, version, 'Binary records have no comment section')
                    self.assertEqual(output.read_bytes(), data)
                    self.assertEqual(source.read_bytes(), data)

    def test_every_truncated_prefix_and_trailing_data_is_rejected(self):
        data, _ = binary_3do_bytes()
        for length in range(len(data)):
            with self.subTest(length=length), self.assertRaises(ValueError):
                readBinary3do(data[:length])
        with self.assertRaisesRegex(ValueError, 'trailing'):
            readBinary3do(data + b'junk')

    def test_magic_counts_and_render_modes_are_checked(self):
        data, offsets = binary_3do_bytes()
        for field in ('material_count', 'geoset_count', 'mesh_count', 'vertex_count',
                      'uv_count', 'face_count', 'corner_count', 'node_count'):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'count|Truncated'):
                readBinary3do(changed_word(data, offsets[field], 0xFFFFFFFF))
        for field in ('geometry_mode', 'lighting_mode', 'texture_mode', 'face_geometry',
                      'face_lighting', 'face_texture'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                readBinary3do(changed_word(data, offsets[field], 99))
        with self.assertRaisesRegex(ValueError, 'magic'):
            readBinary3do(b'MODL' + data[4:])

    def test_all_index_tables_reject_out_of_range_values(self):
        data, offsets = binary_3do_bytes()
        for field in ('vertex_index', 'uv_index', 'material_index', 'node0_child',
                      'node1_parent', 'node1_sibling', 'node1_mesh'):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'index'):
                readBinary3do(changed_word(data, offsets[field], 99))

    def test_parent_and_child_sibling_cycles_are_rejected(self):
        data, offsets = binary_3do_bytes()
        for field, value in (('node1_parent', 1), ('node0_child', 0), ('node1_sibling', 1)):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'cycle'):
                readBinary3do(changed_word(data, offsets[field], value))

    def test_nonfinite_represented_data_is_rejected(self):
        data, offsets = binary_3do_bytes()
        for field in ('model_radius', 'insert_offset', 'mesh_radius', 'vertices', 'uvs',
                      'intensities', 'normals', 'face_intensity', 'face_normal',
                      'node0_position', 'node0_rotation', 'node0_pivot'):
            for value in (math.inf, -math.inf, math.nan):
                with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, 'finite'):
                    readBinary3do(changed_word(data, offsets[field], value, 'f'))

    def test_geometry_free_retail_infinite_radius_sentinel_is_preserved(self):
        data, offsets = binary_3do_bytes(empty=True)
        model = readBinary3do(data)
        self.assertEqual(model.radius, math.inf)
        self.assertEqual(model.geosets[0].meshes[0].vertices, [])
        self.assertEqual(encodeBinary3do(model), data)
        # Neither NaN nor negative infinity is the retail empty-bound sentinel.
        for value in (math.nan, -math.inf):
            with self.subTest(value=value), self.assertRaises(ValueError):
                readBinary3do(changed_word(data, offsets['model_radius'], value, 'f'))

    def test_fixed_width_names_and_renames(self):
        data, _ = binary_3do_bytes()
        model = readBinary3do(data)
        model.name = 'm' * 32
        model.materials[0] = 't' * 32
        model.geosets[0].meshes[0].name = 's' * 32
        model.meshHierarchy[1].name = 'j' * 64
        restored = readBinary3do(encodeBinary3do(model))
        self.assertEqual(restored.name, model.name)
        self.assertEqual(restored.materials, model.materials)
        self.assertEqual(restored.geosets[0].meshes[0].name, 's' * 32)
        self.assertEqual(restored.meshHierarchy[1].name, 'j' * 64)

    def test_invalid_names_and_metadata_preserve_existing_output(self):
        original, _ = binary_3do_bytes()
        for field, value in (('name', 'm' * 33), ('name', 'bad\0name'), ('name', 'bad\nname'),
                             ('name', '\N{LATIN SMALL LETTER E WITH ACUTE}'),
                             ('binaryData', {'footer': 'ff'}), ('binaryData', 'not a dictionary')):
            model = readBinary3do(original)
            setattr(model, field, value)
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'previous.3do'
                path.write_bytes(b'previous export')
                with self.assertRaises(ValueError):
                    save3do(model, path, Model3doFileFormat.GrimFandango, '')
                self.assertEqual(path.read_bytes(), b'previous export')

    def test_invalid_vertex_metadata_and_integer_fields_are_rejected(self):
        data, _ = binary_3do_bytes()
        for key, value in (('vertexData', []), ('vertexData', 'bad'), ('unknown1', -1),
                           ('unknown1', 1 << 32), ('bounds', 'not hexadecimal')):
            model = readBinary3do(data)
            model.geosets[0].meshes[0].binaryData[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                encodeBinary3do(model)

    def test_changed_hierarchy_recomputes_depth_and_presence_words(self):
        data, _ = binary_3do_bytes()
        model = readBinary3do(data)
        model.meshHierarchy[0].numChildren = 1
        model.meshHierarchy[1].firstChildIdx = 2
        model.meshHierarchy[1].siblingIdx = -1
        model.meshHierarchy[1].numChildren = 1
        model.meshHierarchy[2].parentIdx = 1
        restored = readBinary3do(encodeBinary3do(model))
        self.assertEqual(restored.meshHierarchy[2].binaryData['depth'], 2)
        self.assertEqual(restored.meshHierarchy[1].binaryData['siblingPointer'], 0)
        self.assertNotEqual(restored.meshHierarchy[1].binaryData['childPointer'], 0)

    def test_text_shadow_and_new_models_convert_to_binary(self):
        model, _ = load3do(TV / 'model' / 'triangle.3do')
        model.geosets[0].meshes[0].shadow = 1
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'shadow.3do'
            save3do(model, path, Model3doFileVersion.Version2_1, '')
            self.assertIn('SHADOW 1', path.read_text())
            restored, _ = load3do(path)
            binary = readBinary3do(encodeBinary3do(restored))
            self.assertEqual(binary.geosets[0].meshes[0].shadow, 1)
            self.assertEqual(binary.insertOffset, (0.5, -0.25, 1))
            self.assertEqual(binary.geosets[0].meshes[0].vertexColors[0], (struct.unpack('<f', struct.pack('<f', 1 / 3))[0],) * 3 + (1,))

    def test_binary_reader_closes_files_even_when_recovery_was_requested(self):
        data, _ = binary_3do_bytes()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'truncated.3do'
            path.write_bytes(data[:-1])
            for recovery in (False, True):
                with self.subTest(recovery=recovery), self.assertRaises(ValueError):
                    load3do(path, allowErrors=recovery)
                # A closed source remains replaceable/unlinkable on Windows.
                path.rename(path.with_suffix('.tmp'))
                path.with_suffix('.tmp').rename(path)

    def test_complete_empty_resource_has_no_required_geometry_or_nodes(self):
        model = Model3do('empty')
        data = encodeBinary3do(model)
        restored = readBinary3do(data)
        self.assertEqual(restored.geosets, [])
        self.assertEqual(restored.meshHierarchy, [])
        self.assertEqual(restored.radius, 0)
        self.assertEqual(encodeBinary3do(restored), data)

    def test_zero_corner_record_retains_optional_texture_presence(self):
        data, _ = binary_3do_bytes()
        model = readBinary3do(data)
        face = model.geosets[0].meshes[0].faces[0]
        face.vertexIdxs, face.uvIdxs = [], []
        encoded = encodeBinary3do(model)
        restored = readBinary3do(encoded)
        self.assertEqual(restored.geosets[0].meshes[0].faces[0].binaryData['texturePointer'], 0xF0000001)
        self.assertEqual(encodeBinary3do(restored), encoded)

    def test_invalid_render_modes_never_replace_an_existing_export(self):
        data, _ = binary_3do_bytes()
        for scope in ('mesh', 'face'):
            for field in ('geometryMode', 'lightMode', 'textureMode'):
                model = readBinary3do(data)
                mesh = model.geosets[0].meshes[0]
                setattr(mesh if scope == 'mesh' else mesh.faces[0], field, 99)
                with self.subTest(scope=scope, field=field), tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / 'previous.3do'
                    path.write_bytes(b'previous export')
                    with self.assertRaises(ValueError):
                        save3do(model, path, Model3doFileFormat.GrimFandango, '')
                    self.assertEqual(path.read_bytes(), b'previous export')

    def test_deep_hierarchy_depths_use_a_linear_number_of_parent_reads(self):
        model = Model3do('deep')
        count = 1000
        for index in range(count):
            node = Mesh3doNode('joint')
            node.idx, node.parentIdx = index, index - 1
            node.firstChildIdx = index + 1 if index + 1 < count else -1
            node.numChildren = int(index + 1 < count)
            model.meshHierarchy.append(node)
        original = Mesh3doNode.parentIdx
        reads = 0

        def parent(node):
            nonlocal reads
            reads += 1
            return original.fget(node)

        with patch.object(Mesh3doNode, 'parentIdx', property(parent)):
            data = encodeBinary3do(model)
        self.assertLess(reads, count * 20)
        restored = readBinary3do(data)
        self.assertEqual(restored.meshHierarchy[-1].binaryData['depth'], count - 1)
        self.assertEqual(encodeBinary3do(restored), data)

    def test_scalar_intensities_preserve_negative_zero_and_subnormal_bits(self):
        data, offsets = binary_3do_bytes()
        for value in (-0.0, struct.unpack('<f', struct.pack('<I', 1))[0]):
            changed = changed_word(data, offsets['intensities'], value, 'f')
            changed = changed_word(changed, offsets['face_intensity'], value, 'f')
            with self.subTest(value=value):
                self.assertEqual(encodeBinary3do(readBinary3do(changed)), changed)
