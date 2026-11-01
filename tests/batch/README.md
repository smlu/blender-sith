# Local Game-Asset Verification

These opt-in scripts scan extracted, legally obtained assets. They are separate
from CI and never download, commit or modify game assets. The output directory
must be outside the input trees. Every resource is hashed before and after its
check. Reports contain filenames, hashes, measurements and differences, not asset
contents. Temporary exported resources are deleted unless `--keep-exports` is set.
Discovery preserves distinct filename spellings on case-sensitive volumes, even
when running on Windows. Canonical path components are compared without Windows
Path case folding. Physical directory identity joins namespace aliases without
merging differently named hard links or case-distinct files. Alternate Windows
namespaces also receive physical containment checks, so they cannot bypass source
or output boundaries. The same checks cover mounted aliases with a shared path
anchor. Case-only sibling trees are not confused and file symlinks
outside the selected corpus stay excluded.
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

```sh
python tests/batch/core.py --title IJIM --assets /path/to/extracted/assets --output /path/to/build/corpus/ijim-core
```

3DO and KEY go through parse/write/parse, preserving the source version and
comparing every represented field with explicit serialization tolerances. MAT
decoding is compared against independent raw-byte channel extraction at every
mipmap level and cel. CMP palette entries are compared against the original bytes.
Packed components are normalized by their own full range, `value / (2^bits - 1)`,
not expanded with zero-filled low bits. Maximum colors/alpha therefore reach one.
There is no MAT/CMP exporter in the add-on; these checks are not called round trips.

## Blender

```sh
blender --background --factory-startup --python-exit-code 1 --python tests/batch/app.py -- --title IJIM --key-target IJIM --assets /path/to/extracted/assets --output /path/to/build/corpus/ijim-app
```

- 3DO: import into Blender, preserve radius helpers, export in the source version,
  reload, then compare hierarchy, transforms, mesh/face modes, material bindings,
  normals, vertex colors and UVs. Vertex/material reindexing, a cyclic polygon
  starting corner and baked pivot translations are allowed; reversed winding,
  changed normals, lost geosets and changed properties are not silently ignored.
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
- MAT: import every cel and compare the actual Blender image dimensions and
  pixel buffer to independently decoded source data. Only base levels are imported
  into Blender; the core check covers the rest of each mip chain.
  Cels are resolved through their material's image bindings. Generated byte-image
  buffers allow half an 8-bit step (`0.5/255`, plus floating-point tolerance) for
  quantization of 5/6-bit channels; float buffers retain the strict `1e-6` check.
- CMP: verify palette data, as in the core script.

## Options And Results

Repeat `--assets` for multiple extracted roots. `--cmp /path/to/dflt.cmp` selects
the palette explicitly; otherwise the first discovered `dflt.cmp` is used and
recorded in the report. Palette selection is not inferred from a level: a MAT can
look different with another level's palette. `--formats 3do key`, `--match '*whip*'`
and `--limit 10` allow targeted runs. A limit is per format, `0` means all files,
and limited runs are explicitly marked as not covering the full corpus.

`--key-target IJIM`, `JKDF2` or `MOTS` enables engine-specific KEY export count and
name-buffer checks in both runners. The default `CUSTOM` checks codec/token rules
without imposing a specific engine's limits; the report title alone does not
select a target. `CUSTOM` is the interactive **Generic** option.
Blender's interactive KEY export defaults to IJIM independently.
Markers are written chronologically, with stable ordering at equal times.
Comparisons require that chronological output, preserve every marker's time/type
and tie order, and record `source_marker_order_corrected` when a source file was
originally out of order. They do not sort both inputs and hide bad exported order.

`summary.json` reports corpus/selected/processed counts and totals by format.
`results.jsonl` records each file immediately, including errors and comparison
details. Parsing/comparison failures are recorded and remaining resources continue.
Unsafe output paths abort the batch instead of being treated as ordinary asset
errors. Headerless or structurally incomplete KEY/3DO files are errors, not
successful empty resources. 3DO section order, duplicates and negative counts
are validated before a core round trip can pass. Errors, mismatches and
unsupported resources cause a nonzero exit status, never a passing or empty run.
Some original resources or existing importer limitations may therefore fail:
inspect their records rather than assuming every difference is a parser bug.
Full-corpus comparisons are useful regression evidence, not proof of byte-identical
exports or compatibility with every engine's runtime behavior.
