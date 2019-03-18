from .keyLoader import load as loadKey
from .key import *

from ijim.types.vector import *
from ijim.text.serutils import *
from typing import Tuple, List
import os

max_markers = 16

def _flags2str(flags: int):
    return '0x{:04X}'.format(flags)

def _vector_to_str(vector: Tuple):
    out = ""
    vert_format  = "{:>" + str(13) + ".8f}"
    for count, e in enumerate(vector):
        out += vert_format.format(e)
    return out

def _write_section_header(file, key: Key, headerComment: str):
    writeCommentLine(file, headerComment)
    writeNewLine(file)

    writeSectionTitle(file, "header")
    writeKeyValue(file, "flags"  , _flags2str(key.flags)   , 6)
    writeKeyValue(file, "type"   , _flags2str(key.type)    , 6)
    writeKeyValue(file, "frames" , key.numFrames           , 6)
    writeKeyValue(file, "fps"    , "{:.3f}".format(key.fps), 6)
    writeKeyValue(file, "joints" , int(key.numJoints)      , 6)
    writeNewLine(file)
    writeNewLine(file)

def _write_section_markers(file, key: Key):
    num_marker = len(key.markers)
    if num_marker < 1:
        return

    writeSectionTitle(file, "markers")
    writeKeyValue(file, "markers", num_marker)
    writeNewLine(file)

    for m in key.markers:
        writeKeyValue(file, "{:.6f}".format(m.frame), int(m.type))
    writeNewLine(file)
    writeNewLine(file)

def _write_section_keyframe_nodes(file, key: Key):
    writeSectionTitle(file, "keyframe nodes")
    writeKeyValue(file, "nodes", len(key.nodes))
    writeNewLine(file)

    for n in key.nodes:
        writeKeyValue(file, "node", n.num, 7)
        writeKeyValue(file, "mesh name", n.meshName)
        writeKeyValue(file, "entries", len(n.keyframes))
        writeNewLine(file)

        writeCommentLine(file, "num:   frame:   flags:           x:           y:           z:           p:           y:           r:")
        writeCommentLine(file, "                                dx:          dy:          dz:          dp:          dy:          dr:")
        for idx, k in enumerate(n.keyframes):
            row1 = '{:>4}:'.format(idx)
            row1 += '{:>9d}'.format(k.frame)
            row1 += '{:>9s}'.format(_flags2str(k.flags))
            row1 += _vector_to_str(k.position)
            row1 += _vector_to_str(k.orientation)
            writeLine(file, row1)

            row2 =  " " * 23
            row2 += _vector_to_str(k.deltaPosition)
            row2 += _vector_to_str(k.deltaRotation)
            writeLine(file, row2)
        writeNewLine(file)

def write(key: Key, filePath, headerComment):
    f = open(filePath, 'w')

    _write_section_header(f, key, headerComment)
    _write_section_markers(f, key)
    _write_section_keyframe_nodes(f, key)