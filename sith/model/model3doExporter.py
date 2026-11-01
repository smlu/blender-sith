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

import bpy, bmesh, mathutils, os
import numpy as np

from ..types import BenchmarkMeter
from ..utils import *
from typing import Dict, List, Optional

from .model3do import *
from .model3doLoader import Model3doFileVersion
from . import model3doWriter
from .utils import *

kDefaultLightMode   = 3
kDefaultTexMode     = 3
kDefaultVertexColor = Vector4f(0.0, 0.0, 0.0, 1.0)
kHNDefaultFlags     = 0
kHNDefaultType      = 0

def export3do(obj: bpy.types.Object, path: str, version: Model3doFileVersion, uvAbsolute: bool, exportVertexColors: bool, sync_mesh_list: bool, *, warnings=None):
    """Build the resource from a Blender model, then write the requested version."""
    with BenchmarkMeter(' done in {:.4f} sec.'):
        print("exporting 3DO: %r..." % (path), end="")

        bpy.path.ensure_ext(path, '.3do')
        model_name = os.path.basename(path)
        model3do = makeModel3doFromObj(model_name, obj, uvAbsolute=uvAbsolute, exportVertexColors=exportVertexColors, sync_mesh_list=sync_mesh_list)
        if not model3do.meshHierarchy:
            raise ValueError('No exportable joints were found; select a model hierarchy, not only radius helpers.')
        header   = getExportFileHeader(f"3DO model '{os.path.basename(path)}'")
        model3doWriter.save3do(model3do, path, version, header, warnings=warnings)


def _set_hnode_pose(node: Mesh3doNode, scale: mathutils.Vector):
    """Copy a local pose to a resource node without changing the Blender object."""
    # Only inherited scale affects this translation. The object's own scale is
    # already baked into its mesh vertices by _model3do_add_obj.
    scaledLocation = vectorMultiply(node.obj.location, scale)
    node.position  = Vector3f(*scaledLocation)
    node.rotation  = objRotationToPYR(node.obj)
    node.pivot     = Vector3f(0.0, 0.0, 0.0)

    # Split Blender's local origin into the engine's position/pivot convention.
    pivot = vectorMultiply(objPivot(node.obj), scale)
    if pivot.length_squared:
        node.position = Vector3f(*(scaledLocation - pivot))
        node.pivot    = Vector3f(*pivot)


def _get_mat_name_org(mat: bpy.types.Material) -> str:
    return mat.name.lower() if mat else ""

def _get_mat_name(mat: bpy.types.Material) -> str:
    name = _get_mat_name_org(mat)
    if not name:
        return ''
    base, separator, suffix = name.rpartition('.')
    if separator and suffix.isdigit() and base.endswith('.mat'):
        name = base
    return name if name.endswith('.mat') else name + '.mat'

def _is_aux_obj(obj: bpy.types.Object) -> bool:
    return isRadiusObj(obj)

def _uv_add_image_size(uv: mathutils.Vector, mat) -> mathutils.Vector:
    image = getMaterialImage(mat)
    return vectorMultiply(uv, mathutils.Vector(image.size)) if image else uv


def _find_vertex(vlist: List[Vector3f], v: Vector3f, vcolors: List[Vector4f], vcolor: Vector4f, normals: List[Vector3f], normal: Vector3f, used_in_face=()) -> int:
    def np_array(o):
        return np.array(o, dtype="f,f,f")
    for vidx in np.where(np_array(vlist) == np_array(v))[0]:
        if (vidx not in used_in_face and vidx < len(vcolors) and vidx < len(normals)
                and vcolors[vidx] == vcolor and normals[vidx] == normal):
            return vidx
    return -1


