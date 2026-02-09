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

import bpy, os.path
from pathlib import Path
from typing import Optional, Union, Tuple

from .material import ColorMap

kMaxNameLen = 64
kDefaultCmp = 'dflt.cmp'

_fsys_case_sensitive = not Path(str(Path.home()).upper()).exists()

# Cache for addon version info (read once, use many times)
_addon_version_cache = None

def _get_addon_version_info():
    """Get addon version and maintainer from manifest file"""
    global _addon_version_cache

    # Return cached value if already read
    if _addon_version_cache is not None:
        return _addon_version_cache

    try:
        # Read from blender_manifest.toml
        addon_dir = Path(__file__).parent
        manifest_path = addon_dir / "blender_manifest.toml"

        if manifest_path.exists():
            with open(manifest_path, 'r', encoding='utf-8') as f:
                version = None
                maintainer = None
                for line in f:
                    line = line.strip()
                    if line.startswith('version = '):
                        version = line.split('=', 1)[1].strip().strip('"\'')
                    elif line.startswith('maintainer = '):
                        maintainer = line.split('=', 1)[1].strip().strip('"\'')

                    if version and maintainer:
                        break

                if version and maintainer:
                    _addon_version_cache = (version, maintainer)
                    return _addon_version_cache
    except Exception:
        pass

    # Fallback to hardcoded values
    _addon_version_cache = ("1.x.x", "Crt Vavros")
    return _addon_version_cache

def isValidNameLen(name: str):
    return len(name) <= kMaxNameLen

def isASCII(s: str):
    return all(ord(c) < 128 for c in s)

def assertName(name: str):
    if not isValidNameLen(name):
        raise AssertionError(f"name error: len of '{name}' is greater then {kMaxNameLen} chars")

    if not isASCII(name):
        raise AssertionError(f"name error: '{name}' len does not contain all ASCII chars")

def findCmpFileInPath(cmpFile: Union[Path, str], path: Union[Path, str]) -> Optional[Path]:
    cmpFile = Path(cmpFile)
    modelDir: Path = Path(os.path.dirname(path))

    # try model folder
    path = modelDir / cmpFile
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

def getCmpFileOrDefault(filepath: Union[Path, str], searchPath: Union[Path, str]) -> Optional[ColorMap]:
    cmp_file = Path(filepath)
    if len(filepath) == 0:
        cmp_file = Path(kDefaultCmp)
    if not cmp_file.is_file():
        cmp_file = findCmpFileInPath(cmp_file, searchPath)
    cmp = None
    if cmp_file is not None and cmp_file.is_file():
        cmp = ColorMap.load(cmp_file)
    return cmp

def getDefaultMatFolders(model3doPath: Union[Path, str]):
    path1 = os.path.dirname(model3doPath)
    path2 = os.path.join(path1, 'mat')
    path3 = os.path.abspath(os.path.join(path1, os.pardir))
    path3 = os.path.join(path3, 'mat')
    return [path1, path2, path3]

def getFilePathInDir(filename: str, dirPath: Union[Path, str], insensitive: bool = True):
    "Returns string file path in dir if file exists otherwise None"

    if not os.path.isdir(dirPath) or len(filename) < 1:
        return None

    def file_exists(filePath: str):
        return os.path.isfile(filePath) and os.access(filePath, os.R_OK)

    filePath = os.path.join(dirPath, filename)
    if file_exists(filePath):
        return filePath

    if _fsys_case_sensitive and insensitive:
        # Try to find the file by lower-cased name
        filename = filename.lower()
        filePath = os.path.join(dirPath, filename)
        if file_exists(filePath):
            return filePath

        # Ok, now let's go through all files in folder and
        # try to find file by case insensitive comparing it.
        # to other file names.
        for f in os.listdir(dirPath):
            filePath = os.path.join(dirPath, f)
            if file_exists(filePath) and f.lower() == filename:
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
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    # Clear default nodes
    nodes.clear()
    # Create Principled BSDF and Output
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.location = (0, 0)
    output = nodes.new('ShaderNodeOutputMaterial')
    output.location = (300, 0)
    links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
    # Create Image Texture node
    tex_node = nodes.new('ShaderNodeTexImage')
    tex_node.location = (-300, 0)
    links.new(tex_node.outputs['Color'], bsdf.inputs['Base Color'])
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

        for collection in scene.collection.children:
            scene.collection.children.unlink(collection)

        # Remove all objects from the scene's master collection
        for obj in list(scene.collection.objects):
            scene.collection.objects.unlink(obj)

        for vl in list(scene.view_layers):
            try: scene.view_layers.remove(vl)
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
        bpy.data.lights,
        bpy.data.images,
        bpy.data.curves,
        bpy.data.materials,
        bpy.data.cameras,
        bpy.data.textures,
        bpy.data.collections,
        bpy.data.lattices,
        bpy.data.annotations,
        bpy.data.libraries,
        bpy.data.metaballs,
        bpy.data.movieclips,
        bpy.data.node_groups,
        bpy.data.particles,
        bpy.data.shape_keys,
        bpy.data.worlds
    ):
        for id_data in bpy_data_iter:
            if hasattr(bpy_data_iter, 'remove'): # Some bpy_prop_collection don't have this method.
                bpy_data_iter.remove(id_data)

def getExportFileHeader(prefix: str):
    """Generate export file header with current addon version from manifest"""
    version, maintainer = _get_addon_version_info()
    return f"{prefix} created with Blender Sith addon v{version} by {maintainer}"
