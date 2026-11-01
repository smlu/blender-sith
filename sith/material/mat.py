# Sith Blender Addon
# Copyright (C) 2019-2026 Crt Vavros
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

import os
import numpy as np

from collections import namedtuple
from enum import IntEnum
from pathlib import Path
from struct import Struct
from typing import BinaryIO, List, NamedTuple, Optional, Union
from .cmp import ColorMap

file_magic        = b'MAT '
required_version  = 0x32
color_tex_width   = 32
color_tex_height  = 32

kMatCelImagePrefix = '_sith_mat_cel_'

class MatType(IntEnum):
    Color   = 0
    Texture = 2

class ColorMode(IntEnum):
    Indexed  = 0
    RGB      = 1
    RGBA     = 2

class ColorFormat(NamedTuple):
    color_mode: ColorMode
    bpp: int
    red_bpp: int
    green_bpp: int
    blue_bpp: int
    red_shl: int
    green_shl: int
    blue_shl: int
    red_shr: int
    green_shr: int
    blue_shr: int
    alpha_bpp: int
    alpha_shl: int
    alpha_shr: int

cf_serf = Struct('<14I')

class MatHeader(NamedTuple):
    magic: bytes
    version: int
    type: int
    record_count: int
    texture_count: int
    color_info: ColorFormat

mh_serf = Struct('<4siIii')

class MatColorRecord(NamedTuple):
    type: int
    color_index: int
    unknown_1: int
    unknown_2: int
    unknown_3: int
    unknown_4: int

mcr_serf = Struct('<6i')

class MatTextureRecord(NamedTuple):
    type: int
    color_index: int
    unknown_1: int
    unknown_2: int
    unknown_3: int
    unknown_4: int
    unknown_5: int
    unknown_6: int
    unknown_7: int
    cel_idx: int

mtr_serf = Struct('<10i')

class MatMipmapHeader(NamedTuple):
    width: int
    height: int
    transparent: int
    unknown_1: int
    transparent_color_num: int
    levels: int

mmm_serf = Struct('<6i')

class Pixel(NamedTuple):
    red: float
    green: float
    blue: float
    alpha: float

Pixels = List[Pixel]

class Mipmap(NamedTuple):
    width: int
    height: int
    color_info: ColorFormat
    pixel_data_array: Optional[List[Pixels]]
    transparent: bool

_linear_coef = 1.0 / 255.0

def _read_exact(f: BinaryIO, size: int) -> bytes:
    # Bound untrusted dimensions by bytes actually available before allocating.
    position = f.tell()
    end = f.seek(0, os.SEEK_END)
    f.seek(position)
    if size < 0 or size > end - position:
        raise ImportError('Truncated MAT data')
    data = f.read(size)
    if len(data) != size:
        raise ImportError('Truncated MAT data')
    return data

def _read_header(f: BinaryIO):
    rh  = _read_exact(f, mh_serf.size)
    rcf = _read_exact(f, cf_serf.size)
    cf  = ColorFormat._make(cf_serf.unpack(rcf))
    h   = MatHeader(*mh_serf.unpack(rh), cf)

    if h.magic != file_magic:
        raise ImportError("Invalid MAT file")
    if h.version != required_version:
        raise ImportError(f"Invalid MAT file version: {h.version}")
    if h.type != MatType.Color and h.type != MatType.Texture:
        raise ImportError(f"Invalid MAT file type: {h.type}")
    if h.type == MatType.Texture and h.record_count != h.texture_count:
        raise ImportError("MAT file record and texture count missmatch")
    if h.record_count <= 0:
        raise ImportError("MAT file contains no record(s)")
    if not (ColorMode.Indexed <= h.color_info.color_mode <= ColorMode.RGBA):
        raise ImportError(f"Invalid color mode: {h.color_info.color_mode}")
    if h.color_info.bpp not in (8, 16, 24, 32):
        raise ImportError(f"Invalid color depth: {h.color_info.bpp}")
    return h

