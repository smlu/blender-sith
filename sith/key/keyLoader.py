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

import os
from .key import *
from pathlib import Path
from ..text.tokenizer import TokenType, Tokenizer
from ..model import Mesh3doNodeType
from typing import Union

def loadKey(filePath: Union[Path, str]) -> Key:
    """ Loads Key from .key file """
    f = open(filePath, 'r', encoding='utf-8')
    tok = Tokenizer(f)
    key = Key(os.path.basename(filePath))

    while True:
        _skip_to_next_key_section(tok)
        t = tok.getToken()
        if t.type == TokenType.EOF:
            break

        if t.value.upper() == "HEADER":
            _parse_key_section_header(tok, key)

        elif t.value.upper() == "MARKERS":
            _parse_key_section_markers(tok, key)

        elif t.value.upper() == "KEYFRAME":
            tok.assertIdentifier("NODES")
            _parse_key_section_keyframe_nodes(tok, key)

    return key

def _skip_to_next_key_section(tok: Tokenizer):
    t = tok.getToken()
    while t.type != TokenType.EOF and (t.type != TokenType.Identifier or t.value.upper() != "SECTION"):
        t = tok.getToken()

    if t.type != TokenType.EOF:
        tok.assertPunctuator(":")

def _parse_key_section_header(tok: Tokenizer, key: Key):
    tok.assertIdentifier("FLAGS")
    key.flags  = KeyFlag(tok.getIntNumber())

    tok.assertIdentifier("TYPE")
    key.nodeTypes = Mesh3doNodeType(tok.getIntNumber())

    tok.assertIdentifier("FRAMES")
    key.numFrames = tok.getIntNumber()

    tok.assertIdentifier("FPS")
    key.fps = tok.getFloatNumber()

    tok.assertIdentifier("JOINTS")
    key.numJoints = tok.getIntNumber()

def _parse_key_section_markers(tok: Tokenizer, key: Key):
    tok.assertIdentifier("MARKERS")

    numMarkers = tok.getIntNumber()
    for _ in range(0, numMarkers):
        m       = KeyMarker()
        m.frame = tok.getFloatNumber()
        mt      = tok.getIntNumber()
        try:
            m.type  = KeyMarkerType(mt)
        except:
            print(f"\nWarning: Unknown marker type '{mt}' at frame {m.frame}, skipping!")
            continue
        key.markers.append(m)

def _parse_key_section_keyframe_nodes(tok: Tokenizer, key: Key):
    tok.assertIdentifier("NODES")
    numNodes = tok.getIntNumber()
    for _ in range(0, numNodes):
        node = KeyNode()

        tok.assertIdentifier("NODE")
        node.idx = tok.getIntNumber()

        tok.assertIdentifier("MESH")
        tok.assertIdentifier("NAME")
        node.meshName = tok.getSpaceDelimitedString()

        tok.assertIdentifier("ENTRIES")
        numEntries = tok.getIntNumber()
        for j in range(0, numEntries):
            tok.assertInteger(j)
            tok.assertPunctuator(':')

            keyframe = Keyframe()
            keyframe.frame = tok.getIntNumber()
            keyframe.flags = KeyframeFlag(tok.getIntNumber())

            keyframe.position      = tok.getVector3f()
            keyframe.orientation   = tok.getVector3f()
            keyframe.deltaPosition = tok.getVector3f()
            keyframe.deltaRotation = tok.getVector3f()

            node.keyframes.append(keyframe)
        key.nodes.append(node)
