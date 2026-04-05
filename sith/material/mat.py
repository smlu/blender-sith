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

import bpy, os
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

def _read_header(f: BinaryIO):
    rh  = bytearray(f.read(mh_serf.size))
    rcf = bytearray(f.read(cf_serf.size))
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
    if h.color_info.bpp % 8 != 0 and not (8 <= h.color_info.bpp <= 32):
        raise ImportError(f"Invalid color depth: {h.color_info.bpp}")
    return h

def _read_records(f: BinaryIO, h: MatHeader) -> List[Union[MatColorRecord, MatTextureRecord]]:
    rh_list: List[Union[MatColorRecord, MatTextureRecord]] = []
    for _ in range(0, h.record_count):
        if h.type == MatType.Color:
            mrh = mcr_serf.unpack(bytearray(f.read(mcr_serf.size)))
            record = MatColorRecord._make(mrh)
        else:
            mrh = mtr_serf.unpack(bytearray(f.read(mtr_serf.size)))
            record = MatTextureRecord._make(mrh)
        rh_list.append(record)
    return rh_list

def _decode_indexed_pixel_data(pd, width: int, height: int, cmp: ColorMap, transparent_color: Optional[int] = None) -> Pixels:
    idx = np.frombuffer(pd, dtype=np.uint8) # image index buffer
    pal = np.insert(cmp.palette, 3, 255, axis=1) # expand palette to contain 255 for alpha
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
    type = np.uint8 if (ci.bpp == 8 or ci.bpp == 24) else np.uint16 if ci.bpp == 16 else np.uint32
    raw_img = np.frombuffer(pd, type)
    if ci.bpp == 24: # expand array to contain 255 for alpha
        raw_img = np.insert(raw_img.reshape((-1, 3)), 3, 255, axis=1) \
            .flatten().view(np.uint32)
    raw_img = raw_img.astype(np.uint32)

    def decode_alpha(img):
        a = 255
        if ci.alpha_bpp > 0:
            a = ((img >> ci.alpha_shl) & am) << ci.alpha_shr
            if ci.alpha_bpp == 1: # clamp rgb5551 to 0 or 255
                np.clip(a * 255, 0, 255, a) # faster than a[a>0] = 255
        return a

    # Decode image to 32 bit
    rm = _get_color_mask(ci.red_bpp)
    gm = _get_color_mask(ci.green_bpp)
    bm = _get_color_mask(ci.blue_bpp)
    am = _get_color_mask(ci.alpha_bpp)
    raw_img = ((raw_img >> ci.red_shl)   & rm)  << ci.red_shr         | \
              ((raw_img >> ci.green_shl) & gm)  << ci.green_shr << 8  | \
              ((raw_img >> ci.blue_shl)  & bm)  << ci.blue_shr  << 16 | \
              decode_alpha(raw_img) << 24

    # Flip image over Y-axis (height) and convert to linear
    raw_img = np.flip(
        raw_img.view(np.uint8).reshape((height, width, 4)), axis=[0]
    ).flatten() * _linear_coef # get byte array and convert to linear
    return raw_img

def _read_pixel_data(f: BinaryIO, width: int, height: int, ci: ColorFormat, cmp: Optional[ColorMap] = None, transparent_color: Optional[int] = None) -> Pixels:
    pd_size = _get_pixel_data_size(width, height, ci.bpp)
    pd = bytearray(f.read(pd_size))
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
    mmh_raw = mmm_serf.unpack(bytearray(f.read(mmm_serf.size)))
    mmh     = MatMipmapHeader._make(mmh_raw)

    pd: Optional[List[Pixels]] = None
    if (ci.color_mode != ColorMode.Indexed and ci.bpp != 8) or cmp:
        # Read MipMap pixel data
        transparent_color =  mmh.transparent_color_num if ci.bpp == 8 and mmh.transparent else None
        pd = []
        for i in range(0, mmh.levels):
            w: int = mmh.width >> i
            h: int = mmh.height >> i
            pd += [_read_pixel_data(f, w, h, ci, cmp, transparent_color)]
    else:
        print("  Missing ColorMap, only texture size will be loaded!")

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
    img_name = _get_tex_name(texIdx, mat.name)
    if img_name not in bpy.data.images:
        img = bpy.data.images.new(
            img_name,
            width  = width,
            height = height
        )
    else:
        img = bpy.data.images[img_name]
        if img.has_data:
            img.scale(width, height)

    if pixdata is not None:
        img.pixels[:] = pixdata
        img.file_format = 'PNG'
        img.pack()
        img.update()
    else:
        img.generated_type   = 'UV_GRID'
        img.generated_width  = width
        img.generated_height = height

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

def _make_color_textures(mat: bpy.types.Material, records: List[MatColorRecord], cmp: Optional[ColorMap]): # cmp is None then blank 64x64 textures is created
    # Creates 1 palette pixel color texture of size color_tex_height * color_tex_width
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

def importMat(filePath: Union[Path, str], cmp: Optional[ColorMap] = None) -> bpy.types.Material:
    f = open(filePath, 'rb')
    h = _read_header(f)
    records = _read_records(f, h)

    mat_name = os.path.basename(filePath)
    if mat_name in bpy.data.materials:
        mat = bpy.data.materials[mat_name]
        print(f"Info: MAT file '{mat_name}' already loaded, reloading textures!")
        # Remove old images associated with this material
        if mat.use_nodes and mat.node_tree:
            for node in mat.node_tree.nodes:
                if node.type == 'TEX_IMAGE' and node.image:
                    bpy.data.images.remove(node.image)
            mat.node_tree.nodes.clear()
    else:
        mat = bpy.data.materials.new(mat_name)

    if h.type == MatType.Color:
        mat.blend_method = 'OPAQUE'
        _make_color_textures(mat, records, cmp)
    else: # MAT contains textures
        # 1. Read all mipmaps first to determine global transparency
        mipmaps = []
        for i in range(0, _max_cels(h.texture_count)):
            mipmaps.append(_read_mipmap(f, h.color_info, cmp))

        # 2. Check if ANY cel uses transparency
        use_transparency = any(mm.transparent for mm in mipmaps)
        mat.blend_method = 'BLEND' if use_transparency else 'OPAQUE'

        mat.use_transparent_shadow = False
        if hasattr(mat, 'use_tranparency_overlap'):
            mat.use_tranparency_overlap = use_transparency
        elif hasattr(mat, 'show_transparent_back'):
            mat.show_transparent_back = use_transparency

        # 3. Create textures and setup nodes
        for i, mm in enumerate(mipmaps):
            # Pass the SPECIFIC transparency of this cel to _mat_add_new_texture
            # This ensures opaque cels in a mixed material don't get an alpha link (which causes glitches)
            _mat_add_new_texture(mat, mm.width, mm.height, i, mm.pixel_data_array[0] if mm.pixel_data_array else None, hasTransparency=mm.transparent)

    return mat
