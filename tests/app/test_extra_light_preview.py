"""Live shading stays derived from face metadata, never exported vertex colors."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest import mock

import bpy
import bmesh
from _bpy_restrict_state import RestrictBlend

from app.support import SceneTestCase
from fixtures import TV, RGB24, mat_bytes
from sith import app
from sith.material import importMat
from sith.model import model3doPreview as preview
from sith.model.model3doExporter import export3do
from sith.model.model3doImporter import import3do
from sith.model.model3doLoader import load3do, Model3doFileVersion, Model3doFileFormat
from sith.model.utils import bmMeshInit3doLayers, bmFaceSetExtraLight, bmFaceGetExtraLight, getMaterialImage
from sith.types import Vector4f


class ExtraLightTestCase(SceneTestCase):
    def setUp(self):
        super().setUp()
        self.scene = bpy.context.scene
        old = preview.getPreviewEnabled(self.scene)
        self.addCleanup(lambda: preview.setPreviewEnabled(bpy.context.scene, old))
        preview.setPreviewEnabled(self.scene, True)

    def material(self, name='preview.mat'):
        material = bpy.data.materials.new(name)
        material.use_nodes = True
        shader = next(node for node in material.node_tree.nodes if node.type == 'BSDF_PRINCIPLED')
        shader.inputs['Base Color'].default_value = (0.2, 0.4, 0.8, 1)
        return material, shader

    def model(self, material=None, colors=((0.25, 0, 0, 1), (0, 0.5, 0, 1))):
        mesh = bpy.data.meshes.new('preview')
        mesh.from_pydata([(-1, -0.75, 0), (0, -0.75, 0), (0, 0.75, 0), (-1, 0.75, 0),
                          (0, -0.75, 0), (1, -0.75, 0), (1, 0.75, 0), (0, 0.75, 0)], [],
                         [(0, 1, 2, 3), (4, 5, 6, 7)])
        obj = bpy.data.objects.new('preview', mesh)
        self.scene.collection.objects.link(obj)
        mesh.materials.append(material)
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmMeshInit3doLayers(bm)
        for face, color in zip(bm.faces, colors):
            bmFaceSetExtraLight(face, bm, Vector4f(*color))
        bm.to_mesh(mesh)
        bm.free()
        return obj

    def group(self, material):
        return next(node for node in material.node_tree.nodes if preview.isPreviewNode(node))

    def values(self, mesh):
        return [tuple(mesh.attributes[name].data[index].value for name in preview.kPreviewChannels)
                for index in range(len(mesh.polygons))]


class ExtraLightPreviewTests(ExtraLightTestCase):
    def test_registration_defers_refresh_until_scene_data_is_available(self):
        material, _ = self.material()
        obj = self.model(material)
        other = bpy.data.scenes.new('deferred preview')
        other.collection.objects.link(obj)
        preview.setPreviewEnabled(other, False)
        # Model construction initializes these too; emulate an older .blend
        # whose original lighting exists without the derived preview cache.
        for name in preview.kPreviewChannels:
            obj.data.attributes.remove(obj.data.attributes[name])
        preview.unregister()
        try:
            # Blender replaces bpy.data/context while enabling an add-on.
            # Register RNA and callbacks here, but do not inspect any scenes.
            with mock.patch.object(preview, 'syncScenePreview') as sync:
                with RestrictBlend():
                    preview.register()
                sync.assert_not_called()
            self.assertTrue(bpy.app.timers.is_registered(preview._initPreview))
            self.assertEqual(bpy.app.handlers.load_post.count(preview._loadPreview), 1)
            self.assertNotIn(preview.kPreviewChannels[0], obj.data.attributes)

            # Invoke the pending callback after registration, when data is safe.
            bpy.app.timers.unregister(preview._initPreview)
            with mock.patch.object(preview, 'syncScenePreview',
                                   wraps=preview.syncScenePreview) as sync:
                self.assertIsNone(preview._initPreview())
                self.assertEqual(sync.call_args_list,
                                 [mock.call(scene) for scene in bpy.data.scenes])
            self.assertIn(preview.kPreviewChannels[0], obj.data.attributes)
            self.assertIsNotNone(self.group(material))
            self.assertFalse(preview.getPreviewEnabled(other))
        finally:
            bpy.data.scenes.remove(other)
            if not hasattr(bpy.types.Scene, preview.kPreviewProperty):
                preview.register()

    def test_unregister_cancels_pending_preview_refresh(self):
        preview.unregister()
        try:
            for _ in range(2):
                with RestrictBlend():
                    preview.register()
                self.assertTrue(bpy.app.timers.is_registered(preview._initPreview))
                self.assertEqual(bpy.app.handlers.load_post.count(preview._loadPreview), 1)
                preview.unregister()
                self.assertFalse(bpy.app.timers.is_registered(preview._initPreview))
                self.assertNotIn(preview._loadPreview, bpy.app.handlers.load_post)
                self.assertFalse(hasattr(bpy.types.Scene, preview.kPreviewProperty))
        finally:
            if not hasattr(bpy.types.Scene, preview.kPreviewProperty):
                preview.register()

    def test_default_and_panel_location(self):
        scene = bpy.data.scenes.new('preview default')
        try:
            self.assertTrue(getattr(scene, preview.kPreviewProperty))
        finally:
            bpy.data.scenes.remove(scene)
        material, _ = self.material()
        obj = self.model(material)
        layout = mock.Mock()
        app.Model3doPanel.draw(SimpleNamespace(layout=layout), SimpleNamespace(object=obj, scene=self.scene))
        self.assertTrue(any(call.kwargs.get('text') == 'Preview' for call in layout.mock_calls))
        self.assertTrue(any(call[0].endswith('prop') and call.args == (self.scene, preview.kPreviewProperty)
                            for call in layout.mock_calls))

    def test_numeric_face_attributes_do_not_become_color_attributes(self):
        obj = self.model(colors=((-2, 3, 0.25, 0.5), (0.5, -0.75, 0, 1)))
        preview.syncObjectPreview(obj)
        self.assertEqual(self.values(obj.data), [(-1, 1, 0.25), (0.5, -0.75, 0)])
        self.assertEqual(len(obj.data.color_attributes), 0)
        for name in preview.kPreviewChannels:
            attribute = obj.data.attributes[name]
            self.assertEqual((attribute.domain, attribute.data_type), ('FACE', 'FLOAT'))
        bm = bmesh.new()
        try:
            bm.from_mesh(obj.data)
            self.assertEqual([tuple(bmFaceGetExtraLight(face, bm)) for face in bm.faces],
                             [(-2, 3, 0.25, 0.5), (0.5, -0.75, 0, 1)])
        finally:
            bm.free()

    def test_ui_edits_refresh_selected_faces_immediately(self):
        material, _ = self.material()
        obj = self.model(material)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        for face in bm.faces:
            face.select_set(face.index == 0)
        bm.faces.active = bm.faces[0]
        layer = bpy.context.window_manager.sith_mesh3do_face_layer
        layer.face_id = -1
        panel = SimpleNamespace(layout=mock.Mock(), _get_face_id=app.Mesh3doFacePanel._get_face_id)
        app.Mesh3doFacePanel.draw(panel, bpy.context)
        layer.extra_light = (-0.5, 0.75, 2, 0.25)
        for name, expected in zip(preview.kPreviewChannels, (-0.5, 0.75, 1)):
            field = bm.faces.layers.float[name]
            self.assertEqual(bm.faces[0][field], expected)
        self.assertEqual(bm.faces[1][bm.faces.layers.float[preview.kPreviewChannels[1]]], 0.5)
        self.assertEqual(len(obj.data.color_attributes), 0)
        self.assertIsNotNone(self.group(material))

    def test_shared_material_reads_each_mesh_and_scene_without_drivers(self):
        material, _ = self.material()
        first = self.model(material)
        second = self.model(material, colors=((0, 0, 0.9, 1), (0, 0, 0, 1)))
        preview.syncObjectPreview(first)
        preview.syncObjectPreview(second)
        self.assertEqual(sum(preview.isPreviewNode(node) for node in material.node_tree.nodes), 1)
        self.assertNotEqual(self.values(first.data), self.values(second.data))
        group = self.group(material).node_tree
        state = next(node for node in group.nodes if node.type == 'ATTRIBUTE' and node.attribute_type == 'VIEW_LAYER')
        self.assertEqual(state.attribute_name, preview.kPreviewDisabled)
        self.assertIsNone(group.animation_data)
        other = bpy.data.scenes.new('other preview')
        try:
            preview.setPreviewEnabled(other, False)
            self.assertTrue(preview.getPreviewEnabled(self.scene))
            self.assertFalse(preview.getPreviewEnabled(other))
        finally:
            bpy.data.scenes.remove(other)

    def test_toggle_keeps_colors_normals_images_and_material_ids(self):
        obj = import3do(TV / 'model/face_lighting_hdr.3do', clearScene=False)
        mesh_obj = next(child for child in obj.children_recursive if child.type == 'MESH')
        mesh = mesh_obj.data
        before = ([(attribute.name, [tuple(value.color) for value in attribute.data])
                   for attribute in mesh.color_attributes],
                  mesh.color_attributes.active_color_index,
                  [tuple(normal.vector) for normal in mesh.corner_normals],
                  tuple(mesh.materials), set(bpy.data.images))
        for _ in range(3):
            setattr(self.scene, preview.kPreviewProperty, False)
            setattr(self.scene, preview.kPreviewProperty, True)
        after = ([(attribute.name, [tuple(value.color) for value in attribute.data])
                  for attribute in mesh.color_attributes],
                 mesh.color_attributes.active_color_index,
                 [tuple(normal.vector) for normal in mesh.corner_normals],
                 tuple(mesh.materials), set(bpy.data.images))
        self.assertEqual(after, before)

    def test_preview_never_changes_export_bytes_for_any_model_format(self):
        material, _ = self.material()
        obj = self.model(material, colors=((-0.25, 2, 0.5, 0.75), (1, 0.25, 0, 1)))
        colors = obj.data.color_attributes.new(name='authored', type='FLOAT_COLOR', domain='CORNER')
        colors.data.foreach_set('color', [value for _ in obj.data.loops for value in (0.25, 0.5, 0.75, 1)])
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'preview.3do'
            for version in (*Model3doFileVersion, Model3doFileFormat.GrimFandango):
                for vertex_colors in (False, True):
                    with self.subTest(version=version, colors=vertex_colors):
                        export3do(obj, str(output), version, False, vertex_colors, True)
                        original = output.read_bytes()
                        preview.syncObjectPreview(obj)
                        for enabled in (False, True):
                            setattr(self.scene, preview.kPreviewProperty, enabled)
                            export3do(obj, str(output), version, False, vertex_colors, True)
                            self.assertEqual(output.read_bytes(), original)

    def test_shader_keeps_image_lookup_and_alpha_links(self):
        material, shader = self.material()
        nodes, links = material.node_tree.nodes, material.node_tree.links
        image = bpy.data.images.new('preview image', width=16, height=8)
        texture = nodes.new('ShaderNodeTexImage')
        texture.image = image
        links.new(texture.outputs['Color'], shader.inputs['Base Color'])
        links.new(texture.outputs['Alpha'], shader.inputs['Alpha'])
        shader.inputs['Emission Color'].default_value = (0.1, 0.2, 0.3, 1)
        shader.inputs['Emission Strength'].default_value = 2
        preview.ensureMaterialPreview(material)
        group = self.group(material)
        self.assertIs(getMaterialImage(material), image)
        self.assertEqual(shader.inputs['Alpha'].links[0].from_node, texture)
        self.assert_vector(group.inputs['Emission Color'].default_value, (0.1, 0.2, 0.3, 1))
        self.assertEqual(group.inputs['Emission Strength'].default_value, 2)
        for _ in range(3):
            preview.ensureMaterialPreview(material)
        self.assertEqual(sum(preview.isPreviewNode(node) for node in nodes), 1)

    def test_material_reload_restores_its_preview(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'reload.mat'
            source.write_bytes(mat_bytes(RGB24, [(1, 1, [bytes((30, 60, 90))], False, 0)]))
            material = importMat(source)
            obj = self.model(material)
            preview.syncObjectPreview(obj)
            source.write_bytes(mat_bytes(RGB24, [(1, 1, [bytes((90, 60, 30))], False, 0)]))
            self.assertIs(importMat(source), material)
            self.assertEqual(sum(preview.isPreviewNode(node) for node in material.node_tree.nodes), 1)

    def test_import_preserves_disabled_choice_including_clear_scene(self):
        setattr(self.scene, preview.kPreviewProperty, False)
        for clear in (False, True):
            root = import3do(TV / 'model/face_lighting_hdr.3do', clearScene=clear)
            self.assertFalse(preview.getPreviewEnabled(bpy.context.scene))
            mesh_obj = next(child for child in root.children_recursive if child.type == 'MESH')
            self.assertIn(preview.kPreviewChannels[0], mesh_obj.data.attributes)

    def test_load_refresh_and_unregister_restore_original_shader(self):
        material, shader = self.material()
        original = tuple(shader.inputs['Base Color'].default_value)
        obj = self.model(material)
        preview.syncObjectPreview(obj)
        preview._loadPreview(None)
        self.assertEqual(sum(preview.isPreviewNode(node) for node in material.node_tree.nodes), 1)
        try:
            preview.unregister()
            self.assertFalse(shader.inputs['Base Color'].is_linked)
            self.assert_vector(shader.inputs['Base Color'].default_value, original)
            self.assertFalse(any(preview.isPreviewNode(node) for node in material.node_tree.nodes))
        finally:
            preview.register()

    def test_animated_and_linked_materials_are_not_rewritten(self):
        material, shader = self.material()
        material.node_tree.animation_data_create()
        nodes = set(material.node_tree.nodes)
        preview.ensureMaterialPreview(material)
        self.assertEqual(set(material.node_tree.nodes), nodes)
        preview.ensureMaterialPreview(SimpleNamespace(is_editable=False))

    def test_refresh_and_cleanup_preserve_user_rewired_shader_inputs(self):
        material, shader = self.material()
        obj = self.model(material)
        preview.syncObjectPreview(obj)
        color = material.node_tree.nodes.new('ShaderNodeRGB')
        material.node_tree.links.new(color.outputs[0], shader.inputs['Base Color'])
        preview.syncObjectPreview(obj)
        self.assertEqual(sum(preview.isPreviewNode(node) for node in material.node_tree.nodes), 1)
        try:
            preview.unregister()
            self.assertEqual(shader.inputs['Base Color'].links[0].from_node, color)
        finally:
            preview.register()

    def test_cleanup_keeps_preview_groups_reused_in_user_graphs(self):
        material, shader = self.material()
        obj = self.model(material)
        preview.syncObjectPreview(obj)
        group = self.group(material)
        material.node_tree.links.new(group.outputs['Base Color'], shader.inputs['Roughness'])
        try:
            preview.unregister()
            self.assertEqual(shader.inputs['Roughness'].links[0].from_node, group)
        finally:
            preview.register()

    def test_unrelated_mesh_and_empty_material_slots_stay_unmodified(self):
        material, _ = self.material()
        obj = self.model(None)
        preview.syncObjectPreview(obj)
        self.assertIsNone(obj.data.materials[0])
        mesh = bpy.data.meshes.new('ordinary')
        ordinary = bpy.data.objects.new('ordinary', mesh)
        self.scene.collection.objects.link(ordinary)
        mesh.materials.append(material)
        preview.syncObjectPreview(ordinary)
        self.assertFalse(any(preview.isPreviewNode(node) for node in material.node_tree.nodes))

    def test_blend_data_retains_disabled_state(self):
        setattr(self.scene, preview.kPreviewProperty, False)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'preview.blend'
            bpy.data.libraries.write(str(path), {self.scene})
            with bpy.data.libraries.load(str(path), link=False) as (source, destination):
                destination.scenes = [self.scene.name]
            loaded = destination.scenes[0]
            try:
                self.assertFalse(preview.getPreviewEnabled(loaded))
            finally:
                bpy.data.scenes.remove(loaded)


class ExtraLightRenderTests(ExtraLightTestCase):
    """Small CPU renders prove that derived attributes affect pixels, not just nodes."""

    def render_pixels(self, scene=None, engine='CYCLES', capturePath=None):
        source = scene or self.scene
        scene = bpy.data.scenes.new('isolated preview render')
        scene[preview.kPreviewDisabled] = int(not preview.getPreviewEnabled(source))
        for obj in source.objects:
            if obj.type == 'MESH':
                scene.collection.objects.link(obj)
        scene.render.engine = engine
        scene.cycles.device = 'CPU'
        scene.cycles.samples = 4
        scene.cycles.use_denoising = False
        scene.render.resolution_x = 32
        scene.render.resolution_y = 24
        scene.render.resolution_percentage = 100
        scene.render.film_transparent = True
        scene.render.image_settings.file_format = 'OPEN_EXR'
        scene.render.image_settings.color_mode = 'RGBA'
        scene.render.image_settings.color_depth = '32'
        scene.world = bpy.data.worlds.new('preview black')
        scene.world.use_nodes = True
        scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0
        camera = bpy.data.cameras.new('preview camera')
        camera.type = 'ORTHO'
        camera.ortho_scale = 2.5
        obj = bpy.data.objects.new('preview camera', camera)
        obj.location = (0, 0, 3)
        scene.collection.objects.link(obj)
        scene.camera = obj
        try:
            with tempfile.TemporaryDirectory() as directory:
                bpy.ops.render.render(scene=scene.name)
                path = str(Path(directory) / 'preview.exr')
                bpy.data.images['Render Result'].save_render(path, scene=scene)
                if capturePath is not None:
                    scene.render.image_settings.file_format = 'PNG'
                    bpy.data.images['Render Result'].save_render(str(capturePath), scene=scene)
                image = bpy.data.images.load(path, check_existing=False)
                try:
                    pixels = tuple(image.pixels)
                finally:
                    bpy.data.images.remove(image)
        finally:
            world = scene.world
            bpy.data.scenes.remove(scene)
            bpy.data.objects.remove(obj)
            bpy.data.cameras.remove(camera)
            bpy.data.worlds.remove(world)
        return [pixels[4 * (12 * 32 + x):4 * (12 * 32 + x) + 4] for x in (9, 22)]

    def test_rendered_colors_update_when_face_values_and_toggle_change(self):
        material, shader = self.material()
        shader.inputs['Base Color'].default_value = (1, 1, 1, 1)
        obj = self.model(material)
        preview.syncObjectPreview(obj)
        on = self.render_pixels()
        self.assert_vector(on[0], (0.25, 0, 0, 1), tolerance=0.02)
        self.assert_vector(on[1], (0, 0.5, 0, 1), tolerance=0.02)
        setattr(self.scene, preview.kPreviewProperty, False)
        off = self.render_pixels()
        for pixel in off:
            self.assert_vector(pixel, (0, 0, 0, 1), tolerance=0.02)

        # Mutate the authoritative face field, then render the updated cache.
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        bmFaceSetExtraLight(bm.faces[0], bm, Vector4f(0, 0, 0.75, 1))
        bm.to_mesh(obj.data)
        bm.free()
        setattr(self.scene, preview.kPreviewProperty, True)
        updated = self.render_pixels()
        self.assert_vector(updated[0], (0, 0, 0.75, 1), tolerance=0.02)

    def test_transparent_texture_stays_transparent_with_extra_light(self):
        material, shader = self.material()
        image = bpy.data.images.new('transparent preview', width=1, height=1)
        image.pixels = (1, 0.5, 0.25, 0)
        node = material.node_tree.nodes.new('ShaderNodeTexImage')
        node.image = image
        material.node_tree.links.new(node.outputs['Color'], shader.inputs['Base Color'])
        material.node_tree.links.new(node.outputs['Alpha'], shader.inputs['Alpha'])
        obj = self.model(material, colors=((1, 1, 1, 1), (1, 1, 1, 1)))
        preview.syncObjectPreview(obj)
        for pixel in self.render_pixels():
            self.assert_vector(pixel, (0, 0, 0, 0), tolerance=0.02)
