import unittest

import bpy


class SceneTestCase(unittest.TestCase):
    """Use only the factory-startup test process's scene and datablocks."""
    def setUp(self):
        self.clear_data()
        self.addCleanup(self.clear_data)

    @staticmethod
    def clear_data():
        if bpy.context.object is not None and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        for collection in (bpy.data.meshes, bpy.data.materials, bpy.data.images, bpy.data.actions):
            for item in list(collection):
                collection.remove(item)

    def assert_vector(self, actual, expected, tolerance=1e-5):
        self.assertEqual(len(actual), len(expected))
        for a, b in zip(actual, expected):
            self.assertAlmostEqual(a, b, delta=tolerance)
