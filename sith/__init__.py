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

bl_info = {
    "name": "Sith Game Engine Formats (.3do, .mat, .key)",
    "description": "Import/export 3D model(s), animation(s) and texture(s) for the games based on Sith game engine",
    "author": "Crt Vavros",
    "version": (1, 0, 0),
    "pre_release": "rc3",
    "warning": "Pre-release RC3",
    "blender": (2, 79, 0),
    "location": "File > Import-Export",
    "wiki_url": "https://github.com/smlu/blender-sith",
    "tracker_url": "https://github.com/smlu/blender-sith/issues",
    "support": "COMMUNITY",
    "category": "Import-Export"
}

# Reload imported submodules if script is reloaded
if "bpy" in locals():
    import importlib
    if "sith.key" in locals():
        importlib.reload(sith.key)
    if "sith.material" in locals():
        importlib.reload(sith.material)
    if "sith.material" in locals():
        importlib.reload(sith.material)
    if "sith.model" in locals():
        importlib.reload(sith.model)
    if "sith.model.utils" in locals():
        importlib.reload(sith.model.utils)
    if "text" in locals():
        importlib.reload(text)
    if "utils" in locals():
        importlib.reload(utils)

import bpy, bmesh, os.path, re
from bpy_extras.io_utils import ImportHelper
from bpy_extras.io_utils import ExportHelper
from pathlib import Path

from sith.key import (
    exportKey,
    importKey,
    KeyFlag
)

from sith.material import ColorMap, importMat

from sith.model import (
    export3do,
    import3do,
    FaceType,
    GeometryMode,
    LightMode,
    TextureMode
)

from sith.model.model3doLoader import Model3doFileVersion
from sith.model.utils import (
    bmFaceGetExtraLight,
    bmFaceGetGeometryMode,
    bmFaceGetLightMode,
    bmFaceGetTextureMode,
    bmFaceGetType,
    bmFaceSetExtraLight,
    bmFaceSetGeometryMode,
    bmFaceSetLightMode,
    bmFaceSetTextureMode,
    bmFaceSetType,
    bmMeshInit3doLayers,
    kGModel3do,
    kNameOrderPrefix
)

from sith.utils import *
from sith.types import HexProperty, Vector4f


def _make_readable(str):
    return re.sub(r"(\w)([A-Z])", r"\1 \2", str)

def _get_key_flags_enum_list():
    return [
        (KeyFlag.UsePuppetFPS.name    , 'Use Puppet FPS'     , "Don't use FPS and play animation at speed based on puppet movement in the game"),
        (KeyFlag.NoLoop.name          , 'No Loop'            , "Don't loop play animation"),
        (KeyFlag.PauseOnLastFrame.name, 'Pause On Last Frame', 'Pause animation on the last frame'),
        (KeyFlag.RestartActive.name   , 'Restart Active'     , 'Restart animation if active'),
        (KeyFlag.DisableFadeIn.name   , 'Disable Fade-in'    , 'Disable animation fade-in interpolation'),
        (KeyFlag.FadeOutAndNoLoop.name, 'Fade-out & No Loop' , 'Fade-out animation and finish playing'),
    ]

