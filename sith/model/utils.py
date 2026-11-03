# Sith Blender Addon
# Copyright (C) 2019-2026 Crt Vavros
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import bpy, bmesh, mathutils, math, re
import hashlib
import struct
import json
import numpy as np

from pathlib import Path
from ..material import ColorMap, importMat
from ..material.mat import kMatCelImagePrefix
from ..types import Vector3f, Vector4f
from ..utils import *
from typing import List, Optional, Union

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
k3doUvAbsolute     = "3do_uv_absolute"
k3doLooseColors    = "3do_loose_vertex_colors"
kDefaultFaceColor  = Vector4f(0.0, 0.0, 0.0, 1.0)  # Black color
kImEulerOrder      = "YXZ"                         # Infernal machine euler orientation order Y - roll, X - pitch, Z - yaw
kMeshRadius        = "MESH_RADIUS_"
kModelRadius       = "MODEL_RADIUS_"
kNameOrderPrefix   = "no"

kModel3doGeometryMode = "sith_model3do_geometry_mode"
kModel3doRadius       = "_sith_radius"
kModel3doRadiusShape  = "_sith_radius_shape"
kModel3doRadiusKind   = "_sith_radius_kind"
kModel3doImportReport = "_sith_import_report"
kModel3doShadow       = "sith_model3do_shadow"
kModel3doBinaryModel  = "_sith_modl_model"
kModel3doBinaryMesh   = "_sith_modl_mesh"
kModel3doBinaryNode   = "_sith_modl_node"
k3doBinaryVertex     = "3do_binary_vertex"
k3doBinaryFace       = "3do_binary_face"
k3doBinaryNormal     = "3do_binary_normal"


