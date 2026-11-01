# Sith Blender Addon
# Copyright (C) 2019-2026 Crt Vavros
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

from xmlrpc.client import Boolean
import bpy, mathutils, math

from ..model.utils import *
from ..types import BenchmarkMeter
from ..utils import *

from typing import Optional

from .key import *
from . import keyLoader
from .keyUtils import getActionFCurves, getActionSlotFCurves, prepareSceneFrameRate, setSceneFrameRate, setSceneKeyFlags, markerName, rememberImportedJump, validateConstraintAnimation, validateKeyActionState
from ..model.model3do import Model3do, Mesh3doNode

kKeyFrameSnapTolerance = 0.0001  # Blender's F-curve exact-key matching tolerance, in frames.


def importKey(keyPath: str, scene: bpy.types.Scene, clearScene: bool, validateActiveObject: bool, namedMarkers: bool):
    """Apply KEY tracks to a model in the supplied, currently active context scene."""
    with BenchmarkMeter(' done in {:.4f} sec.'):
        print("importing KEY: %r..." % (keyPath), end="")

        key = keyLoader.loadKey(keyPath)
        if scene != bpy.context.scene:
            raise ValueError(f"Destination scene '{scene.name}' must match the active context before KEY import")
        # Even empty tracks update timing and markers. Reject linked scenes
        # before clearing animation or copying any destination actions.
        if not scene.is_editable:
            raise ValueError(f"Make scene '{scene.name}' local or editable before KEY import")
        prepareSceneFrameRate(scene, key.fps)
        samplesByJoint = _prepare_import_samples(key)

        # 1. Resolve the model root and its joint mapping before clearing any
        # animation, so an incompatible or ambiguous skeleton leaves it intact.
        # Linked and local IDs may share a name; membership must use identity.
        sceneObjects = set(scene.objects)
        obj = bpy.context.view_layer.objects.active
        if obj:
            obj = _get_parent(obj)
            if obj not in sceneObjects:
                raise ValueError(f"Model root '{obj.name}' is outside destination scene '{scene.name}'; include its hierarchy before KEY import")
            if validateActiveObject and not _check_obj(obj, key.nodes, key.numJoints):
                raise ValueError(f"Selected object '{obj.name}' doesn't contain all required nodes to animate!")
        else:
            obj = _find_anim_obj_in_scene(scene, key.nodes, key.numJoints)
            if obj is None:
                raise ValueError(f"Couldn't find a valid object to animate!")

        jointLookup = _joint_lookup(obj, key.numJoints)
        # Object parenting is global: a root can have joint descendants that
        # belong only to another scene, including joints absent from this KEY.
        for joint in jointLookup[0]:
            if joint not in sceneObjects:
                raise ValueError(f"Model joint '{joint.name}' is outside destination scene '{scene.name}'; include its hierarchy before KEY import")
        # Resolve every destination and its supported pivot before clearing any
        # actions. A bad later joint must not leave an earlier one half-imported.
        destinations = []
        pivots = {}
        resolvedJoints = {}
        for node in key.nodes:
            aobj = _find_joint_obj_for_anim_node(obj, node, key.numJoints, jointLookup)
            if aobj is not None:
                # Partial name matching must also be unique across source tracks,
                # not only across candidates for one track. Never overwrite one
                # joint twice through aliases for distinct source node indices.
                if aobj in resolvedJoints:
                    raise ValueError(f"KEY joints {resolvedJoints[aobj]} and {node.idx} resolve to the same joint object '{aobj.name}'; assign unique joint sequence numbers before import")
                resolvedJoints[aobj] = node.idx
                if samplesByJoint[node.idx] and not aobj.is_editable:
                    raise ValueError(f"Make joint '{aobj.name}' local or editable before KEY import")
                if not clearScene and samplesByJoint[node.idx] and aobj.rotation_mode != kImEulerOrder:
                    rotation_paths = ('rotation_euler', 'rotation_quaternion', 'rotation_axis_angle')
                    animation = aobj.animation_data
                    hasRotation = any(curve.is_valid and not curve.mute and curve.data_path in rotation_paths
                                      for curve in getActionFCurves(aobj))
                    hasProcedural = animation and (
                        any(not driver.mute and driver.data_path in rotation_paths for driver in animation.drivers)
                        or _has_nla_rotation(animation, rotation_paths)
                    )
                    if hasRotation or hasProcedural:
                        raise ValueError(f"Bake existing rotation animation on '{aobj.name}' to {kImEulerOrder} before merging a KEY, or enable Clear scene")
                if not clearScene and samplesByJoint[node.idx] and aobj.animation_data:
                    transform_paths = ('location', 'rotation_euler', 'rotation_quaternion', 'rotation_axis_angle')
                    if any(not driver.mute and driver.data_path in transform_paths
                           for driver in aobj.animation_data.drivers):
                        raise ValueError(f"Mute or remove transform drivers on '{aobj.name}' before merging a KEY, or enable Clear scene")
                    _validate_import_channels(aobj)
                pivot = objPivot(aobj, forAnimation=True)
                if not all(math.isfinite(value) for value in pivot):
                    raise ValueError(f"Pivot on '{aobj.name}' must be finite")
                pivots[node.idx] = tuple(pivot)
            destinations.append((node, aobj))

        _validate_import_pivots(destinations, samplesByJoint, clearScene)
        # Check every destination-adjusted sample before clearing any action.
        # Python arithmetic avoids float32 overflow or RNA's silent clamping.
        positionsByJoint = {
            node.idx: [_key_position_to_blender(sample.position, pivots[node.idx])
                       for sample in samplesByJoint[node.idx]]
            for node, aobj in destinations if aobj is not None
        }
        for node, aobj in destinations:
            if aobj is None:
                continue
            coordinates = _get_import_coordinates(samplesByJoint[node.idx], positionsByJoint[node.idx])
            if not clearScene:
                _validate_import_merge_times(aobj, coordinates)

        if clearScene:
            clearSceneAnimData(scene)
        else:
            # Keep linked library data read-only and isolate conflicting users.
            # Independent, editable slots in a local action may stay shared.
            for node, aobj in destinations:
                if aobj is None or not samplesByJoint[node.idx] or not aobj.animation_data:
                    continue
                animation = aobj.animation_data
                slot = animation.action_slot
                if animation.action and (not animation.action.is_editable
                                         or (slot and len(slot.users()) > 1)
                                         or _nla_uses_action_slot(animation, animation.action, slot)):
                    identifier = slot.identifier if slot else None
                    animation.action = animation.action.copy()
                    if identifier is not None:
                        animation.action_slot = animation.action.slots[identifier]

        # 2. Restore playback metadata and markers. Fractional marker times live
        # in marker names because Blender timeline markers have integer frames.
        scene.frame_start     = 0
        scene.frame_end       = key.numFrames - 1 if clearScene else max(scene.frame_end, key.numFrames - 1)
        scene.frame_step      = 1
        setSceneFrameRate(scene, key.fps)

        if clearScene:
            setSceneKeyFlags(scene, key.flags)
            scene.sith_key_types = format(int(key.nodeTypes), 'x')

        for m in key.markers:
            scene.timeline_markers.new(markerName(m, namedMarkers), frame=math.floor(m.frame))

        # 3. Expand each KEY base-plus-delta track to Blender transform keys,
        # then restore the engine's linear/held interpolation per segment.
        for node, aobj in destinations:
            # Get object to animate
            if aobj is None:
                print(f"Couldn't find joint object '{node.meshName}' to animate!")
                continue

            # KEY interpolates Euler components, not quaternion shortest paths.
            samples = samplesByJoint[node.idx]
            if not samples:
                continue
            aobj.rotation_mode = kImEulerOrder
            _insert_import_samples(aobj, samples, positions=positionsByJoint[node.idx])

            # A change flag means linear motion; an unset flag holds that channel.
            _fix_obj_anim_interpolation(aobj, samples)

            # Retain exact discontinuity data only for a clean replacement import;
            # later export can reuse it while the generated curves stay unedited.
            rememberImportedJump(aobj, node, key.numFrames,
                                 clearScene and any(getattr(entry, '_left_limit', False) for entry in samples))

        # Set current frame to 0
        scene.frame_set(0)


