"""Independent synthetic MODL records, not output from the production writer."""
import struct


def grim_mat_bytes(*, tag=8, cels=None, trailer=b''):
    """Indexed type-3 MAT, with independent full/compact record packing."""
    if cels is None:
        cels = [(2, 2, [bytes((0, 17, 70, 255))], True)]
    # Only the first two color-format words are meaningful for these indexed
    # resources. Retail files retain arbitrary values in the remaining fields.
    data = struct.pack('<4s4I14I', b'MAT ', 50, 3, len(cels), len(cels),
                       0, 8, *([0x12345678] * 12))
    for index in range(len(cels)):
        words = (tag if index == 0 else 8, 70, 0x3f800000, 0x3f800000,
                 0x3f800000, 0x3f800000, 0xABCDEF01, 0x12345678, 0, index)
        compact = index == 0 and tag == 0
        data += struct.pack('<6I' if compact else '<10I', *(words[:6] if compact else words))
    for width, height, levels, transparent in cels:
        data += struct.pack('<6I', width, height, int(transparent), 0, 0, len(levels))
        data += b''.join(levels)
    return data + trailer


def binary_3do_bytes(*, textured=True, material=True, geosets=1, empty=False):
    data = bytearray(b'LDOM')
    offsets = {}

    def record(name, fmt, *values):
        offsets.setdefault(name, len(data))
        data.extend(struct.pack('<' + fmt, *values))

    def name(value, size, padding):
        encoded = value.encode('ascii') + b'\0'
        data.extend(encoded + bytes([padding]) * (size - len(encoded)))

    # 1. Names and pointer-presence words deliberately retain nonzero padding
    # and non-boolean values so normalized rewrites cannot pass byte equality.
    record('material_count', 'I', 1)
    name('checker.mat', 32, 0xA1)
    name('binary_test.3do', 32, 0xB2)
    record('geoset_pointer', 'I', 0x10203040)
    record('geoset_count', 'I', geosets)
    for geoset in range(geosets):
        record('mesh_count', 'I', 1)
        name('triangle' if not geoset else 'other_lod', 32, 0xC3)
        record('mesh_unknown', 'I', 0x13579BDF)
        record('geometry_mode', 'I', 4)
        record('lighting_mode', 'I', 6)
        record('texture_mode', 'I', 3)
        record('vertex_count', 'I', 0 if empty else 4)
        record('uv_count', 'I', 0 if empty else 3)
        record('face_count', 'I', 0 if empty else 1)
        if not empty:
            record('vertices', '12f', 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1)
            record('uvs', '6f', 0, 0, 64, 0, 0, 32)
            record('intensities', '4f', -0.5, 0.25, 2.0, 0.75)
            record('vertex_data', '4I', 0, 0xFFFFFFFF, 0x12345678, 0x80000000)
            record('face_id', 'I', 11)
            record('face_flags', 'I', 0x80000103)
            record('face_geometry', 'I', 4 if textured else 3)
            record('face_lighting', 'I', 3)
            record('face_texture', 'I', 3)
            record('corner_count', 'I', 3)
            record('face_unknown1', 'I', 0x2468ACE0)
            record('texture_pointer', 'I', 0xF0000001 if textured else 0)
            record('material_pointer', 'I', 0xE0000002 if material else 0)
            record('face_unknown2', '12s', b'\xA5' * 12)
            record('face_intensity', 'f', 0.125)
            record('face_unknown3', '12s', b'\x5A' * 12)
            record('face_normal', '3f', 0, 0, 1)
            record('vertex_index', '3I', 0, 1, 2)
            if textured:
                record('uv_index', '3I', 0, 1, 2)
            if material:
                record('material_index', 'I', 0)
            record('normals', '12f', 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 0)
        record('shadow', 'I', 1)
        record('mesh_unknown3', 'I', 0x89ABCDEF)
        record('mesh_radius', 'f', 2.0)
        record('mesh_bounds', '6f', -1, -2, -3, 2, 3, 4)

    # 2. An empty root has two children. Only the first child owns a mesh;
    # sibling links and optional parent indices are independent of mesh IDs.
    record('node_pointer', 'I', 0x50607080)
    record('node_count', 'I', 3)
    for index, label in enumerate(('root', 'head', 'empty_joint')):
        record('node' + str(index), '0s', b'')
        name(label, 64, 0xCC)
        record(f'node{index}_flags', 'I', 0x80010001 + index)
        record(f'node{index}_unknown', 'I', 0xABC00000 + index)
        record(f'node{index}_type', 'I', 0x8008)
        record(f'node{index}_mesh', 'i', 0 if index == 1 else -1)
        record(f'node{index}_depth', 'I', int(index != 0))
        record(f'node{index}_parent_pointer', 'I', 0x20000000 if index else 0)
        record(f'node{index}_children', 'I', 0 if index else 2)
        record(f'node{index}_child_pointer', 'I', 0 if index else 0x30000000)
        record(f'node{index}_sibling_pointer', 'I', 0x40000000 if index == 1 else 0)
        record(f'node{index}_pivot', '3f', 0.25 if index == 1 else 0, 0, 0)
        record(f'node{index}_position', '3f', 0, index, index * 2)
        record(f'node{index}_rotation', '3f', 10 if index == 0 else 0, -20 if index == 0 else 0, 30 if index == 0 else 0)
        record(f'node{index}_transform', '48s', bytes([0x30 + index]) * 48)
        if index:
            record(f'node{index}_parent', 'I', 0)
        else:
            record('node0_child', 'I', 1)
        if index == 1:
            record('node1_sibling', 'I', 2)

    # 3. The opaque footer starts with a different vector from INSERT OFFSET.
    # This independently catches the early 3doobj footer-order interpretation.
    record('model_radius', 'f', float('inf') if empty else 3.5)
    record('model_footer', '9f', 91, 92, 93, -11, -12, -13, 21, 22, 23)
    record('insert_offset', '3f', 0.5, -0.25, 1.5)
    return bytes(data), offsets


