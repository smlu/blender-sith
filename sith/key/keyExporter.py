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

import bpy, mathutils, math, os.path
from numpy.polynomial import Polynomial
from . import keyWriter
from bisect import bisect_left
from .keyUtils import getActionFCurves, getSceneFrameRate, getSceneKeyFlags, hasActiveNlaStrips, markerTimeAndType, unchangedImportedJump, validateConstraintAnimation, validateKeyActionState, kKeyBinaryData
from .keyBinary import prepareGrimExport
import json
from .keyValidation import validateKeyForTarget

from .key import *
from ..model.utils import *
from ..model import makeModel3doFromObj, Mesh3doNodeType
from ..types import BenchmarkMeter
from ..utils import *


def exportKey(obj: bpy.types.Object, scene: bpy.types.Scene, path: str, target='IJIM', *, fps=None, flags=None, nodeTypes=None):
    """Convert the selected model's animation to KEY, validate it, then write it."""
    with BenchmarkMeter(' done in {:.4f} sec.'):
        print(f"exporting KEY: {path} for obj: '{obj.name}'...", end="")

        key_name = os.path.basename(path)
        if not isValidNameLen(key_name):
            raise ValueError(f"Export file name '{key_name}' is longer then {kMaxNameLen} chars!")

        key = _make_key_from_obj(key_name, obj, scene, target=target, fps=fps, flags=flags, nodeTypes=nodeTypes)
        if key.numJoints == 0:
            raise ValueError('No exportable joints were found; select a model hierarchy, not only radius helpers.')
        if len(key.nodes) == 0:
            print("\nWarning: The object doesn't have any animation data to export!")

        header  = getExportFileHeader(f"Keyframe '{os.path.basename(path)}'")
        keyWriter.saveKey(key, path, header, fileFormat=key.fileFormat)


def _set_keyframe_delta(kf1: Keyframe, kf2: Keyframe, dtype: KeyframeFlag):
    """Store motion per frame on the segment's first entry, not its endpoint."""
    assert dtype == KeyframeFlag.PositionChange or dtype == KeyframeFlag.OrientationChange

    if kf2.frame <= kf1.frame:
        return

    vec1 = kf1.position
    vec2 = kf2.position
    if dtype == KeyframeFlag.OrientationChange:
        vec1 = kf1.orientation
        vec2 = kf2.orientation

    # Subtract in Python precision: finite float32 endpoints can overflow a
    # mathutils subtraction even when division yields a representable slope.
    dframes = kf2.frame - kf1.frame
    delta   = Vector3f(*((last - first) / dframes for first, last in zip(vec1, vec2)))
    validateFloat32(delta, 'Generated KEY delta')

    if any(delta):
        if dtype == KeyframeFlag.PositionChange:
            kf1.deltaPosition = delta
        else:
            kf1.deltaRotation = delta

        if kf1.flags == KeyframeFlag.NoChange:
            kf1.flags = dtype
        elif kf1.flags != dtype:
            kf1.flags = KeyframeFlag.AllChange


def _curve_value(curve, frame, left_limit=False, keyframes=None):
    """Sample a curve, optionally taking the pose just before a CONSTANT jump."""
    if keyframes is None:
        points = list(curve.keyframe_points)
        keyframes = ([point.co[0] for point in points], [point.co[1] for point in points],
                     [point.interpolation for point in points])

    times, values, interpolation = keyframes
    index = bisect_left(times, frame)
    hasModifiers = any(not modifier.mute for modifier in curve.modifiers)

    # At a hold boundary, the left limit belongs to the preceding segment;
    # normal evaluation at the same time must instead return the new key's pose.
    if index < len(times) and times[index] == frame:
        if left_limit and index > 0 and interpolation[index - 1] == 'CONSTANT':
            if hasModifiers:
                raise ValueError('Bake modifiers on discontinuous CONSTANT curves before KEY export')
            return values[index - 1]
        if not hasModifiers:
            return values[index]

    if not hasModifiers and 0 < index < len(times):
        # Blender evaluate() snaps close times to keys; retain the declared KEY segments.
        if interpolation[index - 1] == 'CONSTANT':
            return values[index - 1]
        if interpolation[index - 1] == 'LINEAR':
            weight = (frame - times[index - 1]) / (times[index] - times[index - 1])
            return values[index - 1] + (values[index] - values[index - 1]) * weight

    # Let Blender evaluate Bezier curves, sampled curves and extrapolation.
    return curve.evaluate(frame)


