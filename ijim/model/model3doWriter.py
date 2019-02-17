from .model3do import *
from ijim.types.vector import *
from typing import Tuple, List
import os

_file_magic = "3DO"
_file_version = "2.3"

def _vector_to_str(vector: Tuple, compact = True, align_width = 11):
    out = "" if compact else '('

    if align_width > 0 and compact:
        format_text = "{:>" + str(align_width) + ".6f}"
    else:
        format_text = "{:.6f}"

    for count, e in enumerate(vector):
        if count > 0 and (not compact or align_width == 0):
            out += '/' if not compact else ' '
        out += format_text.format(e)

    if not compact:
        out += ')'
    return out

def _radius_to_str(radius):
    return "{:>11.6f}".format(radius)

def _make_comment(comment):
    return '# ' + comment

def _write_comment_line(file, comment):
    _write_line(file, _make_comment(comment))

def _write_new_line(file):
    file.write("\n")

def _write_line(file, line):
    file.write(line)
    _write_new_line(file)

def _write_key_value(file, key: str, value):
    _write_line(file, key.upper() + " " + str(value))

def _write_section_title(file, section):
    _write_line(file, "###############")
    _write_line(file, "SECTION: " + section.upper())
    _write_new_line(file)

def _write_section_header(file, model: Model, headerComment):
    _write_comment_line(file, headerComment)
    _write_new_line(file)

    _write_section_title(file, "header")
    _write_key_value(file, _file_magic, _file_version)
    _write_new_line(file)

def _write_section_resources(file, model: Model):
    num_mats = len(model.materials)
    if num_mats < 1:
        return

    _write_section_title(file, "modelresource")
    _write_comment_line(file, "Materials list")
    _write_key_value(file, "materials", num_mats)
    _write_new_line(file)

    for idx, mat in enumerate(model.materials):
        row = '{:>10}:{:>15}'.format(idx, mat)
        _write_line(file, row)
    _write_new_line(file)
    _write_new_line(file)

def _write_vertices(file, vertices, vertices_color):
    _write_key_value(file, "vertices", len(vertices))
    _write_new_line(file)

    _write_comment_line(file, "num:     x:         y:         z:         i:")
    for idx, vert in enumerate(vertices):
        row = '{:>5}:'.format(idx)
        row += _vector_to_str(vert)
        row += " " + _vector_to_str(vertices_color[idx], True, 0)
        _write_line(file, row)

    _write_new_line(file)
    _write_new_line(file)

def _write_tex_vertices(file, vertices):
    _write_key_value(file, "texture vertices", len(vertices))
    _write_new_line(file)

    for idx, vert in enumerate(vertices):
        row = '{:>5}:'.format(idx)
        row += _vector_to_str(vert)
        _write_line(file, row)

    _write_new_line(file)
    _write_new_line(file)

def _write_vert_normals(file, normals):
    _write_line(file, "vertex normals".upper())
    _write_new_line(file)

    _write_comment_line(file, "num:     x:         y:         z:")
    for idx, n in enumerate(normals):
        row = '{:>5}:'.format(idx)
        row += _vector_to_str(n)
        _write_line(file, row)

    _write_new_line(file)
    _write_new_line(file)


def _face_vertx_to_str(vert_idxs: List[int], text_vert_idxs: List[int]):
    out = '{:>8}  '.format(len(vert_idxs))
    for i in range(0, len(vert_idxs)):
        out += "{:>3}, {:>2} ".format(vert_idxs[i], text_vert_idxs[i])
    return out

def _write_faces(file, faces: List[MeshFace]):
    _write_key_value(file, "faces", len(faces))
    _write_new_line(file)

    _write_comment_line(file, " num:  material:   type:  geo:  light:   tex:  R:  G:  B:  A:  verts:")
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
        _write_line(file, row)

        face_normals.append(face.normal)
    _write_new_line(file)
    _write_new_line(file)

    # write face normals
    _write_line(file, "face normals".upper())
    _write_new_line(file)

    _write_comment_line(file, "num:     x:         y:         z:")
    for idx, n in enumerate(face_normals):
        row = '{:>5}:'.format(idx)
        row += _vector_to_str(n)
        _write_line(file, row)

    _write_new_line(file)
    _write_new_line(file)

def _write_mesh(file, mesh: ModelMesh):
    _write_comment_line(file, "Mesh definition")
    _write_key_value(file, "mesh", mesh.idx)
    _write_new_line(file)

    _write_key_value(file, "name", mesh.name)
    _write_new_line(file)

    _write_key_value(file, "radius", _radius_to_str(mesh.radius))
    _write_new_line(file)

    _write_key_value(file, "geometrymode", int(mesh.geometryMode))
    _write_key_value(file, "lightingmode", int(mesh.lightMode))
    _write_key_value(file, "texturemode", int(mesh.textureMode))
    _write_new_line(file)
    _write_new_line(file)

    _write_vertices(file, mesh.vertices, mesh.verticesColor)
    _write_tex_vertices(file, mesh.textureVertices)
    _write_vert_normals(file, mesh.normals)
    _write_faces(file, mesh.faces)

def _write_section_geometry(file, model: Model):
    _write_section_title(file, "geometrydef")

    _write_comment_line(file, "Object radius")
    _write_key_value(file, "radius", _radius_to_str(model.radius))
    _write_new_line(file)

    _write_comment_line(file, "Insertion offset")
    _write_key_value(file, "insert offset", _vector_to_str(model.insertOffset))
    _write_new_line(file)

    _write_comment_line(file, "Number of Geometry Sets")
    _write_key_value(file, "geosets", len(model.geosets))
    _write_new_line(file)

    for num, geoset in enumerate(model.geosets):
        _write_comment_line(file, "Geometry Set definition")
        _write_key_value(file, "geoset", num)
        _write_new_line(file)

        _write_comment_line(file, "Number of Meshes")
        _write_key_value(file, "meshes", len(geoset.meshes))
        _write_new_line(file)
        _write_new_line(file)

        for mesh in geoset.meshes:
            _write_mesh(file, mesh)

def _write_section_hierarchydef(file, model: Model):
    _write_section_title(file, "hierarchydef")

    _write_comment_line(file, "Hierarchy node list")
    _write_key_value(file, "hierarchy nodes", len(model.hierarchyNodes))
    _write_new_line(file)

    _write_comment_line(file, " num:   flags:   type:    mesh:  parent:  child:  sibling:  numChildren:        x:         y:         z:     pitch:       yaw:      roll:    pivotx:    pivoty:    pivotz:  hnodename:")
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
        row += "  " + node.name
        _write_line(file, row)





def write(model: Model, filePath, headerComment):
    f = open(filePath, 'w')

    _write_section_header(f, model, headerComment)
    _write_section_resources(f, model)
    _write_section_geometry(f, model)
    _write_section_hierarchydef(f, model)