def _get_mesh3do_face_type_list():
    return [
        (FaceType.DoubleSided.name   , 'Double Sided'              , 'Polygon face is rendered in game on both sides'                                                                                          ),
        (FaceType.Translucent.name   , 'Translucent'               , 'Polygon is rendered in game with alpha blending enabled. This makes polygon with transparent texture translucent'                        ),
        (FaceType.TexClamp_x.name    , 'Clamp Horizontal'          , 'Polygon texture is clamped horizontally instead of repeated (Might not be used in JKDF2 & MOTS)'                                         ),
        (FaceType.TexClamp_y.name    , 'Clamp Vertical'            , 'Polygon texture is clamped vertically instead of repeated (Might not be used in JKDF2 & MOTS)'                                           ),
        (FaceType.TexFilterNone.name , 'Disable Bilinear Filtering', 'Disables texture bilinear interpolation filtering and instead point filtering is used as a texture magnification or minification filter' ),
        (FaceType.ZWriteDisabled.name, 'Disable ZWrite'            , 'Disables writing polygon face to depth buffer'                                                                                           ),
        (FaceType.IjimLedge.name     , '(IJIM) Ledge'              , '(IJIM only) Polygon face is a ledge that player can grab and hang from'                                                                  ),
        (FaceType.IjimFogEnabled.name, '(IJIM) Enable Fog'         , '(IJIM only) Enables fog rendering for polygon face. Enabled by default by the engine'                                                    ),
        (FaceType.IjimWhipAim.name   , '(IJIM) Whip Aim'           , '(IJIM only) Polygon face is whip aiming spot from which player can search in the area for object(s) to mount whip on'                    )
    ]

def _get_model3do_geometry_mode_list():
    l = []
    for f in GeometryMode:
        l.append((f.name, _make_readable(f.name), ''))
    return l

def _get_model3do_light_mode_list():
    l = []
    for f in LightMode:
        if f == LightMode.GfUnknown6:
            l.append((f.name, 'GF Unknown 6', 'Unknown lighting mode used in Grim Fandango'))
        else:
            l.append((f.name, _make_readable(f.name), ''))
    return l

def _get_model3do_texture_mode_list():
    l = []
    for f in TextureMode:
        l.append((f.name, _make_readable(f.name), ''))
    return l

def _get_export_obj(context, report, data_type: str):
    """ Returns obj by searching for top object which represents 3DO model """
    eobj = None
    if kGModel3do not in bpy.data.groups or len(bpy.data.groups[kGModel3do].objects) == 0:
        # Get one selected object
        if context.active_object is None:
            print(f"Error: Could not determine which object to export {data_type} data from. Select 1 object or put object into '{kGModel3do}' group!")
            report({'ERROR'}, f"No object selected! Select 1 object or put object into '{kGModel3do}' group!")
            return None
        eobj = context.active_object

    else: # Model3do group
        objs = bpy.data.groups[kGModel3do].objects
        if len(objs) == 0:
            print(f"Error: No object in '{kGModel3do}' group. Add object to the group or delete the group!")
            report({'ERROR'}, f"Group '{kGModel3do}' is empty! Add object to the group or delete the group!")
            return None
        elif len(objs) > 1:
            for obj in objs:
                if obj.select:
                    if not eobj is None:
                        print(f"Error: Could not determine from which object to export {data_type} data from. Too many objects selected in '{kGModel3do}' group!")
                        report({'ERROR'}, f"Too many objects selected in group '{kGModel3do}'. Select only 1 object in that group!")
                        return None
                    eobj = obj
            if eobj is None:
                print(f"Error: Could not determine which object to export {data_type} data from. No object selected in '{kGModel3do}' group!")
                report({'ERROR'}, f"No object selected in group '{kGModel3do}'!")
                return None
        else:
            eobj = objs[0]

    if 'EMPTY' != eobj.type != 'MESH':
        print(f"Error: Selected object is of type '{eobj.type}', can only export {data_type} data from an object of type 'MESH' or 'EMPTY'!")
        report({'ERROR'}, f"Cannot export {data_type} data from selected object of a type '{eobj.type}'!")
        return None

    # Get the top obj
    while eobj.parent != None and \
        (eobj.parent.type == 'MESH' or eobj.parent.type == 'EMPTY'):
        eobj = eobj.parent
    return eobj


