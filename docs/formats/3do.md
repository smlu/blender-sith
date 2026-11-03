# 3DO Models

[Technical index](../README.md) | [Formats](README.md) | [Blender pipeline](../blender-pipeline.md)

3DO stores a model's material table, geometry sets and joint hierarchy. Text
versions 2.1, 2.2 and 2.3 share a grammar; Grim Fandango also uses binary MODL
resources. Detection uses file contents, not the filename extension.

- [Data model and indices](#data-model-and-index-domains)
- [Text grammar and modes](#text-layout)
- [Grim rendering controls](#grim-rendering-controls)
- [Binary stream and records](#grim-binary-modl)
- [Validation and round trips](#validation-and-round-trips)

## Data Model And Index Domains

```text
Model3do
  +-- materials[] <----------------------- face.materialIdx
  +-- geosets[]
  |     +-- meshes[] <-------------------- node.meshIdx
  |           +-- vertices[] <------------ face.vertexIdxs[]
  |           +-- vertexColors[]          one per vertex
  |           +-- normals[]               one per vertex
  |           +-- uvs[] <----------------- face.uvIdxs[]
  |           +-- faces[]                 ordered polygon corners
  +-- meshHierarchy[] <------------------- parent / child / sibling links
  +-- radius
  +-- insertOffset
```

**A hierarchy node is a joint, not a mesh.** A joint can reference a mesh or use
`meshIdx = -1` to remain meshless. KEY animations address joint indices, not mesh
indices. Likewise, a face's UV indices are independent of its vertex indices:
one geometric vertex can have different UVs on adjacent faces.

Geosets provide alternative geometry, commonly LODs. The resource model can hold
them all; Blender imports/exports **geoset 0 only**. A valid hierarchy can refer
to a parent appearing later in the node array; stream order alone is not ancestry.

## Text Layout

Sections appear in the order below. Keywords are case-insensitive; `#` introduces
a comment. Counts and indexed rows delimit the arrays. The schematic uses
placeholders such as `V` and `N`, not literal file tokens.

```text
SECTION: HEADER
3DO 2.1

SECTION: MODELRESOURCE
MATERIALS M
  0: material.mat
  ...

SECTION: GEOMETRYDEF
RADIUS radius
INSERT OFFSET x y z
GEOSETS G
  GEOSET 0
  MESHES K
    MESH 0
    NAME mesh_name
    RADIUS radius
    [SHADOW value]                  optional Grim extension
    GEOMETRYMODE mode
    LIGHTINGMODE mode
    TEXTUREMODE mode
    VERTICES V
      i: x y z <vertex lighting>
    TEXTURE VERTICES T
      i: u v
    VERTEX NORMALS
      i: nx ny nz                  V rows, no separate count
    FACES F
      i: mat flags geo light tex <extra light> C v0,t0 v1,t1 ...
    FACE NORMALS
      i: nx ny nz                  F rows, no separate count
    ...                            next mesh / geoset

SECTION: HIERARCHYDEF
HIERARCHY NODES N
  i: flags type mesh parent child sibling children pos rot pivot name
```

The final hierarchy row expands to:

```text
i: flags typeMask meshIdx parentIdx firstChildIdx nextSiblingIdx numChildren
   posX posY posZ pitch yaw roll pivotX pivotY pivotZ nodeName
```

It is written as one row. `-1` means no mesh/link where applicable. Position and
pivot are XYZ vectors; orientation is **pitch, yaw, roll in degrees**. The
insertion offset is model-level placement, separate from the root joint's pose.

### Version Differences

| Property | 2.1 | 2.2 | 2.3 |
| --- | --- | --- | --- |
| Vertex lighting fields | `intensity` | `r g b` | `r g b a` |
| Face extra-light fields | `intensity` | `r g b` | `(r/g/b/a)` |
| Usual texture units | Absolute pixels | Normalized | Normalized |
| Typical consumers | JKDF2, MOTS, DroidWorks, Grim text | Infernal Machine | Infernal Machine |

These colors are lighting data, not the MAT texture pixels. Scalar intensity is
decoded to equal RGB components with alpha 1. Writing 2.1 averages RGB as
`(r + g + b) / 3`; writing 2.2 drops alpha. Converting versions can therefore lose
color information intentionally. Enable **v2.1 Absolute UV** for pixel-space
resources; see the [UV conversion](../blender-pipeline.md#uv-conversion) example.

Grim text can include `SHADOW` and lighting mode 6. The core writer supports that
extension. Ordinary Sith text export from Blender omits `SHADOW` from its
temporary output rather than emitting Grim-only grammar into other engines.

Text mesh `NAME` permits spaces; material and hierarchy names are token fields.
Long names are not silently truncated. The text writer warns about compatibility
lengths: 31 characters for 2.1 names, 63 for 2.2/2.3 model/material/mesh names and
127 for 2.2/2.3 joint names. These warnings differ from fixed binary field limits.

### Render Modes And Face Flags

Mesh defaults and per-face records both carry modes. The stored integer is not
an instruction to change Blender's viewport shading mode.

| Geometry | Label | Lighting | Label | Texture | Label |
| ---: | --- | ---: | --- | ---: | --- |
| 0 | Not drawn | 0 | Fully lit | 0 | Affine |
| 1 | Vertices | 1 | Not lit | 1 | Perspective |
| 2 | Wireframe | 2 | Diffuse | 2 | Unknown (2) |
| 3 | Solid | 3 | Gouraud | 3 | PerspectiveCorrected |
| 4 | Textured | 6 | Mesh intensity, Grim | | |

The historical identifiers `GfUnknown6` and `PerspectiveUnknown` remain unchanged
for saved Blender properties and Python callers. Their display names explain
the known behavior, rather than imply that mode 2 has a verified perspective
algorithm. `PerspectiveCorrected` is also a toolkit label, not proof that every
engine uses the same algorithm for mode 3.

| Face flag | Toolkit interpretation | Scope of this meaning |
| ---: | --- | --- |
| `0x01` | Double sided | Shared Sith face flag |
| `0x02` | Translucent | Shared Sith face flag |
| `0x04`, `0x08` | Clamp texture X / Y | Infernal Machine |
| `0x10` | Disable bilinear filtering; use nearest | Infernal Machine |
| `0x20` | Disable Z writes | Infernal Machine |
| `0x40` | Ledge | Infernal Machine |
| `0x100` | Fog enabled | Infernal Machine |
| `0x200` | Whip aim | Infernal Machine |

The UI marks the Infernal Machine meanings with an **(IJIM)** suffix, including
clamping, filtering and depth writes. A shared 3DO version does not imply shared flag
semantics. These labels must not be applied to JKDF2, MOTS, DroidWorks or Grim
Fandango without engine-specific evidence, nor do they mean those engines ignore
the corresponding bits. For example, bit `0x10` instead forces lighting mode 1
in [OpenJKDF2's MOTS draw path](https://github.com/shinyquagsire23/OpenJKDF2/blob/master/src/Primitives/rdModel3.c)
and in the supplied Grim executable's `rdModel3_DrawFace`; the latter was checked
against machine code. It is not a nearest-filter flag in those paths.

The toolkit retains the raw mask, including unknown `0x80` and higher bits, in
all supported formats. Changing a known checkbox edits only its bit. Display
labels do not rename saved identifiers, remove incompatible bits on export or
emulate these engine flags in Blender's viewport.

Hierarchy node flags are retained as raw bit fields. Grim's use of flag `0x2`
is described below; it must not be generalized to other games. Node **type** is
a separate mask:
`0x1` torso, `0x2/0x4` left/right arm, `0x8` head, `0x10` hip,
`0x20/0x40` left/right leg, `0x80/0x100` left/right hand, `0x400` vehicle,
`0x800` back part and `0x1000` front part. These are toolkit labels used for
animation priority selection, not a bitset of joint indices or universal anatomy
for every game. Other named unknown bits must not be assigned guessed meanings.

## Grim Rendering Controls

These observations come from the supplied symbol-bearing Linux executable and
the corresponding decompilation, checked against its machine code where noted.
They describe inspected paths, not native-runtime tests of every renderer or a
claim that recovered descriptive names are original enum spellings.

### Text Version Versus Binary Format

Grim's `rdModel3_WriteText` emits `3DO 2.1`. The binary writer instead emits the
MODL stream below, without a text-version field. The export choice **Grim
Fandango** writes binary MODL. Its scalar lighting and pixel-space UVs resemble
the text 2.1 representation, but that does not make a binary file a text file
with a different header. Its fixed name fields also have their own sizes.

### Mesh Shadow Flag

`SHADOW` controls participation in a separate projected actor-shadow pass:

```text
mesh bounds + nonzero SHADOW
            |
rdModel3_BuildShadowModel
            | builds a 16-vertex proxy from min/max bound components
            v
sputCostume_DrawActorShadow
            | checks actor/component state, mesh flag and visibility
            v
sputCostume_DrawMeshShadow
            | transforms proxy by joint matrix
            | projects it from the shadow source onto a receiver plane
            v
sputCostume_OutputShadowPoly
            | clips projected quads against walk-plane regions
            v
shadow geometry / software cache
```

The shadow is based on a coarse bounds-derived proxy, not necessarily the actual
mesh silhouette. A nonzero flag alone does not configure the actor's shadow
source, receiver planes or scene state. Clearing it removes that mesh from this
path; it does not hide the ordinary mesh, change its material alpha, or toggle
Blender ray-traced/viewport shadows. The inspected ordinary mesh draw path is
separate. These branches are confirmed in the Linux machine code, not inferred
solely from the word `SHADOW` in the file.

### Lighting Mode 6

In Grim's inspected software path, `rdModel3_DrawMeshImpl` handles lighting mode
6 specially: it skips the ordinary mesh-lighting calculation and copies the
cached `meshIntensity` into each face's `extraLight` field. This is distinct from
recalculating vertex intensities for Gouraud mode 3.

`rdModel3_DrawHNode` supplies a clear use case. For a joint with node flag `0x2`,
it walks up past ancestors with the same flag, copies the selected ancestor
mesh's cached intensity, and sets this mesh's lighting mode to 6 before drawing:

```text
ancestor mesh: calculate/cache intensity
            |
descendant joint with flag 0x2
            | copy ancestor meshIntensity; select mode 6
            v
descendant mesh: reuse intensity as per-face extra light
```

This can keep attached parts using a common lighting value. The UI calls it
**Mesh Intensity (Grim Fandango)**; it is not an independent Blender shading mode,
nor a promise that every face becomes unlit or every renderer handles it alike.
The flag test, ancestor traversal, mode assignment and intensity copy are also
confirmed in the Linux machine code. The original enum spelling is not known.

### Texture Mode 2

The exact meaning remains unresolved. The inspected code reads/writes the integer
and combines global, thing, mesh and face modes, but that does not establish a
particular projection equation for value 2. The available software draw paths
clearly distinguish affine mode 0 and perspective mode 1; they do not justify
renaming mode 2 to a supposedly verified interpolation variant.
The related [OpenJKDF2 enum](https://github.com/shinyquagsire23/OpenJKDF2/blob/master/src/types_enums.h)
also leaves value 2 unknown; that is a cross-check on the naming uncertainty,
not proof of identical behavior in Grim.

The UI therefore shows **Unknown (2)** and retains the original value on export.
The old `PerspectiveUnknown` identifier remains for .blend compatibility. Leave
an imported value unchanged unless the target engine's requirements are known.
This field is independent of absolute-pixel versus normalized UV units.

## Grim Binary MODL

All numbers are little-endian. The on-disk magic is **`LDOM`**, not the literal
string `MODL`. There is no separate version word. See [notation](../README.md#reading-the-layouts).

```text
byte 0  +---------------------------------------+
        | 'LDOM'                           4 B  |
        | materialCount                    u32  |
        | materialNames[materialCount]    32 B ea|
        | modelName                       32 B  |
        | opaque geoset pointer word       u32  |
        | geosetCount                      u32  |
        +---------------------------------------+
        | for each geoset:                      |
        |   meshCount                      u32  |
        |   mesh records[meshCount]    variable |
        +---------------------------------------+
        | opaque node pointer word         u32  |
        | nodeCount                        u32  |
        | node records[nodeCount]      variable |
        +---------------------------------------+
        | model radius                     f32  |
        | opaque footer                   36 B  |
        | insertion offset               vec3f  |
EOF     +---------------------------------------+
```

The footer is **52 bytes**. The insertion offset occupies its final 12 bytes,
after the 36 opaque bytes, not immediately after radius. This differs from the
early 3doobj reader's layout. Material/model/mesh names occupy 32-byte ASCII
fields; node names occupy 64 bytes. A completely full field need not end in NUL.

### Mesh Record

Offsets below are relative to the start of a mesh. `V`, `T` and `F` are its vertex,
UV and face counts. The first variable array starts at offset 60.

| Offset | Storage | Field |
| ---: | --- | --- |
| 0 | 32 bytes | Mesh name |
| 32 | u32 | Opaque word |
| 36 | u32 | Geometry mode |
| 40 | u32 | Lighting mode |
| 44 | u32 | Texture mode |
| 48 | u32 | `V` |
| 52 | u32 | `T` |
| 56 | u32 | `F` |

```text
mesh +60
  positions[V]             vec3f[V]          12*V bytes
  UVs[T]                   vec2f[T]           8*T bytes
  intensities[V]           f32[V]             4*V bytes
  opaque vertex words[V]   u32[V]             4*V bytes
  faces[F]                 variable
  vertex normals[V]        vec3f[V]          12*V bytes
  shadow                   u32                  4 bytes
  cached mesh intensity    f32                  4 bytes
  mesh radius              f32                  4 bytes
  mesh-local bounds        vec3f min, max       24 bytes
```

Normals follow faces in binary, unlike the text order. The trailing mesh block
is 36 bytes, so total mesh size is:

```text
96 + 32*V + 8*T + sum(size of each face)
```

The inspected engine's binary reader/writer and shadow builder identify the
footer cache as `meshIntensity` and the 24 bounds bytes as mesh-local axis-aligned
`minXYZ`, then `maxXYZ`. The codec still retains both in raw metadata (`unknown3`
for the intensity's bits, `bounds` for the six floats), rather than rewriting
cache values during a byte-preserving round trip. Per-vertex metadata words
remain uninterpreted. Native `rdModel3_LoadPostProcess` recalculates bounding boxes
before building shadow proxies; retaining cache bytes is not a promise that
they describe arbitrary subsequent Blender geometry edits.

### Face Record

The fixed prefix is **76 bytes**. Following arrays are separate contiguous
arrays, not interleaved vertex/UV pairs as in text.

| Offset | Storage | Field |
| ---: | --- | --- |
| 0 | u32 | Stored face ID, retained |
| 4 | u32 | Face flags |
| 8 | u32 | Geometry mode |
| 12 | u32 | Lighting mode |
| 16 | u32 | Texture mode |
| 20 | u32 | Corner count `C` |
| 24 | u32 | Opaque word |
| 28 | u32 | UV-array presence word |
| 32 | u32 | Material-index presence word |
| 36 | 12 bytes | Opaque data |
| 48 | f32 | Extra intensity |
| 52 | 12 bytes | Opaque data |
| 64 | vec3f | Face normal |
| 76 | u32[C] | Vertex indices |
| variable | u32[C] | UV indices, only if UV presence word is nonzero |
| variable | u32 | Material index, only if material presence word is nonzero |

```text
size = 76 + 4*C + (UVs present ? 4*C : 0) + (material present ? 4 : 0)

example: triangle, UVs and material -> 76 + 12 + 12 + 4 = 104 bytes
```

Presence words can contain non-boolean pointer-like values. They indicate that
data follows **here**, not at the word's numeric address. The codec retains the
original word while its presence state is unchanged. Absent UVs decode to `-1`
corner references; absent material decodes to `-1`.

### Hierarchy Node Record

The fixed prefix is **184 bytes**. The node's own index is its position in the
stream, not a separately stored field.

| Offset | Storage | Field |
| ---: | --- | --- |
| 0 | 64 bytes | Joint name |
| 64 | u32 | Node flags |
| 68 | u32 | Opaque word |
| 72 | u32 | Node type mask |
| 76 | i32 | Mesh index; `-1` for no mesh |
| 80 | u32 | Depth |
| 84 | u32 | Parent-link presence word |
| 88 | u32 | Number of children |
| 92 | u32 | First-child-link presence word |
| 96 | u32 | Next-sibling-link presence word |
| 100 | vec3f | Pivot |
| 112 | vec3f | Local position |
| 124 | vec3f | Pitch, yaw, roll in degrees |
| 136 | 48 bytes | Opaque cached-transform data |
| 184 | conditional u32 | Parent index, if present |
| variable | conditional u32 | First-child index, if present |
| variable | conditional u32 | Next-sibling index, if present |

```text
node size = 184 + 4*(parent present + child present + sibling present)
                       each presence term is 0 or 1
```

Links appear in parent, child, sibling order, omitting absent ones. Parent/child
relationships determine depth; the writer recomputes it. The 48 cached bytes are
not treated as an authoritative editable transform or dereferenced as pointers.

## Validation And Round Trips

| Layer | Behavior |
| --- | --- |
| Binary codec | Retains geosets, opaque data, original padding and presence words where applicable; rejects truncation, unsafe counts/references, malformed hierarchy and trailing bytes |
| Blender preflight | Requires representable finite transforms and usable topology before replacing the scene; a binary record alone is not proof that Blender can make a polygon from it |
| Blender export | Rebuilds LOD 0 geometry, links and mesh radii; keeps compatible imported metadata, not arbitrary byte identity |
| Text recovery | Opt-in partial parsing, retaining recoverable completed data with warnings; not an assertion that the source was valid |
| Binary recovery | Not supported; truncated MODL records are rejected |

The codec can retain zero-corner binary face records that are not Blender
polygons. Repeated corners and zero-area faces in original text resources are
not automatically treated as syntax corruption; adapter/topology checks are
separate from parsing.

Some geometry-free retail skeletons store positive infinity as an unused model
radius. The codec retains this sentinel only without vertices. Blender uses
finite zero bounds and restores the sentinel on binary export only while the
model remains empty. Infinite bounds on real geometry are not accepted.

Blender bakes source pivots into vertices, recalculates face normals and may split
vertices at color/normal seams. Vertex normals retain original binary precision
while unedited. See [conversion boundaries](../blender-pipeline.md#preservation-and-limitations)
before interpreting byte differences as geometry errors.

## Materials And Implementation

3DO references MAT names, not a CMP palette. Grim scene/costume context assigns
the palette; for example `action_manny.3do` uses `action.cmp` through `ma.cos`.
Many CMPs in one directory do not establish a universal default. See
[materials](materials.md) and the [lookup flow](../blender-pipeline.md#resource-lookup).

Implementation: [resource objects](../../sith/model/model3do.py),
[text reader](../../sith/model/model3doLoader.py),
[text writer](../../sith/model/model3doWriter.py),
[binary codec](../../sith/model/model3doBinary.py).
The binary reconstruction uses [3doobj's declarations](https://github.com/cplhenshaw/3doobj/blob/master/modl.h)
and is cross-checked against [ScummVM's Grim model reader](https://github.com/scummvm/scummvm/blob/master/engines/grim/model.cpp)
and original resource layouts. Unknown bytes are deliberately not promoted to
documented semantics based only on their resemblance to a C structure.
