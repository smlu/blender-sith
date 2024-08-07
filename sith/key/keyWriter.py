# Sith Blender Addon
# Copyright (c) 2019-2024 Crt Vavros

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

from sith.text.serutils import *
from pathlib import Path
from typing import TextIO, Tuple, Union
from .key import *

def saveKey(key: Key, filePath: Union[Path, str], headerComment: str):
    """ Saves `key` to .key file """
    f = open(filePath, 'w', encoding='utf-8')

    _write_section_header(f, key, headerComment)
    _write_section_markers(f, key)
    _write_section_keyframe_nodes(f, key)

    f.flush()
    f.close()

def _flags2str(flags: int) -> str:
    return '0x{:04X}'.format(flags)

def _vector_to_str(vector: Tuple[float, ...]) -> str:
    out = ""
    vert_format  = " {:>" + str(12) + ".8f}"
    for e in vector:
        out += vert_format.format(e)
    return out

def _write_section_header(file: TextIO, key: Key, headerComment: str):
    writeCommentLine(file, headerComment)
    writeNewLine(file)

    writeSectionTitle(file, "header")
    writeKeyValue(file, "flags"  , _flags2str(key.flags)    , 6)
    writeKeyValue(file, "type"   , _flags2str(key.nodeTypes), 6)
    writeKeyValue(file, "frames" , key.numFrames            , 6)
    writeKeyValue(file, "fps"    , "{:.3f}".format(key.fps) , 6)
    writeKeyValue(file, "joints" , int(key.numJoints)       , 6)
    writeNewLine(file)
    writeNewLine(file)

def _write_section_markers(file: TextIO, key: Key):
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

def _write_section_keyframe_nodes(file: TextIO, key: Key):
    writeSectionTitle(file, "keyframe nodes")
    writeKeyValue(file, "nodes", len(key.nodes))
    writeNewLine(file)

    for n in key.nodes:
        writeKeyValue(file, "node", n.idx, 7)
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
