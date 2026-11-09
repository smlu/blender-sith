# SPDX-FileCopyrightText: 2026 Crt Vavros
# SPDX-License-Identifier: GPL-3.0-or-later
"""Grim Fandango FYEK resources, with opaque fields retained for round trips."""
import copy
import operator
import struct

from .key import Key, KeyFileFormat, KeyFlag, KeyNode, Keyframe, KeyframeFlag, KeyMarker, KeyMarkerType
from ..model import Mesh3doNodeType
from ..types import Vector3f
from ..types.vector import validateFloat32

kBinaryKeyMagic = b'FYEK'
kBinaryKeyHeaderSize = 136
kBinaryKeyNameSize = 36
kBinaryKeyNodeNameSize = 32
kBinaryKeyMaxMarkers = 8
kGrimKeyNoInterpolation = 0x100
_prefix = struct.Struct('<4s36s3If4I')
_node = struct.Struct('<32s3I')
_entry = struct.Struct('<fI12f')


def _integer(value, label, signed=False):
    try:
        value = operator.index(value)
    except TypeError as error:
        raise ValueError(f'Binary KEY {label} must be an integer') from error
    low, high = (-(1 << 31), (1 << 31) - 1) if signed else (0, (1 << 32) - 1)
    if not low <= value <= high:
        raise ValueError(f'Binary KEY {label} is outside its 32-bit field')
    return value


def _metadata(value):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError('Invalid binary KEY metadata')
    return value


def _bytes(metadata, name, size):
    try:
        raw = bytes.fromhex(metadata[name]) if name in metadata else bytes(size)
    except (TypeError, ValueError) as error:
        raise ValueError(f'Invalid binary KEY {name} metadata') from error
    if len(raw) != size:
        raise ValueError(f'Binary KEY {name} requires {size} bytes')
    return raw


def _name(raw):
    try:
        value = raw.split(b'\0', 1)[0].decode('ascii')
    except UnicodeDecodeError as error:
        raise ValueError('Binary KEY names must be ASCII') from error
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError('Binary KEY names cannot contain control characters')
    return value


def _write_name(value, size, metadata):
    if not isinstance(value, str) or '\0' in value:
        raise ValueError('Binary KEY names must be strings without embedded NULs')
    try:
        raw = value.encode('ascii')
    except UnicodeEncodeError as error:
        raise ValueError('Binary KEY names must be ASCII') from error
    _name(raw)
    if len(raw) > size:
        raise ValueError(f'Binary KEY name {value!r} exceeds its {size}-byte field')
    if 'nameBytes' in metadata:
        original = _bytes(metadata, 'nameBytes', size)
        if _name(original) == value:
            return original
    return raw.ljust(size, b'\0')


def validateBinaryKey(key):
    """Validate physical fields independently of text-engine name restrictions."""
    _write_name(key.name, kBinaryKeyNameSize, _metadata(key.binaryData))
    for name in ('numFrames', 'numJoints', 'flags', 'nodeTypes'):
        _integer(getattr(key, name), name)
    validateFloat32((key.fps,), 'Binary KEY FPS')
    if key.fps <= 0:
        raise ValueError('Binary KEY FPS must be positive')
    if len(key.markers) > kBinaryKeyMaxMarkers:
        raise ValueError('Binary KEY supports at most 8 markers')
    for marker in key.markers:
        validateFloat32((marker.frame,), 'Binary KEY marker frame')
        _integer(marker.type, 'marker type', signed=True)
    seen = set()
    for node in key.nodes:
        _integer(node.idx, 'joint index')
        if node.idx >= key.numJoints or node.idx in seen:
            raise ValueError('Binary KEY joint index is out of range or duplicated')
        seen.add(node.idx)
        _write_name(node.meshName, kBinaryKeyNodeNameSize, _metadata(node.binaryData))
        for entry in node.keyframes:
            validateFloat32((entry.frame,), 'Binary KEY entry frame')
            if entry.frame < 0:
                raise ValueError('Binary KEY entry frames must be nonnegative')
            _integer(entry.flags, 'entry flags')
            for vector in (entry.position, entry.orientation, entry.deltaPosition, entry.deltaRotation):
                if len(vector) != 3:
                    raise ValueError('Binary KEY transforms require three components')
                validateFloat32(vector, 'Binary KEY transform')


