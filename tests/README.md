# Regression Tests

## Core: No Blender Required

Run from the repository root with Python 3.11 or newer:

```sh
python -m pip install -r tests/requirements.txt
python tests/run.py --suite core
```

`core/` tests the actual resource modules with no fake Blender modules. A fresh
interpreter test explicitly rejects imports of `bpy`, `bmesh`, `mathutils` and
`bpy_extras`. NumPy is the only test dependency and is already used by MAT/CMP.
The `sith` package loads Blender registration lazily from `sith.app`.

- 3DO 2.1/2.2/2.3 parsing/writing: geometry, vertex/face colors, UVs, normals,
  flags, hierarchy, multiple geosets, empty models, malformed/truncated input,
  and the text Grim Fandango `SHADOW` / lighting-mode extension.
- Opt-in 3DO recovery: completed-record retention, vertices-only meshes, UV
  placeholders, omitted invalid faces, preserved duplicate surfaces, partial hierarchy, broken parent
  links and missing meshes. Strict mode still rejects malformed input; valid files
  serialize identically with recovery enabled in all three supported versions.
- KEY parsing/writing: all marker/flag types, fractional timing, signed deltas,
  sparse joint indices, malformed input, deterministic serialization, stable
  chronological marker order and target-engine limits. An isolated subprocess
  checks invalid-token termination with a timeout so parser regressions cannot hang CI.
- MAT decoding: indexed 8-bit, RGB565, RGB24, RGBA32, RGBA4444 and RGBA1555,
  alpha, vertical orientation, multiple cels, rectangular mipmap chains,
  palette-free metadata loading and malformed/truncated input.
- CMP palettes: both supported versions, every palette index and truncation.
- Tokenizer, vector data and flags: comments, whitespace, escaped strings,
  numeric formats, EOF, token positions and rejection paths.

