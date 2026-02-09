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

from typing import NamedTuple

class Vector2f(NamedTuple):
    x: float
    y: float

    def __repr__(self) -> str:
        return f'<Vector2f ({self.x}, {self.y})>'

class Vector3f(NamedTuple):
    x: float
    y: float
    z: float

    def __repr__(self) -> str:
        return f'<Vector3f ({self.x}, {self.y}, {self.z})>'

class Vector4f(NamedTuple):
    x: float
    y: float
    z: float
    w: float

    def __repr__(self) -> str:
        return f'<Vector4f ({self.x}, {self.y}, {self.z}, {self.w})>'
