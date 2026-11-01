"""Export headers read actual TOML rather than assuming one manifest layout."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sith import utils


class ExportMetadataTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.manifest = self.folder / 'blender_manifest.toml'
        self.enterContext(patch.object(utils, '__file__', str(self.folder / 'utils.py')))
        self.enterContext(patch.object(utils, '_addon_version_cache', None))

    def test_valid_toml_spacing_comments_and_escaped_strings(self):
        documents = (
            'version\t=\t"1.2.3"\nmaintainer="Test Author" # owner\n',
            "version='1.2.3' # release\nmaintainer = 'Test Author'\n",
            'version="1.2.3"\nmaintainer="Test \\u0041uthor"\n',
            '# comment\nversion="1.2.3"\nmaintainer="Test Author"\n[extra]\nversion="ignored"\n',
        )
        for document in documents:
            with self.subTest(document=document):
                utils._addon_version_cache = None
                self.manifest.write_text(document, encoding='utf-8')
                self.assertEqual(utils._get_addon_version_info(), ('1.2.3', 'Test Author'))
                self.assertEqual(utils.getExportFileHeader('resource'),
                                 'resource created with Blender Sith addon v1.2.3 by Test Author')

    def test_invalid_missing_or_wrongly_typed_metadata_falls_back(self):
        documents = ('', 'version="1.2.3"\n', 'maintainer="Test"\n',
                     'version="1.2.3"\nmaintainer=4\n', 'version=123\nmaintainer="Test"\n',
                     'version=""\nmaintainer="Test"\n', 'version="1.2.3"\nmaintainer=""\n',
                     'version="1.2.3"\nversion="duplicate"\nmaintainer="Test"\n',
                     'version="unterminated\nmaintainer="Test"\n',
                     '[extra]\nversion="1.2.3"\nmaintainer="Test"\n')
        for document in documents:
            with self.subTest(document=document):
                utils._addon_version_cache = None
                self.manifest.write_text(document, encoding='utf-8')
                self.assertEqual(utils._get_addon_version_info(), ('1.x.x', 'Crt Vavros'))

    def test_missing_unreadable_and_invalid_utf8_manifest_fall_back(self):
        self.assertEqual(utils._get_addon_version_info(), ('1.x.x', 'Crt Vavros'))
        utils._addon_version_cache = None
        self.manifest.write_bytes(b'\xff')
        self.assertEqual(utils._get_addon_version_info(), ('1.x.x', 'Crt Vavros'))
        utils._addon_version_cache = None
        with patch('builtins.open', side_effect=PermissionError('blocked manifest')):
            self.assertEqual(utils._get_addon_version_info(), ('1.x.x', 'Crt Vavros'))

    def test_success_and_fallback_are_cached(self):
        for valid in (False, True):
            with self.subTest(valid=valid):
                utils._addon_version_cache = None
                if valid:
                    self.manifest.write_text('version="1.2.3"\nmaintainer="Test Author"\n')
                expected = ('1.2.3', 'Test Author') if valid else ('1.x.x', 'Crt Vavros')
                self.assertEqual(utils._get_addon_version_info(), expected)
                with patch('builtins.open', side_effect=AssertionError('cached metadata must not be reread')):
                    self.assertEqual(utils._get_addon_version_info(), expected)
