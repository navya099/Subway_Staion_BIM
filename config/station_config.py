import dataclasses

@dataclasses.dataclass
class StationParameters:
    """정거장 제원 데이터 클래스
    Attributes:
        start_station: 시작 측점
        length: 길이
        width: 폭
        offset: FL과 바닥 슬래브 OFFSET
        height: 내부 높이 H (m)
        floors: 층수
        wall_t: 외벽 두께 (m)
        floor_t: 바닥 슬래브 두께 (m)
        slab_t: 천장/중간 슬래브 두께 (m)
    """
    start_station: float = 0.0
    length: float = 200.0          # L (m)
    width: float = 20.0            # W (m)
    offset: float = 0.0           # 선형~바닥 상단 오프셋 (m)
    height: float = 12.0           # 내부 높이 H (m)
    floors: int = 3               # 층수
    wall_t: float = 1           # 외벽 두께 (m)
    floor_t: float = 1.2          # 바닥 슬래브 두께 (m)
    slab_t: float = 0.4            # 천장/중간 슬래브 두께 (m)
    sta_tick: float = 20.0         # 평면도 측점 표기 간격 (m)