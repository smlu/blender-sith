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

import bpy, bmesh, mathutils, time

from sith.material import ColorMap
from sith.utils import *
from typing import List, Optional

from . import model3doLoader
from .utils import *
from .model3do import (
    Model3do,
    Mesh3do
)

def _set_obj_rotation(obj, rotation):
    objSetRotation(obj, rotation)

def _set_obj_pivot(obj, pivot):
    pvec = mathutils.Vector(pivot)
    if  obj.type == 'MESH' and obj.data is not None and pvec.length > 0:
        obj.data.transform(mathutils.Matrix.Translation(pvec))

def _make_radius_obj(name, parent, radius):
    if name in bpy.data.meshes:
        mesh = bpy.data.meshes[name]
    else:
        mesh = bpy.data.meshes.new(name)
        ro = bpy.data.objects.new(name , mesh)
        ro.draw_type = 'WIRE'
        ro.hide = True
        ro.parent_type = 'OBJECT'
        ro.parent = parent
        bpy.context.scene.objects.link(ro)

    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, diameter=radius)
    bm.to_mesh(mesh)
    bm.free()

def _set_model_radius(obj, radius):
    _make_radius_obj(kModelRadius + obj.name, obj, radius)

def _set_mesh_radius(obj, radius):
    _make_radius_obj(kMeshRadius + obj.name, obj, radius)

def _make_mesh(mesh3do: Mesh3do, uvAbsolute: bool, vertexColors: bool, mat_list: List):
    mesh = bpy.data.meshes.new(mesh3do.name)

    faces = []
    for face in mesh3do.faces:
        faces += [face.vertexIdxs]

    # Construct mesh
    mesh.from_pydata(mesh3do.vertices, [], faces)
    mesh.show_double_sided = True

    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()

    vert_color = bm.loops.layers.color.verify()
    uv_layer   = bm.loops.layers.uv.verify()
    bm.faces.layers.tex.verify()
    bmMeshInit3doLayers(bm)

    # Set mesh materials and UV map
    for face in bm.faces:
        face3do = mesh3do.faces[face.index]

        # Set custom property for face type, geometry, light, texture mode
        bmFaceSetType(face, bm, face3do.type)
        bmFaceSetGeometryMode(face, bm, face3do.geometryMode)
        bmFaceSetLightMode(face, bm, face3do.lightMode)
        bmFaceSetTextureMode(face, bm, face3do.textureMode)
        bmFaceSetExtraLight(face, bm, face3do.color)

        # Set face normal
        face.normal = mesh3do.faces[face.index].normal

        # Set face material index
        mat = None
        if face3do.materialIdx > -1:
            mat_name = mat_list[face3do.materialIdx]
            mat = getGlobalMaterial(mat_name)
            if mat is None:
                print("\nWarning: Could not find or load material file '{}'".format(mat_name))
                mat = makeNewGlobalMaterial(mat_name)

        if mat:
            if mat.name not in mesh.materials:
                mesh.materials.append(mat)
            face.material_index = mesh.materials.find(mat.name)

        # Set face texture
        img = None
        if mat and mat.texture_slots[0].texture:
            tex = mat.texture_slots[0].texture
            img = tex.image
            tex_layer = bm.faces.layers.tex[uv_layer.name]
            face[tex_layer].image = img

        # Set vertices color and face uv map
        for idx, loop in enumerate(face.loops): # update vertices
            vidx             = loop.vert.index
            loop.vert.normal = mesh3do.normals[vidx]
            if vertexColors:
                loop[vert_color] = mesh3do.vertexColors[vidx]

            # Set UV coordinates
            luv    = loop[uv_layer]
            uvIdx  = face3do.uvIdxs[idx]
            if uvIdx < len(mesh3do.uvs):
                uv = mesh3do.uvs[uvIdx]
                if uvAbsolute: # Remove image size from uv
                    if img is not None:
                        uv = vectorDivide(mathutils.Vector(uv), mathutils.Vector(img.size))
                    elif face3do.materialIdx > -1:
                        print(f"\nWarning: Could not remove image size from UV coord due to missing image! mesh:'{mesh3do.name}' face:{face.index} uvIdx:{uvIdx}")
                luv.uv = (uv.x, -uv.y) # Note: Flipped v
            elif uvIdx > -1:
                print(f"Warning: UV index out of range {uvIdx} >= {len(mesh3do.uvs)}! mesh:'{mesh3do.name}' face:{face.index}")

    bm.to_mesh(mesh)
    bm.free()

    mesh.update()
    return mesh

