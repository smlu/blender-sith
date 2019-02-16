from typing import NamedTuple

class Vector2f(NamedTuple):
    x: float
    y: float

    def __repr__(self) -> str:
        return f'<Vector2f ({self.x}, {self.y})>'

class Vector3f(NamedTuple):
    x: float
    y: float
    z: float

    def __repr__(self) -> str:
        return f'<Vector3f ({self.x}, {self.y}, {self.z})>'

class Vector4f(NamedTuple):
    x: float
    y: float
    z: float
    w: float

    def __repr__(self) -> str:
        return f'<Vector4f ({self.x}, {self.y}, {self.z}, {self.w})>'