def _nla_uses_action_slot(animation, action, slot):
    """Slot users count IDs, not an object's active-action and NLA references."""
    pending = [strip for track in animation.nla_tracks for strip in track.strips]
    while pending:
        strip = pending.pop()
        if strip.type == 'META':
            pending.extend(strip.strips)
        elif strip.type == 'CLIP' and strip.action == action and strip.action_slot == slot:
            # Muted clips also retain their source animation for later reuse.
            return True
    return False


def _has_nla_rotation(animation, rotation_paths):
    """Changing rotation mode must not reinterpret an existing NLA rotation clip."""
    if animation is None or not animation.use_nla:
        return False

    pending = [strip for track in animation.nla_tracks if not track.mute for strip in track.strips]
    while pending:
        strip = pending.pop()
        if strip.mute:
            continue
        if strip.type == 'META':
            pending.extend(strip.strips)
        elif strip.type == 'CLIP':
            if any(curve.is_valid and not curve.mute and curve.data_path in rotation_paths
                   for curve in getActionSlotFCurves(strip.action, strip.action_slot)):
                return True
    return False


def _prepare_import_samples(key):
    """Reject invalid metadata/tracks before clearing any existing animation."""
    if key.numFrames < 1 or key.numJoints < 0:
        raise ValueError('KEY requires a positive frame count and nonnegative joint count')
    if not math.isfinite(key.fps) or key.fps <= 0.0:
        raise ValueError('Animation FPS must be finite and positive')
    frame_range = bpy.types.Scene.bl_rna.properties['frame_end']
    if not frame_range.hard_min <= key.numFrames - 1 <= frame_range.hard_max:
        raise ValueError(f'KEY duration exceeds Blender timeline limits ({frame_range.hard_max + 1} frames)')
    if any(not math.isfinite(marker.frame) for marker in key.markers):
        raise ValueError('KEY marker frames must be finite')
    marker_range = bpy.types.TimelineMarker.bl_rna.properties['frame']
    if any(not marker_range.hard_min <= math.floor(marker.frame) <= marker_range.hard_max
           for marker in key.markers):
        raise ValueError('KEY marker is outside Blender timeline marker limits')

    # Prepare every track first. Otherwise a malformed later joint could fail
    # only after Clear Animation and earlier joints had already changed the scene.
    samples = {}
    for node in key.nodes:
        if not 0 <= node.idx < key.numJoints:
            raise ValueError(f'KEY joint index {node.idx} is outside its joint count')
        if node.idx in samples:
            raise ValueError(f'Duplicate KEY joint index {node.idx}')
        samples[node.idx] = _make_import_samples(node, key.numFrames)
    return samples