class ImportMat(bpy.types.Operator, ImportHelper):
    """Import Sith game engine texture (.mat)"""
    bl_idname    = 'import_material.sith_mat'
    bl_label     = 'Import MAT'
    filename_ext = '.mat'

    filter_glob = bpy.props.StringProperty(
        default = '*.mat',
        options = {'HIDDEN'}
    )

    cmp_file = bpy.props.StringProperty(
        name        = 'ColorMap Directory',
        description = "Path to the ColorMap file (.cmp) used by mat textures of the imported 3DO model (JKDF2 & MOTS only).\n\nBy default file is searched in specified path, in the directory of the imported 3DO model and it's parent directory.\nIf no file is specified 'dflt.cmp' file is loaded",
        #subtype='DIR_PATH'
    )

    def draw(self, context):
        layout = self.layout
        cmp_file_layout = layout.box().column()
        cmp_file_layout.label(text='ColorMap File (JKDF2 & MOTS)')
        cmp_file_layout.prop(self, 'cmp_file', text='')

    def execute(self, context):
        cmp = getCmpFileOrDefault(self.cmp_file, self.filepath)
        importMat(self.filepath, cmp)
        return {'FINISHED'}


class ImportModel3do(bpy.types.Operator, ImportHelper):
    """Import Sith game engine 3DO model (.3do)"""
    bl_idname    = 'import_scene.sith_3do'
    bl_label     = 'Import 3DO'
    filename_ext = '.3do'

    filter_glob = bpy.props.StringProperty(
        default = '*.3do',
        options = {'HIDDEN'}
    )

    set_3d_view = bpy.props.BoolProperty(
        name        = 'Adjust 3D View',
        description = 'Adjust 3D View accordingly to the 3DO model position, size etc..',
        default     = True,
    )

    clear_scene = bpy.props.BoolProperty(
        name        = 'Clear Scene',
        description = 'Remove all scenes and content before importing 3DO model to the scene',
        default     = True,
    )

    uv_absolute_3do_2_1 = bpy.props.BoolProperty(
        name        = '3DO 2.1 - Absolute UV',
        description = 'Remove texture size from associated UV coordinates If imported 3DO file is version 2.1 (Required for JKDF2 & MOTS)',
        default     = True,
    )

    vertex_colors = bpy.props.BoolProperty(
        name        = 'Import Vertex Colors',
        description = 'Import mesh vertex colors from 3DO',
        default     = False,
    )

    import_radius_objects = bpy.props.BoolProperty(
        name        = 'Import Radius Objects',
        description = 'Import mesh radius as wireframe sphere object',
        default     = False,
    )

    preserve_order = bpy.props.BoolProperty(
        name        = 'Preserve Mesh Hierarchy',
        description = f"Preserve 3DO node hierarchy of objects in Blender.\n\nIf set, the order of imported mesh hierarchy will be preserved by prefixing the name of every mesh object with '{kNameOrderPrefix}<seq_number>_'.",
        default     = False,
    )

    mat_dir = bpy.props.StringProperty(
        name        = 'Material(s) Directory',
        description = "Path to the directory to search for texture files (.mat) of the imported 3DO model.\n\nBy default required texture files are searched in 'mat' directory at the location of imported 3DO model and it's parent directory",
        #subtype='DIR_PATH'
    )

    cmp_file = bpy.props.StringProperty(
        name        = 'ColorMap File',
        description = "Path to the ColorMap file (.cmp) used by mat textures of the imported 3DO model (JKDF2 & MOTS only).\n\nBy default file is searched in specified path, in the directory of the imported 3DO model and it's parent directory.\nIf no file is specified 'dflt.cmp' file is loaded",
        #subtype='DIR_PATH'
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, 'set_3d_view')
        layout.prop(self, 'clear_scene')
        layout.prop(self, 'uv_absolute_3do_2_1')
        layout.prop(self, 'vertex_colors')
        layout.prop(self, 'import_radius_objects')
        layout.prop(self, 'preserve_order')
        mat_layout = layout.box().column()
        mat_layout.label(text='Texture(s)')
        mat_dir_layout = mat_layout.box().column()
        mat_dir_layout.label(text='Directory')
        mat_dir_layout.prop(self, 'mat_dir', text='')
        cmp_file_layout = mat_layout.box().column()
        cmp_file_layout.label(text='ColorMap File (JKDF2 & MOTS)')
        cmp_file_layout.prop(self, 'cmp_file', text='')

    def execute(self, context):
        obj = import3do(self.filepath, [self.mat_dir], self.cmp_file, self.uv_absolute_3do_2_1, self.vertex_colors, self.import_radius_objects, self.preserve_order, self.clear_scene)

        if self.set_3d_view:
            area   = next(area   for area   in context.screen.areas if area.type == 'VIEW_3D')
            region = next(region for region in area.regions if region.type == 'WINDOW')
            space  = next(space  for space  in area.spaces if space.type == 'VIEW_3D')
            space.viewport_shade    = 'MATERIAL'
            space.lens              = 100.0
            space.clip_start        = 0.001
            space.lock_object       = obj
            space.show_floor        = True
            space.show_axis_x       = True
            space.show_axis_y       = True
            space.grid_lines        = 10
            space.grid_scale        = 1.0
            space.grid_subdivisions = 10

            active_obj = context.scene.objects.active
            context.scene.objects.active = obj
            bpy.ops.object.select_grouped(type='CHILDREN_RECURSIVE')

            override = {'area': area, 'region': region, 'edit_object': context.edit_object}
            bpy.ops.view3d.view_center_lock(override)
            bpy.ops.view3d.viewnumpad(override, type='BACK', align_active=True)
            bpy.ops.view3d.view_selected(override)

            bpy.ops.object.select_all(action='DESELECT')
            context.scene.objects.active = active_obj
            space.lock_object            = None

        return {'FINISHED'}

