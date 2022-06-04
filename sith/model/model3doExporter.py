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

import bpy, bmesh, mathutils, os
import numpy as np

from sith.types import BenchmarkMeter
from sith.utils import *
from typing import List

from .model3do import *
from .model3doLoader import Model3doFileVersion
from . import model3doWriter
from .utils import *

kDefaultLightMode   = 3
kDefaultTexMode     = 3
kDefaultVertexColor = Vector4f(0.0, 0.0, 0.0, 1.0)
kHNDefaultFlags     = 0
kHNDefaultType      = 0


def _set_hnode_location(node: Mesh3doNode, scale: mathutils.Vector):
    node.position = Vector3f(*vectorMultiply(node.obj.location, scale))
    node.rotation = objOrientationToImEuler(node.obj)
    node.pivot    = Vector3f(0.0, 0.0, 0.0)

    pc = None
    for c in node.obj.constraints:
        if type(c) == bpy.types.PivotConstraint:
            pc = c
            break

    if not pc is None and pc.influence:
        pivot = -pc.offset
        if c.target:
            pivot += -c.target.location
        node.position = Vector3f(*(node.obj.location - pivot))
        node.pivot    = Vector3f(*pivot)

def _get_mat_name_org(mat: bpy.types.Material):
    return mat.name.lower() if mat else ""

def _get_mat_name(mat: bpy.types.Material):
    name = _get_mat_name_org(mat)
    if not name.endswith(".mat"):
        name = os.path.splitext(name)[0] + '.mat'
    return name

def _is_aux_obj(obj: bpy.types.Object):
    return (kModelRadius in obj.name) or (kMeshRadius in obj.name)

def _uv_add_image_size(uv: mathutils.Vector, mat) -> mathutils.Vector:
    for s in mat.texture_slots:
        if s and s.texture_coords == 'UV' and s.texture and s.texture.type == 'IMAGE':
            return vectorMultiply(uv, mathutils.Vector(s.texture.image.size))
    return uv

def _find_vertex(vlist: List[Vector3f], v: Vector3f, vcolors: List[Vector4f], vcolor: Vector4f) -> int:
    def np_array(o):
        return np.array(o, dtype="f,f,f")
    for vidx in np.where(np_array(vlist) == np_array(v))[0]:
        if vidx < len(vcolors) and vcolors[vidx] == vcolor:
            return vidx
    return -1

def _model3do_add_mesh(model: Model3do, mesh: bpy.types.Mesh, scale: mathutils.Vector, uvAbsolute: bool, exportVertexColors: bool) -> int:
    if mesh is None:
        return -1

    mesh_idx = 0
    if len(model.geosets) > 0:
        mesh_idx = len(model.geosets[0].meshes)
    else:
        model.geosets.append(Model3doGeoSet())

    assertName(mesh.name)
    mesh3do = Mesh3do(mesh_idx, mesh.name)

    # Set model resources
    for mat in mesh.materials:
        name = _get_mat_name_org(mat)
        if len(name) > 0: # mesh could have non existing material
            if not name.endswith(".mat"):
                print("\nWarning: adding an extension '.mat' to the material file name '{}' ".format(name))
                name = _get_mat_name(mat)

            if not model.materials.count(name):
                assertName(name)
                model.materials.append(name)

    # Set mesh faces
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    vcolor_layer = bm.loops.layers.color.verify()
    uv_layer     = bm.loops.layers.uv.verify()

    for face in bm.faces:
        face3do = Mesh3doFace()
        face3do.materialIdx = -1
        mat = None
        if face.material_index >= 0 and face.material_index < len(mesh.materials):
            mat = mesh.materials[face.material_index]
            mat_name = _get_mat_name(mat)
            face3do.materialIdx = model.materials.index(mat_name) if mat_name in model.materials else -1
            if face3do.materialIdx < 0:
                print(f"\nWarning: Couldn't find material index for mesh:'{mesh3do.name}' face:{len(mesh3do.faces)}!")
                mat = None

        face3do.type         = bmFaceGetType(face, bm)
        face3do.geometryMode = bmFaceGetGeometryMode(face, bm)
        face3do.lightMode    = bmFaceGetLightMode(face, bm)
        face3do.textureMode  = bmFaceGetTextureMode(face, bm)
        face3do.color        = bmFaceGetExtraLight(face, bm)
        face3do.normal       = Vector3f(*face.normal)

        # Set face vertex and texture index
        for loop in face.loops:
            vertx  = Vector3f(*vectorMultiply(loop.vert.co, scale))
            vcolor = Vector4f(*loop[vcolor_layer]) if exportVertexColors else kDefaultVertexColor
            vidx   = _find_vertex(mesh3do.vertices, vertx, mesh3do.vertexColors, vcolor)
            if vidx < 0:
                vidx = len(mesh3do.vertices)
                mesh3do.vertices.append(vertx)
                mesh3do.vertexColors.append(vcolor)
                mesh3do.normals.append(Vector3f(*loop.vert.normal))
            face3do.vertexIdxs.append(vidx)

            # Set UV coordinates
            uv = loop[uv_layer].uv
            if uvAbsolute and mat is not None:
                if len(mat.texture_slots) == 0:
                    print(f"\nWarning: Using absolute UV coords for mesh:'{mesh3do.name}' face:{len(mesh3do.faces)} due to face hasn't any texture set!")
                    face3do.materialIdx = -1
                else:
                    uv = _uv_add_image_size(uv, mat)
                    if uv != mathutils.Vector.Fill(2) and uv == loop[uv_layer].uv:
                        print(f"\nWarning: Using absolute UV coords due to no face texture with UV coords and set image was found! mesh:'{mesh3do.name}' face:{len(mesh3do.faces)}")
                        face3do.materialIdx = -1

            uv = Vector2f(uv.x, -uv.y) # Note: Flipped v
            if not mesh3do.uvs.count(uv):
                mesh3do.uvs.append(uv)

            uv_idx = mesh3do.uvs.index(uv)
            face3do.uvIdxs.append(uv_idx)
        mesh3do.faces.append(face3do)
    bm.free()

    assert len(mesh3do.vertices) == len(mesh3do.vertexColors) == len(mesh3do.normals)
    model.geosets[0].meshes.append(mesh3do)
    return mesh_idx

