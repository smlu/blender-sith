# SPDX-FileCopyrightText: 2026 Crt Vavros
# SPDX-License-Identifier: GPL-3.0-or-later
"""Conservative KEY recovery: omit unusable data without inventing poses."""
from .key import KeyFileFormat, KeyMarkerType
from ..types.vector import validateFloat32


def recoveryWarning(warnings, message):
    print(f'\nWarning: {message}')
    if warnings is not None:
        warnings.append(message)


def recoverKey(key, warnings=None):
    """Keep valid tracks and markers; structural bounds remain the loader's job."""
    # A bad header cannot be recovered by guessing the clip's duration or FPS.
    validateFloat32((key.fps,), 'KEY FPS')
    if key.fps <= 0 or key.numFrames < 0 or key.numJoints < 0:
        raise ValueError('Cannot recover KEY with invalid playback metadata')

    markers = []
    for marker in key.markers:
        try:
            validateFloat32((marker.frame,), 'KEY marker frame')
            if marker.type not in KeyMarkerType._value2member_map_:
                raise ValueError('unsupported marker type')
        except ValueError as error:
            recoveryWarning(warnings, f'Omitted KEY marker at {marker.frame}: {error}')
        else:
            markers.append(marker)
    key.markers = markers

    # Drop the entire damaged track, not just its bad entry: removing a segment
    # would otherwise extrapolate a different motion across the missing data.
    nodes = []
    dropped = False
    for node in key.nodes:
        try:
            previous = None
            for entry in node.keyframes:
                validateFloat32((entry.frame,), 'KEY entry frame')
                if entry.frame < 0 or (previous is not None and (
                        entry.frame < previous or (entry.frame == previous and key.fileFormat != KeyFileFormat.GrimBinary))):
                    raise ValueError('entry frames are negative or out of order')
                validateFloat32((value
                                 for vector in (entry.position, entry.orientation,
                                                entry.deltaPosition, entry.deltaRotation)
                                 for value in vector), 'KEY transforms and deltas')
                previous = entry.frame
        except ValueError as error:
            dropped = True
            recoveryWarning(warnings, f'Omitted KEY joint {node.idx} ({node.meshName}): {error}')
        else:
            nodes.append(node)
    if dropped and not any(node.keyframes for node in nodes):
        raise ValueError('KEY recovery found no usable animation tracks')
    key.nodes = nodes
    return key
