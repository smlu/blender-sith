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