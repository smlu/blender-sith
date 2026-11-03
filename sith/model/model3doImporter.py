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

import bpy, bmesh, mathutils, math, os, json
from ..types import BenchmarkMeter
from ..utils import *
from typing import List, Optional

from . import model3doLoader
from .utils import *
from .model3do import (
    Model3do,
    Mesh3do
)

def import3do(file_path: Union[Path, str], mat_dirs: List[Union[Path, str]] = [], cmp_file: str = '', uvAbsolute_2_1: bool = True, importVertexColors: bool = True, importRadiusObj: bool = False, preserveOrder: bool = True, clearScene: bool = True, *, allowErrors: bool = False, warnings: Optional[List[str]] = None, importVertexNormals: bool = False) -> bpy.types.Object:
    """Import strictly by default; opt-in recovery retains incomplete geometry.

    Recovery diagnostics are returned through ``warnings`` and saved as a Blender
    Text datablock referenced by the model root. Missing source data is not
    reconstructed: placeholders and omitted faces are explicitly reported.
    """
    with BenchmarkMeter(' done in {:.4f} sec.'):
        print("importing 3DO: %r..." % (file_path), end="")

        # 1. Parse and validate before Clear Scene can discard existing work.
        # Recovery is opt-in and reports omitted/incomplete source data.
        diagnostics = []
        with BenchmarkMeter('Info: \nLoaded model from file in {:.4f} sec.', enabled=False):
            model, fileVersion = model3doLoader.load3do(file_path, allowErrors=allowErrors, warnings=diagnostics)
        if warnings is not None:
            warnings.extend(diagnostics)

        usesIndexedMaterials = fileVersion in (model3doLoader.Model3doFileVersion.Version2_1,
                                               model3doLoader.Model3doFileFormat.GrimFandango)
        if not model.meshHierarchy:
            if model.geosets and any(geoset.meshes for geoset in model.geosets):
                raise ValueError('3DO hierarchy is missing; enable Try Recover Broken File to recover available meshes')
            print("Info: Nothing to load because 3DO model doesn't contain a hierarchy.")
            return

        # Geometry-free retail skeletons use an infinite cached radius. Blender
        # needs finite bounds; retain the original sentinel for binary re-export.
        if model.binaryData is not None and model.radius == math.inf:
            model.binaryData['emptyRadius'] = True
            model.radius = 0.0
        _validate_import(model)

        # 2. Legacy text and Grim MODL use palette ColorMaps for material decoding. Resolve
        # external resources separately from the already-validated model data.
        mat_dirs = _convert_to_absolute_paths(mat_dirs, os.path.dirname(file_path))
        cmp = None
        if usesIndexedMaterials:
            try:
                cmp = getCmpFileOrDefault(cmp_file, file_path, searchPaths=mat_dirs)
            except Exception as e:
                print(f"Warning: Failed to load ColorMap '{cmp_file}': {e}")
            if not cmp:
                print("Warning: Loading an indexed 3DO model and no ColorMap was found!")

        if clearScene:
            from .model3doPreview import getPreviewEnabled, setPreviewEnabled
            previewEnabled = getPreviewEnabled(bpy.context.scene)
            clearAllScenes()
            setPreviewEnabled(bpy.context.scene, previewEnabled)

        # 3. Track newly created datablocks for failure cleanup. This is not an
        # undo of Clear Scene; only pre-existing data still present is protected.
        collections = (bpy.data.objects, bpy.data.meshes, bpy.data.materials, bpy.data.images, bpy.data.texts)
        before = [set(collection) for collection in collections]

        try:
            # Load model's textures
            with BenchmarkMeter('Info: \nLoaded materials from files in {:.4f} sec.', enabled=False):
                importMaterials(model.materials, getDefaultMatFolders(file_path, mat_dirs), cmp)

            # 4. Create LOD 0 geometry and joints, then add a wrapper carrying
            # INSERT OFFSET and the authored model radius outside the skeleton.
            _create_objects_from_model(
                model, uvAbsolute=(usesIndexedMaterials and uvAbsolute_2_1), geosetNum=0,
                vertexColors=importVertexColors, importRadiusObj=importRadiusObj,
                preserveOrder=preserveOrder, preserveNormals=importVertexNormals
            )

            baseObj = bpy.data.objects.new(model.name, None)
            baseObj.empty_display_size = (0.0)
            bpy.context.scene.collection.objects.link(baseObj)
            baseObj.location = model.insert_offset
            baseObj[kModel3doRadius] = model.radius
            if model.binaryData is not None:
                baseObj[kModel3doBinaryModel] = json.dumps(model.binaryData)
            if importRadiusObj:
                _set_model_radius(baseObj, model.radius)

            for node in model.meshHierarchy:
                if node.parentIdx == -1:
                    node.obj.parent_type = 'OBJECT'
                    node.obj.parent = baseObj

            # Keep recovery diagnostics with the imported model, not just stdout.
            if diagnostics:
                report = bpy.data.texts.new(f'{model.name} - Import Report')
                report.write(f'Incomplete 3DO import: {file_path}\n\n' + '\n'.join(diagnostics)
                             + '\n\nRecovery is not a repair. Verify missing geometry, UVs and node placement before export.\n')
                report.use_fake_user = True
                baseObj[kModel3doImportReport] = report.name

            from .model3doPreview import ensureObjectMaterials
            for node in model.meshHierarchy:
                ensureObjectMaterials(node.obj)

            return baseObj

        except Exception:
            # Remove only datablocks created by this import, never pre-existing data.
            for collection, original in zip(collections, before):
                for item in list(collection):
                    if item not in original:
                        collection.remove(item, do_unlink=True)
            raise


