import subprocess
import sys
import unittest
from pathlib import Path


class ImportTests(unittest.TestCase):
    def test_resources_do_not_import_blender(self):
        """A fresh interpreter rejects Blender imports, rather than faking bpy."""
        code = '''
import importlib.abc
import sys
class NoBlender(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('bpy', 'bmesh', 'mathutils', 'bpy_extras'):
            raise AssertionError('Unexpected application dependency: ' + fullname)
sys.meta_path.insert(0, NoBlender())
import sith
from sith.key.keyLoader import loadKey
from sith.key.keyWriter import saveKey
from sith.key.keyBinary import readBinaryKey, encodeBinaryKey
from sith.key.keyValidation import validateKeyForTarget
from sith.model.model3doLoader import load3do
from sith.model.model3doWriter import save3do
from sith.model.model3doBinary import readBinary3do, encodeBinary3do
from sith.material import ColorMap
from sith.material.mat import _read_header, _read_mipmap
from sith.types import Flag, Vector3f
'''
        # Blender's embedded Python executable is blender.exe, not a Python CLI.
        if 'bpy' in sys.modules:
            from sith.material import mat
            self.assertNotIn('bpy', vars(mat))
            return
        result = subprocess.run([sys.executable, '-B', '-c', code],
                                cwd=Path(__file__).resolve().parents[2],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
