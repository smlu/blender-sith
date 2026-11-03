# SPDX-FileCopyrightText: 2026 Crt Vavros
# SPDX-License-Identifier: GPL-3.0-or-later
"""Grim Fandango's little-endian MODL resource (on-disk magic ``LDOM``).

Undocumented words, cached transforms and name padding remain opaque metadata.
They are not addresses to follow or offsets into the file. Nonzero pointer words
only indicate whether a following index/array is present.
"""
import math
import struct

from .model3do import (FaceType, GeometryMode, LightMode, Mesh3do, Mesh3doFace,
                       Mesh3doNode, Mesh3doNodeFlags, Mesh3doNodeType, Model3do,
                       Model3doGeoSet, TextureMode)
from ..types import Vector2f, Vector3f, Vector4f
from ..types.vector import validateFloat32

kBinary3doMagic = b'LDOM'
kBinary3doNameSize = 32
kBinary3doNodeNameSize = 64


class _Reader:
    def __init__(self, data):
        self.data = memoryview(data)
        self.offset = 0

    def take(self, size, label):
        if size < 0 or size > len(self.data) - self.offset:
            raise ValueError(f'Truncated binary 3DO {label} at byte {self.offset}')
        result = self.data[self.offset:self.offset + size]
        self.offset += size
        return result

    def unpack(self, fmt, label):
        record = struct.Struct('<' + fmt)
        return record.unpack(self.take(record.size, label))

    def count(self, label, minimumSize):
        value, = self.unpack('I', label + ' count')
        self.check_count(value, minimumSize, label)
        return value

    def check_count(self, value, minimumSize, label):
        if value > (len(self.data) - self.offset) // minimumSize:
            raise ValueError(f'Binary 3DO {label} count {value} exceeds the remaining file')

    def array(self, fmt, count, label):
        record = struct.Struct('<' + fmt)
        self.check_count(count, record.size, label)
        return list(record.iter_unpack(self.take(count * record.size, label)))


def _name(raw, label):
    try:
        value = bytes(raw).split(b'\0', 1)[0].decode('ascii')
    except UnicodeDecodeError as error:
        raise ValueError(f'Binary 3DO {label} must be ASCII') from error
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f'Binary 3DO {label} contains control characters')
    return value


def _metadata(value, label):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f'Invalid binary 3DO {label} metadata')
    return value


def _opaque(metadata, key, size):
    try:
        data = bytes.fromhex(metadata[key]) if key in metadata else bytes(size)
    except (TypeError, ValueError) as error:
        raise ValueError(f'Invalid binary 3DO {key} metadata') from error
    if len(data) != size:
        raise ValueError(f'Binary 3DO {key} must contain exactly {size} bytes')
    return data


def _write_name(value, size, original=None):
    if not isinstance(value, str) or '\0' in value:
        raise ValueError('Binary 3DO names must be strings without embedded NULs')
    try:
        data = value.encode('ascii')
    except UnicodeEncodeError as error:
        raise ValueError('Binary 3DO names must be ASCII') from error
    if len(data) > size:
        raise ValueError(f'Binary 3DO name {value!r} exceeds its {size}-byte field')
    _name(data, 'name')
    if original is not None:
        try:
            raw = bytes.fromhex(original)
        except (TypeError, ValueError) as error:
            raise ValueError('Invalid binary 3DO name padding metadata') from error
        if len(raw) != size:
            raise ValueError('Invalid binary 3DO name field size')
        if _name(raw, 'name') == value:
            return raw
    return data.ljust(size, b'\0')


def _presence(metadata, key, present):
    value = metadata.get(key, int(present))
    return value if bool(value) == present else int(present)


