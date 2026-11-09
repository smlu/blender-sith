# Resource Formats

This reference describes formats supported by Blender-Sith, not every resource
consumed by the original engines. Layout facts are separated from Blender
workflow limitations; proprietary game assets are not part of this documentation.

| Resource | Supported forms | Reference |
| --- | --- | --- |
| 3DO model | Sith text 2.1/2.2/2.3; Grim text extensions; Grim MODL binary | [3DO](3do.md) |
| KEY animation | Shared Sith/Grim text grammar; Sith text playback interpretation; Grim FYEK binary | [KEY](key.md) |
| MAT material | Version 0x32 (50): palette-color, indexed and RGB/RGBA Sith variants; Grim indexed variants | [Materials](materials.md) |
| CMP palette | Versions 0x14 and 0x1e | [Materials](materials.md) |

JKDF2, Mysteries of the Sith and DroidWorks use the text 2.1 model family.
Infernal Machine adds text 2.2 RGB and 2.3 RGBA vertex lighting. Grim Fandango
uses both text and binary model/animation resources.

## Game Families And Export Choices

| Game family | 3DO output | KEY target | Material boundary |
| --- | --- | --- | --- |
| Jedi Knight: Dark Forces II | Text 2.1 | JKDF2 | Legacy indexed MAT/CMP; other reader-supported encodings are not a game guarantee |
| Mysteries of the Sith | Text 2.1 | MOTS | Legacy indexed MAT/CMP; version-10 MAT is unsupported |
| DroidWorks | Text 2.1 | No dedicated target; Generic needs independent limit checks | Indexed MAT/CMP; no native-game certification here |
| Indiana Jones and the Infernal Machine | Text 2.2 or 2.3 | IJIM (default) | Packed RGB/RGBA; selected indexed output requires its CMP on reload |
| Grim Fandango | Binary MODL; ordinary text 2.1 output omits Grim SHADOW | GRIM writes FYEK | Type-3 indexed MAT, explicit scene/costume CMP, base mip only on export |

The 3DO dialog defaults to text 2.3, independently of the KEY target. File
versions are not retail game revision numbers or the add-on release version.
There is no per-patch/platform compatibility matrix: codec/app tests do not
certify all game editions. In particular, parsed Grim text KEY does not select
FYEK's global flag semantics. See [KEY interpretation](key.md#text-layout) and
[evidence boundaries](../README.md#evidence-levels).

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
