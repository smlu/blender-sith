# Sith Blender Addon - Blender registration and user interface
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

# Reload imported submodules if script is reloaded
if "bpy" in locals():
    import importlib
    from . import key as _key_pkg
    importlib.reload(_key_pkg)
    from . import material as _mat_pkg
    importlib.reload(_mat_pkg)
    from . import model as _model_pkg
    importlib.reload(_model_pkg)
    from .model import utils as _model_utils_pkg
    importlib.reload(_model_utils_pkg)
    from . import text as _text_pkg
    importlib.reload(_text_pkg)
    from . import utils as _utils_pkg
    importlib.reload(_utils_pkg)

import bpy, bmesh, mathutils, math, os.path, re
from bpy_extras.io_utils import ImportHelper
from bpy_extras.io_utils import ExportHelper
from pathlib import Path

from .key import (
    exportKey,
    importKey,
    KeyFlag
)
from .key.keyValidation import kKeyTargets
from .key.keyUtils import getSceneFrameRate, prepareSceneFrameRate, setSceneFrameRate, kKeyImportReport

from .material import importMat

from .model import (
    export3do,
    import3do,
    FaceType,
    GeometryMode,
    LightMode,
    TextureMode
)

from .model.model3doLoader import Model3doFileFormat, Model3doFileVersion
from .model import model3doPreview
from .model.utils import (
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
    kModel3doGeometryMode,
    kModel3doImportReport,
    kModel3doShadow,
    kNameOrderPrefix
)

from .utils import *
from .types import HexProperty, Vector4f
from .types.vector import kFloat32Max


def _make_readable(str):
    return re.sub(r"(\w)([A-Z])", r"\1 \2", str)

def _get_key_flags_enum_list():
    return [
        (KeyFlag.MovementControlled.name    , 'Movement controlled'   , "Animation is controlled by the movement of animated game object, and played at speed of the puppet movement. Keyframe's FPS is not used" ),
        (KeyFlag.NoLoop.name                , 'No Loop'               , "Don't loop play animation"                                                                                                               ),
        (KeyFlag.PauseOnLastFrame.name      , 'Pause On Last Frame'   , 'Pause animation on the last frame'                                                                                                       ),
        (KeyFlag.RestartActive.name         , 'Restart Active'        , 'Restart animation if active'                                                                                                             ),
        (KeyFlag.DisableFadeIn.name         , 'Disable Fade-in'       , 'Disable animation fade-in interpolation'                                                                                                 ),
        (KeyFlag.FadeOutAndNoLoop.name      , 'Fade-out & No Loop'    , 'Fade-out animation and finish playing'                                                                                                   ),
        (KeyFlag.SetPositionToLastFrame.name, '(IJIM) Last Frame Pose', '(IJIM only) Animation sets the game object\'s pose to the last frame pose when the animation finishes playing.'                          ),
    ]

