from .model3do import *
from ijim.types.vector import *
from ijim.text.serutils import *
from typing import Tuple, List
import os

_file_magic = "3DO"
_file_version = "2.3"

def _vector_to_str(vector: Tuple, compact = True, align_width = 10):
    out = "" if compact else '('
    if compact:
        format_text = " {:>" + str(align_width) + ".6f}"
    else:
        format_text = "{:.6f}"

    for count, e in enumerate(vector):
        if count > 0 and not compact:
            out += '/'
        out += format_text.format(e)

    if not compact:
        out += ')'
    return out

def _radius_to_str(radius):
    return "{:>11.6f}".format(radius)

def _write_section_header(file, model: Model, headerComment):
    writeCommentLine(file, headerComment)
    writeNewLine(file)

    writeSectionTitle(file, "header")
    writeKeyValue(file, _file_magic, _file_version)
    writeNewLine(file)

def _write_section_resources(file, model: Model):
    num_mats = len(model.materials)
    if num_mats < 1:
        return

    writeSectionTitle(file, "modelresource")
    writeCommentLine(file, "Materials list")
    writeKeyValue(file, "materials", num_mats)
    writeNewLine(file)

    for idx, mat in enumerate(model.materials):
        row = '{:>10}:{:>15}'.format(idx, mat)
        writeLine(file, row)
    writeNewLine(file)
    writeNewLine(file)

def _write_vertices(file, vertices, vertices_color):
    writeKeyValue(file, "vertices", len(vertices))
    writeNewLine(file)

    writeCommentLine(file, "num:     x:         y:         z:         i:")
    for idx, vert in enumerate(vertices):
        row = '{:>5}:'.format(idx)
        row += _vector_to_str(vert)
        row += " " + _vector_to_str(vertices_color[idx], True, 0)
        writeLine(file, row)

    writeNewLine(file)
    writeNewLine(file)

def _write_tex_vertices(file, vertices):
    writeKeyValue(file, "texture vertices", len(vertices))
    writeNewLine(file)

    for idx, vert in enumerate(vertices):
        row = '{:>5}:'.format(idx)
        row += _vector_to_str(vert)
        writeLine(file, row)

    writeNewLine(file)
    writeNewLine(file)

def _write_vert_normals(file, normals):
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

def _write_faces(file, faces: List[MeshFace]):
    writeKeyValue(file, "faces", len(faces))
    writeNewLine(file)

    writeCommentLine(file, " num:  material:   type:  geo:  light:   tex:  R:  G:  B:  A:  verts:")
    face_normals = []
    for idx, face in enumerate(faces):
        row = '{:>6}:'.format(idx)
        row += '{:>10}'.format(face.materialIdx)
        row += '  0x{:04x}'.format(face.type)
        row += '{:>6}'.format(face.geometryMode)
        row += '{:>8}'.format(face.lightMode)
        row += '{:>7}'.format(face.textureMode)
        row += ' ' + _vector_to_str(face.color, False, 0)
        row += _face_vertx_to_str(face.vertexIdxs, face.texVertexIdxs)
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

def _write_mesh(file, mesh: ModelMesh):
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

    _write_vertices(file, mesh.vertices, mesh.verticesColor)
    _write_tex_vertices(file, mesh.textureVertices)
    _write_vert_normals(file, mesh.normals)
    _write_faces(file, mesh.faces)

def _write_section_geometry(file, model: Model):
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
            _write_mesh(file, mesh)

def _write_section_hierarchydef(file, model: Model):
    writeSectionTitle(file, "hierarchydef")

    writeCommentLine(file, "Hierarchy node list")
    writeKeyValue(file, "hierarchy nodes", len(model.hierarchyNodes))
    writeNewLine(file)

    writeCommentLine(file, " num:   flags:   type:    mesh:  parent:  child:  sibling:  numChildren:        x:         y:         z:     pitch:       yaw:      roll:    pivotx:    pivoty:    pivotz:  hnodename:")
    for idx, node in enumerate(model.hierarchyNodes):
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



def write(model: Model, filePath, headerComment):
    f = open(filePath, 'w')

    _write_section_header(f, model, headerComment)
    _write_section_resources(f, model)
    _write_section_geometry(f, model)
    _write_section_hierarchydef(f, model)
    
    f.flush()
    f.close()