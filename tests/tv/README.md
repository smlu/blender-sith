# Synthetic Resource Vectors

All files here are hand-authored test data, not game assets or output from the
production writer. Tests must assert independent expected fields as well as round
trips. Strict tests must reject deliberately malformed vectors. Explicit recovery
tests may retain/repair only the declared records in memory or temporary output;
never rewrite a source vector to make it pass.

Run them through the [test runner](../README.md), not as an asset corpus. The
[shared expectations](../vector_expectations.py), [core vector tests](../core/test_vectors.py)
and [application matrix](../app/test_vector_matrix.py) provide independent fields
and configuration checks. They do not establish five separate game-corpus passes;
see the [game coverage table](../README.md#game-coverage).

Grim Fandango binary records are constructed independently with `struct` in
[grim_fixtures.py](../grim_fixtures.py), like the synthetic MAT/CMP byte vectors in
[fixtures.py](../fixtures.py). They
include nonzero name padding, non-boolean pointer-presence words, unknown raw data,
signed/HDR intensities, a loose vertex, multiple geosets and optional records. A
footer vector deliberately differs from INSERT OFFSET to catch field-order mistakes.
The codec suite tests every truncated prefix and corrupts individual count/index
fields; the Blender suite also checks opaque metadata, custom normals and authoring
changes. No original Grim assets are included or downloaded by the test suites.
Binary MAT/MODL/FYEK fixtures are generated in memory, not missing files in this
directory. MAT writer/export tests also generate synthetic images and palettes;
their six-encoding and mipmap coverage is separate from this text-vector inventory.

## Models

- [order_colors.3do](model/order_colors.3do): opposing name/node order, empty root/intermediate joint,
  independent mesh IDs, face flags, alpha, signed/HDR colors, a loose vertex and
  an unused UV. `key/order_colors.key` animates all four joints.
- [shared_mesh.3do](model/shared_mesh.3do): two differently placed/pivoted joints bind the same mesh.
- [legacy_pixels.3do](model/legacy_pixels.3do): 2.1 scalar intensities and pixel UVs for a 64-by-32 image.
- [rgb22.3do](model/rgb22.3do): 2.2 RGB vertex/face colors with implicit alpha one.
- [loose_vertices.3do](model/loose_vertices.3do): vertex-only geometry, coincident colored points and alpha.
- [color_seams.3do](model/color_seams.3do): coincident corners with different colors/alpha and opposite
  surface winding; position-only deduplication would destroy the color seam.
- [empty.3do](model/empty.3do): valid resource with no geometry/hierarchy; import creates nothing.
- [invalid/header_only.3do](model/invalid/header_only.3do) and
  [invalid/negative_counts.3do](model/invalid/negative_counts.3do): incomplete syntax
  and a negative material count; neither may pass a core corpus round trip.
- [triangle.3do](model/triangle.3do): original asymmetric colored triangle and pivot fixture.
- [face_lighting_hdr.3do](model/face_lighting_hdr.3do): signed/HDR face extra light and unknown high face flags
  for real import, panel-edit and all-version export regressions.
- [float32_overflow.3do](model/float32_overflow.3do): a syntactically valid finite coordinate outside float32
  range; strict and recovery imports reject it before clearing existing work.
- [degenerate_faces.3do](model/degenerate_faces.3do): nine faces with adjacent/nonadjacent repeated corners,
  a repeated closing corner, a fully collapsed triangle, collinear vertices,
  coincident points with different colors, zero normals and a loose HDR point.
  Normal import preserves all faces and corner UVs; recovery is not required.

## Recovery

[model/recovery/expected.json](model/recovery/expected.json) declares retained vertex/face counts, repaired
parents, required diagnostics and whether the recovered hierarchy is exportable.
`vertices` counts raw recovered records; an optional `export_vertices` declares
additional coincident vertices needed to keep repeated face corners in Blender.
Vectors cover invalid UVs, repeated/out-of-range faces, opposite-facing duplicate
surfaces, parent cycles, missing meshes, nonfinite values, and truncation at vertex,
face and hierarchy records. Unsupported headers and input without any completed
usable record must still fail.

The manifest accounts for all ten recovery files: `bad_uvs.3do`, `bad_faces.3do`,
`parent_cycle.3do`, `missing_mesh.3do`, `truncated_vertices.3do`,
`truncated_faces.3do`, `truncated_hierarchy.3do`, `nonfinite.3do`, `bad_header.3do`
and `no_geometry.3do`. The last two are unrecoverable, while `missing_mesh.3do`
and `truncated_hierarchy.3do` are inspectable but not exportable as-is.

Missing/partial hierarchy vectors may recover multiple roots for inspection.
They must report lost placement information and reject normal 3DO export until
the user repairs the hierarchy; tests do not silently invent original transforms.

## Animation

- [fractional.key](key/fractional.key): fractional entries/marker timing, 59.94 FPS,
  held endpoints and moving position/rotation channels.
- [winding_and_holds.key](key/winding_and_holds.key): a two-turn moving rotation,
  held spans, a position jump and fractional FPS.
- [held_too_close.key](key/held_too_close.key),
  [held_separated.key](key/held_separated.key) and
  [held_float32_collision.key](key/held_float32_collision.key) are
  syntactically valid held-position tracks with independently specified frames and
  X values. The first and third must fail Blender preflight before any mutation;
  the separated control must match both visible and serialized poses. They are
  codec-readable inputs, not files to repair or silently retime.

- [nonzero_first.key](key/nonzero_first.key) starts its only track at frame 2 with
  independent position and rotation deltas. The core codec must retain those
  fields. Default strict Blender import rejects the track before merge or
  replacement; opt-in relaxed frame-zero handling is tested separately, including
  backward extrapolation and overflow. It is not an unconditional codec error or
  an input that tests should silently retime. Named export targets still require
  frame-zero tracks; Generic export has separate source-timestamp behavior.

- [order_colors.key](key/order_colors.key) includes all real mesh/empty joints, ignored stale deltas on
  held channels, full-turn Euler winding, a wrap across 360 degrees, a moving jump,
  fractional FPS, negative/fractional markers and tied events.
- [invalid_timing.key](key/invalid_timing.key),
  [duplicate_joint.key](key/duplicate_joint.key),
  [out_of_range.key](key/out_of_range.key),
  [unordered_entries.key](key/unordered_entries.key) and
  [truncated_entry.key](key/truncated_entry.key) contain invalid timing,
  duplicate/out-of-range joints, unordered entries or a truncated record.
  Each must fail strict import without losing existing animation.
  Duplicate/out-of-range joint indices and truncated records fail in the core
  codec; playback timing and entry-order checks also run in the Blender importer.
- [oversized_timeline.key](key/oversized_timeline.key) has a valid two-million-frame header outside Blender's
  playback range. Import must reject it without clamping the duration or clearing
  the current animation.
