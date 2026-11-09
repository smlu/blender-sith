# Local Game-Asset Verification

These opt-in [core](core.py) and [Blender](app.py) scripts scan extracted, legally
obtained assets. They are separate from [synthetic CI tests](../README.md) and
never download, commit or intentionally modify game assets. Input and output
trees must not overlap in either direction. Each processed resource is SHA-256
hashed before and after its check, not every unselected file in the inventory.
Reports contain paths, hashes, measurements, diagnostics and differences, not
packaged copies of the assets; they are not anonymized. Temporary exported
resources are deleted on normal cleanup unless `--keep-exports` is set.
Discovery preserves distinct filename spellings on case-sensitive volumes, even
when running on Windows. Canonical path components are compared without Windows
Path case folding. Physical directory identity joins namespace aliases without
merging differently named hard links or case-distinct files. Alternate Windows
namespaces also receive physical containment checks, so they cannot bypass source
or output boundaries. The same checks cover mounted aliases with a shared path
anchor. Case-only sibling trees are not confused and file symlinks
outside the selected corpus stay excluded.
Directory symlinks are not traversed; skipped external aliases and unsupported
filename suffixes are outside the inventory, not per-resource exception records.
Resolving an internal file symlink does not change the directory used for its
following siblings; aliases deduplicate without omitting or substituting files.
Relative-path matching happens before deduplication, so an unmatched alias cannot
hide a matching target name. Directory enumeration errors abort indexing before
existing reports are replaced; an unreadable subtree is not a complete corpus.

Report filenames must be regular files, not symbolic links or directories. Both
paths are checked before replacing either report. `results.jsonl` is recreated
exclusively and remains incrementally flushed; `summary.json` is written through
a temporary file and atomically replaced. Existing hard-linked reports therefore
cannot cause writes to their source inode. Retained export targets with multiple
hard links are rejected rather than risk modifying an input alias.

## Core

Requires ordinary Python 3.11+ and the NumPy dependency in
[requirements.txt](../requirements.txt), not Blender or fake `bpy` modules.
Install it with `python -m pip install -r tests/requirements.txt` first.

```sh
python tests/batch/core.py --title IJIM --assets /path/to/extracted/assets --output /path/to/build/corpus/ijim-core
```

3DO and KEY go through parse/write/parse, preserving the source version/format and
comparing the declared model/KEY snapshot fields with explicit serialization
tolerances. MAT
decoding is compared against independent raw-byte channel extraction at every
mipmap level and cel. CMP palette entries are compared against the original bytes.
Packed components are normalized by their own full range, `value / (2^bits - 1)`,
not expanded with zero-filled low bits. Maximum colors/alpha therefore reach one.
These core material checks are import/decode references. The Blender runner also
exports and reimports MATs using their source encoding; CMP export is not implemented.

Grim Fandango binary 3DOs are auto-detected and also require byte-identical codec
output, including opaque fields and fixed-name padding. Their `byte_identical`
result is recorded explicitly. Text Grim models retain parsed mesh shadow fields.
For Blender checks, text 2.1 and binary Grim select pixel UV export; text 2.2/2.3
select normalized UV export. The binary codec preserves opaque metadata, while
the Blender import/export path has additional LOD/pivot limitations.
Use `--import-vertex-normals` for Grim text models without an identifying `SHADOW`
field or lighting mode. This opts into authored-normal preservation instead of the
legacy geometric-normal fallback, without guessing the game from resource names.

## Blender

Requires Blender 5.0+ in a separate factory-startup background process. This tool
registers/unregisters the checkout's add-on directly, unlike `tests/run.py`'s
restricted `addon_utils` registration. It deletes objects, meshes, materials,
images, actions and markers in that isolated process; do not run it in a working
interactive scene. NumPy is bundled with Blender. Keep `--python-exit-code 1`
so exceptions propagate to the shell.

```sh
blender --background --factory-startup --python-exit-code 1 --python tests/batch/app.py -- --title IJIM --key-target IJIM --assets /path/to/extracted/assets --output /path/to/build/corpus/ijim-app
```

