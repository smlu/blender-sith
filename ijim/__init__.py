bl_info = {
    "name": "Indiana Jones and the Infernal Machine",
    "description": "Import/export game 3D model(s) [.3do], animation(s) [.key] and material(s) [.mat]",
    "author": "Crt Vavros",
    "version": (0, 9, 3),
    "blender": (2, 79, 0),
    "location": "File > Import-Export",
    "wiki_url": "https://github.com/smlu/blender-ijim",
    "tracker_url": "https://github.com/smlu/blender-ijim/issues",
    "support": "COMMUNITY",
    "category": "Import-Export"
}

# Reload imported submodules if script is reloaded
if "bpy" in locals():
    import importlib
    if "key" in locals():
        importlib.reload(key)
    if "keyImporter" in locals():
        importlib.reload(keyImporter)
    if "keyExporter" in locals():
        importlib.reload(keyExporter)
    if "material" in locals():
        importlib.reload(material)
    if "ijim.material" in locals():
        importlib.reload(ijim.material)
    if "model" in locals():
        importlib.reload(model)
    if "model3do" in locals():
        importlib.reload(model3do)
    if "model3doImporter" in locals():
        importlib.reload(model3doImporter)
    if "model3doExporter" in locals():
        importlib.reload(model3doExporter)
    if "text" in locals():
        importlib.reload(text)
    if "utils" in locals():
        importlib.reload(utils)

import os.path, re

import bpy, bmesh
from bpy_extras.io_utils import ImportHelper
from bpy_extras.io_utils import ExportHelper

from ijim.key.key import KeyFlag
import ijim.key.keyImporter as keyImporter
import ijim.key.keyExporter as keyExporter

from ijim.material.material import importMat
from ijim.utils.utils import *
from ijim.types.props import *

from ijim.model.model3do import FaceType, GeometryMode, LightMode, TextureMode
import ijim.model.model3doExporter as model3doExporter
import ijim.model.model3doImporter as model3doImporter
from ijim.model.model3doLoader import Model3doFileVersion
from ijim.model.utils import (
    bmFaceGetGeometryMode,
    bmFaceGetLightMode,
    bmFaceGetTextureMode,
    bmFaceGetType,
    bmFaceSetGeometryMode,
    bmFaceSetLightMode,
    bmFaceSetTextureMode,
    bmFaceSetType,
    bmMeshInit3doLayers,
    kGModel3do,
    kNameOrderPrefix
)


def _make_readable(str):
    return re.sub(r"(\w)([A-Z])", r"\1 \2", str)

def _get_key_flags_enum_list():
    l = []
    for f in reversed(KeyFlag):
        if f != 0x00:
            l.append((f.name, _make_readable(f.name), ""))
    return l

def _get_mesh3do_face_type_list():
    return [
        (FaceType.DoubleSided.name   , 'Double Sided'              , "Polygon face is in game rendered on both sides"                                                                                          ),
        (FaceType.Translucent.name   ,  'Translucent'              , "Polygon is in game rendered with alpha blending enabled making transparent polygon texture translucent"                                  ),
        (FaceType.TexClamp_x.name    , 'Clamp Horizontal'          , "Polygon texture is clamped horizontally instead of repeated (Might not be used in JKDF2 & MOTS)"                                         ),
        (FaceType.TexClamp_y.name    , 'Clamp Vertical'            , "Polygon texture is clamped vertically instead of repeated (Might not be used in JKDF2 & MOTS)"                                           ),
        (FaceType.TexFilterNone.name , 'Disable Bilinear Filtering', "Disables texture bilinear interpolation filtering and instead point filtering is used as a texture magnification or minification filter" ),
        (FaceType.ZWriteDisabled.name, 'Disable ZWrite'            , "Disables writting polygon face to depth buffer"                                                                                          ),
        (FaceType.IjimLedge.name     , '(IJIM)  Ledge'             , "(IJIM only) Polygon face is a ledge that player can grab and hang from"                                                                  ),
        (FaceType.IjimFogEnabled.name, '(IJIM)  Enable Fog'        , "(IJIM only) Enables fog rendering for polygon face. Enabled by default by the engine"                                                    ),
        (FaceType.IjimWhipAim.name   , '(IJIM) Whip Aim'           , "(IJIM only) Polygon face is the start point for player to aim at object with whip"                                                       )
    ]