class ExportModel3do(bpy.types.Operator, ExportHelper):
    """Export object(s) to Sith game engine 3DO file format (.3do)"""
    bl_idname    = 'export_scene.sith_3do'
    bl_label     = 'Export 3DO'
    filename_ext = '.3do'

    filter_glob = bpy.props.StringProperty(
        default = '*.3do',
        options = {'HIDDEN'}
    )

    version = bpy.props.EnumProperty(
        name        = 'Version',
        description = '3DO file version',
        items       = [
            (Model3doFileVersion.Version2_1.name, '2.1 - JKDF2 & MOTS', 'Star Wars Jedi Knight: Dark Forces II & Star Wars Jedi Knight: Mysteries of the Sith'),
            (Model3doFileVersion.Version2_2.name, '2.2 - IJIM (RGB)'  , 'Indiana Jones and the Infernal Machine - RGB color' ),
            (Model3doFileVersion.Version2_3.name, '2.3 - IJIM'        , 'Indiana Jones and the Infernal Machine - RGBA color')
        ],
        default= Model3doFileVersion.Version2_3.name
    )

    absolute_uv = bpy.props.BoolProperty(
        name        = 'Absolute UV',
        description = 'Exported UV coordinates will be fixed to associated texture image size (Required for JKDF2 & MOTS)',
        default     = True,
    )

    export_vert_colors = bpy.props.BoolProperty(
        name        = 'Export Vertex Colors',
        description = 'Export vertex colors to 3DO file',
        default     = False,
    )

    obj = None

    def draw(self, context):
        layout = self.layout
        layout.prop(self, 'version')
        if self.version == Model3doFileVersion.Version2_1.name:
            layout.prop(self, 'absolute_uv')
        layout.prop(self, 'export_vert_colors')

    def invoke(self, context, event):
        self.obj = _get_export_obj(context, self.report, 'mesh')
        if self.obj is None:
            return {'CANCELLED'}
        self.filepath = bpy.path.ensure_ext(self.obj.name , self.filename_ext)
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        try:
            version = Model3doFileVersion[self.version]
            if version != Model3doFileVersion.Version2_1:
                self.absolute_uv = False
            export3do(self.obj, self.filepath, version, self.absolute_uv, self.export_vert_colors)
        except (AssertionError, ValueError) as e:
            print(f"\nAn exception was encountered while exporting object '{self.obj.name}' to 3DO format!\nError: {e}")
            self.report({'ERROR'}, f'Error: {e}')
            return {'CANCELLED'}

        self.report({'INFO'}, f"3DO model '{os.path.basename(self.filepath)}' was successfully exported")
        return {'FINISHED'}


