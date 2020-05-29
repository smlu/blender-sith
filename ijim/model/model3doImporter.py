import mathutils
import math
import bpy, types, bmesh

import sys
import os.path
import time
from typing import List

from . import model3doLoader
from .utils import *
from .model3do import (
    Model,
    GeometryMode,
    LightMode,
    TextureMode,
    ModelMesh,
    FaceType
)

from ijim.material.material import importMatFile
from ijim.utils.utils import *

def getObjByName(name):
    if name in bpy.context.scene.objects:
        return bpy.context.scene.objects[name]
    for o in bpy.context.scene.objects:
        if name == stripOrderPrefix(o.name):
            return o
    raise ValueError("Could not find object '{}'".format(name))

def _get_encoded_face_prop(prop):
    return str(int(prop)).encode('utf-8')

def _get_radius_obj(name):
    try:
        return bpy.context.scene.objects[name]
    except:
        return None


def _set_obj_rotation(obj, rotation):
    setObjEulerRotation(obj, rotation)

def _set_obj_pivot(obj, pivot):
    # note: this function might be worng, load gen_chicken.3do to see the outcome
    if pivot[0] == 0 and  pivot[1] == 0 and pivot[2] == 0:
        return

    pc = obj.constraints.new('PIVOT')
    pc.rotation_range = 'ALWAYS_ACTIVE'
    pc.use_relative_location = True
    pc.owner_space = 'LOCAL'
    pc.offset = -mathutils.Vector(pivot)
    obj.location += mathutils.Vector(pivot)

def _make_radius_obj(name, parent, radius):
    if name in bpy.data.meshes:
        mesh = bpy.data.meshes[name]
    else:
        mesh = bpy.data.meshes.new(name)
        ro = bpy.data.objects.new(name , mesh)
        ro.draw_type = 'WIRE'
        ro.hide = True
        ro.parent_type = 'OBJECT'
        ro.parent = parent
        bpy.context.scene.objects.link(ro)

    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, diameter=radius)
    bm.to_mesh(mesh)
    bm.free()

def _set_model_radius(obj, radius):
    _make_radius_obj(kModelRadius + obj.name, obj, radius)

def _set_mesh_radius(obj, radius):
    _make_radius_obj(kMeshRadius + obj.name, obj, radius)


def _make_mesh(mesh3do: ModelMesh, mat_list: List):
    mesh = bpy.data.meshes.new(mesh3do.name)

    faces = []
    for face in mesh3do.faces:
        faces += [face.vertexIdxs]

    # Construct mesh
    mesh.from_pydata(mesh3do.vertices, [], faces)
    mesh.show_double_sided = True

    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()

    uv_layer = bm.loops.layers.uv.verify()
    bm.faces.layers.tex.verify()

    #face_color_layer = bm.loops.layers.color.new("face_color_")# + str(mesh3do.idx) + str(face.index))

    # Face's custom property tags
    tag_face_type = getBmeshFaceLayer(bm.faces, kFType)
    tag_face_gm   = getBmeshFaceLayer(bm.faces, kGeometryMode)
    tag_face_lm   = getBmeshFaceLayer(bm.faces, kLightingMode)
    tag_face_tm   = getBmeshFaceLayer(bm.faces, kTextureMode)

    # Set mesh materials and UV map
    for face in bm.faces:
        face3do = mesh3do.faces[face.index]

        # Set custom property for face type, geometry, light, texture mode
        face[tag_face_type] = _get_encoded_face_prop(face3do.type)
        face[tag_face_gm]   = _get_encoded_face_prop(face3do.geometryMode)
        face[tag_face_lm]   = _get_encoded_face_prop(face3do.lightMode)
        face[tag_face_tm]   = _get_encoded_face_prop(face3do.textureMode)

        # Set face normal
        face.normal = mesh3do.faces[face.index].normal

        # Set face material index
        mat_name = mat_list[face3do.materialIdx]
        mat = getGlobalMaterial(mat_name)
        if mat is None:
            print("\nWarning: could not find material file '{}'".format(mat_name))
            mat = makeNewGlobalMaterial(mat_name)

        if not mat.name in mesh.materials:
            mesh.materials.append(mat)
        face.material_index = mesh.materials.find(mat.name)

        # Set face texture
        if not mat.texture_slots[0].texture is None:
            tex = mat.texture_slots[0].texture
            img = tex.image
            tex_layer = bm.faces.layers.tex[uv_layer.name]
            face[tex_layer].image = img

        # Set vertices color and face uv map
        for idx, loop in enumerate(face.loops): # update vertices
            vidx = loop.vert.index
            loop.vert.normal = mesh3do.normals[vidx]
            #loop[face_color_layer] =  mesh3do.verticesColor[vidx] # don't vertex color because blender can show only 8 color layers

            # Set UV coordinates
            luv = loop[uv_layer]
            uv = mesh3do.textureVertices[face3do.texVertexIdxs[idx]]
            luv.uv = (uv[0], -uv[1]) # Note: Flipped v

    bm.to_mesh(mesh)
    bm.free()

    mesh.update()
    return mesh




