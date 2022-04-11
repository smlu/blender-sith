from ijim.material.material import importMatFile
from ijim.types.vector import Vector3f
from ijim.utils.utils import *
from .model3do import GeometryMode

import math
import os.path
import re
from typing import List

import bpy
import mathutils

kImEulerOrder     = "YXZ"        # Infernal machine euler orientation order
kGModel3do        = "Model3do"
kModelRadius      = "MODEL_RADIUS_"
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

def getOrderedNameIdx(name):
    str_idx = re.findall("^{}([0-9]+)_".format(kNameOrderPrefix), name)[0]
    return int(str_idx)

def stripOrderPrefix(name):
    return re.sub("^{}([0-9]+)_".format(kNameOrderPrefix), "", name)

def getRadius(obj):
    if obj is None:
        return 0
    bx = obj.dimensions[0]
    by = obj.dimensions[1]
    bz = obj.dimensions[2]
    r2 = math.pow(bx, 2) + math.pow(by, 2) + math.pow(bz, 2)
    return math.sqrt(r2) /2

def rot_matrix(pitch, yaw, roll):
    p = math.radians(pitch)
    y = math.radians(yaw)
    r = math.radians(roll)
    return mathutils.Matrix.Rotation(y, 3, 'Z') * \
           mathutils.Matrix.Rotation(p, 3, 'X') * \
           mathutils.Matrix.Rotation(r, 3, 'Y')

def makeEulerRotation(rot: Vector3f):
    return rot_matrix(rot[0], rot[1], rot[2]).to_euler(kImEulerOrder)
    # p = math.radians(rot[0])
    # y = math.radians(rot[1])
    # r = math.radians(rot[2])
    # return mathutils.Euler((p, r, y), kImEulerOrder)

def setObjEulerRotation(obj: bpy.types.Object, rotation: Vector3f):
    obj.rotation_mode  = kImEulerOrder
    obj.rotation_euler = makeEulerRotation(rotation)

def makeQuaternionRotation(rot: Vector3f):
    return rot_matrix(rot[0], rot[1], rot[2]).to_quaternion()
    # p = mathutils.Quaternion((1.0, 0.0, 0.0), math.radians(rot[0]))
    # y = mathutils.Quaternion((0.0, 0.0, 1.0), math.radians(rot[1]))
    # r = mathutils.Quaternion((0.0, 1.0, 0.0), math.radians(rot[2]))
    # return   y * p * r

def setObjQuaternionRotation(obj: bpy.types.Object, rotation: Vector3f):
    obj.rotation_mode = 'QUATERNION'
    obj.rotation_quaternion = makeQuaternionRotation(rotation)

def eulerToImEuler(euler, order):
    if order != kImEulerOrder:
        euler = mathutils.Euler(euler, order)
        euler.order = kImEulerOrder
    rot = []
    for a in euler:
        d = math.degrees(a)
        rot.append(d)
    return Vector3f(rot[0], rot[2], rot[1])

def quaternionToImEuler(quaternion: mathutils.Quaternion):
    assert  type(quaternion) is mathutils.Quaternion
    qrot = quaternion.normalized()
    return eulerToImEuler(qrot.to_euler(kImEulerOrder), kImEulerOrder)

def getObj_ImEulerOrientation(obj: bpy.types.Object):
    erot = None
    eorder = kImEulerOrder
    rmode = obj.rotation_mode
    if rmode == "QUATERNION":
        qrot = obj.rotation_quaternion.normalized()
        erot = qrot.to_euler(kImEulerOrder)
    elif rmode == "AXIS_ANGLE":
        qrot = mathutils.Quaternion(obj.rotation_axis_angle)
        qrot.normalize()
        erot.to_euler(kImEulerOrder)
    else:
        erot = obj.rotation_euler.copy()
        eorder = rmode

    return eulerToImEuler(erot, eorder)

def getObjPivot(obj: bpy.types.Object):
    for c in obj.constraints:
        if type(c) is bpy.types.PivotConstraint:
            pivot = -c.offset
            if c.target:
                pivot += -c.target.location
            return mathutils.Vector(pivot)
    return mathutils.Vector((0.0, 0.0, 0.0))

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
        for path in search_paths:
            mat_path = getFilePathInDir(name, path)
            if mat_path is not None:
                importMatFile(mat_path)
                break
