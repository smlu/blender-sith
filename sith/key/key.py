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

from enum import IntEnum, unique
from typing import List
from sith.model import Mesh3doNodeType
from sith.types import Flag, Vector3f

@unique
class KeyFlag(Flag):
    Loop              = 0x0
    UsePuppetFPS      = 0x1
    NoLoop            = 0x2
    PauseOnLastFrame  = 0x4
    RestartActive     = 0x8
    DisableFadeIn     = 0x10
    FadeOutAndNoLoop  = 0x20

@unique
class KeyMarkerType(IntEnum):
    Default              = 0
    LeftFoot             = 1
    RightFoot            = 2
    Attack               = 3
    Swing                = 4
    SwingFinish          = 5
    SwimLeft             = 6
    Tread                = 7 # Water treading
    RunLeftFoot          = 8
    RunRightFoot         = 9
    Died                 = 10
    Jump                 = 11
    JumpUp               = 12
    SwimRight            = 13
    Duck                 = 14
    Climb                = 15
    Activate             = 16
    Crawl                = 17 # maybe crouch
    RunJumpLand          = 18
    ActivateRightArm     = 19
    ActivateRightArmRest = 20
    PlaceRightArm        = 21
    PlaceRightArmRest    = 22
    ReachRightArm        = 23
    ReachRightArmRest    = 24
    Pickup               = 25
    Drop                 = 26
    Move                 = 27
    InventoryPull        = 28
    InventoryPut         = 29
    AttackFinish         = 30
    TurnOff              = 31
    Row                  = 32
    RowFinish            = 33
    LeftHand             = 34 # ijim snd climbhandleft
    RightHand            = 35 # ijim snd climbhandright

@unique
class KeyframeFlag(IntEnum):
    NoChange          = 0,
    PositionChange    = 1,
    OrientationChange = 2,
    AllChange         = 3

class KeyMarker:
    def __init__(self):
        self.f : float = 0.0
        self.t : KeyMarkerType = KeyMarkerType.Default

    @property
    def frame(self) -> float:
        return self.f

    @frame.setter
    def frame(self, frame: float):
        self.f = frame

    @property
    def type(self) -> KeyMarkerType:
        return self.t

    @type.setter
    def type(self, type: KeyMarkerType):
        self.t = type


class Keyframe:
    def __init__(self):
        self.f: KeyframeFlag = KeyframeFlag.NoChange
        self.frme : int      = 0
        self.pos: Vector3f   = Vector3f(0.0, 0.0, 0.0) # x,y,z
        self.orien: Vector3f = Vector3f(0.0, 0.0, 0.0) # pitch, yaw, roll:
        self.dpos: Vector3f  = Vector3f(0.0, 0.0, 0.0) # x,y,z
        self.drot: Vector3f  = Vector3f(0.0, 0.0, 0.0) # pitch, yaw, roll:

    @property
    def flags(self) -> KeyframeFlag:
        return self.f

    @flags.setter
    def flags(self, flags: KeyframeFlag):
        self.f = flags

    @property
    def frame(self) -> int:
        return self.frme

    @frame.setter
    def frame(self, frame: int):
        self.frme = frame

    @property
    def position(self) -> Vector3f:
        return self.pos

    @position.setter
    def position(self, pos: Vector3f):
        self.pos = pos

    @property
    def orientation(self) -> Vector3f:
        return self.orien

    @orientation.setter
    def orientation(self, orien: Vector3f):
        self.orien = orien

    @property
    def deltaPosition(self) -> Vector3f:
        return self.dpos

    @deltaPosition.setter
    def deltaPosition(self, dpos: Vector3f):
        self.dpos = dpos

    @property
    def deltaRotation(self) -> Vector3f:
        return self.drot

    @deltaRotation.setter
    def deltaRotation(self, drot: Vector3f):
        self.drot = drot

class KeyNode:
    def __init__(self):
        self.n : int = 0
        self.mesh_name : str = ""
        self.kfs : List[Keyframe] = []

    @property
    def idx(self) -> int:
        return self.n

    @idx.setter
    def idx(self, idx: int):
        self.n = idx

    @property
    def meshName(self) -> str:
        return self.mesh_name

    @meshName.setter
    def meshName(self, mesh_name: str):
        self.mesh_name = mesh_name

    @property
    def keyframes(self) -> str:
        return self.kfs

    @keyframes.setter
    def keyframes(self, keyframes: List[Keyframe]):
        self.kfs = keyframes

class Key:
    def __init__(self, name: str):
        self.n = name
        self.f: KeyFlag = KeyFlag.Loop
        self.t: Mesh3doNodeType = Mesh3doNodeType.Nothing
        self.frames: int = 0
        self.nfps: float = 0.0
        self.joints: int = 0

        self.m : List[KeyMarker] = []
        self.n : List[KeyNode]   = []

    @property
    def name(self) -> str:
        return self.n

    @name.setter
    def name(self, name: str):
        self.n = name

    @property
    def flags(self) -> KeyFlag:
        return self.f

    @flags.setter
    def flags(self, flags: KeyFlag):
        self.f = flags

    @property
    def nodeTypes(self) -> Mesh3doNodeType:
        """ Returns high animation priority node types """
        return self.t

    @nodeTypes.setter
    def nodeTypes(self, type: Mesh3doNodeType):
        """ Sets high animation priority node types """
        self.t = type

    @property
    def numFrames(self) -> int:
        return self.frames

    @numFrames.setter
    def numFrames(self, numFrames: int):
        self.frames = numFrames

    @property
    def numJoints(self) -> int:
        return self.joints

    @numJoints.setter
    def numJoints(self, numJoints: int):
        self.joints = numJoints

    @property
    def fps(self) -> float:
        return self.nfps

    @fps.setter
    def fps(self, fps: float):
        self.nfps = fps

    @property
    def markers(self) -> List[KeyMarker]:
        return self.m

    @markers.setter
    def markers(self, markers: List[KeyMarker]):
        self.m = markers

    @property
    def nodes(self) -> List[KeyNode]:
        return self.n

    @nodes.setter
    def nodes(self, nodes: List[KeyNode]):
        self.n = nodes
