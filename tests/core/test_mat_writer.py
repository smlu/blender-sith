"""Independent MAT layout, quantization, transparency and mip-chain expectations."""
import io
import struct
import unittest

import numpy as np

from sith.material import mat
from sith.material.cmp import ColorMap, CmpPaletteRGB
from sith.material.matWriter import MatCel, encodeMat, kMatColorFormats


def palette():
    value = ColorMap()
    value.palette = [CmpPaletteRGB(index, index, index) for index in range(256)]
    return value


def decode(data, cmp=None):
    stream = io.BytesIO(data)
    header = mat._read_header(stream)
    records = mat._read_records(stream, header)
    cels = [mat._read_mipmap(stream, header.color_info, cmp) for _ in range(header.texture_count)]
    if stream.read():
        raise AssertionError('Unexpected trailing MAT data')
    return header, records, cels


def expected_pixels(pixels, encoding, cmp=None):
    """Small-image oracle independent of the writer's format and palette helpers."""
    values = np.clip(np.asarray(pixels, dtype=np.float64), 0, 1)
    if encoding == 'INDEXED':
        colors = np.asarray(cmp.palette, dtype=np.int64)
        transparent = bool(np.any(values[..., 3] < 0.5))
        first = int(transparent)
        result = np.empty_like(values)
        for index in np.ndindex(values.shape[:-1]):
            pixel = values[index]
            rgb = np.floor(pixel[:3] * 255 + 0.5).astype(np.int64)
            nearest = min(range(first, 256), key=lambda item: sum((int(a) - int(b)) ** 2
                          for a, b in zip(rgb, colors[item])))
            alpha = 0 if transparent and pixel[3] < 0.5 else 1
            result[index] = (*((colors[nearest] if alpha else colors[0]) / 255), alpha)
        return result
    bits = {'RGBA32': (8, 8, 8, 8), 'RGB24': (8, 8, 8, 0), 'RGB565': (5, 6, 5, 0),
            'RGBA4444': (4, 4, 4, 4), 'RGBA1555': (5, 5, 5, 1)}[encoding]
    result = np.ones_like(values)
    for channel, count in enumerate(bits):
        if count:
            maximum = (1 << count) - 1
            result[..., channel] = np.floor(values[..., channel] * maximum + 0.5) / maximum
    return result