# TODO: add option to load model first
class ImportKey(bpy.types.Operator, ImportHelper):
    """Import Sith game engine animation (.key)"""
    bl_idname    = 'import_anim.sith_key'
    bl_label     = 'Import KEY'
    filename_ext = '.key'

    filter_glob = bpy.props.StringProperty(
        default = '*.key',
        options = {'HIDDEN'}
    )

    validate_active_object = bpy.props.BoolProperty(
        name        = 'Validate object',
        description = 'Validate active object has all required animation nodes before importing KEY animation.',
        default     = True,
    )

    clear_scene = bpy.props.BoolProperty(
        name        = 'Clear scene',
        description = 'Clear any existing animation data from the scene before importing KEY animation.',
        default     = True,
    )

    def execute(self, context):
        try:
            scene = context.scene
            importKey(self.filepath, scene, self.clear_scene, self.validate_active_object)
        except Exception as e:
            print(f"\nError: An exception was encountered while importing keyframe '{os.path.basename(self.filepath)}'!\nError: {e}")
            self.report({'ERROR'}, f'Error: {e}')
            return {'CANCELLED'}
        return {'FINISHED'}

class ExportKey(bpy.types.Operator, ExportHelper):
    """Export animation to Sith game engine KEY file format (.key)"""
    bl_idname    = 'export_anim.sith_key'
    bl_label     = 'Export KEY'
    filename_ext = '.key'

    filter_glob = bpy.props.StringProperty(
        default = '*.key',
        options = {'HIDDEN'}
    )

    def _get_fps_enum_list():
        return [('60'   , '60 fps', ''),
                ('50'   , '50 fps', ''),
                ('30'   , '30 fps', ''),
                ('25'   , '25 fps', ''),
                ('24'   , '24 fps', ''),
                ('20'   , '20 fps', ''),
                ('15'   , '15 fps', '')]

    flags = bpy.props.EnumProperty(
        name        = 'Flags',
        description = 'Animation flags. Probably not used in the game and overridden by puppet sub-mode flags',
        items       = _get_key_flags_enum_list(),
        options     = {'ENUM_FLAG'}
    )

    node_types = HexProperty(
        'node_types',
        name        = 'High Priority Node(s)',
        description = '3DO hierarchy node types which have higher animation priority set by the associated puppet file.\n\nBy default all 3DO joint nodes have low animation priority assigned in the associated puppet file (.pup). When the node type is defined here then this node will have high priority value assigned. Set this field to `FFFF` in order to assign all node types to high priority',
        default     = '0xFFFF',
        maxlen      = 4,
        pad         = True
    )

    fps = bpy.props.EnumProperty(
        name  = 'Frame rate',
        items = _get_fps_enum_list()
    )

    obj   = None

    def draw(self, context):
        layout = self.layout
        layout.prop_menu_enum(self, 'flags')
        types_layout = layout.box().column()
        types_layout.label(text='High Priority Node(s)')
        types_layout.prop(self, 'node_types', text='')
        layout.prop(self, 'fps')

    def invoke(self, context, event):
        self.flags       = context.scene.sith_key_flags
        self.node_types  = context.scene.sith_key_types
        fps              = context.scene.render.fps
        for e in reversed(ExportKey._get_fps_enum_list()):
            if e[0] == str(fps):
                self.fps = str(e[0])
                break
            elif fps < float(e[0]):
                self.fps = str(e[0])
                break

        self.obj = _get_export_obj(context, self.report, 'animation')
        if self.obj is None:
            return {'CANCELLED'}
        kfname        = bpy.path.display_name_from_filepath(self.obj.name )
        self.filepath = bpy.path.ensure_ext(kfname, self.filename_ext)
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        context.scene.sith_key_flags = self.flags
        context.scene.sith_key_types = self.node_types
        context.scene.render.fps     = float(self.fps)
        scene = context.scene.copy()
        try:
            exportKey(self.obj, scene, self.filepath)
            self.report({'INFO'}, f"KEY '{os.path.basename(self.filepath)}' was successfully exported")
            return {'FINISHED'}
        except (AssertionError, ValueError) as e:
            print(f"\nAn exception was encountered while exporting animation data of object '{self.obj.name}' to KEY file format!\nError: {e}")
            self.report({'ERROR'}, f'Error: {e}')
            return {'CANCELLED'}
        finally:
            if scene:
                bpy.data.scenes.remove(scene, True)


