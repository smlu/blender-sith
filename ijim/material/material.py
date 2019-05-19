import bpy
from bpy_extras.io_utils import ImportHelper

from collections import namedtuple
from enum import IntEnum
from struct import *
import os


file_magic       = b'MAT '
required_version = 0x32
required_type    = 2

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
    'mipmap_count',
    'color_info'
])
mh_serf = Struct('<4siIii')


mat_record_header = namedtuple('mat_record_header', [
    'record_type',
    'transparent_color',
    'unknown_1',
    'unknown_2',
    'unknown_3',
    'unknown_4',
    'unknown_5',
    'unknown_6',
    'unknown_7',
    'mipmap_idx'
])
mrh_serf = Struct('<10i')

mat_mipmap_header = namedtuple('mat_mipmap_header', [
    'width',
    'height',
    'transparent',
    'unknown_1',
    'unknown_2',
    'texture_count',
])
mmm_serf = Struct('<6i')


mipmap = namedtuple("mipmap", [
    'width',
    'height',
    'color_info',
    'pixel_data_array'
])






def _read_header(f):
    rh = bytearray(f.read(mh_serf.size))
    rcf = bytearray(f.read(cf_serf.size))
    cf = color_format._make(cf_serf.unpack(rcf))
    h = mat_header(*mh_serf.unpack(rh), cf)

    if h.magic != file_magic:
        raise ImportError("Invalid MAT file")
    if h.version != required_version:
        raise ImportError("Invalid MAT file version")
    if h.type != required_type:
        raise ImportError("Invalid MAT file type")
    if h.record_count != h.mipmap_count:
        raise ImportError("Cannot read older version of MAT file")
    if h.record_count <= 0:
        raise ImportError("MAT file record count <= 0")
    if not ( ColorMode.RGB <= h.color_info.color_mode <= ColorMode.RGBA ):
        raise ImportError("Invalid color mode")
    if h.color_info.bpp % 8 != 0:
        raise ImportError("BPP % 8 != 0")

    return h

def _read_records(f, h: mat_header):
    rh_list = []
    for i in range(0, h.record_count):
        rc = h.record_count
        mrh = mrh_serf.unpack(bytearray(f.read(mrh_serf.size)))
        rh_list.append(mat_record_header._make(mrh))
    return rh_list

def _get_img_row_len(width, bpp):
    return int(abs(width) * (bpp /8))

def _get_pixel_data_size(width, height, bpp):
    return int(abs(width * height) * (bpp /8))

def _get_color_mask(bpc):
    return 0xFFFFFFFF >> (32 - bpc)

def _decode_pixel(p, ci: color_format):
    r = ((p >> ci.red_shl)   & _get_color_mask(ci.red_bpp))   << ci.red_shr
    g = ((p >> ci.green_shl) & _get_color_mask(ci.green_bpp)) << ci.green_shr
    b = ((p >> ci.blue_shl)  & _get_color_mask(ci.blue_bpp))  << ci.blue_shr
    a = 255
    if ci.alpha_bpp != 0:
        a= ((p >> ci.alpha_shl) & _get_color_mask(ci.alpha_bpp)) << ci.alpha_shr

    # Return blender's pixel representation
    return (float(r/255), float(g/255), float(b/255), float(a/255))

def _decode_pixel_data(pd, width, height, ci: color_format):
    pixel_size = int(ci.bpp /8)
    row_len = _get_img_row_len(width, ci.bpp)
    dpd = []

    # MAT cord-system is bottom left, so we use reverse here to flip img over y cord.
    for r in reversed(range(0, height)):
        for c in (range(0, row_len, pixel_size)):
            i = c + r * row_len
            p_raw = pd[i: i + pixel_size]
            pixel = int.from_bytes(p_raw, byteorder='little', signed=False)
            dpd.extend(_decode_pixel(pixel, ci))
    return dpd

def _read_texture(f, width, height, ci: color_format):
    pd_size = _get_pixel_data_size(width, height, ci.bpp)
    pd = bytearray(f.read(pd_size))
    return _decode_pixel_data(pd, width, height, ci)


def _read_mipmap(f, ci: color_format):
    mmh_raw = mmm_serf.unpack(bytearray(f.read(mmm_serf.size)))
    mmh = mat_mipmap_header._make(mmh_raw)

    pd = []
    for i in range(0, mmh.texture_count):
        tex_w  = mmh.width >> i
        tex_h = mmh.height >> i
        pd += [_read_texture(f, tex_w, tex_h, ci)]

    return mipmap(mmh.width, mmh.height, ci, pd)


def _get_tex_name(idx, mat_name):
    name = os.path.splitext(mat_name)[0]
    if idx > 0:
        name += '_' + str(idx)
    return name





def importMatFile(filePath):
    f = open(filePath, 'rb')
    h = _read_header(f)
    _read_records(f, h)

    mat_name = os.path.basename(filePath)
    if mat_name in bpy.data.materials:
        mat = bpy.data.materials[mat_name]
    else:
        mat = bpy.data.materials.new(mat_name)


    mat.use_shadeless = True
    mat.use_object_color = True
    mat.use_face_texture = True

    use_transparency =  True if  h.color_info.alpha_bpp > 0 else False
    mat.use_transparency = use_transparency
    mat.transparency_method = 'Z_TRANSPARENCY'
    mat.alpha = 0.0

    for i in range(0, h.mipmap_count):
        mm = _read_mipmap(f, h.color_info)

        img_width  = mm.width
        img_height = mm.height
        img_name = _get_tex_name(i, mat_name)
        if not img_name in bpy.data.images:
            img = bpy.data.images.new(
                img_name,
                width=img_width,
                height=img_height
            )
        else:
            img = bpy.data.images[img_name]
            img.scale(img_width, img_height)

        img.pixels = mm.pixel_data_array[0]
        img.update()
        img.pack(as_png=True)

        tex = bpy.data.textures.new(img_name, 'IMAGE')
        tex.image = img
        tex.use_preview_alpha = use_transparency

        ts = mat.texture_slots.add()
        ts.texture = tex
        ts.use_map_alpha = use_transparency
        ts.texture_coords = 'UV'
        ts.uv_layer = 'UVMap'

    return mat