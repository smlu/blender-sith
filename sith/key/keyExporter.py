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

import bpy, mathutils, os.path
import sith.key.keyWriter as keyWriter
from collections import OrderedDict

from sith.key import *
from sith.model.utils import *
from sith.model import makeModel3doFromObj, Mesh3doNodeType
from sith.types import BenchmarkMeter
from sith.utils import *

def _set_keyframe_delta(dtype: KeyframeFlag, kf1: Keyframe, kf2: Keyframe):
    assert dtype == KeyframeFlag.PositionChange or dtype == KeyframeFlag.OrientationChange
    vec1 = mathutils.Vector(kf1.position)
    vec2 = mathutils.Vector(kf2.position)
    if dtype == KeyframeFlag.OrientationChange:
        vec1 = mathutils.Vector(kf1.orientation)
        vec2 = mathutils.Vector(kf2.orientation)

    dframes = kf2.frame - kf1.frame
    delta   = ( vec2 - vec1 ) / dframes

    if delta != mathutils.Vector((0.0, 0.0, 0.0)):
        if dtype == KeyframeFlag.PositionChange:
            kf1.deltaPosition = Vector3f(*delta)
        else:
            kf1.deltaRotation = Vector3f(*delta)

        if kf1.flags == KeyframeFlag.NoChange:
            kf1.flags = dtype
        elif kf1.flags != dtype:
            kf1.flags = KeyframeFlag.AllChange

def _make_key_from_obj(key_name, obj: bpy.types.Object, scene: bpy.types.Scene):
    key           = Key(key_name)
    key.flags     = KeyFlag.fromSet(scene.sith_key_flags)
    key.nodeTypes = Mesh3doNodeType.fromHex(scene.sith_key_types)
    key.numFrames = scene.frame_end + 1
    key.fps       = scene.render.fps
    for marker in scene.timeline_markers:
        t = KeyMarkerType.Default
        try:
            t = KeyMarkerType[marker.name]
        except:
            print("\nWarning: Invalid marker name '{}'. Using marker type '{}'!".format(marker.name, t.name))

        m = KeyMarker()
        m.frame = marker.frame
        m.type = t
        key.markers.append(m)

    # Make model3do from object to get ordered hierarchy nodes
    model3do = makeModel3doFromObj(key_name, obj)
    for hnode in model3do.meshHierarchy:
        cobj = hnode.obj
        if cobj.animation_data:
            knode          = KeyNode()
            knode.idx      = hnode.idx
            knode.meshName = hnode.name

            # Get node's keyframe entries
            cobj_pivot = objPivot(cobj)
            kfs = OrderedDict()
            for fc in cobj.animation_data.action.fcurves:
                if fc.data_path.endswith(('location','rotation_euler','rotation_quaternion')):
                    for k in fc.keyframe_points :
                        frame = k.co[0]
                        axis_co = k.co[1]

                        if frame not in kfs:
                            kfs[frame] = {"flags": KeyframeFlag.NoChange}

                        if fc.data_path not in kfs[frame]:
                            if fc.data_path.endswith(('location', 'rotation_euler')):
                                kfs[frame][fc.data_path] = [0.0, 0.0, 0.0]
                                kfs[frame]["delta_" + fc.data_path] = [0.0, 0.0, 0.0]
                            else: # quaternion rotation
                                kfs[frame][fc.data_path] = [0.0, 0.0, 0.0, 0.0]
                                kfs[frame]["delta_" + fc.data_path] = [0.0, 0.0, 0.0, 0.0]

                        # Set coordinate for data
                        # Note: fc.array_index is an index to the axis of a vector
                        if fc.data_path.endswith(('location')):
                            axis_co -= cobj_pivot[fc.array_index]
                        kfs[frame][fc.data_path][fc.array_index] = axis_co

            # Set node's keyframes
            kfs_items = list(sorted(kfs.items()))
            for idx, item in enumerate(kfs_items):
                frame = item[0]
                entry = item[1]

                kf       = Keyframe()
                kf.frame = int(frame)
                kf.flags = entry["flags"]

                previous_kf = knode.keyframes[idx - 1] if idx > 0 else None

                # Set location
                if "location" in entry:
                    def get_scale(o):
                        scale = o.scale
                        nonlocal obj
                        while o != obj:
                            o = o.parent
                            scale = vectorMultiply(scale, o.scale)
                        return scale
                    loc = mathutils.Vector(entry['location'])
                    loc = vectorMultiply(loc, get_scale(cobj))
                    kf.position =  Vector3f(*loc)
                elif previous_kf:
                    kf.position = previous_kf.position

                # Set delta position
                if previous_kf:
                    _set_keyframe_delta(KeyframeFlag.PositionChange, previous_kf, kf)

                # Set orientation
                if 'rotation_euler' in entry:
                    kf.orientation   = eulerToImEuler(entry["rotation_euler"], cobj.rotation_mode)
                elif "rotation_quaternion" in entry:
                    orient = mathutils.Quaternion(entry["rotation_quaternion"])
                    kf.orientation = quaternionToImEuler(orient)
                elif previous_kf:
                    kf.orientation = previous_kf.orientation

                # Set delta rotation
                if previous_kf:
                    _set_keyframe_delta(KeyframeFlag.OrientationChange, previous_kf, kf)

                knode.keyframes.append(kf)

            # Append keyframe node if node has keyframes
            if len(knode.keyframes):
                key.nodes.append(knode)
    key.numJoints = len(model3do.meshHierarchy)
    return key

def exportKey(obj: bpy.types.Object, scene: bpy.types.Scene, path: str):
    with BenchmarkMeter(' done in {:.4f} sec.'):
        print(f"exporting KEY: {path} for obj: '{obj.name}'...", end="")

        key_name = os.path.basename(path)
        if not isValidNameLen(key_name):
            raise ValueError(f"Export file name '{key_name}' is longer then {kMaxNameLen} chars!")

        key = _make_key_from_obj(key_name, obj, scene)
        if len(key.nodes) == 0:
            print("\nWarning: The object doesn't have any animation data to export!")
        header  = getExportFileHeader(f"Keyframe '{os.path.basename(path)}'")
        keyWriter.saveKey(key, path, header)
