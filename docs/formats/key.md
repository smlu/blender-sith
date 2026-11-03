# KEY Animation

[Technical index](../README.md) | [Formats](README.md) | [Blender animation pipeline](../blender-pipeline.md#animation-import-and-export)

KEY stores local joint motion and timed event markers. A track's index addresses
an entry in the 3DO **hierarchy**, not its mesh array. `JOINTS` counts the full
skeleton; the list of animated tracks can be smaller.

- [Text grammar and interpolation](#text-layout)
- [Binary header and records](#grim-binary-fyek)
- [Export targets and preservation](#export-targets-and-preservation)

```text
KEY
 +-- flags / priority type mask / frame count / FPS / joint count
 +-- markers[]                (frame, event type)
 +-- nodes[]                  (joint index, name)
       +-- entries[]          (frame, flags, position, orientation, deltas)

node index --same joint domain--> 3DO.meshHierarchy[index]
```

## Text Layout

The required sections are HEADER and KEYFRAME NODES, in that order. MARKERS is
optional and precedes KEYFRAME NODES. Keywords are case-insensitive; comments
start with `#`. This is a schematic, not a literal test vector:

```text
SECTION: HEADER
FLAGS  flags
TYPE   nodeTypeMask
FRAMES frameCount
FPS    framesPerSecond
JOINTS jointCount

SECTION: MARKERS
MARKERS markerCount
  frame eventType
  ...

SECTION: KEYFRAME NODES
NODES trackCount
  NODE jointIndex
  MESH NAME jointName
  ENTRIES entryCount
    i: frame flags posX posY posZ pitch yaw roll
                   dPosX dPosY dPosZ dPitch dYaw dRoll
  ...
```

The delta line continues the same entry; it is not a second timestamp. Positions
and deltas use XYZ. Angles and angular deltas use pitch/yaw/roll in degrees.
**Entry and marker frames are floats**, including fractional values. Frame and
joint counts are integers. Deltas are **per frame**, not per second.

### Sith Entry Interpolation

Choose the last entry at or before the requested frame. If it begins at `f0`,
use the following until the next entry takes over:

```text
elapsed = requestedFrame - f0

position    = basePosition + elapsed * deltaPosition    if flags & 1
            = basePosition                             otherwise
orientation = basePYR      + elapsed * deltaPYR         if flags & 2
            = basePYR                                  otherwise
```

| Entry flags | Meaning |
| ---: | --- |
| 0 | Hold both channels |
| 1 | Position changes |
| 2 | Orientation changes |
| 3 | Both change |

For example, at frame 2.5 a position entry beginning at frame 2 with
`baseX = 1` and `deltaX = 0.2` produces `X = 1.1` when position changes are enabled.
The slope already includes division by the source segment's frame duration;
there is no extra multiplication by FPS. KEY rotation uses component-wise Euler
deltas, not quaternion shortest-path interpolation.

### Header Flags And Type Mask

These are the toolkit's Sith flag labels. They are not a promise of identical
runtime behavior across engines:

| Flag | Label |
| ---: | --- |
| `0` | Loop default |
| `0x01` | Movement controlled |
| `0x02` | No loop |
| `0x04` | Pause on last frame |
| `0x08` | Restart active |
| `0x10` | Disable fade in |
| `0x20` | Fade out and no loop |
| `0x40` | Set position to last frame, Infernal Machine |

`TYPE` uses the [3DO node-type mask](3do.md#render-modes-and-face-flags) for
priority selection. It is not a joint index or a mask where bit `i` means joint
`i`. Unknown animation bits are retained separately from the UI's known flags.
Grim's interpolation bit is described below.

### Marker Types

The table lists the add-on's event names, not a universal engine ABI for every
consumer. Event handling, sounds and blending belong to the game runtime.

| ID | Name | ID | Name | ID | Name |
| ---: | --- | ---: | --- | ---: | --- |
| 0 | Finished | 12 | JumpUp | 24 | ReachRightArmRest |
| 1 | LeftFoot | 13 | SwimRight | 25 | Pickup |
| 2 | RightFoot | 14 | Duck | 26 | Drop |
| 3 | Attack | 15 | Climb | 27 | Move |
| 4 | Swing | 16 | Activate | 28 | InventoryPull |
| 5 | SwingFinish | 17 | Crawl | 29 | InventoryPut |
| 6 | SwimLeft | 18 | RunJumpLand | 30 | AttackFinish |
| 7 | Tread | 19 | ActivateRightArm | 31 | TurnOff |
| 8 | RunLeftFoot | 20 | ActivateRightArmRest | 32 | Row |
| 9 | RunRightFoot | 21 | PlaceRightArm | 33 | RowFinish |
| 10 | Died | 22 | PlaceRightArmRest | 34 | LeftHand |
| 11 | Jump | 23 | ReachRightArm | 35 | RightHand |

The text reader warns and skips unknown event IDs. The binary codec can retain
unknown signed event IDs, but Blender import rejects events it cannot represent
before replacing animation. Do not treat either behavior as validation of an
unknown event's gameplay meaning.

## Grim Binary FYEK

The little-endian on-disk magic is **`FYEK`**, not literal `KEYF`. The header is
**136 bytes**, followed by exactly `numJoints` serialized node slots. A common
empty first node adds 44 bytes to the stream; it is not part of the header.

```text
+------------------------------+ byte 0
| fixed header                 | 72 bytes
+------------------------------+ byte 72
| marker frames[8]             | 32 bytes
+------------------------------+ byte 104
| marker event IDs[8]          | 32 bytes
+------------------------------+ byte 136
| node slot 0: header          | 44 bytes
|              entries[]       | 56 bytes each
+------------------------------+
| node slot 1: header, entries  | variable
+------------------------------+
| ... numJoints slots total    |
+------------------------------+ EOF
```

### Header

| Offset | Storage | Field |
| ---: | --- | --- |
| 0 | 4 bytes | `FYEK` |
| 4 | 36 bytes | Resource name, fixed ASCII field |
| 40 | u32 | Animation flags |
| 44 | u32 | Duplicate joint count, retained |
| 48 | u32 | Priority-node type mask |
| 52 | f32 | Stored FPS |
| 56 | u32 | Number of frames |
| 60 | u32 | Joint / serialized-node-slot count |
| 64 | u32 | Opaque word, often pointer-like; not another flags field |
| 68 | u32 | Used marker count, from 0 through 8 |
| 72 | f32[8] | Marker frame slots |
| 104 | i32[8] | Marker type slots |

Only the first `usedMarkerCount` slots in each marker array are active. Original
unused slots are retained as bytes, not interpreted as valid floating-point
timestamps; their contents need not be finite.

### Node And Entry Records

| Node offset | Storage | Field |
| ---: | --- | --- |
| 0 | 32 bytes | Mesh/joint name |
| 32 | u32 | Joint index |
| 36 | u32 | Entry count `E` |
| 40 | u32 | Opaque word |
| 44 | entry[E] | Entries immediately follow the node header |

| Entry offset | Storage | Field |
| ---: | --- | --- |
| 0 | f32 | Frame |
| 4 | u32 | Entry flags |
| 8 | vec3f | Base position |
| 20 | vec3f | Base pitch/yaw/roll |
| 32 | vec3f | Position delta per frame |
| 44 | vec3f | Pitch/yaw/roll delta per frame |

```text
node size = 44 + 56*E
file size = 136 + sum(node sizes across all serialized slots)
```

A duplicate joint index is allowed only for an empty placeholder: its entire
32-byte name field is zero and its entry count is zero. It is not an additional
animated track. Physical slot count and unique decoded node count can therefore
differ. Nonempty duplicate tracks are invalid. Newly generated resources fill
unanimated joint slots with empty records.

### Grim Playback Interpretation

Grim uses base-plus-delta motion **without** Sith's per-entry channel gates.
Animation flag **`0x100` disables interpolation globally**. Otherwise both position
and orientation use their stored deltas. Entry flags are retained by the codec,
not incorrectly applied as Sith change gates during Blender import.

```text
FYEK decoded entries --copy--> playback-normalized entries --> Blender curves
        |                           |
        |                           +-- collapse adjacent equal frames: last wins
        |                           +-- normalize change flags for playback
        +-- original codec data remains unchanged
```

Finite out-of-order entries remain representable by the codec. Blender rejects
backwards timing; equal adjacent frames use the last-entry rule matching Grim's
upper-bound search. **Require Frame Zero** is enabled by default for Blender
import. Disable it for late-start tracks: the importer evaluates their first
entry's active deltas backward to frame zero, without retiming stored entries.
Unset change flags hold their channel. This is not a claim that every target
engine supports late-start tracks.
Zero-duration pose clips use one display frame and retain their original zero
count on binary re-export while the timeline remains on that single frame.

Stored FPS is retained. Engine-specific timing overrides are outside the codec;
frame-domain pose equivalence alone does not verify in-game timing or blending.
Binary export with `0x100` rejects moving linear segments instead of silently
turning them into holds. Use stepped motion or clear the retained flag.

## Export Targets And Preservation

The **Target** option controls both output representation and engine limits:

| Target | Output | Joint limit | Marker limit | Name limits |
| --- | --- | ---: | ---: | --- |
| Infernal Machine | Text | 64 | 16 | 63 characters |
| Jedi Knight: Dark Forces II | Text | 64 | 8 | 31 characters |
| Mysteries of the Sith | Text | 64 | 8 | 31 characters |
| Grim Fandango | FYEK | No assumed fixed engine cap | 8 | 36 ASCII characters for resources / 32 for joints |
| Generic | Text | No engine-specific cap | No engine-specific cap | Shared text validation, at most 64 characters |

Generic does **not** disable validation. Text names must be nonempty ASCII
identifier tokens without whitespace, quotes, `#` or control characters. FYEK's
physical integers must fit their 32-bit fields, and represented numeric values
must be finite. The binary codec additionally rejects truncation, trailing data,
unsafe counts/indices and invalid duplicate records.

Generic permits nonzero first frames. It samples from the scene's nonnegative
start frame without rebasing timestamps; `FRAMES` remains `scene.frame_end + 1`.
At scene start zero, an unedited replacement import can reuse its original
late-start entries exactly. Other targets sample from zero, including the
backward-extrapolated prefix of a relaxed import. Editing curves invalidates
source-entry reuse and exports the current Blender motion instead.

Core `saveKey` defaults to text unless binary format is explicitly selected.
The Blender UI selects binary for Grim Fandango; the other targets remain text.
Binary bytes are constructed and validated before opening the export destination.

Codec round trips preserve opaque words, raw name padding, unused marker slots
and null-slot layout where compatible. Blender rebuilds tracks and reuses binary
metadata only for a matching replacement import's joint count and animated joint
identities. Merges clear that cache; hierarchy edits can require fresh defaults.
Do not expect an edited Blender export to be byte-identical to the source.

## Opt-In Recovery

**Try Recover Broken File** is off by default and independent of **Require Frame
Zero**. Recovery keeps valid complete tracks at their original joint indices and
omits a whole track if its numeric transforms or chronological order are invalid.
It does not bridge a missing entry by inventing motion. Invalid/unsupported
markers are omitted. Grim's adjacent equal-frame entries remain valid.

For text files, a broken node tail can be discarded after at least one complete
animated track has been read. An invalid header, unsafe binary count/index,
truncated binary record or trailing binary data still fails. If all damaged
animation tracks would be omitted, import fails without clearing the scene.
Blender preflight checks (including float32 precision and destination safety)
remain enabled; recovery is not a promise that every malformed file can import.

Warnings are printed and saved as a Blender Text datablock. **View KEY Import
Report** in **3DO Properties** opens it; the original file is never modified.
Omitted joints are left unanimated after a replacement import. Merging leaves
their existing animation intact. Inspect the result before using it in a game.

Scripted callers use `loadKey(path, allowErrors=True, warnings=messages)` or
`importKey(..., allowErrors=True, requireFrameZero=False, warnings=messages)`.
Both options keep their strict defaults when omitted.

## Implementation

[Resource objects](../../sith/key/key.py), [text reader](../../sith/key/keyLoader.py),
[text writer](../../sith/key/keyWriter.py), [binary codec](../../sith/key/keyBinary.py)
and [target validation](../../sith/key/keyValidation.py).
The binary layout and interpolation interpretation are cross-checked against
[ScummVM's Grim keyframe reader](https://github.com/scummvm/scummvm/blob/master/engines/grim/keyframe.cpp)
and original resource layouts. See the [animation pipeline](../blender-pipeline.md#animation-import-and-export)
for action slots, rotation branches, pivots and fractional Blender markers.
