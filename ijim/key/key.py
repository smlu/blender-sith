from enum import IntEnum, unique
from typing import Tuple, List
from ijim.types.vector import *

@unique
class KeyFlag(IntEnum):
    Loop                = 0x0
    PauseOnFirstFrame   = 0x1
    NoLoop              = 0x2
    PauseOnLastFrame    = 0x4
    RestartIfPlaying    = 0x8
    FinishInGivenTime   = 0x10
    EndSmoothly         = 0x20

@unique
class KeyType(IntEnum):
    Unknown   = 0x0000
    Unknown1  = 0x000F    #0so_armsmid_3_3.key
    Unknown2  = 0x0104    #in_attack_put_gun.key
    Unknown3  = 0x010D    #in_attack_put_whip.key, in_attack_put_machete.key
    Unknown4  = 0x018F    #in_attack_unaim_rifle.key, in_attack_unaim_shotgun.key, in_attack_put_imp.key
    Unknown5  = 0x04FB    #in_activate_medium_left.key
    Unknown6  = 0x0904    #in_attack_pull_whip.key, in_attack_pull_satchel.key, in_attack_pull_imp.key
    Unknown7  = 0x0986    #in_attack_pull_rifle.key
    Unknown8  = 0x090D    #in_attack_pull_machete.key
    Unknown9  = 0x098F    #in_attack_pull_fists.key
    Unknown10 = 0xFFFF

@unique
class KeyMarkerType(IntEnum):
    Invalid                  = -1
    LeftFootstep             = 1
    RightFootstep            = 2
    AttackFire               = 3
    WhipSwing                = 4
    SaberUnknown2            = 5
    SwimLeft                 = 6
    LeftRunFootstep          = 8
    RightRunFootstep         = 9
    Died                     = 10
    Jump                     = 11
    SwimRight                = 13
    Climb                    = 15
    Activate                 = 16
    Crawl                    = 17
    RunJumpLand              = 18
    RightArmPickup           = 19
    RightArmPickupRest       = 20
    RightArmPlace            = 21
    RightArmPlaceRest        = 22
    RightArmReach            = 23
    RightArmReachRest        = 24
    Pickup                   = 25
    Drop                     = 26
    Pull                     = 27
    InventoryPull            = 28
    InventoryPut             = 29
    AttackFireFinish         = 30
    TurnOff                  = 31
    MoveLeftSide             = 34
    MoveRightSide            = 35

@unique
class KeyframeFlag(IntEnum):
    NoChange          = 0,
    PositionChange    = 1,
    OrientationChange = 2,
    AllChange         = 3


class KeyMarker:
    def __init__(self):
        self.f : float = 0.0
        self.t : KeyMarkerType = KeyMarkerType.Invalid

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
        self.frme : int = 0
        self.pos: Vector3f = [] # x,y,z
        self.orien: Vector3f = [] # pitch, yaw, roll:
        self.dpos: Vector3f = [] # x,y,z
        self.drot: Vector3f = [] # pitch, yaw, roll:

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
    def num(self) -> int:
        return self.n

    @num.setter
    def num(self, num: int):
        self.n = num

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
        self.t: KeyType = KeyType.Unknown
        self.frames: int = 0
        self.nfps: float  = 0.0
        self.joints: int = 0

        self.m : List[KeyMarker] = []
        self.n : List[KeyNode] = []

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
    def type(self) -> KeyType:
        return self.t

    @type.setter
    def type(self, type: KeyType):
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




