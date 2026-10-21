from enum import Enum


class WallShapeType(Enum):
    """
    벽체 타입 정의
    """
    RECTANGLE = 0
    ARC = 1
    POLYGON = 2
    ETC = -1


class WallRole(Enum):
    """벽체 위치 역할 (정거장 진행방향 기준)"""
    START = 0   # 시점 마감벽
    END = 1     # 종점 마감벽
    LEFT = 2    # 좌측 외벽
    RIGHT = 3   # 우측 외벽
