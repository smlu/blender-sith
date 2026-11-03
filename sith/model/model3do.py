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

from enum import IntEnum, unique
import math
from collections import defaultdict
from ..types import (
    Flag,
    Vector2f,
    Vector3f,
    Vector4f
)
from typing import Dict, List

@unique
class FaceType(Flag):
    Normal         = 0x00
    DoubleSided    = 0x01
    Translucent    = 0x02
    TexClamp_x     = 0x04,  # (IJIM interpretation) Clamp the texture in X instead of repeating it.
    TexClamp_y     = 0x08,  # (IJIM interpretation) Clamp the texture in Y instead of repeating it.
    TexFilterNone  = 0x10,  # (IJIM interpretation) Use nearest filtering; MOTS/Grim instead force lighting mode 1.
    ZWriteDisabled = 0x20,  # (IJIM interpretation) Disable ZWrite for the polygon face.
    IjimLedge      = 0x40,  # (IJIM specific) Player can hang on the ledge of this polygon face. (same as surface flag Ledge = 0x1000000 for world surface)
                            #   e.g.: bab_bull_block.3do, olv_statue_lefty.3do, tem_bridge_20mholes.3do
    IjimFogEnabled = 0x100, # (IJIM specific) Enables fog rendering for the face polygon.
                            #  Note: This flag is set by default for all surfaces but sky surfaces.

    IjimWhipAim    = 0x200 # (IJIM specific) Marks the whip aim surface (same as surface flag `WhipAim` = 0x10000000).
                           #   e.g.: aet_dais_trio.3do

@unique
class GeometryMode(IntEnum):
    NotDrawn   = 0
    VertexOnly = 1
    Wireframe  = 2
    Solid      = 3
    Texture    = 4

@unique
class LightMode(IntEnum):
    FullyLit   = 0
    NotLit     = 1
    Diffuse    = 2
    Gouraud    = 3
    GfUnknown6 = 6 # Grim Fandango

@unique
class TextureMode(IntEnum):
    Affine               = 0
    Perspective          = 1
    PerspectiveUnknown   = 2
    PerspectiveCorrected = 3 # <- IJIM use only this

@unique
class Mesh3doNodeFlags(Flag):
    Nothing      = 0x00
    Unknown_01   = 0x01
    Unknown_02   = 0x02
    Unknown_04   = 0x04
    Unknown_08   = 0x08
    Unknown_10   = 0x10
    Unknown_20   = 0x20
    Unknown_40   = 0x40
    Unknown_80   = 0x80
    Unknown_100  = 0x100
    Unknown_200  = 0x200
    Unknown_400  = 0x400
    Unknown_800  = 0x800
    Unknown_1000 = 0x1000
    Unknown_2000 = 0x2000
    Unknown_4000 = 0x4000
    Unknown_8000 = 0x8000

@unique
class Mesh3doNodeType(Flag):
    Nothing       = 0x00
    Torso         = 0x01
    LeftArm       = 0x02
    RightArm      = 0x04
    Head          = 0x08
    Hip           = 0x10
    LeftLeg       = 0x20
    RightLeg      = 0x40
    LeftHand      = 0x80
    #LeftHand2    = 0x82
    RightHand     = 0x100
    #RightHand2   = 0x104
    Unknown_200   = 0x200
    Vehicle       = 0x400
    BackPart      = 0x800
    FrontPart     = 0x1000
    Unknown_2000  = 0x2000
    Unknown_4000  = 0x4000
    Unknown_8000  = 0x8000
    # BackWheel  = 0xC00    #Vehicle + BackPart
    # FrontWheel = 0x1400   #Vehicle + FrontWheel
    # Unknown1  = 0x0001    #tu_hit_shoulderl.key
    # Unknown2  = 0x0004    #tu_attack_ready.key
    # Unknown3  = 0x0008    #tu_hit_headl
    # Unknown4  = 0x000F    #0so_armsmid_3_3.key
    # Unknown5  = 0x0070    #vo_rotate_left.key
    # Unknown6  = 0x0104    #in_attack_put_gun.key
    # Unknown7  = 0x010D    #in_attack_put_whip.key, in_attack_put_machete.key
    # Unknown8  = 0x0186    #0vo_bothup_3_3.key
    # Unknown9  = 0x018F    #in_attack_unaim_rifle.key, in_attack_unaim_shotgun.key, in_attack_put_imp.key
    # Unknown10 = 0x04FB    #in_activate_medium_left.key
    # Unknown11 = 0x0904    #in_attack_pull_whip.key, in_attack_pull_satchel.key, in_attack_pull_imp.key
    # Unknown12 = 0x0986    #in_attack_pull_rifle.key
    # Unknown13 = 0x090D    #in_attack_pull_machete.key
    # Unknown14 = 0x098F    #in_attack_pull_fists.key

