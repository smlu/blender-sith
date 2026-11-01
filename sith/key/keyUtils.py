# Sith Blender Addon
# Copyright (C) 2026 Crt Vavros
# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared Blender action and timing helpers for the text KEY format."""

import math
import json
import struct

from .key import KeyFlag, KeyNode, Keyframe, KeyframeFlag, KeyMarkerType
from ..types import Vector3f

kKeyUnknownFlags = '_sith_key_unknown_flags'
kKeyKnownFlagMask = sum(int(flag) for flag in KeyFlag)


def setSceneKeyFlags(scene, flags):
    """Replace imported flags without dropping bits absent from the enum UI."""
    flags = KeyFlag(flags)
    scene.sith_key_flags = flags.toSet()

    # Store a hex string so high bits do not depend on ID-property integer width.
    unknown = int(flags) & ~kKeyKnownFlagMask
    if unknown:
        scene[kKeyUnknownFlags] = format(unknown, 'X')
    elif kKeyUnknownFlags in scene:
        del scene[kKeyUnknownFlags]


def getSceneKeyFlags(scene, flags=None):
    """Combine editable known flags with the scene's retained extension bits."""
    known = KeyFlag.fromSet(scene.sith_key_flags if flags is None else flags)
    unknown = int(scene.get(kKeyUnknownFlags, '0'), 16) & ~kKeyKnownFlagMask
    return KeyFlag(int(known) | unknown)


def getActionFCurves(obj):
    """Collect channels belonging to this object's slot in a layered action."""
    if not obj.animation_data or not obj.animation_data.action:
        return []

    return getActionSlotFCurves(obj.animation_data.action, obj.animation_data.action_slot)


def getActionSlotFCurves(action, slot):
    """Read channels for one active-action or NLA action/slot pair."""
    if action is None or slot is None:
        return []

    # An action may be shared. Read only this object's slot, not other users'
    # channels; composition conflicts are checked by the exporter afterwards.
    curves = []
    for layer in action.layers:
        for strip in layer.strips:
            if hasattr(strip, 'channelbag'):
                channelbag = strip.channelbag(slot)
                if channelbag is not None:
                    curves.extend(channelbag.fcurves)

    return curves


def iterActiveNlaStrips(animation):
    """Visit live leaf strips without changing action/slot ownership."""
    if animation is None or not animation.use_nla:
        return

    # A Meta strip is inactive when all of its descendants are muted. This only
    # tests evaluation: muted clips still retain their action/slot ownership.
    pending = [strip for track in animation.nla_tracks if not track.mute for strip in track.strips]
    while pending:
        strip = pending.pop()
        if strip.mute:
            continue
        if strip.type == 'META':
            pending.extend(strip.strips)
        else:
            yield strip


def hasActiveNlaStrips(animation):
    """Check evaluation gates without treating inactive NLA as live composition."""
    return next(iterActiveNlaStrips(animation), None) is not None


def validateKeyActionState(obj):
    """Require direct transform channels to have ordinary action evaluation."""
    animation = obj.animation_data
    if animation is None:
        return
    # Tweak mode remaps action time and makes the active action binding read-only.
    # Reject it before import can copy actions or export can sample raw key times.
    if animation.use_tweak_mode:
        raise ValueError(f"Exit NLA tweak mode on '{obj.name}' before KEY import/export")

    # Muting a strip removes its pose, but a populated unmuted track still
    # enables active-action blending. Raw curves omit that influence/blend mode.
    hasNla = animation.use_nla and any(not track.mute and track.strips for track in animation.nla_tracks)
    if hasNla and (animation.action_blend_type != 'REPLACE' or animation.action_influence != 1.0):
        raise ValueError(f"Set active action blending on '{obj.name}' to Replace with full influence before KEY import/export, or disable NLA evaluation")


def validateConstraintAnimation(obj, constraintTypes=None):
    """Reject live constraint settings which direct KEY channel sampling omits."""
    if not obj.animation_data or not obj.constraints:
        return

    # Include constraint-only NLA clips: they can change the pivot even when
    # the active action contains only the transform keys being imported/exported.
    curves = list(getActionFCurves(obj))
    for strip in iterActiveNlaStrips(obj.animation_data):
        if strip.type == 'CLIP':
            curves.extend(getActionSlotFCurves(strip.action, strip.action_slot))
    paths = {curve.data_path for curve in curves if curve.is_valid and not curve.mute}
    paths.update(driver.data_path for driver in obj.animation_data.drivers if not driver.mute)

    for constraint in obj.constraints:
        if constraintTypes is not None and constraint.type not in constraintTypes:
            continue
        # Use Blender's escaped RNA path, including quotes/brackets in names.
        prefix = constraint.path_from_id() + '.'
        if not any(path.startswith(prefix) for path in paths):
            continue
        # A constant disabled gate makes other animated settings harmless. A
        # keyed/driven gate cannot be judged from its value at the current frame.
        if constraint.mute and prefix + 'mute' not in paths:
            continue
        if constraint.influence == 0 and prefix + 'influence' not in paths:
            continue
        raise ValueError(f"Bake animated or driven constraint '{constraint.name}' on '{obj.name}' to transform channels before KEY import/export")


def getSceneFrameRate(scene):
    if not math.isfinite(scene.render.fps_base) or scene.render.fps_base <= 0.0:
        raise ValueError('Animation FPS base must be finite and positive')

    # KEY stores the effective rate, including Blender's fractional FPS base.
    fps = scene.render.fps / scene.render.fps_base
    if not math.isfinite(fps) or fps <= 0.0:
        raise ValueError('Animation FPS must be finite and positive')

    return fps


