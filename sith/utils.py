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
import math
import tomllib
from pathlib import Path
from typing import Optional, Union, Tuple

from .material import ColorMap
from .text.serutils import assertName, isASCII, isValidNameLen, kMaxNameLen
from .types.vector import kFloat32Max, validateFloat32

kDefaultCmp = 'dflt.cmp'

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

        with open(manifest_path, 'rb') as f:
            manifest = tomllib.load(f)
        version, maintainer = manifest.get('version'), manifest.get('maintainer')
        if all(isinstance(value, str) and value for value in (version, maintainer)):
            _addon_version_cache = (version, maintainer)
            return _addon_version_cache
    except (OSError, ValueError):
        pass

    # Fallback to hardcoded values
    _addon_version_cache = ("1.x.x", "Crt Vavros")
    return _addon_version_cache

def findCmpFileInPath(cmpFile: Union[Path, str], path: Union[Path, str], *, searchPaths=()) -> Optional[Path]:
    cmpFile = Path(cmpFile)
    if not cmpFile.name:
        return None
    modelDir = Path(os.path.abspath(path)).parent
    # Preserve the existing search order, resolving both folder and filename
    # spelling on the resource volume rather than guessing from the home volume.
    folders = [modelDir, modelDir / 'misc/cmp', modelDir.parent,
               modelDir.parent / 'misc/cmp', modelDir.parent.parent / 'misc/cmp',
               modelDir / 'misc/cmap', modelDir / 'cmp', modelDir / 'cmap',
               modelDir.parent / 'misc/cmap', modelDir.parent.parent / 'misc/cmap']
    for root in searchPaths:
        if not os.fspath(root):
            continue
        base = Path(root)
        if not base.is_absolute():
            base = modelDir / base
        folders.extend((base, base / 'misc/cmp', base / 'misc/cmap', base / 'cmp', base / 'cmap',
                        base.parent, base.parent / 'misc/cmp', base.parent / 'misc/cmap'))
    for folder in dict.fromkeys(folders):
        candidate = folder / cmpFile
        if candidate.is_file():
            return candidate
        found = getFilePathInDir(candidate.name, candidate.parent)
        if found is not None:
            return Path(found)
    return None

def getCmpFileOrDefault(filepath: Union[Path, str], searchPath: Union[Path, str], *, searchPaths=()) -> Optional[ColorMap]:
    # Do not guess among room/costume palettes. Grim's named default is a last
    # fallback only when the user has not selected a particular CMP file.
    names = (os.fspath(filepath),) if os.fspath(filepath) else (kDefaultCmp, 'dfltcmp.cmp')
    for name in names:
        requested = Path(name)
        # Explicit/current-directory paths retain priority over model-relative paths.
        found = requested if requested.is_file() else getFilePathInDir(requested.name, requested.parent)
        if found is None:
            found = findCmpFileInPath(requested, searchPath, searchPaths=searchPaths)
        if found is not None:
            return ColorMap.load(found)
    return None

def getDefaultMatFolders(model3doPath: Union[Path, str], matDirs=()):
    modelDir = Path(os.path.abspath(model3doPath)).parent
    folders = [modelDir, modelDir / 'mat', modelDir.parent / 'mat', modelDir / '3do/mat']
    for root in matDirs:
        if not os.fspath(root):
            continue
        base = Path(root)
        if not base.is_absolute():
            base = modelDir / base
        folders.extend((base, base / 'mat', base / '3do/mat'))
    return [str(folder) for folder in dict.fromkeys(folders)]

def getFilePathInDir(filename: str, dirPath: Union[Path, str], insensitive: bool = True):
    """Find a readable file, preferring exact spelling over a unique case match."""
    if not os.fspath(filename) or not os.fspath(dirPath):
        return None

    def file_exists(filePath: str):
        return os.path.isfile(filePath) and os.access(filePath, os.R_OK)

    filePath = os.path.join(dirPath, filename)
    if file_exists(filePath):
        return filePath

    if not insensitive:
        return None

    # Exact lookup is the common fast path. On a miss, walk only the requested
    # components: MAT directories and misc/cmp can have different casing too.
    candidate = Path(filePath)
    current = Path(candidate.anchor) if candidate.anchor else Path('.')
    parts = candidate.parts[1:] if candidate.anchor else candidate.parts
    for index, part in enumerate(parts):
        accepts = os.path.isdir if index < len(parts) - 1 else file_exists
        exact = current / part
        if accepts(exact):
            current = exact
            continue
        if not os.path.isdir(current):
            return None

        try:
            with os.scandir(current) as entries:
                matches = [Path(entry.path) for entry in entries
                           if entry.name.lower() == part.lower() and accepts(entry.path)]
        except OSError:
            # A missing/inaccessible search folder is not a usable resource.
            return None
        if not matches:
            return None
        if len(matches) > 1:
            names = ', '.join(sorted(match.name for match in matches))
            raise ValueError(f"Ambiguous resource path '{filePath}': {names} in '{current}'; use exact spelling")
        current = matches[0]
    return str(current) if file_exists(current) else None

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
    # Validate the entire scene first: clearing a linked object's animation can
    # appear to work but is lost on reopen. Never clear local work before this check.
    if not scene.is_editable:
        raise ValueError(f"Make scene '{scene.name}' local or editable before clearing animation")
    animated = [ob for ob in scene.objects if ob.animation_data is not None]
    for ob in animated:
        if not ob.is_editable:
            raise ValueError(f"Make animated object '{ob.name}' local or editable before clearing scene animation, or disable Clear scene")
    scene.timeline_markers.clear()
    for ob in animated:
        ob.animation_data_clear()

def clearAllScenes():
    for scene in list(bpy.data.scenes):
        if not scene.is_editable:
            # Clear Scene discards linked scene IDs, not their read-only contents.
            bpy.data.scenes.remove(scene)
            continue
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
