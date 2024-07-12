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

from enum import IntEnum, unique
from typing import List
from sith.model import Mesh3doNodeType
from sith.types import Flag, Vector3f

@unique
class KeyFlag(Flag):
    Loop                   = 0x0
    MovementControlled     = 0x1
    NoLoop                 = 0x2
    PauseOnLastFrame       = 0x4
    RestartActive          = 0x8
    DisableFadeIn          = 0x10
    FadeOutAndNoLoop       = 0x20
    SetPositionToLastFrame = 0x40 # (IJIM) Set position of animated object to last frame when animation is finished

@unique
class KeyMarkerType(IntEnum):
    Finished             = 0 # Marker 0 denotes the end of the animation
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
    NoChange          = 0
    PositionChange    = 1
    OrientationChange = 2
    AllChange         = 3

class KeyMarker:
    def __init__(self):
        self._frame : float = 0.0
        self._type : KeyMarkerType = KeyMarkerType.Finished

    @property
    def frame(self) -> float:
        return self._frame

    @frame.setter
    def frame(self, frame: float):
        self._frame = frame

    @property
    def type(self) -> KeyMarkerType:
        return self._type

    @type.setter
    def type(self, type: KeyMarkerType):
        self._type = type

class Keyframe:
    def __init__(self):
        self._flags: KeyframeFlag = KeyframeFlag.NoChange
        self._frame : int      = 0
        self._pos: Vector3f    = Vector3f(0.0, 0.0, 0.0) # x,y,z
        self._orient: Vector3f = Vector3f(0.0, 0.0, 0.0) # pitch, yaw, roll:
        self._dpos: Vector3f   = Vector3f(0.0, 0.0, 0.0) # x,y,z
        self._drot: Vector3f   = Vector3f(0.0, 0.0, 0.0) # pitch, yaw, roll:

    @property
    def flags(self) -> KeyframeFlag:
        return self._flags

    @flags.setter
    def flags(self, flags: KeyframeFlag):
        self._flags = flags

    @property
    def frame(self) -> int:
        return self._frame

    @frame.setter
    def frame(self, frame: int):
        self._frame = frame

    @property
    def position(self) -> Vector3f:
        return self._pos

    @position.setter
    def position(self, pos: Vector3f):
        self._pos = pos

    @property
    def orientation(self) -> Vector3f:
        return self._orient

    @orientation.setter
    def orientation(self, orien: Vector3f):
        self._orient = orien

    @property
    def deltaPosition(self) -> Vector3f:
        return self._dpos

    @deltaPosition.setter
    def deltaPosition(self, dpos: Vector3f):
        self._dpos = dpos

    @property
    def deltaRotation(self) -> Vector3f:
        return self._drot

    @deltaRotation.setter
    def deltaRotation(self, drot: Vector3f):
        self._drot = drot

class KeyNode:
    def __init__(self):
        self._idx : int = 0
        self._meshName : str = ""
        self._kfs : List[Keyframe] = []

    @property
    def idx(self) -> int:
        return self._idx

    @idx.setter
    def idx(self, idx: int):
        self._idx = idx

    @property
    def meshName(self) -> str:
        return self._meshName

    @meshName.setter
    def meshName(self, meshName: str):
        self._meshName = meshName

    @property
    def keyframes(self) -> List[Keyframe]:
        return self._kfs

    @keyframes.setter
    def keyframes(self, keyframes: List[Keyframe]):
        self._kfs = keyframes

class Key:
    def __init__(self, name: str):
        self._name = name
        self._flags: KeyFlag = KeyFlag.Loop
        self._types: Mesh3doNodeType = Mesh3doNodeType.Nothing
        self._numFrames: int = 0
        self._fps: float = 0.0
        self._numJoints: int = 0

        self._markers : List[KeyMarker] = []
        self._nodes   : List[KeyNode]   = []

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, name: str):
        self._name = name

    @property
    def flags(self) -> KeyFlag:
        return self._flags

    @flags.setter
    def flags(self, flags: KeyFlag):
        self._flags = flags

    @property
    def nodeTypes(self) -> Mesh3doNodeType:
        """ Returns high animation priority node types """
        return self._types

    @nodeTypes.setter
    def nodeTypes(self, type: Mesh3doNodeType):
        """ Sets high animation priority node types """
        self._types = type

    @property
    def numFrames(self) -> int:
        return self._numFrames

    @numFrames.setter
    def numFrames(self, numFrames: int):
        self._numFrames = numFrames

    @property
    def numJoints(self) -> int:
        return self._numJoints

    @numJoints.setter
    def numJoints(self, numJoints: int):
        self._numJoints = numJoints

    @property
    def fps(self) -> float:
        return self._fps

    @fps.setter
    def fps(self, fps: float):
        self._fps = fps

    @property
    def markers(self) -> List[KeyMarker]:
        return self._markers

    @markers.setter
    def markers(self, markers: List[KeyMarker]):
        self._markers = markers

    @property
    def nodes(self) -> List[KeyNode]:
        return self._nodes

    @nodes.setter
    def nodes(self, nodes: List[KeyNode]):
        self._nodes = nodes