def _validate_import_pivots(destinations, samplesByJoint, clearScene):
    """Preflight incoming poses, not just the destination's current Pivot state."""
    incoming = {obj: samplesByJoint[node.idx] for node, obj in destinations if obj is not None}
    rotation_paths = ('rotation_euler', 'rotation_quaternion', 'rotation_axis_angle')
    for node, obj in destinations:
        if obj is None or not samplesByJoint[node.idx]:
            continue
        if not clearScene:
            # A currently disabled Pivot may become active later. Check its
            # channels before filtering by the constraint's current gates.
            validateConstraintAnimation(obj, constraintTypes={'PIVOT'})
        pivots = [c for c in obj.constraints if c.type == 'PIVOT' and not c.mute and c.influence]
        if not pivots:
            continue
        if any(c.rotation_range != 'ALWAYS_ACTIVE' for c in pivots):
            raise ValueError(f"Bake conditional Pivot constraints on '{obj.name}' or set their rotation range to Always before KEY import")

        # Parent rotation changes how a world-space Pivot affects its owner;
        # it cannot be inverted by the importer's constant local translation.
        parent = obj.parent
        while parent is not None:
            samples = incoming.get(parent, ())
            if any(any(sample.orientation) for sample in samples):
                raise ValueError(f"Bake parent rotation for Pivot-constrained object '{obj.name}' before KEY import")
            if not clearScene:
                animation = parent.animation_data
                hasRotation = any(curve.is_valid and not curve.mute and curve.data_path in rotation_paths
                                  for curve in getActionFCurves(parent))
                hasDriver = animation and any(not driver.mute and driver.data_path in rotation_paths
                                              for driver in animation.drivers)
                if hasRotation or hasDriver or _has_nla_rotation(animation, rotation_paths):
                    raise ValueError(f"Bake existing parent rotation for Pivot-constrained object '{obj.name}' before KEY import")
            parent = parent.parent