def _validate_import(model: Model3do):
    """Reject unsafe references before Clear Scene can discard existing work."""
    def finite(values, label):
        validateFloat32(values, label)

    # Blender may accept infinities into mesh data rather than raising an error.
    # Reject them before clearing the scene; recovery sanitizes them separately.
    finite((model.radius, *model.insertOffset), 'Model radius and insert offset')
    if model.radius < 0:
        raise ValueError('Model radius must be nonnegative')
    meshes = model.geosets[0].meshes if model.geosets else []
    nodes = model.meshHierarchy
    visited = set()

    # Validate parent chains independently of sibling order. Remember completed
    # chains so a shared ancestor does not need to be checked for every joint.
    for index, node in enumerate(nodes):
        finite((*node.position, *node.rotation, *node.pivot), f"Node '{node.name}' transforms")
        if node.meshIdx < -1 or node.meshIdx >= len(meshes):
            raise IndexError(f'Mesh index {node.meshIdx} out of range ({len(meshes)})!')

        chain = set()
        while index >= 0 and index not in visited:
            if index >= len(nodes) or index in chain:
                raise ValueError('3DO hierarchy contains an invalid parent or cycle')
            chain.add(index)
            parent = nodes[index].parentIdx
            if parent < -1:
                raise ValueError('3DO hierarchy contains an invalid parent')
            index = parent
        visited.update(chain)

    # Face corner indices must be safe before creating Blender topology. UV
    # references matter only for faces that actually use a textured material.
    for mesh in meshes:
        finite((mesh.radius,), f"Mesh '{mesh.name}' radius")
        if mesh.radius < 0:
            raise ValueError(f"Mesh '{mesh.name}' radius must be nonnegative")
        for values in (mesh.vertices, mesh.vertexColors, mesh.normals, mesh.uvs):
            finite((value for vector in values for value in vector), f"Mesh '{mesh.name}' data")
        for index, face in enumerate(mesh.faces):
            finite((*face.normal, *face.color), f"Mesh '{mesh.name}', face {index} data")
            if len(face.vertexIdxs) < 3:
                raise ValueError(f"Mesh '{mesh.name}', face {index}: polygon has fewer than three corners")
            if any(vertex < 0 or vertex >= len(mesh.vertices) for vertex in face.vertexIdxs):
                raise ValueError(f"Mesh '{mesh.name}', face {index}: invalid vertex index")
            if face.materialIdx < -1 or face.materialIdx >= len(model.materials):
                raise ValueError(f"Mesh '{mesh.name}', face {index}: invalid material index")
            if min(mesh.geometryMode, face.geometryMode) == GeometryMode.Texture and face.materialIdx >= 0:
                if len(face.uvIdxs) != len(face.vertexIdxs):
                    raise ValueError(f"Invalid texture vertex count for mesh '{mesh.name}', face {index}")
                for uv in face.uvIdxs:
                    if uv < 0 or uv >= len(mesh.uvs):
                        raise ValueError(f"Invalid texture vertex {uv} for mesh '{mesh.name}', face {index}: only {len(mesh.uvs)} UVs are available")

    # Individually representable values can still overflow when pivots and
    # hierarchy transforms are applied. Probe the same float32 math before any
    # scene data is removed, including models that share a mesh across joints.
    matrices = {}
    for index in range(len(nodes)):
        chain = []
        current = index
        while current >= 0 and current not in matrices:
            chain.append(current)
            current = nodes[current].parentIdx
        parent = matrices[current] if current >= 0 else mathutils.Matrix.Translation(model.insertOffset)
        for current in reversed(chain):
            node = nodes[current]
            local = makeRotationMatrix(*node.rotation).to_4x4()
            local.translation = node.position
            parent = parent @ local
            finite((value for row in parent for value in row), 'Transformed hierarchy')
            matrices[current] = parent

        node = nodes[index]
        if node.meshIdx >= 0:
            for vertex in meshes[node.meshIdx].vertices:
                baked = mathutils.Vector(vertex) + mathutils.Vector(node.pivot)
                finite((*baked, *(matrices[index] @ baked)), 'Transformed vertex')