def _scaled_normal(normal, scale):
    # Cofactors also work for a flattened mesh. Reflections reverse corner order
    # below, so remove their determinant sign to keep outward-facing normals.
    result = (normal[0] * scale.y * scale.z,
              normal[1] * scale.x * scale.z,
              normal[2] * scale.x * scale.y)
    if math.prod(scale) < 0:
        result = tuple(-value for value in result)

    # Normalize the cofactors before float32 storage. A mathutils.Vector can
    # underflow small products to zero or overflow large products to infinity.
    length = math.hypot(*result)
    if not math.isfinite(length):
        raise ValueError('3DO scaled normals must be finite')
    return Vector3f(*(value / length for value in result)) if length else Vector3f(0.0, 0.0, 0.0)


def _model3do_add_mesh(model: Model3do, obj: bpy.types.Object, scale: mathutils.Vector, uvAbsolute: bool, exportVertexColors: bool, geometryMode=GeometryMode.Texture) -> int:
    """Convert mesh corners to 3DO vertex/color and UV tables, baking scale."""
    mesh = obj.data
    if mesh is None:
        return -1
    # Material slots may override shared mesh materials on this object only.
    # Resolve their effective values without changing either datablock.
    materials = [slot.material for slot in obj.material_slots]

    mesh_idx = 0
    if len(model.geosets) > 0:
        mesh_idx = len(model.geosets[0].meshes)
    else:
        model.geosets.append(Model3doGeoSet())

    assertName(mesh.name, allowSpaces=True, maxLength=None)
    mesh3do = Mesh3do(mesh_idx, mesh.name)
    mesh3do.geometryMode = geometryMode

    # 1. Build the model-wide material table; faces reference this table rather
    # than Blender's per-mesh material slots.
    for mat in materials:
        name = _get_mat_name(mat)
        if len(name) > 0: # mesh could have non existing material
            if not name.endswith(".mat"):
                print(f"\nWarning: adding an extension '.mat' to the material file name '{name}'")
                name = _get_mat_name(mat)

            if not model.materials.count(name):
                assertName(name, maxLength=None)
                model.materials.append(name)

    # 2. Read faces through BMesh so engine-specific per-face layers survive.
    # Color values still come from mesh RNA to preserve their linear-light units.
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    active_color  = mesh.color_attributes.active_color or next(iter(mesh.color_attributes), None)
    # Imported corner layers contain no values for loose vertices. Their POINT
    # companion retains those colors; an explicitly active POINT layer wins.
    loose_colors = (
        active_color if active_color and active_color.domain == 'POINT'
        else mesh.color_attributes.get(k3doLooseColors)
    )
    if loose_colors and loose_colors.domain != 'POINT':
        loose_colors = None

    uv_layer      = bm.loops.layers.uv.verify()
    uv_units      = bm.loops.layers.int.get(k3doUvAbsolute)
    used_vertices = set()
    uv_images = {}
    # Custom normals and explicit sharp edges belong to corners, not vertices.
    # Ordinary imported meshes keep the existing geometric vertex normals.
    split_normals = mesh.has_custom_normals or any(edge.use_edge_sharp for edge in mesh.edges)
    corner_normals = mesh.corner_normals if split_normals else None

    for face in bm.faces:
        face3do = Mesh3doFace()
        face3do.materialIdx = -1
        mat = None
        if face.material_index >= 0 and face.material_index < len(materials):
            mat = materials[face.material_index]
            mat_name = _get_mat_name(mat)
            face3do.materialIdx = model.materials.index(mat_name) if mat_name in model.materials else -1
            if face3do.materialIdx < 0:
                print(f"\nWarning: Couldn't find material index for mesh:'{mesh3do.name}' face:{len(mesh3do.faces)}!")
                mat = None

        face3do.type         = bmFaceGetType(face, bm)
        face3do.geometryMode = bmFaceGetGeometryMode(face, bm)
        face3do.lightMode    = bmFaceGetLightMode(face, bm)
        face3do.textureMode  = bmFaceGetTextureMode(face, bm)
        face3do.color        = bmFaceGetExtraLight(face, bm)
        face3do.normal       = _scaled_normal(face.normal, scale)

        # 3. Convert each corner, reversing winding for reflected scale. 3DO
        # stores color and normal per vertex. Coincident vertices with different
        # lighting normals or colors must remain separate to retain seams.
        loops = list(zip(face.loops, mesh.polygons[face.index].loop_indices))
        if math.prod(scale) < 0:
            loops.reverse()

        for loop, source_loop in loops:
            used_vertices.add(loop.vert.index)
            vertx  = Vector3f(*vectorMultiply(loop.vert.co, scale))
            normal = _scaled_normal(corner_normals[source_loop].vector if corner_normals is not None
                                    else loop.vert.normal, scale)
            color_index = loop.vert.index if active_color and active_color.domain == 'POINT' else source_loop

            # RNA exposes linear color for both byte and float attributes; BMesh
            # byte-color values are sRGB and must not be exported as linear light.
            vcolor = (
                Vector4f(*active_color.data[color_index].color)
                if exportVertexColors and active_color else kDefaultVertexColor
            )
            if not all(math.isfinite(value) for value in (*vertx, *normal, *vcolor)):
                bm.free()
                raise ValueError('3DO positions, normals and vertex colors must be finite')

            # Coincident corners may still be distinct source vertices. Welding
            # them within one polygon would create repeated indices on export.
            vidx = _find_vertex(mesh3do.vertices, vertx, mesh3do.vertexColors, vcolor,
                                mesh3do.normals, normal, face3do.vertexIdxs)
            if vidx < 0:
                vidx = len(mesh3do.vertices)
                mesh3do.vertices.append(vertx)
                mesh3do.vertexColors.append(vcolor)
                mesh3do.normals.append(normal)

            face3do.vertexIdxs.append(vidx)

            # Convert UV units only when they differ from the stored units.
            # Missing textures can leave imported UVs in pixel coordinates;
            # their layer marker prevents multiplying by image size twice.
            uv = loop[uv_layer].uv
            stored_absolute = bool(loop[uv_units]) if uv_units else False
            textured = min(int(mesh3do.geometryMode), int(face3do.geometryMode)) == 4 and mat is not None
            if uvAbsolute != stored_absolute and mat is not None:
                try:
                    if mat not in uv_images:
                        uv_images[mat] = getMaterialImage(mat)
                    image = uv_images[mat]
                except ValueError:
                    bm.free()
                    raise
                if image is None or min(image.size) <= 0:
                    if textured:
                        bm.free()
                        raise ValueError(f"Cannot convert UV units without a texture image for material '{mat.name}'")
                elif uvAbsolute:
                    uv = vectorMultiply(uv, mathutils.Vector(image.size))
                else:
                    uv = vectorDivide(uv, mathutils.Vector(image.size))

            uv = Vector2f(uv.x, -uv.y) # Note: Flipped v
            if not all(math.isfinite(value) for value in uv):
                bm.free()
                raise ValueError('3DO texture coordinates must be finite')
            if not mesh3do.uvs.count(uv):
                mesh3do.uvs.append(uv)

            uv_idx = mesh3do.uvs.index(uv)
            face3do.uvIdxs.append(uv_idx)

        mesh3do.faces.append(face3do)

    # 4. Retain loose vertices in recovered/vertex-only models. Use the indices
    # visited above rather than traversing potentially degenerate face adjacency.
    for vertex in bm.verts:
        if vertex.index in used_vertices:
            continue

        position = Vector3f(*vectorMultiply(vertex.co, scale))
        color = (Vector4f(*loose_colors.data[vertex.index].color)
                 if exportVertexColors and loose_colors else kDefaultVertexColor)
        if not all(math.isfinite(value) for value in (*position, *color)):
            bm.free()
            raise ValueError('3DO positions and vertex colors must be finite')

        mesh3do.vertices.append(position)
        mesh3do.vertexColors.append(color)
        mesh3do.normals.append(_scaled_normal(vertex.normal, scale))

    bm.free()

    assert len(mesh3do.vertices) == len(mesh3do.vertexColors) == len(mesh3do.normals)
    model.geosets[0].meshes.append(mesh3do)
    return mesh_idx


