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


def getBmeshFaceLayer(faces: bmesh.types.BMFaceSeq, name: str, makeLayer=True):
    return faces.layers.string.get(name) or faces.layers.string.new(name) if makeLayer else None

def getDefaultMatFolders(model_path):
    os.path.join(os.path.dirname(model_path), 'mat')
    path1 = os.path.join(os.path.dirname(model_path), 'mat')
    path2 = os.path.abspath(os.path.join(os.path.dirname(model_path), os.pardir))
    path2 = os.path.join(path2, 'mat')
    return [path1, path2]

def getFilePathInDir(fileName: str, dirPath: str, insensitive=True):
    "Returns string file path in dir if file exists otherwise None"

    if not os.path.isdir(dirPath) or len(fileName) < 1:
        return None

    def file_exists(file_path):
        return os.path.isfile(file_path) and os.access(file_path, os.R_OK)

    file_path = os.path.join(dirPath, fileName)
    if file_exists(file_path):
        return file_path

    if insensitive:
        # Try to find the file by lower-cased name
        fileName = fileName.lower()
        file_path = os.path.join(dirPath, fileName)
        if file_exists(file_path):
            return file_path

        # Ok, now let's go through all files in folder and
        # try to find file by case insensitive comparing it.
        # to other file names.
        for f in os.listdir(dirPath):
            file_path = os.path.join(dirPath, f)
            if file_exists(file_path) and f.lower() == fileName:
                return file_path

def getGlobalMaterial(name: str):
    if name in bpy.data.materials:
        return bpy.data.materials[name]

    name = name.lower()
    if name in bpy.data.materials:
        return bpy.data.materials[name]

    for mat in bpy.data.materials:
        if(mat.name.lower() == name):
            return mat

def makeNewGlobalMaterial(name: str):
    mat = bpy.data.materials.new(name)
    mat.texture_slots.add()
    ts = mat.texture_slots[0]
    ts.texture_coords = 'UV'
    ts.uv_layer = 'UVMap'
    return mat

def clearSceneAnimData(scene):
    scene.timeline_markers.clear()
    for ob in scene.objects:
        ob.animation_data_clear()

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