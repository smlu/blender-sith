import bpy, bmesh, mathutils, os, time

from ijim.utils import *
from typing import List

from .model3do import *
from .model3doLoader import Model3doFileVersion
from . import model3doWriter
from .utils import *

kDefaultLightMode   = 3
kDefaultTexMode     = 3
kDefaultVertexColor = Vector4f(0.0, 0.0, 0.0, 1.0)
kDefaultFaceColor   = Vector4f(0.0, 0.0, 0.0, 1.0)
kHNDefaultFlags     = 0
kHNDefaultType      = 0


def _set_hnode_location(node: Mesh3doHierarchyNode, scale: mathutils.Vector):
    node.position = Vector3f(*vectorMultiply(node.obj.location, scale))
    node.rotation = objOrientationToImEuler(node.obj)
    node.pivot    = Vector3f(0.0, 0.0, 0.0)

    pc = None
    for c in node.obj.constraints:
        if type(c) == bpy.types.PivotConstraint:
            pc = c
            break

    if not pc is None and pc.influence:
        pivot = -pc.offset
        if c.target:
            pivot += -c.target.location
        node.position = Vector3f(*(node.obj.location - pivot))
        node.pivot    = Vector3f(*pivot)

def _get_mat_name_org(mat: bpy.types.Material):
    return mat.name.lower() if mat else ""

def _get_mat_name(mat: bpy.types.Material):
    name = _get_mat_name_org(mat)
    if not name.endswith(".mat"):
        name = os.path.splitext(name)[0] + '.mat'
    return name

def _is_aux_obj(obj: bpy.types.Object):
    return (kModelRadius in obj.name) or (kMeshRadius in obj.name)

def _uv_add_image_size(uv: mathutils.Vector, mat) -> mathutils.Vector:
    for s in mat.texture_slots:
        if s and s.texture_coords == 'UV' and s.texture and s.texture.type == 'IMAGE':
            return vectorMultiply(uv, mathutils.Vector(s.texture.image.size))
    return uv

def _model3do_add_mesh(model: Model3do, mesh: bpy.types.Mesh, scale: mathutils.Vector, uvWithImageSize: bool, exportVertexColors: bool) -> int:
    if mesh is None:
        return -1

    mesh_idx = 0
    if len(model.geosets) > 0:
        mesh_idx = len(model.geosets[0].meshes)
    else:
        model.geosets.append(Model3doGeoSet())

    assertName(mesh.name)
    mesh3do = Mesh3do(mesh_idx, mesh.name)

    # Set model resources
    for mat in mesh.materials:
        name = _get_mat_name_org(mat)
        if len(name) > 0: # mesh could have non existing material
            if not name.endswith(".mat"):
                print("\nWarning: adding an extension '.mat' to the material file name '{}' ".format(name))
                name = _get_mat_name(mat)

            if not model.materials.count(name):
                assertName(name)
                model.materials.append(name)

    # Set mesh faces
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    vert_color = bm.loops.layers.color.verify()
    uv_layer   = bm.loops.layers.uv.verify()

    for face in bm.faces:
        face3do = Mesh3doFace()
        face3do.materialIdx = -1
        mat = None
        if face.material_index >= 0 and face.material_index < len(mesh.materials):
            mat = mesh.materials[face.material_index]
            mat_name = _get_mat_name(mat)
            face3do.materialIdx = model.materials.index(mat_name) if mat_name in model.materials else -1
            if face3do.materialIdx < 0:
                print(f"\nWarning: Couldn't find material index for mesh:'{mesh3do.name}' face:{len(mesh3do.faces)}!")
                mat = None

        face3do.type         = bmFaceGetType(face, bm)
        face3do.geometryMode = bmFaceGetGeometryMode(face, bm)
        face3do.lightMode    = bmFaceGetLightMode(face, bm)
        face3do.textureMode  = bmFaceGetTextureMode(face, bm)
        face3do.color        = kDefaultFaceColor
        face3do.normal       = Vector3f(*face.normal)

        # Set face vertex and texture index
        for loop in face.loops:
            vertx = Vector3f(*vectorMultiply(loop.vert.co, scale))
            if not mesh3do.vertices.count(vertx):
                mesh3do.vertices.append(vertx)
                vertColor = Vector4f(*loop[vert_color]) if exportVertexColors else kDefaultVertexColor
                mesh3do.vertexColors.append(vertColor)
                mesh3do.normals.append(Vector3f(*loop.vert.normal))

            vertx_idx = mesh3do.vertices.index(vertx)
            face3do.vertexIdxs.append(vertx_idx)

            # Set UV coordinates
            uv = loop[uv_layer].uv
            if uvWithImageSize and mat is not None:
                if len(mat.texture_slots) == 0:
                    print(f"\nWarning: Using plain UV coords for mesh:'{mesh3do.name}' face:{len(mesh3do.faces)} due to face hasn't any texture set!")
                    face3do.materialIdx = -1
                else:
                    uv = _uv_add_image_size(uv, mat)
                    if uv != mathutils.Vector.Fill(2) and uv == loop[uv_layer].uv:
                        print(f"\nWarning: Using plain UV coord due to no face texture with UV coords and image was found! mesh:'{mesh3do.name}' face:{len(mesh3do.faces)}")
                        face3do.materialIdx = -1

            uv = Vector2f(uv.x, -uv.y) # Note: Flipped v
            if not mesh3do.uvs.count(uv):
                mesh3do.uvs.append(uv)

            uv_idx = mesh3do.uvs.index(uv)
            face3do.uvIdxs.append(uv_idx)
        mesh3do.faces.append(face3do)
    bm.free()

    assert len(mesh3do.vertices) == len(mesh3do.vertexColors) == len(mesh3do.normals)
    model.geosets[0].meshes.append(mesh3do)
    return mesh_idx