def _set_mesh_properties(mesh: Mesh3do, obj: bpy.types.Object, scale: mathutils.Vector):
    mesh.geometryMode = objGeometryMode(obj)

    radius_obj = getMeshRadiusObj(mesh, obj)
    if radius_obj is None:
        mesh.radius = objRadius(obj, scale)
    else:
        mesh.radius = radiusHelperValue(radius_obj, scale)

    try:
        mesh.lightMode = LightMode[obj.sith_model3do_light_mode]
    except:
        print(f"\nWarning: Invalid lighting mode for mesh '{mesh.name}', using default value!")
        mesh.lightMode = kDefaultLightMode

    try:
        mesh.textureMode = TextureMode[obj.sith_model3do_texture_mode]
    except:
        print(f"\nWarning: Invalid texture mode for mesh '{mesh.name}', using default value!")
        mesh.textureMode = kDefaultTexMode

def _get_obj_hnode_name(obj: bpy.types.Object):
    name = stripOrderPrefix(obj.name)
    if len(obj.sith_model3do_hnode_name) > 0:
        name = obj.sith_model3do_hnode_name

    assertName(name, maxLength=None)
    return name

def _get_obj_hnode_idx(nodes: List[Mesh3doNode], obj: bpy.types.Object):
    if obj is not None:
        for idx, n in enumerate(nodes):
            if n.obj == obj:
                return idx
    return -1

