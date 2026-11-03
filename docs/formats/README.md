# Resource Formats

This reference describes formats supported by Blender-Sith, not every resource
consumed by the original engines. Layout facts are separated from Blender
workflow limitations; proprietary game assets are not part of this documentation.

| Resource | Supported forms | Reference |
| --- | --- | --- |
| 3DO model | Sith text 2.1/2.2/2.3; Grim text extensions; Grim MODL binary | [3DO](3do.md) |
| KEY animation | Sith/Grim text; Grim FYEK binary | [KEY](key.md) |
| MAT material | Palette-color, indexed and RGB/RGBA Sith variants; Grim indexed variants | [Materials](materials.md) |
| CMP palette | Versions 0x14 and 0x1e | [Materials](materials.md) |

JKDF2, Mysteries of the Sith and DroidWorks use the text 2.1 model family.
Infernal Machine adds text 2.2 RGB and 2.3 RGBA vertex lighting. Grim Fandango
uses both text and binary model/animation resources.

The UI option **v2.1 Absolute UV** applies to the absolute pixel-space texture
coordinates used by JKDF2, MOTS, DroidWorks and Grim, including Grim binary models.
It is independent of hierarchy ordering and animation export targets.

Blender supports edited LOD 0 and baked pivots. The resource codecs can retain
additional serialized data without implying that Blender edits or reproduces it.
See [USAGE](../../USAGE.md) for interactive options, the
[Blender pipeline](../blender-pipeline.md) for conversions and synchronization,
and [tests](../../tests/README.md) for validation. The
[technical documentation index](../README.md) defines layout notation and
preservation boundaries.
