"""Synthetic on-disk bytes, built independently of the production codecs."""
from pathlib import Path
import struct

TV = Path(__file__).resolve().parent / 'tv'
INDEX8 = (0, 8, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
RGB565 = (1, 16, 5, 6, 5, 11, 5, 0, 3, 2, 3, 0, 0, 0)
RGB24 = (1, 24, 8, 8, 8, 0, 8, 16, 0, 0, 0, 0, 0, 0)
RGBA32 = (2, 32, 8, 8, 8, 0, 8, 16, 0, 0, 0, 8, 24, 0)
RGBA4444 = (2, 16, 4, 4, 4, 8, 4, 0, 4, 4, 4, 4, 12, 4)
RGBA1555 = (2, 16, 5, 5, 5, 10, 5, 0, 3, 3, 3, 1, 15, 0)


def packed_mat_cels():
    """Two 16-bit cels with endpoints/intermediate channels and a full mip chain."""
    return [(4, 2, [struct.pack('<8H', 0, 0xffff, 0x8410, 0x38e7, 0x7bef, 0x1234, 0x8000, 0x07e0),
                     struct.pack('<2H', 0x4567, 0xabcd), struct.pack('<H', 0xffff)], False, 0),
            (2, 1, [struct.pack('<2H', 0x1357, 0x9bdf), struct.pack('<H', 0x2468)], False, 0)]


def mat_bytes(color_format=RGBA32, cels=None, color_indices=None):
    """cels: (width, height, [raw level bytes], transparent, transparent_index)."""
    if cels is None:
        cels = [(2, 2, [bytes((255, 0, 0, 255, 0, 255, 0, 128,
                             0, 0, 255, 0, 255, 255, 255, 255))], False, 0)]
    is_color = color_indices is not None
    count = len(color_indices) if is_color else len(cels)
    data = struct.pack('<4siIii', b'MAT ', 0x32, 0 if is_color else 2,
                       count, 0 if is_color else count)
    data += struct.pack('<14I', *color_format)
    if is_color:
        return data + b''.join(struct.pack('<6i', 0, index, 0, 0, 0, 0)
                               for index in color_indices)
    data += b''.join(struct.pack('<10i', 2, 0, 0, 0, 0, 0, 0, 0, 0, i)
                     for i in range(count))
    for width, height, levels, transparent, transparent_index in cels:
        data += struct.pack('<6i', width, height, transparent, 0,
                            transparent_index, len(levels))
        data += b''.join(levels)
    return data


def cmp_bytes(version=0x1e, alpha=False):
    # Index i has a deliberately asymmetric color, including both endpoints.
    palette = bytes(channel for i in range(256) for channel in (i, 255 - i, i // 2))
    return struct.pack('<4sii52s', b'CMP ', version, alpha, b'\0' * 52) + palette