def _get_hnode_last_sibling(first_child: Mesh3doNode, nodes: List[Mesh3doNode]):
    sidx = first_child.siblingIdx
    if sidx > -1:
        return _get_hnode_last_sibling(nodes[sidx], nodes)
    return first_child

def _model3do_add_hnode(model: Model3do, mesh_idx: int, obj: bpy.types.Object, parent: bpy.types.Object, scale: mathutils.Vector):
    # Build links with temporary list indices. reorderNodes() later applies the
    # requested sequence order and remaps parent/child/sibling references together.
    name               = _get_obj_hnode_name(obj)
    node               = Mesh3doNode(name)
    node.idx           = obj.sith_model3do_hnode_idx
    node.flags         = Mesh3doNodeFlags.fromHex(obj.sith_model3do_hnode_flags)
    node.type          = Mesh3doNodeType.fromHex(obj.sith_model3do_hnode_type)
    node.meshIdx       = mesh_idx
    node.parentIdx     = _get_obj_hnode_idx(model.meshHierarchy, parent)
    node.firstChildIdx = -1
    node.siblingIdx    = -1
    node.numChildren   = 0
    node.obj           = obj

    node_idx = len(model.meshHierarchy)
    if node.parentIdx > -1:
        pnode = model.meshHierarchy[node.parentIdx]
        if pnode.firstChildIdx < 0:
           pnode.firstChildIdx = node_idx
        else:
            snode = model.meshHierarchy[pnode.firstChildIdx]
            snode = _get_hnode_last_sibling(snode,  model.meshHierarchy)
            snode.siblingIdx = node_idx
        pnode.numChildren += 1

    _set_hnode_pose(node, scale)
    model.meshHierarchy.append(node)