def _read_records(f: BinaryIO, h: MatHeader) -> List[Union[MatColorRecord, MatTextureRecord]]:
    rh_list: List[Union[MatColorRecord, MatTextureRecord]] = []
    for _ in range(0, h.record_count):
        if h.type == MatType.Color:
            mrh = mcr_serf.unpack(_read_exact(f, mcr_serf.size))
            record = MatColorRecord._make(mrh)
            if not 0 <= record.color_index < 256:
                raise ImportError(f'Invalid MAT palette index: {record.color_index}')
        else:
            mrh = mtr_serf.unpack(_read_exact(f, mtr_serf.size))
            record = MatTextureRecord._make(mrh)
        rh_list.append(record)
    return rh_list

def _decode_indexed_pixel_data(pd, width: int, height: int, cmp: ColorMap, transparent_color: Optional[int] = None) -> Pixels:
    idx = np.frombuffer(pd, dtype=np.uint8) # image index buffer
    pal = np.insert(np.asarray(cmp.palette, dtype=np.uint8), 3, 255, axis=1)
    if transparent_color is not None:
        pal[transparent_color][3] = 0

    # Convert indexed color to RGB
    raw_img = pal[idx]
    raw_img = raw_img.flatten().view(np.uint32)

    raw_img = np.flip(
        raw_img.view(np.uint8).reshape((height, width, 4)), axis=0
    ).flatten() * _linear_coef # get byte array and convert to linear
    return raw_img

def _get_pixel_data_size(width: int, height: int, bpp: int) -> int:
    return int(abs(width * height) * (bpp /8))

def _get_color_mask(bpc: int) -> int:
    return 0xFFFFFFFF >> (32 - bpc)

def _decode_rgba_pixel_data(pd, width: int, height: int, ci: ColorFormat) -> Pixels:
    type = np.uint8 if (ci.bpp == 8 or ci.bpp == 24) else '<u2' if ci.bpp == 16 else '<u4'
    raw_img = np.frombuffer(pd, type)
    if ci.bpp == 24: # expand array to contain 255 for alpha
        raw_img = np.insert(raw_img.reshape((-1, 3)), 3, 255, axis=1) \
            .flatten().view('<u4')
    raw_img = raw_img.astype(np.uint32)

    def channel(bits, shift, default=0.0):
        if bits == 0:
            return np.full(raw_img.size, default, dtype=np.float64)
        if bits < 0 or shift < 0 or bits + shift > ci.bpp:
            raise ImportError('Invalid MAT color channel layout')
        maximum = _get_color_mask(bits)
        return ((raw_img >> shift) & maximum).astype(np.float64) / maximum

    # Blender consumes normalized floats, not expanded 8-bit channel bytes.
    # Divide by each channel's full range: 31/31 and 15/15 must be 1, not
    # 248/255 or 240/255. This also avoids introducing an 8-bit rounding step.
    rgba = np.stack((channel(ci.red_bpp, ci.red_shl),
                     channel(ci.green_bpp, ci.green_shl),
                     channel(ci.blue_bpp, ci.blue_shl),
                     channel(ci.alpha_bpp, ci.alpha_shl, 1.0)), axis=1)
    return np.flip(rgba.reshape((height, width, 4)), axis=0).flatten()

def _read_pixel_data(f: BinaryIO, width: int, height: int, ci: ColorFormat, cmp: Optional[ColorMap] = None, transparent_color: Optional[int] = None) -> Pixels:
    pd_size = _get_pixel_data_size(width, height, ci.bpp)
    pd = _read_exact(f, pd_size)
    if ci.color_mode == ColorMode.Indexed or ci.bpp == 8:
        if not cmp:
            print("  Missing ColorMap, pixel data not decoded!")
            return []
        else:
            return _decode_indexed_pixel_data(pd, width, height, cmp, transparent_color)
    # RGB(A)
    return _decode_rgba_pixel_data(pd, width, height, ci)

