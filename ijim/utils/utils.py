import bpy, bmesh
import math
import mathutils
import os.path

from typing import List
from ijim.model.model3do import Model, GeometryMode
from ijim.material.material import importMatFile

kGModel3do    = 'Model3do'
kObjRadius    = "OBJ_RADIUS_"
kMeshRadius   = "MESH_RADIUS_"
kPivotObj     = "PIVOT_OBJ_"
kGeometryMode = "geometry mode"
kLightingMode = "lighting mode"
kTextureMode  = "texture mode"
kFType        = "type"
kHnFlags      = "flags"
kHnType       = "type"
kHnName       = 'name'
kFaceType     = "type"

maxNameLen = 64

def isValidNameLen(name: str):
    return len(name) <= maxNameLen

def isASCII(s: str):
    return all(ord(c) < 128 for c in s)

def assertName(name: str):
    if not isValidNameLen(name):
        raise AssertionError("name error: len of '{}' is greater then {} chars".format(name, maxNameLen))

    if not isASCII(name):
        raise AssertionError("name error: '{}' len does not contain all ASCII chars".format(name))


def getBmeshFaceLayer(faces: bmesh.types.BMFaceSeq, name: str):
    return faces.layers.string.get(name) or faces.layers.string.new(name)

def getDefaultMatFolders(model_path):
    path1 = os.path.dirname(model_path) + '/' + 'mat'
    path2 = os.path.abspath(os.path.join(os.path.dirname(model_path), os.pardir)) + '/' + 'mat'
    return [path1, path2]


def getGlobalMaterial(name):
    return bpy.data.materials[name]

def getRadius(obj):
    if obj is None:
        return 0

    bx = obj.dimensions[0]
    by = obj.dimensions[1]
    bz = obj.dimensions[2]
    r2 = math.pow(bx, 2) + math.pow(by, 2) + math.pow(bz, 2)
    return math.sqrt(r2)

def makeQuaternionRotation(v):
    p = mathutils.Quaternion((1.0, 0.0, 0.0), math.radians(v[0]))
    y = mathutils.Quaternion((0.0, 0.0, 1.0), math.radians(v[1]))
    r = mathutils.Quaternion((0.0, 1.0, 0.0), math.radians(v[2]))
    return   y * p * r

def clearAllScenes():
    for scene in bpy.data.scenes:
        for obj in scene.objects:
            if obj.mode != "OBJECT":
                bpy.ops.object.mode_set(mode='OBJECT')
            scene.objects.unlink(obj)

        for layer in scene.render.layers:
            try: scene.render.layers.remove(layer)
            except: pass

        # Remove scene
        try: bpy.data.scenes.remove(scene)
        except: pass

    for bpy_data_iter in (
        bpy.data.actions,
        bpy.data.armatures,
        bpy.data.objects,
        bpy.data.meshes,
        bpy.data.lamps,
        bpy.data.images,
        bpy.data.curves,
        bpy.data.materials,
        bpy.data.cameras,
        bpy.data.textures,
        bpy.data.groups,
        bpy.data.lattices,
        bpy.data.grease_pencil,
        bpy.data.libraries,
        bpy.data.metaballs,
        bpy.data.movieclips,
        bpy.data.node_groups,
        bpy.data.particles,
        bpy.data.shape_keys,
        bpy.data.worlds
    ):
        for id_data in bpy_data_iter:
            bpy_data_iter.remove(id_data)

def getDrawType(geo_mode: GeometryMode):
    if geo_mode == GeometryMode.NotDrawn:
        return 'BOUNDS'
    if geo_mode == GeometryMode.Wireframe:
        return 'WIRE'
    if geo_mode == GeometryMode.Solid:
        return 'SOLID'
    if geo_mode == GeometryMode.Texture:
        return 'TEXTURED'
    raise ValueError("Unknown geometry mode {}".format(geo_mode))

def getGeometryMode(obj: bpy.types.Object):
    dt = obj.draw_type
    if dt == 'BOUNDS':
        return GeometryMode.NotDrawn
    elif dt == 'WIRE':
        return GeometryMode.Wireframe
    elif dt == 'SOLID':
        return GeometryMode.Solid
    elif dt == 'TEXTURED':
        return GeometryMode.Texture
    raise ValueError("Unknown draw type {}".format(dt))

def importMaterials(mat_names: List, search_paths: List):
    for name in mat_names:
        if name in bpy.data.materials:
            continue

        mat_imported = False
        for path in search_paths:
            mat_path = path + '/' + name
            if os.path.isfile(mat_path) and os.access(mat_path, os.R_OK):
                importMatFile(mat_path)
                mat_imported = True
                break

        if not mat_imported:
            print("\nWarning: could not find material file '{}'".format(name))
            mat = bpy.data.materials.new(name)
            mat.texture_slots.add()
            ts = mat.texture_slots[0]
            print(ts.name)
            ts.texture_coords = 'UV'
            ts.uv_layer = 'UVMap'