def getModelRadiusObj(obj):
    return _get_radius_obj(kModelRadius + obj.name)

def getMeshRadiusObj(mesh):
    obj = getObjByName(mesh.name)
    return _get_radius_obj(kMeshRadius + stripOrderPrefix(obj.name))

def importObject(file_path, mat_paths = [], b_preserve_order = True, b_clear_scene = True):
    print("importing 3DO: %r..." % (file_path), end="")
    startTime = time.process_time()

    model = model3doLoader.load(file_path)
    if len(model.geosets) == 0: return

    if b_clear_scene:
        clearAllScenes()

    # Load model's textures
    importMaterials(model.materials, getDefaultMatFolders(file_path) + mat_paths)

    # Create model's meshes
    meshes3do = model.geosets[0].meshes
    for mesh3do in meshes3do:

        mesh = _make_mesh(mesh3do, model.materials)
        meshName = mesh3do.name
        obj = bpy.data.objects.new(meshName, mesh)

        # Set mesh radius object, draw type, custom property for lighting and texture mode
        _set_mesh_radius(obj, mesh3do.radius)
        obj.draw_type        = getDrawType(mesh3do.geometryMode)
        obj[kLightingMode]   = mesh3do.lightMode
        obj[kTextureMode]    = mesh3do.textureMode
        obj.draw_bounds_type = 'SPHERE'
        bpy.context.scene.objects.link(obj)


    # Update model's mesh hierarchy
    for idx, meshNode in enumerate(model.hierarchyNodes):
        meshIdx = meshNode.meshIdx

        # Get node's mesh
        if meshIdx == -1:
            obj = bpy.data.objects.new(meshNode.name, None)
            obj.empty_draw_size = (0.0)
            bpy.context.scene.objects.link(obj)
        else:
            meshName = model.geosets[0].meshes[meshIdx].name
            obj = getObjByName(meshName)

        # Make obj name prefixed by idx num.
        # This will make the hierarchy of model 3do ordered by index instead by name in Blender.
        obj.name = makeOrderedName(obj.name, idx, len(model.hierarchyNodes)) if b_preserve_order else obj.name

        # Set mode's parent mesh
        if meshNode.parentIdx != -1:
            pnode = model.hierarchyNodes[meshNode.parentIdx]
            obj.parent_type = 'OBJECT'
            if pnode.meshIdx == -1:
                pname = pnode.name
            else:
                pname = model.geosets[0].meshes[pnode.meshIdx].name
            obj.parent = getObjByName(pname)

        bpy.context.scene.update()

        # Set hierarchy node flags, type and name
        obj[kHnFlags] = meshNode.flags
        obj[kHnType]  = meshNode.type
        obj[kHnName]  = meshNode.name

        # Set node position, rotation and pivot
        obj.location = meshNode.position
        _set_obj_rotation(obj, meshNode.rotation)
        _set_obj_pivot(obj, meshNode.pivot)


    # Set model's insert offset and radius
    baseObj = bpy.data.objects.new(model.name, None)
    baseObj.empty_draw_size = (0.0)
    bpy.context.scene.objects.link(baseObj)

    baseObj.location = model.insert_offset
    _set_model_radius(baseObj, model.radius)

    firstCName = model.hierarchyNodes[0].name
    firstChild = getObjByName(firstCName)
    firstChild.parent_type = 'OBJECT'
    firstChild.parent = baseObj

    # Add model to the "Model3do" group
    if kGModel3do in bpy.data.groups:
        group = bpy.data.groups[kGModel3do]
    else:
        group = bpy.data.groups.new(kGModel3do)
    group.objects.link(baseObj)

    print(" done in %.4f sec." % (time.process_time() - startTime))
    return baseObj
