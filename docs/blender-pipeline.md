# Blender Import And Export Pipeline

[Technical index](README.md) | [Interactive usage](../USAGE.md) | [Formats](formats/README.md)

This guide follows assets through the add-on. File layouts are documented
separately; here the important questions are which Blender data represents each
field, when conversions happen, and which indices are allowed to change.

- [Model import and scene structure](#model-import)
- [Resource lookup](#resource-lookup)
- [UV conversion](#uv-conversion)
- [Extra Light preview](#extra-light-preview)
- [Model export](#model-export)
- [Node ordering and mesh sync](#node-ordering-and-mesh-sync)
- [Animation import and export](#animation-import-and-export)
- [Preservation and limitations](#preservation-and-limitations)

## Three Representations

```text
              FILE                   CORE RESOURCE              BLENDER

  text 3DO / binary MODL   <-->  Model3do                 <-->  model wrapper
                                  materials[]                 mesh/Empty joints
                                  geosets[].meshes[]           mesh datablocks
                                  meshHierarchy[]              custom properties

  text KEY / binary FYEK   <-->  Key                      <-->  actions + slots
                                  nodes[].keyframes[]           transform F-curves
                                  markers[]                    timeline markers

  MAT + external CMP       -->  headers / cels / pixels    -->  materials + images
                                                              (no MAT export)
```

Core parsing does not require a Blender scene. Import adapters create Blender
data from decoded resources. Export adapters create a **new temporary resource**
from the scene, then serialize it. They do not write Blender's object list directly
into a file or reorder the original scene objects to make an export work.

## Model Import

```text
read magic / parse text
          |
          v
validate topology, references and composed transforms
          |
          v
resolve MAT paths and CMP -----> absent optional resources: warnings/placeholders
          |
          v
Clear Scene, if requested
          |
          v
build every LOD-0 joint -------- mesh-owning node: Mesh object + mesh data
          |                      meshless node: Empty object
          v
connect parent links ----------- links may reference a later source node
          |
          v
add model wrapper, metadata and optional radius helpers
```

Strict parsing and adapter preflight occur before clearing the scene. Text
recovery is opt-in and emits warnings; it is not used for truncated binary
records. After construction begins, failure cleanup removes newly created
objects/datablocks where tracked. **Clear Scene remains an intentional discard**:
cleanup is not a general transaction that restores a previously cleared scene or
all pre-existing material edits. For 3DO import, Clear Scene affects scenes and
their content throughout the current .blend, not just the active scene.

### Scene Structure

```text
model wrapper (Empty)            location = INSERT OFFSET; not a joint
 +-- root joint (Mesh or Empty)  local position / rotation; node sequence property
 |    +-- joint (Mesh)           owns geometry, UVs, face layers, colors
 |    |    +-- mesh radius       optional tagged helper; not a joint
 |    +-- joint (Empty)          valid transform-only joint; no mesh index
 |         +-- joint (Mesh)
 +-- model radius               optional tagged helper; not a joint
```

A source mesh bound at multiple joints becomes separately editable geometry at
those joints; preservation of the source's shared mesh-table identity is not
promised. Extra geosets and unbound source mesh records are not editable scene
objects retained for automatic re-export.

The imported joint properties include its source sequence number
`sith_model3do_hnode_idx` and source name `sith_model3do_hnode_name`, plus flags
and type mask. Display names and serialized names are not interchangeable:
export prefers the stored source name when set, otherwise the object name with
its optional ordering prefix removed. Renaming only the Blender object need not
rename the exported joint.

### What Preserve Mesh Hierarchy Does

Despite its UI name, **Preserve Mesh Hierarchy** controls visible ordering
prefixes, not whether parenting exists:

```text
on:   no0_root, no1_arm, no2_hand ...  (prefix may be zero-padded)
off:  root,     arm,     hand ...

both: parent links + stored source sequence numbers are imported
```

Without prefixes, Blender's child/name ordering can change the traversal used to
collect **unsynced mesh records**. Node sequence properties still drive normalized
joint order. Turning this option off does not flatten the skeleton, erase source
indices, or guarantee that an output file will differ.

### Coordinates And Pivots

File orientations are pitch/yaw/roll in degrees. The rotation construction is:

```text
R(P,Y,R) = Rz(yaw) * Rx(pitch) * Ry(roll)

unscaled source hierarchy, column-vector notation:
  J_i       = J_parent * T(position_i) * R(PYR_i)
  v_model   = J_i * (v_source + pivot_i)
  v_world   = T(insertOffset) * v_model

source pivot moves this joint's mesh, not its child joint's origin
```

Import adds the pivot to mesh vertices. It does **not** recreate that source pivot
as an editable Blender constraint/property. Joint position and rotation stay on
the object, so the model looks correct while remaining convenient to edit. The
original split between vertex coordinates and pivot is then lost.

An explicitly authored, supported Blender Pivot constraint is a separate case:
export can encode its pivot and adjust node position. It must satisfy the
adapter's static/local constraints; arbitrary animated/world-space constraints
must be baked. A source pivot baked on import is not such a live constraint.

### Geometry, Colors And Normals

| Source data | Blender representation / conversion |
| --- | --- |
| Vertex positions | Mesh vertices; source pivot baked into positions |
| Repeated vertex within one face | A coincident Blender vertex can be created to avoid self-linked polygon topology |
| UV indices | Per-loop UVs, with unit and V-sign conversion |
| Vertex lighting | Corner-domain colors; a point-domain companion retains loose-vertex colors |
| Face modes, flags and extra light | Per-face custom data layers |
| Material index | Per-object material slot mapped from the model-wide table |
| No material (`-1`) | Explicit empty slot, avoiding accidental inheritance of material slot 0 |
| Authored vertex normals | Preserved automatically for binary/identified Grim input, or explicitly for ordinary text input |
| Face normals | Recomputed from exported geometry, not frozen to a source value |

The same position can need multiple exported vertices at a color or normal seam.
UV seams alone use the separate UV table. Unchanged imported binary vertex
normals retain their original precision even if Blender quantizes its internal
custom-normal representation. Authored geometry edits invalidate that shortcut.

## Resource Lookup

Let `D` be the model's directory and `R` a supplied MAT search root. Relative
MAT roots are interpreted relative to `D`; absolute roots remain absolute.
Candidates are deduplicated while retaining their search order.

```text
MAT search:
  D -> D/mat -> parent(D)/mat -> D/3do/mat
  then for each R:
    R -> R/mat -> R/3do/mat
```

CMP first checks the requested path as given (including an existing path relative
to the working directory). It then searches these folders for that name:

```text
D
D/misc/cmp
parent(D)
parent(D)/misc/cmp
parent(parent(D))/misc/cmp
D/misc/cmap
D/cmp
D/cmap
parent(D)/misc/cmap
parent(parent(D))/misc/cmap

then for each supplied MAT root R:
R -> R/misc/cmp -> R/misc/cmap -> R/cmp -> R/cmap
  -> parent(R) -> parent(R)/misc/cmp -> parent(R)/misc/cmap
```

With no requested CMP name, the complete search is tried for `dflt.cmp`, then
`dfltcmp.cmp`. A specifically requested but missing palette is not silently
replaced with an unrelated default. Exact spelling wins; otherwise a unique
case-insensitive match is accepted for path components and filenames. Ambiguous
case variants are an error, not an arbitrary choice. Searches are not recursive
scans through all game archives or LAB directories.

Missing/unreadable optional MAT resources produce warnings and allow another
candidate root to be tried. Missing MATs retain material-name placeholders.
Missing CMPs retain indexed texture dimensions but cannot produce correct colors.
Neither case justifies choosing a random palette from the resource directory.

## UV Conversion

The **v2.1 Absolute UV** option selects pixel-space input/output for 2.1-family
assets, including JKDF2, MOTS, DroidWorks and Grim. Texture dimensions come from
the face's bound material image, not viewport or render resolution.

```text
absolute source UV (u_px, v_px), image W x H:
  import -> Blender UV (u_px / W, -v_px / H)
  export -> source UV  (u_bl * W, -v_bl * H)

normalized source UV:
  import -> Blender UV (u, -v)
  export -> source UV  (u_bl, -v_bl)

example: image 128x64, source (32,16) -> Blender (0.25,-0.25)
```

Values are not clamped to `[0,1]`: tiling coordinates outside the base image are
valid. This is a V **sign** change, not `1-v`. MAT image-row flipping is a distinct
stage in [pixel decoding](formats/materials.md#pixel-decoding).

If dimensions are unavailable, import retains absolute coordinates with a
per-corner units marker rather than dividing by guessed dimensions. A correctly
sized MAT placeholder without decoded palette colors can still supply dimensions.
Export converts only when stored units differ from requested units. Required
conversion without resolvable dimensions fails instead of writing plausible but
incorrect UVs. Cel 0's bound image, or an unambiguous relevant shader image,
supplies dimensions; unrelated same-named images do not.

## Extra Light Preview

The scene's **3DO Properties > Preview > Extra Light** switch defaults to on.
Imports create its derived data without resetting an existing scene's choice.
This previews the editable per-face field, not Grim's runtime cached mesh
intensity/ancestor-lighting behavior.

```text
authoritative BMFace string layer: 3do_face_extra_light (RGBA)
       |                                        |
       | RGB, display-clamped to [-1,1]         +--> 3DO face extra light
       v                                             original signed/HDR values
three FACE-domain FLOAT attributes
       |
material preview group <--- current scene's disable flag
       |
       +--> dim base RGB for negative extra light
       +--> add texture-modulated emission for positive extra light

existing vertex colors, texture alpha, pixels and UVs: unchanged
```

`bmFaceSetExtraLight` writes the original string field and its derived cache.
Preview layers are allocated before iterating faces because adding BMesh custom
data can invalidate existing face handles. The edit callback updates the live
mesh and material setup; load/toggle refreshes can reconstruct caches for older
.blend files. Refreshing Object Mode attributes does not round-trip geometry
through BMesh, which could disturb authored normal/color state.

For each preview RGB channel `d`, the shader uses a display-limited value:

```text
d             = clamp(extraLight, -1, 1) * scenePreviewEnabled
baseOut       = baseIn * (1 + min(d, 0))
emissionOut   = oldEmissionColor * oldEmissionStrength + baseIn * max(d, 0)
```

These equations are a Blender editing approximation, not the engine's complete
light accumulation and clamping pipeline. Extra Light alpha is not a texture
alpha override. The existing Principled alpha socket is never rewired. Previous
emission is retained by folding its strength into its color; the Principled
emission strength then becomes one. With preview disabled, the original shading
is recovered algebraically without changing serialized face/vertex values.

The group reads scene state through a View Layer attribute rather than a driver
bound to one scene ID. Missing disable metadata means enabled. Shared materials
therefore read each mesh's own face values and the scene being drawn. The known
preview group's Base Color input is transparent to the UV-image resolver; its
derived brightness is not treated as an additional texture source.

Only editable Principled shaders without node-tree animation are extended.
Linked data, animated node trees, unsupported shader types and empty material
slots remain unchanged. MAT reloads reattach a previously installed preview.
On add-on removal, inputs still owned by the preview group are restored; inputs
that the user has rewired are not overwritten. Material Preview and Rendered
shading evaluate it, including final Blender renders while enabled; Solid mode
does not. None of this data is exported as vertex lighting.

Implementation: [model3doPreview.py](../sith/model/model3doPreview.py).

## Model Export

Both model and animation export resolve the **active selected Mesh or Empty** to
its top-level model hierarchy. Other selected models are not merged. Collection
names/tags have no special export role; no active selected model means no export.
Unsupported parents with exportable descendants must be baked or reparented.

```text
resolve selected model
        |
collect hierarchy + geometry into temporary Model3do
        |
normalize node sequence + rebuild hierarchy links
        |
optional mesh-list sync
        |
validate geometry, dimensions, names and bounds
        |
write selected text version / binary MODL
```

A Mesh root is a joint. A top-level Empty **with children** is the model wrapper:
its location becomes INSERT OFFSET and it does not consume a joint. Its rotation
must be applied before export. An Empty without children can be a meshless joint.
Tagged radius helpers are excluded from both node and mesh counts.

Live Edit Mode data is flushed before reading geometry, without leaving Edit
Mode. Live geometry effects must be applied first: raw mesh export preserves
engine custom layers, not an arbitrary evaluated modifier result. Effective
object material slots honor object-level overrides even for shared mesh data.
The exported model-wide material table uses normalized lowercase `.mat` names;
Blender's numeric suffix after an existing `.mat` extension is removed. Image
pixels are not embedded in the 3DO or exported as new MAT files.

Static local/inherited scale is baked into geometry. A joint's own scale does
not multiply its own local translation; inherited scale does. Reflected scale
also changes polygon winding, and normals are transformed consistently rather
than merely scaled as positions. Vertex reuse compares position, color and
normal, plus preserved opaque per-vertex data where applicable; corners within
one polygon cannot collapse to the same exported index.

When vertex-color export is disabled, generated lighting is `(0,0,0,1)`, not
white. Version conversion can reduce RGB to scalar intensity or drop alpha.

Mesh radius must enclose the emitted mesh; inadequate bounds are enlarged with
outward rounding. **Model RADIUS is different**: an authored value is preserved
because engines can use it for collision defaults. A geometry-wide model bound
is computed only when no authored model radius/helper supplies one.

## Node Ordering And Mesh Sync

There are two distinct passes. Neither changes Blender object ownership.

### 1. Normalize Nodes

`Model3do.reorderNodes` snapshots parent references before sorting. Those
references address the old list, not the requested sequence-number values.

```text
requested sequence numbers
          |
stable sort (ties retain collection traversal order)
          |
old list index -> new dense node index
          |
remap parent indices; rebuild first-child / sibling / child-count fields
```

Sequence gaps do not create empty array slots. Automatic sequence `-1` uses
traversal order; when it would put children ahead of an explicitly numbered
root, explicit numbers are ordered first. 3DO export requires one root sorting
to node 0; invalid references, cycles or a conflicting root order are rejected.
Mesh indices are **not** changed by this pass. Complete KEY skeletons use the
same normalized ordering, but ambiguous duplicate explicit sequences are rejected
on animation import rather than mapped to an arbitrary joint.

### 2. Optionally Synchronize Meshes

With sync on, walk normalized node order and number **mesh-owning** nodes densely.
Reorder mesh records and update their node bindings together. Empty joints keep
`meshIdx = -1` and consume no mesh slot. Thus sync means **mesh order follows
joint order**, not universally `meshIdx == nodeIdx`.

With sync off, mesh records keep collection traversal order. Node ordering and
link remapping still run; different node/mesh indices are intentional and valid.

### Worked Example

Suppose collection produced this temporary hierarchy/mesh order. `seq` is the
requested sequence property, not a parent address:

```text
old node   name    seq   parent(old)   mesh(old)
   0       Root     0       -1           0
   1       Arm     20        0           1
   2       Pivot   10        0          -1
   3       Hand    30        2           2
   4       Head    15        0           3
```

Node normalization maps old indices `0,2,4,1,3` to new indices `0,1,2,3,4`:

```text
new node   name    parent(new)   mesh, sync OFF   mesh, sync ON
   0       Root       -1              0               0
   1       Pivot       0             -1              -1
   2       Head        0              3               1
   3       Arm         0              1               2
   4       Hand        1              2               3

mesh array OFF: [Root, Arm, Hand, Head]
mesh array ON:  [Root, Head, Arm, Hand]

rebuilt hierarchy, independent of sync:
  Root.firstChild = 1             Pivot -> Head -> Arm (sibling chain)
  Pivot.firstChild = 4            Hand is still Pivot's child
```

The Empty joint is why Head's synced mesh index is 1 while its node index is 2.
Changing sync must not change which mesh is attached to Head, or which parent
owns Hand. Source assets often have matching mesh/node IDs simply because they
contain one mesh at each joint; that is not a format invariant.

| Import preserve option | Export sync option | Result |
| --- | --- | --- |
| On | On | Visible source-order prefixes; mesh records follow normalized joints |
| On | Off | Visible prefixes; collected mesh order retained |
| Off | On | Unprefixed display names; mesh records follow normalized joints |
| Off | Off | Unprefixed names; mesh order may follow a different Blender traversal |

All four combinations preserve parenting and stored node sequence properties.
Choose sync according to the consumer's expectations; do not rely on name sorting
alone to maintain mesh/node correspondence.

## Animation Import And Export

### Match Tracks To Joints

For a complete skeleton, import normalizes its eligible joints using the same
ordering as export, then maps KEY joint indices to that order. Meshless joints
count; the wrapper and helpers do not. For a partial skeleton, explicit valid
sequence IDs take priority, then an unambiguous name match is attempted. Two
source tracks cannot target the same destination object.

Preflight checks FPS representation, timing, destination ownership/editability,
pivots and merge compatibility before clearing existing animation. With validation
disabled, unmatched tracks can be reported and skipped; disabling validation is
not permission to ignore unsafe transforms or ambiguous matches. **Clear scene**
on KEY import clears animation data/markers, not the model geometry.

### Construct Blender Curves

```text
KEY base + delta segments
          |
Grim playback normalization, when needed
          |
expand segment boundaries, holds and jumps into samples
          |
map PYR degrees -> Blender Euler radians (YXZ order)
          |
align Euler branches to previous extrapolated orientation
          |
insert location / rotation curves in each object's action slot
```

The Blender XYZ angle components are `(pitch, roll, yaw)` because their axes are
X, Y and Z; the file vector remains `(pitch, yaw, roll)`. Branch alignment matters:
a full turn or authored long rotation must not collapse into a quaternion's short
arc. Imported linear/held channels receive matching interpolation. Exact jump
metadata is reusable only while its generated curves/pose remain unchanged.

**Require Frame Zero** defaults to on. When disabled, a late first entry gets a
frame-zero prefix evaluated using negative elapsed time and its active deltas;
held channels stay held. Source timestamps are not shifted. Exact late-start
entries can be reused for an unedited Generic export at scene start zero.

**Try Recover Broken File** defaults to off. Valid tracks keep their joint IDs;
invalid tracks are omitted with a separate KEY import report, never interpolated
across fabricated entries. Header/binary bounds and destination preflights still
apply. Recovery and the frame-zero policy are independent. See
[KEY recovery](formats/key.md#opt-in-recovery) for supported damage and limits.

For supported live pivots, imported local location is `KEY position + pivot`;
export subtracts the pivot again. A baked 3DO source pivot remains baked and is
not reconstructed here.

### Time And Markers

```text
ordinary clip: FRAMES = N
Blender display: frames 0 .. N-1
export sampling also covers the last fractional interval up to N
export frame count = scene.frame_end + 1

seconds = KEY frame / stored FPS
Blender effective FPS = render.fps / render.fps_base
```

Fractional FPS must fit Blender's supported numerator/base representation.
Grim zero-duration pose clips are a special case described in [KEY](formats/key.md#grim-playback-interpretation).

Blender timeline markers use integer frames. Import stores the integer floor on
the marker and the fraction in its name:

```text
KEY event: frame 12.125, type 1
Blender:   frame 12, name 'LeftFoot@0.125' or '1@0.125'
export:    12 + 0.125 -> 12.125, type 1
```

Moving the marker preserves its subframe suffix. Export decodes supported names
or numeric event IDs and sorts by time; malformed names are warned and skipped.

### Sample And Export Actions

KEY export reads each object's **assigned action slot**, not every curve in a
shared action, and not arbitrary evaluated dependency-graph motion. It combines
channel sample times, preserves fractional boundaries and generates linear/held
base-plus-delta segments. Quaternion/axis-angle source curves are converted to
KEY's Euler representation with the sampling checks in the exporter.

Bake unsupported motion to local location/rotation channels before export:
transform drivers, active NLA composition, live F-curve modifiers, layered
conflicting channels, unsupported constraints and procedural wrapper motion.
Animated scale and Blender delta-transform channels are not KEY fields. A bake
must actually remove the unsupported representation, not leave it active beside
the baked curves.

The **Target** selects engine limits and text versus FYEK output; see
[the target table](formats/key.md#export-targets-and-preservation). Generic removes
engine-specific caps, not shared safety checks. It also permits nonzero starts,
sampling from the scene start without rebasing; named game targets sample from
frame zero. The exported frame count remains `scene.frame_end + 1`.

## Preservation And Limitations

| Data | Core codec | Blender round trip |
| --- | --- | --- |
| Extra geosets | Model resource retains them | LOD 0 only |
| Original pivots | Retained in model fields | Baked into vertices; not reversibly recovered |
| Shared or unbound mesh records | Representable in resources | Original sharing/unbound records not guaranteed |
| Vertex/face counts | Retained unless edited | Can change at seams or repeated corners |
| Face normals | Stored field | Derived from emitted geometry |
| Authored vertex normals | Stored field | Preserved when requested/identified; transformed when needed |
| Model vs mesh radius | Separate fields | Authored model radius retained; mesh bounds enclose geometry |
| Binary opaque fields | Retained where compatible | Only matching imported metadata is reused |
| Animation segments | Stored base/delta entries | Curves are generated and sampled; verify poses, not bytes |
| Native-engine timing/blending | Not executed by a codec | Not established by frame-domain tests |

Binary model metadata is attached to the wrapper, joints and mesh data using
`_sith_modl_model`, `_sith_modl_node` and `_sith_modl_mesh`. Source-record IDs allow
matching original records; zero marks a newly created record and positive IDs
refer to original index plus one. These caches preserve opaque fields, not
hidden authority to overwrite edited transforms/geometry with the original file.

Replacement binary KEY imports retain `_sith_key_binary` metadata on the model
root. It is reused only while joint count and animated joint identities match.
Merging clips clears it; hierarchy changes can require new defaults. Saving a
.blend preserves metadata, but users should not edit these caches to repair a
broken hierarchy.

## Implementation And Tests

| Stage | Entry points |
| --- | --- |
| Model import | [model3doImporter.py](../sith/model/model3doImporter.py) |
| Model export and mesh sync | [model3doExporter.py](../sith/model/model3doExporter.py) |
| Node normalization | [model3do.py](../sith/model/model3do.py), `Model3do.reorderNodes` |
| Transforms, helpers and metadata | [model/utils.py](../sith/model/utils.py) |
| Resource search | [utils.py](../sith/utils.py) |
| Animation import | [keyImporter.py](../sith/key/keyImporter.py) |
| Animation sampling/export | [keyExporter.py](../sith/key/keyExporter.py) |
| Slots, FPS, markers and jump cache | [keyUtils.py](../sith/key/keyUtils.py) |

[Core tests](../tests/README.md) exercise codecs without Blender; app tests exercise
real Blender data and UI contracts. [Batch checks](../tests/batch/README.md)
compare original resources with imported/exported geometry, hierarchy, UVs and
sampled animation poses. Preserve/sync combinations test index relationships;
absolute-UV negative controls verify that disabling a required conversion really
changes the result. A successful round trip is not a license to silently repair
malformed sources or count skipped inputs as passes.
