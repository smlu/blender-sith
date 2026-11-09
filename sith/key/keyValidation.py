# Sith Blender Addon
# Copyright (C) 2026 Crt Vavros
# SPDX-License-Identifier: GPL-3.0-or-later
"""Export limits for the supported, verified KEY engine contracts."""

from ..text.serutils import assertName
from ..types.vector import validateFloat32

kKeyTargets = (
    ('IJIM', 'Infernal Machine', '64 joints, 16 markers, 63-character names'),
    ('JKDF2', 'Jedi Knight: Dark Forces II', '64 joints, 8 markers, 31-character names'),
    ('MOTS', 'Mysteries of the Sith', '64 joints, 8 markers, 31-character names'),
    ('GRIM', 'Grim Fandango', 'Binary format; 8 markers, 36-character resource names and 32-character joint names'),
    ('CUSTOM', 'Generic', 'Text format without engine-specific limits; allows nonzero first frames and uses the scene start frame. Shared format and safety checks remain'),
)
# Each tuple is (joint count, marker count, name length); None removes that
# engine-specific limit but does not bypass the text format's name validation.
kKeyTargetLimits = {
    'IJIM': (64, 16, 63),
    'JKDF2': (64, 8, 31),
    'MOTS': (64, 8, 31),
    'GRIM': (None, 8, None),
    'CUSTOM': (None, None, None)
}


def validateKeyNumericData(key):
    """Check stored numbers before a writer can truncate an existing export."""
    validateFloat32((key.numFrames, key.numJoints, key.fps, key.flags, key.nodeTypes), 'KEY header')
    for marker in key.markers:
        validateFloat32((marker.frame, marker.type), 'KEY marker')
    for node in key.nodes:
        validateFloat32((node.idx,), 'KEY joint index')
        for entry in node.keyframes:
            validateFloat32((entry.frame, entry.flags), 'KEY entry')
            validateFloat32((value
                             for vector in (entry.position, entry.orientation,
                                            entry.deltaPosition, entry.deltaRotation)
                             for value in vector), 'KEY transforms and deltas')


def validateKeyForTarget(key, target):
    """Check engine limits before sampling and again after tracks are populated."""
    if target not in kKeyTargetLimits:
        raise ValueError(f"Unknown KEY export target '{target}'")

    if target == 'GRIM':
        from .keyBinary import validateBinaryKey
        validateBinaryKey(key)
        return

    joints, markers, nameLength = kKeyTargetLimits[target]
    if joints is not None and key.numJoints > joints:
        raise ValueError(f'{target} supports at most {joints} KEY joints; found {key.numJoints}')
    if markers is not None and len(key.markers) > markers:
        raise ValueError(f'{target} supports at most {markers} KEY markers; found {len(key.markers)}')

    # Header-only validation has no nodes yet; the final call also checks every
    # exported track name against the target's fixed-size engine name buffers.
    for name in [key.name, *(node.meshName for node in key.nodes)]:
        assertName(name)
        if nameLength is not None and len(name) > nameLength:
            raise ValueError(f"{target} KEY name '{name}' exceeds {nameLength} characters")
