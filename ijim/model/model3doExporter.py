
import mathutils
import math
import bpy, types, bmesh

import sys
import time
import bpy, bmesh
import os
from typing import List
from collections import defaultdict, OrderedDict

from .model3do import *
from .model3doImporter import getObjByName, getModelRadiusObj, getMeshRadiusObj
from . import model3doWriter
from .utils import *
from ijim.utils.utils import *

kDefaultLightMode   = 3
kDefaultTexMode     = 3
kDefaultVertexColor = Vector4f(0.0, 0.0, 0.0, 1.0)
kDefaultFaceColor   = Vector4f(0.0, 0.0, 0.0, 1.0)
kHNDefaultFlags     = 0
kHNDefaultType      = 0

def _set_hnode_location(node: MeshHierarchyNode, obj: bpy.types.Object):
    node.position = Vector3f(*obj.location)
    node.rotation = getObj_ImEulerOrientation(obj)
    node.pivot = Vector3f(0.0, 0.0, 0.0)

    pc = None
    for c in obj.constraints:
        if type(c) == bpy.types.PivotConstraint:
            pc = c
            break

    if not pc is None and pc.influence:
        pivot = -pc.offset
        if c.target:
            pivot += -c.target.location
        node.position = Vector3f(*(obj.location - pivot))
        node.pivot    = Vector3f(*pivot)

def _get_mat_name_org(mat: bpy.types.Material):
    return mat.name.lower()

def _get_mat_name(mat: bpy.types.Material):
    name = _get_mat_name_org(mat)
    if not name.endswith(".mat"):
        name = os.path.splitext(name)[0] + '.mat'
    return name

def _is_aux_obj(obj: bpy.types.Object):
    return (kModelRadius in obj.name) or (kMeshRadius in obj.name) or (kPivotObj in obj.name)

def _get_face_property_or_default(face: bmesh.types.BMFace, tag: bmesh.types.BMLayerAccessFace, default):
    v = face[tag]
    if len(v):
        return int(v)
    return default

def _get_face_type(face: bmesh.types.BMFace, bm: bmesh.types.BMesh):
    tag = getBmeshFaceLayer(bm.faces, kFType)
    return _get_face_property_or_default(face, tag, 0)

def _get_face_geometry_mode(face: bmesh.types.BMFace, bmesh: bmesh.types.BMesh):
    tag = getBmeshFaceLayer(bmesh.faces, kGeometryMode)
    return _get_face_property_or_default(face, tag, 4)

def _get_face_light_mode(face: bmesh.types.BMFace, bmesh: bmesh.types.BMesh):
    tag = getBmeshFaceLayer(bmesh.faces, kLightingMode)
    return _get_face_property_or_default(face, tag, 3)

def _get_face_tex_mode(face: bmesh.types.BMFace, bmesh: bmesh.types.BMesh):
    tag = getBmeshFaceLayer(bmesh.faces, kTextureMode)
    return _get_face_property_or_default(face, tag, 3)


def _model3do_add_mesh(model: Model, mesh: bpy.types.Mesh) -> int:
    if mesh is None:
        return -1

    mesh_idx = 0
    if len(model.geosets) > 0:
        mesh_idx = len(model.geosets[0].meshes)
    else:
        model.geosets.append(ModelGeoSet())

    assertName(mesh.name)
    mesh3do = ModelMesh(mesh_idx, mesh.name)

    # Set model resources
    for mat in mesh.materials:
        name = _get_mat_name_org(mat)
        if not name.endswith(".mat"):
            print("\nWarning: adding an extension '.mat' to the material file name '{}' ".format(name))
            name = _get_mat_name(mat)

        if not model.materials.count(name):
            assertName(name)
            model.materials.append(name)

    # Set mesh faces
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()
    uv_layer = bm.loops.layers.uv.verify()

    for face in bm.faces:
        face3do = MeshFace()

        mat_name = _get_mat_name(mesh.materials[face.material_index])
        face3do.materialIdx = model.materials.index(mat_name)
        face3do.color = kDefaultFaceColor

        face3do.type         = _get_face_type(face, bm)
        face3do.geometryMode = _get_face_geometry_mode(face, bm)
        face3do.lightMode    = _get_face_light_mode(face, bm)
        face3do.textureMode  = _get_face_tex_mode(face, bm)
        face3do.color        = kDefaultFaceColor
        face3do.normal       = Vector3f(*face.normal)

        # Set face vertex and texture index
        for loop in face.loops:
            vertx = Vector3f(*loop.vert.co)
            if not mesh3do.vertices.count(vertx):
                mesh3do.vertices.append(vertx)
                mesh3do.verticesColor.append(kDefaultVertexColor)
                mesh3do.normals.append(Vector3f(*loop.vert.normal))

            vertx_idx = mesh3do.vertices.index(vertx)
            face3do.vertexIdxs.append(vertx_idx)

            # Set UV coordinates
            uv_vert = loop[uv_layer].uv
            uv = Vector2f(uv_vert[0], -uv_vert[1]) # Note: Flipped v
            if not mesh3do.textureVertices.count(uv):
                mesh3do.textureVertices.append(uv)

            uv_idx = mesh3do.textureVertices.index(uv)
            face3do.texVertexIdxs.append(uv_idx)
        mesh3do.faces.append(face3do)
    bm.free()

    assert len(mesh3do.vertices) == len(mesh3do.verticesColor) == len(mesh3do.normals)
    model.geosets[0].meshes.append(mesh3do)
    return mesh_idx

