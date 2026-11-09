# SPDX-FileCopyrightText: 2026 Crt Vavros
# SPDX-License-Identifier: GPL-3.0-or-later
"""MAT texture encoding, independent of Blender and its shader graph."""
import operator
from typing import NamedTuple

import numpy as np

from .mat import ColorFormat, ColorMode, MatType, cf_serf, file_magic, required_version, mh_serf, mtr_serf, mmm_serf

kMatEncodings = (
    ('RGBA32', 'RGBA32', '32-bit color with 8-bit alpha'),
    ('RGB24', 'RGB 24', '24-bit color without alpha'),
    ('RGB565', 'RGB 565', '16-bit color without alpha'),
    ('RGBA4444', 'RGBA 4444', '16-bit color with 4-bit alpha'),
    ('RGBA1555', 'RGBA 1555', '16-bit color with 1-bit alpha'),
    ('INDEXED', 'Indexed', '8-bit indices into the selected CMP palette; 1-bit transparency'),
)


class MatCel(NamedTuple):
    width: int
    height: int
    pixels: object  # Flat or HxWx4 normalized RGBA, bottom row first like Blender.


def _format(mode, bpp, bits, shifts):
    r, g, b, a = bits
    rs, gs, bs, als = shifts
    return ColorFormat(mode, bpp, r, g, b, rs, gs, bs,
                       8 - r if r else 0, 8 - g if g else 0, 8 - b if b else 0,
                       a, als, 8 - a if a else 0)


kMatColorFormats = {
    'RGBA32': _format(ColorMode.RGBA, 32, (8, 8, 8, 8), (16, 8, 0, 24)),
    'RGB24': _format(ColorMode.RGB, 24, (8, 8, 8, 0), (16, 8, 0, 0)),
    'RGB565': _format(ColorMode.RGB, 16, (5, 6, 5, 0), (11, 5, 0, 0)),
    'RGBA4444': _format(ColorMode.RGBA, 16, (4, 4, 4, 4), (8, 4, 0, 12)),
    'RGBA1555': _format(ColorMode.RGBA, 16, (5, 5, 5, 1), (10, 5, 0, 15)),
    'INDEXED': _format(ColorMode.Indexed, 8, (0, 0, 0, 0), (0, 0, 0, 0)),
}


def _dimension(value):
    try:
        value = operator.index(value)
    except TypeError as error:
        raise ValueError('MAT dimensions must be integers') from error
    if not 1 <= value <= 0x7fffffff:
        raise ValueError('MAT dimensions must be positive signed 32-bit values')
    return value


def _area_reduce(data, size, axis):
    """Integrate pixel areas, including odd-sized edges rather than dropping them."""
    values = np.moveaxis(data, axis, 0)
    length = len(values)
    positions = np.linspace(0, length, size + 1)
    indices = positions.astype(np.intp)
    prefix = np.concatenate((np.zeros_like(values[:1]), np.cumsum(values, axis=0)), axis=0)
    fractions = (positions - indices).reshape((-1,) + (1,) * (values.ndim - 1))
    integral = prefix[indices] + fractions * values[np.minimum(indices, length - 1)]
    reduced = np.diff(integral, axis=0) / (length / size)
    return np.moveaxis(reduced, 0, axis)