3DO structure regressions require unique, ordered body sections and nonnegative
counts, while retaining complete empty models, unknown extension sections and
opt-in recovery of completed records. The core corpus runner must report partial
or negative-count files as errors, not normalize them to successful empty models.
Blender regressions also cover same-slot KEY merge isolation (including unrelated
users), independent slots, preserved out-of-range keys, custom corner-normal
seams under scaled/mirrored export, and muted F-curve modifiers on held/linear
curves and exact imported discontinuities.
Action-import regressions cover single-user linked actions with complete and
missing channels, unchanged library data/files, non-native rotation merge rejection
before any mutation, native-order merge preservation, replacement imports, drivers,
NLA and read-only joint objects. Failed channel insertion reports a clear error.
Same-object NLA reuse is isolated even when slot users reports only one ID;
muted/nested clips keep their source action while independent slots stay shared.
Transform-driver conflicts cover location and rotation in native/non-native modes,
failure before earlier joints or metadata change, muted/property-driver exemptions,
empty tracks and replacement imports that clear drivers.
Merge-channel tests reject sampled transform storage, active F-curve modifiers
and muted destination curves before any insertion, action copy or scene change.
The sampled-curve sentinel prevents regressions from exercising unsafe native
allocation. Direct insertion is guarded too; later-joint failures, empty tracks,
muted modifiers, unrelated sampled property curves and replacement imports are
checked separately.
UV-image tests cover authoritative MAT bindings, connected color images, ignored
unused/roughness nodes, reroutes, inactive outputs, legacy single-image fallback,
ambiguous/procedural graph rejection and unchanged previous export files.
Mixed shader/color graphs with a known image beside an unresolved group also
require a binding; explicit bindings and exports without unit conversion still work.
Legacy import exercises the same resolver with existing materials, including
unused nodes, authoritative bindings without shader nodes, ambiguous/group graphs
that must retain original pixel units, and reimport after resolving dimensions.
Object-material tests cover DATA/OBJECT slots, empty overrides, shared-mesh users,
face-slot indices and normalized/pixel UV export without editing shared materials.
Parenting tests reject vertex, triangle-vertex and bone modes, including directly
exported wrappers, while preserving object poses and previous output files.
Instancing tests reject collection, vertex and face instancers at roots, inside
wrappers and in unsupported branches before either 3DO or KEY output is replaced.
A real evaluated collection instance verifies the lost-geometry case; disabled
instance modes and ordinary shared-mesh objects are positive controls.
Radius-effect tests cover model and mesh helper constraints (including Pivot),
modifiers, relative/pinned/absolute shape keys, invalid types and parenting, and
instancing. Rejection preserves old files and helper data. Muted/disabled effects,
direct scale, baked edits, live Edit Mode edits and geometry-independent KEY export
verify that valid authored bounds workflows remain supported.
Radius-name tests retain ordinary joints containing helper-name fragments through
3DO/KEY import/export, including mesh roots, every 3DO version and both hierarchy
prefix/sync settings. Real helpers stay excluded. Marker precedence, renamed
helpers and unmarked legacy prefixes agree with per-owner helper lookup.
Export-selection tests exercise both registered operators and file-browser
invocation: active roots/children, multiple selected models, ordinary `Model3do`
collections, foreign scenes and excluded view layers. Missing/deselected/foreign
active objects, unsupported types and unavailable/unsupported parents fail before
replacing prior output. Selecting a joint retains its unselected model siblings.
Helper-only export tests use genuine imported model/mesh bounds, including legacy
names, orphaned helpers and helper-only wrappers. Both operators and direct export
functions reject zero-joint results before creating/replacing files. Owned helper
selection, meshless joints and static skeletons remain positive controls; core
codec tests continue to round-trip empty resources.
Palette-path tests cover string/Path/path-like inputs, relative/absolute lookup,
empty-string defaults, missing/invalid palettes and real indexed-model pixel
decoding. Test working directories are isolated and restored after each lookup.
Resource lookup tests model a case-sensitive asset volume even on Windows CI.
Exact matches take priority, while mixed-case file and directory components work
independently of the home volume. Strict lookup, case collisions, unreadable or
disappearing folders, file/directory collisions and every palette search position
are checked. Ambiguous optional MATs warn and keep searching rather than abort
the model import. Real mixed-case MAT/CMP imports also verify decoded packed pixels.
The modeled volume isolates pathlib as well as os probes; a real working-directory
palette is used as an adversarial control against accidental host-filesystem reads.
Batch regressions model Windows Path semantics on every CI platform: case-distinct
files must both be inventoried, overlapping roots must still deduplicate, and
case-only sibling trees must not bypass corpus or output containment checks.
Extended Windows path namespaces are checked against physical ancestors too;
namespace aliases deduplicate without dropping distinct filename spellings.
Mounted aliases with the same path anchor receive physical containment checks too.
Internal file aliases cannot redirect discovery of later siblings, even when a
same-named file exists in the target directory or a path filter skips the alias.
A complete batch run checks the resulting inventory with real MAT codec checks.
Filtered runs also match either name of an internal alias before deduplication.
Directory-enumeration failures abort before processing or replacing reports.
KEY and 3DO writer tests keep multiline header comments inert, including LF,
CR and CRLF text that resembles resource sections.
Palette-error regressions require controlled `ImportError` diagnostics for every
short header in both CMP versions. Direct and registered MAT operators preserve
loaded nodes, image identities and pixels on invalid headers or palette payloads.
Default palette lookup and complete valid/invalid-header controls run too.
Recovery regressions distinguish unused meshes in a complete hierarchy from meshes
left unbound by a missing/partial hierarchy. Complete models keep their joint
count, including after geometry repair, in every version/preserve/sync/recovery
combination; missing hierarchies still recover inspectable geometry.
Constraint-animation tests reject keyed/driven Pivot offsets, changing influence
and mute state, including constraints that start disabled, wrapper motion and
constraint-only actions. Escaped RNA names, fixed disabled gates, muted channels
and unrelated properties verify that supported static poses remain exportable.
Face-flag tests use real Edit Mode callbacks to add/remove each known flag while
retaining unknown high/gap bits, per-face differences and unselected faces; an
export/reparse check verifies the resulting resource flags too.
Face-lighting tests run the actual panel synchronization and RNA callbacks with
only the layout replaced. Signed/HDR values and float32 endpoints survive
component edits; unselected faces and unrelated flags remain unchanged. Serialized
lighting is checked separately in 3DO 2.1, 2.2 and 2.3.
NLA-state export tests cover global evaluation disablement, muted tracks/strips,
empty tracks and both joints and wrappers. Real evaluated poses are compared with
serialized KEY tracks. Live composition, including NLA-only motion, must still
reject before replacing an old export. Nested Meta mute gates use small container
stand-ins because background Blender has no RNA Meta-strip constructor; clip,
track and global gates use actual Blender data. Ownership/isolation tests retain
their separate rule that muted clips still own their original action slots.
MAT transparency tests check opaque, transparent and mixed-cel reloads against
native Blender overlap/shadow settings. A no-legacy-alias control also verifies
that the current transparency-overlap property is used directly.
Import-safety regressions check held position/rotation changes, float32 time
collisions, rounding across Blender's fuzzy-time boundary and conflicts with
existing merge keys. Rejections preserve action/slot ownership, curves, markers,
playback settings, extension flags and object channels, including later-joint
failures with a shared earlier action. Identical nearby poses and well-separated
held vectors are positive controls; visible and re-exported poses are both checked.
Pivot-parent cases cover all rotation representations, drivers, NLA, grandparents,
muted/disabled motion, translation-only motion and replacement imports. Non-native
rotation merges cover every inactive NLA gate without modifying source clip data.
Earlier-audit regressions also exercise imported HDR face lighting through the
panel in all 3DO versions/sync modes, real registered palette-error paths with
shared images, helper-only export across every format/target and file state, and
NLA reactivation that must preserve the preceding successful export.
Background-import tests run the real operator with its default viewport option,
explicit framing requests, recovery warnings and invalid files. Successful imports
must not invoke viewport work or change the existing view/active-object state.
Foreground-framing tests use real Blender data and real 3DO imports with modeled
viewport operators. They cover selection/active-object/view-lock restoration,
perspective restoration after an operator failure, edit-mode and incomplete-layout
skips, and successful import with a framing warning. These are isolated UI-path
tests, not interactive-window automation.
Axis-angle regressions compare written/reloaded KEY poses with Blender's evaluated
transforms at dense and targeted subframes. They cover near-zero axis normalization,
linear/Bezier/sampled curves, extrapolation, held sign jumps, zero-angle/zero-axis
poses, invalid zero-axis rotations and unsupported easing. Unrepresentable turns
must fail before overwriting an existing file rather than silently lose motion.
- File ownership: readers/writers close on failure, mid-write I/O errors propagate,
  and opening a directory for output fails without hiding the OS error.

