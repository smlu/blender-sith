# Reproducible extension packages

The optional Python 3.11+ packager builds an installable extension ZIP and a
portable JSON receipt. It requires no third-party dependencies or Git commands.
Blender's official builder and validator remain the compatibility authority;
this script adds deterministic bytes and per-file provenance.

```sh
python3 scripts/build_extension.py --output-dir /external/sith-packages
```

```powershell
python scripts/build_extension.py --output-dir C:\builds\sith-packages
```

Use `--source-dir` to package another source root containing `sith` and `LICENSE`.
The output must be outside the source and every Git checkout. Both lexical and
resolved routes are checked. Source symlinks/junctions are rejected. Existing
archives and receipts are never overwritten.

Archive names come from the extension manifest's ID, version and optional
platform list. Upstream's pure-Python manifest remains unrestricted. Omitting
`platforms` produces a `-universal.zip` name; an explicitly empty list is invalid.
Platform-specific fixture support does not impose platform restrictions on the
distributed extension.

The ZIP places `blender_manifest.toml`, `__init__.py`, source subpackages and the
original `LICENSE` at its root. Membership allows add-on Python/TOML files and
the license. Bytecode/cache content is ignored; unfamiliar resource files cause
an error so future icons, presets or schemas cannot silently disappear. Such
resources need an explicit allowlist update. Manifest `[build]` path/exclusion
semantics are not implemented by this helper.

Members are sorted with fixed 1980 timestamps, regular-file 0644 permissions,
stored compression and CRLF-to-LF normalization. The `.receipt.json` records
source-relative paths, raw and packaged sizes/hashes, and the final ZIP size and
SHA-256. It omits absolute machine paths. A receipt establishes byte provenance,
not source trust or runtime correctness.

Validate the exact resulting ZIP with an explicitly selected Blender executable:

```sh
/opt/blender/blender --background --factory-startup --offline-mode \
  --command extension validate /external/sith-packages/sith-VERSION-universal.zip
```

Consult [Blender's extension command reference](https://docs.blender.org/manual/en/latest/advanced/command_line/extension_arguments.html).
Packaging does not install the extension, run Blender, or publish a release.

Run the standard-library tests with temporary storage outside Git:

```sh
python -B -m unittest discover -s tests -p test_build_extension.py -v
```

They cover member layout, normalization, deterministic bytes, receipts, manifest
names, invalid inputs, unknown resources, no-overwrite behavior and source/output
link rejection. Link fixtures use explicit capability skips on unsupported hosts.
