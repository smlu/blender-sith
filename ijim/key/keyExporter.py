from ijim.key.key import *
import ijim.key.keyWriter as keyWriter

from ijim.model.utils import *
from ijim.model.model3doExporter import makeModel3doFromObj

from ijim.utils.utils import *


import bpy
import mathutils

import os.path
import time
from collections import OrderedDict

def _get_obj_by_name(scene: bpy.types.Scene, name):
    for o in scene.objects:
        if kHnName in o:
            if o[kHnName] == name:
                return o
            elif stripOrderPrefix(o.name) == name:
                return o
    raise ValueError("Could not find object '{}'".format(name))

def _get_kf_change_flag(str):
    if str.endswith(('rotation_euler', 'rotation_quaternion')):
        return KeyframeFlag.OrientationChange
    else:
        return KeyframeFlag.PositionChange

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
    key.flags     = KeyFlag.fromSet(scene.key_animation_flags)
    key.type      = KeyType.fromHex(scene.key_animation_type)
    key.numFrames = scene.frame_end + 1
    key.fps       = scene.render.fps
    for marker in scene.timeline_markers:
        t = KeyMarkerType.Marker
        try:
            t = KeyMarkerType[marker.name]
        except:
            print("\nWarning: Can't convert invalid marker name '{}' to marker type. Using type '{}'!".format(marker.name, t.name))

        m = KeyMarker()
        m.frame = marker.frame
        m.type = t
        key.markers.append(m)

    # Make model3do from object to get ordered hierarchy nodes
    model3do = makeModel3doFromObj(key_name, obj)
    key.numJoints = len(model3do.hierarchyNodes)
    for hnode_idx, hnode in enumerate(model3do.hierarchyNodes):
        cobj = _get_obj_by_name(scene, hnode.name)
        if cobj.animation_data:
            knode = KeyNode()
            knode.num = hnode_idx
            knode.meshName = hnode.name

            # Get node's keyframe entries
            cobj_pivot = getObjPivot(cobj)
            kfs = OrderedDict()
            for fc in cobj.animation_data.action.fcurves :
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

                keyframe = Keyframe()
                keyframe.frame = int(frame)
                keyframe.flags = entry["flags"]

                previous_kf = knode.keyframes[idx - 1] if idx > 0 else None

                # Set location
                keyframe.position = Vector3f(0.0, 0.0, 0.0)
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
                    keyframe.position =  Vector3f(*loc)
                elif previous_kf:
                    keyframe.position = previous_kf.position

                # Set delta position
                keyframe.deltaPosition = Vector3f(0.0, 0.0, 0.0)
                if previous_kf:
                    _set_keyframe_delta(KeyframeFlag.PositionChange, previous_kf, keyframe)

                # Set orientation
                keyframe.orientation = Vector3f(0.0, 0.0, 0.0)
                if 'rotation_euler' in entry:
                    keyframe.orientation   = eulerToImEuler(entry["rotation_euler"], cobj.rotation_mode)
                elif "rotation_quaternion" in entry:
                    orient = mathutils.Quaternion(entry["rotation_quaternion"])
                    keyframe.orientation = quaternionToImEuler(orient)
                elif previous_kf:
                    keyframe.orientation = previous_kf.orientation

                # Set delta rotation
                keyframe.deltaRotation = Vector3f(0.0, 0.0, 0.0)
                if previous_kf:
                    _set_keyframe_delta(KeyframeFlag.OrientationChange, previous_kf, keyframe)

                knode.keyframes.append(keyframe)

            # Append keyframe node if node has keyframes
            if len(knode.keyframes):
                key.nodes.append(knode)

    return key

def exportObjectAnim(obj: bpy.types.Object, scene: bpy.types.Scene, path: str):
    print("exporting KEY: {} for obj: '{}'...".format(path, obj.name), end="")
    start_time = time.process_time()

    key_name = os.path.basename(path)
    if not isValidNameLen(key_name):
        raise ValueError("Export file name '{}' is longer then {} chars!".format(key_name, maxNameLen))

    key = _make_key_from_obj(key_name, obj, scene)
    if len(key.nodes) == 0:
        print("\nWarning: The object doesn't have any animation data to export!")
    header  = getExportFileHeader("Keyframe '{}'".format(os.path.basename(path)))
    keyWriter.write(key, path, header)

    print(" done in %.4f sec." % (time.process_time() - start_time))