def _rotation_curve_times(curve, end_time, rotation_kind='quaternion'):
    """Seed normalized rotation baking at component zeros and turning points."""
    times = set()
    points = list(curve.keyframe_points) or list(curve.sampled_points)

    def add_time(frame, start, end):
        # Generated boundaries must be distinct at the float32 precision used by
        # Blender and the engine, not just distinct Python double values.
        frame = float(mathutils.Vector((frame, 0.0))[0])
        if max(0.0, start) < frame < min(end_time, end):
            times.add(frame)

    if points and curve.extrapolation == 'LINEAR':
        for start, end in ((0.0, min(end_time, points[0].co[0])),
                           (max(0.0, points[-1].co[0]), end_time)):
            if end > start:
                value, last = curve.evaluate(start), curve.evaluate(end)
                if last != value:
                    add_time(start - value * (end - start) / (last - value), start, end)
    for first, last in zip(points, points[1:]):
        start, end = float(first.co[0]), float(last.co[0])
        if end <= start or start >= end_time or end <= 0:
            continue

        mode = getattr(first, 'interpolation', 'LINEAR')
        if mode == 'CONSTANT':
            continue
        if mode == 'LINEAR':
            value, delta = float(first.co[1]), float(last.co[1] - first.co[1])
            if delta:
                frame = start - value * (end - start) / delta
                add_time(frame, start, end)
            continue
        if mode != 'BEZIER':
            raise ValueError(f'Bake {rotation_kind} easing curves to LINEAR/BEZIER channels before KEY export')

        # Match Blender's BKE_fcurve_correct_bezpart: an overlong handle is
        # shortened independently in both coordinates before curve evaluation.
        controls = [list(first.co), list(first.handle_right), list(last.handle_left), list(last.co)]
        for anchor, handle in ((0, 1), (3, 2)):
            length = abs(controls[handle][0] - controls[anchor][0])
            if length > end - start:
                factor = (end - start) / length
                controls[handle] = [a + factor * (h - a) for a, h in zip(controls[anchor], controls[handle])]
        if not all(math.isfinite(value) for control in controls for value in control):
            raise ValueError('Rotation curve handles must be finite')

        def polynomial(axis):
            a, b, c, d = (control[axis] for control in controls)
            return Polynomial((a, 3 * (b - a), 3 * (a - 2 * b + c), -a + 3 * b - 3 * c + d))

        x, y = polynomial(0), polynomial(1)
        # A narrow turn can lie between all regular probes. Component zeros
        # expose quaternion sign changes or a rapidly changing normalized axis;
        # extrema also expose short out-and-back turns.
        for root in (*y.roots(), *y.deriv().roots()):
            if abs(root.imag) <= 1e-9 and 0 < root.real < 1:
                frame = float(x(root.real))
                add_time(frame, start, end)
    return times