- 3DO: import into Blender, preserve radius helpers, export in the source version,
  reload, then compare hierarchy, transforms, mesh/face modes, material bindings,
  normals, vertex colors and UVs. It uses the importer's default hierarchy-prefix
  setting, imports colors/radius helpers and exports with `sync_mesh_list=False`;
  it is not the regression suite's full preserve-order/mesh-sync option matrix.
  Vertex/material reindexing, a cyclic polygon
  starting corner and baked pivot translations are allowed; reversed winding,
  changed normals, lost geosets and changes to the compared properties are reported.
  Blender byte-color quantization has a separate `1/255` tolerance. Other geometry
  tolerances are `0.00002`, with `0.002` degree node-rotation tolerance.
  Cyclic corner alignment checks every corner and attribute, including collapsed
  faces; a coincident first vertex cannot hide or fabricate a UV/color difference.
  This is a strict preservation report, not a rendering-correctness verdict.
  Recomputed geometric normals, repaired undersized mesh bounds and omitted extra LODs
  can therefore produce expected differences. The application regression suite
  separately checks correct normals, outward winding and enclosing mesh bounds.
  Authored model `RADIUS` values remain unchanged because they can affect collision
  defaults, independently of the engine's calculated visual enclosure. Do not
  restore invalid source values merely to make this strict report pass.
  Only geoset 0's bound face geometry is compared in detail. This comparator does
  not inventory unused vertices/UVs, unbound meshes, every hierarchy bookkeeping
  field, mesh display names, Shadow or all opaque binary metadata. Dedicated
  synthetic tests cover additional fields; a batch pass is not exhaustive scene
  or binary fidelity.
- KEY: create a synthetic skeleton with the file's joint indices, import, export
  and reload. Compare timing/flags/markers and all represented joints at entry
  times, quarter/midpoint and non-quarter probes, immediately before boundaries and near the final
  playback endpoint. Thresholds are `0.00005` position units and `0.01` degrees.
  This verifies local joint poses, not a game-specific model, animation blending,
  skinning or in-game rendering. Missing animation joints are evaluated as the
  synthetic skeleton's identity pose, not assumed to be harmless.
  Non-quarter probes also catch extra full turns which can alias every quarter
  sample of a long segment. These remain bounded sampling checks, not a proof of
  continuous equality for arbitrary procedural motion.
- MAT: independently decode every source cel/mip, import into Blender, export in
  the source encoding, decode the exported file, and reimport it. RGB565,
  RGBA4444, RGBA1555, RGB24, RGBA32 and indexed layouts are checked explicitly;
  an unsupported layout is reported, never silently converted or counted as a pass.
  This retains encoding/channel precision, not raw source bytes, channel-mask
  arrangement or palette-index identity; the source layout selector checks bit
  counts, and pixel comparisons enforce the represented colors.
  Every base-level alpha/visible RGB value must survive the file round trip.
  Transparent indexed RGB may change when transparency is reassigned to palette
  index zero; it is ignored only where alpha is zero. Palette-color records are
  expanded to texture cels and reported as such, not claimed to be byte-identical.
  Standard output regenerates a full mip chain; Grim type-3 output stores only the
  base images. Each exported mip is independently decoded and compared with an
  area-filter reference and format quantization. Original artist-authored lower
  mips are not copied or expected to match regenerated ones.
  Cels are resolved through their material's image bindings. Blender byte-image
  comparisons allow half an 8-bit step (`0.5/255`, plus floating-point tolerance)
  for imported 5/6-bit channels; source-to-export comparisons retain the source
  channel precision. Indexed output uses the supplied/discovered CMP, not an
  inferred room-specific palette. This is file/image verification, not a native
  engine rendering test.
  The adapter in [material.py](material.py) calls Blender's real preparation and
  import paths. The core runner checks MAT decoding only; it does not perform this
  Blender round trip or validate the writer merely by reusing its own decoder.
