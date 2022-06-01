# Sith Blender Addon
# Copyright (c) 2019-2022 Crt Vavros

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

import numpy as np
from pathlib import Path
from struct import Struct
from typing import NamedTuple, List, Tuple, Union

file_magic         = b'CMP '
supported_versions = [
    0x14, # Grim Fandango
    0x1E  # Star Wars JKDF2, MOTS, DroidWorks
]

class CmpHeader(NamedTuple):
    format = Struct('<4sii52s')
    signature: str
    version: int
    hasAlphaTable: bool
    unknown: bytes

class CmpPaletteRGB(NamedTuple):
    r: int
    g: int
    b: int

    def toLinear(self, alpha=1.0) -> Tuple[float, float, float, float]:
        return (float(self.r/255), float(self.g/255), float(self.b/255), alpha)

class ColorMap:
    palette: List[CmpPaletteRGB]

    @classmethod
    def load(cls, filePath: Union[Path, str]) -> 'ColorMap':
        """
        Loads palette from cmp file.
        :`filePath`: Path to the cmp file.
        """
        if isinstance(filePath, str):
            filePath = Path(filePath)
        if not filePath.is_file() or not filePath.exists():
            raise ImportError('Invalid cmp file path')

        with filePath.open('rb') as f:
            rh = CmpHeader.format.unpack(f.read(CmpHeader.format.size))
            h = CmpHeader(*rh)
            if h.signature != file_magic:
                raise ImportError('Invalid CMP file')
            if h.version not in supported_versions:
                raise ImportError(f'Invalid CMP file version 0x{h.version:02x}')

            # Read palette
            pal = f.read(256 * 3) # 256 * len(CmpPaletteRGB)
            cmp = cls()
            cmp.palette = [CmpPaletteRGB(*e) for e in np.frombuffer(pal, dtype=np.uint8).reshape(-1,3)]
            return cmp
