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
