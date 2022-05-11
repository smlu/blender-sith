import numpy as np
from pathlib import Path
from struct import Struct
from typing import NamedTuple, List, Tuple, Union

file_magic       = b'CMP '
required_version = 0x1E


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
                raise ImportError("Invalid CMP file")
            if h.version != required_version:
                raise ImportError("Invalid CMP file version")

            # Read palette
            pal = f.read(256 * 3) # 256 * len(CmpPaletteRGB)
            cmp = cls()
            cmp.palette = [CmpPaletteRGB(*e) for e in np.frombuffer(pal, dtype=np.uint8).reshape(-1,3)]
            return cmp
