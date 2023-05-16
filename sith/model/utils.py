# Sith Blender Addon
# Copyright (c) 2019-2023 Crt Vavros

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

import bpy, bmesh, mathutils, math, re

from sith.material import ColorMap, importMat
from sith.types import Vector3f, Vector4f
from sith.utils import *
from typing import List

from .model3do import (
    FaceType,
    GeometryMode,
    LightMode,
    TextureMode
)

k3doFaceExtraLight = "3do_face_extra_light"
k3doFaceType       = "3do_face_type"
k3doGeometryMode   = "3do_geometry_mode"
k3doLightingMode   = "3do_lighting_mode"
k3doTextureMode    = "3do_texture_mode"
kDefaultFaceColor  = Vector4f(0.0, 0.0, 0.0, 1.0)  # Black color
kGModel3do         = "Model3do"
kImEulerOrder      = "YXZ"                         # Infernal machine euler orientation order Y - roll, X - pitch, Z - yaw
kMeshRadius        = "MESH_RADIUS_"
kModelRadius       = "MODEL_RADIUS_"
kNameOrderPrefix   = "no"


def bmFaceSeqGetLayerString(faces: bmesh.types.BMFaceSeq, name: str, makeLayer=True) -> bmesh.types.BMLayerItem:
    return faces.layers.string.get(name) or (faces.layers.string.new(name) if makeLayer else None)

def __bmface_get_int_property(face: bmesh.types.BMFace, tag: bmesh.types.BMLayerItem, default: int) -> int:
    if tag:
        v = face[tag]
        if len(v) > 0:
            return int(v)
    return default

def __bmface_set_int_property(face: bmesh.types.BMFace, tag: bmesh.types.BMLayerItem, value: int):
    face[tag] = str(int(value)).encode('utf-8')

def __bmface_get_vector4_property(face: bmesh.types.BMFace, tag: bmesh.types.BMLayerItem, default: Vector4f) -> Vector4f:
    if tag:
        v = face[tag]
        if len(v) > 0:
            return Vector4f(*[float(c) for c in v.decode('utf8').split(',')])
    return default

def __bmface_set_vector4_property(face: bmesh.types.BMFace, tag: bmesh.types.BMLayerItem, vector: Vector4f):
    face[tag] = str(','.join(str(c) for c in vector)).encode('utf-8')

def bmMeshInit3doLayers(bm: bmesh.types.BMesh):
    bmFaceSeqGetLayerString(bm.faces, k3doFaceType,       makeLayer=True)
    bmFaceSeqGetLayerString(bm.faces, k3doGeometryMode,   makeLayer=True)
    bmFaceSeqGetLayerString(bm.faces, k3doLightingMode,   makeLayer=True)
    bmFaceSeqGetLayerString(bm.faces, k3doTextureMode,    makeLayer=True)
    bmFaceSeqGetLayerString(bm.faces, k3doFaceExtraLight, makeLayer=True)
    bm.faces.layers.int.verify()

def bmFaceGetType(face: bmesh.types.BMFace, bm: bmesh.types.BMesh) -> FaceType:
    """
    Returns the value of 3DO polygon face type stored in layer of `BMFace`.
    If type layer doesn't exists it returns 0.
    """
    tag = bmFaceSeqGetLayerString(bm.faces, k3doFaceType, makeLayer=False)
    return FaceType(__bmface_get_int_property(face, tag, 0))

def bmFaceSetType(face: bmesh.types.BMFace, bm: bmesh.types.BMesh, t: FaceType):
    """
    Stores the new value of 3DO polygon face in layer of `BMFace`.
    Note: Layer must be already initialized at this point.
          Invoke `bmMeshInit3doLayers` to initialize layer prior to modify any face of `bm`
    """
    tag = bmFaceSeqGetLayerString(bm.faces, k3doFaceType, makeLayer=False)
    __bmface_set_int_property(face, tag, t)

def bmFaceGetGeometryMode(face: bmesh.types.BMFace, bmesh: bmesh.types.BMesh) -> GeometryMode:
    """
    Returns the geometry mode of 3DO polygon face stored in layer of `BMFace`.
    If type layer doesn't exists it returns `GeometryMode.Texture`.
    """
    tag = bmFaceSeqGetLayerString(bmesh.faces, k3doGeometryMode, makeLayer=False)
    return GeometryMode(__bmface_get_int_property(face, tag, GeometryMode.Texture))

