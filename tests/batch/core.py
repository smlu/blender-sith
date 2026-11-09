"""Batch resource parse/write/parse checks; requires Python and NumPy, not Blender."""
from pathlib import Path
import struct
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from batch.common import (UnsupportedResource, arguments, differences, key_snapshot,
                          model_snapshot, run)
from sith.key.keyLoader import loadKey
from sith.key.keyWriter import saveKey
from sith.key.key import KeyFileFormat
from sith.key.keyBinary import validateBinaryKey
from sith.key.keyValidation import validateKeyForTarget
from sith.material import mat
from sith.material.cmp import ColorMap
from sith.model.model3doLoader import load3do
from sith.model.model3doWriter import save3do


def reference_pixels(raw, width, height, info, palette, transparent_index=None):
    """Independent channel-array oracle, with explicit little-endian word sizes."""
    if info.bpp == 8 or info.color_mode == 0:
        if palette is None:
            raise UnsupportedResource('Indexed MAT requires an explicit or default CMP palette')
        rgb = np.asarray(palette.palette, dtype=np.uint8)[np.frombuffer(raw, np.uint8)]
        alpha = np.full((len(rgb), 1), 255, dtype=np.uint8)
        if transparent_index is not None:
            alpha[np.frombuffer(raw, np.uint8) == transparent_index] = 0
        values = np.concatenate((rgb, alpha), axis=1).astype(float) / 255
    else:
        bytes_per_pixel = info.bpp // 8
        octets = np.frombuffer(raw, dtype=np.uint8).reshape(-1, bytes_per_pixel)
        words = sum(octets[:, i].astype(np.uint32) << (8 * i) for i in range(bytes_per_pixel))
        channels = []
        for name in ('red', 'green', 'blue', 'alpha'):
            bits, shift = (getattr(info, name + suffix) for suffix in ('_bpp', '_shl'))
            if not bits:
                channel = np.full(len(words), 1.0 if name == 'alpha' else 0.0)
            else:
                channel = ((words >> shift) % (1 << bits)).astype(float) / ((1 << bits) - 1)
            channels.append(channel)
        values = np.column_stack(channels)
    return values.reshape(height, width, 4)[::-1].reshape(-1)


def read_material(path, palette):
    """Compare every decoded mip level against independent raw-byte decoding."""
    expected_cels = []
    with path.open('rb') as stream:
        header = mat._read_header(stream)
        records = mat._read_records(stream, header)
        if header.type == mat.MatType.Color:
            if palette is None:
                raise UnsupportedResource('Palette-color MAT requires a CMP palette')
            for record in records:
                rgba = np.asarray((*palette.palette[record.color_index], 255), dtype=float) / 255
                expected_cels.append((mat.color_tex_width, mat.color_tex_height,
                                      [np.tile(rgba, mat.color_tex_width * mat.color_tex_height)], False))
            return header, expected_cels
        for cel_index in range(header.texture_count):
            start = stream.tell()
            width, height, transparent, _, transparent_color, levels = struct.unpack('<6i', stream.read(24))
            expected_levels = []
            for level in range(levels):
                w, h = max(1, width >> level), max(1, height >> level)
                raw = stream.read(w * h * header.color_info.bpp // 8)
                expected_levels.append(reference_pixels(raw, w, h, header.color_info, palette,
                                                       transparent_color if transparent else None))
            end = stream.tell()
            stream.seek(start)
            decoded = mat._read_mipmap(stream, header.color_info, palette)
            if stream.tell() != end:
                raise AssertionError(f'Cel {cel_index}: decoder consumed a different number of bytes')
            for level, expected in enumerate(expected_levels):
                np.testing.assert_allclose(decoded.pixel_data_array[level], expected, atol=1e-7, rtol=0)
            expected_cels.append((width, height, expected_levels, decoded.transparent))
    return header, expected_cels


def check(path, target, options):
    extension = path.suffix.lower()
    if extension == '.3do':
        source, version = load3do(path)
        save3do(source, target, version, 'Local corpus verification')
        restored, restored_version = load3do(target)
        result = {'operation': 'parse-write-parse', 'differences':
                differences(model_snapshot(source), model_snapshot(restored), 'model') +
                differences(version.value, restored_version.value, 'version')}
        if version.value == 'LDOM':
            result['byte_identical'] = path.read_bytes() == target.read_bytes()
            if not result['byte_identical']:
                result['differences'].append('Binary MODL serialization changed original bytes')
        return result
    if extension == '.key':
        source = loadKey(path)
        requested = getattr(options, 'key_target', 'CUSTOM')
        if source.fileFormat == KeyFileFormat.GrimBinary and requested == 'CUSTOM':
            validateBinaryKey(source)
        else:
            validateKeyForTarget(source, requested)
        saveKey(source, target, 'Local corpus verification', fileFormat=source.fileFormat)
        expected = key_snapshot(source)
        expected_markers = (sorted(expected['markers'], key=lambda marker: marker[0])
                            if source.fileFormat == KeyFileFormat.Text else expected['markers'])
        marker_order_changed = expected['markers'] != expected_markers
        expected['markers'] = expected_markers
        result = {'operation': 'parse-write-parse', 'differences':
                differences(expected, key_snapshot(loadKey(target)), 'key', atol=1e-7),
                'source_marker_order_corrected': marker_order_changed}
        if source.fileFormat == KeyFileFormat.GrimBinary:
            result['byte_identical'] = path.read_bytes() == target.read_bytes()
            if not result['byte_identical']:
                result['differences'].append('Binary FYEK serialization changed original bytes')
        return result
    if extension == '.cmp':
        palette = ColorMap.load(path)
        raw = path.read_bytes()[64:64 + 768]
        np.testing.assert_array_equal(np.asarray(palette.palette), np.frombuffer(raw, np.uint8).reshape(256, 3))
        return {'operation': 'decode-reference', 'palette_entries': 256}
    palette = ColorMap.load(options.palette_path) if options.palette_path else None
    header, cels = read_material(path, palette)
    return {'operation': 'decode-reference', 'cels': len(cels),
            'mipmap_levels': sum(len(cel[2]) for cel in cels), 'bpp': header.color_info.bpp}


if __name__ == '__main__':
    raise SystemExit(run(arguments(__doc__), check))