class Mesh3doFace:
    def __init__(self):
        self.binaryData = None

        self.material_idx: int      = -1
        self.t: FaceType            = FaceType.Normal
        self.geo_mode: GeometryMode = GeometryMode.NotDrawn
        self.light_mode: LightMode  = LightMode.FullyLit
        self.tex_mode: TextureMode  = TextureMode.Affine

        self.c: Vector4f    = Vector4f(0.0, 0.0, 0.0, 0.0) # RGBA color
        self.vi: List[int]  = []  # List of indexes to the mesh list of vertices (vertex idx)
        self.tvi: List[int] = []  # List of indexes to the mesh list of texture vertices (tex vertex idx)
        self.n: Vector3f    = Vector3f(0.0, 0.0, 0.0) # face normal(x, y, z)

    @property
    def materialIdx(self) -> int:
        return self.material_idx

    @materialIdx.setter
    def materialIdx(self, idx: int):
        self.material_idx = idx

    @property
    def type(self) -> FaceType:
        return self.t

    @type.setter
    def type(self, type: FaceType):
        self.t = type

    @property
    def geometryMode(self) -> GeometryMode:
        return self.geo_mode

    @geometryMode.setter
    def geometryMode(self, mode: GeometryMode):
        self.geo_mode = mode

    @property
    def lightMode(self) -> LightMode:
        return self.light_mode

    @lightMode.setter
    def lightMode(self, mode: LightMode):
        self.light_mode = mode

    @property
    def textureMode(self) -> TextureMode:
        return self.tex_mode

    @textureMode.setter
    def textureMode(self, mode: TextureMode):
        self.tex_mode = mode

    @property
    def color(self) -> Vector4f:
        return self.c

    @color.setter
    def color(self, color: Vector4f):
        self.c = color

    @property
    def vertexIdxs(self) -> List[int]:
        return self.vi

    @vertexIdxs.setter
    def vertexIdxs(self, idxs: List[int]):
        self.vi = idxs

    @property
    def uvIdxs(self) -> List[int]:
        return self.tvi

    @uvIdxs.setter
    def uvIdxs(self, idxs: List[int]):
        self.tvi = idxs

    @property
    def normal(self) -> Vector3f:
        return self.n

    @normal.setter
    def normal(self, normal: Vector3f):
        self.n = normal

class Mesh3do:
    def __init__(self, idx: int = 0, name: str =""):
        self.binaryData = None
        self.shadow     = None

        self.i: int                 = idx
        self.mesh_name: str         = name
        self.mesh_radius: float     = 0.0
        self.geo_mode: GeometryMode = GeometryMode.NotDrawn
        self.light_mode: LightMode  = LightMode.FullyLit
        self.tex_mode: TextureMode  = TextureMode.Affine

        self.v:  List[Vector3f] = [] # vertices
        self.vc: List[Vector4f] = [] # vertex colors
        self.vn: List[Vector3f] = [] # vertex normals
        self.tv: List[Vector2f] = [] # texture vertices

        self.face_list: List[Mesh3doFace] = []

    @property
    def idx(self) -> int:
        return self.i

    @idx.setter
    def idx(self, idx: int):
        self.i = idx

    @property
    def name(self) -> str:
        return self.mesh_name

    @name.setter
    def name(self, name: str):
        self.mesh_name = name

    @property
    def radius(self) -> float:
        return self.mesh_radius

    @radius.setter
    def radius(self, radius: float):
        self.mesh_radius = radius

    @property
    def geometryMode(self) -> GeometryMode:
        return self.geo_mode

    @geometryMode.setter
    def geometryMode(self, mode: GeometryMode):
        self.geo_mode = mode

    @property
    def lightMode(self) -> LightMode:
        return self.light_mode

    @lightMode.setter
    def lightMode(self, mode: LightMode):
        self.light_mode = mode

    @property
    def textureMode(self) -> TextureMode:
        return self.tex_mode

    @textureMode.setter
    def textureMode(self, mode: TextureMode):
        self.tex_mode = mode

    @property
    def vertices(self) -> List[Vector3f]:
        return self.v

    @vertices.setter
    def vertices(self, vertices: List[Vector3f]):
        self.v = vertices

    @property
    def vertexColors(self) -> List[Vector4f]:
        return self.vc

    @vertexColors.setter
    def vertexColors(self, colors: List[Vector4f]):
        self.vc = colors

    @property
    def normals(self) -> List[Vector3f]:
        return self.vn

    @normals.setter
    def normals(self, normals: List[Vector3f]):
        self.vn = normals

    @property
    def uvs(self) -> List[Vector2f]:
        return self.tv

    @uvs.setter
    def uvs(self, texVert: List[Vector2f]):
        self.tv = texVert

    @property
    def faces(self) -> List[Mesh3doFace]:
        return self.face_list

    @faces.setter
    def faces(self, faces: List[Mesh3doFace]):
        self.face_list = faces