There is no MAT writer/exporter in the current add-on. Tests do not invent one:
`fixtures.py` packs independent synthetic binary inputs, not production output.
The hand-authored fixture in `tv/model/` and KEY files in `tv/key/` have explicit
expected values, so round trips are not the only oracle. All fixtures are original
test data; no proprietary game assets are required or downloaded.

## App: Blender Required

Run in a separate Blender 5.0+ background process:

```sh
blender --background --factory-startup --python-exit-code 1 --python tests/run.py -- --suite app
```

`app/` registers the current add-on and exercises actual Blender data and
operators, not API mocks: 3DO scene import/export, hierarchy, pivot baking,
face properties, colors, pixel-sized legacy UVs, radius helpers, MAT images,
shader links, transparency, cels, placeholders and reload, as well as KEY actions,
slots, F-curves and animation import/export. The runner unregisters in `finally`.
Tests replace only the isolated process's objects/datablocks. Nothing is saved to
startup files or preferences. No pytest, mocking framework or installed add-on is
needed. Blender already provides NumPy.

Recovery tests also check the real import operator's opt-in default and warning/error
paths, persisted Text Editor reports, vertices-only Blender meshes, preserved valid
UV corners, recomputed face normals and rejection before Clear Scene when no usable
data exists. The malformed fixtures are synthetic; game assets are not needed in CI.
The report-viewer operator also reports missing datablocks cleanly and avoids
creating UI windows in background mode. Opening the actual report window requires
a separate graphical Blender smoke test, not the headless CI suite.

Rendering-fidelity regressions also verify signed/HDR and legacy byte colors,
active POINT/CORNER attributes, material names with internal dots, missing images
and explicit UV units, vertex-only modes, scaled/mirrored normals and winding,
exact authored model radii (including zero and values below the visual enclosure)
with or without helpers, repaired undersized mesh bounds, all helper rotation
modes and exact node/mesh numbering with syncing on and off. Automatic-root tests
also verify animation joint numbers. Bad source face normals must not
override geometric correctness just to satisfy a round-trip comparison.

