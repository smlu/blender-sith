# Synthetic Resource Vectors

All files here are hand-authored test data, not game assets or output from the
production writer. Tests must assert independent expected fields as well as round
trips. Malformed vectors are deliberately invalid and must not be "repaired".

## Models

- `order_colors.3do`: opposing name/node order, empty root/intermediate joint,
  independent mesh IDs, face flags, alpha, signed/HDR colors, a loose vertex and
  an unused UV. `key/order_colors.key` animates all four joints.
- `shared_mesh.3do`: two differently placed/pivoted joints bind the same mesh.
- `legacy_pixels.3do`: 2.1 scalar intensities and pixel UVs for a 64-by-32 image.
- `rgb22.3do`: 2.2 RGB vertex/face colors with implicit alpha one.
- `loose_vertices.3do`: vertex-only geometry, coincident colored points and alpha.
- `color_seams.3do`: coincident corners with different colors/alpha and opposite
  surface winding; position-only deduplication would destroy the color seam.
- `empty.3do`: valid resource with no geometry/hierarchy; import creates nothing.
- `invalid/header_only.3do` and `invalid/negative_counts.3do`: incomplete syntax
  and a negative material count; neither may pass a core corpus round trip.
- `triangle.3do`: original asymmetric colored triangle and pivot fixture.
- `face_lighting_hdr.3do`: signed/HDR face extra light and unknown high face flags
  for real import, panel-edit and all-version export regressions.
- `float32_overflow.3do`: a syntactically valid finite coordinate outside float32
  range; strict and recovery imports reject it before clearing existing work.
- `degenerate_faces.3do`: nine faces with adjacent/nonadjacent repeated corners,
  a repeated closing corner, a fully collapsed triangle, collinear vertices,
  coincident points with different colors, zero normals and a loose HDR point.
  Normal import preserves all faces and corner UVs; recovery is not required.

## Recovery

`model/recovery/expected.json` declares retained vertex/face counts, repaired
parents, required diagnostics and whether the recovered hierarchy is exportable.
`vertices` counts raw recovered records; an optional `export_vertices` declares
additional coincident vertices needed to keep repeated face corners in Blender.
Vectors cover invalid UVs, repeated/out-of-range faces, opposite-facing duplicate
surfaces, parent cycles, missing meshes, nonfinite values, and truncation at vertex,
face and hierarchy records. Unsupported headers and input without any completed
usable record must still fail.

Missing/partial hierarchy vectors may recover multiple roots for inspection.
They must report lost placement information and reject normal 3DO export until
the user repairs the hierarchy; tests do not silently invent original transforms.

## Animation

`held_too_close.key`, `held_separated.key` and `held_float32_collision.key` are
syntactically valid held-position tracks with independently specified frames and
X values. The first and third must fail Blender preflight before any mutation;
the separated control must match both visible and serialized poses. They are
codec-readable inputs, not files to repair or silently retime.

`nonzero_first.key` starts its only track at frame 2 with independent position and
rotation deltas. The core codec must retain those fields, but Blender import must
reject the track before a merge or replacement: Sith starts at entry zero and
requires a nonnegative elapsed frame count from that entry, including at frame 0.

`order_colors.key` includes all real mesh/empty joints, ignored stale deltas on
held channels, full-turn Euler winding, a wrap across 360 degrees, a moving jump,
fractional FPS, negative/fractional markers and tied events. The other new KEYs
contain invalid timing, duplicate/out-of-range joints, unordered entries or a
truncated record. Each must fail import without losing existing animation.
Duplicate/out-of-range joint indices and truncated records fail in the core
codec; playback timing and entry-order checks also run in the Blender importer.
`oversized_timeline.key` has a valid two-million-frame header outside Blender's
playback range. Import must reject it without clamping the duration or clearing
the current animation.