def getModel3doBinaryData(owner, key):
    """Read opaque MODL metadata without silently accepting damaged .blend data."""
    value = owner.get(key)
    if value is None:
        return None
    try:
        result = json.loads(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Invalid Grim Fandango metadata on '{owner.name}'") from error
    if not isinstance(result, dict):
        raise ValueError(f"Invalid Grim Fandango metadata on '{owner.name}'")
    return result


def bmFaceSeqGetLayerString(faces: bmesh.types.BMFaceSeq, name: str, makeLayer: bool = True) -> Optional[bmesh.types.BMLayerItem]:
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
    from .model3doPreview import initBMeshPreview
    initBMeshPreview(bm)

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
    from .model3doPreview import setFacePreview
    setFacePreview(face, bmesh, color)

def makeOrderedName(name: str, order: int, maxOrder: int) -> str:
    padding = len(str(maxOrder))
    name_format = "{}" + "{:0" + str(padding) + "d}" + "_{}"
    return name_format.format(kNameOrderPrefix, order, name)

def isOrderPrefixed(name: str) -> bool:
    return re.match(f"^{kNameOrderPrefix}([0-9]+)_", name) is not None

def getOrderedNameIdx(name: str) -> int:
    str_idx = re.findall(f"^{kNameOrderPrefix}([0-9]+)_", name)[0]
    return int(str_idx)

def stripOrderPrefix(name: str) -> str:
    return re.sub(f"^{kNameOrderPrefix}([0-9]+)_", "", name)

def _get_scene_obj(name: str) -> Optional[bpy.types.Object]:
    try:
        return bpy.context.scene.objects[name]
    except:
        return None

def isRadiusObj(obj):
    """Match owned helper lookup: markers first, legacy name prefixes otherwise."""
    if kModel3doRadiusKind in obj:
        return obj.get(kModel3doRadiusKind) in (kMeshRadius, kModelRadius)
    return obj.name.startswith((kMeshRadius, kModelRadius))


def _get_radius_child(obj, kind):
    # Parenting establishes ownership; names are only a legacy fallback for
    # helpers created before the explicit kind marker was introduced.
    helpers = [child for child in obj.children
               if child.get(kModel3doRadiusKind) == kind
               or (kModel3doRadiusKind not in child and child.name.startswith(kind))]
    if len(helpers) > 1:
        raise ValueError(f"Multiple radius helpers belong to '{obj.name}'")
    return helpers[0] if helpers else None


def getModelRadiusObj(obj: bpy.types.Object) -> Optional[bpy.types.Object]:
    return _get_radius_child(obj, kModelRadius)

def getMeshObjectByName(meshName: str) -> bpy.types.Object:
    if meshName in bpy.context.scene.objects:
        return bpy.context.scene.objects[meshName]
    for o in bpy.context.scene.objects:
        if meshName == stripOrderPrefix(o.name):
            return o
        if o.data is not None and o.data.name == meshName:
            return o
    raise ValueError(f"Could not find mesh object with name '{meshName}'")

def getMeshRadiusObj(mesh, obj=None) -> Optional[bpy.types.Object]: # mesh is Mesh3do
    if obj is None:
        try:
            obj = getMeshObjectByName(mesh.name)
        except ValueError:
            return None
    return _get_radius_child(obj, kMeshRadius)

def makeRotationMatrix(pitch: float, yaw: float, roll: float) -> mathutils.Matrix:
    p = math.radians(pitch)
    y = math.radians(yaw)
    r = math.radians(roll)

    # rotate arount yaw then pitch and then roll
    return mathutils.Matrix.Rotation(y, 3, 'Z') @ \
           mathutils.Matrix.Rotation(p, 3, 'X') @ \
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

def quaternionToImEuler(quaternion: mathutils.Quaternion, compatible: Optional[mathutils.Euler] = None) -> mathutils.Euler:
    """Convert rotation order, optionally staying near a previous Euler branch."""
    assert type(quaternion) is mathutils.Quaternion
    qrot = quaternion.normalized()

    if compatible is not None:
        return qrot.to_euler(kImEulerOrder, compatible)
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
    """Read the active Blender rotation representation and return engine degrees."""
    euler = None
    if obj.rotation_mode == "QUATERNION":
        euler = quaternionToImEuler(obj.rotation_quaternion)
    elif obj.rotation_mode == "AXIS_ANGLE":
        rotation = obj.rotation_axis_angle
        if not all(math.isfinite(value) for value in rotation):
            raise ValueError('Cannot export a nonfinite axis-angle rotation')

        angle = rotation[0]
        axis = mathutils.Vector(rotation[1:])
        if axis.length < 1.0e-12:
            if abs(angle) > 1.0e-12:
                raise ValueError('Cannot export a nonzero rotation about a zero-length axis')
            # Zero angle has no preferred axis; use a valid one for conversion.
            axis = mathutils.Vector((0.0, 0.0, 1.0))

        # Blender stores (angle, axisX, axisY, axisZ), not quaternion components.
        qrot = mathutils.Quaternion(axis, angle)
        euler = quaternionToImEuler(qrot)
    else:
        euler = mathutils.Euler(obj.rotation_euler, obj.rotation_mode)

    return eulerToPYR(euler)


def objPivot(obj: bpy.types.Object, *, forAnimation=False) -> mathutils.Vector:
    """Convert a supported world-space Pivot to the joint's local offset.

    Static 3DO export can resolve world targets/absolute pivots. KEY positions
    require a constant relative offset; bake world-anchored constraints first.
    """
    constraints = [c for c in obj.constraints if c.type == 'PIVOT' and not c.mute and c.influence]
    if not constraints:
        return mathutils.Vector((0.0, 0.0, 0.0))
    if len(constraints) != 1:
        raise ValueError(f"Bake multiple Pivot constraints on '{obj.name}' before export")

    c = constraints[0]
    if c.influence != 1.0:
        raise ValueError(f"Apply partial Pivot constraint influence on '{obj.name}' before export")
    if c.owner_space != 'WORLD' or (c.target and (c.target_space != 'WORLD' or c.subtarget)):
        raise ValueError(f"Bake unsupported Pivot constraint spaces/bone targets on '{obj.name}' before export")
    if forAnimation and (c.target or not c.use_relative_location):
        raise ValueError(f"Bake world-anchored Pivot constraints on '{obj.name}' before KEY import/export")

    # Blender rotates the owner-to-pivot vector in world space, not in the
    # target's local space. Read evaluated target/parent transforms so parenting
    # and constraints on the target are included before converting coordinates.
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    parent = (obj.parent.evaluated_get(depsgraph).matrix_world @ obj.matrix_parent_inverse
              if obj.parent else mathutils.Matrix.Identity(4))
    if not all(math.isfinite(value) for row in parent for value in row):
        raise ValueError('Pivot parent transforms must be finite')

    # A world-space Pivot's total rotation cannot in general be represented by
    # a fixed local pivot under rotated/nonuniform/reflected parent transforms.
    factor = parent[0][0]
    if factor <= 0 or any(abs(parent[row][column] - (factor if row == column else 0)) > 1e-6
                          for row in range(3) for column in range(3)):
        raise ValueError(f"Bake Pivot constraints under rotated/nonuniform parents on '{obj.name}' before export")
    if any(value <= 0 for value in obj.scale):
        raise ValueError(f"Apply reflected/zero scale on Pivot-constrained object '{obj.name}' before export")

    # Honor the static rotation-range gate. Animated conditional pivots are
    # rejected by KEY export, which samples channels without evaluating stacks.
    if c.rotation_range != 'ALWAYS_ACTIVE':
        order = obj.rotation_mode if obj.rotation_mode not in ('QUATERNION', 'AXIS_ANGLE') else 'XYZ'
        rotation = obj.matrix_basis.to_3x3().normalized().to_euler(order)
        angle = rotation['XYZ'.index(c.rotation_range[-1])]
        if (c.rotation_range.startswith('N') and angle > 0) or (not c.rotation_range.startswith('N') and angle < 0):
            return mathutils.Vector((0.0, 0.0, 0.0))

    offset = mathutils.Vector(c.offset)
    owner = parent @ obj.location
    if c.target:
        pivot = c.target.evaluated_get(depsgraph).matrix_world.translation + offset
    elif c.use_relative_location:
        pivot = owner + offset
    else:
        pivot = offset

    if not all(math.isfinite(value) for value in (*pivot, *owner)):
        raise ValueError('Pivot coordinates must be finite')
    return -(pivot - owner) / factor


def validateObjInstancing(obj):
    """Instance geometry is not present in raw mesh data or ordinary children."""
    if obj.instance_type != 'NONE':
        raise ValueError(f"Make instances on '{obj.name}' real and disable {obj.instance_type} instancing before 3DO/KEY export")


def validateObjTransform(obj, scale=(1.0, 1.0, 1.0)):
    """Reject unapplied transforms that the channel-based exporter would drop."""
    validateObjInstancing(obj)
    if obj.parent and obj.parent_type != 'OBJECT':
        raise ValueError(f"Bake {obj.parent_type} parenting on '{obj.name}' to ordinary object parenting before 3DO/KEY export")
    if any(not constraint.mute and constraint.influence and constraint.type != 'PIVOT'
           for constraint in obj.constraints):
        raise ValueError(f"Bake non-pivot constraints on '{obj.name}' to transform channels before export")

    # 1. Local channels alone do not contain Blender's parent-inverse matrix or
    # delta transforms. Require those to be applied before copying local poses.
    if any(not math.isfinite(value) for row in obj.matrix_parent_inverse for value in row):
        raise ValueError(f"Parent inverse on '{obj.name}' must be finite")
    if any(abs(obj.matrix_parent_inverse[row][column] - (row == column)) > 1e-6
           for row in range(4) for column in range(4)):
        raise ValueError(f"Apply parent inverse on '{obj.name}' before export (preserving its visible transform)")

    deltaRotation = (tuple(obj.delta_rotation_quaternion) != (1.0, 0.0, 0.0, 0.0)
                     if obj.rotation_mode == 'QUATERNION' else any(obj.delta_rotation_euler))
    if any(obj.delta_location) or tuple(obj.delta_scale) != (1.0, 1.0, 1.0) or deltaRotation:
        raise ValueError(f"Apply delta transforms on '{obj.name}' before export")

    # 2. Validate values before using them in mesh scaling or rotation matrices.
    if not all(math.isfinite(value) for value in (*obj.location, *obj.scale, *scale)):
        raise ValueError(f"Transforms on '{obj.name}' must be finite")

    rotation = makeRotationMatrix(*objRotationToPYR(obj))
    if not all(math.isfinite(value) for row in rotation for value in row):
        raise ValueError(f"Rotation on '{obj.name}' must be finite")

    # 3. Baking inherited scale into geometry moves it across the child rotation.
    # This is equivalent only when S*R == R*S; their matrix-entry difference is
    # (scale[row] - scale[column]) * R[row][column]. Otherwise shear is lost.
    tolerance = 1e-6 * max(1.0, *(abs(value) for value in scale))
    if any(abs((scale[row] - scale[column]) * rotation[row][column]) > tolerance
           for row in range(3) for column in range(3)):
        raise ValueError(f"Apply nonuniform parent scale before exporting rotated object '{obj.name}'")


def validateMeshGeometry(obj):
    """Require live mesh effects to be applied before reading raw geometry."""
    if any(modifier.show_viewport for modifier in obj.modifiers):
        raise ValueError(f"Apply visible mesh modifiers on '{obj.name}' before 3DO export")
    keys = obj.data.shape_keys
    if keys and ((not keys.use_relative and len(keys.key_blocks) > 1)
                 or (obj.show_only_shape_key and obj.active_shape_key_index > 0)
                 or any(not key.mute and key.value != 0 for key in keys.key_blocks[1:])):
        raise ValueError(f"Bake shape-key deformation on '{obj.name}' into the mesh before 3DO export")


def objRadius(obj, scale: mathutils.Vector = mathutils.Vector((1.0,) * 3)) -> float:
    r = 0
    if obj is not None and obj.type == 'MESH':
        for v in obj.data.vertices:
            vl = vectorMultiply(v.co, scale).length
            if vl > r:
                r = vl
    return r

def getDrawType(geo_mode: GeometryMode) -> str:
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

def objGeometryMode(obj: bpy.types.Object) -> GeometryMode:
    if obj.is_property_set(kModel3doGeometryMode):
        return GeometryMode[getattr(obj, kModel3doGeometryMode)]
    dt: str = obj.display_type
    if dt == 'BOUNDS':
        return GeometryMode.NotDrawn
    elif dt == 'WIRE':
        return GeometryMode.Wireframe
    elif dt == 'SOLID':
        return GeometryMode.Solid
    elif dt == 'TEXTURED':
        return GeometryMode.Texture
    raise ValueError(f'Unknown draw type {dt}')


def radiusShapeSignature(obj):
    value = hashlib.sha256()
    for vertex in obj.data.vertices:
        value.update(struct.pack('<3f', *vertex.co))
    return value.hexdigest()


def radiusHelperValue(obj, scale):
    """Read an authored sphere or measure an edited radius helper in export units."""
    # Helpers skip the rendered-mesh path, but must not bypass its safety checks.
    if obj.type != 'MESH' or obj.data is None:
        raise ValueError(f"Radius helper '{obj.name}' must be a mesh")
    validateObjInstancing(obj)
    if obj.parent and obj.parent_type != 'OBJECT':
        raise ValueError(f"Bake {obj.parent_type} parenting on radius helper '{obj.name}' before 3DO export")
    if any(not constraint.mute and constraint.influence for constraint in obj.constraints):
        raise ValueError(f"Apply active constraints on radius helper '{obj.name}' before 3DO export")
    validateMeshGeometry(obj)
    if obj.mode == 'EDIT':
        # Read live edits before comparing the stored sphere signature.
        obj.update_from_editmode()

    # 1. Helpers must stay centered. Combine their local basis with inherited
    # scale before measuring either the stored sphere or its edited vertices.
    local = obj.matrix_parent_inverse @ obj.matrix_basis
    if any(not math.isfinite(value) for value in (*scale, *(value for row in local for value in row))):
        raise ValueError('Radius helper transforms must be finite')
    if local.translation.length > 1e-6:
        raise ValueError('Radius helpers must remain centered on their parent')

    linear = mathutils.Matrix.Diagonal(scale) @ local.to_3x3()
    original = obj.get(kModel3doRadius)
    if original is not None and obj.get(kModel3doRadiusShape) == radiusShapeSignature(obj):
        # 2. For an unedited helper, use the original mathematical sphere rather
        # than underestimate its radius from a finite set of sphere-mesh samples.
        if not math.isfinite(original) or original < 0:
            raise ValueError('Radius must be finite and nonnegative')
        # The largest singular value bounds a sphere under rotated nonuniform scales.
        factor = float(np.linalg.svd(np.asarray(linear, dtype=np.float64), compute_uv=False)[0])
        return original * factor

    # 3. An edited helper intentionally defines a new bound; measure its vertices.
    radii = [(linear @ vertex.co).length for vertex in obj.data.vertices]
    if any(not math.isfinite(radius) for radius in radii):
        raise ValueError('Radius helper vertices must be finite')

    return max(radii, default=0.0)

def getMaterialImage(mat):
    """Resolve MAT cel 0 or the rendered color image used for UV dimensions."""
    image = mat.get(kMatCelImagePrefix + '0')
    if isinstance(image, bpy.types.Image):
        return image
    if not mat.use_nodes or not mat.node_tree:
        return None

    images, visited = set(), set()
    legacy_fallback = True
    unresolved_branch = False

    def color_images(socket):
        nonlocal legacy_fallback, unresolved_branch
        for link in socket.links:
            node = link.from_node
            if node.as_pointer() in visited:
                continue
            visited.add(node.as_pointer())
            if node.type == 'GROUP':
                from .model3doPreview import isPreviewNode
                if isPreviewNode(node):
                    # Derived brightness is not a second texture/UV source.
                    color_images(node.inputs['Base Color'])
                    continue
                legacy_fallback = False
                unresolved_branch = True
                continue
            if node.type == 'TEX_IMAGE':
                if node.image:
                    images.add(node.image)
            else:
                if node.type != 'REROUTE':
                    legacy_fallback = False
                for input in node.inputs:
                    color_images(input)

    def shader_images(socket):
        nonlocal legacy_fallback, unresolved_branch
        for link in socket.links:
            node = link.from_node
            if node.as_pointer() in visited:
                continue
            visited.add(node.as_pointer())
            if node.type == 'GROUP':
                legacy_fallback = False
                unresolved_branch = True
                continue
            color = node.inputs.get('Base Color') or node.inputs.get('Color')
            if color is not None:
                color_images(color)
            elif node.type in ('MIX_SHADER', 'ADD_SHADER', 'REROUTE'):
                legacy_fallback = False
                for input in node.inputs:
                    if input.type == 'SHADER':
                        shader_images(input)
            else:
                legacy_fallback = False
                unresolved_branch = True

    for node in mat.node_tree.nodes:
        if node.type == 'OUTPUT_MATERIAL' and node.is_active_output:
            shader_images(node.inputs['Surface'])
    # A known image in one branch cannot supply dimensions for an opaque
    # sibling group/shader. Require the explicit MAT binding instead of guessing.
    if unresolved_branch:
        raise ValueError(f"Cannot resolve every color texture image for material '{mat.name}'; bind MAT cel 0 or simplify the material before UV conversion")
    if not images and legacy_fallback:
        # Older imported materials may have one image without color links.
        images = {node.image for node in mat.node_tree.nodes if node.type == 'TEX_IMAGE' and node.image}
    if len(images) > 1:
        raise ValueError(f"Ambiguous texture images for material '{mat.name}'; bind MAT cel 0 or use one color texture before UV conversion")
    return next(iter(images), None)


def importMaterials(mat_names: List[Union[Path, str]], search_paths: List[Union[Path, str]], cmp: ColorMap):
    def skip_loading_mat(mat):
        if mat.use_nodes and mat.node_tree:
            for node in mat.node_tree.nodes:
                if node.type == 'TEX_IMAGE' and node.image:
                    return True
        return False

    for name in mat_names:
        if name in bpy.data.materials:
            if skip_loading_mat(bpy.data.materials[name]):
                continue
        for path in search_paths:
            try:
                mat_path = getFilePathInDir(name, path)
                if mat_path is not None:
                    importMat(mat_path, cmp)
                    break
            except Exception as e:
                # Optional textures can be absent, ambiguous or unreadable.
                # Retain the model and try the remaining search folders.
                print("Warning: Couldn't load material: ", os.path.join(path, name))
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