def _set_obj_location(obj: bpy.types.Object, location: Vector3f):
    # Undo KEY export's active-pivot subtraction in Blender local coordinates.
    obj.location = _key_position_to_blender(location, objPivot(obj, forAnimation=True))


def _key_position_to_blender(position, pivot):
    validateFloat32((*position, *pivot), 'KEY position and Pivot')
    # Match Blender's float32 operands, but check the sum in Python precision
    # before assigning it to RNA (which would silently clamp an overflow).
    position, pivot = mathutils.Vector(position), mathutils.Vector(pivot)
    values = tuple(float(position[index]) + float(pivot[index]) for index in range(3))
    validateFloat32(values, 'Pivot-adjusted KEY position')
    return values


def _can_animate_obj(obj: bpy.types.Object, node:KeyNode, maxJoints: int) -> bool:
    if obj.sith_model3do_hnode_idx > -1 and obj.sith_model3do_hnode_idx < maxJoints:
            if obj.sith_model3do_hnode_idx == node.idx:
                return True
    elif obj.sith_model3do_hnode_name.lower() == node.meshName.lower():
        return True
    elif node.meshName.lower() == obj.name.lower():
        return True
    elif isOrderPrefixed(obj.name) and getOrderedNameIdx(obj.name) == node.idx:
        return True
    return False


def _joint_lookup(obj, maxJoints):
    """Map KEY indices to export-normalized joints, or allow partial-name lookup."""
    if obj.type not in ('MESH', 'EMPTY'):
        return [], None
    model = Model3do()

    def visit(current, parent):
        if current.type not in ('EMPTY', 'MESH') or isRadiusObj(current):
            return
        index = len(model.meshHierarchy)
        joint = Mesh3doNode()
        joint.idx, joint.parentIdx, joint.obj = current.sith_model3do_hnode_idx, parent, current
        model.meshHierarchy.append(joint)

        for child in current.children:
            visit(child, index)

    # The top-level EMPTY is a model wrapper, not a KEY joint, just as in 3DO
    # export. Radius helpers and unsupported subtrees do not consume joint slots.
    if obj.type == 'MESH' or not obj.children:
        visit(obj, -1)
    else:
        for child in obj.children:
            visit(child, -1)

    # Partial matching must use the same eligible joints as complete matching,
    # never a wrapper, radius helper or object below an unsupported parent.
    candidates = [joint.obj for joint in model.meshHierarchy]
    if len(model.meshHierarchy) == maxJoints:
        # Sequence properties are sort hints, not necessarily dense KEY indices.
        # Reuse the export ordering for complete skeletons (including automatic
        # and sparse sequence values) instead of interpreting those hints as IDs.
        numbers = [joint.idx for joint in model.meshHierarchy if joint.idx >= 0]
        if len(numbers) != len(set(numbers)):
            raise ValueError('Ambiguous joint sequence numbers')

        model.reorderNodes()
        return candidates, {joint.idx: joint.obj for joint in model.meshHierarchy}

    # Partial skeletons cannot reconstruct the complete export order reliably;
    # retain explicit-index/name matching for those instead of guessing a layout.
    return candidates, None


def _find_joint_obj_for_anim_node(obj: bpy.types.Object, node: KeyNode, maxJoints: int, lookup=None) -> Optional[bpy.types.Object]:
    candidates, ordered = _joint_lookup(obj, maxJoints) if lookup is None else lookup
    if ordered is not None:
        return ordered.get(node.idx)

    # For partial models, explicit IDs take priority over name matches anywhere
    # in the subtree. Reject ambiguity rather than animate an arbitrary object.
    indexed = [candidate for candidate in candidates
               if 0 <= candidate.sith_model3do_hnode_idx < maxJoints
               and candidate.sith_model3do_hnode_idx == node.idx]
    if len(indexed) > 1:
        raise ValueError(f'Ambiguous joint sequence number {node.idx}')
    if indexed:
        return indexed[0]

    fallback = [candidate for candidate in candidates if _can_animate_obj(candidate, node, maxJoints)]
    if len(fallback) > 1:
        raise ValueError(f"Ambiguous joint name '{node.meshName}'")
    return fallback[0] if fallback else None