def _set_mesh_properties(mesh: Mesh3do, obj: bpy.types.Object, scale: mathutils.Vector):
    mesh.geometryMode = objGeometryMode(obj)

    radius_obj = getMeshRadiusObj(mesh)
    if radius_obj is None:
        obj = getMeshObjectByName(mesh.name)
        mesh.radius = objRadius(obj, scale)
    else:
        mesh.radius = radius_obj.dimensions[0] / 2

    try:
        mesh.lightMode = LightMode[obj.sith_model3do_light_mode]
    except:
        print("\nWarning: Invalid lighting mode for mesh '{}', using default value!".format(mesh.name))
        mesh.lightMode = kDefaultLightMode

    try:
        mesh.textureMode = TextureMode[obj.sith_model3do_texture_mode]
    except:
        print("\nWarning: Invalid texture mode for mesh '{}', using default value!".format(mesh.name))
        mesh.textureMode = kDefaultTexMode

def _get_obj_hnode_name(obj: bpy.types.Object):
    name = stripOrderPrefix(obj.name)
    if len(obj.sith_model3do_hnode_name) > 0:
        name = obj.sith_model3do_hnode_name

    assertName(name)
    return name

def _get_obj_hnode_idx(nodes: List[Mesh3doNode], obj: bpy.types.Object):
    if obj is not None:
        for idx, n in enumerate(nodes):
            if n.obj == obj:
                return idx
    return -1

def _get_hnode_last_sibling(first_child: Mesh3doNode, nodes: List[Mesh3doNode]):
    sidx = first_child.siblingIdx
    if sidx > -1:
        return _get_hnode_last_sibling(nodes[sidx], nodes)
    return first_child

def _model3do_add_hnode(model: Model3do, mesh_idx: int, obj: bpy.types.Object, parent: bpy.types.Object, scale: mathutils.Vector):
    name               = _get_obj_hnode_name(obj)
    node               = Mesh3doNode(name)
    node.idx           = obj.sith_model3do_hnode_idx
    node.flags         = Mesh3doNodeFlags.fromHex(obj.sith_model3do_hnode_flags)
    node.type          = Mesh3doNodeType.fromHex(obj.sith_model3do_hnode_type)
    node.meshIdx       = mesh_idx
    node.parentIdx     = _get_obj_hnode_idx(model.meshHierarchy, parent)
    node.firstChildIdx = -1
    node.siblingIdx    = -1
    node.numChildren   = 0
    node.obj           = obj

    node_idx = len(model.meshHierarchy)
    if node.parentIdx > -1:
        pnode = model.meshHierarchy[node.parentIdx]
        if pnode.firstChildIdx < 0:
           pnode.firstChildIdx = node_idx
        else:
            snode = model.meshHierarchy[pnode.firstChildIdx]
            snode = _get_hnode_last_sibling(snode,  model.meshHierarchy)
            snode.siblingIdx = node_idx
        pnode.numChildren += 1

    _set_hnode_location(node, scale)
    model.meshHierarchy.append(node)