class MatWriterTests(unittest.TestCase):
    def test_encoding_names_declare_the_expected_channel_layouts(self):
        expected = {
            'RGBA32': (32, (8, 8, 8, 8), (16, 8, 0, 24)),
            'RGB24': (24, (8, 8, 8, 0), (16, 8, 0, 0)),
            'RGB565': (16, (5, 6, 5, 0), (11, 5, 0, 0)),
            'RGBA4444': (16, (4, 4, 4, 4), (8, 4, 0, 12)),
            'RGBA1555': (16, (5, 5, 5, 1), (10, 5, 0, 15)),
        }
        for encoding, (bpp, bits, shifts) in expected.items():
            header = decode(encodeMat([MatCel(1, 1, [1, 1, 1, 1])], encoding))[0]
            info = header.color_info
            with self.subTest(encoding=encoding):
                self.assertEqual(info.bpp, bpp)
                self.assertEqual((info.red_bpp, info.green_bpp, info.blue_bpp, info.alpha_bpp), bits)
                self.assertEqual((info.red_shl, info.green_shl, info.blue_shl, info.alpha_shl), shifts)

    def test_header_records_row_order_and_little_endian_words(self):
        pixels = [(1, 0, 0, 1), (0, 1, 0, 1), (0, 0, 1, 1), (1, 1, 1, 1)]
        data = encodeMat([MatCel(2, 2, pixels)], generateMipmaps=False)
        self.assertEqual(struct.unpack_from('<4s4I', data), (b'MAT ', 50, 2, 1, 1))
        self.assertEqual(struct.unpack_from('<10I', data, 76), (8, 0, 0, 0, 0, 0x3f800000, 0, 0, 0, 0))
        self.assertEqual(struct.unpack_from('<6I', data, 116), (2, 2, 0, 0, 0, 1))
        self.assertEqual(data[140:], struct.pack('<4I', 0xff0000ff, 0xffffffff, 0xffff0000, 0xff00ff00))
        np.testing.assert_allclose(decode(data)[2][0].pixel_data_array[0], np.asarray(pixels).ravel())

    def test_all_packed_formats_round_to_their_actual_channel_precision(self):
        pixels = np.random.default_rng(951).random((3, 5, 4))
        pixels[0, 0], pixels[-1, -1] = 0, 1
        for encoding, info in kMatColorFormats.items():
            if encoding == 'INDEXED':
                continue
            with self.subTest(encoding=encoding):
                data = encodeMat([MatCel(5, 3, pixels)], encoding, generateMipmaps=False)
                header, _, cels = decode(data)
                self.assertEqual(header.color_info, info)
                actual = np.asarray(cels[0].pixel_data_array[0]).reshape((3, 5, 4))
                for axis, bits in enumerate((info.red_bpp, info.green_bpp, info.blue_bpp, info.alpha_bpp)):
                    expected = np.floor(pixels[..., axis] * ((1 << bits) - 1) + 0.5) / ((1 << bits) - 1) if bits else 1
                    np.testing.assert_allclose(actual[..., axis], expected, atol=1e-12)

    def test_rgb24_uses_exactly_three_bytes_per_pixel(self):
        data = encodeMat([MatCel(1, 1, [0.2, 0.4, 0.6, 0])], 'RGB24', generateMipmaps=False)
        self.assertEqual(data[140:], bytes((153, 102, 51)))
        self.assertEqual(len(data), 143)

    def test_every_16_bit_pixel_word_encodes_without_channel_loss(self):
        # Start from every possible stored word, not from production-decoded
        # pixels: even transparent texels must retain their RGB components.
        words = np.arange(65536, dtype=np.uint32).reshape((256, 256))
        formats = {'RGB565': ((5, 6, 5, 0), (11, 5, 0, 0)),
                   'RGBA4444': ((4, 4, 4, 4), (8, 4, 0, 12)),
                   'RGBA1555': ((5, 5, 5, 1), (10, 5, 0, 15))}
        for encoding, (bits, shifts) in formats.items():
            pixels = np.ones((256, 256, 4))
            for channel, (count, shift) in enumerate(zip(bits, shifts)):
                if count:
                    maximum = (1 << count) - 1
                    pixels[..., channel] = ((words >> shift) & maximum) / maximum
            with self.subTest(encoding=encoding):
                data = encodeMat([MatCel(256, 256, np.flip(pixels, axis=0))], encoding,
                                 generateMipmaps=False)
                self.assertEqual(data[140:], words.astype('<u2').tobytes())
                np.testing.assert_allclose(np.asarray(decode(data)[2][0].pixel_data_array[0])
                                           .reshape(pixels.shape), np.flip(pixels, axis=0), atol=1e-12)

    def test_rgb24_and_rgba32_store_every_channel_value_in_declared_byte_order(self):
        # Asymmetric channels and different rows catch swaps that grayscale,
        # black/white or opaque-alpha fixtures cannot expose.
        values = np.arange(256, dtype=np.uint16)
        pixels = np.empty((4, 256, 4), dtype=np.uint8)
        for row in range(4):
            pixels[row, :, 0] = (values + row * 17) % 256
            pixels[row, :, 1] = (values * 73 + row * 31 + 19) % 256
            pixels[row, :, 2] = (values * 151 + row * 43 + 37) % 256
            pixels[row, :, 3] = (values * 29 + row * 59 + 61) % 256
        for encoding, channels in (('RGB24', (2, 1, 0)), ('RGBA32', (2, 1, 0, 3))):
            with self.subTest(encoding=encoding):
                data = encodeMat([MatCel(256, 4, np.flip(pixels, axis=0) / 255)], encoding,
                                 generateMipmaps=False)
                self.assertEqual(data[140:], pixels[..., list(channels)].tobytes())
                expected = np.flip(pixels, axis=0).astype(np.float64) / 255
                if encoding == 'RGB24':
                    expected[..., 3] = 1
                np.testing.assert_allclose(np.asarray(decode(data)[2][0].pixel_data_array[0])
                                           .reshape(expected.shape), expected, atol=1e-12)

    def test_all_256_palette_values_and_both_alpha_states(self):
        values = np.arange(256) / 255
        pixels = np.column_stack((values, values, values, np.ones(256)))
        for grim in (False, True):
            with self.subTest(grim=grim):
                data = encodeMat([MatCel(256, 1, pixels)], 'INDEXED', palette(), grim=grim, generateMipmaps=False)
                header, _, cels = decode(data, palette())
                self.assertEqual(header.type, 3 if grim else 2)
                self.assertEqual(data[140:], bytes(range(256)))
                np.testing.assert_allclose(cels[0].pixel_data_array[0], pixels.ravel())
        pixels[0, 3] = 0
        data = encodeMat([MatCel(256, 1, pixels)], 'INDEXED', palette(), generateMipmaps=False)
        self.assertEqual(struct.unpack_from('<6I', data, 116)[2:5], (1, 0, 0))
        self.assertEqual(data[140], 0)
        self.assertNotIn(0, data[141:])

    def test_opaque_black_cannot_use_the_transparent_reserved_index(self):
        data = encodeMat([MatCel(2, 1, [(0, 0, 0, 0), (0, 0, 0, 1)])], 'INDEXED', palette(), generateMipmaps=False)
        self.assertEqual(data[140:], bytes((0, 1)))

    def test_grim_cels_have_only_base_images_even_when_mipmaps_requested(self):
        cels = [MatCel(2, 2, np.ones((2, 2, 4))), MatCel(1, 2, np.ones((2, 1, 4)))]
        data = encodeMat(cels, 'INDEXED', palette(), grim=True)
        # Independently follow Grim's record offset and base-only cel step.
        offset = 76 + 40 * 2
        for width, height in ((2, 2), (1, 2)):
            self.assertEqual(struct.unpack_from('<6I', data, offset), (width, height, 0, 0, 0, 1))
            offset += 24 + width * height
        self.assertEqual(offset, len(data))
        self.assertEqual([len(cel.pixel_data_array) for cel in decode(data, palette())[2]], [1, 1])

    def test_palette_ties_choose_lowest_index_deterministically(self):
        cmp = palette()
        cmp.palette[10] = cmp.palette[20] = CmpPaletteRGB(255, 0, 0)
        data = encodeMat([MatCel(1, 1, [1, 0, 0, 1])], 'INDEXED', cmp, generateMipmaps=False)
        self.assertEqual(data[-1], 10)

    def test_multiple_cels_preserve_order_and_independent_dimensions(self):
        cels = [MatCel(4, 2, np.ones((2, 4, 4))), MatCel(1, 3, np.zeros((3, 1, 4)))]
        header, records, restored = decode(encodeMat(cels))
        self.assertEqual(header.texture_count, 2)
        self.assertEqual([record.cel_idx for record in records], [0, 1])
        self.assertEqual([(cel.width, cel.height, len(cel.pixel_data_array)) for cel in restored], [(4, 2, 3), (1, 3, 2)])

    def test_odd_rectangular_mips_include_every_source_pixel(self):
        pixels = np.ones((5, 3, 4))
        pixels[..., :3] = np.arange(5)[:, None, None] / 4
        levels = decode(encodeMat([MatCel(3, 5, pixels)]))[2][0].pixel_data_array
        self.assertEqual([len(level) // 4 for level in levels], [15, 2, 1])
        np.testing.assert_allclose(np.asarray(levels[1]).reshape((-1, 4))[:, 0], (0.2, 0.8))
        self.assertAlmostEqual(levels[2][0], 128 / 255)

    def test_alpha_aware_mips_prevent_transparent_color_bleeding(self):
        pixels = [(1, 0, 0, 1), (0, 0, 1, 0)]
        level = decode(encodeMat([MatCel(2, 1, pixels)]))[2][0].pixel_data_array[1]
        np.testing.assert_allclose(level, (1, 0, 0, 128 / 255))

    def test_single_pixels_and_long_thin_chains_end_at_one_by_one(self):
        for width, height in ((1, 1), (1, 16), (16, 1), (8, 4)):
            with self.subTest(size=(width, height)):
                cel = MatCel(width, height, np.ones((height, width, 4)))
                levels = decode(encodeMat([cel]))[2][0].pixel_data_array
                self.assertEqual(len(levels), max(width, height).bit_length())
                self.assertEqual(len(levels[-1]), 4)

    def test_hdr_clamps_and_input_arrays_remain_unchanged(self):
        pixels = np.array([-2, 0.5, 4, 1.5])
        before = pixels.copy()
        actual = decode(encodeMat([MatCel(1, 1, pixels)]))[2][0].pixel_data_array[0]
        np.testing.assert_allclose(actual, (0, 128 / 255, 1, 1))
        np.testing.assert_array_equal(pixels, before)

    def test_invalid_encodings_palettes_counts_dimensions_and_pixels_reject(self):
        cel = MatCel(1, 1, [1, 1, 1, 1])
        for bad in ('', 'RGB33', None):
            with self.subTest(encoding=bad), self.assertRaises(ValueError):
                encodeMat([cel], bad)
        for bad in (None, [], np.zeros((255, 3)), np.full((256, 3), np.nan), np.full((256, 3), 256), np.full((256, 3), 0.5)):
            with self.assertRaises(ValueError):
                encodeMat([cel], 'INDEXED', bad)
        with self.assertRaises(ValueError):
            encodeMat([])
        for size in (0, -1, 1.5, 1 << 31):
            with self.subTest(size=size), self.assertRaises(ValueError):
                encodeMat([MatCel(size, 1, [1] * 4)])
        for pixels in ([1] * 3, [0, np.nan, 0, 1], [0, np.inf, 0, 1], np.ones(4, dtype=complex)):
            with self.assertRaises(ValueError):
                encodeMat([MatCel(1, 1, pixels)])
        with self.assertRaisesRegex(ValueError, 'Indexed'):
            encodeMat([cel], grim=True)