def _check_obj(obj, nodes: List[KeyNode], maxJoints: int) -> bool:
    lookup = _joint_lookup(obj, maxJoints)
    matched = set()
    for node in nodes:
        joint = _find_joint_obj_for_anim_node(obj, node, maxJoints, lookup)
        if joint is None or joint in matched:
            return False
        matched.add(joint)
    return True


def _find_anim_obj_in_scene(scene: bpy.types.Scene, nodes: List[KeyNode], maxJoints: int) -> Optional[bpy.types.Object]:
    for obj in scene.objects:
        if obj.parent is not None:
            continue
        if _check_obj(obj, nodes, maxJoints):
            return obj
    return None


def _get_parent(obj: bpy.types.Object) -> bpy.types.Object:
    while obj.parent is not None:
        obj = obj.parent
    return obj


def _get_rotation_data_path(obj: bpy.types.Object) -> str:
    if obj.rotation_mode == 'QUATERNION':
        return 'rotation_quaternion'
    elif obj.rotation_mode == 'AXIS_ANGLE':
        return 'rotation_axis_angle'
    else:
        return 'rotation_euler'


def _align_orientation(orientation, reference):
    # Choose equivalent angles near the extrapolated pose, retaining full turns.
    return Vector3f(*(value + 360.0 * round((reference[i] - value) / 360.0)
                      for i, value in enumerate(orientation)))