def _set_mesh_properties(mesh: Mesh3do, obj: bpy.types.Object, scale: mathutils.Vector):
    mesh.geometryMode = objGeometryMode(obj)

    radius_obj = getMeshRadiusObj(mesh)
    if radius_obj is None:
        obj = getMeshObjectByName(mesh.name)
        mesh.radius = objRadius(obj, scale)
    else:
        mesh.radius = radius_obj.dimensions[0] / 2

    try:
        mesh.lightMode = LightMode[obj.model3do_light_mode]
    except:
        print("\nWarning: Invalid lighting mode for mesh '{}', using default value!".format(mesh.name))
        mesh.lightMode = kDefaultLightMode

    try:
        mesh.textureMode = TextureMode[obj.model3do_texture_mode]
    except:
        print("\nWarning: Invalid texture mode for mesh '{}', using default value!".format(mesh.name))
        mesh.textureMode = kDefaultTexMode

def _get_obj_hnode_name(obj: bpy.types.Object):
    name = stripOrderPrefix(obj.name)
    if len(obj.model3do_hnode_name) > 0:
        name = obj.model3do_hnode_name

    assertName(name)
    return name

def _get_obj_hnode_idx(nodes: List[Mesh3doHierarchyNode], obj: bpy.types.Object):
    if obj is not None:
        for idx, n in enumerate(nodes):
            if n.obj == obj:
                return idx
    return -1

def _get_hnode_last_sibling(first_child: Mesh3doHierarchyNode, nodes: List[Mesh3doHierarchyNode]):
    sidx = first_child.siblingIdx
    if sidx > -1:
        return _get_hnode_last_sibling(nodes[sidx], nodes)
    return first_child

def _model3do_add_hnode(model: Model3do, mesh_idx: int, obj: bpy.types.Object, parent: bpy.types.Object, scale: mathutils.Vector):
    name               = _get_obj_hnode_name(obj)
    node               = Mesh3doHierarchyNode(name)
    node.idx           = obj.model3do_hnode_num
    node.flags         = Mesh3doNodeFlags.fromHex(obj.model3do_hnode_flags)
    node.type          = Mesh3doNodeType.fromHex(obj.model3do_hnode_type)
    node.meshIdx       = mesh_idx
    node.parentIdx     = _get_obj_hnode_idx(model.hierarchyNodes, parent)
    node.firstChildIdx = -1
    node.siblingIdx    = -1
    node.numChildren   = 0
    node.obj           = obj

    node_idx = len(model.hierarchyNodes)
    if node.parentIdx > -1:
        pnode = model.hierarchyNodes[node.parentIdx]
        if pnode.firstChildIdx < 0:
           pnode.firstChildIdx = node_idx
        else:
            snode = model.hierarchyNodes[pnode.firstChildIdx]
            snode = _get_hnode_last_sibling(snode,  model.hierarchyNodes)
            snode.siblingIdx = node_idx
        pnode.numChildren += 1

    _set_hnode_location(node, scale)
    model.hierarchyNodes.append(node)

