
bl_info = {
    "name": "Indiana Jones and the Infernal Machine",
    "description": "Import-Export game model (.3do) and material (.mat)",
    "author": "Crt Vavros",
    "version": (0, 9, 2),
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
    if "model" in locals():
        importlib.reload(model)
    if "model3doImporter" in locals():
        importlib.reload(model3doImporter)
    if "model3doExporter" in locals():
        importlib.reload(model3doExporter)
    if "text" in locals():
        importlib.reload(text)
    if "utils" in locals():
        importlib.reload(utils)
    if "HexProperty" in locals():
        importlib.reload(types.props)

import bpy
from bpy_extras.io_utils import ImportHelper
from bpy_extras.io_utils import ExportHelper

import os.path
import re

import ijim.model.model3doExporter as model3doExporter
import ijim.model.model3doImporter as model3doImporter
from ijim.model.utils import kGModel3do, kNameOrderPrefix

from ijim.key.key import KeyFlag, KeyType
import ijim.key.keyImporter as keyImporter
import ijim.key.keyExporter as keyExporter

from .material.material import importMatFile
from .utils.utils import *
from .types.props import *


def _make_readable(str):
    return re.sub(r"(\w)([A-Z])", r"\1 \2", str)

def _get_key_flags_enum_list():
    l = []
    for f in reversed(KeyFlag):
        l.append((f.name, _make_readable(f.name), "", int(f)))
    return l

class ImportMat(bpy.types.Operator, ImportHelper):
    """Import Indiana Jones and the Infernal Machine material (.mat)"""
    bl_idname    = "import_material.ijim_mat"
    bl_label     = "Import MAT"
    filename_ext = ".mat"

    filter_glob = bpy.props.StringProperty(
        default = "*.mat",
        options = {"HIDDEN"}
    )

    def execute(self, context):
        importMatFile(self.filepath)
        return {'FINISHED'}


class ImportModel3do(bpy.types.Operator, ImportHelper):
    """Import Indiana Jones and the Infernal Machine 3DO model (.3do)"""
    bl_idname    = "import_object.ijim_3do"
    bl_label     = "Import 3DO"
    filename_ext = ".3do"

    filter_glob = bpy.props.StringProperty(
        default = "*.3do",
        options = {"HIDDEN"}
    )

    b_set_3d_view = bpy.props.BoolProperty(
        name        = 'Adjust 3D View',
        description = 'Adjust 3D View accordingly to the 3DO model position, size etc...',
        default     = True,
    )

    b_clear_scene = bpy.props.BoolProperty(
        name        = 'Clear Scene',
        description = 'Remove all scenes and content before importing 3DO model to the scene',
        default     = True,
    )

    b_import_radius_objects = bpy.props.BoolProperty(
        name        = 'Import radius objects',
        description = 'Import mesh radius as 3D object',
        default     = False,
    )

    b_preserve_order = bpy.props.BoolProperty(
        name        = 'Preserve Mesh Hierarchy',
        description = "If set, the order of imported mesh hierarchy will be preserved by prefixing the name of every mesh object with '{}XYZ_'.\n('XYZ' represents the order number)\nNote: hierarchy order effects animations which use this 3DO model.".format(kNameOrderPrefix),
        default     = True,
    )

    mat_path = bpy.props.StringProperty(
        name        = 'Materials folder',
        description = 'Path to the directory to search for material files (.mat) of 3DO model',
        #subtype='DIR_PATH'
    )

    def execute(self, context):
        obj = model3doImporter.importObject(self.filepath, [self.mat_path], self.b_import_radius_objects, self.b_preserve_order, self.b_clear_scene)

        if self.b_set_3d_view:
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
    """Export object to Indiana Jones and the Infernal Machine 3DO file format (.3do)"""
    bl_idname    = "export_object.ijim_3do"
    bl_label     = "Export 3DO"
    filename_ext = ".3do"

    filter_glob = bpy.props.StringProperty(
        default = "*.3do",
        options = {"HIDDEN"}
    )

    b_export_vert_colors = bpy.props.BoolProperty(
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
            model3doExporter.exportObject(self.obj, self.filepath, self.b_export_vert_colors)
        except (AssertionError, ValueError) as e:
            print("\nAn exception was encountered while exporting object '{}' to 3DO format!\nError: {}".format(self.obj.name, e))
            self.report({'ERROR'}, "Error: {}".format(e))
            return {'CANCELLED'}

        self.report({'INFO'}, "3DO model '{}' was successfully exported".format(os.path.basename(self.filepath)))
        return {'FINISHED'}


# TODO: add option to load model first
class ImportKey(bpy.types.Operator, ImportHelper):
    """Import Indiana Jones and the Infernal Machine animation (.key)"""
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
            keyImporter.importKeyToScene(self.filepath, scene)
        except Exception as e:
            print("\nAn exception was encountered while importing keyframe '{}'!\nError: {}".format(os.path.basename(self.filepath), e))
            self.report({'ERROR'}, "Error: {}".format(e))
            return {'CANCELLED'}
        return {'FINISHED'}


class ExportKey(bpy.types.Operator, ExportHelper):
    """Export animation to Indiana Jones and the Infernal Machine KEY file format (.key)"""
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
        name    = "Animation flags",
        items   = _get_key_flags_enum_list(),
        options = {'ENUM_FLAG'}
    )

    animation_type = HexProperty(
        'animation_type',
        name        = "Animation type",
        description = "It is not known what role does animation type have in the game.",
        maxlen      = 4,
        pad         = True
    )

    fps = bpy.props.EnumProperty(
        name  = "Frame rate",
        items = _get_fps_enum_list()
    )

    obj = None
    scene = None

    def invoke(self, context, event):
        # Initializes self.scene and self.obj by searching for a top object which represents 3DO model
        try:
            self.scene = bpy.context.scene.copy()
            self.animation_flags = self.scene.animation_flags
            self.animation_type  = self.scene.animation_type
            if self.animation_type == '':
                self.animation_type = 'FFFF'

            fps = self.scene.render.fps
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
            keyExporter.exportObjectAnim(self.obj, self.scene, self.filepath)

            self.report({'INFO'}, "Key '{}' was successfully exported".format(os.path.basename(self.filepath)))
            return {'FINISHED'}
        except (AssertionError, ValueError) as e:
            print("\nAn exception was encountered while exporting animation data of object '{}' to Key file format!\nError: {}".format(self.obj.name, e))
            self.report({'ERROR'}, "Error: {}".format(e))
            return {'CANCELLED'}
        finally:
            bpy.data.scenes.remove(self.scene, True)

    def cancel(self, context):
        if self.scene:
            bpy.data.scenes.remove(self.scene, True)



def menu_func_export(self, context):
    self.layout.operator(ExportKey.bl_idname, text="Indiana Jones IM animation (.key)")
    self.layout.operator(ExportModel3do.bl_idname, text="Indiana Jones IM model (.3do)")


def menu_func_import(self, context):
    self.layout.operator(ImportKey.bl_idname, text="Indiana Jones IM animation (.key)")
    self.layout.operator(ImportMat.bl_idname, text="Indiana Jones IM material (.mat)")
    self.layout.operator(ImportModel3do.bl_idname, text="Indiana Jones IM model (.3do)")


def register():
    bpy.types.Scene.animation_flags = bpy.props.EnumProperty(
        items = _get_key_flags_enum_list(),
        name  = 'Key Animation Flags',
        options = {'ENUM_FLAG'},
        description = 'Indiana Jones IM Keyframe Flags'
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

    bpy.utils.register_class(ImportMat)
    bpy.utils.register_class(ImportModel3do)
    bpy.utils.register_class(ExportModel3do)
    bpy.utils.register_class(ImportKey)
    bpy.utils.register_class(ExportKey)

    bpy.types.INFO_MT_file_export.append(menu_func_export)
    bpy.types.INFO_MT_file_import.append(menu_func_import)


def unregister():
    bpy.utils.unregister_class(ExportKey)
    bpy.utils.unregister_class(ImportKey)
    bpy.utils.unregister_class(ExportModel3do)
    bpy.utils.unregister_class(ImportModel3do)
    bpy.utils.unregister_class(ImportMat)

    bpy.types.INFO_MT_file_export.remove(menu_func_export)
    bpy.types.INFO_MT_file_import.remove(menu_func_import)

    del bpy.types.Scene.animation_flags
    del bpy.types.Scene.animation_type
    del bpy.types.Scene.key_animation_flags
    del bpy.types.Scene.key_animation_type


if __name__ == "__main__":
    try:
        unregister()
    except:
        pass
    register()