def _read_mipmap(f: BinaryIO, ci: ColorFormat, cmp: Optional[ColorMap] = None) -> Mipmap:
    """
    Reads MipMap textures and returns List of mipmap pixel data.
    If cmp is required and is None then no pixel data is set
    """
    # Read texture header
    mmh_raw = mmm_serf.unpack(_read_exact(f, mmm_serf.size))
    mmh     = MatMipmapHeader._make(mmh_raw)
    if mmh.width <= 0 or mmh.height <= 0:
        raise ImportError('Invalid MAT texture dimensions')
    if not 1 <= mmh.levels <= max(mmh.width, mmh.height).bit_length():
        raise ImportError('Invalid MAT mipmap level count')

    if (ci.bpp == 8 or ci.color_mode == ColorMode.Indexed) and mmh.transparent:
        if not 0 <= mmh.transparent_color_num < 256:
            raise ImportError('Invalid MAT transparent palette index')

    pd: Optional[List[Pixels]] = None
    if (ci.color_mode != ColorMode.Indexed and ci.bpp != 8) or cmp:
        # Read MipMap pixel data
        transparent_color =  mmh.transparent_color_num if ci.bpp == 8 and mmh.transparent else None
        pd = []
        for i in range(0, mmh.levels):
            # Each level halves both dimensions, clamped independently to 1.
            w: int = max(1, mmh.width >> i)
            h: int = max(1, mmh.height >> i)
            pd += [_read_pixel_data(f, w, h, ci, cmp, transparent_color)]
    else:
        print("  Missing ColorMap, only texture size will be loaded!")
        # Headers for subsequent cels follow this cel's pixels, even without a palette.
        for i in range(mmh.levels):
            _read_exact(f, _get_pixel_data_size(max(1, mmh.width >> i),
                                              max(1, mmh.height >> i), ci.bpp))

    # Note: 8bpp/Indexed headers are the source of truth for transparency, not color_info.alpha_bpp
    is_transparent = ci.alpha_bpp > 0
    if ci.bpp == 8 or ci.color_mode == ColorMode.Indexed:
        is_transparent = bool(mmh.transparent)

    return Mipmap(mmh.width, mmh.height, ci, pd, is_transparent)

def _get_tex_name(idx: int, mat_name: str) -> str:
    name = os.path.splitext(mat_name)[0]
    if idx > 0:
        name += '_cel_' + str(idx)
    return name

def _mat_add_new_texture(mat: bpy.types.Material, width: int, height: int, texIdx: int, pixdata: Optional[Pixels], hasTransparency: bool):
    import bpy

    # Follow the material's cel binding, never an unrelated image with the same
    # display name. ID references also survive image renames and .blend saves.
    binding = kMatCelImagePrefix + str(texIdx)
    img = mat.get(binding)
    if not isinstance(img, bpy.types.Image) and texIdx == 0 and mat.node_tree:
        # Adopt cel 0 from materials imported before cel bindings were stored.
        node = mat.node_tree.nodes.get('SithTexImage')
        img = node.image if node and node.type == 'TEX_IMAGE' else None

    if isinstance(img, bpy.types.Image) and (img.library is not None or not img.is_editable):
        # Linked buffers can change in memory without being saved locally.
        # Copy before resizing/unpacking so this binding can persist its edits
        # while other users keep their original library image.
        img = img.copy()

    if not isinstance(img, bpy.types.Image):
        img = bpy.data.images.new(
            _get_tex_name(texIdx, mat.name),
            width  = width,
            height = height
        )
    elif tuple(img.size) != (width, height):
        img.scale(width, height)
    mat[binding] = img

    if pixdata is not None:
        img.pixels[:] = pixdata
        img.file_format = 'PNG'
        img.pack()
        img.update()
    else:
        # A packed image stays FILE-backed when only generated_type changes.
        # Discard the packed payload without writing it out, then regenerate the
        # placeholder in place so every shared material keeps the same image ID.
        if img.packed_file:
            img.unpack(method='REMOVE')
        img.source           = 'GENERATED'
        img.generated_type   = 'UV_GRID'
        img.generated_width  = width
        img.generated_height = height
        img.update()

    # For the first texture (cel 0), set up the node tree
    if texIdx == 0:
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        # Clear default nodes
        nodes.clear()

        # Create Principled BSDF and Output
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        bsdf.location = (0, 0)
        bsdf.inputs['Specular IOR Level'].default_value = 0.0
        bsdf.inputs['Roughness'].default_value = 1.0
        output = nodes.new('ShaderNodeOutputMaterial')
        output.location = (300, 0)
        links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])

        # Create Image Texture node
        tex_node = nodes.new('ShaderNodeTexImage')
        tex_node.name = 'SithTexImage'
        tex_node.label = 'SithTexImage'
        tex_node.location = (-300, 0)
        tex_node.image = img
        links.new(tex_node.outputs['Color'], bsdf.inputs['Base Color'])

        if hasTransparency:
            links.new(tex_node.outputs['Alpha'], bsdf.inputs['Alpha'])

