"""Malformed 3DO structure must not become a successful empty round trip."""
import contextlib
import io
import json
from pathlib import Path
import re
import shutil
import tempfile
from types import SimpleNamespace
import unittest

from batch.common import run
from batch.core import check
from fixtures import TV
from sith.model.model3doLoader import load3do, Model3doFileVersion
from sith.model.model3doWriter import save3do


class ModelStructureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'structure.3do'
        self.empty = (TV / 'model/empty.3do').read_text()
        self.source = (TV / 'model/triangle.3do').read_text()

    def load_text(self, text, **kwargs):
        self.path.write_text(text)
        return load3do(self.path, **kwargs)

    def test_missing_required_sections_are_not_empty_resources(self):
        sections = re.split(r'(?=SECTION:)', self.empty)[1:]
        for count in range(4):
            with self.subTest(count=count), self.assertRaises((ValueError, OSError)):
                self.load_text(''.join(sections[:count]))
        for missing in range(4):
            with self.subTest(missing=missing), self.assertRaises((ValueError, OSError)):
                self.load_text(''.join(s for i, s in enumerate(sections) if i != missing))

    def test_sections_are_unique_and_ordered(self):
        sections = re.split(r'(?=SECTION:)', self.empty)[1:]
        for index in range(4):
            with self.subTest(duplicate=index), self.assertRaisesRegex(ValueError, 'Duplicate 3DO'):
                self.load_text(''.join(sections[:index + 1] + sections[index:]))
        for index in range(3):
            reordered = sections.copy()
            reordered[index:index + 2] = reversed(reordered[index:index + 2])
            with self.subTest(order=index), self.assertRaisesRegex((ValueError, OSError), '3DO.*(section|HEADER)'):
                self.load_text(''.join(reordered))

    def test_unknown_extension_sections_remain_compatible(self):
        text = self.empty.replace('SECTION: GEOMETRYDEF',
                                  'SECTION: EXTENSION\nignored 123\nSECTION: GEOMETRYDEF')
        model, version = self.load_text(text)
        self.assertEqual((model.geosets, model.meshHierarchy), ([], []))
        self.assertEqual(version, Model3doFileVersion.Version2_3)

    def test_all_negative_counts_are_rejected_before_consuming_records(self):
        replacements = [('MATERIALS 2', 'MATERIALS -1'), ('GEOSETS 1', 'GEOSETS -1'),
                        ('MESHES 1', 'MESHES -1'), ('\nVERTICES 3', '\nVERTICES -1'),
                        ('TEXTURE VERTICES 3', 'TEXTURE VERTICES -1'),
                        ('FACES 1', 'FACES -1'), (' 3 0,0 1,1 2,2', ' -1 0,0 1,1 2,2'),
                        ('HIERARCHY NODES 2', 'HIERARCHY NODES -1'),
                        ('-1 -1 1 -1 1 0.1', '-1 -1 1 -1 -1 0.1')]
        for old, new in replacements:
            self.assertIn(old, self.source)
            with self.subTest(count=old), self.assertRaisesRegex(ValueError, 'count must be nonnegative'):
                self.load_text(self.source.replace(old, new, 1))

    def test_complete_empty_resources_still_round_trip_in_all_versions(self):
        model, _ = self.load_text(self.empty)
        for version in Model3doFileVersion:
            with self.subTest(version=version):
                save3do(model, self.path, version, '')
                warnings = []
                restored, actual = load3do(self.path, allowErrors=True, warnings=warnings)
                self.assertEqual(actual, version)
                self.assertEqual((restored.geosets, restored.meshHierarchy, warnings), ([], [], []))

    def test_missing_hierarchy_recovers_completed_geometry_only_when_opted_in(self):
        text = self.source.split('SECTION: HIERARCHYDEF')[0]
        with self.assertRaisesRegex(ValueError, 'Missing required 3DO section'):
            self.load_text(text)
        warnings = []
        with contextlib.redirect_stdout(io.StringIO()):
            recovered, _ = self.load_text(text, allowErrors=True, warnings=warnings)
        self.assertEqual(len(recovered.geosets[0].meshes[0].faces), 1)
        self.assertIn('Missing required 3DO section', '\n'.join(warnings))

    def test_corpus_reports_partial_and_negative_count_vectors_as_errors(self):
        root, output = Path(self.temp.name) / 'assets', Path(self.temp.name) / 'reports'
        root.mkdir()
        for name in ('header_only.3do', 'negative_counts.3do'):
            shutil.copyfile(TV / 'model/invalid' / name, root / name)
        shutil.copyfile(TV / 'model/empty.3do', root / 'valid.3do')
        before = {p.name: p.read_bytes() for p in root.iterdir()}
        options = SimpleNamespace(assets=[root], output=output, title='synthetic', formats=['3do'],
                                  match='*', limit=0, cmp=None, keep_exports=False)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run(options, check), 1)
        summary = json.loads((output / 'summary.json').read_text())
        self.assertEqual(summary['counts'], {'error': 2, 'pass': 1})
        self.assertTrue(summary['completed'])
        self.assertTrue(summary['full_corpus'])
        self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, before)