class Model3doPanel(bpy.types.Panel):
    """
    Panel exposes 3DO mesh properties to the UI.
    i.e.: light mode, texture mode & hierarchy node properties.
    """
    bl_idname      = 'OBJECT_PT_model_3do_panel'
    bl_label       = '3DO Properties'
    bl_description = '3DO model object properties'
    bl_space_type  = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context     = 'object'
    bl_options     = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return (context.object is not None) and \
            ('EMPTY' == context.object.type or context.object.type == 'MESH')

    def draw(self, context):
        obj    = context.object
        layout = self.layout

        mesh_properties = layout.box()
        mesh_properties.label(text='Mesh Properties')
        mesh_properties.prop(obj, 'sith_model3do_light_mode'  , text='Lighting')
        mesh_properties.prop(obj, 'sith_model3do_texture_mode', text='Texture')

        node_properties = layout.box()
        node_properties.label(text='Hierarchy Node Properties')
        node_properties.prop(obj, 'sith_model3do_hnode_idx'  , text='Sequence no.')
        node_properties.prop(obj, 'sith_model3do_hnode_name' , text='Name')
        node_properties.prop(obj, 'sith_model3do_hnode_flags', text='Flags')
        node_properties.prop(obj, 'sith_model3do_hnode_type' , text='Type')


class Mesh3doFaceLayer(bpy.types.PropertyGroup):
    """
    Intermediate class for temporary storing BMFace properties by Mesh3doFacePanel
    and used it to display stored properties to the UI.
    """
    face_id = bpy.props.IntProperty(default = -1)

    type = bpy.props.EnumProperty(
        name        = 'Type',
        description = 'Face type flag',
        items       = _get_mesh3do_face_type_list(),
        options     = {'ENUM_FLAG'}
    )

    geo_mode = bpy.props.EnumProperty(
        name        = 'Geometry Mode',
        description = 'Geometry mode',
        items       = _get_model3do_geometry_mode_list(),
        default     = GeometryMode.Texture.name,
        options     = {'HIDDEN', 'LIBRARY_EDITABLE'}
    )

    light_mode = bpy.props.EnumProperty(
        name        = 'Lighting Mode',
        description = 'Lighting mode',
        items       = _get_model3do_light_mode_list(),
        default     = LightMode.Gouraud.name,
        options     = {'HIDDEN', 'LIBRARY_EDITABLE'}
    )

    texture_mode = bpy.props.EnumProperty(
        name        = 'Texture Mode',
        description = 'Texture mapping mode (Not used by IJIM)',
        items       = _get_model3do_texture_mode_list(),
        default     = TextureMode.PerspectiveCorrected.name,
        options     = {'HIDDEN', 'LIBRARY_EDITABLE'}
    )

    extra_light = bpy.props.FloatVectorProperty(
        name        = 'Extra Light',
        description = 'Face extra light color',
        size        = 4,
        subtype     ='COLOR',
        default     = [0.0, 0.0, 0.0, 1.0],
        min         = 0.0,
        max         = 1.0
    )

