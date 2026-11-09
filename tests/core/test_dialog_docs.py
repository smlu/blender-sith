"""Keep the quick guide complete without importing Blender's UI module."""
import ast
from pathlib import Path
import re
import tomllib
import unittest

from sith.key.keyValidation import kKeyTargets
from sith.material.matWriter import kMatEncodings


ROOT = Path(__file__).resolve().parents[2]


def keyword(call, name):
    return next((item.value for item in call.keywords if item.arg == name), None)


class DialogDocumentationTests(unittest.TestCase):
    def setUp(self):
        self.source = ast.parse((ROOT / 'sith/app.py').read_text(encoding='utf-8'))
        self.usage = (ROOT / 'USAGE.md').read_text(encoding='utf-8')
        self.classes = {item.name: item for item in self.source.body if isinstance(item, ast.ClassDef)}

    def section(self, start, end):
        # Heading titles stay stable even when their decorative icons change.
        return self.usage.split(f' {start}\n', 1)[1].split(f' {end}\n', 1)[0].casefold()

    def test_every_visible_import_export_property_has_a_local_description(self):
        sections = {
            'ImportModel3do': ('Importing 3DO Models', 'Exporting 3DO Models'),
            'ExportModel3do': ('Exporting 3DO Models', 'Importing KEY Animations'),
            'ImportKey': ('Importing KEY Animations', 'Exporting KEY Animations'),
            'ExportKey': ('Exporting KEY Animations', 'Importing MAT Textures'),
            'ImportMat': ('Importing MAT Textures', 'Exporting MAT Textures'),
            'ExportMat': ('Exporting MAT Textures', 'Editing 3DO Properties'),
        }
        for name, bounds in sections.items():
            section = self.section(*bounds)
            checked = 0
            for member in self.classes[name].body:
                if not isinstance(member, ast.AnnAssign) or not isinstance(member.annotation, ast.Call):
                    continue
                call = member.annotation
                options = keyword(call, 'options')
                if options is not None and 'HIDDEN' in ast.literal_eval(options):
                    continue
                label = keyword(call, 'name')
                self.assertIsInstance(label, ast.Constant, f'{name}: property needs a display name')
                with self.subTest(operator=name, property=member.target.id):
                    self.assertIn(f'**{label.value}**'.casefold(), section)
                checked += 1
            self.assertGreater(checked, 0, name)

    def test_all_format_target_and_encoding_choices_are_documented(self):
        for class_name, field, bounds in (
                ('ExportModel3do', 'version', ('Exporting 3DO Models', 'Importing KEY Animations')),
                ('ExportMat', 'target', ('Exporting MAT Textures', 'Editing 3DO Properties'))):
            member = next(item for item in self.classes[class_name].body
                          if isinstance(item, ast.AnnAssign) and item.target.id == field)
            choices = keyword(member.annotation, 'items')
            for choice in choices.elts:
                label = ast.literal_eval(choice.elts[1])
                with self.subTest(operator=class_name, label=label):
                    self.assertIn(label.casefold(), self.section(*bounds))
        targets = self.section('Exporting KEY Animations', 'Importing MAT Textures')
        for _, label, _ in kKeyTargets:
            with self.subTest(target=label):
                self.assertIn(label.casefold(), targets)
        encodings = self.section('Encodings', 'Editing 3DO Properties')
        for _, label, _ in kMatEncodings:
            with self.subTest(encoding=label):
                self.assertIn(f'**{label}**'.casefold(), encodings)

    def test_every_flags_menu_choice_is_documented(self):
        function = next(item for item in self.source.body
                        if isinstance(item, ast.FunctionDef) and item.name == '_get_key_flags_enum_list')
        choices = next(item.value for item in function.body if isinstance(item, ast.Return))
        section = self.section('Flags Menu', 'High Priority Node(s)')
        for item in choices.elts:
            label = ast.literal_eval(item.elts[1])
            with self.subTest(flag=label):
                self.assertIn(f'**{label}**'.casefold(), section)

    def test_documented_checkbox_defaults_match_the_operator_definitions(self):
        sections = {
            'ImportModel3do': ('Importing 3DO Models', 'Exporting 3DO Models'),
            'ExportModel3do': ('Exporting 3DO Models', 'Importing KEY Animations'),
            'ImportKey': ('Importing KEY Animations', 'Exporting KEY Animations'),
        }
        for name, bounds in sections.items():
            for member in self.classes[name].body:
                if not isinstance(member, ast.AnnAssign) or not isinstance(member.annotation, ast.Call):
                    continue
                call = member.annotation
                if not isinstance(call.func, ast.Attribute) or call.func.attr != 'BoolProperty':
                    continue
                label = ast.literal_eval(keyword(call, 'name'))
                expected = 'on' if ast.literal_eval(keyword(call, 'default')) else 'off'
                pattern = r'^\|\s*\*\*' + re.escape(label.casefold()) + r'\*\*\s*\|([^\n]+)'
                with self.subTest(operator=name, property=member.target.id):
                    row = re.search(pattern, self.section(*bounds), re.MULTILINE)
                    self.assertIsNotNone(row, f'Missing option {label}')
                    default = (re.search(r'^\s*(on|off)\s*\|', row[1])
                               or re.search(r'\b(on|off) by default\b', row[1]))
                    self.assertIsNotNone(default, f'Missing default for {label}')
                    self.assertEqual(default[1], expected)

    def test_readme_minimum_blender_and_install_name_match_the_manifest(self):
        with (ROOT / 'sith/blender_manifest.toml').open('rb') as stream:
            manifest = tomllib.load(stream)
        minimum = manifest['blender_version_min']
        if minimum.endswith('.0'):
            minimum = minimum.rsplit('.', 1)[0]
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        self.assertIn(f'**Blender {minimum}+**', readme)
        self.assertIn(f"**{manifest['name']}**", readme)
