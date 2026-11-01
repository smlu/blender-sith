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

from .key import (
    Key,
    KeyFlag,
    Keyframe,
    KeyframeFlag,
    KeyMarker,
    KeyMarkerType,
    KeyNode
)

def __getattr__(name):
    if name == 'exportKey':
        from .keyExporter import exportKey
        return exportKey
    if name == 'importKey':
        from .keyImporter import importKey
        return importKey
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')

__all__ = [
    "exportKey",
    "importKey",
    "Key",
    "KeyFlag",
    "Keyframe",
    "KeyframeFlag",
    "KeyMarker",
    "KeyMarkerType",
    "KeyNode"
]