def _convert_to_absolute_paths(path_list: List[Union[Path, str]], cwd: Union[Path, str]) -> List[Union[Path, str]]:
    absolute_paths: List[Union[Path, str]] = []
    for path in path_list:
        if not os.path.isabs(path):
            # Convert to absolute path if it's relative
            absolute_path = os.path.abspath(Path(cwd) / path)
        else:
            # Keep the path as it is if it's already absolute
            absolute_path = path
        absolute_paths.append(absolute_path)
    return absolute_paths

def _set_obj_rotation(obj, rotation):
    objSetRotation(obj, rotation)

def _set_obj_pivot(obj, pivot):
    # Bake source pivot translation into the mesh for the editable zero-pivot
    # workflow. This does not recreate the original joint-origin/pivot metadata.
    pvec = mathutils.Vector(pivot)
    if  obj.type == 'MESH' and obj.data is not None and pvec.length > 0:
        obj.data.transform(mathutils.Matrix.Translation(pvec))

def _make_radius_obj(name: str, parent, radius: float):
    if not math.isfinite(radius) or radius < 0:
        raise ValueError('3DO radius must be finite and nonnegative')
    mesh = bpy.data.meshes.new(name)
    ro = bpy.data.objects.new(name, mesh)
    ro.display_type = 'WIRE'
    ro.hide_viewport = True
    ro.parent_type = 'OBJECT'
    ro.parent = parent
    bpy.context.scene.collection.objects.link(ro)

    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=radius)
    bm.to_mesh(mesh)
    bm.free()
    ro[kModel3doRadius] = radius
    ro[kModel3doRadiusShape] = radiusShapeSignature(ro)
    ro[kModel3doRadiusKind] = kMeshRadius if name.startswith(kMeshRadius) else kModelRadius

def _set_model_radius(obj: bpy.types.Object, radius: float):
    _make_radius_obj(kModelRadius + obj.name, obj, radius)

def _set_mesh_radius(obj: bpy.types.Object, radius: float):
    _make_radius_obj(kMeshRadius + obj.name, obj, radius)