Export-contract regressions cover all 192 combinations of three child-sequence
permutations, mesh/empty-node masks and sync modes, with serialized 3DO/KEY pairing
and actual mesh identity checks. Edited-scene cases cover indexed-joint precedence,
ambiguous names/indices, inactive/partial Pivot constraints, linked mesh instances,
unapplied transforms, scale/delta animation and modifier rejection. Unsupported
inputs must fail without overwriting an existing output or mutating the scene.
Loose vertices and their POINT colors are retained, including vertices-only
models produced by recovery, rather than disappearing during face traversal.
Whole-line mesh display names retain embedded spaces without changing hierarchy
or KEY joint identities; whitespace is rejected only in identifier-token fields.
KEY export/reimport also checks automatic and sparse sequence values, resolving
the normalized exported indices rather than confusing them with authoring sort values.
The import-order matrix imports an actual multi-mesh 3DO with prefixes on/off,
exports with mesh syncing on/off, and checks paired KEY motion on its real joints.
Without prefixes and syncing, mesh-table order can differ while parent links,
node identities, mesh ownership and KEY animation remain correct. Identical KEY
output is expected when only mesh-list ordering changes.
Invalid KEY metadata, duplicate/out-of-range joint indices, nonfinite markers and
malformed later tracks are rejected before clearing existing actions or timeline
data. The corpus comparator separately checks track presence, names and unique
indices, so a lost zero-motion track cannot pass on pose equality alone.

### Physical Vector Matrix

`tv/` contains hand-authored 3DO/KEY files, including deliberately broken files.
[The vector inventory](tv/README.md) explains each one; recovery expectations live
in `tv/model/recovery/expected.json` rather than being generated by the writer.
The core suite checks fields, colors and retained records independently of Blender.
Application tests combine the following settings, with explicit expected results:

| Vector Cases | Configurations |
| --- | ---: |
| Order, sync, import/export colors, all output versions | 48 |
| Loose vertices and color seams with the same options | 96 |
| Shared mesh references and pivots | 24 |
| Legacy pixel UVs, texture present/missing, order/sync/colors | 16 |
| Actual paired 3DO/KEY hierarchy with preserve/sync/colors | 8 |
| Broken-file recovery, preserve/sync/colors, all output versions | 384 |
| 2.2 RGB input with preserve/sync/colors, all output versions | 48 |
| Degenerate faces with preserve/sync/colors, all output versions | 48 |

Additional cases cover saved/edited POINT color attributes, CORNER color edits,
mirrored UV/color winding, unsupported recovery headers, empty resources, invalid
KEY imports, and nonfinite transforms, radii, geometry, UVs, normals and colors.
Strict failures must leave existing scenes/actions intact. Multi-root recovery
remains inspectable but must refuse export until the hierarchy is repaired.
No original game asset or texture is required by these tests or CI.

Audit regressions also cover destination-pivot failure before clearing KEY actions,
shared-image MAT reloads, invalid color records before material replacement,
single/multi-object Edit Mode export, active/muted constraints, and nonfinite UVs
in both export and recovery. Strict imports reject missing headers, unsafe references
and incomplete polygons before Clear Scene. Repeated corners and zero-area faces
import normally, preserving all faces and their corner attributes. Both text
writers preflight floating-point fields before opening the destination, preserving
existing outputs on rejection. KEY additionally checks stored values against the
float32 range. Registered export operators are exercised directly,
including arbitrary/fractional FPS, explicit settings, missing selections, validation
failures and disk-error reports. Curve Edit Mode must not enter the mesh-face panel.
Coincident corners within one polygon retain distinct vertex IDs, so export does
not introduce repeated indices while welding vertices shared by different faces.
The hand-authored degenerate-face vector covers adjacent/nonadjacent repeats,
closing corners, fully collapsed and collinear triangles, coincident vertices
with different colors, zero normals, surrounding valid faces and loose HDR colors.

Scene-ownership regressions cover image-name collisions for texture/color MATs,
renamed/deleted cel images, shared image users, legacy cel bindings and `.blend`
serialization. Shared-mesh instances retain independently edited radius helpers
in every preserve/sync mode, including renamed helpers, legacy markers, deletion
and ambiguous ownership. Static Pivot tests compare exported vertices against
Blender's evaluated output for parented/constrained targets, uniform parent scale,
relative/absolute points and rotation-range gates. Unsupported Pivot animation,
wrapper animation/drivers/NLA and unapplied visible mesh modifiers fail without
overwriting existing files; their supported muted/static/applied paths also run.