def _validate_model(model):
    """Validate represented data without interpreting undocumented bytes."""
    # Retail null/skeleton-only resources cache +inf as their unused radius.
    # Keep that sentinel in the codec, but never allow it on actual geometry.
    empty = not any(mesh.vertices for geoset in model.geosets for mesh in geoset.meshes)
    if not (empty and model.radius == math.inf):
        validateFloat32((model.radius,), 'Binary 3DO model radius')
    validateFloat32(model.insertOffset, 'Binary 3DO insert offset')
    if model.radius < 0:
        raise ValueError('Binary 3DO model radius must be nonnegative')
    meshes = model.geosets[0].meshes if model.geosets else []
    nodes = model.meshHierarchy
    for index, node in enumerate(nodes):
        validateFloat32((*node.position, *node.rotation, *node.pivot), 'Binary 3DO node transforms')
        if not -1 <= node.meshIdx < len(meshes):
            raise ValueError(f'Binary 3DO node {index} has an invalid mesh index')
        for value in (node.parentIdx, node.firstChildIdx, node.siblingIdx):
            if not -1 <= value < len(nodes):
                raise ValueError(f'Binary 3DO node {index} has an invalid hierarchy index')
        if node.numChildren < 0 or node.numChildren > len(nodes):
            raise ValueError(f'Binary 3DO node {index} has an invalid child count')

    # Follow both the parent relation and the engine's child/sibling traversal.
    # Iterative walks avoid recursion limits on malformed or very deep resources.
    for traversal in ('parents', 'children'):
        complete = set()
        for start in range(len(nodes)):
            pending = [(start, False)]
            active = set()
            while pending:
                index, leaving = pending.pop()
                if leaving:
                    active.remove(index)
                    complete.add(index)
                    continue
                if index < 0 or index in complete:
                    continue
                if index in active:
                    raise ValueError(f'Binary 3DO hierarchy contains a {traversal} cycle')
                active.add(index)
                pending.append((index, True))
                node = nodes[index]
                links = (node.parentIdx,) if traversal == 'parents' else (node.firstChildIdx, node.siblingIdx)
                pending.extend((value, False) for value in links if value >= 0)

    for geoset in model.geosets:
        for mesh in geoset.meshes:
            GeometryMode(mesh.geometryMode)
            LightMode(mesh.lightMode)
            TextureMode(mesh.textureMode)
            if len(mesh.vertices) != len(mesh.vertexColors) or len(mesh.vertices) != len(mesh.normals):
                raise ValueError('Binary 3DO vertex, intensity and normal counts must agree')
            validateFloat32((mesh.radius,), 'Binary 3DO mesh radius')
            if mesh.radius < 0:
                raise ValueError('Binary 3DO mesh radius must be nonnegative')
            for vectors in (mesh.vertices, mesh.vertexColors, mesh.normals, mesh.uvs):
                validateFloat32((value for vector in vectors for value in vector), 'Binary 3DO mesh data')
            for face in mesh.faces:
                GeometryMode(face.geometryMode)
                LightMode(face.lightMode)
                TextureMode(face.textureMode)
                validateFloat32((*face.normal, *face.color), 'Binary 3DO face data')
                if not -1 <= face.materialIdx < len(model.materials):
                    raise ValueError('Binary 3DO face has an invalid material index')
                if any(index < 0 or index >= len(mesh.vertices) for index in face.vertexIdxs):
                    raise ValueError('Binary 3DO face has an invalid vertex index')
                if len(face.uvIdxs) != len(face.vertexIdxs):
                    raise ValueError('Binary 3DO face vertex and UV counts must agree')
                if any(index < -1 for index in face.uvIdxs):
                    raise ValueError('Binary 3DO face has an invalid UV index')
                if any(index >= 0 for index in face.uvIdxs):
                    if any(index < 0 or index >= len(mesh.uvs) for index in face.uvIdxs):
                        raise ValueError('Binary 3DO face has an invalid UV index')


def readBinary3do(data):
    """Decode a complete resource; truncated binary records are never guessed."""
    reader = _Reader(data)
    if bytes(reader.take(4, 'magic')) != kBinary3doMagic:
        raise ValueError('Invalid Grim Fandango binary 3DO magic; expected LDOM')
    model = Model3do()
    metadata = model.binaryData = {}

    # 1. Fixed-width resource names precede every geometry set.
    count = reader.count('material', kBinary3doNameSize)
    names = [bytes(reader.take(kBinary3doNameSize, 'material name')) for _ in range(count)]
    model.materials = [_name(raw, 'material name') for raw in names]
    metadata['materialNames'] = [raw.hex() for raw in names]
    raw = bytes(reader.take(kBinary3doNameSize, 'model name'))
    model.name = _name(raw, 'model name')
    metadata['nameBytes'] = raw.hex()
    metadata['geosetPointer'], = reader.unpack('I', 'geoset pointer')
    count = reader.count('geoset', 4)
    for _ in range(count):
        geoset = Model3doGeoSet()
        model.geosets.append(geoset)
        meshCount = reader.count('mesh', 96)
        for index in range(meshCount):
            geoset.meshes.append(_read_mesh(reader, index))

    # 2. Hierarchy indices are conditional on nonzero serialized pointer words.
    metadata['nodePointer'], = reader.unpack('I', 'node pointer')
    count = reader.count('node', 184)
    for index in range(count):
        model.meshHierarchy.append(_read_node(reader, index))

    # 3. Unlike the early 3doobj description, INSERT OFFSET is the final vector:
    # radius, 36 opaque bytes, then the actual insertion offset (ScummVM layout).
    model.radius, = reader.unpack('f', 'model radius')
    metadata['footer'] = bytes(reader.take(36, 'model footer')).hex()
    model.insertOffset = Vector3f(*reader.unpack('3f', 'insert offset'))
    if reader.offset != len(reader.data):
        raise ValueError(f'Unexpected trailing binary 3DO data at byte {reader.offset}')
    _validate_model(model)
    return model