def _get_mesh3do_face_type_list():
    return [
        (FaceType.DoubleSided.name   , 'Double Sided'                     , 'Polygon face is rendered in game on both sides'                                                                       ),
        (FaceType.Translucent.name   , 'Translucent'                      , 'Polygon is rendered in game with alpha blending enabled. This makes polygon with transparent texture translucent'     ),
        (FaceType.TexClamp_x.name    , 'Clamp Horizontal (IJIM)'          , '(IJIM only) Polygon texture is clamped horizontally instead of repeated'                                              ),
        (FaceType.TexClamp_y.name    , 'Clamp Vertical (IJIM)'            , '(IJIM only) Polygon texture is clamped vertically instead of repeated'                                                ),
        (FaceType.TexFilterNone.name , 'Disable Bilinear Filtering (IJIM)', '(IJIM only) Uses nearest texture filtering. In MOTS and Grim Fandango, bit 0x10 instead forces lighting mode 1 (Not Lit)' ),
        (FaceType.ZWriteDisabled.name, 'Disable ZWrite (IJIM)'            , '(IJIM only) Disables writing the polygon face to the depth buffer'                                                     ),
        (FaceType.IjimLedge.name     , 'Ledge (IJIM)'                     , '(IJIM only) Polygon face is a ledge that player can grab and hang from'                                                ),
        (FaceType.IjimFogEnabled.name, 'Enable Fog (IJIM)'                , '(IJIM only) Enables fog rendering for polygon face. Enabled by default by the engine'                                  ),
        (FaceType.IjimWhipAim.name   , 'Whip Aim (IJIM)'                  , '(IJIM only) Polygon face is whip aiming spot from which player can search in the area for object(s) to mount whip on'  )
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
            # Keep the saved identifier; only the display name describes the recovered behavior.
            l.append((f.name, 'Mesh Intensity (Grim Fandango)',
                      "Use cached mesh lighting in Grim Fandango's software renderer; "
                      "can inherit an ancestor mesh's intensity. Stored lighting mode 6, "
                      'not a Blender lighting setting'))
        else:
            l.append((f.name, _make_readable(f.name), ''))
    return l

def _get_model3do_texture_mode_list():
    l = []
    for f in TextureMode:
        if f == TextureMode.PerspectiveUnknown:
            l.append((f.name, 'Unknown (2)',
                      'Stored texture mode 2; its exact engine behavior is not established. '
                      'Preserved on import/export, not a Blender texture setting'))
        else:
            l.append((f.name, _make_readable(f.name), ''))
    return l

def _get_export_obj(context, report, data_type: str):
    """Resolve only the active selected object's model in this view layer."""
    obj = context.active_object
    # Linked and local objects can have identical names in the same view layer.
    layerObjects = set(context.view_layer.objects)
    if (obj is None or obj not in context.selected_objects
            or obj not in layerObjects):
        report({'ERROR'}, 'No object selected! Make the model or one of its joints the active selected object.')
        return None
    if obj.type not in ('MESH', 'EMPTY'):
        report({'ERROR'}, f"Cannot export {data_type} data from selected object of type '{obj.type}'; select a Mesh or Empty.")
        return None

    # Selection identifies one model, not a batch. Include its unselected joints,
    # but never cross an unsupported parent or enter another scene/view layer.
    while obj.parent is not None:
        parent = obj.parent
        if parent.type not in ('MESH', 'EMPTY'):
            report({'ERROR'}, f"Bake or reparent '{obj.name}' out of unsupported parent '{parent.name}' ({parent.type}) before export.")
            return None
        if parent not in layerObjects:
            report({'ERROR'}, f"Model parent '{parent.name}' is outside the active view layer; include its hierarchy before export.")
            return None
        obj = parent
    return obj


class ImportMat(bpy.types.Operator, ImportHelper):
    """Import Sith game engine texture (.mat)"""
    bl_idname    = 'import_material.sith_mat'
    bl_label     = 'Import MAT'
    filename_ext = '.mat'

    filter_glob: bpy.props.StringProperty(
        default = '*.mat',
        options = {'HIDDEN'}
    )

    cmp_file: bpy.props.StringProperty(
        name        = 'ColorMap File',
        description = "ColorMap (.cmp) for indexed MAT textures in JKDF2, MOTS, DroidWorks and Grim Fandango. Searches the file's directory and resource folders; an empty field tries dflt.cmp and dfltcmp.cmp. Grim costume-specific palettes must be selected explicitly",
    )

    def draw(self, context):
        layout = self.layout
        cmp_file_layout = layout.box().column()
        cmp_file_layout.label(text='ColorMap File')
        cmp_file_layout.prop(self, 'cmp_file', text='')

    def execute(self, context):
        # Validate filepath
        if not self.filepath or not os.path.isfile(self.filepath):
            self.report({'ERROR'}, 'No file selected or file does not exist!')
            return {'CANCELLED'}
        if not self.filepath.lower().endswith('.mat'):
            self.report({'ERROR'}, 'Selected file is not a .mat file!')
            return {'CANCELLED'}

        try:
            cmp = getCmpFileOrDefault(self.cmp_file, self.filepath)
            importMat(self.filepath, cmp)
        except (ImportError, OSError, ValueError, IndexError) as error:
            self.report({'ERROR'}, f'Cannot import MAT: {error}')
            return {'CANCELLED'}
        return {'FINISHED'}


class ImportModel3do(bpy.types.Operator, ImportHelper):
    """Import Sith game engine 3DO model (.3do)"""
    bl_idname    = 'import_scene.sith_3do'
    bl_label     = 'Import 3DO'
    filename_ext = '.3do'

    filter_glob: bpy.props.StringProperty(
        default = '*.3do',
        options = {'HIDDEN'}
    )

    set_3d_view: bpy.props.BoolProperty(
        name        = 'Adjust 3D View',
        description = 'Adjust 3D View accordingly to the 3DO model position, size etc..',
        default     = True,
    )

    clear_scene: bpy.props.BoolProperty(
        name        = 'Clear Scene',
        description = 'Remove all scenes and content before importing 3DO model to the scene',
        default     = True,
    )

    uv_absolute_3do_2_1: bpy.props.BoolProperty(
        name        = 'v2.1 Absolute UV',
        description = 'Convert absolute pixel-space UVs to normalized Blender UVs for Jedi Knight: Dark Forces II, Mysteries of the Sith, Grim Fandango and DroidWorks',
        default     = True,
    )

    vertex_colors: bpy.props.BoolProperty(
        name        = 'Import Vertex Colors',
        description = 'Import mesh vertex colors from 3DO',
        default     = False,
    )

    vertex_normals: bpy.props.BoolProperty(
        name        = 'Import Vertex Normals (Text)',
        description = 'Preserve authored normals on legacy text models too. Binary and explicitly identified Grim models always preserve their authored normals',
        default     = False,
    )

    import_radius_objects: bpy.props.BoolProperty(
        name        = 'Import Radius Objects',
        description = 'Import mesh radius as wireframe sphere object',
        default     = False,
    )

    preserve_order: bpy.props.BoolProperty(
        name        = 'Preserve Mesh Hierarchy',
        description = f"Keep the original node order visible in Blender by prefixing joint object names with '{kNameOrderPrefix}<seq_number>_'.\n\nParent links and stored node sequence numbers are preserved with this option on or off. Without prefixes, Blender's name ordering may change unsynced mesh-list order on export.",
        default     = False,
    )

    mat_dir: bpy.props.StringProperty(
        name        = 'MAT Directory',
        description = "Path to the directory to search for MAT texture files (.mat) of the imported 3DO model.\n\nBy default, required texture files are searched in the 'mat' directory at the location of the imported 3DO model and its parent directory",
    )

    cmp_file: bpy.props.StringProperty(
        name        = 'ColorMap File',
        description = "ColorMap (.cmp) for indexed MAT textures in JKDF2, MOTS, DroidWorks and Grim Fandango. Searches beside the model and in resource folders; an empty field tries dflt.cmp and dfltcmp.cmp. Grim costume-specific palettes must be selected explicitly",
    )

    allow_errors: bpy.props.BoolProperty(
        name        = 'Try Recover Broken File',
        description = 'Attempt to import usable parts of a broken file, omitting unusable faces and substituting missing UVs. Missing geometry and transforms cannot be reconstructed. View Import Report opens the recovery details',
        default     = False,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, 'set_3d_view')
        layout.prop(self, 'clear_scene')
        layout.prop(self, 'uv_absolute_3do_2_1')
        layout.prop(self, 'vertex_colors')
        layout.prop(self, 'vertex_normals')
        layout.prop(self, 'import_radius_objects')
        layout.prop(self, 'preserve_order')
        layout.prop(self, 'allow_errors')

        mat_layout = layout.box().column()
        mat_layout.label(text='Texture(s)')
        mat_dir_layout = mat_layout.box().column()
        mat_dir_layout.label(text='MAT Directory')
        mat_dir_layout.prop(self, 'mat_dir', text='')
        cmp_file_layout = mat_layout.box().column()
        cmp_file_layout.label(text='ColorMap File')
        cmp_file_layout.prop(self, 'cmp_file', text='')

    def execute(self, context):
        # Validate filepath
        if not self.filepath or not os.path.isfile(self.filepath):
            self.report({'ERROR'}, 'No file selected or file does not exist!')
            return {'CANCELLED'}
        if not self.filepath.lower().endswith('.3do'):
            self.report({'ERROR'}, 'Selected file is not a .3do file!')
            return {'CANCELLED'}

        warnings = []
        try:
            obj = import3do(self.filepath, [self.mat_dir], self.cmp_file, self.uv_absolute_3do_2_1, self.vertex_colors, self.import_radius_objects, self.preserve_order, self.clear_scene, allowErrors=self.allow_errors, warnings=warnings, importVertexNormals=getattr(self, 'vertex_normals', False))
        except (AssertionError, TypeError, ValueError, OSError, IndexError, RuntimeError) as error:
            self.report({'ERROR'}, f'Cannot import 3DO: {error}')
            return {'CANCELLED'}
        if obj is None:
            self.report({'WARNING'}, 'The 3DO contains no importable model')
            return {'CANCELLED'}
        if warnings:
            reportName = obj[kModel3doImportReport]
            warningCount = len(warnings)
            self.report({'WARNING'}, f'Recovery warnings: {warningCount}. View Import Report in 3DO Properties for details')
            if not bpy.app.background and context.window is not None:
                def draw_recovery_notice(menu, context):
                    menu.layout.label(text=f'Recovery warnings: {warningCount}')
                    menu.layout.operator(View3doImportReport.bl_idname, icon='TEXT').report_name = reportName
                context.window_manager.popup_menu(draw_recovery_notice, title='3DO Recovery', icon='ERROR')

        # Background Blender may expose a screen/window while viewport operators
        # still cannot run. Framing is optional and must not fail a valid import.
        if (self.set_3d_view and not bpy.app.background
                and context.window is not None and context.screen is not None):
            try:
                _frame_imported_model(context, obj)
            except RuntimeError as error:
                self.report({'WARNING'}, f'Model imported, but viewport framing failed: {error}')

        return {'FINISHED'}


def _frame_imported_model(context, obj):
    """Frame a model without keeping temporary selection or object-view locks."""
    # Framing must not switch an existing edit/sculpt session to Object Mode.
    if context.mode != 'OBJECT':
        return
    area = next((area for area in context.screen.areas if area.type == 'VIEW_3D'), None)
    if area is None:
        return
    region = next((region for region in area.regions if region.type == 'WINDOW'), None)
    space = next((space for space in area.spaces if space.type == 'VIEW_3D'), None)
    if region is None or space is None or space.region_3d is None:
        return

    active_obj = context.view_layer.objects.active
    selected_objects = tuple(context.selected_objects)
    view_lock = space.lock_object
    perspective = space.region_3d.view_perspective

    # All operators need the viewport override, not the file browser's context.
    with context.temp_override(area=area, region=region):
        try:
            space.shading.type                = 'SOLID'
            space.shading.light               = 'FLAT'
            space.shading.color_type          = 'TEXTURE'
            space.shading.show_object_outline = False
            space.lens                        = 100.0
            space.clip_start                  = 0.001
            space.lock_object                 = obj
            space.overlay.show_floor          = True
            space.overlay.show_axis_x         = True
            space.overlay.show_axis_y         = True
            space.overlay.grid_lines          = 10
            space.overlay.grid_scale          = 1.0
            space.overlay.grid_subdivisions   = 10

            context.view_layer.objects.active = obj
            obj.select_set(True)
            bpy.ops.object.select_grouped(type='CHILDREN_RECURSIVE')
            context.view_layer.update()

            # Measure world-space vertices so child rotations and scale affect
            # framing. Flat models are easier to inspect from above.
            bb_min = mathutils.Vector([float('inf')] * 3)
            bb_max = mathutils.Vector([float('-inf')] * 3)
            for child_obj in [obj] + list(obj.children_recursive):
                if child_obj.type == 'MESH' and child_obj.data:
                    for vertex in child_obj.data.vertices:
                        wco = child_obj.matrix_world @ vertex.co
                        for i in range(3):
                            bb_min[i] = min(bb_min[i], wco[i])
                            bb_max[i] = max(bb_max[i], wco[i])

            view_type = 'BACK'
            if bb_min.x < float('inf'):
                bb_size = bb_max - bb_min
                footprint = max(bb_size.x, bb_size.y)
                if footprint > 0 and bb_size.z < footprint * 0.3:
                    view_type = 'TOP'

            bpy.ops.view3d.view_center_lock()
            bpy.ops.view3d.view_axis(type=view_type, align_active=True)
            space.region_3d.view_perspective = perspective
            if bb_min.x < float('inf'):
                space.region_3d.view_distance = max((bb_max - bb_min).length * 2.5, 1.0)
                space.region_3d.view_location = (bb_min + bb_max) * 0.5
            else:
                bpy.ops.view3d.view_selected()
        finally:
            # Direct selection APIs also work if a viewport operator just failed.
            for selected in context.view_layer.objects:
                if selected.select_get():
                    selected.select_set(False)
            for selected in selected_objects:
                selected.select_set(True)
            context.view_layer.objects.active = active_obj
            space.lock_object = view_lock
            space.region_3d.view_perspective = perspective


class ExportModel3do(bpy.types.Operator, ExportHelper):
    """Export object(s) to Sith game engine 3DO file format (.3do)"""
    bl_idname    = 'export_scene.sith_3do'
    bl_label     = 'Export 3DO'
    filename_ext = '.3do'

    filter_glob: bpy.props.StringProperty(
        default = '*.3do',
        options = {'HIDDEN'}
    )

    version: bpy.props.EnumProperty(
        name        = 'Format',
        description = '',  # Use the selected format's description without a generic preface.
        items       = [
            (Model3doFileVersion.Version2_1.name, '2.1 - JKDF2 & MOTS', 'Star Wars Jedi Knight: Dark Forces II & Star Wars Jedi Knight: Mysteries of the Sith'),
            (Model3doFileVersion.Version2_2.name, '2.2 - IJIM (RGB)'  , 'Indiana Jones and the Infernal Machine - RGB color' ),
            (Model3doFileVersion.Version2_3.name, '2.3 - IJIM'        , 'Indiana Jones and the Infernal Machine - RGBA color'),
            (Model3doFileFormat.GrimFandango.name, 'Grim Fandango', 'Grim Fandango binary format. For text export, select 2.1')
        ],
        default= Model3doFileVersion.Version2_3.name
    )

    absolute_uv: bpy.props.BoolProperty(
        name        = 'v2.1 Absolute UV',
        description = 'Export absolute pixel-space UVs for Jedi Knight: Dark Forces II, Mysteries of the Sith, Grim Fandango and DroidWorks',
        default     = True,
    )

    export_vert_colors: bpy.props.BoolProperty(
        name        = 'Export Vertex Colors',
        description = 'Export vertex colors to 3DO file',
        default     = False,
    )

    sync_mesh_list: bpy.props.BoolProperty(
        name        = 'Sync Mesh List with Node Hierarchy',
        description = 'Number meshes in hierarchy-node order and update every node mesh reference.\n\nEmpty joints use no mesh slot, so mesh IDs do not always equal node IDs. When disabled, keep Blender traversal mesh order; hierarchy node IDs and KEY animation bindings remain independent.',
        default     = True,
    )

    obj = None

    def draw(self, context):
        layout = self.layout
        layout.prop(self, 'version')
        if self.version in (Model3doFileVersion.Version2_1.name, Model3doFileFormat.GrimFandango.name):
            layout.prop(self, 'absolute_uv')
        layout.prop(self, 'export_vert_colors')
        layout.prop(self, 'sync_mesh_list')

    def invoke(self, context, event):
        self.obj = _get_export_obj(context, self.report, 'mesh')
        if self.obj is None:
            return {'CANCELLED'}
        self.filepath = bpy.path.ensure_ext(self.obj.name , self.filename_ext)
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        # Validate filepath
        if not self.filepath:
            self.report({'ERROR'}, 'No file path specified!')
            return {'CANCELLED'}
        if not self.filepath.lower().endswith('.3do'):
            self.filepath = bpy.path.ensure_ext(self.filepath, self.filename_ext)

        # Scripted EXEC_DEFAULT calls do not pass through the file browser's invoke.
        if self.obj is None:
            self.obj = _get_export_obj(context, self.report, 'mesh')
        if self.obj is None:
            return {'CANCELLED'}

        try:
            version = (Model3doFileFormat.GrimFandango if self.version == Model3doFileFormat.GrimFandango.name
                       else Model3doFileVersion[self.version])
            if version not in (Model3doFileVersion.Version2_1, Model3doFileFormat.GrimFandango):
                self.absolute_uv = False
            warnings = []
            export3do(self.obj, self.filepath, version, self.absolute_uv, self.export_vert_colors, self.sync_mesh_list, warnings=warnings)
        except (AssertionError, ValueError, OSError, RuntimeError) as e:
            print(f"\nAn exception was encountered while exporting object '{self.obj.name}' to 3DO format!\nError: {e}")
            self.report({'ERROR'}, f'Error: {e}')
            return {'CANCELLED'}

        self.report({'INFO'}, f"3DO model '{os.path.basename(self.filepath)}' was successfully exported")
        for warning in warnings:
            self.report({'WARNING'}, warning)
        return {'FINISHED'}


# TODO: add option to load model first
class ImportKey(bpy.types.Operator, ImportHelper):
    """Import Sith game engine animation (.key)"""
    bl_idname    = 'import_anim.sith_key'
    bl_label     = 'Import KEY'
    filename_ext = '.key'

    filter_glob: bpy.props.StringProperty(
        default = '*.key',
        options = {'HIDDEN'}
    )

    validate_active_object: bpy.props.BoolProperty(
        name        = 'Validate',
        description = 'Validate that the active object has all the required animating nodes before importing the KEY animation.',
        default     = True,
    )

    clear_scene: bpy.props.BoolProperty(
        name        = 'Clear scene',
        description = 'Clear any existing animation data from the scene before importing KEY animation.',
        default     = True,
    )

    named_markers: bpy.props.BoolProperty(
        name        = 'Import markers by name',
        description = 'Import frame markers by name rather than by number.',
        default     = False,
    )

    require_frame_zero: bpy.props.BoolProperty(
        name        = 'Require Frame Zero',
        description = 'Require each animation track to start at frame zero. Disable to import late-start tracks, extrapolating their active deltas back to frame zero. Data-integrity checks remain enabled',
        default     = True,
    )

    allow_errors: bpy.props.BoolProperty(
        name        = 'Try Recover Broken File',
        description = 'Try importing complete valid tracks from a damaged KEY, omitting corrupt tracks with a report. Does not repair unsafe headers or truncated binary records, or disable Require Frame Zero',
        default     = False,
    )

    def draw(self, context):
        for name in ('validate_active_object', 'clear_scene', 'named_markers', 'require_frame_zero', 'allow_errors'):
            self.layout.prop(self, name)

    def execute(self, context):
        # Validate filepath
        if not self.filepath or not os.path.isfile(self.filepath):
            self.report({'ERROR'}, 'No file selected or file does not exist!')
            return {'CANCELLED'}
        if not self.filepath.lower().endswith('.key'):
            self.report({'ERROR'}, 'Selected file is not a .key file!')
            return {'CANCELLED'}

        try:
            scene = context.scene
            warnings = []
            obj = importKey(self.filepath, scene, self.clear_scene, self.validate_active_object, self.named_markers,
                            allowErrors=self.allow_errors, requireFrameZero=self.require_frame_zero, warnings=warnings)
        except Exception as e:
            print(f"\nError: An exception was encountered while importing keyframe '{os.path.basename(self.filepath)}'!\nError: {e}")
            self.report({'ERROR'}, f'Error: {e}')
            return {'CANCELLED'}
        if warnings:
            warningCount = len(warnings)
            self.report({'WARNING'}, f'Recovery warnings: {warningCount}. View KEY Import Report in 3DO Properties for details')
            if not bpy.app.background and context.window is not None and kKeyImportReport in obj:
                reportName = obj[kKeyImportReport]
                def draw_recovery_notice(menu, context):
                    menu.layout.label(text=f'Recovery warnings: {warningCount}')
                    menu.layout.operator(View3doImportReport.bl_idname, icon='TEXT').report_name = reportName
                context.window_manager.popup_menu(draw_recovery_notice, title='KEY Recovery', icon='ERROR')
        return {'FINISHED'}

class ExportKey(bpy.types.Operator, ExportHelper):
    """Export animation to Sith game engine KEY file format (.key)"""
    bl_idname    = 'export_anim.sith_key'
    bl_label     = 'Export KEY'
    filename_ext = '.key'

    filter_glob: bpy.props.StringProperty(
        default = '*.key',
        options = {'HIDDEN'}
    )

    target: bpy.props.EnumProperty(name='Target', items=kKeyTargets, default='IJIM')

    flags: bpy.props.EnumProperty(
        name        = 'Flags',
        description = 'Animation flags. Probably not used in the game and overridden by puppet sub-mode flags',
        items       = _get_key_flags_enum_list(),
        options     = {'ENUM_FLAG'}
    )

    node_types: HexProperty(
        'node_types',
        name        = 'High Priority Node(s)',
        description = '3DO hierarchy node types which have higher animation priority set by the associated puppet file.\n\nBy default all 3DO joint nodes have low animation priority assigned in the associated puppet file (.pup). When the node type is defined here then this node will have high priority value assigned. Set this field to `FFFF` in order to assign all node types to high priority',
        default     = '0xFFFF',
        pad         = True
    )

    fps: bpy.props.FloatProperty(
        name        = 'Frame Rate',
        description = 'Playback frames per second, including fractional rates',
        default     = 30.0,
        min         = 0.0,
        precision   = 6
    )

    obj   = None

    def draw(self, context):
        layout = self.layout
        layout.prop(self, 'target')
        layout.prop_menu_enum(self, 'flags')
        types_layout = layout.box().column()
        types_layout.label(text='High Priority Node(s)')
        types_layout.prop(self, 'node_types', text='')
        layout.prop(self, 'fps')

    def invoke(self, context, event):
        self.flags       = context.scene.sith_key_flags
        self.node_types  = context.scene.sith_key_types
        self.fps         = getSceneFrameRate(context.scene)

        self.obj = _get_export_obj(context, self.report, 'animation')
        if self.obj is None:
            return {'CANCELLED'}
        kfname        = bpy.path.display_name_from_filepath(self.obj.name )
        self.filepath = bpy.path.ensure_ext(kfname, self.filename_ext)
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        # Validate filepath
        if not self.filepath:
            self.report({'ERROR'}, 'No file path specified!')
            return {'CANCELLED'}
        if not self.filepath.lower().endswith('.key'):
            self.filepath = bpy.path.ensure_ext(self.filepath, self.filename_ext)

        if self.obj is None:
            self.obj = _get_export_obj(context, self.report, 'animation')
        if self.obj is None:
            return {'CANCELLED'}

        try:
            # Build with dialog overrides, without changing scene playback or
            # flags until validation and writing have both succeeded.
            scene = context.scene
            sceneFps = getSceneFrameRate(scene)
            fps = self.fps if self.properties.is_property_set('fps') else sceneFps
            if math.isclose(fps, sceneFps, rel_tol=1e-7):
                fps = sceneFps  # Preserve rates rounded by Blender's float property.
            prepareSceneFrameRate(scene, fps)
            flags = self.flags if self.properties.is_property_set('flags') else scene.sith_key_flags
            # The custom getter returns a default without storing it. Only a
            # value written by the setter is an explicit dialog/script override.
            nodeTypes = self.node_types if 'node_types' in self.properties else scene.sith_key_types
            exportKey(self.obj, scene, self.filepath, target=self.target, fps=fps, flags=flags, nodeTypes=nodeTypes)
        except (AssertionError, ValueError, OSError, RuntimeError) as e:
            print(f"\nAn exception was encountered while exporting animation data of object '{self.obj.name}' to KEY file format!\nError: {e}")
            self.report({'ERROR'}, f'Error: {e}')
            return {'CANCELLED'}

        # Linked scenes may accept transient RNA writes that disappear on reopen.
        # Their overrides belong only to the KEY; local scenes can remember them.
        if scene.is_editable:
            scene.sith_key_flags = flags
            scene.sith_key_types = nodeTypes
            if fps != sceneFps:
                setSceneFrameRate(scene, fps)
        self.report({'INFO'}, f"KEY '{os.path.basename(self.filepath)}' was successfully exported")
        return {'FINISHED'}


class View3doImportReport(bpy.types.Operator):
    """Open the saved recovery report in a separate Blender window"""
    bl_idname = 'wm.sith_view_3do_import_report'
    bl_label  = 'View Import Report'

    report_name: bpy.props.StringProperty(options={'HIDDEN'})

    def execute(self, context):
        report = bpy.data.texts.get(self.report_name)
        if report is None:
            self.report({'ERROR'}, 'The import report is no longer available')
            return {'CANCELLED'}
        if bpy.app.background or context.window is None or context.area is None:
            self.report({'WARNING'}, 'Open the import report from Blender\'s graphical interface')
            return {'CANCELLED'}

        windows = set(context.window_manager.windows)
        try:
            # Duplicate a large editor, not the narrow Properties panel button.
            sourceArea = max(context.window.screen.areas, key=lambda area: area.width * area.height)
            sourceRegion = next(region for region in sourceArea.regions if region.type == 'WINDOW')
            with context.temp_override(area=sourceArea, region=sourceRegion):
                bpy.ops.screen.area_dupli('INVOKE_DEFAULT')
        except RuntimeError as error:
            self.report({'ERROR'}, f'Cannot open the import report window: {error}')
            return {'CANCELLED'}
        window = next((window for window in context.window_manager.windows if window not in windows), None)
        if window is None:
            self.report({'ERROR'}, 'Cannot create the import report window')
            return {'CANCELLED'}

        area = max(window.screen.areas, key=lambda area: area.width * area.height)
        area.type = 'TEXT_EDITOR'
        area.spaces.active.text = report
        area.spaces.active.show_word_wrap = True
        report.cursor_set(0)
        area.spaces.active.top = 0
        return {'FINISHED'}


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

        root = obj
        while root is not None and kModel3doImportReport not in root:
            root = root.parent
        if root is not None:
            recovery = layout.box()
            recovery.alert = True
            recovery.label(text='Imported with errors', icon='ERROR')
            recovery.operator(View3doImportReport.bl_idname, icon='TEXT').report_name = root[kModel3doImportReport]

        root = obj
        while root is not None and kKeyImportReport not in root:
            root = root.parent
        if root is not None:
            recovery = layout.box()
            recovery.alert = True
            recovery.label(text='KEY imported with errors', icon='ERROR')
            recovery.operator(View3doImportReport.bl_idname, text='View KEY Import Report', icon='TEXT').report_name = root[kKeyImportReport]

        mesh_properties = layout.box()
        mesh_properties.label(text='Mesh Properties')
        mesh_properties.prop(obj, kModel3doGeometryMode, text='Geometry')
        mesh_properties.prop(obj, 'sith_model3do_light_mode'  , text='Lighting')
        mesh_properties.prop(obj, 'sith_model3do_texture_mode', text='Texture')
        if obj.type == 'MESH':
            mesh_properties.prop(obj, kModel3doShadow, text='Shadow (Grim Fandango)')

        preview = layout.box()
        preview.label(text='Preview')
        preview.prop(context.scene, model3doPreview.kPreviewProperty, text='Extra Light')

        node_properties = layout.box()
        node_properties.label(text='Hierarchy Node Properties')
        node_properties.prop(obj, 'sith_model3do_hnode_idx'  , text='Sequence no.')
        node_properties.prop(obj, 'sith_model3do_hnode_name' , text='Name')
        node_properties.prop(obj, 'sith_model3do_hnode_flags', text='Flags')
        node_properties.prop(obj, 'sith_model3do_hnode_type' , text='Type')


# -- Update callbacks for Mesh3doFaceLayer properties --
# These fire only when the user actually edits a value in the UI panel,
# so only the changed property is written to the selected faces.

_face_sync_in_progress = False

def _apply_to_selected_faces(context, apply_fn):
    """Helper: apply a function to every selected face in the active edit mesh."""
    if context.edit_object is None or context.edit_object.type != 'MESH':
        return
    bm = bmesh.from_edit_mesh(context.edit_object.data)
    bmMeshInit3doLayers(bm)
    for face in bm.faces:
        if face.select:
            apply_fn(face, bm)

def _on_face_type_update(self, context):
    if _face_sync_in_progress:
        return

    # Determine which flag was toggled by comparing current vs previous
    prev_flags = set(self.prev_type_flags.split(',')) if self.prev_type_flags else set()
    curr_flags = set(self.type)

    added_flags = curr_flags - prev_flags
    removed_flags = prev_flags - curr_flags

    # Apply only the toggled flag to all selected faces
    def apply_flag_toggle(face, bm):
        face_type = bmFaceGetType(face, bm)
        for flag_name in added_flags:
            if hasattr(FaceType, flag_name):
                face_type |= FaceType[flag_name]
        for flag_name in removed_flags:
            if hasattr(FaceType, flag_name):
                # IntFlag inversion stops at known bits; an integer mask keeps
                # unrelated flags from other engine versions or custom assets.
                face_type = FaceType(int(face_type) & ~int(FaceType[flag_name]))
        bmFaceSetType(face, bm, face_type)

    _apply_to_selected_faces(context, apply_flag_toggle)

    # Update the stored previous flags
    self.prev_type_flags = ','.join(sorted(curr_flags))

def _on_face_geo_mode_update(self, context):
    if _face_sync_in_progress:
        return
    _apply_to_selected_faces(context, lambda f, bm: bmFaceSetGeometryMode(f, bm, GeometryMode[self.geo_mode]))

def _on_face_light_mode_update(self, context):
    if _face_sync_in_progress:
        return
    _apply_to_selected_faces(context, lambda f, bm: bmFaceSetLightMode(f, bm, LightMode[self.light_mode]))

def _on_face_texture_mode_update(self, context):
    if _face_sync_in_progress:
        return
    _apply_to_selected_faces(context, lambda f, bm: bmFaceSetTextureMode(f, bm, TextureMode[self.texture_mode]))

def _on_face_extra_light_update(self, context):
    if _face_sync_in_progress:
        return
    _apply_to_selected_faces(context, lambda f, bm: bmFaceSetExtraLight(f, bm, Vector4f(*self.extra_light)))
    if context.edit_object is not None:
        model3doPreview.syncObjectPreview(context.edit_object)


class Mesh3doFaceLayer(bpy.types.PropertyGroup):
    """
    Intermediate class for temporary storing BMFace properties by Mesh3doFacePanel
    and used it to display stored properties to the UI.
    """
    face_id: bpy.props.IntProperty(default = -1)

    # Track previous type flags to detect which specific flag was toggled
    prev_type_flags: bpy.props.StringProperty(default='', options={'HIDDEN', 'SKIP_SAVE'})

    type: bpy.props.EnumProperty(
        name        = 'Type',
        description = 'Face type flag',
        items       = _get_mesh3do_face_type_list(),
        options     = {'ENUM_FLAG'},
        update      = _on_face_type_update
    )

    geo_mode: bpy.props.EnumProperty(
        name        = 'Geometry Mode',
        description = 'Geometry mode',
        items       = _get_model3do_geometry_mode_list(),
        default     = GeometryMode.Texture.name,
        options     = {'HIDDEN', 'LIBRARY_EDITABLE'},
        update      = _on_face_geo_mode_update
    )

    light_mode: bpy.props.EnumProperty(
        name        = 'Lighting Mode',
        description = 'Lighting mode',
        items       = _get_model3do_light_mode_list(),
        default     = LightMode.Gouraud.name,
        options     = {'HIDDEN', 'LIBRARY_EDITABLE'},
        update      = _on_face_light_mode_update
    )

    texture_mode: bpy.props.EnumProperty(
        name        = 'Texture Mode',
        description = 'Texture mapping mode (Not used by IJIM)',
        items       = _get_model3do_texture_mode_list(),
        default     = TextureMode.PerspectiveCorrected.name,
        options     = {'HIDDEN', 'LIBRARY_EDITABLE'},
        update      = _on_face_texture_mode_update
    )

    extra_light: bpy.props.FloatVectorProperty(
        name        = 'Extra Light',
        description = 'Face extra light color',
        size        = 4,
        subtype     ='COLOR',
        default     = [0.0, 0.0, 0.0, 1.0],
        min         = -kFloat32Max,
        max         = kFloat32Max,
        soft_min    = 0.0,
        soft_max    = 1.0,
        update      = _on_face_extra_light_update
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
        # show panel if in edit mode with face selection mode and at least one face selected
        if context.edit_object is not None and context.edit_object.type == 'MESH':
            bm = bmesh.from_edit_mesh(context.edit_object.data)
            return 'FACE' in bm.select_mode and isinstance(bm.select_history.active, bmesh.types.BMFace)
        return False

    @staticmethod
    def _get_face_id(face: bmesh.types.BMFace):
        return hash(face) %2**31 -1 # gen. 32 bit signed hash id of face

    def draw(self, context):
        global _face_sync_in_progress
        wm_fl = context.window_manager.sith_mesh3do_face_layer

        bm = bmesh.from_edit_mesh(context.edit_object.data)
        bmMeshInit3doLayers(bm)

        aface   = bm.faces.active
        enabled = aface is not None and aface.select
        selected_faces = [f for f in bm.faces if f.select]

        if enabled:
            fid = self._get_face_id(aface)
            if wm_fl.face_id != fid: # sync panel properties from active face
                _face_sync_in_progress = True
                wm_fl.face_id      = fid
                type_set           = bmFaceGetType(aface, bm).toSet()
                wm_fl.type         = type_set
                wm_fl.prev_type_flags = ','.join(sorted(type_set))
                wm_fl.geo_mode     = bmFaceGetGeometryMode(aface, bm).name
                wm_fl.light_mode   = bmFaceGetLightMode(aface, bm).name
                wm_fl.texture_mode = bmFaceGetTextureMode(aface, bm).name
                wm_fl.extra_light  = bmFaceGetExtraLight(aface, bm)
                _face_sync_in_progress = False
        else:
            wm_fl.face_id = -1

        layout       = self.layout
        if len(selected_faces) > 1:
            layout.label(text=f'{len(selected_faces)} faces selected')
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
    View3doImportReport,
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
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)

    # 3DO custom properties for object
    setattr(bpy.types.Object, kModel3doShadow, bpy.props.BoolProperty(
        name='Shadow (Grim Fandango)', description="Include this mesh in Grim Fandango's separate projected actor-shadow pass, using a bounds-derived shadow proxy. Does not change ordinary mesh rendering or Blender shadow settings",
        default=False, options={'HIDDEN', 'LIBRARY_EDITABLE'}
    ))
    setattr(bpy.types.Object, kModel3doGeometryMode, bpy.props.EnumProperty(
        name        = 'Geometry Mode',
        description = 'Engine mesh geometry mode, independent of viewport display',
        items       = _get_model3do_geometry_mode_list(),
        default     = 'Texture',
        options     = {'HIDDEN', 'LIBRARY_EDITABLE'}
    ))
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
        options     = {'HIDDEN', 'LIBRARY_EDITABLE'}
    )

    bpy.types.Object.sith_model3do_hnode_flags = HexProperty(
        'sith_model3do_hnode_flags',
        name         = '3DO Hierarchy Node Flags',
        description  = 'The hierarchy node flags',
        pad          = True,
        options      = {'HIDDEN', 'LIBRARY_EDITABLE'}
    )

    bpy.types.Object.sith_model3do_hnode_type = HexProperty(
        'sith_model3do_hnode_type',
        name        = '3DO Hierarchy Node Type',
        description = 'The hierarchy node type',
        default     = '0x01',
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
        pad         = True,
        options     = {'HIDDEN', 'LIBRARY_EDITABLE'}
    )
    model3doPreview.register()

def unregister():
    model3doPreview.unregister()
    del bpy.types.Scene.sith_key_flags
    del bpy.types.Scene.sith_key_types

    del bpy.types.WindowManager.sith_mesh3do_face_layer

    del bpy.types.Object.sith_model3do_hnode_flags
    del bpy.types.Object.sith_model3do_hnode_type
    del bpy.types.Object.sith_model3do_hnode_name
    del bpy.types.Object.sith_model3do_hnode_idx
    del bpy.types.Object.sith_model3do_texture_mode
    delattr(bpy.types.Object, kModel3doGeometryMode)
    delattr(bpy.types.Object, kModel3doShadow)
    del bpy.types.Object.sith_model3do_light_mode

    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)

    for cls in classes:
        bpy.utils.unregister_class(cls)


if __name__ == '__main__':
    try:
        unregister()
    except:
        pass
    register()