Import-boundary tests reject float32 overflow in every 3DO numeric field and in
KEY bases/deltas/extrapolated endpoints, including overflow created by combining
otherwise representable pivots and hierarchy transforms. Strict and recovery
attempts must preserve existing work on rejection. The hand-authored overflow
and oversized-timeline vectors also verify failure before Clear Scene/Animation.
The maximum supported timeline remains exportable without length changes.
Conditional/incoming-parent Pivot animation is preflighted, while Always-active
Pivot import is checked against engine poses across positive/negative rotations.
Shape-key regressions cover active, muted, zero-weight, pinned, absolute and baked
geometry. Long 3DO names are preserved with UI/console warnings at version-specific
boundaries; KEY engine limits and illegal identifier checks remain strict.
Packed MAT decoding exhaustively checks all 65,536 words for each supported
16-bit format, including every alpha level and fully white/opaque endpoints.

FPS preflight tests use Blender's RNA limits and float32 base storage without
changing the scene. Unsupported imports and dialog exports preserve existing
actions, markers, flags, playback settings and destination files. Pivot-adjusted
local positions are checked before replacement/merge, including a failing later
joint; safe cancellation retains float32 operand semantics. Packed MAT batch
regressions run both runners on multiple cels/mips and intermediate 16-bit values,
not only white endpoints, and keep every input file unchanged.

KEY export regressions also cover finite float32 endpoints whose intermediate
difference overflows float32, truly unrepresentable slopes, and rejection before
overwriting an existing export. Serialized long linear tracks and very small
position/rotation deltas retain motion without fixed-decimal truncation. Numeric
codec cases include signed zero, subnormals, exact float32 maximum endpoints and
fractional marker/frame/FPS values. Missing-palette MAT reload tests cover packed
color/texture cels, changed dimensions, renamed/shared images, generated UV-grid
replacement without unpacking files, and restoration when the palette returns.
Shorter texture, color and cel-limited reloads remove stale numbered cel bindings
without deleting shared images or unrelated custom properties. Growth creates new
images for the detached cels; failed decoding retains every old binding and pixel.
Linked-image regressions use real `link=True` libraries and localize the material
without its images. Reloads must create local image copies before changing pixels,
dimensions or missing-palette grids, including the legacy cel-0 node fallback.
Other users retain their linked images and the source library hash stays unchanged.
Actual `.blend` save/reopen checks cover decoded textures, palette-color cels and
generated placeholders; append-only tests cannot prove linked edits persist.
Failure-before-copy, repeated reloads with shared local users, and retained image
color/alpha settings are checked too.
Read-only material reloads reject through both direct and registered APIs before
allocating images or changing nodes, bindings or pixels; explicitly making the
material local enables reload. Source library bytes remain unchanged.
KEY scene-ownership tests use real linked objects and scenes, with empty/nonempty
tracks and replacement/merge through both APIs. Rejections preserve actions,
markers, timing, flags and poses. Clear Scene checks unrelated linked actions and
driver-only animation too; unanimated linked objects and local objects using
linked actions remain supported. Destructive 3DO scene replacement can still
discard linked scenes rather than editing them.
Cross-scene KEY tests reject foreign context scenes, parents and joint descendants
before either scene changes, including unmatched foreign joints, empty tracks,
replacement/merge and disabled skeleton validation. A genuine matching Blender
context override remains supported. Linked-scene exports exercise every target,
explicit/default metadata, property presence, previous-file preservation on error
and actual save/reopen: overrides must reach the KEY without changing readonly
scene state. Editable scenes still remember successful overrides and retain
unknown flag bits. All scene libraries are synthetic and their hashes stay fixed.
Selection regressions also link a full hierarchy beside same-named local IDs;
both 3DO and KEY exports must accept its active root or child, while foreign or
excluded IDs remain invalid. Scene/view-layer membership is checked by identity.
Export-header metadata tests cover valid TOML whitespace, comments, literal and
escaped strings, top-level fields, missing/invalid/unreadable manifests, invalid
UTF-8, wrong field types and cached success/fallback values.

