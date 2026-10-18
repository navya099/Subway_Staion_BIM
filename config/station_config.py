import dataclasses

@dataclasses.dataclass
class StationParameters:
    """정거장 제원 데이터 클래스"""
    length: float = 200.0          # L (m)
    width: float = 20.0            # W (m)
    offset: float = 0.0           # 선형~바닥 상단 오프셋 (m)
    height: float = 12.0           # 내부 높이 H (m)
    floors: int = 3                # 층수
    wall_t: float = 1           # 외벽 두께 (m)
    floor_t: float = 1.2          # 바닥 슬래브 두께 (m)
    slab_t: float = 0.4            # 천장/중간 슬래브 두께 (m)