def _model3do_add_obj(model: Model3do, obj: bpy.types.Object, parent: bpy.types.Object = None, scale: mathutils.Vector = mathutils.Vector((1.0,)*3), uvWithImageSize: bool = False, exportVertexColors: bool = False):
    if 'EMPTY' != obj.type != 'MESH' or _is_aux_obj(obj):
        return

    scale    = vectorMultiply(scale, obj.scale)
    mesh_idx = _model3do_add_mesh(model, obj.data, scale, uvWithImageSize, exportVertexColors)
    if mesh_idx > -1:
        mesh = model.geosets[0].meshes[mesh_idx]
        _set_mesh_properties(mesh, obj, scale)

    _model3do_add_hnode(model, mesh_idx, obj, parent, scale)
    for child in obj.children:
        _model3do_add_obj(model, child, parent=obj, scale=scale, uvWithImageSize=uvWithImageSize, exportVertexColors=exportVertexColors)

def _get_model_radius(obj, scale: mathutils.Vector = mathutils.Vector((1.0,)*3)):
    min = mathutils.Vector((999999.0,)*3)
    max = mathutils.Vector((-999999.0,)*3)
    def do_bb(o, s):
        if o.type != 'MESH': return
        nonlocal min, max
        for  v in o.data.vertices:

            v_world = vectorMultiply(o.matrix_local * v.co, s)
            if v_world.x < min.x:
                min.x = v_world.x
            if v_world.x > max.x:
                max.x = v_world.x

            if v_world.y < min.y:
                min.y = v_world.y
            if v_world.y > max.y:
                max.y = v_world.y

            if v_world.z < min.z:
                min.z = v_world.z
            if v_world.z > max.z:
                max.z = v_world.z

    def traverse_children(o, s):
        for c in o.children:
            s = vectorMultiply(s, c.scale)
            do_bb(c, s)
            traverse_children(c, s)

    scale = vectorMultiply(scale, obj.scale)
    do_bb(obj, scale)
    traverse_children(obj, scale)
    return ((max - min).length /2)

def makeModel3doFromObj(name, obj: bpy.types.Object, uvWithImageSize: bool = False, exportVertexColors: bool = False):
    model = Model3do(name)
    model.geosets.append(Model3doGeoSet())

    model.insertOffset = Vector3f(*obj.location)
    radius_obj = getModelRadiusObj(obj)
    if radius_obj is None:
        model.radius = _get_model_radius(obj)
    else:
        model.radius = radius_obj.dimensions[0] / 2

    if len(obj.children):
        for child in obj.children:
            _model3do_add_obj(model, child, parent=obj, scale=obj.scale, uvWithImageSize=uvWithImageSize, exportVertexColors=exportVertexColors)
    else:
        _model3do_add_obj(model, obj, uvWithImageSize=uvWithImageSize, exportVertexColors=exportVertexColors)

    model.reorderNodes()
    return model

def export3do(obj: bpy.types.Object, path: str, version: Model3doFileVersion, exportVertexColors: bool):
    bpy.path.ensure_ext(path, '.3do')
    print("exporting 3DO: %r..." % (path), end="")
    start_time = time.process_time()

    model_name = os.path.basename(path)
    if not isValidNameLen(model_name):
        raise ValueError("Export file name '{}' is longer then {} chars!".format(model_name, maxNameLen))

    uvWithImageSize = (version == Model3doFileVersion.Version2_1)
    model3do = makeModel3doFromObj(model_name, obj, uvWithImageSize=uvWithImageSize, exportVertexColors=exportVertexColors)
    header   = getExportFileHeader("3DO model '{}'".format(os.path.basename(path)))
    model3doWriter.write(model3do, path, version, header)

    print(" done in %.4f sec." % (time.process_time() - start_time))