class Mesh3doFacePanel(bpy.types.Panel):
    """
    Panel exposes 3DO mesh face properties to the UI.
    i.e.: face type flags, geometry mode, light mode, texture mode & hierarchy node properties.
    """
    bl_idname      = 'DATA_PT_model3do_face_panel'
    bl_label       = '3DO Mesh Face Properties'
    bl_space_type  = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context     = 'data'
    bl_options     = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return context.edit_object is not None

    @staticmethod
    def _get_face_id(face: bmesh.types.BMFace):
        return hash(face) %2**31 -1 # gen. 32 bit signed hash id of face

    def draw(self, context):
        wm_fl = context.window_manager.sith_mesh3do_face_layer

        bm = bmesh.from_edit_mesh(context.edit_object.data)
        bmMeshInit3doLayers(bm)

        face    = bm.faces.active
        enabled = face is not None
        if enabled:
            fid = self._get_face_id(face)
            if wm_fl.face_id != fid: # init Mesh3doFaceLayer properties aka hack to draw BMFace custom properties
                wm_fl.face_id      = fid
                wm_fl.type         = bmFaceGetType(face, bm).toSet()
                wm_fl.geo_mode     = bmFaceGetGeometryMode(face, bm).name
                wm_fl.light_mode   = bmFaceGetLightMode(face, bm).name
                wm_fl.texture_mode = bmFaceGetTextureMode(face, bm).name
                wm_fl.extra_light  = bmFaceGetExtraLight(face, bm)

            # Copy 3DO properties of BMFace from Mesh3doFaceLayer properties
            bmFaceSetType(face, bm, FaceType.fromSet(wm_fl.type))
            bmFaceSetGeometryMode(face, bm, GeometryMode[wm_fl.geo_mode])
            bmFaceSetLightMode(face, bm, LightMode[wm_fl.light_mode])
            bmFaceSetTextureMode(face, bm, TextureMode[wm_fl.texture_mode])
            bmFaceSetExtraLight(face, bm, Vector4f(*wm_fl.extra_light))
        else:
            wm_fl.face = -1

        layout       = self.layout
        box          = layout.box()
        box.enabled  = enabled
        tbox         = box.box()
        tbox.label(text= 'Type Flags')
        tbox.props_enum(wm_fl, 'type')
        box.prop(wm_fl, 'geo_mode'    , text='Geometry')
        box.prop(wm_fl, 'light_mode'  , text='Lighting')
        box.prop(wm_fl, 'texture_mode', text='Texture')
        box.prop(wm_fl, 'extra_light' , text='Extra Light')


classes = (
    Mesh3doFaceLayer,
    Mesh3doFacePanel,
    Model3doPanel,
    ImportMat,
    ImportModel3do,
    ExportModel3do,
    ImportKey,
    ExportKey
)

def menu_func_export(self, context):
    self.layout.operator(ExportKey.bl_idname, text='Sith Game Engine Animation (.key)')
    self.layout.operator(ExportModel3do.bl_idname, text='Sith Game Engine 3D Model (.3do)')


def menu_func_import(self, context):
    self.layout.operator(ImportKey.bl_idname, text='Sith Game Engine Animation (.key)')
    self.layout.operator(ImportMat.bl_idname, text='Sith Game Engine Texture (.mat)')
    self.layout.operator(ImportModel3do.bl_idname, text='Sith Game Engine 3D Model (.3do)')

