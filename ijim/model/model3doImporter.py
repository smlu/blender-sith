import mathutils
import bpy, bmesh

import time
from typing import List

from . import model3doLoader
from .utils import *
from .model3do import (
    Model3do,
    ModelMesh
)

from ijim.material.material import importMatFile
from ijim.utils.utils import *

def getObjByName(name):
    if name in bpy.context.scene.objects:
        return bpy.context.scene.objects[name]
    for o in bpy.context.scene.objects:
        if name.lower() == stripOrderPrefix(o.name).lower():
            return o
    raise ValueError("Could not find object '{}'".format(name))

def getMeshObjectByName(meshName: str):
    if meshName in bpy.context.scene.objects:
        return bpy.context.scene.objects[meshName]
    for o in bpy.context.scene.objects:
        if meshName == stripOrderPrefix(o.name):
            return o
        if o.data is not None and o.data.name == meshName:
            return o
    raise ValueError("Could not find mesh object with name '{}'".format(meshName))

def _get_encoded_face_prop(prop):
    return str(int(prop)).encode('utf-8')

def _get_radius_obj(name):
    try:
        return bpy.context.scene.objects[name]
    except:
        return None

def _set_obj_rotation(obj, rotation):
    setObjQuaternionRotation(obj, rotation)

def _set_obj_pivot(obj, pivot):
    # note: this function might be wrong. for example load gen_chicken.3do
    # if pivot[0] == 0 and  pivot[1] == 0 and pivot[2] == 0:
    #     return

    # pc = obj.constraints.new('PIVOT')
    # pc.rotation_range = 'ALWAYS_ACTIVE'
    # pc.use_relative_location = True
    # pc.owner_space = 'LOCAL'
    # pc.offset     =  -mathutils.Vector(pivot)

    # New way 1

    # Removes Pivot constrain by translating mesh by pivot vector
    # Note: in key exporter/importer and 3do exporter scripts, the code that calculates and translates object for pivot can be removed
    pvec = mathutils.Vector(pivot)
    data = obj.data
    if  obj.type == 'MESH' and data is not None and pvec.length > 0 :
        data.transform(mathutils.Matrix.Translation(pvec))

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

def _make_mesh(mesh3do: ModelMesh, mat_list: List):
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

        # Set face normal
        face.normal = mesh3do.faces[face.index].normal

        # Set face material index
        mat_name = mat_list[face3do.materialIdx]
        mat = getGlobalMaterial(mat_name)
        if mat is None:
            print("\nWarning: Could not find or load material file '{}'".format(mat_name))
            mat = makeNewGlobalMaterial(mat_name)

        if not mat.name in mesh.materials:
            mesh.materials.append(mat)
        face.material_index = mesh.materials.find(mat.name)

        # Set face texture
        if not mat.texture_slots[0].texture is None:
            tex = mat.texture_slots[0].texture
            img = tex.image
            tex_layer = bm.faces.layers.tex[uv_layer.name]
            face[tex_layer].image = img

        # Set vertices color and face uv map
        for idx, loop in enumerate(face.loops): # update vertices
            vidx             = loop.vert.index
            loop.vert.normal = mesh3do.normals[vidx]
            loop[vert_color] = mesh3do.vertexColors[vidx]

            # Set UV coordinates
            luv    = loop[uv_layer]
            uvidx  = face3do.uvIdxs[idx]
            if uvidx < len(mesh3do.uvs):
                uv     = mesh3do.uvs[face3do.uvIdxs[idx]]
                luv.uv = (uv[0], -uv[1]) # Note: Flipped v
            elif uvidx > -1:
                print("Warning: UV index out of range. {} >= {} ".format(uvidx, len(mesh3do.uvs)))

    bm.to_mesh(mesh)
    bm.free()

    mesh.update()
    return mesh

def getModelRadiusObj(obj):
    return _get_radius_obj(kModelRadius + stripOrderPrefix(obj.name))

def getMeshRadiusObj(mesh):
    try:
        obj = getMeshObjectByName(mesh.name)
        return _get_radius_obj(kMeshRadius + stripOrderPrefix(obj.name))
    except:
        return None

def _create_objects_from_model(model: Model3do, geosetNum: int, importRadiusObj:bool, preserveOrder: bool):
    meshes = model.geosets[geosetNum].meshes
    for node in model.hierarchyNodes:
        meshIdx = node.meshIdx

        # Get node's mesh
        if meshIdx > -1:
            if meshIdx >= len(meshes):
                raise IndexError("Mesh index {} out of range ({})!".format(meshIdx, len(meshes)))

            mesh3do = meshes[meshIdx]
            mesh    = _make_mesh(mesh3do, model.materials)
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
        obj.name = makeOrderedName(obj.name, node.idx, len(model.hierarchyNodes)) if preserveOrder else obj.name

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
    for node in model.hierarchyNodes:
        if node.parentIdx != -1:
            node.obj.parent_type = 'OBJECT'
            node.obj.parent      = model.hierarchyNodes[node.parentIdx].obj
    bpy.context.scene.update()

def importObject(file_path, mat_paths = [], importRadiusObj = False, preserveOrder = True, clearScene = True):
    print("importing 3DO: %r..." % (file_path), end="")
    startTime = time.process_time()

    model = model3doLoader.load(file_path)
    if len(model.geosets) == 0:
        print("Info: Nothing to load because 3DO model doesn't contain any geoset.")
        return

    if clearScene:
        clearAllScenes()

    # Load model's textures
    importMaterials(model.materials, getDefaultMatFolders(file_path) + mat_paths)

    # Create objects from model
    _create_objects_from_model(model, geosetNum=0, importRadiusObj=importRadiusObj, preserveOrder=preserveOrder)

    # Set model's insert offset and radius
    baseObj = bpy.data.objects.new(model.name, None)
    baseObj.empty_draw_size = (0.0)
    bpy.context.scene.objects.link(baseObj)

    baseObj.location = model.insert_offset
    if importRadiusObj:
        _set_model_radius(baseObj, model.radius)

    firstChild             = model.hierarchyNodes[0].obj
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
