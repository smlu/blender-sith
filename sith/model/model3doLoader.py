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
from enum import Enum
from pathlib import Path
from ..text.tokenizer import TokenType, Tokenizer
from ..types import Vector4f
from typing import List, Optional, Tuple, Union

from .model3do import *

class Model3doFileVersion(float, Enum):
    Version2_1 = 2.1
    Version2_2 = 2.2
    Version2_3 = 2.3

    @classmethod
    def contains(cls, value):
        return value in cls._value2member_map_

def load3do(filePath: Union[str, Path], *, allowErrors: bool = False, warnings: Optional[List[str]] = None) -> Tuple[Model3do, Model3doFileVersion]:
    """Load a model, optionally retaining completed records after a parse error.

    Recovery stops at the first syntax error; it does not guess missing records
    or resume at an arbitrary token. Invalid headers/versions remain fatal.
    """
    diagnostics = warnings if warnings is not None else []
    with open(filePath, 'r', encoding='utf-8') as f:
        tok = Tokenizer(f)
        file_version = Model3doFileVersion.Version2_1
        headerSeen = False
        requiredSections = ('HEADER', 'MODELRESOURCE', 'GEOMETRYDEF', 'HIERARCHYDEF')
        sections = []
        model = Model3do(os.path.basename(filePath))

        section = 'section header'
        try:
            while True:
                section = 'section header'
                _skip_to_next_model_section(tok)
                t = tok.getToken()
                if t.type == TokenType.EOF:
                    break

                section = t.value.upper()
                if section not in requiredSections:
                    continue
                if section != 'HEADER' and not headerSeen:
                    raise IOError('Missing 3DO HEADER before model data')
                if section in sections:
                    raise ValueError(f'Duplicate 3DO section: {section}')
                if section != requiredSections[len(sections)]:
                    raise ValueError(f'3DO section {section} requires {requiredSections[len(sections)]} first')

                if section == "HEADER":
                    file_version = _parse_model_header_section(tok)
                    headerSeen = True
                elif section == "MODELRESOURCE":
                    _parse_model_resource_section(tok, model)
                elif section == "GEOMETRYDEF":
                    _parse_model_geometry_section(tok, model, file_version, allowErrors)
                elif section == "HIERARCHYDEF":
                    _parse_hierarchy_section(tok, model)
                sections.append(section)

            if not headerSeen:
                raise IOError('Missing 3DO HEADER')
            if len(sections) != len(requiredSections):
                raise ValueError('Missing required 3DO section(s): ' + ', '.join(requiredSections[len(sections):]))
        except (AssertionError, TypeError, ValueError, OSError, IndexError) as error:
            if not allowErrors or section == 'HEADER' or not headerSeen:
                raise
            message = (f"Stopped parsing {section} at line {tok.line}, column {tok.column}: {error}. "
                       "Only completed records were retained; remaining file data was not recovered.")
            diagnostics.append(message)
            print(f"Warning: {message}")

    if not headerSeen:
        raise IOError('Missing 3DO HEADER')

    if allowErrors:
        from .model3doRecovery import recoverModel3do
        recoverModel3do(model, diagnostics,
                        recoverUnboundMeshes='HIERARCHYDEF' not in sections or not model.meshHierarchy)

    return (model, file_version)

def _skip_to_next_model_section(tok: Tokenizer):
    t = tok.getToken()
    while t.type != TokenType.EOF and (t.type != TokenType.Identifier or t.value.upper() != "SECTION"):
        if t.type == TokenType.Invalid:
            raise ValueError(f"Invalid character at line {tok.line}, column {tok.column}")
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

    listLen = _read_count(tok, 'material')
    for i in range(0, listLen):
        idx = tok.getIntNumber()
        if idx != i:
            print(f"Warning: Index mismatch while loading 3DO materials. {idx} != {i}")
        tok.assertPunctuator(':')
        model.materials.append(tok.getSpaceDelimitedString())

