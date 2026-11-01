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

from .model3do import *
from .model3doLoader import Model3doFileVersion
from pathlib import Path
from ..types import Vector4f
from ..types.vector import validateFloat32
from ..text.serutils import *
from typing import List, TextIO, Tuple, Union

_file_magic = "3DO"

def save3do(model: Model3do, filePath: Union[Path, str], version: Model3doFileVersion, headerComment: str, *, warnings=None):
    """ Saves `model` to 3DO file """
    for name in [*model.materials, *(node.name for node in model.meshHierarchy)]:
        assertName(name, maxLength=None)
    for geoset in model.geosets:
        for mesh in geoset.meshes:
            assertName(mesh.name, allowSpaces=True, maxLength=None)

    # Fail before opening the destination: nonfinite numbers serialize as tokens
    # the text format cannot read, and must not overwrite a previous good export.
    def finite(values):
        validateFloat32(values, '3DO numeric data')

    finite((model.radius, *model.insertOffset))
    for node in model.meshHierarchy:
        finite((*node.position, *node.rotation, *node.pivot))
    for geoset in model.geosets:
        for mesh in geoset.meshes:
            finite((mesh.radius,))
            for vectors in (mesh.vertices, mesh.vertexColors, mesh.normals, mesh.uvs):
                finite(value for vector in vectors for value in vector)
            for face in mesh.faces:
                finite((*face.normal, *face.color))

    # Long names remain useful for custom engines. Warn about legacy buffers,
    # but preserve identifiers verbatim rather than truncate or reject them.
    name_limit = 31 if version == Model3doFileVersion.Version2_1 else 63
    joint_limit = 31 if version == Model3doFileVersion.Version2_1 else 127
    names = [('model filename', Path(filePath).name, name_limit)]
    names.extend(('material name', name, name_limit) for name in model.materials)
    names.extend(('joint name', node.name, joint_limit) for node in model.meshHierarchy)
    names.extend(('mesh name', mesh.name, name_limit) for geoset in model.geosets for mesh in geoset.meshes)
    for label, name, limit in names:
        if len(name) > limit:
            message = (f"3DO {label} '{name}' has {len(name)} characters; the legacy compatibility "
                       f"limit is {limit}. Exported without truncation.")
            print('Warning: ' + message)
            if warnings is not None:
                warnings.append(message)

    with open(filePath, 'w', encoding='utf-8') as f:
        _write_section_header(f, model, headerComment, version)
        _write_section_resources(f, model)
        _write_section_geometry(f, model, version)
        _write_section_hierarchydef(f, model)

def _vector_to_str(vector: Tuple[float, ...], compact: bool = True, align_width: int = 10) -> str:
    # Fixed decimals erase small geometry, UVs, normals and lighting values.
    # Float repr retains their stored precision and signed zero in every version.
    values = [repr(float(value)) for value in vector]
    if compact:
        return ''.join(' ' + value.rjust(align_width) for value in values)
    return '(' + '/'.join(values) + ')'

def _radius_to_str(radius: float) -> str:
    return repr(float(radius)).rjust(11)

def _write_section_header(file: TextIO, model: Model3do, headerComment: str, version: Model3doFileVersion):
    writeCommentLine(file, headerComment)
    writeNewLine(file)

    writeSectionTitle(file, "header")
    writeKeyValue(file, _file_magic, version.value)
    writeNewLine(file)

def _write_section_resources(file: TextIO, model: Model3do):
    num_mats = len(model.materials)

    writeSectionTitle(file, "modelresource")
    writeCommentLine(file, "Materials list")
    writeKeyValue(file, "materials", num_mats)
    writeNewLine(file)

    if num_mats == 0: return
    for idx, mat in enumerate(model.materials):
        row = '{:>10}:{:>15}'.format(idx, mat)
        writeLine(file, row)
    writeNewLine(file)
    writeNewLine(file)

def _color_to_str(color: Vector4f, version: Model3doFileVersion, compact: bool = True, align_width: int = 0) -> str:
    if version == Model3doFileVersion.Version2_1:
        color = tuple([(color.x + color.y + color.z) /3])
        compact = True
    elif version == Model3doFileVersion.Version2_2:
        color = color[0:3]
        compact = True  # 2.2 stores plain RGB numbers, not parenthesized RGBA.
    return _vector_to_str(color, compact=compact, align_width=align_width)

def _write_vertices(file: TextIO, vertices, vertices_color, version: Model3doFileVersion):
    writeKeyValue(file, "vertices", len(vertices))
    writeNewLine(file)

    writeCommentLine(file, "num:     x:         y:         z:         i:")
    for idx, vert in enumerate(vertices):
        row = '{:>5}:'.format(idx)
        row += _vector_to_str(vert)
        row += ' ' + _color_to_str(vertices_color[idx], version, compact=True)
        writeLine(file, row)

    writeNewLine(file)
    writeNewLine(file)

def _write_tex_vertices(file: TextIO, vertices):
    writeKeyValue(file, "texture vertices", len(vertices))
    writeNewLine(file)

    for idx, vert in enumerate(vertices):
        row = '{:>5}:'.format(idx)
        row += _vector_to_str(vert)
        writeLine(file, row)

    writeNewLine(file)
    writeNewLine(file)