def bmFaceSetGeometryMode(face: bmesh.types.BMFace, bmesh: bmesh.types.BMesh, geo: GeometryMode):
    """
    Stores the new geometry mode of 3DO polygon face in layer of `BMFace`.
    Note: Layer must be already initialized at this point.
          Invoke `bmMeshInit3doLayers` to initialize layer prior to modify any face of `bm`.
    """
    tag = bmFaceSeqGetLayerString(bmesh.faces, k3doGeometryMode, makeLayer=False)
    __bmface_set_int_property(face, tag, geo)

def bmFaceGetLightMode(face: bmesh.types.BMFace, bmesh: bmesh.types.BMesh) -> LightMode:
    """
    Returns the light mode of 3DO polygon face stored in layer of `BMFace`.
    If type layer doesn't exists it returns `LightMode.Gouraud`.
    """
    tag = bmFaceSeqGetLayerString(bmesh.faces, k3doLightingMode, makeLayer=False)
    return LightMode(__bmface_get_int_property(face, tag, LightMode.Gouraud))

def bmFaceSetLightMode(face: bmesh.types.BMFace, bmesh: bmesh.types.BMesh, lm: LightMode):
    """
    Stores the new light mode of 3DO polygon face in layer of `BMFace`.
    Note: Layer must be already initialized at this point.
          Invoke `bmMeshInit3doLayers` to initialize layer prior to modify any face of `bm`.
    """
    tag = bmFaceSeqGetLayerString(bmesh.faces, k3doLightingMode, makeLayer=False)
    __bmface_set_int_property(face, tag, lm)

def bmFaceGetTextureMode(face: bmesh.types.BMFace, bmesh: bmesh.types.BMesh) -> TextureMode:
    """
    Returns the texture mode of 3DO polygon face stored in layer of `BMFace`.
    If type layer doesn't exists it returns `TextureMode.PerspectiveCorrected`.
    """
    tag = bmFaceSeqGetLayerString(bmesh.faces, k3doTextureMode, makeLayer=False)
    return TextureMode(__bmface_get_int_property(face, tag, TextureMode.PerspectiveCorrected))

def bmFaceSetTextureMode(face: bmesh.types.BMFace, bmesh: bmesh.types.BMesh, tex: TextureMode):
    """
    Stores the new texture mode of 3DO polygon face in layer of `BMFace`.
    Note: Layer must be already initialized at this point.
          Invoke `bmMeshInit3doLayers` to initialize layer prior to modify any face of `bm`.
    """
    tag = bmFaceSeqGetLayerString(bmesh.faces, k3doTextureMode, makeLayer=False)
    __bmface_set_int_property(face, tag, tex)

def bmFaceGetExtraLight(face: bmesh.types.BMFace, bmesh: bmesh.types.BMesh) -> Vector4f:
    """
    Returns the extra light color of 3DO polygon face stored in layer of `BMFace`.
    If type layer doesn't exists it returns `kDefaultFaceColor`.
    """
    tag = bmFaceSeqGetLayerString(bmesh.faces, k3doFaceExtraLight, makeLayer=False)
    return __bmface_get_vector4_property(face, tag, kDefaultFaceColor)

def bmFaceSetExtraLight(face: bmesh.types.BMFace, bmesh: bmesh.types.BMesh, color: Vector4f):
    """
    Stores the new extra light color of 3DO polygon face in layer of `BMFace`.
    Note: Layer must be already initialized at this point.
          Invoke `bmMeshInit3doLayers` to initialize layer prior to modify any face of `bm`.
    """
    tag = bmFaceSeqGetLayerString(bmesh.faces, k3doFaceExtraLight, makeLayer=False)
    __bmface_set_vector4_property(face, tag, color)


def makeOrderedName(name, order, maxOrder):
    padding = len(str(maxOrder))
    name_format = "{}" + "{:0" + str(padding) + "d}" + "_{}"
    return name_format.format(kNameOrderPrefix, order, name)

def isOrderPrefixed(name):
    return re.match(f"^{kNameOrderPrefix}([0-9]+)_", name)

def getOrderedNameIdx(name):
    str_idx = re.findall(f"^{kNameOrderPrefix}([0-9]+)_", name)[0]
    return int(str_idx)

def stripOrderPrefix(name):
    return re.sub(f"^{kNameOrderPrefix}([0-9]+)_", "", name)

def _get_scene_obj(name):
    try:
        return bpy.context.scene.objects[name]
    except:
        return None

def getModelRadiusObj(obj):
    return _get_scene_obj(kModelRadius + stripOrderPrefix(obj.name))

