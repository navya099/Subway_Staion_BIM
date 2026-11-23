from enum import Enum


class ElevatorPartKind(Enum):
    """엘리베이터 구성 부재"""
    HOIST_WALL = "HOIST_WALL"    # 승강로 벽 (콘크리트, 정지층 출입구로 조각 분할)
    PIT_SLAB = "PIT_SLAB"        # 피트 바닥 슬래브
    TOP_SLAB = "TOP_SLAB"        # 승강로 천장 슬래브 (오버헤드 위)
    CAR_FLOOR = "CAR_FLOOR"      # 카 바닥판
    CAR_WALL = "CAR_WALL"        # 카 벽 (문 쪽은 문 양옆·위 조각)
    CAR_ROOF = "CAR_ROOF"        # 카 천장
    CAR_DOOR = "CAR_DOOR"        # 카 문 (닫힌 상태)
    PIT_WALL = "PIT_WALL"        # 투시형: RC 피트 둘레 벽
    COLUMN = "COLUMN"            # 투시형: 모서리 강관 기둥
    GIRT = "GIRT"                # 투시형: 가로재 강관
    GLASS = "GLASS"              # 투시형: 승강로 유리
    PANEL = "PANEL"              # 투시형: 천장 위 금속 패널 띠

    @property
    def is_car(self) -> bool:
        return self.name.startswith("CAR_")