def _model3do_add_obj(model: Model3do, obj: bpy.types.Object, parent: bpy.types.Object = None, scale: mathutils.Vector = mathutils.Vector((1.0,)*3), uvAbsolute: bool = False, exportVertexColors: bool = False):
    if 'EMPTY' != obj.type != 'MESH' or _is_aux_obj(obj):
        return

    scale    = vectorMultiply(scale, obj.scale)
    mesh_idx = _model3do_add_mesh(model, obj.data, scale, uvAbsolute, exportVertexColors)
    if mesh_idx > -1:
        mesh = model.geosets[0].meshes[mesh_idx]
        _set_mesh_properties(mesh, obj, scale)

    _model3do_add_hnode(model, mesh_idx, obj, parent, scale)
    for child in obj.children:
        _model3do_add_obj(model, child, parent=obj, scale=scale, uvAbsolute=uvAbsolute, exportVertexColors=exportVertexColors)

def _get_model_radius(obj, scale: mathutils.Vector = mathutils.Vector((1.0,)*3)):
    min = mathutils.Vector((999999.0,)*3)
    max = mathutils.Vector((-999999.0,)*3)
    def do_bb(o, s):
        if o.type != 'MESH': return
        nonlocal min, max
        for  v in o.data.vertices:

            v_world = vectorMultiply(o.matrix_local * v.co, s)
            if v_world.x < min.x:
                min.x = v_world.x
            if v_world.x > max.x:
                max.x = v_world.x

            if v_world.y < min.y:
                min.y = v_world.y
            if v_world.y > max.y:
                max.y = v_world.y

            if v_world.z < min.z:
                min.z = v_world.z
            if v_world.z > max.z:
                max.z = v_world.z

    def traverse_children(o, s):
        for c in o.children:
            s = vectorMultiply(s, c.scale)
            do_bb(c, s)
            traverse_children(c, s)

    scale = vectorMultiply(scale, obj.scale)
    do_bb(obj, scale)
    traverse_children(obj, scale)
    return ((max - min).length /2)

def makeModel3doFromObj(name, obj: bpy.types.Object, uvAbsolute: bool = False, exportVertexColors: bool = False):
    model = Model3do(name)
    model.geosets.append(Model3doGeoSet())

    radius_obj = getModelRadiusObj(obj)
    if radius_obj is None:
        model.radius = _get_model_radius(obj)
    else:
        model.radius = radius_obj.dimensions[0] / 2

    if obj.type == 'MESH' or len(obj.children) == 0:
        _model3do_add_obj(model, obj, uvAbsolute=uvAbsolute, exportVertexColors=exportVertexColors)
    else:
        model.insertOffset = Vector3f(*obj.location)
        for child in obj.children:
            _model3do_add_obj(model, child, parent=obj, scale=obj.scale, uvAbsolute=uvAbsolute, exportVertexColors=exportVertexColors)

    model.reorderNodes()
    return model

def export3do(obj: bpy.types.Object, path: str, version: Model3doFileVersion, uvAbsolute: bool, exportVertexColors: bool):
    with BenchmarkMeter(' done in {:.4f} sec.'):
        print("exporting 3DO: %r..." % (path), end="")

        bpy.path.ensure_ext(path, '.3do')
        model_name = os.path.basename(path)
        if not isValidNameLen(model_name):
            raise ValueError("Export file name '{}' is longer then {} chars!".format(model_name, kMaxNameLen))

        model3do = makeModel3doFromObj(model_name, obj, uvAbsolute=uvAbsolute, exportVertexColors=exportVertexColors)
        header   = getExportFileHeader("3DO model '{}'".format(os.path.basename(path)))
        model3doWriter.save3do(model3do, path, version, header)