class Model3doGeoSet:
    def __init__(self):
        self.mesh_list: List[Mesh3do] = []

    @property
    def meshes(self) -> List[Mesh3do]:
        return self.mesh_list

    @meshes.setter
    def meshes(self, meshes: List[Mesh3do]):
        self.mesh_list = meshes

class Mesh3doNode:
    def __init__(self, name: str = ""):
        self.binaryData = None

        self._idx: int           = -1
        self.f: Mesh3doNodeFlags = Mesh3doNodeFlags.Nothing
        self.t: Mesh3doNodeType  = Mesh3doNodeType.Nothing
        self.n: str              = name
        self.mesh_i: int         = -1
        self.parent_i: int       = -1
        self.first_child_i: int  = -1
        self.sibling_i: int      = -1
        self.num_children: int   = -1
        self._o                  = None

        self.pos: Vector3f = Vector3f(0.0, 0.0, 0.0)# x,y,z
        self.rot: Vector3f = Vector3f(0.0, 0.0, 0.0) # pitch, yaw, roll:
        self.piv: Vector3f = Vector3f(0.0, 0.0, 0.0) # pivotx, pivoty, pivotz

    @property
    def idx(self) -> int:
        return self._idx

    @idx.setter
    def idx(self, idx: int):
        self._idx = idx

    @property
    def flags(self) -> Mesh3doNodeFlags:
        return self.f

    @flags.setter
    def flags(self, flags: Mesh3doNodeFlags):
        self.f = flags

    @property
    def type(self) -> Mesh3doNodeType:
        return self.t

    @type.setter
    def type(self, type: Mesh3doNodeType):
        self.t = type

    @property
    def name(self) -> str:
        return self.n

    @name.setter
    def name(self, name: str):
        self.n = name

    @property
    def meshIdx(self) -> int:
        return self.mesh_i

    @meshIdx.setter
    def meshIdx(self, idx: int):
        self.mesh_i = idx

    @property
    def parentIdx(self) -> int:
        return self.parent_i

    @parentIdx.setter
    def parentIdx(self, idx: int):
        self.parent_i = idx

    @property
    def firstChildIdx(self) -> int:
        return self.first_child_i

    @firstChildIdx.setter
    def firstChildIdx(self, idx: int):
        self.first_child_i = idx

    @property
    def siblingIdx(self) -> int:
        return self.sibling_i

    @siblingIdx.setter
    def siblingIdx(self, idx: int):
        self.sibling_i = idx

    @property
    def numChildren(self) -> int:
        return self.num_children

    @numChildren.setter
    def numChildren(self, num: int):
        self.num_children = num

    @property
    def position(self) -> Vector3f:
        return self.pos

    @position.setter
    def position(self, pos: Vector3f):
        self.pos = pos

    @property
    def rotation(self) -> Vector3f:
        return self.rot

    @rotation.setter
    def rotation(self, rot: Vector3f):
        self.rot = rot

    @property
    def pivot(self) -> Vector3f:
        return self.piv

    @pivot.setter
    def pivot(self, piv: Vector3f):
        self.piv = piv

    @property
    def obj(self):
        """ Returns associated blender object """
        return self._o

    @obj.setter
    def obj(self, obj):
        """ Sets associated blender object """
        self._o = obj

