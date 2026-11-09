"""MAT image round trips with independent pixel and generated-mipmap checks."""
from pathlib import Path

import numpy as np

from batch.common import UnsupportedResource
from batch.core import read_material
from sith.material.cmp import ColorMap
from sith.material.mat import ColorMode, MatType, importMat, kMatCelImagePrefix
from sith.material.matExporter import prepareMatExports


def source_encoding(header):
    info = header.color_info
    if header.type == MatType.Color or info.color_mode == ColorMode.Indexed or info.bpp == 8:
        return 'INDEXED'
    layout = (info.bpp, info.red_bpp, info.green_bpp, info.blue_bpp, info.alpha_bpp)
    encodings = {(32, 8, 8, 8, 8): 'RGBA32', (24, 8, 8, 8, 0): 'RGB24',
                 (16, 5, 6, 5, 0): 'RGB565', (16, 4, 4, 4, 4): 'RGBA4444',
                 (16, 5, 5, 5, 1): 'RGBA1555'}
    if layout not in encodings:
        raise UnsupportedResource(f'No matching export encoding for source MAT layout {layout}')
    return encodings[layout]


def reference_mip(pixels, alpha):
    """Area-average independent of the writer's cumulative-integral algorithm."""
    values = np.asarray(pixels, dtype=np.float64).copy()
    if alpha:
        values[..., :3] *= values[..., 3:4]
    for axis in (0, 1):
        length = values.shape[axis]
        size = max(1, length // 2)
        if length == size:
            continue
        if length % 2 == 0:
            shape = list(values.shape)
            shape[axis:axis + 1] = [size, 2]
            values = values.reshape(shape).mean(axis=axis + 1)
        else:
            # Each row integrates its exact overlapping source-pixel areas.
            starts = np.arange(size) * length / size
            ends = (np.arange(size) + 1) * length / size
            source = np.arange(length)
            weights = np.maximum(0, np.minimum(ends[:, None], source + 1)
                                 - np.maximum(starts[:, None], source)) / (length / size)
            values = np.moveaxis(np.tensordot(weights, values, axes=(1, axis)), 0, axis)
    if alpha:
        np.divide(values[..., :3], values[..., 3:4], out=values[..., :3],
                  where=values[..., 3:4] > 0)
    return np.clip(values, 0, 1)


def palette_pixels(pixels, palette, transparent):
    """Nearest-color oracle using integer dot products, not writer distances."""
    colors, inverse = np.unique(np.floor(pixels[..., :3] * 255 + 0.5).astype(np.int32)
                                .reshape((-1, 3)), axis=0, return_inverse=True)
    first = int(transparent)
    candidates = np.asarray(palette.palette, dtype=np.int32)[first:]
    nearest = np.empty(len(colors), dtype=np.int32)
    for start in range(0, len(colors), 2048):
        block = colors[start:start + 2048]
        distances = (np.sum(block * block, axis=1)[:, None]
                     + np.sum(candidates * candidates, axis=1)[None, :]
                     - 2 * block @ candidates.T)
        nearest[start:start + len(block)] = np.argmin(distances, axis=1) + first
    indices = nearest[inverse].reshape(pixels.shape[:2])
    if transparent:
        indices[pixels[..., 3] < 0.5] = 0
    rgb = np.asarray(palette.palette, dtype=np.float64)[indices] / 255
    alpha = np.where(pixels[..., 3] < 0.5, 0, 1) if transparent else np.ones(indices.shape)
    return np.concatenate((rgb, alpha[..., None]), axis=2)


def check_material(path, target, palette_path, *, grim=None):
    """Import all cels, export their encoding, then independently decode/reimport."""
    path, target = Path(path), Path(target)
    palette = ColorMap.load(palette_path) if palette_path else None
    source, cels = read_material(path, palette)
    encoding = source_encoding(source)
    material = importMat(path, palette)
    images = []
    for index, (width, height, levels, _) in enumerate(cels):
        image = material[kMatCelImagePrefix + str(index)]
        if tuple(image.size) != (width, height):
            raise AssertionError(f'Cel {index}: Blender image dimensions changed')
        pixels = np.asarray(image.pixels[:], dtype=np.float64).reshape(height, width, 4)
        tolerance = 1e-6 if image.is_float else 0.5 / 255 + 1e-6
        np.testing.assert_allclose(pixels.ravel(), levels[0], atol=tolerance, rtol=0)
        images.append(pixels)

    # Use the real Blender adapter, including cel bindings and file encoding.
    if grim is None:
        grim = source.type == MatType.GrimTexture
    prepared = prepareMatExports([(target.name, material)], target.parent, encoding,
                                 palette_path or '', overwrite=True, grim=grim)
    if len(prepared) != 1 or prepared[0][0] != target:
        raise AssertionError('MAT export did not prepare the requested destination')
    target.write_bytes(prepared[0][1])
    exported, restored = read_material(target, palette)
    if exported.type != (MatType.GrimTexture if grim else MatType.Texture):
        raise AssertionError('MAT export changed the selected engine format')
    if source_encoding(exported) != encoding or len(restored) != len(cels):
        raise AssertionError('MAT export changed its encoding or cel count')

    checked = 0
    for index, ((width, height, original, _), (rw, rh, levels, _), pixels) in enumerate(zip(cels, restored, images)):
        if (rw, rh) != (width, height):
            raise AssertionError(f'Cel {index}: exported dimensions changed')
        if len(levels) != (1 if grim else max(width, height).bit_length()):
            raise AssertionError(f'Cel {index}: incomplete exported mip chain')
        actual = np.asarray(levels[0]).reshape(height, width, 4)
        expected = np.asarray(original[0]).reshape(height, width, 4)
        np.testing.assert_allclose(actual[..., 3], expected[..., 3], atol=1e-7, rtol=0)
        # Transparent indexed RGB can change with a reserved palette index;
        # visible colors and all packed RGB channels must stay unchanged.
        visible = expected[..., 3] > 0 if encoding == 'INDEXED' else np.ones((height, width), dtype=bool)
        np.testing.assert_allclose(actual[..., :3][visible], expected[..., :3][visible], atol=1e-7, rtol=0)
        transparent = encoding == 'INDEXED' and bool(np.any(pixels[..., 3] < 0.5))
        info = exported.color_info
        reference = pixels
        for level, decoded in enumerate(levels):
            actual = np.asarray(decoded).reshape(reference.shape)
            if encoding == 'INDEXED':
                np.testing.assert_allclose(actual, palette_pixels(reference, palette, transparent), atol=1e-7, rtol=0)
            else:
                for channel, bits in enumerate((info.red_bpp, info.green_bpp, info.blue_bpp, info.alpha_bpp)):
                    # At an exact half-code boundary either adjacent code is
                    # acceptable: area-sum order can differ by a few FP ulps.
                    np.testing.assert_allclose(actual[..., channel], reference[..., channel] if bits else 1,
                                               atol=0.5 / ((1 << bits) - 1) + 1e-7 if bits else 1e-7, rtol=0)
            checked += actual.shape[0] * actual.shape[1]
            if level + 1 < len(levels):
                reference = reference_mip(reference, encoding == 'INDEXED' or info.alpha_bpp > 0)

    # Reload through the real importer too, rather than checking bytes alone.
    material = importMat(target, palette)
    for index, (_, _, levels, _) in enumerate(restored):
        image = material[kMatCelImagePrefix + str(index)]
        tolerance = 1e-6 if image.is_float else 0.5 / 255 + 1e-6
        np.testing.assert_allclose(np.asarray(image.pixels[:]), levels[0], atol=tolerance, rtol=0)
    return {'operation': 'import-export-import-image-reference', 'encoding': encoding,
            'cels': len(cels), 'source_mipmap_levels': sum(len(cel[2]) for cel in cels),
            'exported_mipmap_levels': sum(len(cel[2]) for cel in restored),
            'checked_pixels': checked, 'color_records_expanded': source.type == MatType.Color,
            'note': 'Base pixels preserved; mipmaps regenerated, not copied; transparent indexed RGB ignored only for source equivalence'}