def _make_import_samples(node, end_frame):
    """Expand KEY deltas to curve endpoints, preserving holds and pose jumps."""
    samples = []
    previous = None
    for index, source in enumerate(node.keyframes):
        # 1. Validate and copy the source entry; do not modify the parsed KEY.
        validateFloat32((
            value
            for vector in (source.position, source.orientation, source.deltaPosition, source.deltaRotation)
            for value in vector
        ), 'KEY transforms and deltas')
        if not math.isfinite(source.frame) or source.frame < 0.0 or (previous and source.frame <= previous.frame):
            raise ValueError('KEY entries must have finite, strictly increasing, nonnegative frames')
        validateFloat32((source.frame,), 'KEY entry frame')
        # Sith starts playback at entry zero and requires a nonnegative delta
        # from its stored frame. Blender would instead hold a late first pose.
        if index == 0 and mathutils.Vector((source.frame, 0.0))[0] != 0.0:
            raise ValueError('KEY tracks must start at stored frame zero')

        entry = Keyframe()
        entry.frame = source.frame
        entry.position = source.position
        entry.orientation = source.orientation
        entry.flags = source.flags
        entry.deltaPosition = source.deltaPosition
        entry.deltaRotation = source.deltaRotation

        if previous is not None:
            # Follow the previous segment's Euler winding rather than wrapping
            # each stored orientation independently to the nearest zero angle.
            reference = list(previous.orientation)
            if previous.flags & KeyframeFlag.OrientationChange:
                reference = [value + previous.deltaRotation[i] * (entry.frame - previous.frame)
                             for i, value in enumerate(reference)]
            entry.orientation = _align_orientation(entry.orientation, reference)

        samples.append(entry)

        if index + 1 < len(node.keyframes):
            # 2. Extrapolate this segment to the next entry. Its deltas need not
            # land on that entry's stored pose: a mismatch is a discontinuity.
            following = node.keyframes[index + 1]
            span = following.frame - entry.frame
            if not math.isfinite(span) or span <= 0.0:
                raise ValueError('KEY entries must have strictly increasing frames')

            end_position = [value + entry.deltaPosition[i] * span for i, value in enumerate(entry.position)]
            end_rotation = [value + entry.deltaRotation[i] * span for i, value in enumerate(entry.orientation)]
            next_rotation = _align_orientation(following.orientation, end_rotation)
            position_jump = (
                bool(entry.flags & KeyframeFlag.PositionChange)
                and max(abs(a - b) for a, b in zip(end_position, following.position)) > 1.0e-5
            )
            rotation_jump = (
                bool(entry.flags & KeyframeFlag.OrientationChange)
                and max(abs(a - b) for a, b in zip(end_rotation, next_rotation)) > 0.001
            )

            if position_jump or rotation_jump:
                # 3. Add the pose just before the jump, then hold it until the
                # next entry supplies the new pose. This preserves motion up to
                # the boundary rather than interpolating towards the wrong end.
                # Blender evaluates keys within 0.0001 frames as an exact match.
                # Keep the left sample outside that range; the exact source
                # segment is retained separately only while the curves are unedited.
                epsilon = min(span * 0.25, max(0.00025, abs(following.frame) * 2.0 ** -21))
                if epsilon <= 0.0002:
                    raise ValueError('KEY discontinuity is too close to represent at Blender frame precision')

                left = Keyframe()
                left._left_limit = True
                left.frame = following.frame - epsilon
                delta = left.frame - entry.frame
                left.position = Vector3f(*(
                    value + (entry.deltaPosition[i] * delta if entry.flags & KeyframeFlag.PositionChange else 0.0)
                    for i, value in enumerate(entry.position)
                ))
                left.orientation = Vector3f(*(
                    value + (entry.deltaRotation[i] * delta if entry.flags & KeyframeFlag.OrientationChange else 0.0)
                    for i, value in enumerate(entry.orientation)
                ))

                # Stop only channels that jump. Other channels may keep moving
                # across the tiny interval before the next source entry.
                left.flags = KeyframeFlag(int(entry.flags) & ~(1 if position_jump else 0) & ~(2 if rotation_jump else 0))
                samples.append(left)

        previous = entry

    if previous is not None and previous.frame < end_frame:
        # 4. The last entry's delta remains active through the final fractional
        # playback interval; an explicit endpoint prevents Blender extrapolation.
        last = Keyframe()
        last.frame = float(end_frame)
        span = last.frame - previous.frame
        last.position = Vector3f(*(
            value + (previous.deltaPosition[i] * span if previous.flags & KeyframeFlag.PositionChange else 0.0)
            for i, value in enumerate(previous.position)
        ))
        last.orientation = Vector3f(*(
            value + (previous.deltaRotation[i] * span if previous.flags & KeyframeFlag.OrientationChange else 0.0)
            for i, value in enumerate(previous.orientation)
        ))
        samples.append(last)

    # Check extrapolated values and stored times before any destination changes.
    _get_import_coordinates(samples, [sample.position for sample in samples])
    return samples


def _fix_obj_anim_interpolation(obj: bpy.types.Object, samples):
    # Match Blender's float32 key times before looking up each KEY change flag.
    flags = {mathutils.Vector((entry.frame, 0.0))[0]: entry.flags for entry in samples}
    for curve in getActionFCurves(obj):
        if curve.data_path not in ('location', 'rotation_euler'):
            continue

        change = KeyframeFlag.PositionChange if curve.data_path == 'location' else KeyframeFlag.OrientationChange
        for point in curve.keyframe_points:
            if point.co[0] in flags:
                point.interpolation = 'LINEAR' if flags[point.co[0]] & change else 'CONSTANT'

        # FCurve.update() also deduplicates nearby keys, erasing left-limit samples.
        curve.keyframe_points.sort()
        curve.keyframe_points.handles_recalc()


def _validate_import_channels(obj):
    """Reject incompatible destination curves before changing any joint or action."""
    validateKeyActionState(obj)
    for curve in getActionFCurves(obj):
        if curve.data_path not in ('location', 'rotation_euler'):
            continue
        # Blender's samples and keyframes share a point count. Adding raw keys
        # to sampled storage would leave two buffers with inconsistent lengths.
        if curve.sampled_points:
            raise ValueError(f"Convert sampled transform curves on '{obj.name}' to keyframes before merging a KEY, or enable Clear scene")
        if curve.mute:
            raise ValueError(f"Unmute transform curves on '{obj.name}' before merging a KEY, or enable Clear scene")
        if any(not modifier.mute for modifier in curve.modifiers):
            raise ValueError(f"Mute or remove transform F-curve modifiers on '{obj.name}' before merging a KEY, or enable Clear scene")