class Model3do:
    def __init__(self, name: str = ""):
        self.binaryData = None

        self.model_name: str          = name
        self.material_list: List[str] = []
        self.col_radius: float        = 0.0
        self.insert_offset: Vector3f  = Vector3f(0.0, 0.0, 0.0) # x,y, z

        self.geoset_list: List[Model3doGeoSet]           = []
        self.mesh_nodes: List[Mesh3doNode] = []

    @property
    def name(self) -> str:
        return self.model_name

    @name.setter
    def name(self, name: str):
        self.model_name = name

    @property
    def materials(self) -> List[str]:
        return self.material_list

    @materials.setter
    def materials(self, materials: List[str]):
        self.material_list = materials

    @property
    def radius(self) -> float :
        return self.col_radius

    @radius.setter
    def radius(self, radius: float):
        self.col_radius = radius

    @property
    def insertOffset(self) -> Vector3f:
        return self.insert_offset

    @insertOffset.setter
    def insertOffset(self, offset: Vector3f):
        self.insert_offset = offset

    @property
    def geosets(self) -> List[Model3doGeoSet]:
        return self.geoset_list

    @geosets.setter
    def geosets(self, geosets: List[Model3doGeoSet]):
        self.geoset_list = geosets

    @property
    def meshHierarchy(self) -> List[Mesh3doNode]:
        return self.mesh_nodes

    @meshHierarchy.setter
    def meshHierarchy(self, nodes: List[Mesh3doNode]):
        self.mesh_nodes = nodes

    def reorderNodes(self, requireRoot: bool = False) -> None:
        """
        Reorders nodes by their sequence number.
        3DO export requires one root at entry 0; KEY export can use flat joint lists.
        """
        # 1. Snapshot old parent indices before sorting or renumbering nodes.
        # Parent references address the old list, not the sequence-number values.
        original = list(self.meshHierarchy)
        parents = [node.parentIdx for node in original]
        if any(parent < -1 or parent >= len(original) for parent in parents):
            raise ValueError('Model hierarchy has an invalid parent index')

        visited = set()
        for index in range(len(original)):
            chain = set()
            while index >= 0 and index not in visited:
                if index in chain:
                    raise ValueError('Model hierarchy contains a parent cycle')
                chain.add(index)
                index = parents[index]
            visited.update(chain)

        roots = [index for index, parent in enumerate(parents) if parent == -1]
        if requireRoot and original and len(roots) != 1:
            raise ValueError('Model hierarchy must have exactly one root')

        # 2. Preserve stable sequence ordering whenever it starts at the root.
        # Automatic (-1) children need special handling when the root has an
        # explicit sequence number, but ties must still retain traversal order.
        order = sorted(range(len(original)), key=lambda index: original[index].idx)
        if len(roots) == 1 and order[0] != roots[0]:
            # Automatic children must not precede an explicitly numbered root.
            order = sorted(
                range(len(original)),
                key=lambda index: (original[index].idx if original[index].idx >= 0 else math.inf, index)
            )
        if requireRoot and order and order[0] != roots[0]:
            raise ValueError('Model root must sort to node 0; check the hierarchy sequence numbers')

        # 3. Build the complete old-to-new map before modifying any node. Mesh
        # indices stay independent; optional mesh synchronization happens later.
        remap = {old: new for new, old in enumerate(order)}
        nodes = [original[index] for index in order]
        kids_map: Dict[int, List[int]] = defaultdict(list)
        for idx, old in enumerate(order):
            node = original[old]
            node.idx = idx
            node.parentIdx = remap[parents[old]] if parents[old] >= 0 else -1
            node.firstChildIdx, node.siblingIdx, node.numChildren = -1, -1, 0
            if node.parentIdx >= 0:
                kids_map[node.parentIdx].append(idx)

        # 4. Rebuild child/sibling traversal links from the remapped parents,
        # using the new order for each sibling chain.
        for pidx, kids in kids_map.items():
            nodes[pidx].firstChildIdx = kids[0]
            nodes[pidx].numChildren = len(kids)
            for current, following in zip(kids, kids[1:]):
                nodes[current].siblingIdx = following

        self.meshHierarchy = nodes