def _read_mesh(reader, index):
    raw = bytes(reader.take(kBinary3doNameSize, 'mesh name'))
    mesh = Mesh3do(index, _name(raw, 'mesh name'))
    metadata = mesh.binaryData = {'nameBytes': raw.hex()}
    metadata['unknown1'], geo, light, tex, vertices, uvs, faces = reader.unpack('7I', 'mesh header')
    mesh.geometryMode, mesh.lightMode, mesh.textureMode = GeometryMode(geo), LightMode(light), TextureMode(tex)
    # Account for every minimum-sized array before allocating any of them.
    minimum = vertices * 32 + uvs * 8 + faces * 76 + 36
    reader.check_count(minimum, 1, 'mesh payload byte')
    mesh.vertices = [Vector3f(*values) for values in reader.array('3f', vertices, 'vertices')]
    mesh.uvs = [Vector2f(*values) for values in reader.array('2f', uvs, 'UVs')]
    mesh.vertexColors = [Vector4f(value, value, value, 1.0)
                         for value, in reader.array('f', vertices, 'vertex intensities')]
    metadata['vertexData'] = [value for value, in reader.array('I', vertices, 'vertex metadata')]
    mesh.faces = [_read_face(reader) for _ in range(faces)]
    mesh.normals = [Vector3f(*values) for values in reader.array('3f', vertices, 'vertex normals')]
    mesh.shadow, metadata['unknown3'], mesh.radius = reader.unpack('2If', 'mesh footer')
    metadata['bounds'] = bytes(reader.take(24, 'mesh bounds')).hex()
    return mesh


def _read_face(reader):
    face = Mesh3doFace()
    metadata = face.binaryData = {}
    (metadata['id'], flags, geo, light, tex, count, metadata['unknown1'],
     metadata['texturePointer'], metadata['materialPointer']) = reader.unpack('9I', 'face header')
    face.type = FaceType(flags)
    face.geometryMode, face.lightMode, face.textureMode = GeometryMode(geo), LightMode(light), TextureMode(tex)
    metadata['unknown2'] = bytes(reader.take(12, 'face metadata')).hex()
    intensity, = reader.unpack('f', 'face intensity')
    face.color = Vector4f(intensity, intensity, intensity, 1.0)
    metadata['unknown3'] = bytes(reader.take(12, 'face metadata')).hex()
    face.normal = Vector3f(*reader.unpack('3f', 'face normal'))
    face.vertexIdxs = [value for value, in reader.array('I', count, 'face vertex indices')]
    face.uvIdxs = ([value for value, in reader.array('I', count, 'face UV indices')]
                   if metadata['texturePointer'] else [-1] * count)
    if metadata['materialPointer']:
        face.materialIdx, = reader.unpack('I', 'face material index')
    return face


def _read_node(reader, index):
    raw = bytes(reader.take(kBinary3doNodeNameSize, 'node name'))
    node = Mesh3doNode(_name(raw, 'node name'))
    node.idx = index
    metadata = node.binaryData = {'nameBytes': raw.hex()}
    (flags, metadata['unknown1'], kind, mesh, metadata['depth'], metadata['parentPointer'],
     node.numChildren, metadata['childPointer'], metadata['siblingPointer']) = reader.unpack('IIIi5I', 'node header')
    node.flags, node.type, node.meshIdx = Mesh3doNodeFlags(flags), Mesh3doNodeType(kind), mesh
    node.pivot = Vector3f(*reader.unpack('3f', 'node pivot'))
    node.position = Vector3f(*reader.unpack('3f', 'node position'))
    node.rotation = Vector3f(*reader.unpack('3f', 'node rotation'))
    metadata['transform'] = bytes(reader.take(48, 'node cached transform')).hex()
    for pointer, attribute in (('parentPointer', 'parentIdx'), ('childPointer', 'firstChildIdx'),
                               ('siblingPointer', 'siblingIdx')):
        if metadata[pointer]:
            setattr(node, attribute, reader.unpack('I', attribute)[0])
    return node


