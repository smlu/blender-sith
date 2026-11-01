#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build a deterministic Blender extension ZIP and provenance receipt (Python 3.11+).

Run with --output-dir pointing outside every Git checkout. The default source is
this script's repository; --source-dir selects another explicit source tree.
Only sith/**/*.py, sith/**/*.toml and the original LICENSE are included. Unknown
extension resources fail the build so future assets cannot silently disappear.
Python bytecode/cache directories are ignored. Text bytes are normalized from
CRLF to LF; the receipt records both hashes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tomllib
import zipfile


def _is_link(path: Path) -> bool:
    """Include Windows junctions, which Python 3.11 does not call symlinks."""
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _source_root(path: Path) -> Path:
    absolute = Path(os.path.abspath(path))
    for part in (absolute, *absolute.parents):
        if _is_link(part):
            raise ValueError(f"Source symlink or junction is forbidden: {part}")
    if not absolute.is_dir():
        raise ValueError(f"Source must be a directory: {absolute}")
    return absolute.resolve()


def _output_root(path: Path, source: Path) -> Path:
    lexical = Path(os.path.abspath(path))
    output = path.resolve()
    # A checkout link to external storage still exposes generated files to Git.
    # Check the supplied route as well as the physical destination.
    for candidate in (lexical, output):
        if candidate == source or source in candidate.parents:
            raise ValueError("Output directory must be outside the source tree")
        for ancestor in (candidate, *candidate.parents):
            if os.path.lexists(ancestor / ".git"):
                raise ValueError(f"Output directory has a Git ancestor: {ancestor}")
    return output


def _source_files(source: Path) -> list[tuple[str, Path]]:
    addon = source / "sith"
    required = (source / "LICENSE", addon, addon / "blender_manifest.toml", addon / "__init__.py")
    for path in required:
        if not os.path.lexists(path):
            raise ValueError(f"Missing required source: {path.name}")
        if _is_link(path):
            raise ValueError(f"Source symlink or junction is forbidden: {path}")
        if (path == addon and not path.is_dir()) or (path != addon and not path.is_file()):
            raise ValueError(f"Invalid required source: {path.name}")

    files = [("LICENSE", source / "LICENSE")]
    for directory, dirs, names in os.walk(addon, followlinks=False):
        for name in dirs + names:
            path = Path(directory) / name
            if _is_link(path):
                raise ValueError(f"Source symlink or junction is forbidden: {path}")
        dirs[:] = sorted(name for name in dirs if name != "__pycache__")
        for name in names:
            path = Path(directory) / name
            if path.suffix in (".py", ".toml"):
                if not path.is_file():
                    raise ValueError(f"Source is not a regular file: {path}")
                files.append((path.relative_to(addon).as_posix(), path))
            elif path.suffix not in (".pyc", ".pyo"):
                raise ValueError(f"Unclassified extension resource: {path.relative_to(addon)}; update the explicit package allowlist")
    return sorted(files)


def _manifest_identity(data: bytes) -> tuple[str, str]:
    manifest = tomllib.loads(data.decode("utf-8"))
    if manifest.get("id") != "sith":
        raise ValueError("Manifest id must be 'sith'")
    version = manifest.get("version")
    if not isinstance(version, str) or not re.fullmatch(
        r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?", version
    ):
        raise ValueError("Manifest version must be a safe semantic version")
    platforms = manifest.get("platforms", [])
    macos_platforms = {"macos-arm64", "macos-x64"}
    supported = {"linux-x64", "windows-x64", "windows-arm64"} | macos_platforms
    if (not isinstance(platforms, list) or ("platforms" in manifest and not platforms) or
            any(not isinstance(item, str) or item not in supported for item in platforms) or
            len(set(platforms)) != len(platforms)):
        raise ValueError("Manifest platforms must be unique values from: " + ", ".join(sorted(supported)))
    if len(platforms) == 1:
        platform = platforms[0]
    elif set(platforms) == macos_platforms:
        platform = "macos-universal"
    else:
        platform = "universal"
    return version, platform


def build_extension(source_dir: Path, output_dir: Path) -> tuple[Path, Path]:
    source = _source_root(source_dir)
    output = _output_root(output_dir, source)
    records = []
    payloads = []
    for archive_path, path in _source_files(source):
        raw = path.read_bytes()
        packaged = raw.replace(b"\r\n", b"\n")
        payloads.append((archive_path, packaged))
        records.append({
            "source_path": path.relative_to(source).as_posix(),
            "archive_path": archive_path,
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "packaged_sha256": hashlib.sha256(packaged).hexdigest(),
            "raw_size": len(raw),
            "packaged_size": len(packaged),
        })
    version, platform = _manifest_identity(dict(payloads)["blender_manifest.toml"])
    stem = f"sith-{version}-{platform}"
    archive = output / (stem + ".zip")
    receipt = output / (stem + ".receipt.json")
    for target in (archive, receipt):
        if os.path.lexists(target):
            raise FileExistsError(f"Output already exists: {target}")

    output.mkdir(parents=True, exist_ok=True)
    # Exclusive creation also prevents a concurrent invocation from overwriting.
    with archive.open("xb") as archive_file:
        with zipfile.ZipFile(archive_file, "w", compression=zipfile.ZIP_STORED) as package:
            for name, data in payloads:
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                info.compress_type = zipfile.ZIP_STORED
                package.writestr(info, data)

    archive_bytes = archive.read_bytes()
    document = {
        "schema_version": 1,
        "version": version,
        "platform": platform,
        "normalization": "CRLF to LF",
        "archive": {
            "name": archive.name,
            "sha256": hashlib.sha256(archive_bytes).hexdigest(),
            "size": len(archive_bytes),
        },
        "files": records,
    }
    with receipt.open("x", encoding="utf-8", newline="\n") as receipt_file:
        receipt_file.write(json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return archive, receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        archive, receipt = build_extension(args.source_dir, args.output_dir)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Build failed: {exc}\n")
    print(json.dumps({"archive": str(archive), "receipt": str(receipt)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
