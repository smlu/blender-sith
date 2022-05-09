from ijim.material.material import importMatFile
from ijim.types.vector import Vector3f
from ijim.utils.utils import *
from .model3do import FaceType, GeometryMode, LightMode, TextureMode

import math
import re
from typing import List

import bpy, bmesh
import mathutils

kImEulerOrder     = "YXZ"        # Infernal machine euler orientation order
kGModel3do        = "Model3do"
kModelRadius      = "MODEL_RADIUS_"
kMeshRadius       = "MESH_RADIUS_"
k3doGeometryMode  = "3do_geometry_mode"
k3doLightingMode  = "3do_lighting_mode"
k3doTextureMode   = "3do_texture_mode"
k3doFaceType      = "3do_face_type"
kNameOrderPrefix  = "no"


def bmFaceSeqGetLayerString(faces: bmesh.types.BMFaceSeq, name: str, makeLayer=True) -> bmesh.types.BMLayerItem:
    return faces.layers.string.get(name) or (faces.layers.string.new(name) if makeLayer else None)

def __bmface_get_property(face: bmesh.types.BMFace, tag: bmesh.types.BMLayerItem, default) -> int:
    if tag:
        v = face[tag]
        if len(v) > 0:
            return int(v)
    return default

def __bmface_set_property(face: bmesh.types.BMFace, tag: bmesh.types.BMLayerItem, value: int):
    face[tag] = str(int(value)).encode('utf-8')

def bmMeshInit3doLayers(bm: bmesh.types.BMesh):
    bmFaceSeqGetLayerString(bm.faces, k3doFaceType,     makeLayer=True)
    bmFaceSeqGetLayerString(bm.faces, k3doGeometryMode, makeLayer=True)
    bmFaceSeqGetLayerString(bm.faces, k3doLightingMode, makeLayer=True)
    bmFaceSeqGetLayerString(bm.faces, k3doTextureMode,  makeLayer=True)
    bm.faces.layers.int.verify()

def bmFaceGetType(face: bmesh.types.BMFace, bm: bmesh.types.BMesh) -> FaceType:
    """
    Returns the value of 3DO polygon face type stored in layer of `BMFace`.
    If type layer doesn't exists it returns 0.
    """
    tag = bmFaceSeqGetLayerString(bm.faces, k3doFaceType, makeLayer=False)
    return FaceType(__bmface_get_property(face, tag, 0))

def bmFaceSetType(face: bmesh.types.BMFace, bm: bmesh.types.BMesh, t: FaceType):
    """
    Stores the new value of 3DO polygon face in layer of `BMFace`.
    Note: Layer must be already initialized at this point.
          Invoke `bmMeshInit3doLayers` to initialize layer prior to modify any face of `bm`
    """
    tag = bmFaceSeqGetLayerString(bm.faces, k3doFaceType, makeLayer=False)
    __bmface_set_property(face, tag, t)

def bmFaceGetGeometryMode(face: bmesh.types.BMFace, bmesh: bmesh.types.BMesh) -> GeometryMode:
    """
    Returns the geometry mode of 3DO polygon face stored in layer of `BMFace`.
    If type layer doesn't exists it returns `GeometryMode.Texture`.
    """
    tag = bmFaceSeqGetLayerString(bmesh.faces, k3doGeometryMode, makeLayer=False)
    return GeometryMode(__bmface_get_property(face, tag, GeometryMode.Texture))

def bmFaceSetGeometryMode(face: bmesh.types.BMFace, bmesh: bmesh.types.BMesh, geo: GeometryMode):
    """
    Stores the new geometry mode of 3DO polygon face in layer of `BMFace`.
    Note: Layer must be already initialized at this point.
          Invoke `bmMeshInit3doLayers` to initialize layer prior to modify any face of `bm`.
    """
    tag = bmFaceSeqGetLayerString(bmesh.faces, k3doGeometryMode, makeLayer=False)
    __bmface_set_property(face, tag, geo)

def bmFaceGetLightMode(face: bmesh.types.BMFace, bmesh: bmesh.types.BMesh) -> LightMode:
    """
    Returns the light mode of 3DO polygon face stored in layer of `BMFace`.
    If type layer doesn't exists it returns `LightMode.Gouraud`.
    """
    tag = bmFaceSeqGetLayerString(bmesh.faces, k3doLightingMode, makeLayer=False)
    return LightMode(__bmface_get_property(face, tag, LightMode.Gouraud))

def bmFaceSetLightMode(face: bmesh.types.BMFace, bmesh: bmesh.types.BMesh, lm: LightMode):
    """
    Stores the new light mode of 3DO polygon face in layer of `BMFace`.
    Note: Layer must be already initialized at this point.
          Invoke `bmMeshInit3doLayers` to initialize layer prior to modify any face of `bm`.
    """
    tag = bmFaceSeqGetLayerString(bmesh.faces, k3doLightingMode, makeLayer=False)
    __bmface_set_property(face, tag, lm)

