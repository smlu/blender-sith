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

import bpy, os.path
from pathlib import Path
from typing import Optional
from . import bl_info

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

def getDefaultCmpFilePath(model3doPath) -> Optional[Path]:
    cmpFile  = Path('dflt.cmp')
    modelDir = Path(os.path.dirname(model3doPath))

    # try model folder
    path = modelDir/ cmpFile
    if path.exists() and path.is_file():
        return path

    # try model folder / misc/cmp
    path = modelDir / Path('misc/cmp') / cmpFile
    if path.exists() and path.is_file():
        return path

    # try parent folder
    path = modelDir.parent / cmpFile
    if path.exists() and path.is_file():
        return path

    # try parent folder / misc/cmp
    path = modelDir.parent / Path('misc/cmp') / cmpFile
    if path.exists() and path.is_file():
        return path

    # try parent/parent folder / misc/cmp
    path = modelDir.parent.parent / Path('misc/cmp') / cmpFile
    if path.exists() and path.is_file():
        return path

    return None

def getDefaultMatFolders(model3doPath):
    path1 = os.path.join(os.path.dirname(model3doPath), 'mat')
    path2 = os.path.abspath(os.path.join(os.path.dirname(model3doPath), os.pardir))
    path2 = os.path.join(path2, 'mat')
    return [path1, path2]

def getFilePathInDir(fileName: str, dirPath: str, insensitive=True):
    "Returns string file path in dir if file exists otherwise None"

    if not os.path.isdir(dirPath) or len(fileName) < 1:
        return None

    def file_exists(filePath):
        return os.path.isfile(filePath) and os.access(filePath, os.R_OK)

    filePath = os.path.join(dirPath, fileName)
    if file_exists(filePath):
        return filePath

    if insensitive:
        # Try to find the file by lower-cased name
        fileName = fileName.lower()
        filePath = os.path.join(dirPath, fileName)
        if file_exists(filePath):
            return filePath

        # Ok, now let's go through all files in folder and
        # try to find file by case insensitive comparing it.
        # to other file names.
        for f in os.listdir(dirPath):
            filePath = os.path.join(dirPath, f)
            if file_exists(filePath) and f.lower() == fileName:
                return filePath

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

def getExportFileHeader(prefix):
    version = bl_info['version']
    version = '.'.join([str(v) for v in version])
    if 'pre_release' in bl_info:
        version += '-' + bl_info['pre_release']
    return "{} created with Blender Sith addon v{} by {}".format(prefix, version, bl_info['author'])