def _next_mip(pixels, alpha):
    data = pixels.copy()
    if alpha:
        data[..., :3] *= data[..., 3:4]
    data = _area_reduce(data, max(1, len(data) // 2), 0)
    data = _area_reduce(data, max(1, data.shape[1] // 2), 1)
    if alpha:
        # Transparent RGB must not bleed into the visible edge of smaller mips.
        np.divide(data[..., :3], data[..., 3:4], out=data[..., :3], where=data[..., 3:4] > 0)
    return np.clip(data, 0, 1)


def _palette(palette):
    if palette is None:
        raise ValueError('Indexed MAT encoding requires a CMP palette')
    values = np.asarray(getattr(palette, 'palette', palette))
    if (values.shape != (256, 3) or values.dtype.kind not in 'iuf'
            or not np.isfinite(values).all() or np.any(values < 0) or np.any(values > 255)
            or np.any(values != np.floor(values))):
        raise ValueError('CMP palette must contain 256 RGB byte triples')
    return values.astype(np.float32)


def _indexed(pixels, palette, transparent):
    rgb = np.floor(pixels[..., :3] * 255 + 0.5).astype(np.uint8).reshape((-1, 3))
    colors, inverse = np.unique(rgb, axis=0, return_inverse=True)
    first = 1 if transparent else 0
    nearest = np.empty(len(colors), dtype=np.uint8)
    # Bound scratch memory independently of the image dimensions. Repeated
    # colors share one search; equal distances choose the lowest palette index.
    for offset in range(0, len(colors), 2048):
        delta = colors[offset:offset + 2048].astype(np.float32)[:, None, :] - palette[None, first:, :]
        nearest[offset:offset + 2048] = np.argmin(np.sum(delta * delta, axis=2), axis=1) + first
    indices = nearest[inverse].reshape(pixels.shape[:2])
    if transparent:
        indices[pixels[..., 3] < 0.5] = 0
    return np.flip(indices, axis=0).tobytes()


def _packed(pixels, info):
    words = np.zeros(pixels.shape[:2], dtype=np.uint32)
    for channel, bits, shift in zip(range(4),
                                    (info.red_bpp, info.green_bpp, info.blue_bpp, info.alpha_bpp),
                                    (info.red_shl, info.green_shl, info.blue_shl, info.alpha_shl)):
        if bits:
            quantized = np.floor(pixels[..., channel] * ((1 << bits) - 1) + 0.5).astype(np.uint32)
            words |= quantized << shift
    words = np.flip(words, axis=0)
    if info.bpp == 24:
        return words.astype('<u4').view(np.uint8).reshape((-1, 4))[:, :3].tobytes()
    return words.astype('<u2' if info.bpp == 16 else '<u4').tobytes()


def encodeMat(cels, encoding='RGBA32', palette=None, *, generateMipmaps=True, grim=False):
    """Encode editable cel pixels, not Blender shaders. HDR values clamp to [0,1].

    Every input cel uses normalized numeric channels in the decoder's domain.
    Packed fields round to nearest. Indexed output quantizes RGB to bytes, then
    chooses the nearest CMP entry in RGB space without dithering. Alpha below
    0.5 uses reserved palette index zero; opaque pixels cannot reuse that index.
    """
    if encoding not in kMatColorFormats:
        raise ValueError(f'Unknown MAT encoding: {encoding}')
    if grim and encoding != 'INDEXED':
        raise ValueError('Grim Fandango MAT textures require Indexed encoding')
    cels = list(cels)
    if not 1 <= len(cels) <= 0x7fffffff:
        raise ValueError('MAT requires at least one texture cel')
    info = kMatColorFormats[encoding]
    colors = _palette(palette) if encoding == 'INDEXED' else None
    output = bytearray(mh_serf.pack(file_magic, required_version,
                                  MatType.GrimTexture if grim else MatType.Texture, len(cels), len(cels)))
    output.extend(cf_serf.pack(*info))
    for index in range(len(cels)):
        # Match rdMaterial_Write's texture record, including its unit scalar.
        output.extend(mtr_serf.pack(8, 0, 0, 0, 0, 0x3f800000, 0, 0, 0, index))
    for cel in cels:
        width, height = _dimension(cel.width), _dimension(cel.height)
        if np.iscomplexobj(cel.pixels):
            raise ValueError('MAT pixels must be real RGBA values')
        pixels = np.asarray(cel.pixels, dtype=np.float64)
        if pixels.size != width * height * 4 or not np.isfinite(pixels).all():
            raise ValueError('MAT cel must contain finite RGBA pixels matching its dimensions')
        pixels = np.clip(pixels.reshape((height, width, 4)), 0, 1)
        transparent = encoding == 'INDEXED' and bool(np.any(pixels[..., 3] < 0.5))
        levels = [pixels]
        # Grim readers advance to the next cel directly after its base pixels.
        if generateMipmaps and not grim:
            while levels[-1].shape[0] > 1 or levels[-1].shape[1] > 1:
                levels.append(_next_mip(levels[-1], encoding == 'INDEXED' or info.alpha_bpp > 0))
        output.extend(mmm_serf.pack(width, height, int(transparent), 0, 0, len(levels)))
        for level in levels:
            output.extend(_indexed(level, colors, transparent) if colors is not None else _packed(level, info))
    return bytes(output)
