"""Run resource tests with Python, or Blender integration tests with --suite app."""
import argparse
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))


def main():
    # Blender consumes its own arguments before the -- separator.
    args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    in_blender = 'bpy' in sys.modules
    if in_blender and '--' not in sys.argv:
        args = []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=('core', 'app', 'all'),
                        default='all' if in_blender else 'core')
    options = parser.parse_args(args)
    needs_blender = options.suite in ('app', 'all')
    if needs_blender:
        import bpy
        if bpy.app.version < (5, 0, 0):
            raise RuntimeError('Application tests require Blender 5.0 or newer')
        if not bpy.app.background:
            raise RuntimeError('Application tests require a separate background Blender process')
        import sith
        sith.register()
    try:
        suite = unittest.TestSuite()
        groups = ('core', 'app') if options.suite == 'all' else (options.suite,)
        for group in groups:
            suite.addTests(unittest.TestLoader().discover(
                str(root / 'tests' / group), pattern='test_*.py',
                top_level_dir=str(root / 'tests')))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    finally:
        if needs_blender:
            sith.unregister()
    if not result.wasSuccessful():
        raise RuntimeError('Regression tests failed')


if __name__ == '__main__':
    main()
