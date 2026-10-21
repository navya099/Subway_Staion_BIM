from enum import Enum


class PlatformType(Enum):
    """승강장 설치 타입"""
    NORMAL = 0
    ISLAND = 1


class PlatformSide(Enum):
    """상대식 승강장의 좌/우 구분 (선형 진행방향 기준, 하선측 = 좌측)"""
    LEFT = 0
    RIGHT = 1


class PlatformPart(Enum):
    """승강장(ㅠ형) 구성 부재"""
    SLAB = 0           # 상부 슬래브
    SUPPORT_WALL = 1   # 슬래브를 받치는 지지벽체 (다리)
