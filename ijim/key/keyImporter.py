import bpy, mathutils, time

from ijim.model.utils import *
from ijim.utils import *

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
    print("importing KEY: %r..." % (keyPath), end="")
    startTime = time.process_time ()

    key = keyLoader.load(keyPath)
    clearSceneAnimData(scene)

    scene.frame_start     = 0
    scene.frame_end       = key.numFrames - 1
    scene.frame_step      = 1
    scene.render.fps      = key.fps
    scene.render.fps_base = 1.0

    scene.key_animation_flags = key.flags.toSet()
    scene.key_animation_type  = key.type.hex()

    for m in key.markers:
        scene.timeline_markers.new(m.type.name, m.frame)

    for node in key.nodes:
        # Get object to animate
        kobj = None
        for obj in scene.objects:
            if obj.model3do_hnode_num != -1:
                if obj.model3do_hnode_num == node.idx:
                    kobj = obj
                    break
            elif obj.model3do_hnode_name.lower() == node.meshName.lower():
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
    print(" done in %.4f sec." % (time.process_time() - startTime))
