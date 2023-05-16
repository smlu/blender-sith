# Sith Blender Addon
# Copyright (c) 2019-2023 Crt Vavros

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

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