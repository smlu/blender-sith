# Sith Blender Addon
# Copyright (c) 2019-2024 Crt Vavros

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
from collections import defaultdict, OrderedDict

from sith.key import *
from sith.model.utils import *
from sith.model import makeModel3doFromObj, Mesh3doNodeType
from sith.types import BenchmarkMeter
from sith.utils import *

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

def _set_keyframe_delta(kf1: Keyframe, kf2: Keyframe, dtype: KeyframeFlag):
    assert dtype == KeyframeFlag.PositionChange or dtype == KeyframeFlag.OrientationChange

    if kf2.frame <= kf1.frame:
        return

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

def _make_key_from_obj(key_name: str, obj: bpy.types.Object, scene: bpy.types.Scene) -> Key:
    key           = Key(key_name)
    key.flags     = KeyFlag.fromSet(scene.sith_key_flags)
    key.nodeTypes = Mesh3doNodeType.fromHex(scene.sith_key_types)
    key.numFrames = scene.frame_end + 1
    key.fps       = scene.render.fps
    for marker in scene.timeline_markers:
        m       = KeyMarker()
        m.frame = marker.frame
        try:
            m.type = KeyMarkerType[marker.name]
        except:
            try:
                im = int(marker.name)
                m.type = KeyMarkerType(im)
            except:
                print(f"\nWarning: Invalid marker '{marker.name}' at frame {marker.frame}, skipping it!")
                continue
        key.markers.append(m)

    # Make model3do from object to get ordered hierarchy nodes
    model3do      = makeModel3doFromObj(key_name, obj)
    key.numJoints = len(model3do.meshHierarchy)

    for hnode in model3do.meshHierarchy:
        cobj = hnode.obj
        if cobj.animation_data and cobj.animation_data.action:

            # Get object's animation data
            cobj_pivot = objPivot(cobj)
            fcs = defaultdict(OrderedDict)
            for fc in cobj.animation_data.action.fcurves:
                if fc.is_valid and fc.data_path.endswith(('location','rotation_euler','rotation_quaternion')):
                    fcdp = fcs[fc.data_path]
                    for k in fc.keyframe_points :
                        # co[1] represents the value of position or rotation axis (only 1 e.g. x or y or z etc...).
                        # Which axis is determined by fc.array_index,
                        # and fc.data_path defines the type of data (location, rotation_euler, rotation_quaternion)
                        frame   = k.co[0]
                        axis_co = k.co[1]

                        if frame not in fcdp:
                            fcdp[frame] = [None, None, None] # location or rotation_euler
                            if fc.data_path.endswith(('rotation_quaternion', 'rotation_axis_angle')):
                                fcdp[frame] = [None, None, None, None]

                        # Set coordinate for data
                        # Note: fc.array_index is an index to the axis of a vector
                        if fc.data_path.endswith(('location')):
                            axis_co -= cobj_pivot[fc.array_index]
                        # kfs[frame][fc.data_path][fc.array_index] = axis_co
                        fcdp[frame][fc.array_index] = axis_co

            # Fill missing keyframe data and make new dict with ordered frames
            kfs = OrderedDict()
            for data_path, fcdp in fcs.items():
                prev_co = None
                for frame, co in fcdp.items():
                    # Fill missing coordinate
                    co = [co[i] or (prev_co[i] if prev_co else 0.0) for i in range(len(co))] # If co[i] is None set to previous coordinate if available, otherwise 0.0
                    kfs.setdefault(frame, {})[data_path] = co # assign co to kfs[frame][data_path]
                    prev_co = co

            # Make key node from animation data
            knode          = KeyNode()
            knode.idx      = hnode.idx
            knode.meshName = hnode.name

            kfs_items = list(sorted(kfs.items()))
            for idx, item in enumerate(kfs_items):
                frame = item[0]
                entry = item[1]

                if idx == 0 and frame != 0:
                    print(f"\nWarning: The object '{cobj.name}' doesn't have a keyframe set at frame 0!")

                kf       = Keyframe()
                kf.frame = int(frame)
                kf.flags = KeyframeFlag.NoChange

                previous_kf = knode.keyframes[idx - 1] if idx > 0 else None

                # Set location
                if "location" in entry:
                    def get_scale(o):
                         # Note, must not use object's scale
                         # for the same reason as when exporting 3DO node.
                         # See, _model3do_add_obj
                        scale = mathutils.Vector((1.0,) * 3)
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
                    _set_keyframe_delta(previous_kf, kf, KeyframeFlag.PositionChange)

                # Set orientation
                if "rotation_quaternion" in entry:
                    orient = mathutils.Quaternion(entry["rotation_quaternion"])
                    kf.orientation = quaternionToPYR(orient)
                elif 'rotation_euler' in entry:
                    euler = mathutils.Euler(entry["rotation_euler"], cobj.rotation_mode)
                    kf.orientation = eulerToPYR(euler)
                elif 'rotation_axis_angle' in entry: # Note, using axis angles can lead to broken rotations
                    orient = mathutils.Quaternion(entry["rotation_axis_angle"])
                    kf.orientation = quaternionToPYR(orient)
                elif previous_kf:
                    kf.orientation = previous_kf.orientation

                # Set delta rotation
                if previous_kf:
                    _set_keyframe_delta(previous_kf, kf, KeyframeFlag.OrientationChange)

                knode.keyframes.append(kf)

            # Append keyframe node if node has keyframes
            if len(knode.keyframes):
                key.nodes.append(knode)

    return key
