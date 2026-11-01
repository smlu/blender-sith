"""Shared reporting, read-only corpus discovery and semantic comparisons."""
import argparse
from collections import Counter, defaultdict
import contextlib
import fnmatch
import hashlib
import io
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback


class UnsupportedResource(Exception):
    """A required format/application feature is not implemented, not a pass."""


def arguments(description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('--assets', type=Path, action='append', required=True,
                        help='Extracted asset root; repeat for additional roots')
    parser.add_argument('--output', type=Path, required=True,
                        help='Reports and optional exports, outside all input roots')
    parser.add_argument('--title', required=True, help='Report label, e.g. IJIM, JKDF2, MOTS')
    parser.add_argument('--formats', nargs='+', choices=('3do', 'key', 'mat', 'cmp'),
                        default=['3do', 'key', 'mat', 'cmp'])
    parser.add_argument('--cmp', type=Path, help='Palette for indexed MATs; otherwise find dflt.cmp')
    parser.add_argument('--limit', type=int, default=0, help='Per-format limit; 0 checks every file')
    parser.add_argument('--match', default='*', help='Case-insensitive relative-path glob')
    parser.add_argument('--keep-exports', action='store_true')
    parser.add_argument('--key-target', choices=('IJIM', 'JKDF2', 'MOTS', 'CUSTOM'), default='CUSTOM',
                        help='Validate KEY exports against a target engine (default: CUSTOM codec-only limits)')
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    options = parser.parse_args(argv)
    if options.limit < 0:
        parser.error('--limit cannot be negative')
    return options


def _is_within_resolved(path, root):
    # Windows Path equality folds case even on case-sensitive shares. Resolve
    # aliases first, then compare the actual component spelling, not Path objects.
    if path.parts[:len(root.parts)] == root.parts:
        return True
    # Alternate namespaces, drives or mounted aliases can name the same tree.
    # Missing output leaves are harmless: an existing ancestor identifies it.
    for ancestor in (path, *path.parents):
        try:
            if os.path.samefile(ancestor, root):
                return True
        except OSError:
            continue
    return False


def validate_paths(roots, output):
    roots = [root.resolve() for root in roots]
    output = output.resolve()
    for root in roots:
        if not root.is_dir():
            raise ValueError(f'Asset root is not a directory: {root}')
        if _is_within_resolved(output, root) or _is_within_resolved(root, output):
            raise ValueError('Output and source asset trees must not overlap')
    return roots, output


def _raise_walk_error(error):
    # os.walk otherwise silently skips inaccessible or vanished directories.
    raise error


def discover(roots, formats, pattern='*'):
    found = []
    seen = set()
    parent_ids = {}
    for index, root in enumerate(roots):
        root = root.resolve()
        for walk_parent, directories, names in os.walk(root, followlinks=False, onerror=_raise_walk_error):
            directories.sort(key=lambda value: (value.casefold(), value))
            for name in sorted(names, key=lambda value: (value.casefold(), value)):
                path = Path(walk_parent) / name
                if path.suffix.lower().lstrip('.') not in formats or not path.is_file():
                    continue
                resolved = path.resolve()
                # Do not follow a resource-file symlink outside the selected corpus.
                if not _is_within_resolved(resolved, root):
                    continue
                # Keep the resolved cache key separate from the walk directory.
                parent_key = str(resolved.parent)
                if parent_key not in parent_ids:
                    info = resolved.parent.stat()
                    parent_ids[parent_key] = (info.st_dev, info.st_ino) if info.st_ino else parent_key
                # Parent identity joins namespace aliases; exact leaf spelling
                # retains distinct case variants and differently named hard links.
                identity = (parent_ids[parent_key], resolved.name)
                if identity in seen:
                    continue
                relative = path.relative_to(root)
                if not fnmatch.fnmatchcase(relative.as_posix().casefold(), pattern.casefold()):
                    continue
                found.append((index, relative, resolved))
                seen.add(identity)
    return found


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def differences(expected, actual, label='', atol=1e-6, limit=20):
    """Compare declared fields, allowing only explicit serialization precision."""
    result = []
    def visit(a, b, path):
        if len(result) >= limit:
            return
        if isinstance(a, dict) and isinstance(b, dict):
            if a.keys() != b.keys():
                result.append(f'{path}: different fields')
                return
            for name in a:
                visit(a[name], b[name], f'{path}.{name}')
        elif isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
            if len(a) != len(b):
                result.append(f'{path}: length {len(a)} != {len(b)}')
                return
            for index, (av, bv) in enumerate(zip(a, b)):
                visit(av, bv, f'{path}[{index}]')
        elif isinstance(a, float) or isinstance(b, float):
            if not isinstance(a, (int, float)) or not isinstance(b, (int, float)) or not math.isclose(a, b, rel_tol=1e-9, abs_tol=atol):
                result.append(f'{path}: {a!r} != {b!r}')
        elif a != b:
            result.append(f'{path}: {a!r} != {b!r}')
    visit(expected, actual, label)
    return result


def fields(value, names):
    return {name: getattr(value, name) for name in names.split()}


def model_snapshot(model):
    result = fields(model, 'radius insertOffset materials')
    result['nodes'] = [fields(node, 'idx name flags type meshIdx parentIdx firstChildIdx siblingIdx numChildren position rotation pivot')
                       for node in model.meshHierarchy]
    result['geosets'] = []
    for geoset in model.geosets:
        meshes = []
        for mesh in geoset.meshes:
            data = fields(mesh, 'idx name radius geometryMode lightMode textureMode vertices vertexColors uvs normals')
            data['faces'] = [fields(face, 'materialIdx type geometryMode lightMode textureMode color vertexIdxs uvIdxs normal')
                             for face in mesh.faces]
            meshes.append(data)
        result['geosets'].append(meshes)
    return result


def key_snapshot(key):
    result = fields(key, 'flags nodeTypes numFrames fps numJoints')
    result['markers'] = [(marker.frame, int(marker.type)) for marker in key.markers]
    result['nodes'] = []
    for node in key.nodes:
        data = fields(node, 'idx meshName')
        data['entries'] = [fields(entry, 'frame flags position orientation deltaPosition deltaRotation') for entry in node.keyframes]
        result['nodes'].append(data)
    return result


def _validate_report_path(path):
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError(f'Unsafe batch report path: {path}; expected a regular file, not a link or directory')


def _open_results(path):
    # Unlink the directory entry rather than truncate its inode: an existing
    # hard link could alias an input asset. Exclusive creation cannot follow a
    # symlink placed at this name between unlink and open.
    _validate_report_path(path)
    path.unlink(missing_ok=True)
    return path.open('x', encoding='utf-8')


def _write_summary(path, summary):
    _validate_report_path(path)
    stream = tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                         prefix='.summary-', suffix='.tmp',
                                         dir=path.parent, delete=False)
    temporary = Path(stream.name)
    try:
        with stream:
            json.dump(summary, stream, indent=2)
            stream.write('\n')
        # Closing first also permits replacement on Windows. Replace the entry
        # itself, never write through an existing hard link to another file.
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def run(options, handler):
    roots, output = validate_paths(options.assets, options.output)
    print(f'{options.title}: indexing extracted resource trees', flush=True)
    all_files = discover(roots, ('3do', 'key', 'mat', 'cmp'))
    # Match logical input paths before alias deduplication. An earlier alias
    # excluded by --match must not hide the canonical name the user requested.
    files = (all_files if options.match == '*' else discover(roots, ('3do', 'key', 'mat', 'cmp'), options.match))
    files = [item for item in files if item[2].suffix.lower()[1:] in options.formats]
    if not files:
        raise ValueError('No matching resources found; an empty run is not a pass')
    inventory = Counter(path.suffix.lower()[1:] for _, _, path in files)
    selected = []
    counts = Counter()
    for item in files:
        extension = item[2].suffix.lower()[1:]
        if not options.limit or counts[extension] < options.limit:
            selected.append(item)
            counts[extension] += 1
    output.mkdir(parents=True, exist_ok=True)
    results_path, summary_path = output / 'results.jsonl', output / 'summary.json'
    # Check both paths before replacing either report or processing any input.
    for path in (results_path, summary_path):
        _validate_report_path(path)
    palette_paths = [path for _, _, path in all_files if path.name.lower() == 'dflt.cmp']
    options.palette_path = options.cmp or (palette_paths[0] if palette_paths else None)
    options.mat_dirs = sorted({str(path.parent) for _, _, path in all_files if path.suffix.lower() == '.mat'})
    records = []
    started = time.monotonic()
    complete = False
    with tempfile.TemporaryDirectory(prefix='working-', dir=output) as working:
        with _open_results(results_path) as report:
            try:
                for index, (root_index, relative, path) in enumerate(selected, 1):
                    record = {'source': str(path), 'relative': relative.as_posix(),
                              'format': path.suffix.lower()[1:], 'status': 'error'}
                    before = digest(path)
                    record['source_sha256'] = before
                    target = (output / 'exports' if options.keep_exports else Path(working)) / str(root_index) / relative
                    resolved_target = target.resolve()
                    if not _is_within_resolved(resolved_target, output) or any(_is_within_resolved(resolved_target, root) for root in roots):
                        raise ValueError('Export target escapes the output tree, possibly through a symlink')
                    if target.is_file() and target.stat().st_nlink > 1:
                        raise ValueError(f'Unsafe multiply-linked export target: {target}')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    messages = io.StringIO()
                    tick = time.monotonic()
                    try:
                        with contextlib.redirect_stdout(messages), contextlib.redirect_stderr(messages):
                            details = handler(path, target, options)
                        record.update(details)
                        record['status'] = 'mismatch' if details.get('differences') else 'pass'
                    except UnsupportedResource as error:
                        record.update(status='unsupported', error=str(error))
                    except Exception as error:
                        record.update(error=f'{type(error).__name__}: {error}', traceback=traceback.format_exc())
                    finally:
                        record['source_unchanged'] = digest(path) == before
                        if not record['source_unchanged']:
                            record.update(status='error', error='Source file changed during verification')
                        record['seconds'] = round(time.monotonic() - tick, 6)
                        if messages.getvalue():
                            record['messages'] = messages.getvalue()[:8000]
                        records.append(record)
                        report.write(json.dumps(record, allow_nan=False) + '\n')
                        report.flush()
                    if index % 25 == 0 or index == len(selected):
                        print(f'{options.title}: {index}/{len(selected)} {dict(Counter(r["status"] for r in records))}', flush=True)
                complete = True
            finally:
                by_format = defaultdict(Counter)
                for record in records:
                    by_format[record['format']][record['status']] += 1
                summary = {'title': options.title, 'roots': [str(root) for root in roots],
                           'palette': str(options.palette_path) if options.palette_path else None,
                           'inventory': dict(inventory), 'selected': dict(counts),
                           'processed': len(records), 'completed': complete,
                           'full_corpus': complete and len(selected) == len(files) and options.match == '*',
                           'counts': dict(Counter(record['status'] for record in records)),
                           'by_format': dict(by_format), 'seconds': round(time.monotonic() - started, 3)}
                _write_summary(summary_path, summary)
    print(json.dumps(summary, indent=2), flush=True)
    return 0 if complete and all(record['status'] == 'pass' for record in records) else 1
