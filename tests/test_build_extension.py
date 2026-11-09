# SPDX-License-Identifier: GPL-3.0-or-later
"""Packager contract tests; all generated files live in external temporary trees."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_extension.py"


class BuildExtensionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sith package tests ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source with spaces"
        self.addon = self.source / "sith"
        self.addon.mkdir(parents=True)
        self.write_manifest()
        (self.addon / "__init__.py").write_bytes(b"VALUE = 1\r\n")
        (self.source / "LICENSE").write_bytes(b"Original license text\r\nSecond line\r\n")

    def write_manifest(self, platforms=None, version="1.2.3"):
        text = f'schema_version = "1.0.0"\nid = "sith"\nversion = "{version}"\n'
        if platforms is not None:
            text += "platforms = " + json.dumps(platforms) + "\n"
        (self.addon / "blender_manifest.toml").write_bytes(text.encode())

    def run_builder(self, output=None, source=None, extra=()):
        command = [sys.executable, "-B", str(SCRIPT), "--source-dir", str(source or self.source)]
        if output is not None:
            command += ["--output-dir", str(output)]
        result = subprocess.run(command + list(extra), cwd=self.root, capture_output=True,
                                text=True, timeout=20, check=False)
        return result

    def build(self, output, platform="universal", source=None):
        result = self.run_builder(output, source=source)
        self.assertEqual(result.returncode, 0, result.stderr)
        archive = output / f"sith-1.2.3-{platform}.zip"
        receipt = output / f"sith-1.2.3-{platform}.receipt.json"
        self.assertTrue(archive.is_file())
        self.assertTrue(receipt.is_file())
        return archive, json.loads(receipt.read_text(encoding="utf-8"))

    def test_root_layout_allowlist_normalization_and_provenance(self):
        nested = self.addon / "nested folder"
        nested.mkdir()
        (nested / "module.py").write_bytes(b"# nested\r\n")
        (nested / "settings.toml").write_bytes(b"enabled = true\n")
        for name in ("bytecode.pyc",):
            (nested / name).write_bytes(b"do not package")
        cache = nested / "__pycache__"
        cache.mkdir()
        (cache / "cache.pyc").write_bytes(b"do not package")
        (self.source / "outside.py").write_bytes(b"do not package")
        archive, receipt = self.build(self.root / "output")
        with zipfile.ZipFile(archive) as package:
            self.assertEqual(package.namelist(), ["LICENSE", "__init__.py", "blender_manifest.toml",
                                                 "nested folder/module.py", "nested folder/settings.toml"])
            self.assertEqual(package.read("LICENSE"), b"Original license text\nSecond line\n")
            self.assertEqual(package.read("__init__.py"), b"VALUE = 1\n")
            self.assertEqual(package.read("blender_manifest.toml"),
                             (self.addon / "blender_manifest.toml").read_bytes())
            for info in package.infolist():
                self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
                self.assertEqual(stat.S_IMODE(info.external_attr >> 16), 0o644)
        self.assertEqual(receipt["version"], "1.2.3")
        self.assertEqual(receipt["platform"], "universal")
        self.assertEqual(receipt["archive"]["sha256"], hashlib.sha256(archive.read_bytes()).hexdigest())
        records = {item["archive_path"]: item for item in receipt["files"]}
        self.assertEqual(records["__init__.py"]["raw_sha256"],
                         hashlib.sha256(b"VALUE = 1\r\n").hexdigest())
        self.assertEqual(records["__init__.py"]["packaged_sha256"],
                         hashlib.sha256(b"VALUE = 1\n").hexdigest())
        self.assertEqual(records["LICENSE"]["source_path"], "LICENSE")
        self.assertNotIn(str(self.root), json.dumps(receipt))
        self.assertFalse(list(self.source.rglob("*.zip")))
        self.assertFalse(list(self.source.rglob("*.receipt.json")))

    def test_unclassified_extension_resources_fail_instead_of_disappearing(self):
        for name in ("preset.txt", "icon.png", "schema.json"):
            with self.subTest(name=name):
                resource = self.addon / name
                resource.write_bytes(b"required future resource")
                output = self.root / (name + "-output")
                result = self.run_builder(output)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Unclassified extension resource", result.stderr)
                self.assertFalse(output.exists())
                resource.unlink()

    def test_repeated_build_bytes_do_not_depend_on_mtime_permissions_or_line_endings(self):
        first, _ = self.build(self.root / "first")
        before = first.read_bytes()
        for path in [self.addon / "__init__.py", self.source / "LICENSE"]:
            path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))
            os.utime(path, (1700000000, 1700000000))
            path.chmod(0o744)
        second, _ = self.build(self.root / "second")
        self.assertEqual(before, second.read_bytes())

    def test_unreadable_submodule_aborts_before_creating_archive_or_receipt(self):
        required = self.addon / "required_module"
        required.mkdir()
        (self.addon / "__init__.py").write_text("from .required_module import VALUE\n", encoding="utf-8")
        (required / "__init__.py").write_text("VALUE = 123\n", encoding="utf-8")
        baseline, _ = self.build(self.root / "readable")
        with zipfile.ZipFile(baseline) as archive:
            self.assertIn("required_module/__init__.py", archive.namelist())

        spec = importlib.util.spec_from_file_location("sith_packager_unreadable_test", SCRIPT)
        packager = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(packager)
        real_scandir = os.scandir

        def unreadable_directory(path):
            if Path(path) == required:
                raise PermissionError("Cannot enumerate required package module")
            return real_scandir(path)

        output = self.root / "unreadable"
        # Model an enumeration failure without relying on host ACLs or privileges.
        # Leave the actual walk, source inventory and archive builder in use.
        with patch.object(packager.os, "scandir", side_effect=unreadable_directory), \
                self.assertRaisesRegex(PermissionError, "required package module"):
            packager.build_extension(self.source, output)
        self.assertFalse(output.exists())

    def test_platform_names_come_from_manifest(self):
        for platforms, expected in [(["linux-x64"], "linux-x64"),
                                    (["windows-x64"], "windows-x64"),
                                    (["windows-arm64"], "windows-arm64"),
                                    (["linux-x64", "windows-x64"], "universal")]:
            with self.subTest(platforms=platforms):
                self.write_manifest(platforms)
                self.build(self.root / expected, expected)

    def test_macos_archive_names_and_receipts_match_manifest_scope(self):
        cases = [(["macos-arm64"], "macos-arm64"),
                 (["macos-x64"], "macos-x64"),
                 (["macos-arm64", "macos-x64"], "macos-universal"),
                 (["macos-x64", "macos-arm64"], "macos-universal")]
        for index, (platforms, expected) in enumerate(cases):
            with self.subTest(platforms=platforms):
                self.write_manifest(platforms)
                archive, receipt = self.build(self.root / str(index), expected)
                self.assertEqual(receipt["platform"], expected)
                self.assertEqual(receipt["archive"]["name"], archive.name)
                with zipfile.ZipFile(archive) as package:
                    self.assertEqual(package.read("blender_manifest.toml"),
                                     (self.addon / "blender_manifest.toml").read_bytes())

    def test_omitted_or_mixed_platforms_keep_universal_name(self):
        cases = [None, ["linux-x64", "macos-arm64"],
                 ["windows-x64", "macos-x64"],
                 ["linux-x64", "windows-x64", "macos-arm64", "macos-x64"]]
        for index, platforms in enumerate(cases):
            with self.subTest(platforms=platforms):
                self.write_manifest(platforms)
                _, receipt = self.build(self.root / str(index))
                self.assertEqual(receipt["platform"], "universal")

    def test_long_and_unicode_paths_with_spaces(self):
        nested = self.addon / ("long module directory " + "x" * 65) / "démo files"
        nested.mkdir(parents=True)
        (nested / "module.py").write_bytes(b"VALUE = 2\n")
        archive, _ = self.build(self.root / "output directory with spaces")
        with zipfile.ZipFile(archive) as package:
            self.assertEqual(package.read((nested / "module.py").relative_to(self.addon).as_posix()),
                             b"VALUE = 2\n")

    def test_output_dir_is_required(self):
        result = self.run_builder()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--output-dir", result.stderr)

    def test_output_inside_source_is_rejected_before_creation(self):
        output = self.source / "generated"
        result = self.run_builder(output)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("source", result.stderr.lower())
        self.assertFalse(output.exists())

    def test_any_git_ancestor_is_forbidden_for_output(self):
        for marker_type in ("directory", "file"):
            with self.subTest(marker_type=marker_type):
                checkout = self.root / marker_type
                checkout.mkdir()
                marker = checkout / ".git"
                if marker_type == "directory":
                    marker.mkdir()
                else:
                    marker.write_text("gitdir: somewhere\n", encoding="utf-8")
                output = checkout / "nested" / "results"
                result = self.run_builder(output)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("git", result.stderr.lower())
                self.assertFalse(output.exists())

    def test_existing_archive_or_receipt_is_never_overwritten(self):
        for suffix in (".zip", ".receipt.json"):
            with self.subTest(suffix=suffix):
                output = self.root / suffix[1:]
                output.mkdir()
                sentinel = output / ("sith-1.2.3-universal" + suffix)
                sentinel.write_bytes(b"preserve existing bytes")
                result = self.run_builder(output)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("exist", result.stderr.lower())
                self.assertEqual(sentinel.read_bytes(), b"preserve existing bytes")
                self.assertEqual(list(output.iterdir()), [sentinel])

    def test_missing_required_files_are_rejected(self):
        for path in (self.source / "LICENSE", self.addon / "__init__.py",
                     self.addon / "blender_manifest.toml"):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                path.unlink()
                output = self.root / ("missing " + path.name)
                result = self.run_builder(output)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(path.name, result.stderr)
                self.assertFalse(output.exists())
                path.write_bytes(original)

    def test_invalid_manifest_cannot_control_archive_path(self):
        for platforms, version in [(["unknown-platform"], "1.2.3"), (None, "../outside"),
                                   ([], "1.2.3"),
                                   ("linux-x64", "1.2.3"),
                                   (["macos-arm64", "macos-arm64"], "1.2.3"),
                                   (["macos-universal"], "1.2.3"),
                                   (["macos-arm64", 1], "1.2.3")]:
            with self.subTest(platforms=platforms, version=version):
                self.write_manifest(platforms, version)
                output = self.root / "invalid"
                result = self.run_builder(output)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("manifest", result.stderr.lower())
                self.assertFalse(output.exists())

    def make_symlink(self, link, target, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"Host cannot create symlinks: {exc}")

    def test_source_symlinks_are_rejected_even_for_ignored_files(self):
        target = self.root / "outside.txt"
        target.write_bytes(b"outside source")
        self.make_symlink(self.addon / "ignored.txt", target)
        output = self.root / "symlink output"
        result = self.run_builder(output)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symlink", result.stderr.lower())
        self.assertFalse(output.exists())

    def test_source_directory_symlink_is_rejected(self):
        link = self.root / "linked source"
        self.make_symlink(link, self.source, directory=True)
        result = self.run_builder(self.root / "linked source output", source=link)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symlink", result.stderr.lower())

    def test_output_symlink_cannot_bypass_git_ancestor_check(self):
        checkout = self.root / "checkout"
        checkout.mkdir()
        (checkout / ".git").mkdir()
        link = self.root / "linked output"
        self.make_symlink(link, checkout, directory=True)
        result = self.run_builder(link / "generated")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("git", result.stderr.lower())
        self.assertFalse((checkout / "generated").exists())

    def test_checkout_output_link_to_external_tree_is_rejected(self):
        for location in ("source", "other checkout"):
            with self.subTest(location=location):
                external = self.root / ("external " + location)
                external.mkdir()
                checkout = self.source if location == "source" else self.root / location
                if location != "source":
                    checkout.mkdir()
                    (checkout / ".git").mkdir()
                link = checkout / "external output link"
                self.make_symlink(link, external, directory=True)
                result = self.run_builder(link / "generated")
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue("source" in result.stderr.lower() or "git" in result.stderr.lower())
                self.assertFalse((external / "generated").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