def _get_import_coordinates(samples, positions):
    """Preflight float32 samples without assigning any Blender object channels."""
    if len(positions) != len(samples):
        raise ValueError('KEY sample/local-position count mismatch')

    coordinates = {(path, axis): {} for path in ('location', 'rotation_euler') for axis in range(3)}
    previousFrame, previousPose = None, None
    for sample, position in zip(samples, positions):
        validateFloat32((sample.frame, *position, *sample.orientation), 'KEY sample')
        frame = mathutils.Vector((sample.frame, 0.0))[0]
        if frame < 0 or (previousFrame is not None and frame <= previousFrame):
            raise ValueError('KEY sample times collide or change order at float32 frame precision')

        # RNA stores float32 channel values too. Equal stored poses are harmless
        # even at close times; different poses can be shadowed by the next key.
        pose = (*mathutils.Vector(position),
                *mathutils.Vector(tuple(math.radians(sample.orientation[i]) for i in (0, 2, 1))))
        if (previousFrame is not None and frame - previousFrame <= kKeyFrameSnapTolerance
                and pose != previousPose):
            raise ValueError('KEY pose changes are too close to represent at Blender frame precision')
        for channel, value in zip(coordinates, pose):
            coordinates[channel][frame] = value
        previousFrame, previousPose = frame, pose
    return coordinates


def _validate_import_merge_times(obj, coordinates):
    """Check incoming/existing neighbors before action isolation or key insertion."""
    for curve in getActionFCurves(obj):
        incoming = coordinates.get((curve.data_path, curve.array_index))
        if not incoming:
            continue
        values = {point.co[0]: point.co[1] for point in curve.keyframe_points}
        values.update(incoming)  # An exact time match deliberately replaces that key.
        times = sorted(values)
        for left, right in zip(times, times[1:]):
            if (right - left <= kKeyFrameSnapTolerance and (left in incoming or right in incoming)
                    and values[left] != values[right]):
                raise ValueError('KEY merge keys are too close to represent at Blender frame precision')


def _insert_import_samples(obj, samples, *, positions=None):
    """Add exact float-time samples without Blender's nearby-key replacement."""
    if not samples:
        return

    # Keep the low-level insertion safe for direct callers too. The public
    # importer also checks every destination before updating scene metadata.
    _validate_import_channels(obj)

    if positions is None:
        pivot = objPivot(obj, forAnimation=True)
        positions = [_key_position_to_blender(sample.position, pivot) for sample in samples]
    coordinates = _get_import_coordinates(samples, positions)
    _validate_import_merge_times(obj, coordinates)

    # 1. Preserve the prior bootstrap pose, but only after all checks succeed.
    obj.location = positions[-1]
    obj.rotation_euler = tuple(math.radians(samples[-1].orientation[i]) for i in (0, 2, 1))

    # 2. Create any missing channels through Blender's action/slot API, then
    # populate their raw arrays so nearby discontinuity keys are not merged.
    curves = {(curve.data_path, curve.array_index): curve for curve in getActionFCurves(obj)}
    for path, axis in coordinates:
        if (path, axis) not in curves:
            # Let Blender create the action/slot/channel, then populate its raw points.
            if not obj.keyframe_insert(data_path=path, index=axis, frame=samples[0].frame):
                raise ValueError(f"Cannot create KEY channel {path}[{axis}] on '{obj.name}'")

    # 3. Reacquire curves after Blender creates channels, reserve point storage
    # once per curve, and merge only keys with exactly matching float32 times.
    curves = {(curve.data_path, curve.array_index): curve for curve in getActionFCurves(obj)}
    for channel, values in coordinates.items():
        points = curves[channel].keyframe_points
        existing = {point.co[0]: index for index, point in enumerate(points)}
        next_index = len(points)
        points.add(sum(frame not in existing for frame in values))

        # Keep indices rather than point references: add() can reallocate the array.
        for frame, value in values.items():
            index = existing.get(frame)
            if index is None:
                index = next_index
                next_index += 1
            points[index].co = (frame, value)
        points.sort()
