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

from .benchmark import BenchmarkMeter
from .enum import Flag
def __getattr__(name):
    if name == 'HexProperty':
        from .props import HexProperty
        return HexProperty
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')

from .vector import (
    Vector2f,
    Vector3f,
    Vector4f
)

__all__ = [
    'BenchmarkMeter',
    'HexProperty',
    'Flag',
    'Vector2f',
    'Vector3f',
    'Vector4f'
]
