# Technical Documentation

Use [USAGE](../USAGE.md) for interactive options. These pages describe the data
behind those options and the transformations performed by the add-on.

```text
                        Files on disk
                              |
                 +------------+------------+
                 |                         |
          Text tokenizers             Binary codecs
                 |                         |
                 +------------+------------+
                              |
                    Resource data objects
                  Model3do / Key / material
                              |
                      Blender adapters
                              |
              Objects, meshes, images, actions
```

| Question | Read |
| --- | --- |
| Which formats and versions are supported? | [Format index](formats/README.md) |
| What is stored in a model, and at which byte offsets? | [3DO models](formats/3do.md) |
| How are joint motion, deltas and markers represented? | [KEY animations](formats/key.md) |
| How do MAT pixels, cels, mipmaps and CMP palettes fit together? | [Materials and palettes](formats/materials.md) |
| How do scene objects become joints, and what does sync reorder? | [Blender pipeline](blender-pipeline.md) |
| Why does import/export require baking or reject an animation? | [Compatibility notes](blender-compatibility.md) |
| How is compatibility checked? | [Tests](../tests/README.md) and [asset verification](../tests/batch/README.md) |

## Reading The Layouts

- Binary offsets are decimal byte offsets relative to the enclosing record,
  unless explicitly described as file offsets.
- `u32`, `i32` and `f32` mean unsigned 32-bit integer, signed 32-bit integer and
  IEEE-754 single-precision float. The supported binary resources are
  little-endian; there is no implicit native-structure alignment.
- `vec2f` and `vec3f` occupy 8 and 12 bytes. Array sizes use the preceding count.
- A fixed name field is ASCII up to its first NUL, or the entire field when
  full. Unchanged binary names can retain original padding after the NUL.
- **Opaque** means retained bytes with no asserted meaning. A pointer-like word
  is not permission to seek to that address. Conditional records are read from
  the current stream position.
- Tables describe the supported serialization contract. Enum labels describe
  the toolkit's interpretation; title-specific engine behavior is called out
  separately rather than assumed to apply to every game.

## Preservation Boundaries

```text
original file -> decoded resource -> same-format codec write
                    |
                    +-> Blender scene -> newly generated resource -> file
                        editing boundary
```

A codec can preserve opaque fields and original numeric values without Blender
being able to represent them all. Blender round trips rebuild geometry and
animation: LOD 0 is edited, pivots are baked, face normals follow geometry, and
curves are sampled. Byte identity and equivalent visible poses are therefore
different checks. The [pipeline guide](blender-pipeline.md) lists these boundaries
and the conditions for reusing binary metadata.

These references are checked against the implementation and synthetic tests.
External reconstruction references are linked where useful, but unknown fields
remain unknown. Proprietary assets are not included, and serialization or
frame-domain pose checks do not establish native-engine timing or blending.

## Release And File Versions

The add-on release version is separate from resource versions. Text 3DO writes
the selected `3DO 2.1`, `3DO 2.2` or `3DO 2.3` field; text KEY has no corresponding
format-version field. The Blender exporters obtain their leading creator comment
from `getExportFileHeader` in [utils.py](../sith/utils.py), which reads and caches
the installed manifest's version and maintainer. Core writers instead accept a
caller-supplied comment. Binary MODL/FYEK have no creator-comment field, and MAT
continues to use format version `0x32`, independently of the add-on release.
Missing/invalid manifest metadata uses the helper's fallback. Because metadata
is cached, a fresh process is needed when checking a changed release manifest.

## Evidence Levels

| Evidence | Establishes | Does not establish |
| --- | --- | --- |
| Core codec tests | Supported parsing, field layouts, encoding and rejection cases | Blender representation or game behavior |
| Blender app tests | Scene conversion, selection, editable data and sampled poses | Native renderer, event handling or playback blending |
| Asset batch checks | The explicitly tested corpus, options and reported exceptions | Untested assets, game revisions or skipped/rejected inputs |
| Engine source inspection | Behavior of the particular inspected implementation/path | Execution of a retail game or equivalence across engines |

The [format index](formats/README.md) separates game-family choices from format
support. Tests named in these guides are regression coverage, not a claim that
every suite, Blender release or native game was run for a documentation edit.