- CMP: verify palette data, as in the core script.

## Options And Results

Both entry points use the same [argument parser](common.py). Put script arguments
after Blender's `--`. Choices are case-sensitive; the title is an arbitrary report
label, not a game selector.

| Argument | Default And Behavior |
| --- | --- |
| `-h`, `--help` | Show help and exit. |
| `--assets PATH` | Required directory; repeat for multiple extracted roots. Overlapping roots/aliases deduplicate discovered files. |
| `--output PATH` | Required report/export directory; must neither contain nor be contained by any input root, including physical aliases. |
| `--title TEXT` | Required report label; never enables game-specific validation on its own. |
| `--formats FORMAT [FORMAT ...]` | Defaults to all of `3do key mat cmp`; one or more of those lowercase values. Inventory/selection is restricted to the requested formats. |
| `--cmp PATH` | No explicit palette by default; otherwise use this palette. Automatic selection uses the first discovered `dflt.cmp`, even outside a format/path filter, and records its path. |
| `--limit N` | `0`: all matching files; positive values cap each format independently; negative values are parser errors. |
| `--match GLOB` | `*`: all relative paths; case-insensitive matching uses `/` separators. Quote patterns, for example `--match '*whip*'`. |
| `--keep-exports` | Off by default. Retain generated files under `OUTPUT/exports/ROOT_INDEX/relative/path`; otherwise use a temporary working directory under output. Decode-only checks create no export. |
| `--import-vertex-normals` | Off by default. Blender-only opt-in for authored normals on ambiguous legacy text 3DOs; accepted but unused by core checks. Explicit Grim/binary detection already preserves authored normals. |
| `--mat-target SOURCE\|GRIM` | `SOURCE`: preserve the source MAT family; `GRIM`: request base-only indexed type-3 output in Blender. Accepted but unused by core checks. |
| `--key-target IJIM\|JKDF2\|MOTS\|GRIM\|CUSTOM` | `CUSTOM`: generic codec limits, with binary-Grim handling described below. Other values enable the named target's validation; only the Blender runner selects export format from this target. |

The boolean switches are opt-in `store_true` flags, with no `--no-*` counterparts.
There are no mutually exclusive argument groups: formats can be combined,
`--match` and `--limit` compose, and both target options can be supplied together.
There is no CLI for recovery, relaxed KEY frame-zero import, mipmap disabling,
hierarchy-prefix/mesh-sync matrices or exception allowlists.

Automatic batch palette selection recognizes `dflt.cmp`, not Grim's
`dfltcmp.cmp`; pass `--cmp` explicitly for that name or costume/room palettes.
This differs from application resource lookup's additional fallback. An indexed
MAT without a selected palette is `unsupported`, not a placeholder-based pass.
Neither a title nor a level name infers the correct palette.

### Five-Game Scope

| Assets | Relevant Selection And Limitations |
| --- | --- |
| IJIM | `--key-target IJIM`; text 2.2/2.3 and represented MAT layouts are checked from the supplied files. |
| JKDF2 | `--key-target JKDF2`; legacy text 2.1/pixel UVs, indexed MATs and CMPs use the shared paths. |
| MOTS | `--key-target MOTS`; the same shared codecs, with MOTS KEY limits. |
| Grim Fandango | `--key-target GRIM` for binary KEY output in Blender; `--mat-target GRIM --cmp /path/to/palette.cmp` for Grim MAT checks, including ordinary type-2 sources. MODL/FYEK detection is content-based. |
| DroidWorks | Use an appropriate report title and explicit CMP. There is no DroidWorks KEY target; `CUSTOM` checks shared text contracts without title-specific limits. Shared codec support is not a dedicated DroidWorks corpus or runtime certification. |

Supply each game's extracted assets separately when reporting title coverage.
These scripts do not extract archives, discover missing resources beyond the
four supported suffixes, run games, or establish that all five corpora passed.

