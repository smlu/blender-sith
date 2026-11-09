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

def HexProperty(varName: str, name: Optional[str] = '', description: Optional[str] = '', default : Optional[str] = '', maxlen: int = 0, options: Optional[set] = set(), pad: bool = False) -> bpy.props.StringProperty:
    """Hex text property; Blender's maxlen=0 preserves all mask digits."""
    def normalize(value):
        number = int(value, 16)
        if number < 0:
            raise ValueError('Hexadecimal masks cannot be negative')
        value = format(number, 'X')
        if pad:
            value = value.zfill(len(value) + len(value) % 2)
        return value

    defaultValue = normalize(default) if default else ''

    def __get_hexvalue(self):
        if varName in self:
            return self[varName]
        # Reading a default must not store an explicit override on an operator.
        return defaultValue

    def __set_hexvalue(self, value):
        try:
            self[varName] = normalize(value) if value else defaultValue
        except (ValueError, TypeError):
            pass

    return bpy.props.StringProperty(
        name = name,
        description = description,
        default = default,
        maxlen = maxlen,
        get = __get_hexvalue,
        set = __set_hexvalue,
        options = options
    )
