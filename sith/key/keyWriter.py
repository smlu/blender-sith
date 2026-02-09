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

from ..text.serutils import *
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