def _set_mesh_properties(mesh: ModelMesh, obj: bpy.types.Object):
    mesh.geometryMode = getGeometryMode(obj)

    radius_obj = getMeshRadiusObj(mesh)
    if radius_obj is None:
        print("\nWarning: no radius object found for mesh '{}', using calculated value!".format(mesh.name))
        obj = getObjByName(mesh.name)
        mesh.radius = getRadius(obj)
    else:
        mesh.radius = radius_obj.dimensions[0] / 2

    if kLightingMode in obj:
        mesh.lightMode = obj[kLightingMode]
    else:
        print("\nWarning: no lighting mode found for mesh '{}', using default value!".format(mesh.name))
        mesh.lightMode = kDefaultLightMode

    if kTextureMode in obj:
        mesh.textureMode = obj[kTextureMode]
    else:
        print("\nWarning: no texture mode found for mesh '{}', using default value!".format(mesh.name))
        mesh.textureMode = kDefaultTexMode


def _get_obj_property(obj: bpy.types.Object, prop: str, default):
    if prop in obj:
        return obj[prop]
    else:
        print("\nWarning : Property '{}' not set for obj '{}', using default value!".format(prop, obj.name))
        return default

def _get_obj_hnode_name(obj: bpy.types.Object):
    name = stripOrderPrefix(obj.name)
    if kHnName in obj:
        name = obj[kHnName]

    assertName(name)
    return name

def _get_hnode_idx(nodes: List[MeshHierarchyNode], name):
    for idx, node in enumerate(nodes):
        if name == node.name:
            return idx
    return -1

def _get_obj_hnode_idx(nodes: List[MeshHierarchyNode], obj: bpy.types.Object):
    if obj is None:
        return -1
    name = _get_obj_hnode_name(obj)
    return _get_hnode_idx(nodes, name)

def _get_hnode_last_sibling(first_child: MeshHierarchyNode, nodes: List[MeshHierarchyNode]):
    sidx = first_child.siblingIdx
    if sidx > -1:
        return _get_hnode_last_sibling(nodes[sidx], nodes)
    return first_child

def _model3do_add_hnode(model: Model, mesh_idx: int, obj: bpy.types.Object, parent: bpy.types.Object):
    name = _get_obj_hnode_name(obj)
    if name in model.hierarchyNodes:
        return

    node               = MeshHierarchyNode(name)
    node.flags         = _get_obj_property(obj, kHnFlags, kHNDefaultFlags)
    node.type          = _get_obj_property(obj, kHnType, kHNDefaultType)
    node.meshIdx       = mesh_idx
    node.parentIdx     = _get_obj_hnode_idx(model.hierarchyNodes, parent)
    node.firstChildIdx = -1
    node.siblingIdx    = -1
    node.numChildren   = 0

    node_idx = len(model.hierarchyNodes)
    if node.parentIdx > -1:
        pnode = model.hierarchyNodes[node.parentIdx]
        if pnode.firstChildIdx < 0:
           pnode.firstChildIdx = node_idx
        else:
            snode = model.hierarchyNodes[pnode.firstChildIdx]
            snode = _get_hnode_last_sibling(snode,  model.hierarchyNodes)
            snode.siblingIdx = node_idx
        pnode.numChildren += 1

    _set_hnode_location(node, obj)
    model.hierarchyNodes.append(node)

def _model3do_add_obj(model: Model, obj: bpy.types.Object, parent: bpy.types.Object = None):
    if 'EMPTY' != obj.type != 'MESH' or _is_aux_obj(obj):
        return

    mesh_idx  = _model3do_add_mesh(model, obj.data)
    if mesh_idx > -1:
        mesh = model.geosets[0].meshes[mesh_idx]
        _set_mesh_properties(mesh, obj)

    _model3do_add_hnode(model, mesh_idx, obj, parent)
    for child in obj.children:
        _model3do_add_obj(model, child, obj)

def makeModel3doFromObj(name, obj: bpy.types.Object):
    model = Model(name)
    model.geosets.append(ModelGeoSet())

    model.insertOffset = Vector3f(*obj.location)
    radius_obj = getModelRadiusObj(obj)
    if radius_obj is None:
        print("\nWarning: no model radius object found, using calculated value!")
        model.radius = getRadius(obj)
    else:
        model.radius = radius_obj.dimensions[0] / 2

    for child in obj.children:
        _model3do_add_obj(model, child, obj)
        
    return model

def exportObject(obj: bpy.types.Object, path: str):
    bpy.path.ensure_ext(path, '.3do')
    print("exporting 3DO: %r..." % (path), end="")
    start_time = time.process_time()

    model_name = os.path.basename(path)
    if not isValidNameLen(model_name):
        raise ValueError("Export file name '{}' is longer then {} chars!".format(model_name, maxNameLen))

    model3do = makeModel3doFromObj(model_name, obj)
    header = "Model '{}' created with Blender v{}".format(os.path.basename(path), bpy.app.version_string)
    model3doWriter.write(model3do, path, header)

    print(" done in %.4f sec." % (time.process_time() - start_time))

