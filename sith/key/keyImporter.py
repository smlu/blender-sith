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

from xmlrpc.client import Boolean
import bpy, mathutils

from sith.model.utils import *
from sith.types import BenchmarkMeter
from sith.utils import *

from typing import Optional

from .key import *
from . import keyLoader

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

def _check_obj(obj, nodes: List[KeyNode], maxJoints: int ) -> bool:
    for node in nodes:
        if _find_joint_obj_for_anim_node(obj, node, maxJoints) is None:
            return False
    return True

def _find_anim_obj_in_scene(scene: bpy.types.Scene, nodes: List[KeyNode], maxJoints: int):
    for obj in scene.objects:
        if obj.parent is not None:
            continue
        if _check_obj(obj, nodes, maxJoints):
            return obj
    return None

def _get_parent(obj):
    while obj.parent is not None:
        obj = obj.parent
    return obj

def importKey(keyPath, scene: bpy.types.Scene, clearScene: bool, validateActiveObject: bool):
    with BenchmarkMeter(' done in {:.4f} sec.'):
        print("importing KEY: %r..." % (keyPath), end="")

        key = keyLoader.loadKey(keyPath)

        # Check selected object or find anim object in the scene
        obj = scene.objects.active
        if obj:
            obj = _get_parent(obj)
            if validateActiveObject and not _check_obj(obj, key.nodes, key.joints):
                raise ValueError(f"Selected object '{obj.name}' doesn't contain all required nodes to animate!")
        else:
            obj = _find_anim_obj_in_scene(scene, key.nodes, key.joints)
            if obj is None:
                raise ValueError(f"Couldn't find a valid object to animate!")

        if clearScene:
            clearSceneAnimData(scene)

        scene.frame_start     = 0
        scene.frame_end       = key.numFrames - 1 if clearScene else  max(scene.frame_end, key.numFrames - 1)
        scene.frame_step      = 1
        scene.render.fps      = key.fps
        scene.render.fps_base = 1.0

        if clearScene:
            scene.sith_key_flags = key.flags.toSet()
            scene.sith_key_types = key.nodeTypes.hex()

        for m in key.markers:
            scene.timeline_markers.new(m.type.name, m.frame)

        for node in key.nodes:
            # Get object to animate
            aobj = _find_joint_obj_for_anim_node(obj, node, key.joints)
            if aobj is None:
                print(f"Couldn't find joint object '{node.meshName}' to animate!")
                continue

            # Set object's keyframes
            for keyframe in node.keyframes:
                _set_obj_location(aobj, keyframe.position)
                aobj.keyframe_insert(data_path="location", frame=keyframe.frame)

                objSetRotation(aobj, keyframe.orientation)
                aobj.keyframe_insert(data_path="rotation_quaternion", frame=keyframe.frame)

        scene.frame_set(0)