Export-preservation regressions cover coincident vertices with different normals,
matching-normal welding and independent color seams. Normal checks use geometric
cross products after serialization in every 3DO version, with syncing/colors on
and off and uniform, nonuniform, reflected and flattened scale.
Normal-scaling references span float32 scale magnitudes from `1e-30` to `1e30`,
with inverse-transpose directions calculated before float32 storage. Real exports
also check tiny/large scaled positions and face/vertex normals in every 3DO
version and both mesh-sync modes. Zero normals and singular scales remain valid.
Unsupported
intermediary Curve/Armature/Camera/Light parents must reject both model and KEY
export before replacing files; nested excluded branches, harmless nonmodel leaves,
radius helpers and unsupported API roots are checked separately.
Long joint names with identical prefixes survive every version/order/sync mode,
including names beyond legacy limits and `.blend` serialization. KEY name limits
remain strict. Hex-property tests cover unstored defaults, normalization, invalid
edits, explicit zero/default overrides, scene-versus-export precedence and failed
exports that must not store defaults or overwrite prior output.

Metadata-mask regressions retain unknown KEY header bits through every export
target, known-flag edits, explicit API/operator overrides and `.blend` storage.
Replacement imports replace or clear extension bits; merge imports retain scene
metadata, and rejected imports/exports leave it unchanged. Wide KEY priority masks
and 3DO joint flags/types, including the unsigned high bit, survive native Blender
property access, export dialogs, serialization and every 3DO version/order/sync
combination. Invalid hex edits preserve the prior value, while clearing a field
restores its declared default, including empty/zero joint flags.

KEY structure tests require ordered, unique HEADER/KEYFRAME NODES sections and
optional intervening MARKERS, rejecting headerless garbage and invalid counts or
joint indices. Core corpus runs must report those files as errors and continue to
valid resources. Numeric tests cover leading plus, trailing decimal points and
decimal-point exponents in complete KEY/3DO files, plus malformed signed literals.
Partial-skeleton tests exclude wrappers, radius helpers and unsupported subtrees
from both index/name fallback, preserving existing actions and scene metadata
when required joints are missing. Real mesh and leaf-Empty roots remain animatable.
Partial-name mapping also rejects multiple source tracks resolving to one target,
including case/display-name aliases with validation disabled. Merge/replacement
and registered operators must preserve old state; automatic selection skips that
candidate. Complete skeletons with repeated source names and single-track partial
imports remain supported.
KEY corpus-comparison regressions include long segments with 4/8/16 extra turns
that align at every quarter probe; non-quarter samples must still detect them.

Batch-output tests reject symlinked/directory report paths before either report
is changed. Hard-linked reports are replaced without writing their input inode,
and exclusive results-file creation refuses a newly introduced alias. Results
remain visible after each resource. Retained hard-linked export targets are
rejected before the codec runs; failed summary encoding/replacement preserves the
previous report and removes temporary files. Filesystem-link integration tests
skip explicitly where the OS/filesystem does not permit creating those links.

Packaging tests exercise the standard-library builder, archive-root manifest,
exclusion of nested pytest caches alongside bytecode/IDE files,
resource inclusion/development-file filtering, working-directory independence,
paths with spaces, and preservation of an existing ZIP on validation, directory
enumeration or write failure.
Physical source aliases cannot bypass the package output boundary; case-distinct
trees remain distinct where the underlying filesystem supports them.
The Bash-wrapper smoke test is POSIX-only; Windows uses the same Python builder.

Use `--suite all` to run both suites in Blender. With no suite option, ordinary
Python defaults to `core`; Blender defaults to `all` for the original command's
backward compatibility. Application suites deliberately fail without background
Blender rather than silently skipping tests.

For Microsoft Store Blender on Windows, invoke its registered alias from
PowerShell, replacing the script path with this checkout's absolute path:

```powershell
& "$env:LOCALAPPDATA\Microsoft\WindowsApps\blender-launcher.exe" --background --factory-startup --python-exit-code 1 --python "C:\path\to\blender-sith\tests\run.py" -- --suite app
```

The GitHub Actions workflow `tests.yml` has independent jobs: core tests on
Windows/macOS/Linux with Python 3.11 and 3.13, and application tests using the
official, checksum-verified portable Blender 5.0.1 on Linux. No game executable,
GPU rendering, desktop session or add-on installation is required.

## Animation Fidelity

For optional read-only verification against extracted game assets, see
[batch/README.md](batch/README.md). These scripts produce per-resource JSON reports
and run separately from the synthetic CI suites.