def register():
    # Register classes
    for cls in classes:
        bpy.utils.register_class(cls)

    # Register menu functions
    bpy.types.INFO_MT_file_export.append(menu_func_export)
    bpy.types.INFO_MT_file_import.append(menu_func_import)

    # 3DO custom properties for object
    bpy.types.Object.sith_model3do_light_mode = bpy.props.EnumProperty(
        name        = 'Lighting Mode',
        description = 'Lighting mode',
        items       = _get_model3do_light_mode_list(),
        default     = 'Gouraud',
        options     = {'HIDDEN', 'LIBRARY_EDITABLE'}
    )

    bpy.types.Object.sith_model3do_texture_mode = bpy.props.EnumProperty(
        name        = 'Texture Mode',
        description = 'Texture mapping mode (Not used by IJIM)',
        items       = _get_model3do_texture_mode_list(),
        default     = 'PerspectiveCorrected',
        options     = {'HIDDEN', 'LIBRARY_EDITABLE'}
    )

    bpy.types.Object.sith_model3do_hnode_idx = bpy.props.IntProperty(
        name        = '3DO Hierarchy Node Number',
        description = 'The node position number in the hierarchy list. If set to -1 the position will be auto assigned when exporting to 3DO file',
        default     = -1,
        min         = -1,
        options     = {'HIDDEN', 'LIBRARY_EDITABLE'}
    )

    bpy.types.Object.sith_model3do_hnode_name = bpy.props.StringProperty(
        name        = '3DO Hierarchy Node Name',
        description = 'The name of hierarchy node',
        maxlen      = 64,
        options     = {'HIDDEN', 'LIBRARY_EDITABLE'}
    )

    bpy.types.Object.sith_model3do_hnode_flags = HexProperty(
        'sith_model3do_hnode_flags',
        name         = '3DO Hierarchy Node Flags',
        description  = 'The hierarchy node flags',
        maxlen       = 4,
        pad          = True,
        options      = {'HIDDEN', 'LIBRARY_EDITABLE'}
    )

    bpy.types.Object.sith_model3do_hnode_type = HexProperty(
        'sith_model3do_hnode_type',
        name        = '3DO Hierarchy Node Type',
        description = 'The hierarchy node type',
        default     = '0x01',
        maxlen      = 4,
        pad         = True,
        options     = {'HIDDEN', 'LIBRARY_EDITABLE'}
    )

    # 3DO Mesh Face custom properties
    bpy.types.WindowManager.sith_mesh3do_face_layer = bpy.props.PointerProperty(type=Mesh3doFaceLayer)

    # KEY custom properties
    bpy.types.Scene.sith_key_flags = bpy.props.EnumProperty(
        items       = _get_key_flags_enum_list(),
        name        = 'KEY Flags',
        description = 'Sith KEY animation flags. This are puppet animation flags which are probably not used by the game.',
        options     = {'ENUM_FLAG', 'HIDDEN', 'LIBRARY_EDITABLE'},
    )

    bpy.types.Scene.sith_key_types = HexProperty(
        'sith_key_types',
        name        = 'High Priority Node(s)',
        description = '3DO hierarchy node types which have higher animation priority set by the associated puppet file.\n\nBy default all 3DO joint nodes have low animation priority assigned in the associated puppet file (.pup). When the node type is defined here then this node will have high priority value assigned. Set this field to `FFFF` in order to assign all node types to high priority',
        default     = '0xFFFF',
        maxlen      = 4,
        pad         = True,
        options     = {'HIDDEN', 'LIBRARY_EDITABLE'}
    )

def unregister():
    del bpy.types.Scene.sith_key_flags
    del bpy.types.Scene.sith_key_types

    del bpy.types.WindowManager.sith_mesh3do_face_layer

    del bpy.types.Object.sith_model3do_hnode_flags
    del bpy.types.Object.sith_model3do_hnode_type
    del bpy.types.Object.sith_model3do_hnode_name
    del bpy.types.Object.sith_model3do_hnode_idx
    del bpy.types.Object.sith_model3do_texture_mode
    del bpy.types.Object.sith_model3do_light_mode

    bpy.types.INFO_MT_file_export.remove(menu_func_export)
    bpy.types.INFO_MT_file_import.remove(menu_func_import)

    for cls in classes:
        bpy.utils.unregister_class(cls)


if __name__ == '__main__':
    try:
        unregister()
    except:
        pass
    register()
