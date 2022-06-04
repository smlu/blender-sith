# Sith Blender Addon
# Copyright (c) 2019-2022 Crt Vavros

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import bpy, os
import numpy as np

from collections import namedtuple
from enum import IntEnum
from struct import Struct
from typing import List, Optional, Tuple
from .cmp import ColorMap

file_magic        = b'MAT '
required_version  = 0x32
color_tex_width   = 64
color_tex_height  = 64
max_texture_slots = 18 # blender 2.79 limitation


class MatType(IntEnum):
    Color   = 0
    Texture = 2

class ColorMode(IntEnum):
    Indexed  = 0
    RGB      = 1
    RGBA     = 2

color_format = namedtuple('color_format', [
    'color_mode',
    'bpp',
    'red_bpp', 'green_bpp', 'blue_bpp',
    'red_shl', 'green_shl', 'blue_shl',
    'red_shr', 'green_shr', 'blue_shr',
    'alpha_bpp', 'alpha_shl', 'alpha_shr'
])
cf_serf = Struct('<14I')

mat_header = namedtuple('mat_header', [
    'magic',
    'version',
    'type',
    'record_count',
    'texture_count',
    'color_info'
])
mh_serf = Struct('<4siIii')

mat_color_record = namedtuple('mat_color_record', [
    'type',
    'color_index',
    'unknown_1',
    'unknown_2',
    'unknown_3',
    'unknown_4',
])
mcr_serf = Struct('<6i')

mat_texture_record = namedtuple('mat_texture_record', [
    'type',
    'color_index',
    'unknown_1',
    'unknown_2',
    'unknown_3',
    'unknown_4',
    'unknown_5',
    'unknown_6',
    'unknown_7',
    'cel_idx'
])
mtr_serf = Struct('<10i')

mat_mipmap_header = namedtuple('mat_mipmap_header', [
    'width',
    'height',
    'transparent',
    'unknown_1',
    'unknown_2',
    'levels',
])
mmm_serf = Struct('<6i')

mipmap = namedtuple("mipmap", [
    'width',
    'height',
    'color_info',
    'pixel_data_array'
])

_linear_coef = 1.0 / 255.0

def _read_header(f):
    rh = bytearray(f.read(mh_serf.size))
    rcf = bytearray(f.read(cf_serf.size))
    cf = color_format._make(cf_serf.unpack(rcf))
    h = mat_header(*mh_serf.unpack(rh), cf)

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

def _read_records(f, h: mat_header) -> List[Tuple[mat_color_record, mat_texture_record]]:
    rh_list = []
    for _ in range(0, h.record_count):
        if h.type == MatType.Color:
            mcr_serf
            mrh = mcr_serf.unpack(bytearray(f.read(mcr_serf.size)))
            record = mat_color_record._make(mrh)
        else:
            mrh = mtr_serf.unpack(bytearray(f.read(mtr_serf.size)))
            record = mat_texture_record._make(mrh)
        rh_list.append(record)
    return rh_list

def _decode_indexed_pixel_data(pd, width, height, cmp: ColorMap) -> List[Tuple[float, float, float, float]]:
    idx = np.frombuffer(pd, dtype=np.uint8) # image index buffer
    pal = np.insert(cmp.palette, 3, 255, axis=1) # expand palette to contain 255 for alpha

    # Convert indexed color to RGB
    raw_img = pal[idx]
    raw_img = raw_img.flatten().view(np.uint32)

    raw_img = np.flip(
        raw_img.view(np.uint8).reshape((height, width, 4)), axis=0
    ).flatten() * _linear_coef # get byte array and convert to linear
    return raw_img


def _get_pixel_data_size(width, height, bpp):
    return int(abs(width * height) * (bpp /8))

def _get_color_mask(bpc):
    return 0xFFFFFFFF >> (32 - bpc)

def _decode_rgba_pixel_data(pd, width, height, ci: color_format) -> List[Tuple[float, float, float, float]]:
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

def _read_pixel_data(f, width, height, ci: color_format, cmp: Optional[ColorMap] = None) -> List[Tuple[float, float, float, float]]:
    pd_size = _get_pixel_data_size(width, height, ci.bpp)
    pd = bytearray(f.read(pd_size))
    if ci.color_mode == ColorMode.Indexed or ci.bpp == 8:
        return _decode_indexed_pixel_data(pd, width, height, cmp)
    # RGB(A)
    return _decode_rgba_pixel_data(pd, width, height, ci)