def encodeBinary3do(model):
    """Build and validate all bytes before an existing destination can be opened."""
    _validate_model(model)
    output = bytearray(kBinary3doMagic)

    def pack(fmt, *values):
        try:
            output.extend(struct.pack('<' + fmt, *values))
        except (struct.error, OverflowError, TypeError) as error:
            raise ValueError(f'Invalid binary 3DO field: {error}') from error

    metadata = _metadata(model.binaryData, 'model')
    materialNames = metadata.get('materialNames', [])
    if not isinstance(materialNames, list):
        raise ValueError('Invalid binary 3DO material-name metadata')
    pack('I', len(model.materials))
    for index, name in enumerate(model.materials):
        output.extend(_write_name(name, kBinary3doNameSize,
                                   materialNames[index] if index < len(materialNames) else None))
    output.extend(_write_name(model.name, kBinary3doNameSize, metadata.get('nameBytes')))
    pack('2I', metadata.get('geosetPointer', 0), len(model.geosets))
    for geoset in model.geosets:
        pack('I', len(geoset.meshes))
        for mesh in geoset.meshes:
            _write_mesh(output, pack, mesh)

    pack('2I', metadata.get('nodePointer', 0), len(model.meshHierarchy))
    # Cache shared ancestry once; walking every parent chain separately would
    # make serialization quadratic on a deeply nested but valid hierarchy.
    depths = {}
    for index in range(len(model.meshHierarchy)):
        chain = []
        current = index
        while current >= 0 and current not in depths:
            chain.append(current)
            current = model.meshHierarchy[current].parentIdx
        depth = depths.get(current, -1)
        for current in reversed(chain):
            depth += 1
            depths[current] = depth
    for index, node in enumerate(model.meshHierarchy):
        _write_node(output, pack, node, depths[index])
    empty = not any(mesh.vertices for geoset in model.geosets for mesh in geoset.meshes)
    radius = math.inf if empty and model.radius == 0 and metadata.get('emptyRadius') else model.radius
    pack('f', radius)
    output.extend(_opaque(metadata, 'footer', 36))
    pack('3f', *model.insertOffset)
    return bytes(output)


def _write_mesh(output, pack, mesh):
    metadata = _metadata(mesh.binaryData, 'mesh')
    output.extend(_write_name(mesh.name, kBinary3doNameSize, metadata.get('nameBytes')))
    pack('7I', metadata.get('unknown1', 0), int(mesh.geometryMode), int(mesh.lightMode), int(mesh.textureMode),
         len(mesh.vertices), len(mesh.uvs), len(mesh.faces))
    for vertex in mesh.vertices:
        pack('3f', *vertex)
    for uv in mesh.uvs:
        pack('2f', *uv)
    for color in mesh.vertexColors:
        pack('f', (color[0] + color[1] + color[2]) / 3.0)
    vertexData = metadata.get('vertexData', [0] * len(mesh.vertices))
    if not isinstance(vertexData, list) or len(vertexData) != len(mesh.vertices):
        raise ValueError('Binary 3DO vertex metadata count must match its vertices')
    for value in vertexData:
        pack('I', value)
    for index, face in enumerate(mesh.faces):
        data = _metadata(face.binaryData, 'face')
        textured = (all(value >= 0 for value in face.uvIdxs) if face.uvIdxs
                    else bool(data.get('texturePointer')))
        material = face.materialIdx >= 0
        pack('9I', data.get('id', index), int(face.type), int(face.geometryMode), int(face.lightMode),
             int(face.textureMode), len(face.vertexIdxs), data.get('unknown1', 0),
             _presence(data, 'texturePointer', textured), _presence(data, 'materialPointer', material))
        output.extend(_opaque(data, 'unknown2', 12))
        pack('f', (face.color[0] + face.color[1] + face.color[2]) / 3.0)
        output.extend(_opaque(data, 'unknown3', 12))
        pack('3f', *face.normal)
        for value in face.vertexIdxs:
            pack('I', value)
        if textured:
            for value in face.uvIdxs:
                pack('I', value)
        if material:
            pack('I', face.materialIdx)
    for normal in mesh.normals:
        pack('3f', *normal)
    pack('2If', mesh.shadow if mesh.shadow is not None else 0, metadata.get('unknown3', 0), mesh.radius)
    output.extend(_opaque(metadata, 'bounds', 24))


def _write_node(output, pack, node, depth):
    metadata = _metadata(node.binaryData, 'node')
    output.extend(_write_name(node.name, kBinary3doNodeNameSize, metadata.get('nameBytes')))
    pack('IIIi5I', int(node.flags), metadata.get('unknown1', 0), int(node.type), node.meshIdx, depth,
         _presence(metadata, 'parentPointer', node.parentIdx >= 0), node.numChildren,
         _presence(metadata, 'childPointer', node.firstChildIdx >= 0),
         _presence(metadata, 'siblingPointer', node.siblingIdx >= 0))
    pack('3f', *node.pivot)
    pack('3f', *node.position)
    pack('3f', *node.rotation)
    output.extend(_opaque(metadata, 'transform', 48))
    for index in (node.parentIdx, node.firstChildIdx, node.siblingIdx):
        if index >= 0:
            pack('I', index)
