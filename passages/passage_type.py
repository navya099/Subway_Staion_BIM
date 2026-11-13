from enum import Enum


class PassagePartKind(Enum):
    """출구통로 구성 부재"""
    FLOOR = "FLOOR"      # 바닥 슬래브 (하부 헌치 포함)
    ROOF = "ROOF"        # 천장 슬래브 (상부 헌치 포함)
    WALL = "WALL"        # 측벽
