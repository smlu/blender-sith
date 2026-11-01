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

from typing import Optional
import bpy

def HexProperty(varName: str, name: Optional[str] = '', description: Optional[str] = '', default : Optional[str] = '', maxlen: Optional[int] = None, options: Optional[set] = set(), pad: bool = False) -> bpy.props.StringProperty:
    """Hex digits with an optional input prefix; maxlen limits canonical digits.

    Validate after removing the prefix, not with RNA's raw string limit, which
    raises callback errors for valid inputs such as 0xFFFF in a four-digit field.
    Invalid/negative/out-of-range input leaves the previous value unchanged.
    """
    def normalize(value):
        number = int(value or default or '0', 16)
        if number < 0:
            raise ValueError('Hex flags cannot be negative')
        value = format(number, 'X')
        if pad:
            value = value.zfill(len(value) + len(value) % 2)
        if maxlen and len(value) > maxlen:
            raise ValueError('Hex flags exceed the digit limit')
        return value

    default_value = normalize(default)

    def __get_hexvalue(self):
        if varName in self:
            return self[varName]
        return default_value

    def __set_hexvalue(self, value):
        try:
            normalized = normalize(value)
        except (ValueError, TypeError):
            return
        self[varName] = normalized

    return bpy.props.StringProperty(
        name = name,
        description = description,
        default = default_value,
        maxlen = 0,
        get = __get_hexvalue,
        set = __set_hexvalue,
        options = options
    )
