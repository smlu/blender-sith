import bpy, bmesh
import os.path

from typing import List

maxNameLen = 64

def isValidNameLen(name: str):
    return len(name) <= maxNameLen

def isASCII(s: str):
    return all(ord(c) < 128 for c in s)

def assertName(name: str):
    if not isValidNameLen(name):
        raise AssertionError("name error: len of '{}' is greater then {} chars".format(name, maxNameLen))

    if not isASCII(name):
        raise AssertionError("name error: '{}' len does not contain all ASCII chars".format(name))


def getBmeshFaceLayer(faces: bmesh.types.BMFaceSeq, name: str):
    return faces.layers.string.get(name) or faces.layers.string.new(name)

def getDefaultMatFolders(model_path):
    path1 = os.path.dirname(model_path) + '/' + 'mat'
    path2 = os.path.abspath(os.path.join(os.path.dirname(model_path), os.pardir)) + '/' + 'mat'
    return [path1, path2]


def getGlobalMaterial(name):
    return bpy.data.materials[name]

def clearSceneAnimData(scene):
    scene.timeline_markers.clear()

def clearAllScenes():
    for scene in bpy.data.scenes:
        for obj in scene.objects:
            if obj.mode != "OBJECT":
                bpy.ops.object.mode_set(mode='OBJECT')
            scene.objects.unlink(obj)

        for layer in scene.render.layers:
            try: scene.render.layers.remove(layer)
            except: pass

        # Remove animation data:
        clearSceneAnimData(scene)
        # Remove scene
        try: bpy.data.scenes.remove(scene)
        except: pass

    for bpy_data_iter in (
        bpy.data.actions,
        bpy.data.armatures,
        bpy.data.objects,
        bpy.data.meshes,
        bpy.data.lamps,
        bpy.data.images,
        bpy.data.curves,
        bpy.data.materials,
        bpy.data.cameras,
        bpy.data.textures,
        bpy.data.groups,
        bpy.data.lattices,
        bpy.data.grease_pencil,
        bpy.data.libraries,
        bpy.data.metaballs,
        bpy.data.movieclips,
        bpy.data.node_groups,
        bpy.data.particles,
        bpy.data.shape_keys,
        bpy.data.worlds
    ):
        for id_data in bpy_data_iter:
            bpy_data_iter.remove(id_data)