from typing import Optional
import bpy

def HexProperty(varName: str, name: Optional[str] = '', description: Optional[str] = '', default : Optional[str] = '', maxlen: Optional[int] = None, pad: bool = False) -> bpy.props.StringProperty:
    def __get_hexvalue(self):
        if varName in self:
            return self[varName] 
        return ''

    def __set_hexvalue(self, value):
        try:
            if len(value) == 0:
                value = '0'
            int(value, 16)
            self[varName] = value.upper().lstrip('0X')
            if pad:
                l = len(self[varName])
                l += l % 2
                self[varName] = self[varName].zfill(l)
        except: pass

    return bpy.props.StringProperty(
        name = name,
        description = description,
        maxlen = maxlen,
        get = __get_hexvalue,
        set = __set_hexvalue,
    )