from ijim.material.material import importMatFile
from ijim.types.vector import Vector3f
from .model3do import GeometryMode

import math
import os.path
import re
from typing import List

import bpy
import mathutils


kGModel3do        = 'Model3do'
kObjRadius        = "OBJ_RADIUS_"
kMeshRadius       = "MESH_RADIUS_"
kPivotObj         = "PIVOT_OBJ_"
kGeometryMode     = "geometry mode"
kLightingMode     = "lighting mode"
kTextureMode      = "texture mode"
kFType            = "type"
kHnFlags          = "flags"
kHnType           = "type"
kHnName           = 'name'
kFaceType         = "type"
kNameOrderPrefix  = "no"

def makeOrderedName(name, order, maxOrder):
    padding = len(str(maxOrder))
    name_format = "{}" + "{:0" + str(padding) + "d}" + "_{}"
    return name_format.format(kNameOrderPrefix, order, name)

def isOrderPrefixed(name):
    return re.match("^{}([0-9]+)_".format(kNameOrderPrefix), name)

def stripOrderPrefix(name):
    return re.sub("^{}([0-9]+)_".format(kNameOrderPrefix), "", name)

def getRadius(obj):
    if obj is None:
        return 0

    bx = obj.dimensions[0]
    by = obj.dimensions[1]
    bz = obj.dimensions[2]
    r2 = math.pow(bx, 2) + math.pow(by, 2) + math.pow(bz, 2)
    return math.sqrt(r2)

def makeEulerRotation(rot: Vector3f):
    p = math.radians(rot[0])
    y = math.radians(rot[1])
    r = math.radians(rot[2])
    return mathutils.Euler((p, r, y), 'YXZ')

def setObjEulerRotation(obj: bpy.types.Object, rotation: Vector3f):
    obj.rotation_mode = 'YXZ'
    obj.rotation_euler  = makeEulerRotation(rotation)

def makeQuaternionRotation(rot: Vector3f):
    p = mathutils.Quaternion((1.0, 0.0, 0.0), math.radians(rot[0]))
    y = mathutils.Quaternion((0.0, 0.0, 1.0), math.radians(rot[1]))
    r = mathutils.Quaternion((0.0, 1.0, 0.0), math.radians(rot[2]))
    return   y * p * r

def setObjQuaternionRotation(obj: bpy.types.Object, rotation: Vector3f):
    obj.rotation_mode = 'QUATERNION'
    obj.rotation_quaternion = makeQuaternionRotation(rotation)

def get_IM_EulerOrientation(obj: bpy.types.Object):
    erot = None
    rmode = obj.rotation_mode
    if rmode == "QUATERNION":
        qrot = obj.rotation_quaternion.normalized()
        erot = qrot.to_euler("YXZ")
    elif rmode == "AXIS_ANGLE":
        qrot = mathutils.Quaternion(obj.rotation_axis_angle)
        qrot.normalize()
        erot.to_euler("YXZ")
    else:
        erot = obj.rotation_euler.copy()
        if erot.order != "YXZ":
            erot.order = "YXZ"

    rot = []
    for a in erot:
        d = math.degrees(a)
        rot.append(d)
    return Vector3f(rot[0], rot[2], rot[1])

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
