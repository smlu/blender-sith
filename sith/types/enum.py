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

from enum import IntFlag

class Flag(IntFlag):

    def hex(self) -> str:
        return hex(self)

    @classmethod
    def fromHex(cls, hexvalue: str) -> 'Flag':
        if len(hexvalue) == 0:
            hexvalue = '0'
        return cls(int(hexvalue, 16))

    def toSet(self) -> set:
        return { m.name for m in self.__class__ if m.value & self.value }

    @classmethod
    def fromSet(cls, setflags: set) -> 'Flag':
        flags = cls(0)
        for v in setflags:
            try:
                flags |= cls[v]
            except: pass
        return flags