def changed_word(data, offset, value, fmt='I'):
    result = bytearray(data)
    struct.pack_into('<' + fmt, result, offset, value)
    return bytes(result)


def binary_key_bytes(*, first_animated=False, duplicates=True, flags=0, fps=15.0, markers=2):
    """136-byte FYEK header plus independently packed node/entry records."""
    offsets = {}
    name = b'fixture.key\0' + b'\xA1' * (36 - len(b'fixture.key\0'))
    data = bytearray(struct.pack('<4s36s3If4I', b'FYEK', name, flags, 3, 0xFFFF,
                                 fps, 4, 3, 0x12345678, markers))
    # Inactive marker slots retain arbitrary bits, including signaling NaNs.
    data.extend(struct.pack('<8I', *([0x7FA00001] * 8)))
    data.extend(struct.pack('<8i', *([-123456] * 8)))
    for index in range(markers):
        struct.pack_into('<f', data, 72 + 4 * index, index + 0.125)
        struct.pack_into('<i', data, 104 + 4 * index, index % 2 + 1)

    def node(index, name, animated, label):
        offsets[label] = len(data)
        raw = name.encode('ascii')
        raw = (raw + b'\0' + b'\xB2' * (31 - len(raw))) if raw else bytes(32)
        data.extend(struct.pack('<32s3I', raw, index, 2 if animated else 0, 0xABC00000 + index))
        if animated:
            offsets[label + '_entry'] = len(data)
            # Entry flags deliberately say "no change"; Grim still uses deltas
            # unless the animation-level 0x100 flag disables interpolation.
            data.extend(struct.pack('<fI12f', 0, 0, 1, 2, 3, 10, 20, 30, .5, 0, 0, 0, 90, 0))
            data.extend(struct.pack('<fI12f', 2, 3, 2, 2, 3, 10, 200, 30, 0, 0, 0, 0, 0, 0))

    node(0, 'root' if first_animated else '', first_animated, 'node0')
    node(1, 'joint', True, 'node1')
    node(0 if duplicates else 2, '', False, 'node2')
    return bytes(data), offsets
