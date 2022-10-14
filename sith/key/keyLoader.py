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

import os
from sith.text.tokenizer import TokenType, Tokenizer
from sith.key import *
from sith.model import Mesh3doNodeType

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
    key.frames = tok.getIntNumber()

    tok.assertIdentifier("FPS")
    key.fps    = tok.getFloatNumber()

    tok.assertIdentifier("JOINTS")
    key.joints = tok.getIntNumber()

def _parse_key_section_markers(tok: Tokenizer, key: Key):
    tok.assertIdentifier("MARKERS")

    numMarkers = tok.getIntNumber()
    for _ in range(0, numMarkers):
        m       = KeyMarker()
        m.frame = tok.getFloatNumber()
        m.type  = KeyMarkerType.Default
        mt      = tok.getIntNumber()
        try:
            m.type  = KeyMarkerType(mt)
        except:
            print(f"\nWarning: Unknown marker type '{mt}' fallback to '{m.type.name}'!")
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


def loadKey(filePath) -> Key:
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