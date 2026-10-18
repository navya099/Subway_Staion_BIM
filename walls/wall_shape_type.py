from enum import Enum


class WallShapeType(Enum):
    """
    벽체 타입 정의
    """
    RECTANGLE = 0
    ARC = 1
    POLYGON = 2
    ETC = -1
