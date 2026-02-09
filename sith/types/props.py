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
    def __get_hexvalue(self):
        if varName in self:
            return self[varName]
        return ''

    def __set_hexvalue(self, value):
        try:
            if len(value) == 0:
                value = default
            int(value, 16)
            self[varName] = value.upper().lstrip('0X')
            if len(self[varName]) == 0:
                self[varName] = '0'
            if pad:
                l = len(self[varName])
                l += l % 2
                self[varName] = self[varName].zfill(l)
        except: pass

    return bpy.props.StringProperty(
        name = name,
        description = description,
        default = default,
        maxlen = maxlen,
        get = __get_hexvalue,
        set = __set_hexvalue,
        options = options
    )