"""Independent corpus pixel oracles must not mirror the writer's implementation."""
import unittest

import numpy as np

from batch.common import UnsupportedResource
from batch.material import palette_pixels, reference_mip, source_encoding
from sith.material.mat import ColorFormat, MatHeader, MatType
from sith.material.cmp import ColorMap


class MaterialOracleTests(unittest.TestCase):
    def test_odd_edges_and_single_axes_contribute_to_area_average(self):
        for shape in ((1, 5, 4), (5, 1, 4), (3, 5, 4), (4, 2, 4)):
            values = np.arange(np.prod(shape), dtype=float).reshape(shape) / np.prod(shape)
            reduced = reference_mip(values, False)
            self.assertEqual(reduced.shape, (max(1, shape[0] // 2), max(1, shape[1] // 2), 4))
            np.testing.assert_allclose(reduced.mean(axis=(0, 1)), values.mean(axis=(0, 1)), atol=1e-15)

    def test_alpha_filter_does_not_mix_in_invisible_rgb(self):
        pixels = np.array([[[1, 0, 0, 0], [0, 0, 1, 1]]], dtype=float)
        np.testing.assert_array_equal(reference_mip(pixels, True), [[[0, 0, 1, 0.5]]])
        np.testing.assert_array_equal(reference_mip(pixels, False), [[[0.5, 0, 0.5, 0.5]]])

    def test_nearest_palette_ties_and_reserved_transparency(self):
        palette = ColorMap()
        palette.palette = [(255, 255, 255)] * 256
        palette.palette[:3] = [(0, 0, 0), (2, 0, 0), (0, 0, 0)]
        pixels = np.array([[[1 / 255, 0, 0, 1], [0, 0, 0, 0]]])
        np.testing.assert_array_equal(palette_pixels(pixels, palette, False), [[[0, 0, 0, 1], [0, 0, 0, 1]]])
        np.testing.assert_allclose(palette_pixels(pixels, palette, True), [[[2 / 255, 0, 0, 1], [0, 0, 0, 0]]])

    def test_unknown_source_layout_is_not_silently_counted_as_a_pass(self):
        info = ColorFormat(1, 16, 5, 5, 5, 10, 5, 0, 3, 3, 3, 0, 0, 0)
        header = MatHeader(b'MAT ', 50, MatType.Texture, 1, 1, info)
        with self.assertRaisesRegex(UnsupportedResource, 'No matching export encoding'):
            source_encoding(header)
