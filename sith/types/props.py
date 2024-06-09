# Sith Blender Addon
# Copyright (c) 2019-2024 Crt Vavros

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