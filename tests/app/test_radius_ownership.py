"""Radius helpers belong to objects, not globally unique display names."""
from pathlib import Path

import bpy

from app.support import SceneTestCase
from sith.key.keyExporter import _make_key_from_obj
from sith.model.model3doExporter import makeModel3doFromObj
from sith.model.model3doImporter import import3do
from sith.model.utils import (getMeshRadiusObj, getModelRadiusObj, kMeshRadius,
                              kModelRadius, kModel3doRadiusKind)

TV = Path(__file__).resolve().parents[1] / 'tv/model/shared_mesh.3do'


class RadiusOwnershipTests(SceneTestCase):
    def load(self, preserve=True):
        return import3do(TV, importRadiusObj=True, preserveOrder=preserve)

    def joints(self, root):
        return sorted((obj for obj in root.children_recursive
                       if obj.type == 'MESH' and kModel3doRadiusKind not in obj),
                      key=lambda obj: obj.sith_model3do_hnode_idx)

    def test_shared_mesh_instances_export_their_own_edited_helpers_in_all_modes(self):
        # Imported instances share a source mesh name but own distinct bounds.
        for preserve in (False, True):
            for sync in (False, True):
                with self.subTest(preserve=preserve, sync=sync):
                    root = self.load(preserve)
                    first, second = self.joints(root)
                    for obj, scale in ((first, 1.5), (second, 5)):
                        helper = next(child for child in obj.children
                                      if child.get(kModel3doRadiusKind) == kMeshRadius)
                        self.assertEqual(getMeshRadiusObj(None, obj), helper)
                        helper.scale = (scale,) * 3
                    bpy.context.view_layer.update()

                    model = makeModel3doFromObj('bounds.3do', root, sync_mesh_list=sync)
                    for index, radius in ((1, 3), (2, 10)):
                        node = model.meshHierarchy[index]
                        self.assertEqual(model.geosets[0].meshes[node.meshIdx].radius, radius)
                    self.assertEqual(model.radius, 4)
                    self.assertEqual(len(model.meshHierarchy), 3)

    def test_renaming_objects_and_helpers_keeps_ownership_and_excludes_helpers(self):
        root = self.load()
        first, second = self.joints(root)
        root.name = 'renamed_model'
        root_helper = getModelRadiusObj(root)
        root_helper.name, root_helper.scale = 'outer_bound', (2, 2, 2)
        second.name = 'renamed_joint'
        mesh_helper = getMeshRadiusObj(None, second)
        mesh_helper.name, mesh_helper.scale = 'inner_bound', (5, 5, 5)
        bpy.context.view_layer.update()

        model = makeModel3doFromObj('renamed.3do', root)
        self.assertEqual(len(model.meshHierarchy), 3)
        self.assertEqual(model.radius, 8)
        self.assertEqual(model.geosets[0].meshes[model.meshHierarchy[2].meshIdx].radius, 10)
        self.assertEqual(getModelRadiusObj(root), root_helper)
        self.assertEqual(getMeshRadiusObj(None, second), mesh_helper)

        # KEY must use the same skeleton, without treating renamed bounds as joints.
        first.keyframe_insert(data_path='location', frame=0)
        scene = bpy.context.scene
        scene.frame_end, scene.sith_key_flags, scene.sith_key_types = 4, set(), 'ffff'
        key = _make_key_from_obj('renamed.key', root, scene)
        self.assertEqual(key.numJoints, 3)
        self.assertEqual([node.idx for node in key.nodes], [1])

    def test_legacy_helpers_are_resolved_by_parent_even_without_kind_markers(self):
        root = self.load()
        for obj in [root, *self.joints(root)]:
            helper = next(child for child in obj.children if kModel3doRadiusKind in child)
            del helper[kModel3doRadiusKind]
            found = getModelRadiusObj(obj) if obj == root else getMeshRadiusObj(None, obj)
            self.assertEqual(found, helper)

    def test_global_name_collision_cannot_steal_another_objects_helper(self):
        root = self.load()
        first, second = self.joints(root)
        helper = getMeshRadiusObj(None, first)
        helper.parent = second
        # A helper with the expected global name is no longer owned by first.
        self.assertIsNone(getMeshRadiusObj(None, first))
        with self.assertRaisesRegex(ValueError, 'Multiple radius helpers'):
            getMeshRadiusObj(None, second)

    def test_duplicate_model_helpers_are_rejected_instead_of_arbitrarily_selected(self):
        root = self.load()
        duplicate = getModelRadiusObj(root).copy()
        bpy.context.scene.collection.objects.link(duplicate)
        duplicate.parent = root
        with self.assertRaisesRegex(ValueError, 'Multiple radius helpers'):
            makeModel3doFromObj('ambiguous.3do', root)

    def test_deleted_helper_falls_back_to_geometry_not_a_global_decoy(self):
        root = self.load()
        first, second = self.joints(root)
        helper = getMeshRadiusObj(None, first)
        name = helper.name
        bpy.data.objects.remove(helper, do_unlink=True)
        decoy = bpy.data.objects.new(name, None)
        bpy.context.scene.collection.objects.link(decoy)
        self.assertIsNone(getMeshRadiusObj(None, first))
        model = makeModel3doFromObj('fallback.3do', root)
        radius = model.geosets[0].meshes[model.meshHierarchy[1].meshIdx].radius
        self.assertGreater(radius, 1)
        self.assertLess(radius, 2)