def _model3do_add_obj(model: Model3do, obj: bpy.types.Object, parent: bpy.types.Object = None, scale: mathutils.Vector = mathutils.Vector((1.0,) * 3), uvAbsolute: bool = False, exportVertexColors: bool = False, hierarchyOnly: bool = False):
    if _is_aux_obj(obj):
        return
    if obj.type not in ('EMPTY', 'MESH'):
        validateObjInstancing(obj)
        # Unsupported leaves are harmless, but skipping a parent would also
        # discard its mesh/joint descendants and their transforms/animation.
        pending = list(obj.children)
        while pending:
            child = pending.pop()
            if _is_aux_obj(child):
                continue
            validateObjInstancing(child)
            if child.type in ('EMPTY', 'MESH'):
                raise ValueError(f"Bake or reparent joint '{child.name}' out of unsupported parent '{obj.name}' ({obj.type}) before export")
            pending.extend(child.children)
        return

    validateObjTransform(obj, scale)

    # Raw mesh data retains the authored per-face engine layers. Require live
    # geometry effects to be applied rather than silently dropping them or
    # evaluating a mesh whose custom layers may no longer correspond.
    if not hierarchyOnly and obj.type == 'MESH':
        validateMeshGeometry(obj)

    # Edit Mode owns a separate live mesh. Flush it without leaving Edit Mode
    # so exported positions, topology, UVs and bounds include the visible edits.
    if not hierarchyOnly and obj.type == 'MESH' and obj.mode == 'EDIT':
        obj.update_from_editmode()

    # Bake this object's scale and all ancestor scales into mesh geometry.
    objScale = vectorMultiply(scale, obj.scale)
    mesh_idx = -1 if hierarchyOnly else _model3do_add_mesh(
        model, obj, objScale, uvAbsolute, exportVertexColors, objGeometryMode(obj)
    )
    if mesh_idx > -1:
        mesh = model.geosets[0].meshes[mesh_idx]
        _set_mesh_properties(mesh, obj, objScale)

    # Local location is not scaled by the object's own scale in Blender; pass
    # only inherited scale here, then pass the combined scale to its children.
    _model3do_add_hnode(model, mesh_idx, obj, parent, scale)

    # Add children
    for child in obj.children:
        _model3do_add_obj(
            model, child, parent=obj, scale=objScale, uvAbsolute=uvAbsolute,
            exportVertexColors=exportVertexColors, hierarchyOnly=hierarchyOnly
        )


def _get_model_radius(model):
    """Measure exported vertices in model space using the engine's pivot chain."""
    matrices = {}

    def world(index):
        if index not in matrices:
            # A mesh includes its own pivot translation, while its descendants
            # inherit the joint transform with that mesh pivot removed.
            node = model.meshHierarchy[index]
            local = makeRotationMatrix(*node.rotation).to_4x4()
            local.translation = node.position
            local = local @ mathutils.Matrix.Translation(node.pivot)
            if node.parentIdx >= 0:
                parent = model.meshHierarchy[node.parentIdx]
                local = world(node.parentIdx) @ mathutils.Matrix.Translation(-mathutils.Vector(parent.pivot)) @ local

            matrices[index] = local
        return matrices[index]

    # Shared parent matrices are cached so each vertex only needs its final
    # mesh-to-model transform, not another walk through the hierarchy.
    return max((
        (world(node.idx) @ mathutils.Vector(vertex)).length
        for node in model.meshHierarchy if node.meshIdx >= 0
        for vertex in model.geosets[0].meshes[node.meshIdx].vertices
    ), default=0.0)


def _valid_radius(requested, required, label):
    if not math.isfinite(requested) or requested < 0:
        raise ValueError(f"Invalid radius for '{label}': must be finite and nonnegative")
    if requested + 1e-6 >= required:
        return requested

    # Do not preserve an authored bound that clips the geometry actually exported.
    repaired = math.ceil(required * 1e6) / 1e6
    print(f"Warning: Enlarging radius for '{label}' from {requested:g} to {repaired:g} to enclose its geometry")
    return repaired


