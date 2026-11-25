# SPDX-License-Identifier: GPL-3.0-or-later
"""Euler forms of KEY rotations, without Blender.

A KEY stores rotations as (pitch, yaw, roll) degrees for ``R = Rz(yaw) Rx(pitch) Ry(roll)``
(``rdMatrix_Build34``). From each entry the engine moves each component with that entry's own
deltas until the next entry (``rdPuppet_BuildJointMatrices``), and an exporter sets those deltas
to reach the next entry's triple. Two triples for the same rotation therefore do not play the
same way between entries: one may take the short way, the other a full turn.

Every rotation has two Euler forms, ``(p, y, r)`` and ``(180 - p, y + 180, r + 180)``, and each
component may also carry whole turns. ``nearestEuler`` picks, among those, the triple nearest a
previous one. This keeps a sampled animation's components continuous.

At pitch exactly +-90 degrees, yaw and roll are not separable: only their sum (pitch +90) or
difference (pitch -90) changes the rotation. These helpers choose between the two forms and
whole turns only; they do not choose within that family.
"""

__all__ = ['eulerTwin', 'unwrapEuler', 'nearestEuler']


def eulerTwin(pyr) -> tuple:
    """The other Euler form of the same rotation: ``(180 - pitch, yaw + 180, roll + 180)``."""
    pitch, yaw, roll = (float(value) for value in pyr)
    return (180.0 - pitch, yaw + 180.0, roll + 180.0)


def unwrapEuler(previous, current) -> tuple:
    """``current`` shifted by whole turns, per component, to lie within 180 degrees of ``previous``.

    A component exactly 180 degrees away keeps its value.
    """
    return tuple(float(c) - 360.0 * round((float(c) - float(p)) / 360.0)
                 for p, c in zip(previous, current))


def nearestEuler(previous, current) -> tuple:
    """``current``'s rotation as the (pitch, yaw, roll) triple nearest ``previous``.

    The candidates are ``current`` and ``eulerTwin(current)``, each shifted by whole turns per
    component (``unwrapEuler``). The smaller sum of absolute component differences wins; a tie
    keeps ``current``'s form. This is ``near_euler`` from Red's lightwhip tools.
    """
    previous = tuple(float(value) for value in previous)
    same = unwrapEuler(previous, current)
    twin = unwrapEuler(previous, eulerTwin(current))

    def cost(candidate):
        return sum(abs(a - b) for a, b in zip(candidate, previous))

    return same if cost(same) <= cost(twin) + 1e-9 else twin
