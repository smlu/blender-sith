"""Grim indexed MAT variants, independent pixels and malformed records."""
import contextlib
import io
import struct
import unittest

import numpy as np

from grim_fixtures import grim_mat_bytes
from sith.material import mat
from sith.material.cmp import ColorMap


class GrimMaterialTests(unittest.TestCase):
    def palette(self):
        result = ColorMap()
        result.palette = [(index, 255 - index, index // 2) for index in range(256)]
        return result

    def decode(self, data, palette=None):
        stream = io.BytesIO(data)
        header = mat._read_header(stream)
        records = mat._read_records(stream, header)
        images = [mat._read_mipmap(stream, header.color_info, palette)
                  for _ in range(header.texture_count)]
        return header, records, images, stream

    def test_full_and_compact_records_have_exact_texture_offsets(self):
        for tag, offset in ((8, 116), (0, 100)):
            with self.subTest(tag=tag):
                header, records, images, stream = self.decode(grim_mat_bytes(tag=tag), self.palette())
                self.assertEqual(header.type, mat.MatType.GrimTexture)
                self.assertEqual(len(records), 1)
                self.assertEqual((images[0].width, images[0].height), (2, 2))
                self.assertEqual(stream.tell(), offset + 24 + 4)
                self.assertEqual(stream.read(), b'')
                self.assertTrue(images[0].transparent)
                expected = [(70, 185, 35, 255), (255, 0, 127, 255),
                            (0, 255, 0, 0), (17, 238, 8, 255)]
                np.testing.assert_allclose(np.asarray(images[0].pixel_data_array[0]).reshape(-1, 4),
                                           np.asarray(expected) / 255, atol=1e-7)

    def test_palette_conversion_covers_every_index_and_both_alpha_states(self):
        for tag in (0, 8):
            for transparent in (False, True):
                with self.subTest(tag=tag, transparent=transparent):
                    data = grim_mat_bytes(tag=tag, cels=[(16, 16, [bytes(range(256))], transparent)])
                    _, _, images, _ = self.decode(data, self.palette())
                    pixels = np.asarray(images[0].pixel_data_array[0]).reshape(16, 16, 4)[::-1].reshape(-1, 4)
                    expected = [(index, 255 - index, index // 2,
                                 0 if transparent and index == 0 else 255) for index in range(256)]
                    np.testing.assert_allclose(pixels, np.asarray(expected) / 255, atol=1e-7)

    def test_multiple_cels_and_rectangular_mipmaps_stay_aligned(self):
        cels = [(4, 2, [bytes(range(8)), b'\x11\x46', b'\xff'], True),
                (1, 2, [b'\x46\x11'], False), (1, 1, [b'\x00'], True)]
        for tag in (0, 8):
            with self.subTest(tag=tag):
                _, records, images, stream = self.decode(grim_mat_bytes(tag=tag, cels=cels), self.palette())
                self.assertEqual(len(records), 3)
                self.assertEqual([(image.width, image.height) for image in images], [(4, 2), (1, 2), (1, 1)])
                self.assertEqual([len(image.pixel_data_array) for image in images], [3, 1, 1])
                self.assertEqual([image.transparent for image in images], [True, False, True])
                self.assertEqual(stream.read(), b'')

    def test_missing_palette_consumes_all_cels_and_mipmaps_without_decoding(self):
        cels = [(2, 1, [b'\x11\x46', b'\xff'], False), (1, 1, [b'\x00'], True)]
        for tag in (0, 8):
            with self.subTest(tag=tag), contextlib.redirect_stdout(io.StringIO()):
                _, _, images, stream = self.decode(grim_mat_bytes(tag=tag, cels=cels))
                self.assertEqual([image.pixel_data_array for image in images], [None, None])
                self.assertEqual(stream.read(), b'')

    def test_external_palette_is_used_even_with_an_opaque_trailer(self):
        # Some type-3 files carry a further 768 bytes. Grim's material loader
        # still colors texture indices with the selected external CMP palette.
        _, _, images, stream = self.decode(grim_mat_bytes(trailer=b'\xff' * 768), self.palette())
        self.assertEqual(stream.read(), b'\xff' * 768)
        np.testing.assert_allclose(images[0].pixel_data_array[0][:4], (70 / 255, 185 / 255, 35 / 255, 1))

    def test_every_truncated_prefix_is_rejected_with_or_without_a_palette(self):
        for tag in (0, 8):
            data = grim_mat_bytes(tag=tag)
            for palette in (None, self.palette()):
                for size in range(len(data)):
                    with self.subTest(tag=tag, palette=palette is not None, size=size), \
                         contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ImportError):
                        self.decode(data[:size], palette)

    def test_invalid_record_tag_count_and_indexed_format_are_rejected(self):
        for offset, value in ((76, 7), (12, 2), (12, 0), (20, 1), (24, 16),
                              (116, 0), (136, 0), (124, 1)):
            data = bytearray(grim_mat_bytes())
            struct.pack_into('<I', data, offset, value)
            if offset == 124:
                # Turning transparency on is valid; an invalid transparent
                # index, not the alpha flag itself, must be rejected.
                struct.pack_into('<I', data, 132, 256)
            with self.subTest(offset=offset, value=value), self.assertRaises(ImportError):
                self.decode(data, self.palette())
