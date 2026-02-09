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

import numpy as np
from pathlib import Path
from struct import Struct
from typing import NamedTuple, List, Union

file_magic         = b'CMP '
supported_versions = [
    0x14, # Grim Fandango
    0x1E  # Star Wars JKDF2, MOTS, DroidWorks
]

class CmpHeader(NamedTuple):
    format = Struct('<4sii52s')
    signature: bytes
    version: int
    hasAlphaTable: bool
    unknown: bytes

class CmpPaletteRGB(NamedTuple):
    r: int
    g: int
    b: int

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