def getMeshObjectByName(meshName: str):
    if meshName in bpy.context.scene.objects:
        return bpy.context.scene.objects[meshName]
    for o in bpy.context.scene.objects:
        if meshName == stripOrderPrefix(o.name):
            return o
        if o.data is not None and o.data.name == meshName:
            return o
    raise ValueError(f"Could not find mesh object with name '{meshName}'")

def getMeshRadiusObj(mesh):
    try:
        obj = getMeshObjectByName(mesh.name)
        return _get_scene_obj(kMeshRadius + stripOrderPrefix(obj.name))
    except:
        return None

def makeRotationMatrix(pitch, yaw, roll):
    p = math.radians(pitch)
    y = math.radians(yaw)
    r = math.radians(roll)

    # rotate arount yaw then pitch and then roll
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

def makeQuaternionRotation(pyr: Vector3f) -> mathutils.Quaternion:
    return makeRotationMatrix(pyr[0], pyr[1], pyr[2]).to_quaternion().normalized()
    # p = mathutils.Quaternion((1.0, 0.0, 0.0), math.radians(rot[0]))
    # y = mathutils.Quaternion((0.0, 0.0, 1.0), math.radians(rot[1]))
    # r = mathutils.Quaternion((0.0, 1.0, 0.0), math.radians(rot[2]))
    # return   y * p * r

def objSetRotation(obj: bpy.types.Object, pyr: Vector3f):
    """
    Sets `obj` rotation as quaternion from `pyr` rotation.
    """
    obj.rotation_mode       = 'QUATERNION'
    obj.rotation_quaternion = makeQuaternionRotation(pyr)

def quaternionToImEuler(quaternion: mathutils.Quaternion) -> mathutils.Euler:
    assert type(quaternion) is mathutils.Quaternion
    qrot = quaternion.normalized()
    return qrot.to_euler(kImEulerOrder)

def eulerToPYR(euler: mathutils.Euler) -> Vector3f:
    assert type(euler) is mathutils.Euler
    if euler.order != kImEulerOrder:
        euler = quaternionToImEuler(euler.to_quaternion())
    rot = []
    for a in euler:
        d = math.degrees(a)
        rot.append(d)
    # Blender Euler angles are in order XYZ (pitch, roll, yaw)
    return Vector3f(rot[0], rot[2], rot[1])

def quaternionToPYR(quaternion: mathutils.Quaternion) -> Vector3f:
    assert type(quaternion) is mathutils.Quaternion
    return eulerToPYR(quaternionToImEuler(quaternion))

def objRotationToPYR(obj: bpy.types.Object) -> Vector3f:
    euler = None
    if obj.rotation_mode == "QUATERNION":
        euler = quaternionToImEuler(obj.rotation_quaternion)
    elif obj.rotation_mode == "AXIS_ANGLE": # Note, using axis angles can lead to broken rotations
        qrot = mathutils.Quaternion(obj.rotation_axis_angle)
        euler = quaternionToImEuler(qrot)
    else:
        euler = mathutils.Euler(obj.rotation_euler, obj.rotation_mode)
    return eulerToPYR(euler)

def objPivot(obj: bpy.types.Object) -> mathutils.Vector:
    for c in obj.constraints:
        if type(c) is bpy.types.PivotConstraint:
            pivot = -c.offset
            if c.target:
                pivot += -c.target.location
            return mathutils.Vector(pivot)
    return mathutils.Vector((0.0, 0.0, 0.0))

def objRadius(obj, scale: mathutils.Vector = mathutils.Vector((1.0,) * 3)):
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
    if geo_mode == GeometryMode.VertexOnly:
        return 'WIRE'
    if geo_mode == GeometryMode.Wireframe:
        return 'WIRE'
    if geo_mode == GeometryMode.Solid:
        return 'SOLID'
    if geo_mode == GeometryMode.Texture:
        return 'TEXTURED'
    raise ValueError(f"Unknown geometry mode {geo_mode}")

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
    raise ValueError(f'Unknown draw type {dt}')

def importMaterials(mat_names: List, search_paths: List, cmp: ColorMap):
    def skip_loading_mat(mat):
        for s in mat.texture_slots:
            if s is not None and s.texture is not None:
                return True
        return False

    for name in mat_names:
        if name in bpy.data.materials:
            if skip_loading_mat(bpy.data.materials[name]):
                continue
        for path in search_paths:
            mat_path = getFilePathInDir(name, path)
            if mat_path is not None:
                try:
                    importMat(mat_path, cmp)
                    break
                except Exception as e:
                    print("Warning: Couldn't load material: ", mat_path)
                    print(f'  Error: {e}')

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
