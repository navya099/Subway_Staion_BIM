from enum import Enum


class VentPartKind(Enum):
    """환기구 구성 부재"""
    FLOOR = "FLOOR"            # 덕트 바닥 슬래브
    ROOF = "ROOF"              # 덕트 천장 슬래브 (상부 헌치 포함)
    WALL = "WALL"              # 덕트 바깥 벽 (좌·우)
    MID_WALL = "MID_WALL"      # 칸 사이 중벽
    END_WALL = "END_WALL"      # 수직구 쪽 덕트 끝을 막는 벽
    SHAFT_WALL = "SHAFT_WALL"  # 수직구 벽 (앞·뒤·좌·우·중벽)
    GRILL = "GRILL"            # 끝 금속 그릴 (칸마다)
