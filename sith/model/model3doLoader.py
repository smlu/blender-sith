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

import os
from enum import Enum
from pathlib import Path
from sith.text.tokenizer import TokenType, Tokenizer
from sith.types import Vector4f
from typing import Tuple, Union

from .model3do import *

class Model3doFileVersion(float, Enum):
    Version2_1 = 2.1
    Version2_2 = 2.2
    Version2_3 = 2.3

    @classmethod
    def contains(cls, value):
        return value in cls._value2member_map_

def load3do(filePath: Union[str, Path] ) -> Tuple[Model3do, Model3doFileVersion]:
    f = open(filePath, 'r', encoding='utf-8')
    tok = Tokenizer(f)

    file_version = Model3doFileVersion.Version2_1
    model = Model3do(os.path.basename(filePath))

    while True:
        _skip_to_next_model_section(tok)
        t = tok.getToken()
        if t.type == TokenType.EOF:
            break

        if t.value.upper() == "HEADER":
            file_version = _parse_model_header_section(tok)

        elif t.value.upper() == "MODELRESOURCE":
            _parse_model_resource_section(tok, model)

        elif t.value.upper() == "GEOMETRYDEF":
            _parse_model_geometry_section(tok, model, file_version)

        elif t.value.upper() == "HIERARCHYDEF":
            _parse_hierarchy_section(tok, model)

    return (model, file_version)

def _skip_to_next_model_section(tok: Tokenizer):
    t = tok.getToken()
    while t.type != TokenType.EOF and (t.type != TokenType.Identifier or t.value.upper() != "SECTION"):
        t = tok.getToken()

    if t.type != TokenType.EOF:
        tok.assertPunctuator(":")

def _parse_model_header_section(tok: Tokenizer) -> Model3doFileVersion:
    file_sig = tok.getSpaceDelimitedString()
    if file_sig.upper() != "3DO":
        raise IOError("Invalid 3DO model file!")

    version = tok.getFloatNumber()
    if not Model3doFileVersion.contains(version):
        raise IOError("Invalid file version of 3DO model!")
    return Model3doFileVersion(version)

def _parse_model_resource_section(tok: Tokenizer, model: Model3do):
    tok.assertIdentifier("MATERIALS")

    listLen = tok.getIntNumber()
    for i in range(0, listLen):
        idx = tok.getIntNumber()
        if idx != i:
            print(f"Warning: Index mismatch while loading 3DO materials. {idx} != {i}")
        tok.assertPunctuator(':')
        model.materials.append(tok.getSpaceDelimitedString())