def _create_objects_from_model(model: Model3do, uvAbsolute: bool, geosetNum: int, vertexColors: bool, importRadiusObj:bool, preserveOrder: bool):
    meshes = model.geosets[geosetNum].meshes
    for node in model.meshHierarchy:
        meshIdx = node.meshIdx

        # Get node's mesh
        if meshIdx > -1:
            if meshIdx >= len(meshes):
                raise IndexError("Mesh index {} out of range ({})!".format(meshIdx, len(meshes)))

            mesh3do = meshes[meshIdx]
            mesh    = _make_mesh(mesh3do, uvAbsolute, vertexColors, model.materials)
            obj     = bpy.data.objects.new(mesh3do.name, mesh)

            # Set mesh radius object, draw type, custom property for lighting and texture mode
            if importRadiusObj:
                _set_mesh_radius(obj, mesh3do.radius)

            obj.draw_type             = getDrawType(mesh3do.geometryMode)
            obj.model3do_light_mode   = mesh3do.lightMode.name
            obj.model3do_texture_mode = mesh3do.textureMode.name
            obj.draw_bounds_type      = 'SPHERE'
            bpy.context.scene.objects.link(obj)
        else:
            obj = bpy.data.objects.new(node.name, None)
            obj.empty_draw_size = (0.0)
            bpy.context.scene.objects.link(obj)

        # Make obj name prefixed by idx num.
        # This will make the hierarchy of model 3do ordered by index instead by name in Blender.
        obj.name = makeOrderedName(obj.name, node.idx, len(model.meshHierarchy)) if preserveOrder else obj.name

        # Set hierarchy node flags, type and name
        obj.model3do_hnode_num   = node.idx
        obj.model3do_hnode_name  = node.name
        obj.model3do_hnode_flags = node.flags.hex()
        obj.model3do_hnode_type  = node.type.hex()

        # Set node position, rotation and pivot
        _set_obj_pivot(obj, node.pivot)
        obj.location = node.position
        _set_obj_rotation(obj, node.rotation)

        node.obj = obj

    bpy.context.scene.update()

    # Set parent hierarchy
    for node in model.meshHierarchy:
        if node.parentIdx != -1:
            node.obj.parent_type = 'OBJECT'
            node.obj.parent      = model.meshHierarchy[node.parentIdx].obj
    bpy.context.scene.update()

def _import_colormap(cmp_file: str) -> Optional[ColorMap]:
    try:
        return ColorMap.load(cmp_file)
    except Exception as e:
        print(f"Warning: Failed to load ColorMap '{cmp_file}': {e}")

def import3do(file_path, mat_dirs = [], cmp_file = '', uvAbsolute_2_1 = True, importVertexColors = True, importRadiusObj = False, preserveOrder = True, clearScene = True):
    print("importing 3DO: %r..." % (file_path), end="")
    startTime = time.process_time()

    model, fileVersion = model3doLoader.load(file_path)
    isJkdf2 = (fileVersion == model3doLoader.Model3doFileVersion.Version2_1)
    if len(model.geosets) == 0:
        print("Info: Nothing to load because 3DO model doesn't contain any geoset.")
        return

    cmp = None
    if isJkdf2:
        # Load ColorMap
        if len(cmp_file) == 0:
            print('\nInfo: ColorMap path not set, loading default...')
            cmp_file = getDefaultCmpFilePath(file_path)
        if cmp_file:
            cmp = _import_colormap(cmp_file)
        else:
            print("Warning: Loading 3DO version 2.1 and no ColorMap was found!")

    if clearScene:
        clearAllScenes()

    # Load model's textures
    importMaterials(model.materials, getDefaultMatFolders(file_path) + mat_dirs, cmp)

    # Create objects from model
    _create_objects_from_model(model, uvAbsolute=(isJkdf2 and uvAbsolute_2_1), geosetNum=0, vertexColors=importVertexColors, importRadiusObj=importRadiusObj, preserveOrder=preserveOrder)

    # Set model's insert offset and radius
    baseObj = bpy.data.objects.new(model.name, None)
    baseObj.empty_draw_size = (0.0)
    bpy.context.scene.objects.link(baseObj)

    baseObj.location = model.insert_offset
    if importRadiusObj:
        _set_model_radius(baseObj, model.radius)

    firstChild             = model.meshHierarchy[0].obj
    firstChild.parent_type = 'OBJECT'
    firstChild.parent      = baseObj

    # Add model to the "Model3do" group
    if kGModel3do in bpy.data.groups:
        group = bpy.data.groups[kGModel3do]
    else:
        group = bpy.data.groups.new(kGModel3do)
    group.objects.link(baseObj)

    print(" done in %.4f sec." % (time.process_time() - startTime))
    return baseObj