def _get_model3do_geometry_mode_list():
    l = []
    for f in GeometryMode:
        l.append((f.name, _make_readable(f.name), ""))
    return l

def _get_model3do_light_mode_list():
    l = []
    for f in LightMode:
        l.append((f.name, _make_readable(f.name), ""))
    return l

def _get_model3do_texture_mode_list():
    l = []
    for f in TextureMode:
        l.append((f.name, _make_readable(f.name), ""))
    return l

class ImportMat(bpy.types.Operator, ImportHelper):
    """
    Import Indiana Jones and the Infernal Machine material (.mat)
    """
    bl_idname    = "import_material.ijim_mat"
    bl_label     = "Import MAT"
    filename_ext = ".mat"

    filter_glob = bpy.props.StringProperty(
        default = "*.mat",
        options = {"HIDDEN"}
    )

    def execute(self, context):
        importMat(self.filepath)
        return {'FINISHED'}


class ImportModel3do(bpy.types.Operator, ImportHelper):
    """
    Import Indiana Jones and the Infernal Machine 3DO model (.3do)
    """
    bl_idname    = "import_object.ijim_3do"
    bl_label     = "Import 3DO"
    filename_ext = ".3do"

    filter_glob = bpy.props.StringProperty(
        default = "*.3do",
        options = {"HIDDEN"}
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

    import_radius_objects = bpy.props.BoolProperty(
        name        = 'Import Radius Objects',
        description = 'Import mesh radius as wireframe sphere object',
        default     = False,
    )

    preserve_order = bpy.props.BoolProperty(
        name        = 'Preserve Mesh Hierarchy',
        description = "Preserve 3DO node hierarchy of objects in Blender.\n\nIf set, the order of imported mesh hierarchy will be preserved by prefixing the name of every mesh object with '{}<seq_number>_'.".format(kNameOrderPrefix),
        default     = False,
    )

    mat_dir = bpy.props.StringProperty(
        name        = 'Material(s) Directory',
        description = "Path to the directory to search for material files (.mat) of 3DO model.\n\nBy default addon tries to find required material files in the 'mat' directory of the model path and parent directory",
        #subtype='DIR_PATH'
    )

    cmp_file = bpy.props.StringProperty(
        name        = 'ColorMap Directory',
        description = "Path to the ColorMap file (.cmp) of mat textures of imported 3DO model (JKDF2 & MOTS only).\n\nBy default addon tries to load 'dflt.cmp' from the model path and parent directory",
        #subtype='DIR_PATH'
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, 'set_3d_view')
        layout.prop(self, 'clear_scene')
        layout.prop(self, 'import_radius_objects')
        layout.prop(self, 'preserve_order')
        mat_layout = layout.box().column()
        mat_layout.label(text='Texture(s)')
        mat_dir_layout = mat_layout.box().column()
        mat_dir_layout.label(text='Material(s) Directory')
        mat_dir_layout.prop(self, "mat_dir", text='')
        cmp_file_layout = mat_layout.box().column()
        cmp_file_layout.label(text='ColorMap File (JKDF2 & MOTS)')
        cmp_file_layout.prop(self, "cmp_file", text='')

    def execute(self, context):
        obj = model3doImporter.import3do(self.filepath, [self.mat_dir], self.cmp_file, self.import_radius_objects, self.preserve_order, self.clear_scene)

        if self.set_3d_view:
            area = next(area for area in bpy.context.screen.areas if area.type == 'VIEW_3D')
            region = next(region for region in area.regions if region.type == 'WINDOW')
            space = next(space for space in area.spaces if space.type == 'VIEW_3D')
            space.viewport_shade = "MATERIAL"
            space.lens = 100.0
            space.clip_start = 0.001
            space.lock_object = obj

            space.show_floor  = True
            space.show_axis_x = True
            space.show_axis_y = True
            space.grid_lines  = 10
            space.grid_scale  = 1.0
            space.grid_subdivisions = 10

            active_obj = bpy.context.scene.objects.active
            bpy.context.scene.objects.active = obj
            bpy.ops.object.select_grouped(type='CHILDREN_RECURSIVE')

            override = {'area': area, 'region': region, 'edit_object': bpy.context.edit_object}
            bpy.ops.view3d.view_center_lock(override)
            bpy.ops.view3d.viewnumpad(override, type='BACK', align_active=True)
            bpy.ops.view3d.view_selected(override)

            bpy.ops.object.select_all(action='DESELECT')
            bpy.context.scene.objects.active = active_obj

        return {'FINISHED'}

class ExportModel3do(bpy.types.Operator, ExportHelper):
    """
    Export object to Indiana Jones and the Infernal Machine 3DO file format (.3do)
    """
    bl_idname    = "export_object.ijim_3do"
    bl_label     = "Export 3DO"
    filename_ext = ".3do"

    filter_glob = bpy.props.StringProperty(
        default = "*.3do",
        options = {"HIDDEN"}
    )

    version = bpy.props.EnumProperty(
        name        = "Version",
        description = "3DO file version",
        items       = [
            (Model3doFileVersion.Version2_1.name, '2.1 - JKDF2 & MOTS', 'Star Wars Jedi Knight: Dark Forces II & Star Wars Jedi Knight: Mysteries of the Sith'),
            (Model3doFileVersion.Version2_2.name, '2.2 - IJIM (RGB)'  , 'Indiana Jones and the Infernal Machine - RGB color'),
            (Model3doFileVersion.Version2_3.name, '2.3 - IJIM'        , 'Indiana Jones and the Infernal Machine - RGBA color')
        ],
        default= Model3doFileVersion.Version2_3.name
    )

    export_vert_colors = bpy.props.BoolProperty(
        name        = 'Export vertex colors',
        description = 'Export vertex colors to 3DO file',
        default     = False,
    )

    obj = None

    def invoke(self, context, event):
        eobj = None
        if not kGModel3do in bpy.data.groups or len(bpy.data.groups[kGModel3do].objects) == 0:
            # Get one selected object
            if len(bpy.context.selected_objects) == 0:
                print("Error: could not determine which objects to export. Put into '{}' group or select (1) top object in hierarchy!".format(kGModel3do))
                self.report({'ERROR'}, 'No object selected to export')
                return {'CANCELLED'}

            if len(bpy.context.selected_objects) > 1:
                print("Error: could not determine which objects to export, more then 1 object selected!")
                self.report({'ERROR'}, 'Too many objects selected to export')
                return {'CANCELLED'}

            eobj = bpy.context.selected_objects[0]

        else: # Model3do goup
            objs = bpy.data.groups[kGModel3do].objects
            if len(objs) == 0:
                print("Error: could not determine which objects to export, no object in '{}' group!".format(kGModel3do))
                self.report({'ERROR'}, "No object in group '{}' to export".format(kGModel3do))
                return {'CANCELLED'}
            elif len(objs) > 1:
                for obj in objs:
                    if obj.select:
                        if not eobj is None:
                            print("Error: could not determine which objects to export, too many objects selected in '{}' group!".format(kGModel3do))
                            self.report({'ERROR'}, "Too many objects selected in group '{}' to export".format(kGModel3do))
                            return {'CANCELLED'}
                        eobj = obj
                if eobj is None:
                    print("Error: could not determine which objects to export, no object selected in '{}' group!".format(kGModel3do))
                    self.report({'ERROR'}, "No object selected in group '{}' to export".format(kGModel3do))
                    return {'CANCELLED'}
            else:
                eobj = objs[0]

        if 'EMPTY' != eobj.type != 'MESH':
            print("Error: selected object is of type '{}', can only export an object with type 'MESH' or 'EMPTY'!".format(eobj.type))
            self.report({'ERROR'}, "Cannot export selected object of a type '{}'".format(eobj.type ))
            return {'CANCELLED'}

        while eobj.parent != None and \
            (eobj.parent.type == 'MESH' or eobj.parent.type == 'EMPTY'):
            eobj = eobj.parent

        self.obj = eobj
        self.filepath = bpy.path.ensure_ext(self.obj.name , self.filename_ext)
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        try:
            version = Model3doFileVersion[self.version]
            model3doExporter.export3do(self.obj, self.filepath, version, self.export_vert_colors)
        except (AssertionError, ValueError) as e:
            print("\nAn exception was encountered while exporting object '{}' to 3DO format!\nError: {}".format(self.obj.name, e))
            self.report({'ERROR'}, "Error: {}".format(e))
            return {'CANCELLED'}

        self.report({'INFO'}, "3DO model '{}' was successfully exported".format(os.path.basename(self.filepath)))
        return {'FINISHED'}


# TODO: add option to load model first
class ImportKey(bpy.types.Operator, ImportHelper):
    """
    Import Indiana Jones and the Infernal Machine animation (.key)
    """
    bl_idname    = "import_anim.ijim_key"
    bl_label     = "Import KEY"
    filename_ext = ".key"

    filter_glob = bpy.props.StringProperty(
        default = "*.key",
        options = {"HIDDEN"}
    )

    def execute(self, context):
        try:
            scene = bpy.context.scene
            keyImporter.importKey(self.filepath, scene)
        except Exception as e:
            print("\nAn exception was encountered while importing keyframe '{}'!\nError: {}".format(os.path.basename(self.filepath), e))
            self.report({'ERROR'}, "Error: {}".format(e))
            return {'CANCELLED'}
        return {'FINISHED'}


class ExportKey(bpy.types.Operator, ExportHelper):
    """
    Export animation to Indiana Jones and the Infernal Machine KEY file format (.key)
    """
    bl_idname    = "export_anim.ijim_key"
    bl_label     = "Export KEY"
    filename_ext = ".key"

    filter_glob = bpy.props.StringProperty(
        default = "*.key",
        options = {"HIDDEN"}
    )

    def _get_fps_enum_list():
        return [("60"   , "60 fps", ""),
                ("50"   , "50 fps", ""),
                ("30"   , "30 fps", ""),
                ("25"   , "25 fps", ""),
                ("24"   , "24 fps", ""),
                ("15"   , "15 fps", "")]

    animation_flags = bpy.props.EnumProperty(
        name        = "Flags",
        description = "Animation flags. By default animation loops indefinitely",
        items       = _get_key_flags_enum_list(),
        options     = {'ENUM_FLAG'}
    )

    animation_type = HexProperty(
        'animation_type',
        name        = "Type",
        description = "Animation type. Unknown what role does the type have in the game",
        default     = '0xFFFF',
        maxlen      = 4,
        pad         = True
    )

    fps = bpy.props.EnumProperty(
        name  = "Frame rate",
        items = _get_fps_enum_list()
    )

    obj   = None
    scene = None

    def draw(self, context):
        layout = self.layout
        flags_layout = layout.box().column()
        flags_layout.label(text='Flags')
        flags_layout.prop(self, "animation_flags")
        layout.prop(self, 'animation_type')
        layout.prop(self, 'fps')

    def invoke(self, context, event):
        # Initializes self.scene and self.obj by searching for a top object which represents 3DO model
        try:
            self.scene           = bpy.context.scene.copy()
            self.animation_flags = self.scene.key_animation_flags
            self.animation_type  = self.scene.key_animation_type
            fps                  = self.scene.render.fps
            for e in reversed(ExportKey._get_fps_enum_list()):
                if e[0] == str(fps):
                    self.fps = str(e[0])
                    break
                elif fps < float(e[0]):
                    self.fps = str(e[0])
                    break

            eobj = None
            if not kGModel3do in bpy.data.groups or len(bpy.data.groups[kGModel3do].objects) == 0:
                # Get one selected object
                if len(bpy.context.selected_objects) == 0:
                    print("Error: could not determine which objects to export. Put into '{}' group or select (1) top object in hierarchy!".format(kGModel3do))
                    self.report({'ERROR'}, 'No object selected to export')
                    bpy.data.scenes.remove(self.scene, True)
                    return {'CANCELLED'}

                if len(bpy.context.selected_objects) > 1:
                    print("Error: could not determine which objects to export, more then 1 object selected!")
                    self.report({'ERROR'}, 'Too many objects selected to export')
                    bpy.data.scenes.remove(self.scene, True)
                    return {'CANCELLED'}

                eobj = bpy.context.selected_objects[0]
            else: # Model3do group
                objs = bpy.data.groups[kGModel3do].objects
                if len(objs) == 0:
                    print("Error: could not determine which objects to export animation data from. No object in '{}' group!".format(kGModel3do))
                    self.report({'ERROR'}, "No object in group '{}' to export animation data from".format(kGModel3do))
                    bpy.data.scenes.remove(self.scene, True)
                    return {'CANCELLED'}
                elif len(objs) > 1:
                    for obj in objs:
                        if obj.select:
                            if not eobj is None:
                                print("Error: could not determine from which objects to export animation data. Too many objects selected in '{}' group!".format(kGModel3do))
                                self.report({'ERROR'}, "Too many objects selected in group '{}' to export animation data from".format(kGModel3do))
                                bpy.data.scenes.remove(self.scene, True)
                                return {'CANCELLED'}
                            eobj = obj
                    if eobj is None:
                        print("Error: could not determine which from objects to export animation data from. No object selected in '{}' group!".format(kGModel3do))
                        self.report({'ERROR'}, "No object selected in group '{}' to export animation data from".format(kGModel3do))
                        bpy.data.scenes.remove(self.scene, True)
                        return {'CANCELLED'}
                else:
                    eobj = objs[0]

            if 'EMPTY' != eobj.type != 'MESH':
                print("Error: selected object is of type '{}', can only export the animation data from an object with type 'MESH' or 'EMPTY'!".format(eobj.type))
                self.report({'ERROR'}, "Cannot export animation data from selected object of a type '{}'".format(eobj.type ))
                bpy.data.scenes.remove(self.scene, True)
                return {'CANCELLED'}

            # Get the top obj
            while eobj.parent != None and \
                (eobj.parent.type == 'MESH' or eobj.parent.type == 'EMPTY'):
                eobj = eobj.parent

            self.obj = eobj
            kfname = bpy.path.display_name_from_filepath(self.obj.name )
            self.filepath = bpy.path.ensure_ext(kfname, self.filename_ext)
            return ExportHelper.invoke(self, context, event)
        except:
            if self.scene:
                bpy.data.scenes.remove(self.scene, True)
            raise

    def execute(self, context):
        try:
            self.scene.key_animation_flags = self.animation_flags
            self.scene.key_animation_type  = self.animation_type
            self.scene.render.fps          = float(self.fps)
            keyExporter.exportKey(self.obj, self.scene, self.filepath)

            self.report({'INFO'}, "KEY '{}' was successfully exported".format(os.path.basename(self.filepath)))
            return {'FINISHED'}
        except (AssertionError, ValueError) as e:
            print("\nAn exception was encountered while exporting animation data of object '{}' to KEY file format!\nError: {}".format(self.obj.name, e))
            self.report({'ERROR'}, "Error: {}".format(e))
            return {'CANCELLED'}
        finally:
            bpy.data.scenes.remove(self.scene, True)

    def cancel(self, context):
        if self.scene:
            bpy.data.scenes.remove(self.scene, True)


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
    bl_context     = "object"
    bl_options     = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return (context.object is not None) and \
            ('EMPTY' == context.object.type or context.object.type == 'MESH')

    def draw(self, context):
        obj = context.object
        layout = self.layout

        mesh_properties = layout.box()
        mesh_properties.label(text="Mesh Properties")
        mesh_properties.prop(obj, "model3do_light_mode", text="Lighting")
        mesh_properties.prop(obj, "model3do_texture_mode", text="Texture")

        node_properties = layout.box()
        node_properties.label(text="Hierarchy Node Properties")
        node_properties.prop(obj, "model3do_hnode_num", text="Sequence no.")
        node_properties.prop(obj, "model3do_hnode_name", text="Name")
        node_properties.prop(obj, "model3do_hnode_flags", text="Flags")
        node_properties.prop(obj, "model3do_hnode_type", text="Type")


class Mesh3doFaceLayer(bpy.types.PropertyGroup):
    """
    Intermediant class for temporary storing BMFace properties by Mesh3doFacePanel
    and used it to disply stored properties to the UI.
    """
    face_id = bpy.props.IntProperty(default = -1)

    type = bpy.props.EnumProperty(
        name        = "Type",
        description = "Face type flag",
        items       = _get_mesh3do_face_type_list(),
        options     = {'ENUM_FLAG'}
    )

    geo_mode = bpy.props.EnumProperty(
        name        = "Geometry Mode",
        description = "Geometry mode",
        items       = _get_model3do_geometry_mode_list(),
        default     = GeometryMode.Texture.name,
        options     = {'HIDDEN', 'LIBRARY_EDITABLE'}
    )

    light_mode = bpy.props.EnumProperty(
        name        = "Lighting Mode",
        description = "Lighting mode",
        items       = _get_model3do_light_mode_list(),
        default     = LightMode.Gouraud.name,
        options     = {'HIDDEN', 'LIBRARY_EDITABLE'}
    )

    texture_mode = bpy.props.EnumProperty(
        name        = "Texture Mode",
        description = "Texture mapping mode (Not used by IJIM)",
        items       = _get_model3do_texture_mode_list(),
        default     = TextureMode.PerspectiveCorrected.name,
        options     = {'HIDDEN', 'LIBRARY_EDITABLE'}
    )


class Mesh3doFacePanel(bpy.types.Panel):
    """
    Panel exposes 3DO mesh face properties to the UI.
    i.e.: face type flags, geometry mode, light mode, texture mode & hierarchy node properties.
    """
    bl_idname      = 'DATA_PT_model3do_face_panel'
    bl_label       = "3DO Mesh Face Properties"
    bl_space_type  = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context     = "data"
    bl_options     = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return context.edit_object is not None

    @staticmethod
    def _get_face_id(face: bmesh.types.BMFace):
        return hash(face) %2**31 -1 # gen. 32 bit signed hash id of face

    def draw(self, context):
        wm_fl = context.window_manager.mesh3do_face_layer

        bm = bmesh.from_edit_mesh(context.edit_object.data)
        bmMeshInit3doLayers(bm)
        face = bm.faces.active
        enabled = face is not None
        if enabled:
            fid = self._get_face_id(face)
            if wm_fl.face_id != fid: # init Mesh3doFaceLayer properties aka hack to draw BMFace custom properties
                wm_fl.face_id      = fid
                wm_fl.type         = bmFaceGetType(face, bm).toSet()
                wm_fl.geo_mode     = bmFaceGetGeometryMode(face, bm).name
                wm_fl.light_mode   = bmFaceGetLightMode(face, bm).name
                wm_fl.texture_mode = bmFaceGetTextureMode(face, bm).name

            # Copy 3DO properties of BMFace from Mesh3doFaceLayer properties
            bmFaceSetType(face, bm, FaceType.fromSet(wm_fl.type))
            bmFaceSetGeometryMode(face, bm, GeometryMode[wm_fl.geo_mode])
            bmFaceSetLightMode(face, bm, LightMode[wm_fl.light_mode])
            bmFaceSetTextureMode(face, bm, TextureMode[wm_fl.texture_mode])
        else:
            wm_fl.face = -1

        layout       = self.layout
        box          = layout.box()
        box.enabled  = enabled
        tbox         = box.box()
        tbox.label(text="Type Flags")
        tbox.prop(wm_fl, "type", text="Type")
        box.prop(wm_fl, "geo_mode", text="Geometry")
        box.prop(wm_fl, "light_mode", text="Lighting")
        box.prop(wm_fl, "texture_mode", text="Texture")


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
    self.layout.operator(ExportKey.bl_idname, text="Indiana Jones IM animation (.key)")
    self.layout.operator(ExportModel3do.bl_idname, text="Indiana Jones IM model (.3do)")


def menu_func_import(self, context):
    self.layout.operator(ImportKey.bl_idname, text="Indiana Jones IM animation (.key)")
    self.layout.operator(ImportMat.bl_idname, text="Indiana Jones IM material (.mat)")
    self.layout.operator(ImportModel3do.bl_idname, text="Indiana Jones IM model (.3do)")


def register():
    # Register classes
    for cls in classes:
        bpy.utils.register_class(cls)

    # Register menu functions
    bpy.types.INFO_MT_file_export.append(menu_func_export)
    bpy.types.INFO_MT_file_import.append(menu_func_import)

    # 3DO custom properties for object
    bpy.types.Object.model3do_light_mode = bpy.props.EnumProperty(
        name        = "Lighting Mode",
        description = "Lighting mode",
        items       = _get_model3do_light_mode_list(),
        default     = 'Gouraud',
        options     = {'HIDDEN', 'LIBRARY_EDITABLE'}
    )

    bpy.types.Object.model3do_texture_mode = bpy.props.EnumProperty(
        name        = "Texture Mode",
        description = "Texture mapping mode (Not used by IJIM)",
        items       = _get_model3do_texture_mode_list(),
        default     = 'PerspectiveCorrected',
        options     = {'HIDDEN', 'LIBRARY_EDITABLE'}
    )

    bpy.types.Object.model3do_hnode_num = bpy.props.IntProperty(
        name        = '3DO Hierarchy Node Number',
        description = "The hierarchy sequence number of the node",
        default     = -1,
        options     = {'HIDDEN', 'LIBRARY_EDITABLE'}
    )

    bpy.types.Object.model3do_hnode_name = bpy.props.StringProperty(
        name        = '3DO Hierarchy Node Name',
        description = "The name of hierarchy node",
        maxlen      = 64,
        options     = {'HIDDEN', 'LIBRARY_EDITABLE'}
    )

    bpy.types.Object.model3do_hnode_flags = HexProperty(
        'model3do_hnode_flags',
        name         = '3DO Hierarchy Node Flags',
        description  = "The hierarchy node flags",
        maxlen       = 4,
        pad          = True,
        options      = {'HIDDEN', 'LIBRARY_EDITABLE'}
    )

    bpy.types.Object.model3do_hnode_type = HexProperty(
        'model3do_hnode_type',
        name        = '3DO Hierarchy Node Type',
        description = "The hierarchy node type",
        default     = '0x01',
        maxlen      = 4,
        pad         = True,
        options     = {'HIDDEN', 'LIBRARY_EDITABLE'}
    )

    # 3DO Mesh Face custom properties
    bpy.types.WindowManager.mesh3do_face_layer = bpy.props.PointerProperty(type=Mesh3doFaceLayer)

    # KEY custom properties
    bpy.types.Scene.key_animation_flags = bpy.props.EnumProperty(
        items       = _get_key_flags_enum_list(),
        name        = 'KEY Flags',
        description = "KEY Animation flags. By default animation loops indefinitely",
        options     = {'ENUM_FLAG', 'HIDDEN', 'LIBRARY_EDITABLE'},
    )

    bpy.types.Scene.key_animation_type = HexProperty(
        'key_animation_type',
        name        = 'KEY Type',
        description = "KEY animation type. Unknown what role does the type have in the game.",
        default     = '0xFFFF',
        maxlen      = 4,
        pad         = True,
        options     = {'HIDDEN', 'LIBRARY_EDITABLE'}
    )


def unregister():
    del bpy.types.Scene.key_animation_flags
    del bpy.types.Scene.key_animation_type

    del bpy.types.WindowManager.mesh3do_face_layer

    del bpy.types.Object.model3do_hnode_flags
    del bpy.types.Object.model3do_hnode_type
    del bpy.types.Object.model3do_hnode_name
    del bpy.types.Object.model3do_hnode_num
    del bpy.types.Object.model3do_texture_mode
    del bpy.types.Object.model3do_light_mode

    bpy.types.INFO_MT_file_export.remove(menu_func_export)
    bpy.types.INFO_MT_file_import.remove(menu_func_import)

    for cls in classes:
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    try:
        unregister()
    except:
        pass
    register()
