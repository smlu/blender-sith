# Repeatable extension packages

Use the existing Python 3.11+ packager from any working directory:

```sh
python -B scripts/make_addon.py --output /external/sith-packages/sith.zip
```

```powershell
python -B scripts/make_addon.py --output C:\builds\sith-packages\sith.zip
```

The shell wrapper `scripts/make_addon.sh` uses the same implementation. Blender's
own `extension build` remains an alternative; there is no separate reproducible
packager. The script neither installs nor publishes the extension.

## Package membership

In a Git checkout, the package contains existing regular files tracked in the
index below `sith/`, subject to the existing exclusions. This includes newly
staged files and current working-tree edits to tracked files; it does not require
a clean checkout or package committed blobs instead. **An untracked scratch
`.py` is excluded.** Add an intended new module or resource to the index before
packaging. Both `__init__.py` and `blender_manifest.toml` must be tracked.
Directories with no tracked descendants are pruned before traversal. Missing or
deleted non-required tracked files retain the existing skip behaviour.

The nearest ancestor `.git` directory or file identifies a checkout, including
linked worktrees and submodules. The read-only `git ls-files` query has a
15-second timeout. If Git is unavailable, its index cannot be read, or its normal
repository trust checks fail, packaging stops without replacing an old archive.
It does not silently fall back to including untracked files. No Git configuration
is changed by the packager.

A clean downloaded/extracted source archive without a `.git` ancestor uses the
existing filesystem scan and needs only Python's standard library, **not Git**.
Without an index there is no tracked/untracked distinction, so an ordinary
scratch `.py` in such a source tree will be included. Keep archive-build sources
clean and inspect ZIP membership. The fallback is automatic; do not remove a
checkout's `.git` metadata merely to bypass a membership failure.

Both routes retain arbitrary legitimate resources such as icons or schemas, and
retain the same exclusion rules: `__pycache__`, `.pytest_cache`, `.git`, `.vs` and
`.vscode` directories; `__test.py`, `.directory` and `.DS_Store`; bytecode and
`.blend*` files. Symlinks and Windows reparse directories (including junctions)
are excluded, so directory aliases cannot pull outside content into the ZIP.
This helper does not
implement Blender manifest `[build]` path/exclusion semantics. Its archive layout
is the contents of `sith/` at ZIP root, as before; it does not inject other
repository files.

## Determinism and failure handling

Members are sorted by relative path with the existing case-insensitive ordering
and a case-sensitive tie-break. Every entry has timestamp `1980-01-01 00:00:00`,
Unix regular-file permissions `0644`, and DEFLATE level 9. Source timestamps,
permissions and filesystem enumeration order therefore do not affect the ZIP.
Source bytes are copied unchanged, including line endings and binary resources.
Different Git line-ending configurations can produce different input bytes;
compression output can also differ between zlib implementations. Byte identity
is promised for the same member paths/bytes and compression implementation, not
across arbitrary source checkouts or toolchain versions.

Sources are never modified. Output must remain outside the add-on source tree;
use a new external output directory for validation artifacts. Source-scan errors
and archive-write failures leave an existing destination intact and clean up the
temporary ZIP. A successful build atomically replaces the destination, preserving
the existing utility's behaviour. Record a SHA-256 separately if required; this
change adds no new receipt format.

Run the packaging tests with temporary storage outside a checkout:

```sh
python -B -m unittest discover -s tests/core -p test_packaging.py -v
```

The tests cover repeat bytes after timestamp/permission changes, fixed archive
metadata, unchanged source/resource bytes, checkout membership and untracked
scratch exclusion, source-archive operation without Git, failed/timed-out index
queries, existing exclusions, and atomic failure handling. The real checkout
fixtures skip explicitly if Git is absent; source-archive tests still run.

Validate the exact result separately with the intended Blender installation:

```sh
/opt/blender/blender --background --factory-startup --offline-mode \
  --command extension validate /external/sith-packages/sith.zip
```

A repeatable ZIP is not evidence of Blender validation or game compatibility.
