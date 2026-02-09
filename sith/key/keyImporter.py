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

from xmlrpc.client import Boolean
import bpy, mathutils

from ..model.utils import *
from ..types import BenchmarkMeter
from ..utils import *

from typing import Optional

from .key import *
from . import keyLoader

def importKey(keyPath: str, scene: bpy.types.Scene, clearScene: bool, validateActiveObject: bool, namedMarkers: bool):
    with BenchmarkMeter(' done in {:.4f} sec.'):
        print("importing KEY: %r..." % (keyPath), end="")

        key = keyLoader.loadKey(keyPath)

        # Check selected object or find anim object in the scene
        obj = bpy.context.view_layer.objects.active
        if obj:
            obj = _get_parent(obj)
            if validateActiveObject and not _check_obj(obj, key.nodes, key.numJoints):
                raise ValueError(f"Selected object '{obj.name}' doesn't contain all required nodes to animate!")
        else:
            obj = _find_anim_obj_in_scene(scene, key.nodes, key.numJoints)
            if obj is None:
                raise ValueError(f"Couldn't find a valid object to animate!")

        if clearScene:
            clearSceneAnimData(scene)

        scene.frame_start     = 0
        scene.frame_end       = key.numFrames - 1 if clearScene else max(scene.frame_end, key.numFrames - 1)
        scene.frame_step      = 1
        scene.render.fps      = int(key.fps)
        scene.render.fps_base = 1.0

        if clearScene:
            scene.sith_key_flags = key.flags.toSet()
            scene.sith_key_types = key.nodeTypes.hex()

        for m in key.markers:
            marker_name = str(m.type.value)
            if namedMarkers:
                marker_name = m.type.name
            scene.timeline_markers.new(marker_name, frame=int(m.frame))

        for node in key.nodes:
            # Get object to animate
            aobj = _find_joint_obj_for_anim_node(obj, node, key.numJoints)
            if aobj is None:
                print(f"Couldn't find joint object '{node.meshName}' to animate!")
                continue

            # Add object's keyframes
            for keyframe in node.keyframes:
                _set_obj_location(aobj, keyframe.position)
                aobj.keyframe_insert(data_path="location", frame=keyframe.frame)

                objSetRotation(aobj, keyframe.orientation)
                aobj.keyframe_insert(data_path=_get_rotation_data_path(aobj), frame=keyframe.frame)

            # Fix any broken interpolation between keyframes
            _fix_obj_anim_interpolation(aobj)

        # Set current frame to 0
        scene.frame_set(0)

def _set_obj_location(obj: bpy.types.Object, location: Vector3f):
    obj.location = location

    # Substract pivot offset from location
    for c in obj.constraints:
        if type(c) is bpy.types.PivotConstraint:
            pivot = -c.offset
            if c.target:
                pivot += -c.target.location
            obj.location += mathutils.Vector(pivot)
            break

def _can_animate_obj(obj: bpy.types.Object, node:KeyNode, maxJoints: int) -> bool:
    if obj.sith_model3do_hnode_idx > -1 and obj.sith_model3do_hnode_idx < maxJoints:
            if obj.sith_model3do_hnode_idx == node.idx:
                return True
    elif obj.sith_model3do_hnode_name.lower() == node.meshName.lower():
        return True
    elif node.meshName.lower() == obj.name.lower():
        return True
    elif isOrderPrefixed(obj.name) and getOrderedNameIdx(obj.name) == node.idx:
        return True
    return False

def _find_joint_obj_for_anim_node(obj: bpy.types.Object, node: KeyNode, maxJoints: int ) -> Optional[bpy.types.Object]:
    if _can_animate_obj(obj, node, maxJoints):
            return obj
    for cobj in obj.children:
        jobj =  _find_joint_obj_for_anim_node(cobj, node, maxJoints)
        if jobj:
            return jobj
    return None

def _check_obj(obj, nodes: List[KeyNode], maxJoints: int) -> bool:
    for node in nodes:
        if _find_joint_obj_for_anim_node(obj, node, maxJoints) is None:
            return False
    return True

def _find_anim_obj_in_scene(scene: bpy.types.Scene, nodes: List[KeyNode], maxJoints: int) -> Optional[bpy.types.Object]:
    for obj in scene.objects:
        if obj.parent is not None:
            continue
        if _check_obj(obj, nodes, maxJoints):
            return obj
    return None

def _get_parent(obj: bpy.types.Object) -> bpy.types.Object:
    while obj.parent is not None:
        obj = obj.parent
    return obj

def _get_rotation_data_path(obj: bpy.types.Object) -> str:
    if obj.rotation_mode == 'QUATERNION':
        return 'rotation_quaternion'
    elif obj.rotation_mode == 'AXIS_ANGLE':
        return 'rotation_axis_angle'
    else:
        return 'rotation_euler'

def _get_channelbag_fcurves(obj: bpy.types.Object):
    """Get fcurves from the channelbag for the object's action slot (Blender 5.0+)."""
    action = obj.animation_data.action
    slot = obj.animation_data.action_slot
    if not slot or not action.layers:
        return None
    for layer in action.layers:
        for strip in layer.strips:
            if hasattr(strip, 'channelbag'):
                cb = strip.channelbag(slot)
                if cb is not None:
                    return cb.fcurves
    return None

def _fix_obj_anim_interpolation(obj: bpy.types.Object):
    """ fixes broken quaternion interpolation between frames and sets it to LINEAR"""

    interpolation = 'LINEAR'
    fcurves = _get_channelbag_fcurves(obj)
    if fcurves is None:
        return

    fq = [
        fcurves.find('rotation_quaternion', index = 0), # w
        fcurves.find('rotation_quaternion', index = 1), # x
        fcurves.find('rotation_quaternion', index = 2), # y
        fcurves.find('rotation_quaternion', index = 3), # z
    ]

    def _get_quat_at_frame(frame: int):
        return mathutils.Quaternion((
            fq[0].keyframe_points[frame].co[1], # w
            fq[1].keyframe_points[frame].co[1], # x
            fq[2].keyframe_points[frame].co[1], # y
            fq[3].keyframe_points[frame].co[1], # z
        ))

    def _set_interpolation_for_frame(frame: int, interpolation: str):
        for f in fq:
            f.keyframe_points[frame].interpolation = interpolation

    def _negate_quat_at_frame(frame: int):
        for f in fq:
            f.keyframe_points[frame].co[1] = -f.keyframe_points[frame].co[1]

    # negate quaternion so that interpolation takes the shortest path
    nextQuat = None
    if len(fq[0].keyframe_points) > 0:
        nextQuat = _get_quat_at_frame(0)
        _set_interpolation_for_frame(0, interpolation)

    for i in range(len(fq[0].keyframe_points) - 1):
        _set_interpolation_for_frame(i + 1, interpolation)

        curQuat = nextQuat
        nextQuat = _get_quat_at_frame(i + 1)

        if curQuat.dot(nextQuat) < 0:
            nextQuat.negate()
            _negate_quat_at_frame(i + 1)
