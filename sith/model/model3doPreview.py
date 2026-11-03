# SPDX-FileCopyrightText: 2026 Crt Vavros
# SPDX-License-Identifier: GPL-3.0-or-later
"""Derived Extra Light shading, independent of serialized vertex lighting."""
import math

import bpy
import bmesh
from bpy.app.handlers import persistent


kPreviewProperty = 'sith_preview_extra_light'
kPreviewDisabled = '_sith_extra_light_preview_disabled'
kPreviewChannels = tuple('_sith_preview_extra_light_' + channel for channel in 'rgb')
kPreviewGroup = '_sith_extra_light_preview_group'
kPreviewNode = '_sith_extra_light_preview_node'
kPreviewMaterial = '_sith_extra_light_preview_material'
kPreviewVersion = 1


def getPreviewEnabled(scene):
    return not bool(scene.get(kPreviewDisabled, False))


def setPreviewEnabled(scene, enabled):
    scene[kPreviewDisabled] = int(not enabled)
    if enabled:
        syncScenePreview(scene)
    scene.update_tag()
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def initBMeshPreview(bm):
    # Adding custom-data layers invalidates face handles. Create all layers
    # before callers begin iterating or retaining faces, never inside a setter.
    for name in kPreviewChannels:
        if bm.faces.layers.float.get(name) is None:
            bm.faces.layers.float.new(name)


def setFacePreview(face, bm, color):
    """Use FACE floats, never color attributes that could become vertex lighting."""
    for name, value in zip(kPreviewChannels, color):
        layer = bm.faces.layers.float.get(name)
        if layer is None:
            return
        # Display limits are deliberately separate from signed/HDR file values.
        face[layer] = max(-1.0, min(1.0, value)) if math.isfinite(value) else 0.0


def isPreviewNode(node):
    return (node.type == 'GROUP' and node.get(kPreviewNode) == kPreviewVersion
            and node.node_tree is not None
            and node.node_tree.get(kPreviewGroup) == kPreviewVersion)


def _mathNode(tree, operation, left, right):
    node = tree.nodes.new('ShaderNodeMath')
    node.operation = operation
    for socket, value in zip(node.inputs, (left, right)):
        if isinstance(value, (int, float)):
            socket.default_value = value
        else:
            tree.links.new(value, socket)
    return node.outputs[0]


def _vectorNode(tree, operation, left, right):
    node = tree.nodes.new('ShaderNodeVectorMath')
    node.operation = operation
    for socket, value in zip(node.inputs, (left, right)):
        if isinstance(value, tuple):
            socket.default_value = value
        else:
            tree.links.new(value, socket)
    return node.outputs[0]


