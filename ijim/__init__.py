
bl_info = {
    "name": "Indiana Jones and the Infernal Machine",
    "description": "Import-Export game model (.3do) and material (.mat)",
    "author": "smlu",
    "version": (0, 9, 0),
    "blender": (2, 79, 0),
    "location": "File > Import-Export",
    "wiki_url": "https://github.com/smlu/blender-infernal-machine",
    "tracker_url": "https://github.com/smlu/blender-infernal-machine/issues",
    "support": "COMMUNITY",
    "category": "Import-Export"
}


import mathutils
import math
import bpy, types, bmesh
from bpy_extras.io_utils import ImportHelper
from bpy_extras.io_utils import ExportHelper

import sys
import os.path
from typing import List

import ijim.model.model3doExporter as model3doExporter
import ijim.model.model3doImporter as model3doImporter
from ijim.model.utils import getRadius, kGModel3do, kNameOrderPrefix
from .material.material import importMatFile
from .utils.utils import *

class ImportMat(bpy.types.Operator, ImportHelper):
    """Import Indiana Jones and the Infernal Machine MAT file format (.mat)"""
    bl_idname = "import_material.ijim_mat"
    bl_label = "Import MAT"
    filename_ext = ".mat"

    filter_glob = bpy.props.StringProperty(
        default="*.mat",
        options={"HIDDEN"}
    )

    def execute(self, context):
        importMatFile(self.filepath)
        return {'FINISHED'}


class ImportModel3do(bpy.types.Operator, ImportHelper):
    """Import Indiana Jones and the Infernal Machine 3DO file format (.3do)"""
    bl_idname = "import_object.ijim_3do"
    bl_label = "Import 3DO"
    filename_ext = ".3do"

    filter_glob = bpy.props.StringProperty(
        default="*.3do",
        options={"HIDDEN"}
    )

    b_set_3d_view = bpy.props.BoolProperty(
        name='Adjust 3D View',
        description='Adjust 3D View accordingly to the 3do model position, size etc...',
        default=True,
    )

    b_clear_scene = bpy.props.BoolProperty(
        name='Clear Scene',
        description='Remove all scenes and content before importing 3do model to the scene',
        default=True,
    )

    b_preserve_order = bpy.props.BoolProperty(
        name='Preserve Mesh Hierarchy',
        description="If set, the order of imported mesh hierarchy will be preserved by prefixing the name of all mesh objects with '{}XYZ_'.\n('XYZ' represents the order number)".format(kNameOrderPrefix),
        default=True,
    )

    mat_path = bpy.props.StringProperty(
        name='Materials folder',
        description='Path to a directory to search for material files (.mat) of 3do model',
        #subtype='DIR_PATH'
    )

    def execute(self, context):
        obj = model3doImporter.importObject(self.filepath, [self.mat_path], self.b_preserve_order, self.b_clear_scene)

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
            space.grid_lines  = 85
            space.grid_scale  = 0.027
            space.grid_subdivisions = 14

            obj_radius = model3doImporter.getObjRadiusObj(obj)
            mesh_radius = model3doImporter.getMeshRadiusObj(obj)
            if getRadius(obj_radius) >= getRadius(mesh_radius):
                obj = obj_radius
            else:
                obj = mesh_radius

            obj.hide = False
            obj.select = True

            override = {'area': area, 'region': region, 'edit_object': bpy.context.edit_object}
            bpy.ops.view3d.view_center_lock(override)
            bpy.ops.view3d.viewnumpad(override, type='BACK', align_active=True)
            bpy.ops.view3d.view_selected(override)
            #bpy.ops.view3d.view_orbit(override, angle=0.0, type='ORBITUP') # Note: does not work properly in combination with viewnumpad operator

            obj.select = False
            obj.hide = True

        return {'FINISHED'}

class ExportModel3do(bpy.types.Operator, ExportHelper):
    """Export object to Indiana Jones and the Infernal Machine 3DO file format (.3do)"""
    bl_idname = "export_object.ijim_3do"
    bl_label = "Export 3DO"
    filename_ext = ".3do"

    filter_glob = bpy.props.StringProperty(
        default="*.3do",
        options={"HIDDEN"}
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

        while eobj.parent != None:
            eobj = eobj.parent

        self.obj = eobj
        self.filepath = bpy.path.ensure_ext(self.obj.name , self.filename_ext)
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        try:
            model3doExporter.exportObject(self.obj, self.filepath)
        except (AssertionError, ValueError) as e:
            print("\nAn exception was encountered while exporting object '{}' to 3do format!\nError: {}".format(self.obj.name, e))
            self.report({'ERROR'}, "Error: {}".format(e))
            return {'CANCELLED'}

        self.report({'INFO'}, "3DO model '{}' was successfully exported".format(os.path.basename(self.filepath)))
        return {'FINISHED'}



def menu_func_export(self, context):
    self.layout.operator(ExportModel3do.bl_idname, text="Indiana Jones IM model (.3do)")

def menu_func_import(self, context):
    self.layout.operator(ImportModel3do.bl_idname, text="Indiana Jones IM model (.3do)")
    self.layout.operator(ImportMat.bl_idname, text="Indiana Jones IM material (.mat)")

def register():
    bpy.utils.register_class(ExportModel3do)
    bpy.utils.register_class(ImportMat)
    bpy.utils.register_class(ImportModel3do)

    bpy.types.INFO_MT_file_export.append(menu_func_export)
    bpy.types.INFO_MT_file_import.append(menu_func_import)


def unregister():
    bpy.utils.unregister_class(ExportModel3do)
    bpy.utils.unregister_class(ImportModel3do)
    bpy.utils.unregister_class(ImportMat)
    bpy.types.INFO_MT_file_export.remove(menu_func_export)
    bpy.types.INFO_MT_file_import.remove(menu_func_import)


if __name__ == "__main__":
    try:
        unregister()
    except:
        pass
    register()