def prepareSceneFrameRate(scene, fps):
    """Return representable FPS/base settings without changing the scene."""
    if not math.isfinite(fps) or fps <= 0.0:
        raise ValueError('Animation FPS must be finite and positive')

    fps_range = scene.render.bl_rna.properties['fps']
    base_range = scene.render.bl_rna.properties['fps_base']
    numerator = min(fps_range.hard_max, max(fps_range.hard_min, round(fps)))
    base = numerator / fps
    if not base_range.hard_min <= base <= base_range.hard_max:
        raise ValueError('Animation FPS is outside Blender playback limits')

    # RNA stores the base as float32. Validate that rounded value too, rather
    # than relying on setters which clamp or reject after a destructive import.
    base = struct.unpack('<f', struct.pack('<f', base))[0]
    if (not base_range.hard_min <= base <= base_range.hard_max
            or not math.isclose(numerator / base, fps, rel_tol=1e-7)):
        raise ValueError('Animation FPS cannot be represented by Blender playback settings')
    return numerator, base


def setSceneFrameRate(scene, fps):
    numerator, base = prepareSceneFrameRate(scene, fps)
    scene.render.fps, scene.render.fps_base = numerator, base


def markerName(marker, named):
    if not math.isfinite(marker.frame):
        raise ValueError('KEY marker frames must be finite')

    name = marker.type.name if named else str(int(marker.type))
    fraction = marker.frame - math.floor(marker.frame)
    # TimelineMarker has no custom-property storage. Keep the subframe in its
    # editable name so moves, duplicates and saving a .blend retain the timing.
    text = format(fraction, '.12g')
    if float(text) >= 1:
        text = format(fraction, '.17g')
    return name + ('@' + text if fraction else '')


def markerTimeAndType(marker):
    """Decode a marker's type and optional @subframe suffix into KEY timing."""
    name, separator, fraction = marker.name.partition('@')
    offset = float(fraction) if separator else 0.0
    if not math.isfinite(offset) or not 0 <= offset < 1:
        raise ValueError('Marker subframe must be between zero and one')

    kind = KeyMarkerType[name] if name in KeyMarkerType.__members__ else KeyMarkerType(int(name))
    return marker.frame + offset, kind


def _importCurveState(obj):
    """Snapshot authored curve data used to detect edits to imported jumps."""
    curves = []
    for curve in getActionFCurves(obj):
        if curve.data_path not in ('location', 'rotation_euler'):
            continue

        # This snapshot describes ordinary keyframes only. A modifier or sampled
        # curve must use the normal export path rather than reuse source entries.
        if any(not modifier.mute for modifier in curve.modifiers) or curve.sampled_points:
            return None

        curves.append([
            curve.data_path, curve.array_index, curve.mute, curve.is_valid,
            curve.extrapolation,
            [
                [list(point.co), point.interpolation, list(point.handle_left),
                 list(point.handle_right), point.handle_left_type, point.handle_right_type]
                for point in curve.keyframe_points
            ]
        ])

    return sorted(curves, key=lambda value: (value[0], value[1]))


def rememberImportedJump(obj, node, end_frame, enabled):
    """Keep exact source segments alongside their editable Blender approximation."""
    # 1. Always discard stale metadata, including when importing without reuse.
    for name in ('_sith_key_jump', '_sith_key_jump_action'):
        if name in obj:
            del obj[name]
    if not enabled:
        return

    from ..model.utils import objPivot

    # 2. Save both the source entries and the state that makes reuse valid. The
    # action reference also prevents another action with similar curves reusing it.
    data = {
        'version': 1,
        'end_frame': end_frame,
        'rotation_mode': obj.rotation_mode,
        'pivot': list(objPivot(obj, forAnimation=True)),
        'curves': _importCurveState(obj),
        'entries': [
            [entry.frame, int(entry.flags), list(entry.position), list(entry.orientation),
             list(entry.deltaPosition), list(entry.deltaRotation)]
            for entry in node.keyframes
        ]
    }
    obj['_sith_key_jump'] = json.dumps(data)
    obj['_sith_key_jump_action'] = obj.animation_data.action


def unchangedImportedJump(obj, end_frame):
    """Return fresh source entries only while their imported animation is unedited."""
    if not obj.animation_data or obj.get('_sith_key_jump_action') != obj.animation_data.action:
        return None

    from ..model.utils import objPivot

    try:
        # 1. Verify the action, timeline, pivot and authored curves before bypassing
        # sampling. Any mismatch falls back to exporting the current Blender data.
        data = json.loads(obj.get('_sith_key_jump', 'null'))
        if (not data or data['version'] != 1 or data['end_frame'] != end_frame
                or data['rotation_mode'] != obj.rotation_mode or data['pivot'] != list(objPivot(obj, forAnimation=True))
                or data['curves'] != _importCurveState(obj)):
            return None

        # 2. Rebuild independent entries; the exporter may scale their positions
        # without modifying the saved snapshot or Blender's editable curves.
        node = KeyNode()
        for values in data['entries']:
            entry = Keyframe()
            entry.frame, entry.flags = values[0], KeyframeFlag(values[1])
            entry.position, entry.orientation = Vector3f(*values[2]), Vector3f(*values[3])
            entry.deltaPosition, entry.deltaRotation = Vector3f(*values[4]), Vector3f(*values[5])
            node.keyframes.append(entry)

        return node
    except (ValueError, KeyError, TypeError, IndexError):
        # Missing or obsolete metadata is not an export failure: resample instead.
        return None