def _previewGroup():
    for tree in bpy.data.node_groups:
        if tree.bl_idname == 'ShaderNodeTree' and tree.get(kPreviewGroup) == kPreviewVersion:
            return tree

    tree = bpy.data.node_groups.new('Sith Extra Light Preview', 'ShaderNodeTree')
    tree[kPreviewGroup] = kPreviewVersion
    for name, kind, default in (('Base Color', 'NodeSocketColor', (0.8, 0.8, 0.8, 1.0)),
                                ('Emission Color', 'NodeSocketColor', (0.0, 0.0, 0.0, 1.0)),
                                ('Emission Strength', 'NodeSocketFloat', 1.0)):
        socket = tree.interface.new_socket(name=name, in_out='INPUT', socket_type=kind)
        socket.default_value = default
    for name in ('Base Color', 'Emission Color'):
        tree.interface.new_socket(name=name, in_out='OUTPUT', socket_type='NodeSocketColor')

    inputs = tree.nodes.new('NodeGroupInput')
    output = tree.nodes.new('NodeGroupOutput')

    # 1. Read the scene currently being drawn, not a driver bound to one scene ID.
    # Missing disable metadata means enabled, including a newly imported scene.
    state = tree.nodes.new('ShaderNodeAttribute')
    state.attribute_type = 'VIEW_LAYER'
    state.attribute_name = kPreviewDisabled
    enabled = _mathNode(tree, 'SUBTRACT', 1.0, state.outputs['Fac'])

    channels = tree.nodes.new('ShaderNodeCombineXYZ')
    for index, name in enumerate(kPreviewChannels):
        attribute = tree.nodes.new('ShaderNodeAttribute')
        attribute.attribute_name = name
        tree.links.new(_mathNode(tree, 'MULTIPLY', attribute.outputs['Fac'], enabled),
                       channels.inputs[index])

    # 2. Negative values dim the base; positive values add texture-modulated
    # emission. This is a Blender preview, not a reconstruction of engine lighting.
    negative = _vectorNode(tree, 'MINIMUM', channels.outputs[0], (0.0, 0.0, 0.0))
    scale = _vectorNode(tree, 'ADD', negative, (1.0, 1.0, 1.0))
    base = _vectorNode(tree, 'MULTIPLY', inputs.outputs['Base Color'], scale)
    positive = _vectorNode(tree, 'MAXIMUM', channels.outputs[0], (0.0, 0.0, 0.0))
    extra = _vectorNode(tree, 'MULTIPLY', inputs.outputs['Base Color'], positive)

    # 3. Retain existing emission, folding its original strength into the color.
    # The original Principled alpha and all other shading inputs stay untouched.
    strength = tree.nodes.new('ShaderNodeCombineXYZ')
    for socket in strength.inputs:
        tree.links.new(inputs.outputs['Emission Strength'], socket)
    original = _vectorNode(tree, 'MULTIPLY', inputs.outputs['Emission Color'], strength.outputs[0])
    emission = _vectorNode(tree, 'ADD', original, extra)
    tree.links.new(base, output.inputs['Base Color'])
    tree.links.new(emission, output.inputs['Emission Color'])

    # Keep the generated graph readable when inspecting a material in Blender.
    for index, node in enumerate(tree.nodes):
        node.location = ((index % 5) * 220, -(index // 5) * 200)
    return tree


def _copyInput(tree, source, target):
    target.default_value = source.default_value
    for link in list(source.links):
        tree.links.new(link.from_socket, target)


def ensureMaterialPreview(material):
    """Extend editable Principled shaders without changing images or alpha links."""
    if (material is None or not material.is_editable or not material.use_nodes
            or material.node_tree is None or not material.node_tree.is_editable):
        return
    tree = material.node_tree
    # Moving an animated socket into a group would invalidate its RNA path.
    if tree.animation_data is not None:
        return

    for shader in list(tree.nodes):
        if shader.type != 'BSDF_PRINCIPLED':
            continue
        base = shader.inputs['Base Color']
        if any(isPreviewNode(link.from_node)
               for name in ('Base Color', 'Emission Color') for link in shader.inputs[name].links):
            continue
        preview = tree.nodes.new('ShaderNodeGroup')
        preview.node_tree = _previewGroup()
        preview[kPreviewNode] = kPreviewVersion
        preview.label = 'Extra Light Preview'
        preview.select = False
        preview.location = (shader.location.x - 240, shader.location.y - 200)
        for name in ('Base Color', 'Emission Color', 'Emission Strength'):
            _copyInput(tree, shader.inputs[name], preview.inputs[name])
        tree.links.new(preview.outputs['Base Color'], base)
        tree.links.new(preview.outputs['Emission Color'], shader.inputs['Emission Color'])
        for link in list(shader.inputs['Emission Strength'].links):
            tree.links.remove(link)
        shader.inputs['Emission Strength'].default_value = 1.0
        material[kPreviewMaterial] = True


def ensureObjectMaterials(obj):
    if obj.type != 'MESH':
        return
    for slot in obj.material_slots:
        ensureMaterialPreview(slot.material)


def syncObjectPreview(obj):
    """Populate old/imported meshes and keep shader setup separate from file data."""
    if obj.type != 'MESH' or not obj.is_editable or not obj.data.is_editable:
        return
    from .utils import k3doFaceExtraLight, bmFaceGetExtraLight

    mesh = obj.data
    editing = mesh.is_editmode
    bm = bmesh.from_edit_mesh(mesh) if editing else bmesh.new()
    try:
        if not editing:
            bm.from_mesh(mesh)
        if bm.faces.layers.string.get(k3doFaceExtraLight) is None:
            return
        if editing:
            initBMeshPreview(bm)
            for face in bm.faces:
                setFacePreview(face, bm, bmFaceGetExtraLight(face, bm))
            bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
        else:
            colors = [bmFaceGetExtraLight(face, bm) for face in bm.faces]
    finally:
        if not editing:
            bm.free()

    if not editing:
        # Do not round-trip existing geometry through BMesh just to refresh a
        # display cache: that could change authored normals or active colors.
        for name in kPreviewChannels:
            attribute = mesh.attributes.get(name)
            if attribute and (attribute.data_type != 'FLOAT' or attribute.domain != 'FACE'):
                raise ValueError(f"Reserved preview attribute '{name}' must be a FACE float")
        for index, name in enumerate(kPreviewChannels):
            attribute = mesh.attributes.get(name)
            if attribute is None:
                attribute = mesh.attributes.new(name=name, type='FLOAT', domain='FACE')
            attribute.data.foreach_set('value', [max(-1.0, min(1.0, color[index]))
                                                if math.isfinite(color[index]) else 0.0
                                                for color in colors])
        mesh.update()

    ensureObjectMaterials(obj)


def syncScenePreview(scene):
    for obj in scene.objects:
        try:
            syncObjectPreview(obj)
        except (ValueError, RuntimeError, TypeError) as error:
            print(f"Warning: Extra Light preview for '{obj.name}' was not updated: {error}")


@persistent
def _loadPreview(_):
    for scene in bpy.data.scenes:
        syncScenePreview(scene)


def register():
    setattr(bpy.types.Scene, kPreviewProperty, bpy.props.BoolProperty(
        name='Extra Light', default=True, get=getPreviewEnabled, set=setPreviewEnabled,
        options=set(),
        description='Preview face Extra Light in Material Preview/Rendered shading without changing vertex colors or exported values'
    ))
    if _loadPreview not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_loadPreview)
    for scene in bpy.data.scenes:
        syncScenePreview(scene)


def unregister():
    if _loadPreview in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_loadPreview)
    # Restore sockets still owned by our group. User-rewired inputs are left alone.
    for material in bpy.data.materials:
        if not material.is_editable or not material.node_tree:
            continue
        tree = material.node_tree
        for preview in list(tree.nodes):
            if not isPreviewNode(preview):
                continue
            # A group reused elsewhere is user-authored graph data now. Do not
            # remove it or write a color default into an unrelated socket type.
            if any(link.to_node.type != 'BSDF_PRINCIPLED'
                   or link.to_socket != link.to_node.inputs.get(name)
                   for name in ('Base Color', 'Emission Color')
                   for link in preview.outputs[name].links):
                continue
            shaders = set()
            for name in ('Base Color', 'Emission Color'):
                for link in list(preview.outputs[name].links):
                    shaders.add(link.to_node)
                    target = link.to_socket
                    tree.links.remove(link)
                    _copyInput(tree, preview.inputs[name], target)
            for shader in shaders:
                strength = shader.inputs.get('Emission Strength')
                if strength and not strength.is_linked and strength.default_value == 1.0:
                    _copyInput(tree, preview.inputs['Emission Strength'], strength)
            tree.nodes.remove(preview)
    for tree in list(bpy.data.node_groups):
        if tree.get(kPreviewGroup) == kPreviewVersion and tree.users == 0:
            bpy.data.node_groups.remove(tree)
    delattr(bpy.types.Scene, kPreviewProperty)