def _sync_model_meshes(model: Model3do):
    """Order meshes by their hierarchy nodes while keeping every binding valid.

    Empty joints consume no mesh slot, so mesh IDs are dense but need not equal
    node IDs when the hierarchy contains empties. All geosets use the same map.
    """
    if not model.geosets:
        return

    # 1. Every geoset must be able to use the same old-to-new mesh index map.
    mesh_count = len(model.geosets[0].meshes)
    if not all(len(geoset.meshes) == mesh_count for geoset in model.geosets):
        raise # Maybe print some error or warning

    # 2. Walk normalized node order and number only joints that own a mesh.
    index_map: Dict[int, int] = {}
    new_index = 0
    for node in model.meshHierarchy:
        if node.meshIdx >= 0:
            index_map[node.meshIdx] = new_index
            node.meshIdx = new_index # Update mesh index
            new_index += 1

    # 3. Apply the mapping to each geoset after updating the nodes' mesh bindings.
    for geoset in model.geosets:
        new_meshes: List[Optional[Mesh3do]] = [None] * mesh_count
        for old_index, mesh in enumerate(geoset.meshes):
            if old_index in index_map:
                mesh.idx = index_map[old_index]
                new_meshes[mesh.idx] = mesh

        # Unreferenced meshes have no node ordering; retain them in the unused
        # slots rather than discard resource geometry during synchronization.
        remaining_meshes = [mesh for i, mesh in enumerate(geoset.meshes) if i not in index_map]
        for i, slot in enumerate(new_meshes):
            if slot is None:
                if remaining_meshes:
                    new_meshes[i] = remaining_meshes.pop(0)
                    new_meshes[i].idx = i
                # else:
                #     raise ValueError(f"Not enough meshes to fill all slots in geoset")

        geoset.meshes = new_meshes


def makeModel3doFromObj(name: str, obj: bpy.types.Object, uvAbsolute: bool = False, exportVertexColors: bool = False, sync_mesh_list: bool = True, hierarchyOnly: bool = False):
    """Collect local geometry and hierarchy; hierarchyOnly also serves KEY export."""
    if obj.type not in ('MESH', 'EMPTY'):
        raise ValueError('3DO/KEY export requires a MESH or EMPTY root object')
    model = Model3do(name)
    model.geosets.append(Model3doGeoSet())

    radius_obj = getModelRadiusObj(obj)

    # 1. A mesh root is a joint. An EMPTY with children is instead the model
    # wrapper: its location becomes INSERT OFFSET, not a hierarchy-node pose.
    if obj.type == 'MESH' or len(obj.children) == 0:
        _model3do_add_obj(model, obj, uvAbsolute=uvAbsolute, exportVertexColors=exportVertexColors, hierarchyOnly=hierarchyOnly)
    else:
        validateObjTransform(obj)
        rotation = makeRotationMatrix(*objRotationToPYR(obj))
        if any(abs(rotation[row][column] - (row == column)) > 1e-6
               for row in range(3) for column in range(3)):
            raise ValueError('Apply model wrapper rotation before export')

        model.insertOffset = Vector3f(*obj.location)
        for child in obj.children:
            _model3do_add_obj(
                model, child, parent=obj, scale=obj.scale, uvAbsolute=uvAbsolute,
                exportVertexColors=exportVertexColors, hierarchyOnly=hierarchyOnly
            )

    # 2. Normalize node order before assigning optional mesh order. KEY uses this
    # same node layout but needs neither mesh extraction nor geometry bounds.
    model.reorderNodes(requireRoot=not hierarchyOnly)
    if hierarchyOnly:
        return model

    # With sync disabled, retain traversal mesh order and independent node IDs.
    if sync_mesh_list:
        _sync_model_meshes(model)

    # 3. Ensure mesh culling spheres enclose the geometry actually written.
    for mesh in model.geosets[0].meshes:
        required = max((mathutils.Vector(vertex).length for vertex in mesh.vertices), default=0.0)
        mesh.radius = _valid_radius(mesh.radius, required, mesh.name)

    # 4. Preserve an authored model RADIUS: it controls collision defaults, not
    # the visual enclosure. Compute a geometry bound only when none was supplied.
    if radius_obj is not None:
        model.radius = radiusHelperValue(radius_obj, obj.scale)
    elif kModel3doRadius in obj:
        radius = obj[kModel3doRadius]
        if not math.isfinite(radius) or radius < 0:
            raise ValueError('Model radius must be finite and nonnegative')
        if any(not math.isfinite(value) for value in obj.scale):
            raise ValueError('Model scale must be finite')
        model.radius = radius * max(abs(value) for value in obj.scale)
    else:
        model.radius = math.ceil(_get_model_radius(model) * 1e6) / 1e6

    if not math.isfinite(model.radius):
        raise ValueError('Model radius must be finite')

    return model