def _make_mesh(mesh3do: Mesh3do, uvAbsolute: bool, vertexColors: bool, mat_list: List, preserveNormals: bool = False):
    """Build Blender geometry, preserving engine face modes, colors and UV units."""
    mesh = bpy.data.meshes.new(mesh3do.name)

    # Keep original vertices at their original indices. Repeated corners need
    # separate, coincident vertices to avoid self-linked BMesh topology. Their
    # source mapping also preserves normals and colors, including loose points.
    vertices = list(mesh3do.vertices)
    vertexSources = list(range(len(vertices)))
    faces: List[List[int]] = []
    for face in mesh3do.faces:
        corners = []
        used = set()
        for source in face.vertexIdxs:
            index = source
            if source in used:
                index = len(vertices)
                vertices.append(mesh3do.vertices[source])
                vertexSources.append(source)
            used.add(source)
            corners.append(index)
        faces.append(corners)

    # 1. Create topology, then attach engine face layers through BMesh.
    mesh.from_pydata(vertices, [], faces)

    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()

    vert_color = bm.loops.layers.float_color.verify() if vertexColors else None
    uv_layer   = bm.loops.layers.uv.verify()
    uv_units   = bm.loops.layers.int.new(k3doUvAbsolute)
    bmMeshInit3doLayers(bm)
    uv_images = {}

    # 2. Resolve model-wide material references into local Blender material slots
    # and copy each face's rendering metadata before filling corner attributes.
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
                print(f"\nWarning: Could not find or load material file '{mat_name}'")
                mat = makeNewGlobalMaterial(mat_name)

        if mat:
            if mat.name not in mesh.materials:
                mesh.materials.append(mat)
            face.material_index = mesh.materials.find(mat.name)
        elif face3do.materialIdx < 0:
            # A missing binding must not inherit another face's material slot 0.
            emptySlot = next((index for index, value in enumerate(mesh.materials) if value is None), None)
            if emptySlot is None:
                emptySlot = len(mesh.materials)
                mesh.materials.append(None)
            face.material_index = emptySlot

        # Use the same bound/color image as export when converting UV units.
        img = None
        if uvAbsolute and mat:
            if mat not in uv_images:
                try:
                    image = getMaterialImage(mat)
                    uv_images[mat] = image if image and min(image.size) > 0 else None
                except ValueError as error:
                    # Keep pixel UVs when dimensions are ambiguous, just as for
                    # missing textures. Do not rewrite them using an arbitrary image.
                    print(f"Warning: {error}. Imported UVs remain in pixel units.")
                    uv_images[mat] = None
            img = uv_images[mat]

        # 3. Expand per-vertex colors/normals onto Blender corners. Convert pixel
        # UVs to normalized units only when the texture dimensions are available.
        # Otherwise mark them as absolute so export can preserve their units.
        for idx, loop in enumerate(face.loops): # update vertices
            vidx             = vertexSources[loop.vert.index]
            loop.vert.normal = mesh3do.normals[vidx]
            if vertexColors:
                loop[vert_color] = mesh3do.vertexColors[vidx]

            # Set UV coordinates
            luv    = loop[uv_layer]
            uvIdx  = face3do.uvIdxs[idx]
            loop[uv_units] = int(uvAbsolute and img is None)

            if 0 <= uvIdx < len(mesh3do.uvs):
                uv = mesh3do.uvs[uvIdx]
                if uvAbsolute: # Remove image size from uv
                    if img is not None:
                        uv = vectorDivide(mathutils.Vector(uv), mathutils.Vector(img.size))
                    elif face3do.materialIdx > -1:
                        print(f"\nWarning: Could not remove image size from UV coord due to missing image! mesh:'{mesh3do.name}' face:{face.index} uvIdx:{uvIdx}")
                luv.uv = (uv.x, -uv.y) # Note: Flipped v
            elif min(int(mesh3do.geometryMode), int(face3do.geometryMode)) == 4 and face3do.materialIdx >= 0:
                message = f"Invalid texture vertex {uvIdx} for mesh '{mesh3do.name}', face {face.index}: only {len(mesh3do.uvs)} UVs are available"
                bm.free()
                raise ValueError(message)

    active_color_name = vert_color.name if vert_color else None
    bm.to_mesh(mesh)
    bm.free()

    # Face-corner colors cannot represent unused vertices. Keep a POINT layer
    # for those models as well, populated for all vertices so it can also be
    # selected and edited normally in Blender. Vertex-only models use it directly.
    used_vertices = {vertex for face in mesh.polygons for vertex in face.vertices}
    if vertexColors and len(used_vertices) < len(mesh.vertices):
        point_colors = mesh.color_attributes.new(name=k3doLooseColors, type='FLOAT_COLOR', domain='POINT')
        # Bulk float storage retains signed/HDR channels; scalar RNA color
        # assignment clamps them to the display color range.
        point_colors.data.foreach_set('color', [value for index in vertexSources
                                               for value in mesh3do.vertexColors[index]])
        if not mesh.polygons:
            active_color_name = point_colors.name

    mesh.update()
    if mesh3do.binaryData is not None or preserveNormals:
        # Positive source IDs survive Blender vertex/face reordering; zero means
        # newly authored geometry with no original undocumented record to copy.
        vertex_ids = mesh.attributes.new(k3doBinaryVertex, 'INT', 'POINT')
        vertex_ids.data.foreach_set('value', [index + 1 for index in vertexSources])
        face_ids = mesh.attributes.new(k3doBinaryFace, 'INT', 'FACE')
        face_ids.data.foreach_set('value', list(range(1, len(mesh.polygons) + 1)))
        metadata = mesh3do.binaryData if mesh3do.binaryData is not None else {'vertexData': [0] * len(mesh3do.vertices)}
        mesh[kModel3doBinaryMesh] = json.dumps({'mesh': metadata,
                                              'faces': [face.binaryData for face in mesh3do.faces],
                                              'name': mesh3do.name, 'blenderName': mesh.name,
                                              'normals': [list(normal) for normal in mesh3do.normals],
                                              'shadow': mesh3do.shadow})
        if mesh.polygons:
            # MODL carries authored vertex normals. Preserve their corner values
            # instead of replacing intentional smooth shading with Blender's
            # recomputed normals. Face winding/normals still follow the geometry.
            mesh.normals_split_custom_set([mesh3do.normals[vertexSources[loop.vertex_index]]
                                           for loop in mesh.loops])
    if active_color_name is not None:
        # Attribute order can change when POINT and CORNER domains coexist.
        # Select by name rather than assuming the original layer stayed at 0.
        mesh.color_attributes.active_color = mesh.color_attributes[active_color_name]
        mesh.color_attributes.render_color_index = mesh.color_attributes.active_color_index
    return mesh