def _parse_model_geometry_section(tok: Tokenizer, model: Model3do, fileVersion: Model3doFileVersion, allowErrors: bool = False):
    tok.assertIdentifier("RADIUS")
    model.radius = tok.getFloatNumber()

    tok.assertIdentifier("INSERT")
    tok.assertIdentifier("OFFSET")
    model.insertOffset = tok.getVector3f()

    tok.assertIdentifier("GEOSETS")
    numGeoSets = _read_count(tok, 'geoset')
    for i in range(0, numGeoSets):
        geoset = Model3doGeoSet()
        if allowErrors:
            model.geosets.append(geoset)

        tok.assertIdentifier("GEOSET")
        geosetIdx = tok.getIntNumber()
        if geosetIdx != i:
            print(f"Warning: Index mismatch while loading 3DO geosets. {geosetIdx} != {i}")

        tok.assertIdentifier("MESHES")
        numMeshes = _read_count(tok, 'mesh')
        for j in range(0, numMeshes):
            tok.assertIdentifier("MESH")
            meshIdx = tok.getIntNumber()
            if meshIdx != j:
                print(f"Warning: Index mismatch while loading 3DO meshes. {meshIdx} != {i}")

            tok.assertIdentifier("NAME")
            name = tok.getDelimitedStringToken(lambda c: c == '\n')
            mesh = Mesh3do(meshIdx, name.value.strip())
            if allowErrors:
                geoset.meshes.append(mesh)

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
            numVertices = _read_count(tok, 'vertex')
            for k in range(0, numVertices):
                uvIdx = tok.getIntNumber()
                if uvIdx != k:
                    print(f"Warning: Index mismatch while loading 3DO vertices. {uvIdx} != {k}")

                tok.assertPunctuator(':')

                vertex = tok.getVector3f()
                if fileVersion == Model3doFileVersion.Version2_1:
                    intensity = tok.getFloatNumber()
                    color = Vector4f(*((intensity, )*3), 1.0)
                elif fileVersion == Model3doFileVersion.Version2_2:
                    color = Vector4f(*tok.getVector3f(), 1.0) # RGB
                else: # 2.3
                    color = tok.getVector4f() #RGBA
                mesh.vertices.append(vertex)
                mesh.vertexColors.append(color)

            tok.assertIdentifier("TEXTURE")
            tok.assertIdentifier("VERTICES")
            numUVs = _read_count(tok, 'UV')
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
            numFaces = _read_count(tok, 'face')
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

                numFaceVerts = _read_count(tok, 'face corner')
                for _ in range(0, numFaceVerts):
                    idxs = tok.getPairOfInts()
                    face.vertexIdxs.append(idxs[0])
                    face.uvIdxs.append(idxs[1])

                # Repeated corners and zero-area triangles exist in retail
                # assets. Keep their records; Blender handles their topology
                # separately without requiring lossy broken-file recovery.
                if not allowErrors and numFaceVerts < 3:
                    raise ValueError(f"Mesh '{mesh.name}', face {k}: polygon has fewer than three corners")

                mesh.faces.append(face)

            tok.assertIdentifier("FACE")
            tok.assertIdentifier("NORMALS")
            for k in range(0, numFaces):
                faceNormalIdx = tok.getIntNumber()
                if faceNormalIdx != k:
                    print(f"Warning: Index mismatch while loading 3DO mesh face normals. {faceNormalIdx} != {k}")
                tok.assertPunctuator(':')
                mesh.faces[k].normal = tok.getVector3f()

            if not allowErrors:
                geoset.meshes.append(mesh)
        if not allowErrors:
            model.geosets.append(geoset)

def _parse_hierarchy_section(tok: Tokenizer, model: Model3do):
    tok.assertIdentifier("HIERARCHY")
    tok.assertIdentifier("NODES")

    numNodes = _read_count(tok, 'hierarchy node')
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
        node.numChildren   = _read_count(tok, 'child')

        node.position      = tok.getVector3f()
        node.rotation      = tok.getVector3f()
        node.pivot         = tok.getVector3f()

        node.name          = tok.getSpaceDelimitedString()

        model.meshHierarchy.append(node)


def _read_count(tok: Tokenizer, label: str) -> int:
    count = tok.getIntNumber()
    if count < 0:
        raise ValueError(f'3DO {label} count must be nonnegative')
    return count