def readBinaryKey(data, *, allowErrors=False, warnings=None):
    """Decode a complete FYEK file; null duplicate records are not extra joints."""
    if len(data) < kBinaryKeyHeaderSize:
        raise ValueError('Truncated binary KEY header')
    magic, raw_name, flags, duplicate, types, fps, frames, joints, unknown, count = _prefix.unpack_from(data)
    if magic != kBinaryKeyMagic:
        raise ValueError('Invalid binary KEY magic; expected FYEK')
    if count > kBinaryKeyMaxMarkers:
        raise ValueError('Binary KEY marker count exceeds its 8 slots')
    if joints > (len(data) - kBinaryKeyHeaderSize) // _node.size:
        raise ValueError('Binary KEY joint count exceeds the remaining file')
    key = Key(_name(raw_name))
    key.fileFormat = KeyFileFormat.GrimBinary
    key.flags, key.nodeTypes = KeyFlag(flags), Mesh3doNodeType(types)
    key.fps, key.numFrames, key.numJoints = fps, frames, joints
    key.binaryData = {'nameBytes': raw_name.hex(), 'duplicateJoints': duplicate,
                      'originalJoints': joints, 'originalFrames': frames, 'unknown': unknown,
                      'markerSlots': bytes(data[72:136]).hex(), 'records': []}
    for index in range(count):
        marker = KeyMarker()
        marker.frame, = struct.unpack_from('<f', data, 72 + index * 4)
        kind, = struct.unpack_from('<i', data, 104 + index * 4)
        marker.type = KeyMarkerType(kind) if kind in KeyMarkerType._value2member_map_ else kind
        key.markers.append(marker)

    # A record exists for every joint slot, even though null placeholders may
    # repeat joint zero. Keep those empty records and their padding verbatim.
    offset = kBinaryKeyHeaderSize
    seen = set()
    for _ in range(joints):
        if _node.size > len(data) - offset:
            raise ValueError('Truncated binary KEY node')
        raw_header = bytes(data[offset:offset + _node.size])
        raw_name, index, entries, pointer = _node.unpack(raw_header)
        offset += _node.size
        if index >= joints or entries > (len(data) - offset) // _entry.size:
            raise ValueError('Binary KEY joint index or entry count exceeds the file')
        duplicate_node = index in seen
        if duplicate_node and (entries or any(raw_name)):
            raise ValueError('Binary KEY contains a nonempty duplicate joint')
        record = {'index': index, 'duplicate': duplicate_node,
                  'empty': raw_header.hex() if entries == 0 else None}
        key.binaryData['records'].append(record)
        if duplicate_node:
            continue
        seen.add(index)
        node = KeyNode()
        node.idx, node.meshName = index, _name(raw_name)
        node.binaryData = {'nameBytes': raw_name.hex(), 'unknown': pointer}
        key.nodes.append(node)
        for _ in range(entries):
            values = _entry.unpack_from(data, offset)
            offset += _entry.size
            entry = Keyframe()
            entry.frame, entry.flags = values[:2]
            entry.position, entry.orientation, entry.deltaPosition, entry.deltaRotation = (
                Vector3f(*values[start:start + 3]) for start in (2, 5, 8, 11))
            node.keyframes.append(entry)
    if offset != len(data):
        raise ValueError('Binary KEY contains trailing data')
    if allowErrors:
        from .keyRecovery import recoverKey
        recoverKey(key, warnings)
    validateBinaryKey(key)
    return key