Use `--mat-target GRIM` for Grim MAT export checks, including originals with a
type-2 header. It selects the same base-only, indexed type-3 output as the Grim
3DO exporter. This requires indexed source encoding: packed-color inputs fail
rather than being automatically converted to indexed output. The default `SOURCE`
preserves a source's type-2/type-3 family; it
cannot infer a game from an ordinary type-2 indexed header. The core runner only
decodes MAT files, so this option affects Blender checks only.

`--key-target IJIM`, `JKDF2` or `MOTS` enables engine-specific KEY export count and
name-buffer checks in both runners: 64 joints and respectively 16/8/8 markers,
with 63/31/31-character names. The default `CUSTOM` checks codec/token rules
without imposing a specific engine's limits; the report title alone does not
select a target. `CUSTOM` is the interactive **Generic** option.
Blender's interactive KEY export defaults to IJIM independently.

FYEK binary KEY input is auto-detected. Core checks retain binary output and
require byte-identical serialization, including null records and unused markers.
With the default generic corpus target, binary application checks select Grim
output automatically and compare playback using Grim's global interpolation rule.
The `GRIM` key target explicitly selects binary validation and, in Blender, output.
Core always retains the input KEY's text/binary format even with an explicit
target. Grim has eight marker slots and fixed binary resource/joint-name fields.
A synthetic skeleton verifies the clip, not in-game blending with a particular costume.
Core text output and Blender output write markers chronologically, with stable
ordering at equal times; core binary checks instead retain the original bytes.
Chronological comparisons preserve every marker's time/type
and tie order, and record `source_marker_order_corrected` when a source file was
originally out of order. They do not sort both inputs and hide bad exported order.

### Accounting And Failures

`summary.json` reports `inventory` (after format/path filtering, before the limit),
`selected` (per format after the limit), `processed`, `completed`, status `counts`
and `by_format`, plus roots, title, selected palette and elapsed time. It does not
store all CLI settings or a release/source revision; retain the invocation and
checkout identity alongside reports when publishing evidence.

`full_corpus` means the selected run completed, selected every filtered file and
used `--match '*'`. It is relative to the supplied roots and `--formats`, not all
four formats or a complete game installation. Any non-`*` match makes it false;
a positive limit makes it false only if files were actually omitted. Neither
`completed` nor `full_corpus` means all checks passed.

`results.jsonl` flushes each processed record with source path/relative name,
format, source hash, `source_unchanged`, time, diagnostics and operation-specific
details. Handler comparison differences produce `mismatch`; explicit unimplemented
requirements produce `unsupported`; other handler exceptions (including NumPy
assertions) produce `error` with a traceback; otherwise the status is `pass`.
A changed source hash forces `error`. Captured stdout/stderr is truncated to
8,000 characters and comparison diagnostics are bounded, not a complete transcript
of every possible difference.
Parsing/comparison failures inside that boundary are recorded and remaining
resources continue. Missing palettes, malformed sources and known limitations
are not silently skipped or allowlisted as passes. Diagnose and report their
counts separately without changing the original assets or removing their records.
Unsafe output paths abort the batch instead of being treated as ordinary asset
errors. Indexing, directory creation, source hashing and report I/O can also
abort outside the per-resource handler; do not assume an exception record exists
for every selected file after an interrupted run. Some early failures happen
before either report is replaced, leaving old reports in place. Check `completed`,
selected/processed totals and the process exit status against the current run.
Hash equality is a selected-file preservation check, not a whole-tree audit or
a guarantee against concurrent source changes between checks.

Headerless or structurally incomplete KEY/3DO files are errors, not
successful empty resources. 3DO section order, duplicates and negative counts
are validated before a core round trip can pass. Errors, mismatches and
unsupported resources cause a nonzero exit status, never a passing or empty run.
Some original resources or existing importer limitations may therefore fail:
inspect their records rather than assuming every difference is a parser bug.
Full-corpus comparisons are useful regression evidence, not proof of byte-identical
exports or compatibility with every engine's runtime behavior.
