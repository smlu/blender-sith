import contextlib
import io
from pathlib import Path
import struct
import tempfile
import unittest

import numpy as np

from fixtures import (INDEX8, RGB565, RGB24, RGBA32, RGBA4444, RGBA1555,
                      cmp_bytes, mat_bytes)
from sith.material.cmp import ColorMap
from sith.material import mat


def read_mat(data, palette=None):
    stream = io.BytesIO(data)
    header = mat._read_header(stream)
    records = mat._read_records(stream, header)
    mipmaps = [mat._read_mipmap(stream, header.color_info, palette)
               for _ in range(header.texture_count)]
    return header, records, mipmaps, stream


class ColorMapTests(unittest.TestCase):
    def load(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'palette.cmp'
            path.write_bytes(data)
            return ColorMap.load(path)

    def test_both_supported_versions_and_palette_endpoints(self):
        for version in (0x14, 0x1e):
            for alpha in (False, True):
                with self.subTest(version=version, alpha=alpha):
                    palette = self.load(cmp_bytes(version, alpha))
                    self.assertEqual(len(palette.palette), 256)
                    for i in range(256):
                        self.assertEqual(palette.palette[i], (i, 255 - i, i // 2))

    def test_invalid_signature_and_version(self):
        data = cmp_bytes()
        for invalid in (b'BAD ' + data[4:], data[:4] + struct.pack('<i', 999) + data[8:]):
            with self.subTest(prefix=invalid[:8]), self.assertRaises(ImportError):
                self.load(invalid)

    def test_truncated_header_and_palette(self):
        for count in (0, 4, 63, 64, 64 + 3, 64 + 765, 64 + 767):
            label = 'header' if count < 64 else 'palette'
            with self.subTest(count=count), self.assertRaisesRegex(ImportError, 'Truncated CMP ' + label):
                self.load(cmp_bytes()[:count])

    def test_every_truncated_header_reports_an_import_error(self):
        for version in (0x14, 0x1e):
            data = cmp_bytes(version)
            for count in range(64):
                with self.subTest(version=version, count=count):
                    with self.assertRaisesRegex(ImportError, 'Truncated CMP header'):
                        self.load(data[:count])

    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ImportError):
            ColorMap.load(Path(directory) / 'missing.cmp')


class MatCodecTests(unittest.TestCase):
    def palette(self):
        value = ColorMap()
        value.palette = [(i, 255 - i, i // 2) for i in range(256)]
        return value

    def assert_pixels(self, pixels, expected):
        np.testing.assert_allclose(np.asarray(pixels).reshape(-1, 4),
                                   np.asarray(expected) / 255, atol=1e-7)

    def test_rgba32_channels_alpha_and_vertical_flip(self):
        header, records, mipmaps, stream = read_mat(mat_bytes())
        self.assertEqual((header.type, header.record_count, header.texture_count), (2, 1, 1))
        self.assertEqual(records[0].cel_idx, 0)
        self.assertEqual((mipmaps[0].width, mipmaps[0].height), (2, 2))
        self.assert_pixels(mipmaps[0].pixel_data_array[0],
                           [(0, 0, 255, 0), (255, 255, 255, 255),
                            (255, 0, 0, 255), (0, 255, 0, 128)])
        self.assertEqual(stream.read(), b'')

    def test_packed_rgb_formats_have_independent_expected_colors(self):
        cases = (
            (RGB565, struct.pack('<4H', 0xf800, 0x07e0, 0x001f, 0xffff),
             [(0, 0, 255, 255), (255, 255, 255, 255), (255, 0, 0, 255), (0, 255, 0, 255)]),
            (RGB24, bytes((255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255)),
             [(0, 0, 255, 255), (255, 255, 255, 255), (255, 0, 0, 255), (0, 255, 0, 255)]),
            (RGBA4444, struct.pack('<4H', 0xff00, 0x80f0, 0x000f, 0xffff),
             [(0, 0, 255, 0), (255, 255, 255, 255), (255, 0, 0, 255), (0, 255, 0, 136)]),
            (RGBA1555, struct.pack('<4H', 0xfc00, 0x83e0, 0x001f, 0xffff),
             [(0, 0, 255, 0), (255, 255, 255, 255), (255, 0, 0, 255), (0, 255, 0, 255)]))
        for fmt, raw, expected in cases:
            with self.subTest(fmt=fmt):
                _, _, mipmaps, _ = read_mat(mat_bytes(fmt, [(2, 2, [raw], False, 0)]))
                self.assert_pixels(mipmaps[0].pixel_data_array[0], expected)

    def test_every_packed_16bit_value_uses_full_channel_normalization(self):
        # Independent bit layouts and all 65,536 words prevent endpoint-only
        # tests from hiding errors in intermediate colors or alpha levels.
        words = np.arange(65536, dtype='<u2')
        cases = ((RGB565, ((5, 11), (6, 5), (5, 0), None)),
                 (RGBA4444, ((4, 8), (4, 4), (4, 0), (4, 12))),
                 (RGBA1555, ((5, 10), (5, 5), (5, 0), (1, 15))))
        for fmt, layout in cases:
            with self.subTest(fmt=fmt):
                _, _, images, _ = read_mat(mat_bytes(fmt, [(256, 256, [words.tobytes()], False, 0)]))
                decoded = np.flip(np.asarray(images[0].pixel_data_array[0]).reshape(256, 256, 4), axis=0).reshape(-1, 4)
                for index, component in enumerate(layout):
                    if component is None:
                        expected = np.ones(65536)
                    else:
                        bits, shift = component
                        expected = ((words >> shift) & ((1 << bits) - 1)).astype(np.float64) / ((1 << bits) - 1)
                    np.testing.assert_allclose(decoded[:, index], expected, rtol=0, atol=1e-15)

    def test_invalid_packed_channel_layout_is_rejected(self):
        for bits, shift in ((17, 0), (5, 12)):
            with self.subTest(bits=bits, shift=shift):
                invalid = list(RGB565)
                invalid[2], invalid[5] = bits, shift
                with self.assertRaisesRegex(ImportError, 'channel layout'):
                    read_mat(mat_bytes(invalid, [(1, 1, [b'\xff\xff'], False, 0)]))

    def test_indexed_palette_and_transparent_color(self):
        data = mat_bytes(INDEX8, [(2, 2, [bytes((0, 1, 2, 255))], True, 2)])
        _, _, mipmaps, _ = read_mat(data, self.palette())
        self.assertTrue(mipmaps[0].transparent)
        self.assert_pixels(mipmaps[0].pixel_data_array[0],
                           [(2, 253, 1, 0), (255, 0, 127, 255),
                            (0, 255, 0, 255), (1, 254, 0, 255)])

    def test_all_palette_indices(self):
        data = mat_bytes(INDEX8, [(256, 1, [bytes(range(256))], False, 0)])
        _, _, mipmaps, _ = read_mat(data, self.palette())
        self.assert_pixels(mipmaps[0].pixel_data_array[0],
                           [(i, 255 - i, i // 2, 255) for i in range(256)])

    def test_square_and_rectangular_mipmap_chains(self):
        for width, height in ((4, 4), (4, 2), (1, 4)):
            levels = [bytes((20 + i, 30, 40, 255)) *
                      (max(1, width >> i) * max(1, height >> i)) for i in range(3)]
            data = mat_bytes(RGBA32, [(width, height, levels, False, 0)])
            with self.subTest(size=(width, height)):
                _, _, mipmaps, stream = read_mat(data)
                for i, pixels in enumerate(mipmaps[0].pixel_data_array):
                    count = max(1, width >> i) * max(1, height >> i)
                    self.assert_pixels(pixels, [(20 + i, 30, 40, 255)] * count)
                self.assertEqual(stream.read(), b'')

    def test_multiple_cels_preserve_stream_alignment(self):
        data = mat_bytes(INDEX8, [(2, 2, [bytes((0, 1, 2, 3))], False, 0),
                                  (1, 1, [b'\x07'], True, 7)])
        _, records, mipmaps, stream = read_mat(data, self.palette())
        self.assertEqual([record.cel_idx for record in records], [0, 1])
        self.assertEqual([(mm.width, mm.height) for mm in mipmaps], [(2, 2), (1, 1)])
        self.assertEqual([mm.transparent for mm in mipmaps], [False, True])
        self.assertEqual(stream.read(), b'')

    def test_missing_palette_still_consumes_all_cels(self):
        data = mat_bytes(INDEX8, [(2, 2, [b'\0' * 4], False, 0),
                                  (1, 1, [b'\1'], True, 1)])
        with contextlib.redirect_stdout(io.StringIO()):
            _, _, mipmaps, stream = read_mat(data)
        self.assertEqual([(mm.width, mm.height) for mm in mipmaps], [(2, 2), (1, 1)])
        self.assertTrue(all(mm.pixel_data_array is None for mm in mipmaps))
        self.assertEqual(stream.read(), b'')

    def test_color_records(self):
        data = mat_bytes(INDEX8, color_indices=[0, 17, 255])
        header, records, mipmaps, _ = read_mat(data)
        self.assertEqual(header.type, mat.MatType.Color)
        self.assertEqual([r.color_index for r in records], [0, 17, 255])
        self.assertEqual(mipmaps, [])

    def test_invalid_header_fields(self):
        original = mat_bytes()
        for offset, value in ((4, 0), (8, 99), (12, 0), (12, -1),
                              (16, 2), (20, 99), (24, 0), (24, 12), (24, 40)):
            data = bytearray(original)
            struct.pack_into('<i', data, offset, value)
            with self.subTest(offset=offset, value=value), self.assertRaises(ImportError):
                read_mat(data)
        with self.assertRaises(ImportError):
            read_mat(b'BAD ' + original[4:])

    def test_truncated_header_records_and_pixels(self):
        data = mat_bytes()
        for size in (0, 4, 19, 75, 76, 100, 115, 116, 139, len(data) - 1):
            with self.subTest(size=size), self.assertRaises((ImportError, struct.error, ValueError)):
                read_mat(data[:size])

    def test_invalid_mipmap_dimensions_levels_and_transparency_index(self):
        original = mat_bytes(INDEX8, [(2, 2, [b'\0' * 4], True, 0)])
        for offset, value in ((116, 0), (116, -1), (120, 0), (120, -2),
                              (132, 256), (132, -1), (136, 0), (136, -1), (136, 99)):
            data = bytearray(original)
            struct.pack_into('<i', data, offset, value)
            with self.subTest(offset=offset, value=value), self.assertRaises(ImportError):
                read_mat(data, self.palette())

    def test_color_masks_sizes_and_cel_names(self):
        """Packed layout helpers use byte sizes, not platform-native word widths."""
        for bits in (0, 1, 4, 5, 6, 8, 16, 32):
            self.assertEqual(mat._get_color_mask(bits), (1 << bits) - 1)
        for bpp in (8, 16, 24, 32):
            self.assertEqual(mat._get_pixel_data_size(4, 2, bpp), bpp)
        self.assertEqual(mat._get_tex_name(0, 'test.mat'), 'test')
        self.assertEqual(mat._get_tex_name(3, 'test.mat'), 'test_cel_3')

    def test_huge_dimensions_with_missing_pixels_are_rejected_before_allocation(self):
        data = mat_bytes(RGBA32, [(0x7fffffff, 0x7fffffff, [b''], False, 0)])
        with self.assertRaisesRegex(ImportError, 'Truncated'):
            read_mat(data)

    def test_palette_is_not_mutated_when_transparency_changes(self):
        palette = self.palette()
        original = list(palette.palette)
        data = mat_bytes(INDEX8, [(1, 1, [b'\x07'], True, 7)])
        read_mat(data, palette)
        self.assertEqual(palette.palette, original)
