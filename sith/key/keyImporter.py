# Sith Blender Addon
# Copyright (c) 2019-2022 Crt Vavros

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

import bpy, mathutils

from sith.model.utils import *
from sith.types import BenchmarkMeter
from sith.utils import *

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

def importKey(keyPath, scene: bpy.types.Scene):
    with BenchmarkMeter(' done in {:.4f} sec.'):
        print("importing KEY: %r..." % (keyPath), end="")

        key = keyLoader.loadKey(keyPath)
        clearSceneAnimData(scene)

        scene.frame_start     = 0
        scene.frame_end       = key.numFrames - 1
        scene.frame_step      = 1
        scene.render.fps      = key.fps
        scene.render.fps_base = 1.0

        scene.sith_key_flags = key.flags.toSet()
        scene.sith_key_types = key.nodeTypes.hex()

        for m in key.markers:
            scene.timeline_markers.new(m.type.name, m.frame)

        for node in key.nodes:
            # Get object to animate
            kobj = None
            for obj in scene.objects:
                if obj.sith_model3do_hnode_idx > -1 and obj.sith_model3do_hnode_idx < key.joints:
                    if obj.sith_model3do_hnode_idx == node.idx:
                        kobj = obj
                        break
                elif obj.sith_model3do_hnode_name.lower() == node.meshName.lower():
                    kobj = obj
                    break
                elif node.meshName.lower() == obj.name.lower():
                    kobj = obj
                    break
                elif isOrderPrefixed(obj.name) and getOrderedNameIdx(obj.name) == node.idx:
                    kobj = obj
                    break

            if kobj is None:
                raise ValueError("Cannot find object '{}' to animate!".format(node.meshName))

            # Set object's keyframes
            for keyframe in node.keyframes:
                _set_obj_location(kobj, keyframe.position)
                kobj.keyframe_insert(data_path="location", frame=keyframe.frame)

                objSetRotation(kobj, keyframe.orientation)
                kobj.keyframe_insert(data_path="rotation_quaternion", frame=keyframe.frame)

        scene.frame_set(0)