def _sample_key_node(hnode, root, end_frame, *, start_frame=0, allowLateStart=False):
    """Bake one joint's local action curves to KEY position/Euler-delta segments.

    This reads F-curves directly, not evaluated dependency-graph transforms.
    Unsupported procedural motion must therefore be baked before export.
    Return None for a joint without active location/rotation action curves.
    """
    # 1. Reject motion that direct F-curve sampling cannot reproduce. Ancestor
    # scale also affects this joint. KEY cannot encode animated scale or Blender
    # delta-transform channels (distinct from KEY's per-frame motion deltas).
    obj = hnode.obj
    pivots = [c for c in obj.constraints if c.type == 'PIVOT' and not c.mute and c.influence]
    rotation_paths = ('rotation_euler', 'rotation_quaternion', 'rotation_axis_angle')
    ancestor = obj
    while ancestor is not None:
        validateKeyActionState(ancestor)
        validateConstraintAnimation(ancestor)
        for curve in getActionFCurves(ancestor):
            if (curve.is_valid and not curve.mute
                    and (curve.data_path == 'scale' or curve.data_path.startswith('delta_'))):
                raise ValueError(f"KEY cannot represent animated scale/delta transforms on '{ancestor.name}'; remove scale animation or bake delta motion to location/rotation")
            if (pivots and curve.is_valid and not curve.mute and curve.data_path in rotation_paths
                    and (ancestor != obj or any(c.rotation_range != 'ALWAYS_ACTIVE' for c in pivots))):
                raise ValueError(f"Bake conditional/world-space Pivot rotation on '{obj.name}' before KEY export")

        if ancestor.animation_data and any(
            not driver.mute
            and (driver.data_path == 'scale' or driver.data_path.startswith('delta_'))
            for driver in ancestor.animation_data.drivers
        ):
            raise ValueError(f"Remove scale/delta drivers on '{ancestor.name}' before KEY export")
        if pivots and ancestor != obj and ancestor.animation_data and any(
            not driver.mute and driver.data_path in rotation_paths
            for driver in ancestor.animation_data.drivers
        ):
            raise ValueError(f"Bake driven parent rotation for Pivot-constrained object '{obj.name}' before KEY export")

        validateObjTransform(ancestor)
        if ancestor == root:
            break
        ancestor = ancestor.parent

    for constraint in obj.constraints:
        if not constraint.mute and constraint.influence and constraint.type != 'PIVOT':
            raise ValueError('Bake non-pivot constraints to transform channels before KEY export')

    if obj.animation_data:
        if hasActiveNlaStrips(obj.animation_data):
            raise ValueError('Bake NLA composition to transform channels before KEY export')

        # any() stops at the first unmuted transform driver. A driver computes
        # values from expressions/properties rather than ordinary action keys;
        # ignoring it would export a different pose. Bake it to transform keys,
        # then mute/remove the driver. Unrelated property drivers are allowed.
        if any(
            not driver.mute
            and driver.data_path in ('location', 'rotation_euler', 'rotation_quaternion', 'rotation_axis_angle')
            for driver in obj.animation_data.drivers
        ):
            raise ValueError('Bake transform drivers before KEY export')

    rotation_path = 'rotation_euler'
    if obj.rotation_mode == 'QUATERNION':
        rotation_path = 'rotation_quaternion'
    elif obj.rotation_mode == 'AXIS_ANGLE':
        rotation_path = 'rotation_axis_angle'

    # 2. Combine all active transform channels' sample times so a key on any
    # component becomes a shared segment boundary. Keep fractional times intact.
    curves = {}

    # The final fractional playback interval extends to FRAMES, not FRAMES - 1.
    end_time = float(end_frame) + 1.0
    times = {float(start_frame), float(end_frame), end_time}
    for curve in getActionFCurves(obj):
        if not curve.is_valid or curve.mute or curve.data_path not in ('location', rotation_path):
            continue
        if any(not modifier.mute for modifier in curve.modifiers):
            raise ValueError(f"Bake F-curve modifiers on '{obj.name}' before KEY export")

        channel = (curve.data_path, curve.array_index)
        if channel in curves:
            raise ValueError('Bake layered transform actions before KEY export')
        curves[channel] = curve

        for point in list(curve.keyframe_points) + list(curve.sampled_points):
            frame = float(point.co[0])
            if not math.isfinite(frame):
                raise ValueError('Animation frame must be finite')
            if start_frame <= frame <= end_time:
                times.add(frame)

    if not curves:
        return None

    if rotation_path in ('rotation_quaternion', 'rotation_axis_angle'):
        rotation_kind = 'quaternion' if rotation_path == 'rotation_quaternion' else 'axis-angle'
        for (path, axis), curve in curves.items():
            if path == rotation_path:
                times.update(frame for frame in _rotation_curve_times(curve, end_time, rotation_kind)
                             if frame >= start_frame)

    # Cache authored values/interpolation for exact linear and held evaluation.
    curve_keys = {}
    for channel, curve in curves.items():
        points = list(curve.keyframe_points)
        curve_keys[channel] = ([point.co[0] for point in points], [point.co[1] for point in points],
                               [point.interpolation for point in points])

    # 3. Match 3DO's local-coordinate export: inherited scale affects joint
    # translation; this object's own scale is baked into its mesh instead.
    scale = mathutils.Vector((1.0, 1.0, 1.0))
    parent = obj
    while parent != root:
        parent = parent.parent
        scale = vectorMultiply(scale, parent.scale)

    validateObjTransform(obj, scale)
    if (any(abs(value - scale[0]) > 1e-6 for value in scale)
            and any(path == rotation_path for path, axis in curves)):
        raise ValueError(f"Apply nonuniform parent scale before exporting animated rotation on '{obj.name}'")

    pivot = objPivot(obj, forAnimation=True)

    # Blender approximates a moving segment followed by an instantaneous jump,
    # and represents late starts with an explicit backward-extrapolated prefix.
    # Reuse its exact imported KEY entries only while the imported curves and
    # relevant transform metadata remain unchanged.
    imported = unchangedImportedJump(obj, end_time)
    if (imported is not None and imported.keyframes and start_frame == 0
            and (allowLateStart or imported.keyframes[0].frame == 0)):
        imported.idx, imported.meshName = hnode.idx, hnode.name
        for entry in imported.keyframes:
            entry.position = Vector3f(*vectorMultiply(mathutils.Vector(entry.position), scale))
            entry.deltaPosition = Vector3f(*vectorMultiply(mathutils.Vector(entry.deltaPosition), scale))
        return imported

    # A partially keyed transform takes its missing components from the object.
    default_location = tuple(obj.location)
    default_rotation = tuple(getattr(obj, rotation_path))
    native_euler = obj.rotation_mode == kImEulerOrder

    def evaluate(frame, reference=None, left_limit=False):
        # Sample local channels, then convert to the engine's PYR degrees.
        # Native Euler curves retain authored full turns; other rotation modes
        # need a compatible Euler branch to avoid artificial +/-360-degree jumps.
        def values(path, default):
            return [
                _curve_value(curves[(path, axis)], frame, left_limit, curve_keys[(path, axis)])
                if (path, axis) in curves else value
                for axis, value in enumerate(default)
            ]

        location = values('location', default_location)
        rotation = values(rotation_path, default_rotation)
        if not all(math.isfinite(value) for value in location + rotation):
            raise ValueError('Animation transforms must be finite')

        compatible = None
        if reference is not None:
            compatible = mathutils.Euler(tuple(math.radians(reference[i]) for i in (0, 2, 1)), kImEulerOrder)

        if rotation_path == 'rotation_euler':
            euler = mathutils.Euler(rotation, obj.rotation_mode)
            if not native_euler:
                euler = quaternionToImEuler(euler.to_quaternion(), compatible)
        else:
            if rotation_path == 'rotation_quaternion':
                quaternion = mathutils.Quaternion(rotation)
                if quaternion.magnitude < 1.0e-12:
                    raise ValueError('Cannot export a zero-length animation quaternion')
            else:
                axis = mathutils.Vector(rotation[1:])
                if axis.length < 1.0e-12:
                    if abs(rotation[0]) > 1.0e-12:
                        raise ValueError('Cannot export a nonzero rotation about a zero-length axis')
                    axis = mathutils.Vector((0.0, 0.0, 1.0))
                quaternion = mathutils.Quaternion(axis, rotation[0])

            euler = quaternionToImEuler(quaternion, compatible)

        entry = Keyframe()
        entry.frame = frame

        # Invert the importer's active-pivot translation before applying scale.
        entry.position = Vector3f(*vectorMultiply(mathutils.Vector(location) - pivot, scale))
        entry.orientation = eulerToPYR(euler)
        validateFloat32((*entry.position, *entry.orientation), 'Generated KEY transform')
        entry._sourceRotation = rotation
        return entry

    node = KeyNode()
    node.idx = hnode.idx
    node.meshName = hnode.name

    def bake(start, end_frame, depth=0):
        # KEY plays each segment with constant per-frame deltas. Subdivide where
        # that linear motion exceeds the tolerances or loses rotation winding.

        # 1. Probe quarter points and the endpoint, carrying a compatible Euler
        # branch forward so quaternion conversion does not invent sudden wraps.
        span = end_frame - start.frame
        probes = []
        reference = start.orientation
        for fraction in (0.25, 0.5, 0.75, 1.0):
            probe = evaluate(start.frame + span * fraction, reference, fraction == 1.0)
            probes.append(probe)
            reference = probe.orientation

        # 2. Compare the actual curve with the straight segment between endpoints.
        end = probes[-1]
        split = False
        previous = start
        for index, probe in enumerate(probes):
            fraction = (index + 1) * 0.25
            position_error = max(
                abs(probe.position[i] - (start.position[i] + (end.position[i] - start.position[i]) * fraction))
                for i in range(3)
            )
            interpolated = tuple(
                start.orientation[i] + (end.orientation[i] - start.orientation[i]) * fraction
                for i in range(3)
            )

            if native_euler:
                rotation_error = max(abs(probe.orientation[i] - interpolated[i]) for i in range(3))
            else:
                # Equivalent Euler representations can differ sharply at a singularity.
                difference = makeQuaternionRotation(interpolated).conjugated() @ makeQuaternionRotation(probe.orientation)
                rotation_error = math.degrees(2.0 * math.atan2(
                    math.sqrt(sum(value * value for value in difference[1:])), abs(difference[0])
                ))

            # Also bound rotation between probes. Endpoint agreement alone can
            # hide a complete turn, especially for non-native rotation modes.
            difference = makeQuaternionRotation(previous.orientation).conjugated() @ makeQuaternionRotation(probe.orientation)
            angular_step = math.degrees(2.0 * math.atan2(
                math.sqrt(sum(value * value for value in difference[1:])), abs(difference[0])
            ))
            if rotation_path == 'rotation_euler' and not native_euler:
                angular_step = max(
                    angular_step,
                    *(math.degrees(abs(a - b)) for a, b in zip(probe._sourceRotation, previous._sourceRotation))
                )
            elif rotation_path == 'rotation_axis_angle':
                angular_step = max(angular_step, math.degrees(abs(probe._sourceRotation[0] - previous._sourceRotation[0])))
            elif rotation_path == 'rotation_quaternion':
                # Do not take abs(dot): opposite quaternion signs can encode an
                # authored long path through a near-zero component interpolation.
                a = mathutils.Quaternion(previous._sourceRotation).normalized()
                b = mathutils.Quaternion(probe._sourceRotation).normalized()
                angular_step = max(angular_step, math.degrees(2 * math.acos(max(-1.0, min(1.0, a.dot(b))))))

            split |= position_error > 1.0e-5 or rotation_error > 0.05 or (not native_euler and angular_step > 90.0)
            previous = probe

        # 3. Split only as needed. Evaluate the right half from the midpoint's
        # normal pose, not its left limit, to preserve a jump at that boundary.
        if split:
            if depth >= 16 or span < 1.0e-5:
                raise ValueError("Cannot bake animation for '{}' within KEY interpolation tolerances".format(obj.name))
            middle_frame = start.frame + span * 0.5
            if rotation_path in ('rotation_quaternion', 'rotation_axis_angle'):
                middle_frame = float(mathutils.Vector((middle_frame, 0.0))[0])
                if not start.frame < middle_frame < end_frame:
                    raise ValueError("Cannot bake animation for '{}' at float32 frame precision".format(obj.name))
            middle_left = bake(start, middle_frame, depth + 1)
            middle = evaluate(middle_frame, middle_left.orientation)
            return bake(middle, end_frame, depth + 1)

        # 4. An accepted segment stores its slopes on the first entry; the next
        # segment supplies its own base pose, which may deliberately jump.
        _set_keyframe_delta(start, end, KeyframeFlag.PositionChange)
        _set_keyframe_delta(start, end, KeyframeFlag.OrientationChange)
        node.keyframes.append(start)
        return end

    # 4. Bake each authored interval separately so hold/jump boundaries are not
    # smoothed away by subdivision. Carry the Euler branch into the next segment.
    reference = None
    ordered_times = sorted(times)
    for first, last in zip(ordered_times, ordered_times[1:]):
        start = evaluate(first, reference)
        reference = bake(start, last).orientation

    return node