def _parse_model_geometry_section(tok: Tokenizer, model: Model3do, fileVersion: Model3doFileVersion):
    tok.assertIdentifier("RADIUS")
    model.radius = tok.getFloatNumber()

    tok.assertIdentifier("INSERT")
    tok.assertIdentifier("OFFSET")
    model.insertOffset = tok.getVector3f()

    tok.assertIdentifier("GEOSETS")
    numGeoSets = tok.getIntNumber()
    for i in range(0, numGeoSets):
        geoset = Model3doGeoSet()

        tok.assertIdentifier("GEOSET")
        geosetIdx = tok.getIntNumber()
        if geosetIdx != i:
            print(f"Warning: Index mismatch while loading 3DO geosets. {geosetIdx} != {i}")

        tok.assertIdentifier("MESHES")
        numMeshes = tok.getIntNumber()
        for j in range(0, numMeshes):
            tok.assertIdentifier("MESH")
            meshIdx = tok.getIntNumber()
            if meshIdx != j:
                print(f"Warning: Index mismatch while loading 3DO meshes. {meshIdx} != {i}")

            tok.assertIdentifier("NAME")
            name = tok.getDelimitedStringToken(lambda c: c == '\n')
            mesh = Mesh3do(meshIdx, name.value.strip())


            tok.assertIdentifier("RADIUS")
            mesh.radius = tok.getFloatNumber()

            identifier = tok.getIdentifier()
            if identifier.upper() == 'SHADOW': # Grim Fandango
                tok.getToken() # Skip SHADOW
                tok.assertIdentifier("GEOMETRYMODE")
            elif identifier.upper() != 'GEOMETRYMODE':
                raise AssertionError(f"Expected identifier 'GEOMETRYMODE', found '{identifier}'! line: {tok.line} column: {tok.column}")

            mesh.geometryMode = GeometryMode(tok.getIntNumber())

            tok.assertIdentifier("LIGHTINGMODE")
            mesh.lightMode = LightMode(tok.getIntNumber())

            tok.assertIdentifier("TEXTUREMODE")
            mesh.textureMode = TextureMode(tok.getIntNumber())


            tok.assertIdentifier("VERTICES")
            numVertices = tok.getIntNumber()
            for k in range(0, numVertices):
                uvIdx = tok.getIntNumber()
                if uvIdx != k:
                    print(f"Warning: Index mismatch while loading 3DO vertices. {uvIdx} != {k}")

                tok.assertPunctuator(':')

                mesh.vertices.append(tok.getVector3f())
                if fileVersion == Model3doFileVersion.Version2_1:
                    intensity = tok.getFloatNumber()
                    mesh.vertexColors.append(Vector4f(*((intensity, )*3), 1.0))
                elif fileVersion == Model3doFileVersion.Version2_2:
                    color = Vector4f(*tok.getVector3f(), 1.0) # RGB
                    mesh.vertexColors.append(color)
                else: # 2.3
                    mesh.vertexColors.append(tok.getVector4f()) #RGBA

            tok.assertIdentifier("TEXTURE")
            tok.assertIdentifier("VERTICES")
            numUVs = tok.getIntNumber()
            for k in range(0, numUVs):
                uvIdx = tok.getIntNumber()
                if uvIdx != k:
                    print(f"Warning: Index mismatch while loading 3DO UV list. {uvIdx} != {k}")
                tok.assertPunctuator(':')
                mesh.uvs.append(tok.getVector2f())

            tok.assertIdentifier("VERTEX")
            tok.assertIdentifier("NORMALS")
            for k in range(0, numVertices):
                normalIdx = tok.getIntNumber()
                if normalIdx != k:
                    print(f"Warning: Index mismatch while loading 3DO vertex normals. {normalIdx} != {k}")
                tok.assertPunctuator(':')
                mesh.normals.append(tok.getVector3f())

            tok.assertIdentifier("FACES")
            numFaces = tok.getIntNumber()
            for k in range(0, numFaces):
                faceIdx = tok.getIntNumber()
                if faceIdx != k:
                    print(f"Warning: Index mismatch while loading 3DO mesh faces. {faceIdx} != {k}")

                tok.assertPunctuator(':')

                face = Mesh3doFace()
                face.materialIdx  = tok.getIntNumber()
                face.type         = FaceType(tok.getIntNumber())
                face.geometryMode = GeometryMode(tok.getIntNumber())
                face.lightMode    = LightMode(tok.getIntNumber())
                face.textureMode  = TextureMode(tok.getIntNumber())

                if fileVersion == Model3doFileVersion.Version2_1:
                    intensity     = tok.getFloatNumber()
                    face.color    = Vector4f(*((intensity, )*3), 1.0)
                elif fileVersion == Model3doFileVersion.Version2_2:
                    face.color    = Vector4f(*tok.getVector3f(), 1.0)
                else: # 2.3
                    face.color    = tok.getVector4f()

                numFaceVerts = tok.getIntNumber()
                for _ in range(0, numFaceVerts):
                    idxs = tok.getPairOfInts()
                    face.vertexIdxs.append(idxs[0])
                    face.uvIdxs.append(idxs[1])

                mesh.faces.append(face)

            tok.assertIdentifier("FACE")
            tok.assertIdentifier("NORMALS")
            for k in range(0, numFaces):
                faceNormalIdx = tok.getIntNumber()
                if faceNormalIdx != k:
                    print(f"Warning: Index mismatch while loading 3DO mesh face normals. {faceNormalIdx} != {k}")
                tok.assertPunctuator(':')
                mesh.faces[k].normal = tok.getVector3f()

            geoset.meshes.append(mesh)
        model.geosets.append(geoset)

def _parse_hierarchy_section(tok: Tokenizer, model: Model3do):
    tok.assertIdentifier("HIERARCHY")
    tok.assertIdentifier("NODES")

    numNodes = tok.getIntNumber()
    for i in range(0, numNodes):
        nodeIdx = tok.getIntNumber()
        if nodeIdx != i:
            print(f"Warning: Seq. number mismatch while loading 3DO hierarchy list. {nodeIdx} != {i}")

        tok.assertPunctuator(':')
        node               = Mesh3doNode()
        node.idx           = nodeIdx
        node.flags         = Mesh3doNodeFlags(tok.getIntNumber())
        node.type          = Mesh3doNodeType(tok.getIntNumber())
        node.meshIdx       = tok.getIntNumber()
        node.parentIdx     = tok.getIntNumber()
        node.firstChildIdx = tok.getIntNumber()
        node.siblingIdx    = tok.getIntNumber()
        node.numChildren   = tok.getIntNumber()

        node.position      = tok.getVector3f()
        node.rotation      = tok.getVector3f()
        node.pivot         = tok.getVector3f()

        node.name          = tok.getSpaceDelimitedString()

        model.meshHierarchy.append(node)
