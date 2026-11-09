"""Recovery must not turn intentionally unused mesh-table entries into joints."""
import copy
from pathlib import Path
import tempfile

import bpy

from app.support import SceneTestCase
from fixtures import TV
from sith.model.model3doLoader import load3do, Model3doFileVersion
from sith.model.model3doWriter import save3do
from sith.model.model3doImporter import import3do


class RecoveryUnusedMeshTests(SceneTestCase):
    def test_all_modes_keep_the_complete_hierarchy_and_visible_meshes(self):
        with tempfile.TemporaryDirectory() as directory:
            folder, counter = Path(directory), 0
            for version in Model3doFileVersion:
                for recovery in (False, True):
                    for preserve in (False, True):
                        for sync in (False, True):
                            with self.subTest(version=version, recovery=recovery, preserve=preserve, sync=sync):
                                self.clear_data()
                                # The second mesh is valid source data but has no
                                # hierarchy binding, as in original JKDF2/MOTS assets.
                                model, _ = load3do(TV / 'model' / 'triangle.3do')
                                unused = copy.deepcopy(model.geosets[0].meshes[0])
                                unused.idx, unused.name = 1, 'intentionally_unused'
                                model.geosets[0].meshes.append(unused)
                                counter += 1
                                source, output = folder / f'{counter}-source.3do', folder / f'{counter}-output.3do'
                                save3do(model, source, version, '')
                                warnings = []
                                root = import3do(source, uvAbsolute_2_1=False, preserveOrder=preserve,
                                                 clearScene=False, allowErrors=recovery, warnings=warnings)
                                self.assertEqual(warnings, [])
                                self.assertEqual(len(root.children_recursive), 2)
                                bpy.context.view_layer.objects.active = root
                                root.select_set(True)

                                # Exercise the public export resolver too; extra
                                # recovery roots previously made this export fail.
                                self.assertEqual(bpy.ops.export_scene.sith_3do(
                                    filepath=str(output), version=version.name, absolute_uv=False,
                                    export_vert_colors=True, sync_mesh_list=sync), {'FINISHED'})
                                restored, _ = load3do(output)
                                self.assertEqual([node.name for node in restored.meshHierarchy], ['root', 'head'])
                                self.assertEqual([node.parentIdx for node in restored.meshHierarchy], [-1, 0])
                                self.assertEqual(len(restored.geosets[0].meshes), 1)