def _make_key_from_obj(key_name: str, obj: bpy.types.Object, scene: bpy.types.Scene, target='IJIM', *, fps=None, flags=None, nodeTypes=None) -> Key:
    """Build KEY metadata and joint tracks using the same node order as 3DO."""

    # 1. Copy playback metadata. FRAMES includes the final fractional interval
    # after Blender's last integer frame, hence frame_end + 1.
    key           = Key(key_name)
    key.flags     = getSceneKeyFlags(scene, flags)
    key.nodeTypes = Mesh3doNodeType.fromHex(scene.sith_key_types if nodeTypes is None else nodeTypes)
    key.numFrames = scene.frame_end + 1
    key.fps       = getSceneFrameRate(scene) if fps is None else float(fps)
    if not math.isfinite(key.fps) or key.fps <= 0:
        raise ValueError('Animation FPS must be finite and positive')
    if scene.frame_end < 0:
        raise ValueError('KEY animations must end at frame zero or later')
    start_frame = scene.frame_start if target == 'CUSTOM' else 0
    if not 0 <= start_frame <= scene.frame_end:
        raise ValueError('Generic KEY start frame must be nonnegative and not exceed the end frame')

    # 2. Decode event markers, including fractional times stored in their names.
    for marker in scene.timeline_markers:
        m       = KeyMarker()
        try:
            m.frame, m.type = markerTimeAndType(marker)
        except (ValueError, KeyError):
            print(f"\nWarning: Invalid marker '{marker.name}' at frame {marker.frame}, skipping it!")
            continue
        key.markers.append(m)

    key.markers.sort(key=lambda marker: marker.frame)

    # An EMPTY wrapper carries the static 3DO insert offset, not a KEY joint.
    # Its procedural/animated motion must be baked onto joints before export.
    validateKeyActionState(obj)
    validateConstraintAnimation(obj)
    if obj.type == 'EMPTY' and obj.children:
        transform_paths = ('location', 'rotation_euler', 'rotation_quaternion', 'rotation_axis_angle')
        if any(curve.is_valid and not curve.mute and curve.data_path in transform_paths
               for curve in getActionFCurves(obj)):
            raise ValueError('Bake animated model wrapper motion onto joints before KEY export')
        if obj.animation_data:
            if any(not driver.mute and driver.data_path in transform_paths
                   for driver in obj.animation_data.drivers):
                raise ValueError('Bake model wrapper transform drivers onto joints before KEY export')
            if hasActiveNlaStrips(obj.animation_data):
                raise ValueError('Bake model wrapper NLA motion onto joints before KEY export')

    # 3. Reuse 3DO's normalized hierarchy order without extracting mesh geometry.
    # The header counts all joints, even those with no animated track below.
    model3do      = makeModel3doFromObj(key_name, obj, hierarchyOnly=True)
    key.numJoints = len(model3do.meshHierarchy)
    validateKeyForTarget(key, target)

    # 4. Bake animated tracks, then validate the populated resource for the game.
    for hnode in model3do.meshHierarchy:
        node = _sample_key_node(hnode, obj, scene.frame_end,
                                start_frame=start_frame, allowLateStart=target == 'CUSTOM')
        if node is not None:
            key.nodes.append(node)

    if target == 'GRIM':
        # Retain opaque records only while animated joint identities match.
        # Reordering/renaming joints falls back to new binary record defaults.
        if kKeyBinaryData in obj:
            try:
                payload = json.loads(obj[kKeyBinaryData])
                header, nodes = payload['header'], payload['nodes']
                if not isinstance(header, dict) or not isinstance(nodes, dict):
                    raise ValueError('Expected binary KEY metadata dictionaries')
                if (header.get('originalJoints') == key.numJoints
                        and all(str(node.idx) in nodes and nodes[str(node.idx)]['name'] == node.meshName
                                for node in key.nodes)):
                    key.binaryData = header
                    if header.get('originalFrames') == 0 and scene.frame_end == 0:
                        key.numFrames = 0
                    for node in key.nodes:
                        node.binaryData = nodes[str(node.idx)]['metadata']
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError('Invalid imported binary KEY metadata') from error
        key = prepareGrimExport(key)

    validateKeyForTarget(key, target)
    return key