def encodeBinaryKey(key):
    """Build and validate all bytes before the writer opens its destination."""
    validateBinaryKey(key)
    metadata = _metadata(key.binaryData)
    duplicate = metadata.get('duplicateJoints', key.numJoints)
    if metadata.get('originalJoints', key.numJoints) != key.numJoints:
        duplicate = key.numJoints
    output = bytearray(_prefix.pack(
        kBinaryKeyMagic, _write_name(key.name, kBinaryKeyNameSize, metadata),
        key.flags, _integer(duplicate, 'duplicate joint count'), key.nodeTypes,
        key.fps, key.numFrames, key.numJoints, _integer(metadata.get('unknown', 0), 'unknown field'), len(key.markers)))
    slots = bytearray(_bytes(metadata, 'markerSlots', 64))
    for index, marker in enumerate(key.markers):
        struct.pack_into('<f', slots, index * 4, marker.frame)
        struct.pack_into('<i', slots, 32 + index * 4, marker.type)
    output.extend(slots)
    nodes = {node.idx: node for node in key.nodes}
    records = metadata.get('records')
    if records is not None and (not isinstance(records, list) or any(not isinstance(record, dict) for record in records)):
        raise ValueError('Invalid binary KEY record layout metadata')
    if records is not None:
        for record in records:
            _integer(record.get('index'), 'record index')
    if (records is None or len(records) != key.numJoints
            or not nodes.keys() <= {record.get('index') for record in records if not record.get('duplicate')}):
        records = [{'index': index} for index in range(key.numJoints)]
    emitted = set()
    for record in records:
        index = _integer(record.get('index'), 'record index')
        if index >= key.numJoints:
            raise ValueError('Invalid binary KEY record index')
        node = nodes.get(index)
        if record.get('duplicate') or node is None:
            if record.get('empty') is not None:
                raw = _bytes({'empty': record['empty']}, 'empty', _node.size)
                name, raw_index, count, _ = _node.unpack(raw)
                _name(name)
                if count or raw_index != index or (record.get('duplicate') and any(name)):
                    raise ValueError('Invalid binary KEY null record metadata')
                output.extend(raw)
            elif node is None:
                output.extend(_node.pack(bytes(kBinaryKeyNodeNameSize), index, 0, 0))
            else:
                raise ValueError('Missing binary KEY duplicate record metadata')
            continue
        if index in emitted:
            raise ValueError('Duplicate binary KEY record layout index')
        emitted.add(index)
        details = _metadata(node.binaryData)
        output.extend(_node.pack(_write_name(node.meshName, kBinaryKeyNodeNameSize, details),
                                 index, len(node.keyframes), _integer(details.get('unknown', 0), 'node unknown field')))
        for entry in node.keyframes:
            output.extend(_entry.pack(entry.frame, entry.flags, *entry.position, *entry.orientation,
                                      *entry.deltaPosition, *entry.deltaRotation))
    return bytes(output)


def keyForPlayback(key):
    """Adapt Grim's global interpolation rule without changing serialized data."""
    if key.fileFormat != KeyFileFormat.GrimBinary:
        return key
    result = copy.deepcopy(key)
    pose_only = key.numFrames == 0 and any(node.keyframes for node in key.nodes)
    if pose_only:
        # Blender needs a nonempty timeline to display a zero-duration pose.
        # Its original frame count remains in metadata for binary export.
        result.numFrames = 1
    interpolate = not (key.flags & kGrimKeyNoInterpolation) and not pose_only
    result.nodes = [node for node in result.nodes if node.keyframes]
    for node in result.nodes:
        # Grim's upper-bound search chooses the last entry at an equal frame.
        # Collapse only adjacent ties; do not sort or repair backwards timing.
        samples = []
        for entry in node.keyframes:
            if samples and entry.frame == samples[-1].frame:
                samples[-1] = entry
            else:
                samples.append(entry)
        node.keyframes = samples
        for entry in node.keyframes:
            entry.flags = KeyframeFlag.AllChange if interpolate else KeyframeFlag.NoChange
    return result


def prepareGrimExport(key):
    """Convert generated Sith channel holds to Grim's unconditional deltas."""
    result = copy.deepcopy(key)
    result.fileFormat = KeyFileFormat.GrimBinary
    for node in result.nodes:
        for entry in node.keyframes:
            if not entry.flags & KeyframeFlag.PositionChange:
                entry.deltaPosition = Vector3f(0, 0, 0)
            if not entry.flags & KeyframeFlag.OrientationChange:
                entry.deltaRotation = Vector3f(0, 0, 0)
            if result.flags & kGrimKeyNoInterpolation and any((*entry.deltaPosition, *entry.deltaRotation)):
                raise ValueError('Grim KEY flag 0x100 disables interpolation; use stepped animation or clear that flag')
    return result