def _max_cels(len: int) -> int:
    return len  # No longer limited by texture_slots

def _make_color_textures(mat: bpy.types.Material, records: List[MatColorRecord], cmp: Optional[ColorMap]):
    # Creates 1 palette pixel color texture of size color_tex_height * color_tex_width
    num_cels = 0
    for idx, r in zip(range(_max_cels(len(records))), records):
        pixmap: Optional[Pixels] = None
        if cmp:
            rgba   = (cmp.palette[r.color_index]) + (255,)
            pixmap = np.full((color_tex_height, color_tex_width, 4), rgba) \
                .flatten() * _linear_coef # flatten and convert to linear
        else:
            print("  Missing ColorMap, only texture size will be loaded!")

        # Make new texture from Pixels
        _mat_add_new_texture(mat, color_tex_width, color_tex_height, idx, pixmap, hasTransparency=False)
        num_cels += 1
    return num_cels

def importMat(filePath: Union[Path, str], cmp: Optional[ColorMap] = None) -> bpy.types.Material:
    import bpy

    # 1. Parse records and decode only the selected texture cels before touching
    # Blender data. Color-only MATs have no mipmap payload to iterate over.
    with open(filePath, 'rb') as f:
        h = _read_header(f)
        records = _read_records(f, h)

        mipmaps = []
        if h.type == MatType.Texture:
            for _ in range(_max_cels(h.texture_count)):
                mipmaps.append(_read_mipmap(f, h.color_info, cmp))

    # 2. Resolve the material only after decoding succeeds. Keep its old node
    # until cel 0 can recover a legacy binding; texture creation replaces nodes.
    mat_name = os.path.basename(filePath)
    if mat_name in bpy.data.materials:
        mat = bpy.data.materials[mat_name]
        if not mat.is_editable:
            raise ValueError(f"Make material '{mat.name}' local or editable before reloading its MAT")
        print(f"Info: MAT file '{mat_name}' already loaded, reloading textures!")

    else:
        mat = bpy.data.materials.new(mat_name)

    # 3. Build solid-color cels or texture nodes. Material-wide transparency is
    # enabled if needed, but each cel keeps its own alpha-link decision.
    if h.type == MatType.Color:
        mat.blend_method = 'OPAQUE'
        num_cels = _make_color_textures(mat, records, cmp)
    else: # MAT contains textures
        num_cels = len(mipmaps)
        use_transparency = any(mm.transparent for mm in mipmaps)
        mat.blend_method = 'BLEND' if use_transparency else 'OPAQUE'

        mat.use_transparent_shadow = False
        if hasattr(mat, 'use_transparency_overlap'):
            mat.use_transparency_overlap = use_transparency
        elif hasattr(mat, 'show_transparent_back'):
            mat.show_transparent_back = use_transparency

        # The viewport uses each cel's top mip level; lower levels were consumed
        # while reading so the next cel's header starts at the correct position.
        for i, mm in enumerate(mipmaps):
            # Pass the SPECIFIC transparency of this cel to _mat_add_new_texture
            # This ensures opaque cels in a mixed material don't get an alpha link (which causes glitches)
            _mat_add_new_texture(
                mat, mm.width, mm.height, i,
                mm.pixel_data_array[0] if mm.pixel_data_array else None,
                hasTransparency=mm.transparent
            )

    # Successful shorter reloads must not advertise cels absent from the new
    # file. Drop only our numbered bindings; image IDs may have other users.
    for name in list(mat.keys()):
        if name.startswith(kMatCelImagePrefix):
            suffix = name[len(kMatCelImagePrefix):]
            if suffix.isdecimal() and int(suffix) >= num_cels:
                del mat[name]

    return mat