def _create_objects_from_model(model: Model3do, uvAbsolute: bool, geosetNum: int, vertexColors: bool, importRadiusObj:bool, preserveOrder: bool, preserveNormals: bool = False):
    """Create every joint first, then link parents using the resource node IDs."""
    meshes = model.geosets[geosetNum].meshes if model.geosets else []
    grimNormals = preserveNormals or model.binaryData is not None or any(
        mesh.shadow is not None or int(mesh.lightMode) == 6 for mesh in meshes
    )

    # 1. A node's meshIdx is independent of its node index. Nodes without a mesh
    # become EMPTY joints and still participate in the hierarchy and KEY tracks.
    for node in model.meshHierarchy:
        meshIdx = node.meshIdx

        # Get node's mesh
        if meshIdx > -1:
            if meshIdx >= len(meshes):
                raise IndexError(f"Mesh index {meshIdx} out of range ({len(meshes)})!")

            mesh3do = meshes[meshIdx]
            mesh    = _make_mesh(mesh3do, uvAbsolute, vertexColors, model.materials, preserveNormals=grimNormals)
            obj     = bpy.data.objects.new(mesh3do.name, mesh)

            # Set mesh radius object, draw type, custom property for lighting and texture mode
            if importRadiusObj:
                _set_mesh_radius(obj, mesh3do.radius)

            setattr(obj, kModel3doGeometryMode, mesh3do.geometryMode.name)
            obj.display_type              = getDrawType(mesh3do.geometryMode)
            obj.sith_model3do_light_mode   = mesh3do.lightMode.name
            obj.sith_model3do_texture_mode = mesh3do.textureMode.name
            if mesh3do.shadow is not None:
                setattr(obj, kModel3doShadow, bool(mesh3do.shadow))
            obj.display_bounds_type   = 'SPHERE'
            bpy.context.scene.collection.objects.link(obj)
        else:
            obj = bpy.data.objects.new(node.name, None)
            obj.empty_display_size = (0.0)
            bpy.context.scene.collection.objects.link(obj)

        # Make obj name prefixed by idx num.
        # This will make the hierarchy of model 3do ordered by index instead by name in Blender.
        obj.name = makeOrderedName(obj.name, node.idx, len(model.meshHierarchy)) if preserveOrder else obj.name

        # Set hierarchy node flags, type and name
        obj.sith_model3do_hnode_idx   = node.idx
        obj.sith_model3do_hnode_name  = node.name
        obj.sith_model3do_hnode_flags = format(int(node.flags), 'x')
        obj.sith_model3do_hnode_type  = format(int(node.type), 'x')
        if node.binaryData is not None:
            obj[kModel3doBinaryNode] = json.dumps(node.binaryData)

        # Bake mesh pivots, but retain local node position and PYR rotation on
        # the object so parenting reconstructs the resource's relative poses.
        _set_obj_pivot(obj, node.pivot)
        if obj.type == 'MESH' and kModel3doBinaryMesh in obj.data:
            # Blender compresses custom normals. Snapshot the displayed values
            # after pivot baking so unchanged corners can export the original
            # float32 normals, while later normal edits use their new values.
            obj.data.update()
            data = getModel3doBinaryData(obj.data, kModel3doBinaryMesh)
            data['loopNormals'] = [list(normal.vector) for normal in obj.data.corner_normals]
            normalIds = obj.data.attributes.new(k3doBinaryNormal, 'INT', 'CORNER')
            normalIds.data.foreach_set('value', list(range(1, len(obj.data.loops) + 1)))
            obj.data[kModel3doBinaryMesh] = json.dumps(data)
        obj.location = node.position
        _set_obj_rotation(obj, node.rotation)

        node.obj = obj

    bpy.context.view_layer.update()

    # 2. Link parents only after all objects exist; a parent may appear later in
    # the resource. The outer model wrapper is added by import3do afterwards.
    for node in model.meshHierarchy:
        if node.parentIdx != -1:
            node.obj.parent_type = 'OBJECT'
            node.obj.parent      = model.meshHierarchy[node.parentIdx].obj

    bpy.context.view_layer.update()