def bmFaceGetTextureMode(face: bmesh.types.BMFace, bmesh: bmesh.types.BMesh) -> TextureMode:
    """
    Returns the texture mode of 3DO polygon face stored in layer of `BMFace`.
    If type layer doesn't exists it returns `TextureMode.PerspectiveCorrected`.
    """
    tag = bmFaceSeqGetLayerString(bmesh.faces, k3doTextureMode, makeLayer=False)
    return TextureMode(__bmface_get_property(face, tag, TextureMode.PerspectiveCorrected))

def bmFaceSetTextureMode(face: bmesh.types.BMFace, bmesh: bmesh.types.BMesh, tex: TextureMode):
    """
    Stores the new texture mode of 3DO polygon face in layer of `BMFace`.
    Note: Layer must be already initialized at this point.
          Invoke `bmMeshInit3doLayers` to initialize layer prior to modify any face of `bm`.
    """
    tag = bmFaceSeqGetLayerString(bmesh.faces, k3doTextureMode, makeLayer=False)
    __bmface_set_property(face, tag, tex)

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

def makeRotationMatrix(pitch, yaw, roll):
    p = math.radians(pitch)
    y = math.radians(yaw)
    r = math.radians(roll)
    return mathutils.Matrix.Rotation(y, 3, 'Z') * \
           mathutils.Matrix.Rotation(p, 3, 'X') * \
           mathutils.Matrix.Rotation(r, 3, 'Y')

def makeEulerRotation(pyr: Vector3f):
    return makeRotationMatrix(pyr[0], pyr[1], pyr[2]).to_euler(kImEulerOrder)
    # p = math.radians(rot[0])
    # y = math.radians(rot[1])
    # r = math.radians(rot[2])
    # return mathutils.Euler((p, r, y), kImEulerOrder)

def objSetEulerRotation(obj: bpy.types.Object, rotation: Vector3f):
    obj.rotation_mode  = kImEulerOrder
    obj.rotation_euler = makeEulerRotation(rotation)

def makeQuaternionRotation(pyr: Vector3f):
    return makeRotationMatrix(pyr[0], pyr[1], pyr[2]).to_quaternion()
    # p = mathutils.Quaternion((1.0, 0.0, 0.0), math.radians(rot[0]))
    # y = mathutils.Quaternion((0.0, 0.0, 1.0), math.radians(rot[1]))
    # r = mathutils.Quaternion((0.0, 1.0, 0.0), math.radians(rot[2]))
    # return   y * p * r

def objSetRotation(obj: bpy.types.Object, pyr: Vector3f):
    """
    Sets `obj` rotation as quaterion from `pyr` rotation.
    """
    obj.rotation_mode       = 'QUATERNION'
    obj.rotation_quaternion = makeQuaternionRotation(pyr)

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
    assert type(quaternion) is mathutils.Quaternion
    qrot = quaternion.normalized()
    return eulerToImEuler(qrot.to_euler(kImEulerOrder), kImEulerOrder)

def objOrientationToImEuler(obj: bpy.types.Object):
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

def objPivot(obj: bpy.types.Object):
    for c in obj.constraints:
        if type(c) is bpy.types.PivotConstraint:
            pivot = -c.offset
            if c.target:
                pivot += -c.target.location
            return mathutils.Vector(pivot)
    return mathutils.Vector((0.0, 0.0, 0.0))

def objRadius(obj, scale: mathutils.Vector = mathutils.Vector((1.0,)*3)):
    r = 0
    if obj is not None and obj.type == 'MESH':
        for v in obj.data.vertices:
            vl = vectorMultiply(v.co, scale).length
            if vl > r:
                r = vl
    return r

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

def objGeometryMode(obj: bpy.types.Object):
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
                try:
                    importMatFile(mat_path)
                    break
                except Exception as e:
                    print("Warning: Couldn't load material: ", mat_path)
                    print("  Error: {}".format(e))


def _vector_component_op(a: mathutils.Vector, b: mathutils.Vector, oopfunc) -> mathutils.Vector:
    c = a.copy()
    l = min(len(a), len(b))
    for i in range(0, l):
        c[i] = oopfunc(c[i], b[i])
    return c

def vectorMultiply(a: mathutils.Vector, b: mathutils.Vector) -> mathutils.Vector:
    """
    Multiplies vector by another vector (component-wise, not cross or dot product) and returns result vector.
    """
    return _vector_component_op(a, b, lambda a,b: a * b)

def vectorDivide(a: mathutils.Vector, b: mathutils.Vector) -> mathutils.Vector:
    """
    Divides vector by another vector (component-wise, not cross or dot product) and returns result vector.
    """
    return _vector_component_op(a, b, lambda a,b: a / b)