def _read_mipmap(f, ci: color_format, cmp: Optional[ColorMap] = None) -> List[List[Tuple[float, float, float, float]]]:
    """
    Reads MipMap textures and returns List of mipmap pixel data.
    If cmp is required and is None then no pixel data is set
    """
    # Read texture header
    mmh_raw = mmm_serf.unpack(bytearray(f.read(mmm_serf.size)))
    mmh     = mat_mipmap_header._make(mmh_raw)

    pd = None
    if (ci.color_mode != ColorMode.Indexed and ci.bpp != 8) or cmp:
        # Read MipMap pixel data
        pd = []
        for i in range(0, mmh.levels):
            w = mmh.width >> i
            h = mmh.height >> i
            pd += [_read_pixel_data(f, w, h, ci, cmp)]
    else:
        print("  Missing ColorMap, only texture size will be loaded!")

    return mipmap(mmh.width, mmh.height, ci, pd)

def _get_tex_name(idx, mat_name):
    name = os.path.splitext(mat_name)[0]
    if idx > 0:
        name += '_cel_' + str(idx)
    return name

def _mat_add_new_texture(mat: bpy.types.Material, width: int, height: int, texIdx: int, pixdata: Optional[List[Tuple[float, float, float, float]]], hasTransparency: bool):
    img_name = _get_tex_name(texIdx, mat.name)
    if not img_name in bpy.data.images:
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
        img.pack(as_png=True)
        img.update()
    else:
        img.generated_type   = 'UV_GRID'
        img.generated_width  = width
        img.generated_height = height

    tex                   = bpy.data.textures.new(img_name, 'IMAGE')
    tex.image             = img
    tex.use_preview_alpha = hasTransparency

    ts                = mat.texture_slots.add()
    ts.use            = False # Disable slot by default
    ts.texture        = tex
    ts.use_map_alpha  = hasTransparency
    ts.texture_coords = 'UV'
    ts.uv_layer       = 'UVMap'

def _max_cels(len: int) -> int:
    return min(len, max_texture_slots)

def _make_color_textures(mat: bpy.types.Material, records: List[mat_color_record], cmp: Optional[ColorMap]): # cmp is None then blank 64x64 textures is created
    # Creates 1 palette pixel color texture of size color_tex_height * color_tex_width
    for idx, r in zip(range(_max_cels(len(records))), records):
        pixmap = None
        if cmp:
            rgba   = (cmp.palette[r.color_index]) + (255,)
            pixmap = np.full((color_tex_height, color_tex_width, 4), rgba) \
                .flatten() * _linear_coef # flatten and convert to linear
        else:
            print("  Missing ColorMap, only texture size will be loaded!")

        # Make new texture from pixelmap
        _mat_add_new_texture(mat, color_tex_width, color_tex_height, idx, pixmap, hasTransparency=False)

def importMat(filePath, cmp: Optional[ColorMap] = None):
    f = open(filePath, 'rb')
    h = _read_header(f)
    records = _read_records(f, h)

    mat_name = os.path.basename(filePath)
    if mat_name in bpy.data.materials:
        mat = bpy.data.materials[mat_name]
        print(f"Info: MAT file '{mat_name}' already loaded, reloading textures!")
        for idx, s in enumerate(mat.texture_slots):
            if s is not None:
                if s.texture is not None:
                    bpy.data.textures.remove(s.texture)
                mat.texture_slots.clear(idx)
    else:
        mat = bpy.data.materials.new(mat_name)

    mat.use_shadeless    = True
    mat.use_object_color = True
    mat.use_face_texture = True
    if h.type == MatType.Color:
        _make_color_textures(mat, records, cmp)
    else: # MAT contains textures
        use_transparency        =  True if h.color_info.alpha_bpp > 0 else False
        mat.use_transparency    = use_transparency
        mat.transparency_method = 'Z_TRANSPARENCY'
        mat.alpha               = 0.0
        for i in range(0, _max_cels(h.texture_count)):
            mm = _read_mipmap(f, h.color_info, cmp)
            _mat_add_new_texture(mat, mm.width, mm.height, i, mm.pixel_data_array[0] if mm.pixel_data_array else None, hasTransparency=use_transparency)

    mat.use_textures[0] = True # Enable only 1st slot
    return mat
