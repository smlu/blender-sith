"""Build an installable Blender extension ZIP using only Python's standard library."""
import argparse
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRS = {'__pycache__', '.pytest_cache', '.git', '.vs', '.vscode'}
EXCLUDED_FILES = {'__test.py', '.directory', '.DS_Store'}
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def _include(relative):
    return (not any(part in EXCLUDED_DIRS for part in relative.parts[:-1])
            and relative.name not in EXCLUDED_FILES
            and relative.suffix.lower() not in {'.pyc', '.pyo'}
            and not relative.suffix.lower().startswith('.blend'))


def _is_within_source(path, source):
    if path.parts[:len(source.parts)] == source.parts:
        return True
    # Extended Windows namespaces and mounted aliases can name the same tree
    # without sharing path components. Missing output leaves are expected.
    for ancestor in (path, *path.parents):
        try:
            if os.path.samefile(ancestor, source):
                return True
        except OSError:
            continue
    return False


def _tracked_files(source):
    """Use index membership in checkouts; source archives need no Git command."""
    root = next((parent for parent in (source, *source.parents)
                 if (parent / '.git').exists()), None)
    if root is None:
        return None
    try:
        result = subprocess.run(
            ['git', '--literal-pathspecs', '-C', str(root), 'ls-files',
             '--cached', '--full-name', '-z', '--', source.relative_to(root).as_posix()],
            capture_output=True, check=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError('Cannot read Git package membership; make Git available in this '
                         'checkout or build from a clean source archive outside a checkout') from error
    return {root / os.fsdecode(name) for name in result.stdout.split(b'\0') if name}


def _linked_directory(path):
    # os.walk(followlinks=False) does not exclude Windows directory junctions.
    # lstat's reparse attribute is available on Python 3.11 too (is_junction is not).
    details = path.lstat()
    return (stat.S_ISLNK(details.st_mode)
            or bool(getattr(details, 'st_file_attributes', 0) & 0x400))


def create_package(source, destination):
    """Package source without modifying it; replace an old ZIP only on success."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_dir():
        raise ValueError(f'Add-on source directory does not exist: {source}')
    if _is_within_source(destination, source):
        raise ValueError('Package output must be outside the add-on source directory')
    for name in ('__init__.py', 'blender_manifest.toml'):
        required = source / name
        if not required.is_file() or required.is_symlink():
            raise ValueError(f'Missing regular package file: {name}')
    with (source / 'blender_manifest.toml').open('rb') as stream:
        manifest = tomllib.load(stream)
    if not isinstance(manifest.get('id'), str) or not manifest['id']:
        raise ValueError('Extension manifest must declare its id')
    tracked = _tracked_files(source)
    tracked_dirs = None
    if tracked is not None:
        for name in ('__init__.py', 'blender_manifest.toml'):
            if source / name not in tracked:
                raise ValueError(f'Required package file is not tracked: {name}')
        tracked_dirs = {parent for path in tracked for parent in path.parents
                        if parent.is_relative_to(source)}

    def on_walk_error(error):
        # An incomplete source scan must not replace a valid old archive.
        raise error

    files = []
    for parent, directories, names in os.walk(source, followlinks=False, onerror=on_walk_error):
        directories[:] = [name for name in directories
                          if name not in EXCLUDED_DIRS
                          and (tracked_dirs is None or Path(parent) / name in tracked_dirs)
                          and not _linked_directory(Path(parent) / name)]
        for name in names:
            path = Path(parent) / name
            if (path.is_file() and not path.is_symlink() and _include(path.relative_to(source))
                    and (tracked is None or path in tracked)):
                files.append(path)
    files.sort(key=lambda path: (path.relative_to(source).as_posix().casefold(),
                                 path.relative_to(source).as_posix()))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix='.sith-package-', suffix='.zip',
                                     dir=destination.parent, delete=False) as stream:
        temporary = Path(stream.name)
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for path in files:
                info = zipfile.ZipInfo(path.relative_to(source).as_posix(), ZIP_TIMESTAMP)
                info.create_system = 3  # Consistent Unix regular-file metadata on every host.
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED,
                                 compresslevel=9)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/sith.zip',
                        help='Output ZIP path (default: repository build/sith.zip)')
    options = parser.parse_args()
    try:
        path = create_package(ROOT / 'sith', options.output)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        parser.exit(1, f'Packaging failed: {error}\n')
    print(f'Created {path}')


if __name__ == '__main__':
    main()