The synthetic fixtures in `tv/key/` exercise the shared text KEY contract used by
the supported Sith titles, not title-specific joint names or animation constants.
They cover Euler winding, quaternion wraps, sparse and zero channels, hold keys,
Bezier baking, fractional frame times, effective FPS, hierarchy indices and codec
round trips. Grim Fandango's future binary KEY codec is not covered by text tests.

Export samples mesh-object transform F-curves. Constraints, NLA composition and
overlapping action layers must first be baked to those channels. Live F-curve
modifiers must also be baked; their output cannot be bounded by sparse adaptive
probes. Animated scale, scale drivers and unbaked delta motion are rejected.
Nonlinear ordinary curves
are subdivided to at most `0.00001` position units and `0.05` rotation degrees at the
interval's quarter/midpoint probes; failure to converge reports an error. This is
adaptive approximation, not an exact encoding of arbitrary Blender curves.
Quaternion channels additionally seed component zero crossings and extrema for
LINEAR/BEZIER segments, including linear extrapolation. Signed quaternion arcs
keep authored long rotations instead of identifying opposite signs as no motion.
Bezier critical-point analysis follows Blender's independent handle clipping in
[`BKE_fcurve_correct_bezpart`](https://github.com/blender/blender/blob/v5.0.0/source/blender/blenkernel/intern/fcurve.cc).
Other quaternion easing modes must be baked first. Critical boundaries and
quaternion subdivision times use float32 frame precision; an unrepresentable
narrow turn must fail before opening an existing output, rather than vanish.
Tests exercise linear and unit-endpoint Bezier half-turns missed by regular probes,
two crossings within one quarter interval, overlong handles, held sign changes,
linear extrapolation and dense evaluated poses for a representable Bezier turn.
Native KEY-order Euler winding is additionally checked and retained, including
deliberate full rotations. The final fractional playback interval before `FRAMES`
is sampled too, rather than freezing every animation at `FRAMES - 1`.
Imported moving segments with endpoint discontinuities use a small pre-boundary
key and hold because ordinary F-curves cannot encode the exact moving segment
plus its endpoint jump. The sample must remain outside Blender's `0.0001`-frame
fuzzy evaluation threshold. Tests check evaluated object poses before, at and
after the jump, not just exported samples. Arbitrarily close subframe evaluation
is still limited by Blender's evaluator; unrepresentably close jumps are rejected.
An imported jump's exact source segment is retained for export only while the
action reference, transform curves, interpolation, handles and pivot still match.
Curve edits, action changes, modifiers or merged imports cannot reuse stale data.
Import without clearing retains pre-existing keys at unrelated times.
Active-action blend tests exercise partial influence and additive modes above
NLA, including muted strips on populated tracks. Rejection must precede shared
action copies and scene changes. Full Replace, disabled NLA, muted tracks and
empty tracks retain their supported behavior; Clear Scene removes old blending.
Import and export share action-state validation. Export regressions compare
evaluated Blender poses against serialized KEY motion under supported NLA states;
unsupported joint/wrapper blending preserves previous files. Native NLA tweak
mode tests cover early merge rejection without orphan actions, later-joint
failure before action isolation, replacement imports and untouched empty tracks.
3DO precision tests cover every output version, small geometry/UVs/lighting and
radii, float32 extremes, signed zero and rejection before overwriting files.
Nonempty tracks must start at stored float32 frame zero. A synthetic nonzero-first
vector remains codec-readable but must fail both merge/replacement imports before
any scene mutation. Signed zero, underflow-to-zero and empty tracks remain valid.
Pivot merge regressions cover keyed offsets, animated mute/influence (including
initially disabled constraints), setting drivers and constraint-only NLA clips.
They check later joints, escaped constraint names, shared actions and unchanged
scene/constraint state on rejection. Muted channels/drivers, permanently disabled
constraints, inactive NLA and empty tracks remain supported; replacement imports
remove the old procedural animation. Supported imports compare evaluated poses,
and inactive clips must retain their source curves.
Fractional markers use an explicit `@fraction` suffix because Blender's integer
timeline markers lack custom-property storage; tests cover moves and duplicates.
Unmodified LINEAR/CONSTANT export segments are evaluated directly from their key
coordinates, avoiding Blender's near-key evaluation snapping. Bezier curves and
sampled curves still use Blender's evaluator.
