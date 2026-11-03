# MAT Materials And CMP Palettes

[Technical index](../README.md) | [Formats](README.md) | [Resource lookup](../blender-pipeline.md#resource-lookup)

MAT describes solid palette colors or texture cels. CMP supplies the RGB palette
for indexed pixels. A cel is an alternative texture image; a mip level is a
smaller version **within** that cel. The two counts are not interchangeable.

- [MAT header](#mat-header)
- [Records, cels and mipmaps](#records-and-texture-payload)
- [Pixel decoding](#pixel-decoding)
- [CMP layout and palette selection](#cmp-layout-and-palette-selection)
- [Blender material binding](#blender-material-binding)

```text
3DO face --material index--> MAT name
                                |
                    +-----------+-----------+
                    |                       |
               solid color               textures
             palette index                cel 0
                    |                       +-- mip 0 (largest)
                    |                       +-- mip 1
                    |                       +-- ...
                    |                     cel 1 ...
                    |                       |
                    +--> CMP palette <------+ indexed pixels only
                              |
                         Blender RGBA
```

The add-on imports MAT/CMP; it does not export edited Blender materials back to
MAT. 3DO export writes material references, not embedded image bytes. Grim
BM/ZBM scene bitmap/depth resources are separate formats, not MAT substitutes.

## MAT Header

Numbers are little-endian. The common header is **76 bytes**: a 20-byte prefix
followed by fourteen 32-bit color-format words.

| Offset | Storage | Field |
| ---: | --- | --- |
| 0 | 4 bytes | `MAT `, including trailing space |
| 4 | i32 | Version `0x32` |
| 8 | u32 | Material type |
| 12 | i32 | Record count |
| 16 | i32 | Texture count |
| 20 | u32 | Color mode: 0 indexed, 1 RGB, 2 RGBA |
| 24 | u32 | Bits per pixel: 8, 16, 24 or 32 |
| 28 | u32 | Red channel bit count |
| 32 | u32 | Green channel bit count |
| 36 | u32 | Blue channel bit count |
| 40 | u32 | Red bit position (`red_shl`) |
| 44 | u32 | Green bit position (`green_shl`) |
| 48 | u32 | Blue bit position (`blue_shl`) |
| 52 | u32 | Red shift-right metadata |
| 56 | u32 | Green shift-right metadata |
| 60 | u32 | Blue shift-right metadata |
| 64 | u32 | Alpha channel bit count |
| 68 | u32 | Alpha bit position (`alpha_shl`) |
| 72 | u32 | Alpha shift-right metadata |

| Material type | Form |
| ---: | --- |
| 0 | Solid palette-color records |
| 2 | Standard texture records and mip chains |
| 3 | Grim indexed texture variant |

Textured files require record count to equal texture count. Type 3 requires
indexed 8-bit color. Unused packed-channel words in indexed headers can contain
arbitrary values; they are not evidence of an RGB/alpha layout for those pixels.

## Records And Texture Payload

### Type 0: Palette Colors

Each color record is **24 bytes**, six `i32` words:

```text
+0   record type
+4   palette index (0..255)
+8   opaque word
+12  opaque word
+16  opaque word
+20  opaque word
```

The palette index selects the solid color. Blender represents it with a generated
32x32 image; that size is an implementation convenience, not a texture dimension
serialized in this record.

### Type 2: Standard Textures

Each texture record is **40 bytes**, ten `i32` words:

```text
+0   record type
+4   palette/color-index field
+8   opaque words[7]                  28 bytes
+36  cel index
```

The image payload follows **all** records, not each individual record:

```text
+-------------------------+ offset 0
| common header           | 76 bytes
+-------------------------+ offset 76
| texture records[R]      | 40*R bytes
+-------------------------+ offset 76 + 40*R
| cel 0 mip header        | 24 bytes
| cel 0 mip 0 pixels      |
| cel 0 mip 1 pixels      |
| ...                     |
+-------------------------+
| cel 1 mip header/pixels |
| ...                     |
+-------------------------+
```

### Type 3: Grim First-Record Variants

Only the **first** record changes size. Its first word is a tag, with these
supported layouts; subsequent records use 40 bytes:

| First tag | First record size | Remaining record sizes | First texture header offset |
| ---: | ---: | ---: | --- |
| 0 | 24 bytes | 40 bytes each | `60 + 40*celCount` |
| 8 | 40 bytes | 40 bytes each | `76 + 40*celCount` |

```text
type 3, compact first record, two cels:
  header[76] + record0[24] + record1[40] -> texture data at byte 140

type 3, full first record, two cels:
  header[76] + record0[40] + record1[40] -> texture data at byte 156
```

Do not shorten every record or skip an extra block before the pixels. Some
resources have additional trailer bytes; the importer does not use that trailer
as a substitute embedded palette. Indexed colors still use the selected CMP.

### Cel Mip Header

Each cel starts with six `i32` fields, **24 bytes** total:

| Offset | Field |
| ---: | --- |
| 0 | Base width `W` |
| 4 | Base height `H` |
| 8 | Transparency enabled |
| 12 | Opaque word |
| 16 | Transparent palette index |
| 20 | Mip level count `L`, including the base image |

```text
width(level)  = max(1, W >> level)
height(level) = max(1, H >> level)
bytes(level)  = width(level) * height(level) * (bitsPerPixel / 8)

cel size = 24 + sum(bytes(level), level = 0 .. L-1)
```

Dimensions must be positive. A chain may be partial; it cannot contain more
than `floor(log2(max(W,H))) + 1` levels. Both axes clamp **independently** to one:

```text
example: 8x4, 16 bits/pixel, four levels

level     dimensions      bytes
  0          8x4            64
  1          4x2            16
  2          2x1             4
  3          1x1             2
                            --
pixel payload               86
cel header                  24
                           ---
whole cel                  110 bytes
```

When no CMP is available, all indexed pixel bytes are still consumed using this
calculation. Otherwise the next cel's header would be read from the wrong place.
Blender creates each cel's image at its base dimensions and uses the top mip;
lower levels are read but are not exposed as separate editable images.

## Pixel Decoding

### Indexed

Each byte selects one of 256 CMP RGB entries:

```text
pixel byte i -> palette[i] = (R,G,B) -> (R/255, G/255, B/255, A)

A = 0 if cel transparency is enabled and i == transparentPaletteIndex
    1 otherwise
```

Index zero is common in Grim assets, but the header supplies the transparent
index; do not hardcode zero for every MAT. Indexed transparency comes from the
cel header, not `alpha_bpp` in an unused color-format word. A missing palette
produces a size-correct placeholder rather than guessed colors.

### Packed RGB And RGBA

For each nonempty channel:

```text
maximum = (1 << channelBitCount) - 1
channel = ((pixelWord >> channelBitPosition) & maximum) / maximum
```

Missing RGB channels default to zero; missing alpha defaults to one. Channel
layouts must fit within the pixel width. Sixteen-/32-bit words are decoded
little-endian; RGB24 is read from its three stored bytes before channel extraction.
Examples of channel masks follow; the header, not the name, defines the format:

| Common layout | Red | Green | Blue | Alpha |
| --- | --- | --- | --- | --- |
| RGB565 | bits 11..15 | bits 5..10 | bits 0..4 | Absent |
| ARGB1555 | bits 10..14 | bits 5..9 | bits 0..4 | bit 15 |
| ARGB4444 | bits 8..11 | bits 4..7 | bits 0..3 | bits 12..15 |

Normalization uses the full channel range: `31/31 = 1` and `15/15 = 1`.
It does not first expand into an 8-bit byte with lost low bits (`248/255`,
`240/255`). Shift-right metadata is not the normalization divisor.

Decoded image rows are vertically flipped for Blender image storage. This is
separate from the model adapter's UV V-sign conversion; it is not a reason to
apply an extra `1-v` transform to UVs. Values are normalized numerically here;
this does not establish a separate palette gamma or color-management transform.

## CMP Layout And Palette Selection

The supported header versions are `0x14` and `0x1e`. Do not infer the title solely
from that value. The reader consumes the following prefix:

| File offset | Storage | Field |
| ---: | --- | --- |
| 0 | 4 bytes | `CMP `, including trailing space |
| 4 | i32 | Version |
| 8 | i32 | Has-alpha-table indicator |
| 12 | 52 bytes | Opaque header data |
| 64 | 256 RGB byte triples | Palette, 768 bytes |
| 832 | Remaining bytes | Additional tables, not decoded by this importer |

```text
CMP file
  header[64] + RGB palette[768] + optional additional tables
               |
               +-- index 0:   R G B
               +-- index 1:   R G B
               ...
               +-- index 255: R G B
```

Only the RGB palette is used. The alpha-table indicator does not turn every
palette entry into a serialized RGBA quadruple; MAT cel transparency is handled
as described above. Header or palette truncation is rejected.

A model does not name its CMP. Select the palette from the game's scene/costume
context, or supply a known palette explicitly. Named defaults `dflt.cmp` and
`dfltcmp.cmp` are searched when no name is supplied; an arbitrary palette is not
chosen from a directory containing several candidates. See
[resource lookup](../blender-pipeline.md#resource-lookup) for the search order.

## Blender Material Binding

Each cel has an image ID binding `_sith_mat_cel_<index>` on the material. Cel 0
feeds the ordinary material view. ID bindings survive renaming; an unrelated
image with the same display name is not a valid substitute. Each cel keeps its
own alpha-link decision even when another cel makes the material transparent.

Reloads reuse the bound images where editable, copy linked images before editing,
and remove stale numbered bindings when the new file has fewer cels. Missing
pixels do not erase material names or texture dimensions needed for UV conversion.
A valid textured MAT without a CMP can therefore still supply UV dimensions.

Implementation: [MAT reader and Blender adapter](../../sith/material/mat.py),
[CMP reader](../../sith/material/cmp.py). Grim's record variants are also checked
against [ScummVM's material reader](https://github.com/scummvm/scummvm/blob/master/engines/grim/material.cpp)
and original compact/full resources.