def _write_vert_normals(file: TextIO, normals):
    writeLine(file, "vertex normals".upper())
    writeNewLine(file)

    writeCommentLine(file, "num:     x:         y:         z:")
    for idx, n in enumerate(normals):
        row = '{:>5}:'.format(idx)
        row += _vector_to_str(n)
        writeLine(file, row)

    writeNewLine(file)
    writeNewLine(file)


def _face_vertx_to_str(vert_idxs: List[int], text_vert_idxs: List[int]):
    out = '{:>8}  '.format(len(vert_idxs))
    for i in range(0, len(vert_idxs)):
        out += "{:>3}, {:>2} ".format(vert_idxs[i], text_vert_idxs[i])
    return out

def _write_faces(file: TextIO, faces: List[Mesh3doFace], version: Model3doFileVersion):
    writeKeyValue(file, "faces", len(faces))
    writeNewLine(file)

    writeCommentLine(file, " num:  material:   type:  geo:  light:   tex:  extralight:  verts:")
    face_normals: List[Vector3f] = []
    for idx, face in enumerate(faces):
        row  = '{:>6}:'.format(idx)
        row += '{:>10}'.format(face.materialIdx)
        row += '  0x{:04x}'.format(face.type)
        row += '{:>6}'.format(face.geometryMode)
        row += '{:>8}'.format(face.lightMode)
        row += '{:>7}'.format(face.textureMode)
        row += ' ' + _color_to_str(face.color, version, compact=False)
        row += _face_vertx_to_str(face.vertexIdxs, face.uvIdxs)
        writeLine(file, row)

        face_normals.append(face.normal)
    writeNewLine(file)
    writeNewLine(file)

    # write face normals
    writeLine(file, "face normals".upper())
    writeNewLine(file)

    writeCommentLine(file, "num:     x:         y:         z:")
    for idx, n in enumerate(face_normals):
        row = '{:>5}:'.format(idx)
        row += _vector_to_str(n)
        writeLine(file, row)

    writeNewLine(file)
    writeNewLine(file)

def _write_mesh(file: TextIO, mesh: Mesh3do, version: Model3doFileVersion):
    writeCommentLine(file, "Mesh definition")
    writeKeyValue(file, "mesh", mesh.idx)
    writeNewLine(file)

    writeKeyValue(file, "name", mesh.name)
    writeNewLine(file)

    writeKeyValue(file, "radius", _radius_to_str(mesh.radius))
    writeNewLine(file)

    writeKeyValue(file, "geometrymode", int(mesh.geometryMode))
    writeKeyValue(file, "lightingmode", int(mesh.lightMode))
    writeKeyValue(file, "texturemode", int(mesh.textureMode))
    writeNewLine(file)
    writeNewLine(file)

    _write_vertices(file, mesh.vertices, mesh.vertexColors, version)
    _write_tex_vertices(file, mesh.uvs)
    _write_vert_normals(file, mesh.normals)
    _write_faces(file, mesh.faces, version)

def _write_section_geometry(file: TextIO, model: Model3do, version: Model3doFileVersion):
    writeSectionTitle(file, "geometrydef")

    writeCommentLine(file, "Object radius")
    writeKeyValue(file, "radius", _radius_to_str(model.radius))
    writeNewLine(file)

    writeCommentLine(file, "Insertion offset")
    writeKeyValue(file, "insert offset", _vector_to_str(model.insertOffset))
    writeNewLine(file)

    writeCommentLine(file, "Number of Geometry Sets")
    writeKeyValue(file, "geosets", len(model.geosets))
    writeNewLine(file)

    for num, geoset in enumerate(model.geosets):
        writeCommentLine(file, "Geometry Set definition")
        writeKeyValue(file, "geoset", num)
        writeNewLine(file)

        writeCommentLine(file, "Number of Meshes")
        writeKeyValue(file, "meshes", len(geoset.meshes))
        writeNewLine(file)
        writeNewLine(file)

        for mesh in geoset.meshes:
            _write_mesh(file, mesh, version)

def _write_section_hierarchydef(file: TextIO, model: Model3do):
    writeSectionTitle(file, "hierarchydef")

    writeCommentLine(file, "Hierarchy node list")
    writeKeyValue(file, "hierarchy nodes", len(model.meshHierarchy))
    writeNewLine(file)

    writeCommentLine(file, " num:   flags:   type:    mesh:  parent:  child:  sibling:  numChildren:        x:         y:         z:     pitch:       yaw:      roll:    pivotx:    pivoty:    pivotz:  hnodename:")
    for idx, node in enumerate(model.meshHierarchy):
        row = '{:>6}:'.format(idx)
        row += '  0x{:04x}'.format(node.flags)
        row += ' 0x{:05x}'.format(node.type)
        row += ' {:>8}'.format(node.meshIdx)
        row += ' {:>8}'.format(node.parentIdx)
        row += ' {:>7}'.format(node.firstChildIdx)
        row += ' {:>9}'.format(node.siblingIdx)
        row += ' {:>13}'.format(node.numChildren)
        row += _vector_to_str(node.position)
        row += _vector_to_str(node.rotation)
        row += _vector_to_str(node.pivot)
        row += '  ' + node.name
        writeLine(file, row)
